#!/usr/bin/env python
"""LLM_Model3 Engine B (P4) - derive a permaticker->CIK bridge from Sharadar.

Read-only. STEP A (already confirmed): the Sharadar `tickers` schema has NO `cik`
column but DOES carry `secfilings` (a per-permaticker SEC EDGAR URL), plus `cusips`
and `figi`. The CIK is embedded in the secfilings URL, so the survivorship-safe
bridge is permaticker -> secfilings -> parse CIK. This probe confirms the URL
format, extracts the CIK, and measures coverage (especially for DELISTED names,
the survivorship-critical case).

Prints only; writes nothing (Rule 18). Run on GODZILLA in the repo .venv.

Usage (Godzilla .venv, from C:\\trading\\LLM_MODEL3):
    python scripts\\probe_sharadar_cik.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pandas as pd

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "data"))
import sharadar_client as sc  # noqa: E402

FIELDS = ("permaticker,ticker,name,secfilings,isdelisted,"
          "firstpricedate,lastpricedate")
CIK_RE = re.compile(r"(?i)cik=0*(\d+)")


def _present(s: pd.Series) -> pd.Series:
    t = s.astype(str).str.strip().str.lower()
    return s.notna() & ~t.isin(("", "nan", "none", "null"))


def _extract_cik(url) -> str | None:
    if url is None:
        return None
    m = CIK_RE.search(str(url))
    return m.group(1) if m else None


def main() -> None:
    key = sc.load_key()
    print(f"Key loaded (len={len(key)}). Repo: {_REPO}")

    print("\n== full pull (table=stocks): identity + secfilings + cusips + figi ==")
    df, status = sc.paginate("tickers", key, table="stocks", fields=FIELDS)
    if status != "complete":
        sys.exit(f"FAIL: pull status={status!r} - refusing to judge coverage on a "
                 f"possibly-partial pull (Rule 19).")
    if "permaticker" in df.columns:
        df = df.drop_duplicates(subset=["permaticker"]).reset_index(drop=True)
    n = len(df)
    delisted = df["isdelisted"].astype(str).str.upper().eq("Y")

    # --- show RAW secfilings format for a few names (so we trust the parser) ----
    print("\n  RAW secfilings examples (verify the CIK is in the URL):")
    shown = 0
    for needle in ("LEHMAN", "BEAR STEARNS", "WASHINGTON MUTUAL", "ENRON"):
        hit = df[df["name"].astype(str).str.upper().str.contains(needle, na=False)]
        if len(hit):
            r = hit.iloc[0]
            print(f"    [{needle}] pt={r['permaticker']} tk={r['ticker']} "
                  f"del={r['isdelisted']}")
            print(f"        secfilings = {r['secfilings']!r}")
            shown += 1
    for _, r in df[~delisted].head(2).iterrows():   # a couple of active names too
        print(f"    [ACTIVE] pt={r['permaticker']} tk={r['ticker']}")
        print(f"        secfilings = {r['secfilings']!r}")

    # --- coverage: secfilings populated, CIK parseable --------------------------
    secf_ok = _present(df["secfilings"])
    df["_cik"] = df["secfilings"].map(_extract_cik)
    cik_ok = _present(df["_cik"])

    print(f"\n  distinct permatickers:        {n}")
    print(f"  delisted (Y):                 {int(delisted.sum())}  "
          f"active (N): {int((~delisted).sum())}")
    print(f"  secfilings populated:         {int(secf_ok.sum())}  "
          f"({secf_ok.mean()*100:.1f}%)")
    print(f"  CIK parsed from secfilings:   {int(cik_ok.sum())}  "
          f"({cik_ok.mean()*100:.1f}% of all names)")
    print(f"    - among ACTIVE names:       {(cik_ok[~delisted].mean()*100 if (~delisted).any() else 0):.1f}%")
    print(f"    - among DELISTED names:     {(cik_ok[delisted].mean()*100 if delisted.any() else 0):.1f}%"
          f"   <- the survivorship-critical number")

    # names with secfilings present but no parseable CIK (format we missed)
    miss = df[secf_ok & ~cik_ok]
    print(f"  secfilings present but CIK NOT parsed: {len(miss)}")
    if len(miss):
        for _, r in miss.head(3).iterrows():
            print(f"    e.g. pt={r['permaticker']} secfilings={r['secfilings']!r}")

    # --- identity-join sanity: permaticker<->cik multiplicity -------------------
    j = df.loc[cik_ok, ["permaticker", "_cik"]]
    pt_per_cik = j.groupby("_cik")["permaticker"].nunique()
    cik_per_pt = j.groupby("permaticker")["_cik"].nunique()
    n_multi = int((pt_per_cik > 1).sum())
    print("\n  identity-join sanity (names WITH a parsed cik):")
    print(f"    distinct CIK values:                     {j['_cik'].nunique()}")
    print(f"    CIK shared by >1 permaticker:            {n_multi}  "
          f"(some expected: share classes / re-listings under one filer)")
    print(f"    permaticker with >1 CIK (should be 0):   {int((cik_per_pt > 1).sum())}")
    if n_multi:
        ex = pt_per_cik[pt_per_cik > 1].sort_values(ascending=False).head(5)
        print(f"    top shared-CIK (cik -> #permatickers):   {ex.to_dict()}")

    print("\n  VERDICT: if DELISTED-name CIK coverage is high (>~90%) and no permaticker")
    print("  maps to >1 CIK, a tickers re-pull adding `secfilings` + a parsed `cik`")
    print("  column gives a clean, survivorship-safe permaticker->CIK bridge for EDGAR.")
    print("\n== DONE - paste this whole output back ==")


if __name__ == "__main__":
    main()
