"""P2 step 1 - data-integrity pass over the Engine A ETF lake.

Scans every parquet in data/raw/tiingo_eod/ for the failure modes that make a
backtest silently lie: missing bars, NaNs, bad prices, stale flatlines, and
implausible one-day moves. Run on Godzilla (authoritative data lives there;
the Cowork bash mount can be stale - CLAUDE_PREFLIGHT Rule 24).

Checks per ticker:
  HARD (force non-zero exit - these break a backtest):
    - NaN in any OHLC/adjusted price column
    - non-positive close or adj_close
    - duplicate trading dates
    - dates not sorted ascending
  SOFT (reported for review, do NOT fail the run - often legitimate):
    - business-day gaps > GAP_BDAYS between consecutive bars (halts, holidays, inception edges)
    - |1-day adj_close return| > RET_ABS (possible bad tick or real crash - eyeball it)
    - stale runs: > STALE_RUN identical consecutive adj_close (possible frozen feed)
    - zero-volume days

Usage, in the Godzilla .venv (PowerShell), from C:\\trading\\LLM_MODEL3:
    python scripts\\check_data_integrity.py
"""
import os
import sys

import numpy as np
import pandas as pd

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)
from config.universe import ETF_UNIVERSE  # noqa: E402
from data.tiingo_eod import RAW_DIR  # noqa: E402

PRICE_COLS = ["open", "high", "low", "close", "adj_open", "adj_high", "adj_low", "adj_close"]
GAP_BDAYS = 5        # more than a week of missing business days is suspicious
RET_ABS = 0.40       # a >40% one-day move in an unleveraged ETF is almost surely a data error
STALE_RUN = 4        # >4 identical consecutive adj_close = likely frozen feed


def check_ticker(ticker: str) -> dict:
    path = os.path.join(RAW_DIR, f"{ticker}.parquet")
    if not os.path.exists(path):
        return {"ticker": ticker, "hard": [f"missing parquet at {path}"], "soft": [], "rows": 0}
    df = pd.read_parquet(path)
    hard, soft = [], []

    # HARD
    nan_cols = [c for c in PRICE_COLS if df[c].isna().any()]
    if nan_cols:
        hard.append(f"NaN in {nan_cols}")
    if (df["close"] <= 0).any() or (df["adj_close"] <= 0).any():
        hard.append("non-positive close/adj_close")
    dupes = int(df["date"].duplicated().sum())
    if dupes:
        hard.append(f"{dupes} duplicate dates")
    if not df["date"].is_monotonic_increasing:
        hard.append("dates not sorted ascending")

    # SOFT
    d = df["date"].values.astype("datetime64[D]")
    if len(d) > 1:
        gaps = np.busday_count(d[:-1], d[1:])
        big = np.where(gaps > GAP_BDAYS)[0]
        if len(big):
            worst = sorted(((int(gaps[i]), str(d[i]), str(d[i + 1])) for i in big), reverse=True)[:3]
            soft.append(f"{len(big)} gap(s) > {GAP_BDAYS} bdays (worst: " +
                        "; ".join(f"{g}bd {a}->{b}" for g, a, b in worst) + ")")
    ret = df["adj_close"].pct_change(fill_method=None)
    extreme = ret.abs() > RET_ABS
    if extreme.any():
        worst_r = ret[extreme].abs().max()
        soft.append(f"{int(extreme.sum())} day(s) |ret|>{RET_ABS:.0%} (max {worst_r:.0%})")
    same = df["adj_close"].eq(df["adj_close"].shift())
    run = same.groupby((~same).cumsum()).cumsum().max()
    max_run = int(run) if pd.notna(run) else 0
    if max_run > STALE_RUN:
        soft.append(f"stale run of {max_run + 1} identical adj_close")
    zero_vol = int((df["volume"] <= 0).sum())
    if zero_vol:
        soft.append(f"{zero_vol} zero-volume day(s)")

    return {"ticker": ticker, "hard": hard, "soft": soft, "rows": len(df)}


def main() -> None:
    print(f"Data-integrity pass over {RAW_DIR}\n")
    any_hard = False
    soft_total = 0
    for ticker in ETF_UNIVERSE:
        r = check_ticker(ticker)
        status = "FAIL" if r["hard"] else ("warn" if r["soft"] else "ok")
        print(f"  {r['ticker']:<5} {r['rows']:>5} rows  [{status}]")
        for h in r["hard"]:
            print(f"        HARD: {h}")
            any_hard = True
        for s in r["soft"]:
            print(f"        soft: {s}")
        soft_total += len(r["soft"])

    print(f"\nSoft flags (review, not fatal): {soft_total}")
    if any_hard:
        print("RESULT: FAIL - hard integrity problems above must be fixed before building signals.")
        sys.exit(1)
    print("RESULT: PASS - no hard integrity problems. Soft flags are for eyeballing.")


if __name__ == "__main__":
    main()
