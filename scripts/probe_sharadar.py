#!/usr/bin/env python
"""Sharadar Direct API smoke test for LLM_Model3 Engine B (P3).

PROBE-FIRST: prints the REAL response shape (status, columns, dtypes, sample
rows) rather than asserting guessed field names, then runs targeted checks:

  1. Access + tickers schema
  2. Delisted / survivorship coverage (known failures present, with real history)
  3. Point-in-time fundamentals structure (filing date vs report period lag)
  4. As-reported (AR) vs most-recent (MR) dimensions
  5. Factor-field completeness + null rates
  6. Daily market-cap (universe screen input)
  7. History depth (does the full-history tier actually deliver 1998-era data)

Run on GODZILLA in the repo .venv only (the Cowork sandbox is firewalled from
external market APIs). Reads SHARADAR_API_KEY from .env. NEVER prints the key or
a full URL (Rule 22 - key rides in the query string).

Usage (Godzilla .venv, from C:\\trading\\LLM_MODEL3):
    python scripts\\probe_sharadar.py
"""
from __future__ import annotations

import io
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import pandas as pd

BASE = "https://api.sharadar.com/v1.0/data"
REPO = Path(__file__).resolve().parent.parent
ENV = REPO / ".env"

LIVE = "AAPL"          # long-lived survivor for PIT / field checks
LONG_LIVED = "IBM"     # deep history probe (expect 1998-era rows)
DELISTED = ["LEH", "BSC", "SIVB", "FRC", "SHLD", "BBBY"]  # known delistings

# Factor fields we expect SF1 to carry (checked for presence + null rate, not assumed)
FACTOR_FIELDS = [
    "eps", "epsdil", "revenue", "netinc", "equity", "bvps", "tbvps",
    "roe", "roa", "roic", "netmargin", "grossmargin", "de", "debt",
    "fcf", "ncfo", "marketcap", "pe", "pb", "ps", "ev", "evebitda",
]
FILING_CANDIDATES = ["datekey", "date"]  # filing/PIT date column name varies


def load_key(env_path: Path = ENV) -> str:
    if not env_path.exists():
        sys.exit(f"FAIL: .env not found at {env_path}")
    for line in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
        s = line.strip()
        if s.startswith("SHARADAR_API_KEY="):
            k = s.split("=", 1)[1].strip().strip('"').strip("'")
            if not k:
                sys.exit("FAIL: SHARADAR_API_KEY present but empty in .env")
            return k
    sys.exit("FAIL: SHARADAR_API_KEY not found in .env")


def _safe_url(endpoint: str, params: dict) -> str:
    shown = {k: v for k, v in params.items() if k != "api_key"}
    return f"{BASE}/{endpoint}?{urllib.parse.urlencode(shown)}&api_key=<redacted>"


def fetch(endpoint: str, key: str, **params):
    """Return a DataFrame, or None on error. Prints diagnostics; never leaks key.

    `endpoint` is the API table path (tickers/fundamentals/stocks/daily).
    Sharadar's own `table` filter is passed via **params, so the endpoint arg
    is named `endpoint` to avoid a name collision (e.g. fetch('tickers', key,
    table='stocks')).
    """
    params = {k: v for k, v in params.items() if v is not None}
    params["format"] = "csv"
    query = urllib.parse.urlencode({**params, "api_key": key})
    url = f"{BASE}/{endpoint}?{query}"
    safe = _safe_url(endpoint, params)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "LLM_Model3-probe/1.0"})
        with urllib.request.urlopen(req, timeout=90) as r:
            body = r.read().decode("utf-8", "replace")
            status = getattr(r, "status", 200)
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:500]
        print(f"  HTTP {e.code} :: {safe}\n  body: {detail}")
        return None
    except Exception as e:  # noqa: BLE001 - fail loud with context (Rule 18)
        print(f"  ERROR :: {safe}\n  {type(e).__name__}: {e}")
        return None
    if not body.strip():
        print(f"  EMPTY response (status {status}) :: {safe}")
        return pd.DataFrame()
    try:
        return pd.read_csv(io.StringIO(body))
    except Exception as e:  # noqa: BLE001
        print(f"  CSV PARSE FAIL :: {safe}\n  {type(e).__name__}: {e}\n  head: {body[:300]}")
        return None


def hdr(n: int, title: str) -> None:
    print(f"\n{'='*70}\n[{n}] {title}\n{'='*70}")


def show(df, cols=None, rows=5) -> None:
    if df is None:
        print("  -> no dataframe (see error above)")
        return
    print(f"  shape={df.shape}")
    print(f"  columns ({len(df.columns)}): {list(df.columns)}")
    if len(df):
        sub = df[cols] if cols else df
        with pd.option_context("display.max_columns", None, "display.width", 200):
            print(sub.head(rows).to_string(index=False))


def pick_filing_col(cols) -> str | None:
    for c in FILING_CANDIDATES:
        if c in cols and c not in ("calendardate", "reportperiod"):
            return c
    return None


