#!/usr/bin/env python
"""Sharadar survivorship / delisted-coverage probe (corrected) for LLM_Model3 Engine B.

Probe #1 hit ticker recycling; the first cut of this probe hit two API-mechanics
issues (10000-row cap + wrong slice: unfiltered tickers returns institutional
investors first). Corrected per Sharadar docs:
  - the tickers endpoint takes a `table` filter -> table=stocks = equity master
  - pagination is offset-based: limit (max 10000) + skip

This pulls the full EQUITY universe (table=stocks), counts delisted vs active,
searches known failures by COMPANY NAME (recycling-proof), and pulls a delisted
original's price history.

Run on GODZILLA in the repo .venv only. Never prints the key (Rule 22).

Usage (Godzilla .venv, from C:\\trading\\LLM_MODEL3):
    python scripts\\probe_sharadar_delisted.py
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from probe_sharadar import load_key, fetch  # noqa: E402

NAME_TESTS = {
    "LEHMAN BROTHERS": "Lehman Brothers (2008)",
    "BEAR STEARNS": "Bear Stearns (2008)",
    "SVB FINANCIAL": "SVB Financial (2023)",
    "FIRST REPUBLIC": "First Republic Bank (2023)",
    "SIGNATURE BANK": "Signature Bank (2023)",
    "SEARS HOLDINGS": "Sears Holdings (2018)",
    "WASHINGTON MUTUAL": "Washington Mutual (2008)",
    "ENRON": "Enron (2001)",
    "WORLDCOM": "WorldCom (2002)",
    "COUNTRYWIDE": "Countrywide (2008)",
}
FIELDS = "permaticker,ticker,name,isdelisted,category,exchange,firstpricedate,lastpricedate"
PAGE = 10000
MAXPAGES = 8  # up to 80k rows; equity master is well under this


def hdr(title: str) -> None:
    print(f"\n{'='*70}\n{title}\n{'='*70}")


def pull_all(endpoint: str, key: str, **filt):
    frames, skip = [], 0
    for _ in range(MAXPAGES):
        df = fetch(endpoint, key, limit=PAGE, skip=skip, **filt)
        if df is None:
            print(f"    page skip={skip}: fetch error (see above); stopping")
            break
        n = len(df)
        print(f"    page skip={skip}: rows={n}")
        if n:
            frames.append(df)
        if n < PAGE:
            break
        skip += PAGE
        time.sleep(0.3)
    return pd.concat(frames, ignore_index=True) if frames else None


def main() -> None:
    key = load_key()
    print(f"Key loaded (len={len(key)}).")

    hdr("Equity universe: tickers where table=stocks (paginated)")
    t = pull_all("tickers", key, table="stocks", fields=FIELDS)
    if t is None or not len(t):
        print("  FAIL: no equity tickers returned (see errors above).")
        sys.exit(1)
    t = t.drop_duplicates(subset=["permaticker"]) if "permaticker" in t.columns else t
    print(f"  total distinct equity permatickers: {len(t)}")
    if len(t) >= MAXPAGES * PAGE:
        print("  WARNING: hit MAXPAGES cap; universe may be larger (raise MAXPAGES).")

    hdr("Survivorship: delisted vs active (equity universe)")
    if "isdelisted" in t.columns:
        print(t["isdelisted"].value_counts(dropna=False).to_string())
        n_del = int((t["isdelisted"].astype(str) == "Y").sum())
        print(f"\n  delisted equities (isdelisted=Y): {n_del}")
    if "category" in t.columns:
        print("\n  top categories:")
        print(t["category"].value_counts(dropna=False).head(8).to_string())

    hdr("Known delistings, searched by COMPANY NAME (recycling-proof)")
    up = t["name"].astype(str).str.upper()
    hits = 0
    for sub, label in NAME_TESTS.items():
        m = t[up.str.contains(sub, na=False)]
        if len(m):
            hits += 1
            for _, r in m.head(3).iterrows():
                print(f"  [{label}] permaticker={r.get('permaticker')} ticker={r.get('ticker')} "
                      f"isdelisted={r.get('isdelisted')} last={r.get('lastpricedate')} "
                      f":: {str(r.get('name'))[:45]}")
        else:
            print(f"  [{label}] NO NAME MATCH")
    print(f"\n  name-matched {hits}/{len(NAME_TESTS)} known delistings")

    hdr("Real price history for a delisted original")
    cand = t[up.str.contains("LEHMAN BROTHERS", na=False)]
    if not len(cand):
        cand = t[up.str.contains("SVB FINANCIAL", na=False)]
    if len(cand):
        d = cand[cand["isdelisted"].astype(str) == "Y"] if "isdelisted" in cand.columns else cand
        row = (d if len(d) else cand).iloc[0]
        tk = row.get("ticker")
        print(f"  target: {str(row.get('name'))[:45]} ticker={tk} "
              f"permaticker={row.get('permaticker')} last={row.get('lastpricedate')}")
        px = fetch("stocks", key, ticker=tk, fields="ticker,date,close,volume")
        if px is not None and len(px):
            print(f"  price rows for {tk}: {len(px)}  range={px['date'].min()}..{px['date'].max()}")
        else:
            print(f"  no price rows for {tk} (would investigate keying)")
    else:
        print("  no Lehman/SVB match to pull prices for")

    hdr("DONE - paste this whole output back")


if __name__ == "__main__":
    main()
