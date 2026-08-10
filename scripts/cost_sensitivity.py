"""Engine A cost completeness + sensitivity (the debt owed at commit edadfda).

Through edadfda, Engine A was charged ONLY 2 bps per unit of turnover. Two costs
were missing:

  1. STOCK BORROW on the short leg - named explicitly in KILL_RULE.md's
     "net of cost" guardrail. Engine A is short on 92% of days.
  2. MARGIN FINANCING on leverage - not named in the kill rule, but the book
     averages 2.7x gross and borrows cash on 58% of days, so "realistic costs"
     in PROJECT_CHARTER.md cannot mean ignoring it.

Both are implemented in validation/costs.py. The engine itself is UNCHANGED:
its parameters remain exactly as fixed a priori. Charging costs the charter
always required is not a goalpost move - and the movement is one-directional
(costs can only lower the number, never rescue it).

Two engine variants are reported:
  ex_ante  - the A-PRIORI spec (commit 18c3239). Net Sharpe 0.61 at 2 bps. This
             is the number the official kill-rule verdict rests on, so it is the
             one that must still clear 0.40 after costs.
  realized - the post-hoc vol-target calibration (commit edadfda), 0.71 at 2 bps.
             Reported for completeness; it is NOT the adjudicating number.

Run in the Godzilla .venv (PowerShell), from C:\\trading\\LLM_MODEL3:
    python scripts\\cost_sensitivity.py
"""
import os
import sys

import pandas as pd

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)
from data.tiingo_eod import load_panel  # noqa: E402
from validation import backtest, costs  # noqa: E402
import models.engine_a as ea  # noqa: E402

KILL_BAR = 0.40

# Headline cost-complete assumption set, fixed before results were inspected.
BASE_TURNOVER_BPS = 2.0     # as evaluated a priori
BASE_BORROW_STRESS = 1.0    # the a-priori borrow table in validation/costs.py
BASE_FINANCING = 0.04       # 4% flat all-in debit on borrowed cash, 0% credit


_WCACHE = {}


def weights_for(px, mode):
    """build_weights is the expensive step; the cost sweep reuses one build."""
    if mode not in _WCACHE:
        _WCACHE[mode] = ea.build_weights(px, vol_target_mode=mode)
    return _WCACHE[mode]


def evaluate(px, mode, turnover_bps=BASE_TURNOVER_BPS, borrow_stress=None,
             financing=0.0, credit=0.0):
    w, rets = weights_for(px, mode)
    extra = None
    if borrow_stress is not None or financing or credit:
        extra = costs.total_extra_cost(
            w,
            borrow_stress=(borrow_stress or 0.0),
            debit_rate=financing,
            credit_rate=credit,
            include_borrow=borrow_stress is not None,
        )
    bt = backtest.run(w, rets, cost_bps=turnover_bps, extra_cost=extra)
    return backtest.metrics(bt, first_active=ea.first_active_date(w)), w


def breakeven_financing(px, mode, lo=0.0, hi=1.0, tol=1e-4):
    """Flat financing debit rate at which net Sharpe falls to the 0.40 bar."""
    f = lambda x: evaluate(px, mode, borrow_stress=BASE_BORROW_STRESS,
                           financing=x)[0]["net_sharpe"] - KILL_BAR
    if f(lo) < 0:
        return 0.0
    if f(hi) > 0:
        return float("inf")
    for _ in range(40):
        mid = (lo + hi) / 2
        if f(mid) > 0:
            lo = mid
        else:
            hi = mid
        if hi - lo < tol:
            break
    return (lo + hi) / 2


def breakeven_turnover_bps(px, mode, lo=0.0, hi=500.0, tol=1e-2):
    """Turnover cost (bps/side) at which net Sharpe falls to the bar, holding
    borrow at base and financing at the headline 4%."""
    f = lambda x: evaluate(px, mode, turnover_bps=x,
                           borrow_stress=BASE_BORROW_STRESS,
                           financing=BASE_FINANCING)[0]["net_sharpe"] - KILL_BAR
    if f(lo) < 0:
        return 0.0
    if f(hi) > 0:
        return float("inf")
    for _ in range(40):
        mid = (lo + hi) / 2
        if f(mid) > 0:
            lo = mid
        else:
            hi = mid
        if hi - lo < tol:
            break
    return (lo + hi) / 2


def _row(label, m):
    verdict = "PASS" if (m["net_sharpe"] >= KILL_BAR
                         and m["rolling1y_frac_positive"] > 0.5) else "FAIL"
    print(f"  {label:<42s} {m['net_sharpe']:>6.2f}  {m['ann_return']:>7.2%}  "
          f"{m['ann_vol']:>6.2%}  {m['max_drawdown']:>7.1%}  "
          f"{m['rolling1y_frac_positive']:>5.0%}   {verdict}")


