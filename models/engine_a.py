"""Engine A - charter-spec multi-asset ETF trend following (P2 kill-rule candidate).

This is the real Engine A per PROJECT_CHARTER.md section 4: blended multi-timeframe
trend, volatility-targeted positions, risk-parity weighting. It differs from
models/trend_baseline.py (the leak-check) in ONE way that matters: weighting.
The baseline treated all 22 ETFs as independent bets, so a "long equities" regime
stacked 14 correlated ETFs; this version budgets risk EQUALLY across 4 macro
classes (equity / fixed income / commodities / gold), which is what "risk-parity
weighting" in the charter means.

ALL parameters below are fixed A PRIORI, from the charter and standard trend
practice - NOT chosen to clear the kill-rule bar. This engine is evaluated ONCE
against KILL_RULE.md. No goalpost moves: if it misses, it misses.

Signal (per ETF, causal): mean of sign(total return) over 3/6/12 months.
Sizing: inverse-vol within class; equal risk budget across classes; then a
portfolio vol-targeting overlay to ~15% annual (ex-ante proxy, causal), lev cap 2.5x.
Leakage guards: all inputs use data <= day t; final weights lagged one day.

Usage, in the Godzilla .venv (PowerShell), from C:\\trading\\LLM_MODEL3:
    python models\\engine_a.py
"""
import os
import sys

import numpy as np
import pandas as pd

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)
from config.universe import MACRO_CLASS  # noqa: E402
from data.tiingo_eod import load_panel  # noqa: E402
from validation import backtest  # noqa: E402

# --- a-priori parameters (fixed before evaluation; do not tune to results) ---
LOOKBACKS = (63, 126, 252)   # 3, 6, 12 months
VOL_WINDOW = 60
VOL_FLOOR = 0.05
TARGET_PORT_VOL = 0.15       # annual portfolio vol target
LEV_CAP = 2.5
REBALANCE = "W-FRI"
COST_BPS = 2.0


def build_weights(adj_close: pd.DataFrame, lag: int = 1) -> tuple:
    rets = adj_close.pct_change(fill_method=None)
    tickers = list(adj_close.columns)

    # multi-timeframe momentum score, in {-1,-1/3,+1/3,+1}
    score = sum(np.sign(adj_close / adj_close.shift(L) - 1.0) for L in LOOKBACKS) / len(LOOKBACKS)

    # trailing realized vol, floored
    vol = (rets.rolling(VOL_WINDOW).std() * np.sqrt(backtest.TRADING_DAYS)).clip(lower=VOL_FLOOR)

    inv = score / vol  # signed inverse-vol tilt

    # equal risk budget across macro classes; inverse-vol within class
    classes = sorted(set(MACRO_CLASS[t] for t in tickers))
    K = len(classes)
    w_raw = pd.DataFrame(0.0, index=adj_close.index, columns=tickers)
    for c in classes:
        cols = [t for t in tickers if MACRO_CLASS[t] == c]
        denom = score[cols].abs().sum(axis=1).replace(0, np.nan)  # = sum|score| within class
        # class contributes 1/K of the (corr-ignoring) marginal-vol budget
        w_raw[cols] = inv[cols].div(denom, axis=0).fillna(0.0) / K

    # portfolio vol-targeting overlay (ex-ante proxy, ignores cross-correlation)
    vol_proxy = np.sqrt(((w_raw * vol) ** 2).sum(axis=1)).replace(0, np.nan)
    lev = (TARGET_PORT_VOL / vol_proxy).clip(upper=LEV_CAP).fillna(0.0)
    w_scaled = w_raw.mul(lev, axis=0)

    # weekly rebalance, then lag (causal)
    weekly = w_scaled.resample(REBALANCE).last()
    w = weekly.reindex(w_scaled.index, method="ffill").fillna(0.0)
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
    backtest.print_report(m, label="Engine A (charter-spec: risk parity + vol target)")
    print(f"\n  (evaluation starts {fa.date()}; a-priori spec; costs @ {COST_BPS} bps/side)")


if __name__ == "__main__":
    main()
