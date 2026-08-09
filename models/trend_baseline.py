"""Engine A mechanical trend baseline - the leak-free-harness proof (P2).

Deliberately simple, parameter-light time-series momentum. No ML, no fitting,
so there is nothing to overfit and the ONLY way it can look too good is a
leakage bug in the pipeline. That is the point: trend following is the most
replicated edge in quant, so a correct harness should reproduce a MODEST
positive net Sharpe here. A suspiciously high Sharpe means the harness leaks and
must be fixed before any Engine A variant (or Engine B) is trusted.

Signal (per ETF, each day, using only trailing data):
  multi-timeframe time-series momentum = average of sign(total return) over
  3, 6, and 12 months. Score in {-1, -1/3, +1/3, +1}.

Sizing:
  volatility targeting - each position scaled to TARGET_VOL annual using trailing
  realized vol (inverse-vol => risk-parity-ish across the basket), capped at MAX_LEG.
  Sharpe is leverage-invariant pre-cost, so the vol-target LEVEL does not change
  the leak verdict; it just sets the scale.

Leakage guards:
  - momentum and vol use only data up to day t
  - positions rebalanced weekly, then LAGGED one day before returns are applied
  - assets with insufficient history get zero weight (flat) until warmed up

Usage, in the Godzilla .venv (PowerShell), from C:\\trading\\LLM_MODEL3:
    python models\\trend_baseline.py
"""
import os
import sys

import numpy as np
import pandas as pd

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)
from data.tiingo_eod import load_panel  # noqa: E402
from validation import backtest  # noqa: E402

# --- baseline parameters (decisions to revisit before locking results, Rule 7) ---
LOOKBACKS = (63, 126, 252)   # ~3, 6, 12 months of trading days
VOL_WINDOW = 60              # trailing days for realized-vol estimate
TARGET_VOL = 0.10            # per-asset annual vol target (relative-sizing input)
VOL_FLOOR = 0.05             # floor on annual vol est so cash-like ETFs (SHY) don't dominate inverse-vol
MAX_LEG = 1.5                # cap on any single position's raw weight before normalization
GROSS_EXPOSURE = 1.0         # normalize book to 100% gross (revisit to lever the whole book, Rule 7)
REBALANCE = "W-FRI"         # weekly rebalance (light-touch per charter)
COST_BPS = 2.0              # per-side cost on turnover (liquid ETFs)


def build_weights(adj_close: pd.DataFrame, lag: int = 1) -> tuple:
    """Return (weights, returns) as aligned wide frames. weights lagged `lag` days.
    lag=1 is the causal default; lag=0 deliberately leaks (look-ahead) and is used
    only to prove the harness is sensitive to look-ahead."""
    rets = adj_close.pct_change(fill_method=None)

    # multi-timeframe momentum score
    signs = [np.sign(adj_close / adj_close.shift(L) - 1.0) for L in LOOKBACKS]
    score = sum(signs) / len(signs)   # NaN where any lookback lacks history

    # volatility targeting (inverse-vol sizing), with a vol floor so near-zero-vol
    # cash proxies don't grab an outsized share of the book
    realized_vol = (rets.rolling(VOL_WINDOW).std() * np.sqrt(backtest.TRADING_DAYS)).clip(lower=VOL_FLOOR)
    raw_w = score * (TARGET_VOL / realized_vol)
    raw_w = raw_w.clip(-MAX_LEG, MAX_LEG).fillna(0.0)

    # normalize to a fixed gross exposure (portfolio budget), so weights are a
    # real allocation rather than an unbounded sum of per-asset bets
    gross = raw_w.abs().sum(axis=1)
    raw_w = raw_w.div(gross, axis=0).mul(GROSS_EXPOSURE).fillna(0.0)

    # weekly rebalance: hold last value each week, forward-fill to daily
    weekly = raw_w.resample(REBALANCE).last()
    w = weekly.reindex(raw_w.index, method="ffill").fillna(0.0)

    # lag: decided on day t's close, held over day t+lag (lag=1 => no look-ahead)
    w = w.shift(lag).fillna(0.0)
    return w, rets


def first_active_date(weights: pd.DataFrame) -> pd.Timestamp:
    active = weights.abs().sum(axis=1) > 0
    return weights.index[active.argmax()] if active.any() else weights.index[0]


def main() -> None:
    print("Loading ETF panel...")
    panel = load_panel()
    adj_close = panel.pivot(index="date", columns="ticker", values="adj_close").sort_index()
    print(f"  panel: {adj_close.shape[0]} days x {adj_close.shape[1]} ETFs, "
          f"{adj_close.index.min().date()} -> {adj_close.index.max().date()}")

    weights, rets = build_weights(adj_close)
    bt = backtest.run(weights, rets, cost_bps=COST_BPS)
    fa = first_active_date(weights)
    m = backtest.metrics(bt, first_active=fa)
    backtest.print_report(m, label="Engine A mechanical trend baseline")
    print(f"\n  (evaluation starts {fa.date()}, after warm-up; costs @ {COST_BPS} bps/side)")


if __name__ == "__main__":
    main()
