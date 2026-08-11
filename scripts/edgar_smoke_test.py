#!/usr/bin/env python
"""Engine B P4 (Spec 2) - REAL-filing smoke test (Godzilla .venv ONLY).

Validates the LIVE EDGAR path end-to-end on a handful of known CIKs BEFORE any
full corpus build or LLM extraction (docs/ENGINE_B_P4_SPEC2.md sec 6): submissions
traversal (recent + filings.files[]) -> window attribution against the REAL CIK
bridge -> primary-document fetch -> deterministic MD&A / Risk-Factors extraction.
Read-only: prints only, writes nothing, calls NO LLM. The sandbox is firewalled
from EDGAR, so this runs on Godzilla (charter 8).

The parser heuristics (item-header location, TOC skipping, old-.txt SGML) can only
be judged against real, messy filings - that is what this smoke test surfaces.

Usage (Godzilla .venv, from C:\\trading\\LLM_MODEL3):
    python scripts\\edgar_smoke_test.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from data import edgar_ingest as ing              # noqa: E402
from data import edgar_sections as sec            # noqa: E402
from data.edgar_attribution import attribute_filings, AttributionAmbiguityError  # noqa: E402

ENV = _REPO / ".env"
BRIDGE = _REPO / "data" / "raw" / "sharadar" / "permaticker_cik.parquet"

# known CIKs (from the bridge probe) - delisted survivorship cases + one active
PROBE_CIKS = [("LEHMAN BROTHERS", "806085"), ("BEAR STEARNS", "777001"),
              ("WASHINGTON MUTUAL", "933136"), ("KRAFT HEINZ", "1637459")]


def load_contact() -> str:
    if not ENV.exists():
        sys.exit(f"FAIL: .env not found at {ENV}")
    for line in ENV.read_text(encoding="utf-8", errors="replace").splitlines():
        s = line.strip()
        if s.startswith("SEC_EDGAR_CONTACT="):
            v = s.split("=", 1)[1].strip().strip('"').strip("'")
            if v:
                return v
    sys.exit("FAIL: SEC_EDGAR_CONTACT not set in .env (SEC fair-access needs a contact).")


def preview(text, n=160):
    if not text:
        return "None"
    return f"[{len(text)} chars] " + " ".join(text.split())[:n] + "..."


def main() -> None:
    if not BRIDGE.exists():
        sys.exit(f"FAIL: CIK bridge missing at {BRIDGE} (build_cik_bridge.py first).")
    bridge = pd.read_parquet(BRIDGE)
    bridge["cik"] = bridge["cik"].map(ing.canon_cik)
    ua = ing.build_ua(load_contact())
    lim = ing.RateLimiter()
    print(f"UA contact loaded (len ok). Bridge: {len(bridge)} permatickers. "
          f"Probing {len(PROBE_CIKS)} CIKs.\n")

    for label, cik in PROBE_CIKS:
        print("=" * 72)
        print(f"{label}  CIK={cik}")
        try:
            subs = ing.fetch_submissions(cik, ua, lim)
            recent, files = ing.fetch_all_filing_blocks(subs, ua, lim)
        except Exception as e:  # noqa: BLE001 - fail loud with context
            print(f"  ERROR fetching submissions: {type(e).__name__}: {e}")
            continue

        filings = ing.assemble_filing_rows(recent, files, cik=cik)
        n_amend = ing.count_qualifying_amendments(recent, files)
        print(f"  qualifying filings: {len(filings)} "
              f"(10-K*={int(filings.form.map(lambda f: ing.base_form(f).startswith('10-K')).sum())}, "
              f"10-Q*={int(filings.form.map(lambda f: ing.base_form(f).startswith('10-Q')).sum())}); "
              f"/A amendments excluded: {n_amend}")
        if filings.empty:
            print("  (no qualifying filings under this CIK)")
            continue
        print(f"  acceptance_date range: {filings.acceptance_date.min().date()} .. "
              f"{filings.acceptance_date.max().date()}")

        # attribution against the bridge subset for this CIK (the window split)
        sub_bridge = bridge[bridge.cik == ing.canon_cik(cik)]
        try:
            attributed, stats = attribute_filings(filings, sub_bridge)
        except AttributionAmbiguityError as e:
            print(f"  ATTRIBUTION AMBIGUITY (would fail loud in the builder): {e}")
            continue
        print(f"  permatickers on this CIK: {sorted(sub_bridge.permaticker.tolist())}")
        print(f"  attribution: attributed={stats['n_attributed']}, "
              f"unattributed_gap={stats['n_unattributed_gap']}, "
              f"no_cik_in_bridge={stats['n_no_cik_in_bridge']}")
        if not attributed.empty:
            by_pt = attributed.groupby("permaticker").agg(
                n=("accession", "size"),
                first=("acceptance_date", "min"), last=("acceptance_date", "max"))
            for pt, r in by_pt.iterrows():
                print(f"    -> {pt}: {int(r['n'])} filings  {r['first'].date()}..{r['last'].date()}")

        # extract sections for the most-recent and the oldest attributed 10-K
        tens = attributed[attributed.form.map(lambda f: ing.base_form(f).startswith("10-K"))]
        picks = []
        if not tens.empty:
            picks.append(("newest 10-K", tens.loc[tens.acceptance_date.idxmax()]))
            if len(tens) > 1:
                picks.append(("oldest 10-K", tens.loc[tens.acceptance_date.idxmin()]))
        for tag, row in picks:
            url, is_html = ing.doc_fetch_plan(cik, row["accession"], row["primary_document"])
            try:
                raw = ing.fetch_document(url, ua, lim, cache_path=None)
            except Exception as e:  # noqa: BLE001
                print(f"  {tag}: ERROR fetching doc: {type(e).__name__}: {e}")
                continue
            secs = sec.extract_sections(raw, row["form"], is_html=is_html)
            print(f"  {tag} ({row['form']}, acc {row['acceptance_date'].date()}, "
                  f"{'html' if is_html else 'txt'}):")
            print(f"      MD&A: {preview(secs['mdna'])}")
            print(f"      RiskFactors: {preview(secs['risk_factors'])}")

    print("\n" + "=" * 72)
    print("READ: confirm (1) filings attribute to the right permaticker by window")
    print("(WaMu's post-2008 filings must NOT land on WaMu's permaticker), (2) MD&A")
    print("extracts on both modern HTML and old .txt, (3) pre-2006 10-Ks show no Risk")
    print("Factors. If the parser mislocates sections on real filings, fix it BEFORE")
    print("building the full corpus. Writes nothing. == paste this output back ==")


if __name__ == "__main__":
    main()
