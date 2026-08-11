#!/usr/bin/env python
"""LLM_Model3 Engine B (P4) - build the survivorship-safe permaticker->CIK bridge.

The P4 LLM feature layer needs to key each Sharadar security (permaticker) to its
SEC EDGAR filer (CIK). Sharadar's `tickers` schema has no `cik` column but carries
`secfilings` (a per-permaticker EDGAR URL) from which the CIK is parsed. This
writes a clean, integrity-gated map to data/raw/sharadar/permaticker_cik.parquet,
keyed on permaticker, WITHOUT touching the frozen P3 panel files.

Verified by scripts/probe_sharadar_cik.py (2026-08-11): CIK coverage 99.5% overall,
99.4% among delisted names; 0 permaticker maps to >1 CIK; Lehman/Bear/WaMu/Enron
resolve correctly. IDENTITY KEY is permaticker (never the ticker string).

Fail-loud (Rule 18/19): on any integrity failure it writes permaticker_cik_SUSPECT
.parquet and exits non-zero rather than blessing a bad map. Run on GODZILLA in the
repo .venv (the sandbox is firewalled from the API). Never prints the key.

Usage (Godzilla .venv, from C:\\trading\\LLM_MODEL3):
    python scripts\\build_cik_bridge.py
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "data"))
import sharadar_client as sc  # noqa: E402

RAW = _REPO / "data" / "raw" / "sharadar"
FIELDS = ("permaticker,ticker,name,secfilings,isdelisted,"
          "firstpricedate,lastpricedate")
CIK_RE = re.compile(r"(?i)cik=0*(\d+)")

# integrity thresholds (observed coverage ~99.4-99.5%; gate below with margin)
MIN_COVERAGE = 0.98
MIN_COVERAGE_DELISTED = 0.98


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _present(s: pd.Series) -> pd.Series:
    t = s.astype(str).str.strip().str.lower()
    return s.notna() & ~t.isin(("", "nan", "none", "null"))


def _extract_cik(url) -> str | None:
    if url is None:
        return None
    m = CIK_RE.search(str(url))
    return m.group(1) if m else None   # canonical CIK, no leading zeros


def main() -> None:
    key = sc.load_key()
    print(f"Key loaded (len={len(key)}). Repo: {_REPO}")

    print("\n== PULL: tickers (table=stocks) identity + secfilings ==")
    df, status = sc.paginate("tickers", key, table="stocks", fields=FIELDS)
    if status != "complete":
        sys.exit(f"FAIL: pull status={status!r} - refusing to write a possibly-"
                 f"partial map (Rule 19). Investigate before retrying.")
    if "permaticker" in df.columns:
        df = df.drop_duplicates(subset=["permaticker"]).reset_index(drop=True)
    n = len(df)
    df["cik"] = df["secfilings"].map(_extract_cik)
    delisted = df["isdelisted"].astype(str).str.upper().eq("Y")
    cik_ok = _present(df["cik"])

    cov = float(cik_ok.mean()) if n else 0.0
    cov_del = float(cik_ok[delisted].mean()) if delisted.any() else 0.0
    cik_per_pt = df.loc[cik_ok].groupby("permaticker")["cik"].nunique()
    multi_pt = int((cik_per_pt > 1).sum())

    # ---- integrity (all critical) ----
    checks = [
        ("rows in plausible range 15k-30k", 15000 <= n <= 30000, n),
        ("permaticker present", "permaticker" in df.columns, list(df.columns)),
        ("permaticker unique & non-null",
         "permaticker" in df and df["permaticker"].is_unique and df["permaticker"].notna().all(),
         int(df["permaticker"].isna().sum()) if "permaticker" in df else "n/a"),
        ("cik coverage >= 98% overall", cov >= MIN_COVERAGE, f"{cov*100:.2f}%"),
        ("cik coverage >= 98% among delisted", cov_del >= MIN_COVERAGE_DELISTED, f"{cov_del*100:.2f}%"),
        ("no permaticker maps to >1 cik", multi_pt == 0, multi_pt),
    ]
    print(f"\n  distinct permatickers: {n}  delisted(Y): {int(delisted.sum())}  "
          f"active(N): {int((~delisted).sum())}")
    print(f"  cik coverage: {cov*100:.2f}% overall, {cov_del*100:.2f}% delisted; "
          f"distinct CIKs: {df.loc[cik_ok, 'cik'].nunique()}")
    missing = df[~cik_ok]
    print(f"  no-CIK names (counted, not filled): {len(missing)}")
    for _, r in missing.head(5).iterrows():
        print(f"    - pt={r['permaticker']} tk={r['ticker']} name={str(r['name'])[:40]!r}")
    print("  integrity:")
    for label, ok, detail in checks:
        print(f"    [{'OK ' if ok else 'BAD'}] {label} :: {detail}")
    passed = all(ok for _, ok, _ in checks)

    # keep only the bridge columns; store cik as the canonical integer string
    out_df = df[["permaticker", "ticker", "name", "cik", "secfilings",
                 "isdelisted", "firstpricedate", "lastpricedate"]].copy()

    RAW.mkdir(parents=True, exist_ok=True)
    out = RAW / ("permaticker_cik.parquet" if passed else "permaticker_cik_SUSPECT.parquet")
    out_df.to_parquet(out, index=False)
    meta = {
        "source": "sharadar_direct", "endpoint": "tickers", "filter": "table=stocks",
        "derivation": "cik parsed from secfilings URL via regex (?i)cik=0*(\\d+)",
        "pulled_utc": _now(), "rows": n,
        "cik_coverage_overall": round(cov, 4),
        "cik_coverage_delisted": round(cov_del, 4),
        "distinct_cik": int(df.loc[cik_ok, "cik"].nunique()),
        "permaticker_multi_cik": multi_pt,
        "no_cik_rows": int((~cik_ok).sum()),
        "integrity_pass": passed, "file": out.name,
        "columns": list(out_df.columns),
    }
    (RAW / "_permaticker_cik_metadata.json").write_text(json.dumps(meta, indent=2))
    print(f"\n  wrote {out.relative_to(_REPO)}  ({out.stat().st_size/1e6:.2f} MB)")
    if not passed:
        sys.exit("FAIL: integrity checks failed - wrote permaticker_cik_SUSPECT.parquet, "
                 "not the clean file. Do not build EDGAR ingestion on this.")
    print("  permaticker->CIK bridge OK.")
    print("\n== DONE - paste this whole output back ==")


if __name__ == "__main__":
    main()
