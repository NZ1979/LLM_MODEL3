#!/usr/bin/env python
"""Engine B P4 (Spec 2) - run the LLM feature extractor over the EDGAR corpus.

Godzilla .venv ONLY (needs `anthropic` + ANTHROPIC_API_KEY; the sandbox is
firewalled). Reads data/raw/edgar/sections.parquet, masks + truncates each
filing's MD&A / Risk Factors (+ the immediately prior filing's sections for the
change features), calls the extractor (temperature 0, forced JSON, content-hash
cached), and writes the raw per-filing LLM features. Production features are from
MASKED text (Spec 2 sec 4.3); normalisation is applied later, at CV-join time.

PILOT first (operator decision): --pilot-limit bounds the number of filings so
cost and feature sanity can be checked before the full build-span extraction.

  Pilot:
      python scripts\\extract_llm_features.py --model <claude-model-id> --pilot-limit 200

Writes data/raw/edgar/features_llm.parquet and _features_llm_metadata.json.
The masked hindsight-probe / IC-ceiling / lexicon audit (sec 5) runs in the full
step once forward-return labels are joined from the panel; --unmasked-sample here
produces the paired unmasked extractions the probe needs.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import pandas as pd

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from features import edgar_llm_features as elf   # noqa: E402
from data import edgar_ingest as ing             # noqa: E402

DEFAULT_RAW = _REPO / "data" / "raw" / "sharadar"
EDGAR = _REPO / "data" / "raw" / "edgar"


def _sections_by_accession(sec_df: pd.DataFrame) -> pd.DataFrame:
    """One row per accession with mdna/rf text + acceptance ordering keys."""
    piv = (sec_df.pivot_table(index=["permaticker", "cik", "accession", "form",
                                     "acceptance_date", "acceptance_datetime"],
                              columns="section", values="text", aggfunc="first")
                 .reset_index())
    for c in ("mdna", "risk_factors"):
        if c not in piv.columns:
            piv[c] = None
    piv["acceptance_date"] = pd.to_datetime(piv["acceptance_date"])
    return piv.sort_values(["permaticker", "acceptance_date", "accession"])


def _attach_priors(df: pd.DataFrame) -> pd.DataFrame:
    """For each filing, the immediately prior filing's MD&A / Risk Factors (same
    permaticker), used for the change features. Prior = most recent earlier filing
    that HAS that section (NaN change if none) - Spec 2 sec 4.1."""
    df = df.copy()
    df["prior_mdna"] = None
    df["prior_rf"] = None
    for _, g in df.groupby("permaticker", sort=False):
        last_mdna = last_rf = None
        for i in g.index:
            df.at[i, "prior_mdna"] = last_mdna
            df.at[i, "prior_rf"] = last_rf
            cur_mdna = elf._as_text(g.at[i, "mdna"])   # NaN/blank -> None, never a prior
            cur_rf = elf._as_text(g.at[i, "risk_factors"])
            if cur_mdna:
                last_mdna = cur_mdna
            if cur_rf:
                last_rf = cur_rf
    return df


def main() -> None:
    ap = argparse.ArgumentParser(description="Run the LLM feature extractor (Godzilla)")
    ap.add_argument("--model", default=os.environ.get("ANTHROPIC_EXTRACT_MODEL", ""),
                    help="exact Claude model id (recorded in metadata, Spec 2 sec 4.2)")
    ap.add_argument("--raw-dir", default=str(DEFAULT_RAW))
    ap.add_argument("--edgar-dir", default=str(EDGAR))
    ap.add_argument("--pilot-limit", type=int, default=0, help="cap filings for a cost pilot")
    ap.add_argument("--unmasked-sample", type=int, default=0,
                    help="also extract N filings UNMASKED (paired data for the sec-5 probe)")
    ap.add_argument("--sample-seed", type=int, default=20260811)
    args = ap.parse_args()

    if not args.model:
        sys.exit("FAIL: --model (or ANTHROPIC_EXTRACT_MODEL) required and recorded "
                 "(Spec 2 sec 4.2). Do not default a model silently.")

    edgar = Path(args.edgar_dir)
    sec_path = edgar / "sections.parquet"
    if not sec_path.exists():
        sys.exit(f"FAIL: {sec_path} missing - run build_edgar_corpus.py first.")
    sec_df = pd.read_parquet(sec_path)
    bridge = pd.read_parquet(Path(args.raw_dir) / "permaticker_cik.parquet")
    ident = bridge.set_index("permaticker")[["name", "ticker", "cik"]].to_dict("index")

    df = _attach_priors(_sections_by_accession(sec_df))
    if args.pilot_limit:
        df = df.head(args.pilot_limit)
    print(f"filings to extract: {len(df)} ({'PILOT' if args.pilot_limit else 'FULL'}); "
          f"model={args.model}")

    cache = edgar / "llm_cache"
    extractor = elf.AnthropicExtractor(model=args.model, cache_dir=cache)

    rows, trunc_any = [], 0
    for _, r in df.iterrows():
        pid = r["permaticker"]
        ic = ident.get(pid, {})
        name, ticker, cik = ic.get("name"), ic.get("ticker"), ic.get("cik")
        m_mdna, t1 = elf.prepare_for_extraction(r["mdna"], name, ticker, cik)
        m_rf, t2 = elf.prepare_for_extraction(r["risk_factors"], name, ticker, cik)
        p_mdna, _ = elf.prepare_for_extraction(r["prior_mdna"], name, ticker, cik)
        p_rf, _ = elf.prepare_for_extraction(r["prior_rf"], name, ticker, cik)
        feats = extractor.extract(m_mdna, m_rf, p_mdna, p_rf)
        trunc_any += int(t1 or t2)
        rows.append({"permaticker": pid, "cik": r["cik"], "accession": r["accession"],
                     "form": r["form"], "acceptance_date": r["acceptance_date"],
                     "acceptance_datetime": r["acceptance_datetime"],
                     "truncated": bool(t1 or t2), **feats})

    feat_df = pd.DataFrame(rows)
    edgar.mkdir(parents=True, exist_ok=True)
    feat_df.to_parquet(edgar / "features_llm.parquet", index=False)

    # optional paired UNMASKED extractions for the sec-5 masked hindsight-probe
    if args.unmasked_sample:
        samp = df.sample(n=min(args.unmasked_sample, len(df)), random_state=args.sample_seed)
        urows = []
        for _, r in samp.iterrows():
            ic = ident.get(r["permaticker"], {})
            um_mdna, _ = elf.prepare_for_extraction(r["mdna"], mask=False)
            um_rf, _ = elf.prepare_for_extraction(r["risk_factors"], mask=False)
            up_mdna, _ = elf.prepare_for_extraction(r["prior_mdna"], mask=False)
            up_rf, _ = elf.prepare_for_extraction(r["prior_rf"], mask=False)
            uf = extractor.extract(um_mdna, um_rf, up_mdna, up_rf)
            urows.append({"accession": r["accession"], **{f"{k}_unmasked": v for k, v in uf.items()}})
        pd.DataFrame(urows).to_parquet(edgar / "features_llm_unmasked_sample.parquet", index=False)

    meta = {"model": args.model, "prompt_version": elf.PROMPT_VERSION,
            "n_filings": int(len(feat_df)), "api_calls": extractor.calls,
            "cache_hits": extractor.cache_hits, "truncated_filings": int(trunc_any),
            "head_chars": elf.HEAD_CHARS, "tail_chars": elf.TAIL_CHARS,
            "pilot_limit": args.pilot_limit}
    (edgar / "_features_llm_metadata.json").write_text(json.dumps(meta, indent=2))

    print("\n" + "=" * 72)
    print(f"model={args.model}  prompt={elf.PROMPT_VERSION}")
    print(f"filings={len(feat_df)}  api_calls={extractor.calls}  cache_hits={extractor.cache_hits}"
          f"  truncated={trunc_any}")
    print("feature coverage (non-NaN) and mean:")
    for f in elf.FEATURE_COLS:
        s = feat_df[f].dropna()
        cov = len(s) / max(1, len(feat_df))
        print(f"  {f:<24} cov {cov*100:5.1f}%   mean {s.mean():+.3f}" if len(s)
              else f"  {f:<24} cov   0.0%   (all NaN)")
    print(f"  wrote {edgar/'features_llm.parquet'}")
    print("=" * 72)
    print("\n(Pilot: check cost (api_calls), truncation rate, and that coverage/means "
          "look sane. Then the full build-span extraction + the sec-5 audit. Paste this back.)")


if __name__ == "__main__":
    main()
