#!/usr/bin/env python
"""Engine B P4 (Spec 2) - compare two LLM feature extractions on the SAME filings.

Locks the model choice before the big spend: does a cheaper model (e.g. Haiku 4.5)
agree with the one piloted (Sonnet 4.5)? Reads two features_llm parquets, aligns on
accession, and reports per-feature Spearman agreement + level shift. No API, no
network - runs on Godzilla against the local parquets.

  python scripts\\compare_extractors.py ^
      --a data\\raw\\edgar\\features_llm.parquet        --label-a sonnet ^
      --b data\\raw\\edgar\\features_llm_haiku.parquet  --label-b haiku

Read: a high Spearman per feature means the cheaper model ranks filings the same
way (what rank-IC ultimately cares about), so it is safe to use for the full run.
A low Spearman means the cheaper model disagrees -> use the stronger model.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from features.edgar_llm_features import FEATURE_COLS   # noqa: E402

AGREE_GOOD = 0.70     # per-feature Spearman we'd consider "safe to swap"
AGREE_WEAK = 0.50     # below this on many features -> prefer the stronger model


def main() -> None:
    ap = argparse.ArgumentParser(description="Compare two LLM feature extractions")
    ap.add_argument("--a", required=True, help="features parquet A (e.g. the piloted model)")
    ap.add_argument("--b", required=True, help="features parquet B (e.g. the cheaper model)")
    ap.add_argument("--label-a", default="A")
    ap.add_argument("--label-b", default="B")
    args = ap.parse_args()

    a = pd.read_parquet(args.a)
    b = pd.read_parquet(args.b)
    for name, df in ((args.label_a, a), (args.label_b, b)):
        if "accession" not in df.columns:
            sys.exit(f"FAIL: {name} has no 'accession' column ({args.a if df is a else args.b}).")
    m = a.merge(b, on="accession", suffixes=(f"_{args.label_a}", f"_{args.label_b}"))
    print(f"paired filings: {len(m)}  ({args.label_a} rows {len(a)}, {args.label_b} rows {len(b)})")
    print(f"agreement thresholds: good >= {AGREE_GOOD}, weak < {AGREE_WEAK} (Spearman)\n")

    hdr = f"  {'feature':<24} {'n':>5} {'spearman':>9} {'pearson':>8} " \
          f"{'mean_'+args.label_a:>14} {'mean_'+args.label_b:>14} {'mean|diff|':>10}"
    print(hdr)
    print("  " + "-" * (len(hdr) - 2))
    rows = []
    for f in FEATURE_COLS:
        ca, cb = f"{f}_{args.label_a}", f"{f}_{args.label_b}"
        if ca not in m.columns or cb not in m.columns:
            continue
        xa = pd.to_numeric(m[ca], errors="coerce")
        xb = pd.to_numeric(m[cb], errors="coerce")
        ok = xa.notna() & xb.notna()
        n = int(ok.sum())
        if n >= 5 and xa[ok].nunique() > 1 and xb[ok].nunique() > 1:
            sp = stats.spearmanr(xa[ok], xb[ok]).correlation
            pe = float(np.corrcoef(xa[ok], xb[ok])[0, 1])
        else:
            sp = pe = float("nan")
        ma, mb = float(xa[ok].mean()) if n else float("nan"), float(xb[ok].mean()) if n else float("nan")
        md = float((xa[ok] - xb[ok]).abs().mean()) if n else float("nan")
        rows.append((f, n, sp, pe, ma, mb, md))
        flag = "" if not np.isfinite(sp) else (" OK" if sp >= AGREE_GOOD else ("  weak" if sp < AGREE_WEAK else ""))
        print(f"  {f:<24} {n:>5} {sp:>9.3f} {pe:>8.3f} {ma:>14.3f} {mb:>14.3f} {md:>10.3f}{flag}")

    sps = [r[2] for r in rows if np.isfinite(r[2])]
    if sps:
        med = float(np.median(sps))
        n_good = sum(s >= AGREE_GOOD for s in sps)
        n_weak = sum(s < AGREE_WEAK for s in sps)
        print(f"\n  median Spearman across features: {med:.3f}; "
              f"{n_good}/{len(sps)} >= {AGREE_GOOD}, {n_weak}/{len(sps)} < {AGREE_WEAK}")
        if med >= AGREE_GOOD and n_weak == 0:
            print(f"  VERDICT: '{args.label_b}' tracks '{args.label_a}' well - safe to run the "
                  f"full build on the cheaper model.")
        elif n_weak >= 3 or med < AGREE_WEAK:
            print(f"  VERDICT: '{args.label_b}' diverges on several features - prefer the "
                  f"stronger model for the full build.")
        else:
            print("  VERDICT: mixed - inspect the weak features before deciding.")
    print("\n(No API used. Spearman is what matters - rank agreement drives rank-IC.)")


if __name__ == "__main__":
    main()