def exposure_summary(w, fa):
    ww = w.loc[fa:]
    return {
        "gross_mean": float(ww.abs().sum(axis=1).mean()),
        "gross_p95": float(ww.abs().sum(axis=1).quantile(0.95)),
        "gross_max": float(ww.abs().sum(axis=1).max()),
        "short_mean": float(costs.short_notional(ww).mean()),
        "days_short": float((costs.short_notional(ww) > 1e-9).mean()),
        "days_borrowing": float((costs.net_cash(ww) < 0).mean()),
        "borrowed_mean": float((-costs.net_cash(ww).clip(upper=0)).mean()),
    }


def main():
    print("Loading ETF panel...")
    px = load_panel().pivot(index="date", columns="ticker",
                            values="adj_close").sort_index()
    print(f"  panel: {px.shape[0]} days x {px.shape[1]} ETFs, "
          f"{px.index.min().date()} -> {px.index.max().date()}")

    for mode, tag in [("ex_ante", "A-PRIORI SPEC (18c3239) - the adjudicating number"),
                      ("realized", "vol-calibrated (edadfda) - reported, not adjudicating")]:
        w, _ = weights_for(px, mode)
        fa = ea.first_active_date(w)
        ex = exposure_summary(w, fa)

        print(f"\n{'=' * 96}")
        print(f"ENGINE A - {tag}")
        print(f"{'=' * 96}")
        print(f"  exposure: gross mean {ex['gross_mean']:.2f}x, p95 {ex['gross_p95']:.2f}x, "
              f"max {ex['gross_max']:.2f}x | short mean {ex['short_mean']:.2f}x "
              f"on {ex['days_short']:.0%} of days")
        print(f"            borrowing cash on {ex['days_borrowing']:.0%} of days, "
              f"mean borrowed {ex['borrowed_mean']:.2f}x NAV")
        print(f"\n  {'scenario':<42s} {'Sharpe':>6s}  {'ann ret':>7s}  {'vol':>6s}  "
              f"{'maxDD':>7s}  {'roll+':>5s}   verdict")
        print(f"  {'-' * 88}")

        _row("as evaluated (2bps turnover only)",
             evaluate(px, mode)[0])
        _row("+ borrow @ a-priori table",
             evaluate(px, mode, borrow_stress=1.0)[0])
        _row("+ borrow @ 3x stress",
             evaluate(px, mode, borrow_stress=3.0)[0])
        _row("+ borrow @ 10x stress",
             evaluate(px, mode, borrow_stress=10.0)[0])
        print(f"  {'-' * 88}")
        for fin in (0.02, 0.04, 0.06, 0.08):
            _row(f"+ borrow + financing @ {fin:.0%} flat",
                 evaluate(px, mode, borrow_stress=1.0, financing=fin)[0])
        print(f"  {'-' * 88}")
        for bps in (5.0, 10.0, 20.0):
            _row(f"+ borrow + fin 4% + turnover @ {bps:.0f}bps",
                 evaluate(px, mode, turnover_bps=bps, borrow_stress=1.0,
                          financing=BASE_FINANCING)[0])
        print(f"  {'-' * 88}")
        _row("+ borrow 3x + fin 6% + turnover 10bps  [harsh]",
             evaluate(px, mode, turnover_bps=10.0, borrow_stress=3.0,
                      financing=0.06)[0])

        m_head, _ = evaluate(px, mode, borrow_stress=BASE_BORROW_STRESS,
                             financing=BASE_FINANCING)
        be_fin = breakeven_financing(px, mode)
        be_bps = breakeven_turnover_bps(px, mode)
        print(f"\n  HEADLINE cost-complete (2bps + borrow + 4% financing): "
              f"net Sharpe {m_head['net_sharpe']:.2f}, "
              f"{m_head['rolling1y_frac_positive']:.0%} of rolling years positive")
        print(f"  break-even financing rate (borrow at base, 2bps): "
              f"{be_fin:.1%}  -> Sharpe hits {KILL_BAR:.2f} there")
        print(f"  break-even turnover cost (borrow at base, fin 4%):  "
              f"{be_bps:.1f} bps/side")

    print(f"\n{'=' * 96}")
    print("Kill-rule bar: net OOS Sharpe >= 0.40 AND positive in a clear majority of")
    print("rolling windows. Verdict rests on the A-PRIORI (ex_ante) rows.")
    print(f"{'=' * 96}")


if __name__ == "__main__":
    main()