def main() -> None:
    key = load_key()
    print(f"Key loaded from .env (len={len(key)}). Repo: {REPO}")
    findings = []

    # 1. ACCESS + TICKERS SCHEMA -------------------------------------------
    hdr(1, "Access + tickers schema (AAPL)")
    t = fetch("tickers", key, ticker=LIVE)
    show(t)
    have_isdelisted = t is not None and "isdelisted" in getattr(t, "columns", [])
    findings.append(("API access works", t is not None))
    findings.append(("tickers has isdelisted field", bool(have_isdelisted)))

    # 2. DELISTED / SURVIVORSHIP COVERAGE ----------------------------------
    hdr(2, "Delisted coverage (known failures should be present, isdelisted=Y)")
    found = []
    for tk in DELISTED:
        d = fetch("tickers", key, ticker=tk)
        if d is not None and len(d):
            row = d.iloc[0]
            isdel = row.get("isdelisted", "?")
            last = row.get("lastpricedate", "?")
            name = str(row.get("name", "?"))[:40]
            print(f"  {tk:6s} found | isdelisted={isdel} lastpricedate={last} | {name}")
            found.append(tk)
        else:
            print(f"  {tk:6s} NOT FOUND (try an alternate symbol if this matters)")
    findings.append((f"delisted tickers resolved ({len(found)}/{len(DELISTED)})", len(found) >= 3))

    # Prove one delisted name has REAL history ending at delisting (not a stub)
    hdr("2b", "Delisted price history is real (LEH prices should end ~2008)")
    leh = fetch("stocks", key, ticker="LEH")
    if leh is not None and len(leh) and "date" in leh.columns:
        print(f"  LEH price rows={len(leh)} range={leh['date'].min()}..{leh['date'].max()}")
        findings.append(("LEH has real price history", len(leh) > 100))
    else:
        show(leh)
        findings.append(("LEH has real price history", False))

    # 3. POINT-IN-TIME FUNDAMENTALS STRUCTURE ------------------------------
    hdr(3, "Point-in-time fundamentals (AAPL, dimension=ARQ)")
    f = fetch("fundamentals", key, ticker=LIVE, dimension="ARQ")
    show(f, rows=3)
    if f is not None and len(f):
        fcol = pick_filing_col(f.columns)
        print(f"  filing-date column detected: {fcol!r}; reportperiod present: {'reportperiod' in f.columns}")
        if fcol and "reportperiod" in f.columns:
            a = pd.to_datetime(f[fcol], errors="coerce")
            b = pd.to_datetime(f["reportperiod"], errors="coerce")
            lag = (a - b).dt.days.dropna()
            if len(lag):
                print(f"  filing lag days (filing - reportperiod): "
                      f"min={lag.min()} median={lag.median():.0f} max={lag.max()}")
                print("  sample [reportperiod -> filing]:")
                for _, r in f[[ "reportperiod", fcol]].head(4).iterrows():
                    print(f"    {r['reportperiod']} -> {r[fcol]}")
                pit_ok = lag.median() > 0
                findings.append(("PIT lag positive (filing AFTER period end)", bool(pit_ok)))
            else:
                findings.append(("PIT lag computable", False))
        else:
            findings.append(("filing-date + reportperiod columns present", False))

    # 4. AR vs MR DIMENSIONS ------------------------------------------------
    hdr(4, "As-reported (ARQ) vs most-recent (MRQ) row counts (AAPL)")
    arq = fetch("fundamentals", key, ticker=LIVE, dimension="ARQ", fields="ticker,reportperiod,revenue,eps")
    mrq = fetch("fundamentals", key, ticker=LIVE, dimension="MRQ", fields="ticker,reportperiod,revenue,eps")
    print(f"  ARQ rows={0 if arq is None else len(arq)}  MRQ rows={0 if mrq is None else len(mrq)}")
    findings.append(("both AR and MR dimensions return data",
                     arq is not None and mrq is not None and len(arq) > 0 and len(mrq) > 0))

    # 5. FACTOR-FIELD COMPLETENESS -----------------------------------------
    hdr(5, "Factor-field presence + null rate (AAPL ARQ)")
    if f is not None and len(f):
        present = [c for c in FACTOR_FIELDS if c in f.columns]
        missing = [c for c in FACTOR_FIELDS if c not in f.columns]
        print(f"  present ({len(present)}/{len(FACTOR_FIELDS)}): {present}")
        print(f"  missing: {missing}")
        if present:
            nn = (f[present].notna().mean() * 100).round(1)
            print("  non-null % per field:")
            print(nn.to_string())
        findings.append((f"core factor fields present ({len(present)}/{len(FACTOR_FIELDS)})",
                         len(present) >= 12))
    else:
        findings.append(("core factor fields present", False))

    # 6. DAILY MARKET-CAP (universe screen input) --------------------------
    hdr(6, "Daily metrics / market-cap (AAPL)")
    day = fetch("daily", key, ticker=LIVE)
    show(day, rows=3)
    findings.append(("daily table has marketcap",
                     day is not None and "marketcap" in getattr(day, "columns", [])))

    # 7. HISTORY DEPTH ------------------------------------------------------
    hdr(7, "History depth (IBM ARQ 1998-1999 should return rows on full-history tier)")
    deep = fetch("fundamentals", key, ticker=LONG_LIVED, dimension="ARQ",
                 **{"from": "1998-01-01", "to": "1999-12-31"},
                 fields="ticker,reportperiod,revenue,eps")
    if deep is not None and len(deep):
        print(f"  IBM 1998-99 rows={len(deep)} reportperiods={list(deep['reportperiod'])}")
    else:
        show(deep)
    findings.append(("full-history tier delivers 1998-era data",
                     deep is not None and len(deep) > 0))

    # SUMMARY ---------------------------------------------------------------
    hdr("*", "SUMMARY (observations, not a verdict - operator interprets)")
    for label, ok in findings:
        print(f"  [{'PASS' if ok else 'CHECK'}] {label}")
    n_ok = sum(1 for _, ok in findings if ok)
    print(f"\n  {n_ok}/{len(findings)} checks look good. Paste this whole output back.")


if __name__ == "__main__":
    main()
