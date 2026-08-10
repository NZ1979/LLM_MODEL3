"""Backtest engine + metrics for Engine A - the leak-aware evaluation core.

Deliberately simple and transparent: given a matrix of positions (weights held
DURING each day, already decided on prior information) and a matrix of asset
returns, it computes net-of-cost portfolio returns and the metrics the kill rule
cares about (net Sharpe + rolling-window consistency).

Leakage contract (enforced by the caller, documented here):
  - weights[t] is the position held over day t and must be decided using data
    up to day t-1 only. The trend model lags weights by one day before calling
    this, so nothing here peeks forward.
  - costs are charged on turnover |weights[t] - weights[t-1]|.
  - all reported returns are NET of cost. Gross is shown only for diagnosis.

This module has no model logic and no I/O; it is reused unchanged by the
mechanical baseline (P2) and later by any Engine A variant, so the harness that
declares an edge is the same one proven leak-free on the baseline.
"""
import numpy as np
import pandas as pd

TRADING_DAYS = 252


def run(weights: pd.DataFrame, returns: pd.DataFrame, cost_bps: float = 2.0,
        extra_cost: pd.Series = None) -> pd.DataFrame:
    """Return a frame with gross, cost, net daily portfolio returns and equity.

    weights and returns are aligned wide frames (index=date, columns=tickers).
    cost_bps is per unit of turnover per side (2.0 = 2 basis points).

    extra_cost is an optional daily carrying-cost series (fraction of NAV per
    day) added on top of turnover cost - used for stock-borrow on the short leg
    and margin financing on leverage; see validation/costs.py. Default None
    reproduces every result computed through commit edadfda bit-for-bit.
    """
    w = weights.reindex_like(returns).fillna(0.0)
    r = returns.fillna(0.0)
    gross = (w * r).sum(axis=1)

    turnover = w.diff().abs().sum(axis=1)
    turnover.iloc[0] = w.iloc[0].abs().sum()  # initial establishment of positions
    cost = turnover * (cost_bps / 1e4)

    if extra_cost is not None:
        cost = cost + extra_cost.reindex(cost.index).fillna(0.0)

    net = gross - cost
    out = pd.DataFrame({"gross": gross, "cost": cost, "net": net})
    out["equity"] = (1.0 + out["net"]).cumprod()
    out["turnover"] = turnover
    return out


def _sharpe(daily: pd.Series) -> float:
    daily = daily.dropna()
    if daily.std() == 0 or len(daily) < 2:
        return float("nan")
    return float(daily.mean() / daily.std() * np.sqrt(TRADING_DAYS))


def _max_drawdown(equity: pd.Series) -> float:
    peak = equity.cummax()
    return float((equity / peak - 1.0).min())


def metrics(bt: pd.DataFrame, first_active: pd.Timestamp = None) -> dict:
    """Summary stats on the NET series. If first_active given, evaluate from there
    (skips the warm-up period before any position is taken)."""
    net = bt["net"]
    if first_active is not None:
        net = net.loc[first_active:]
    n = len(net)
    ann_ret = float(net.mean() * TRADING_DAYS)
    ann_vol = float(net.std() * np.sqrt(TRADING_DAYS))
    equity = (1.0 + net).cumprod()

    # rolling 1yr Sharpe and the fraction of windows that are positive (kill-rule consistency)
    roll = net.rolling(TRADING_DAYS).apply(_sharpe, raw=False)
    roll = roll.dropna()
    frac_pos = float((roll > 0).mean()) if len(roll) else float("nan")

    # per calendar year net return
    by_year = (net.groupby(net.index.year).apply(lambda s: (1 + s).prod() - 1))

    return {
        "days": n,
        "years": round(n / TRADING_DAYS, 1),
        "ann_return": ann_ret,
        "ann_vol": ann_vol,
        "net_sharpe": _sharpe(net),
        "gross_sharpe": _sharpe(bt["gross"].loc[net.index]),
        "max_drawdown": _max_drawdown(equity),
        "avg_daily_turnover": float(bt["turnover"].loc[net.index].mean()),
        "rolling1y_frac_positive": frac_pos,
        "by_year": {int(y): round(v, 4) for y, v in by_year.items()},
    }


def print_report(m: dict, label: str = "strategy") -> None:
    print(f"\n=== {label} (NET of costs) ===")
    print(f"  span:            {m['years']} yrs ({m['days']} days)")
    print(f"  ann return:      {m['ann_return']:+.2%}")
    print(f"  ann vol:         {m['ann_vol']:.2%}")
    print(f"  NET Sharpe:      {m['net_sharpe']:.2f}    (gross {m['gross_sharpe']:.2f})")
    print(f"  max drawdown:    {m['max_drawdown']:.1%}")
    print(f"  rolling-1y > 0:  {m['rolling1y_frac_positive']:.0%} of windows")
    print(f"  avg daily turnover: {m['avg_daily_turnover']:.3f}")
    print(f"  kill-rule bar:   net OOS Sharpe >= 0.40 AND positive in a clear majority of windows")
    print("  by year:")
    for y, v in m["by_year"].items():
        print(f"    {y}: {v:+.1%}")
