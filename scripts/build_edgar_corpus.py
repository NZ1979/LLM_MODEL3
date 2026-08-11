#!/usr/bin/env python
"""Engine B P4 (Spec 2) - build the EDGAR text corpus (Godzilla .venv ONLY).

Fetch -> window-attribute -> deterministic section extraction, over the eligible
universe, writing the frozen corpus (docs/ENGINE_B_P4_SPEC2.md sec 1-2). Sandbox
is firewalled from EDGAR (charter 8); run on Godzilla. Every raw document is cached
(gitignored) so re-runs are free and reproducible. Fail loud, show denominators.

PILOT (operator decision 2026-08-11): validate cost + plumbing on a small sample
first, before the full 1998-2020 build.

  Pilot (a seeded sample of names, no panel build needed):
      python scripts\\build_edgar_corpus.py --span build --pilot-permatickers 150

  Full build universe (screens the panel for eligible names - heavy):
      python scripts\\build_edgar_corpus.py --span build

Writes: data/raw/edgar/filings_index.parquet, .../sections.parquet, cached docs
under data/raw/edgar/docs/. Prints the coverage funnel (Rule 18).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from data import edgar_ingest as ing               # noqa: E402
from data import edgar_sections as sec             # noqa: E402
from data.edgar_attribution import attribute_filings, AttributionAmbiguityError  # noqa: E402

ENV = _REPO / ".env"
DEFAULT_RAW = _REPO / "data" / "raw" / "sharadar"
DEFAULT_OUT = _REPO / "data" / "raw" / "edgar"
SPANS = {"build": ("1998-01-01", "2020-12-31"), "holdout": ("2021-01-01", "2026-12-31")}


def load_contact() -> str:
    if not ENV.exists():
        sys.exit(f"FAIL: .env not found at {ENV}")
    for line in ENV.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.strip().startswith("SEC_EDGAR_CONTACT="):
            v = line.split("=", 1)[1].strip().strip('"').strip("'")
            if v:
                return v
    sys.exit("FAIL: SEC_EDGAR_CONTACT not set in .env (SEC fair-access needs a contact).")


def target_permatickers(bridge, raw_dir, span, pilot_n, seed):
    """Pilot: a seeded sample of names whose price window overlaps the span.
    Full: the eligible universe from the panel screen (heavy - builds the panel)."""
    b = bridge.copy()
    b["firstpricedate"] = pd.to_datetime(b["firstpricedate"], errors="coerce")
    b["lastpricedate"] = pd.to_datetime(b["lastpricedate"], errors="coerce")
    s0, s1 = pd.Timestamp(span[0]), pd.Timestamp(span[1])
    overlap = b[(b["firstpricedate"] <= s1) & (b["lastpricedate"] >= s0)
                & b["cik"].map(lambda c: ing.canon_cik(c) != "")]
    if pilot_n:
        n = min(pilot_n, len(overlap))
        return set(overlap.sample(n=n, random_state=seed)["permaticker"])
    # FULL: screen the panel for the eligible universe (import here to avoid the
    # heavy panel build in pilot mode)
    from data import sharadar_panel as sp
    from models import engine_b_universe as ebu
    print("Full build: assembling PIT panel + universe screen (heavy)...")
    built = sp.build_panel_from_parquet(str(raw_dir), span[0], span[1], verbose=True)
    screened = ebu.screen(built)
    elig = screened[screened["eligible"]]
    return set(elig["permaticker"].unique())


def main() -> None:
    ap = argparse.ArgumentParser(description="Build the EDGAR text corpus (Godzilla)")
    ap.add_argument("--span", choices=list(SPANS), required=True)
    ap.add_argument("--raw-dir", default=str(DEFAULT_RAW))
    ap.add_argument("--out-dir", default=str(DEFAULT_OUT))
    ap.add_argument("--pilot-permatickers", type=int, default=0,
                    help="sample N names for a pilot (skips the full panel screen)")
    ap.add_argument("--pilot-seed", type=int, default=20260811)
    args = ap.parse_args()

    span = SPANS[args.span]
    out = Path(args.out_dir)
    docs_dir = out / "docs"
    bridge_path = Path(args.raw_dir) / "permaticker_cik.parquet"
    if not bridge_path.exists():
        sys.exit(f"FAIL: CIK bridge missing at {bridge_path} (build_cik_bridge.py first).")
    bridge = pd.read_parquet(bridge_path)
    bridge["cik"] = bridge["cik"].map(ing.canon_cik)
    ua = ing.build_ua(load_contact())
    lim = ing.RateLimiter()

    targets = target_permatickers(bridge, Path(args.raw_dir), span,
                                  args.pilot_permatickers, args.pilot_seed)
    tgt_bridge = bridge[bridge["permaticker"].isin(targets)]
    ciks = sorted({c for c in tgt_bridge["cik"] if c})
    print(f"span {args.span} {span}; target names: {len(targets)} "
          f"({'PILOT' if args.pilot_permatickers else 'FULL'}); distinct CIKs: {len(ciks)}")
    print(f"names with no CIK (dropped, counted): {len(targets) - tgt_bridge['cik'].map(bool).sum()}")

    idx_rows, sec_rows = [], []
    funnel = {"ciks": len(ciks), "ciks_fetched": 0, "ambiguous_ciks": 0,
              "filings_attributed": 0, "docs_fetched": 0, "doc_fetch_errors": 0,
              "mdna_found": 0, "rf_found": 0, "rf_pre2006_none": 0, "section_not_found": 0}
    s1 = pd.Timestamp(span[1])

    for i, cik in enumerate(ciks, 1):
        try:
            subs = ing.fetch_submissions(cik, ua, lim)
            recent, files = ing.fetch_all_filing_blocks(subs, ua, lim)
        except Exception as e:  # noqa: BLE001 - fail loud, continue corpus
            print(f"  [{i}/{len(ciks)}] CIK {cik}: submissions fetch ERROR {type(e).__name__}: {e}")
            continue
        funnel["ciks_fetched"] += 1
        filings = ing.assemble_filing_rows(recent, files, cik=cik)
        if filings.empty:
            continue
        cik_bridge = bridge[bridge["cik"] == cik]      # ALL permatickers on this CIK
        try:
            attributed, _ = attribute_filings(filings, cik_bridge)
        except AttributionAmbiguityError as e:
            funnel["ambiguous_ciks"] += 1
            print(f"  [{i}/{len(ciks)}] CIK {cik}: AMBIGUOUS - skipped (not grafted): {e}")
            continue
        # keep only target names, filings knowable by span end (priors incl.)
        keep = attributed[attributed["permaticker"].isin(targets)
                          & (pd.to_datetime(attributed["acceptance_date"]) <= s1)]
        for _, r in keep.iterrows():
            acc_nodash = str(r["accession"]).replace("-", "")
            urls, is_html = ing.doc_fetch_plan(cik, r["accession"], r["primary_document"])
            ext = "htm" if is_html else "txt"
            cache = docs_dir / str(cik) / f"{acc_nodash}.{ext}"
            try:
                raw = ing.fetch_document(urls, ua, lim, cache_path=cache)
            except Exception as e:  # noqa: BLE001
                funnel["doc_fetch_errors"] += 1
                print(f"      doc ERROR {r['form']} {r['accession']}: {type(e).__name__}: {e}")
                continue
            funnel["docs_fetched"] += 1
            funnel["filings_attributed"] += 1
            secs = sec.extract_sections(raw, r["form"], is_html=is_html)
            yr = pd.to_datetime(r["acceptance_date"]).year
            idx_rows.append({
                "permaticker": r["permaticker"], "cik": cik, "accession": r["accession"],
                "form": r["form"], "is_amendment": bool(r["is_amendment"]),
                "filing_date": r["filing_date"], "acceptance_datetime": r["acceptance_datetime"],
                "acceptance_date": r["acceptance_date"], "report_date": r["report_date"],
                "primary_document": r["primary_document"], "is_html": is_html,
                "mdna_chars": len(secs["mdna"]) if secs["mdna"] else 0,
                "rf_chars": len(secs["risk_factors"]) if secs["risk_factors"] else 0,
            })
            for name, txt in (("mdna", secs["mdna"]), ("risk_factors", secs["risk_factors"])):
                sec_rows.append({
                    "permaticker": r["permaticker"], "cik": cik, "accession": r["accession"],
                    "form": r["form"], "acceptance_datetime": r["acceptance_datetime"],
                    "acceptance_date": r["acceptance_date"], "section": name,
                    "char_len": len(txt) if txt else 0,
                    "extraction_status": "ok" if txt else "not_found",
                    "text": txt if txt else None,
                })
            if secs["mdna"]:
                funnel["mdna_found"] += 1
            if secs["risk_factors"]:
                funnel["rf_found"] += 1
            elif yr < 2006:
                funnel["rf_pre2006_none"] += 1
            else:
                funnel["section_not_found"] += 1

    out.mkdir(parents=True, exist_ok=True)
    idx_df = pd.DataFrame(idx_rows)
    sec_df = pd.DataFrame(sec_rows)
    idx_df.to_parquet(out / "filings_index.parquet", index=False)
    sec_df.to_parquet(out / "sections.parquet", index=False)

    print("\n" + "=" * 72)
    print("COVERAGE FUNNEL (Rule 18):")
    for k, v in funnel.items():
        print(f"  {k:<22} {v}")
    print(f"  filings_index rows: {len(idx_df)}; sections rows: {len(sec_df)}")
    print(f"  wrote {out/'filings_index.parquet'} and {out/'sections.parquet'}")
    print("=" * 72)
    print("\n(Corpus is gitignored data. Next: scripts/extract_llm_features.py "
          "for the LLM feature layer. Paste this funnel back.)")


if __name__ == "__main__":
    main()
