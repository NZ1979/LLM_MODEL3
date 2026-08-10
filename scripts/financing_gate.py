"""Engine A pre-paper realism gate: financing measured, not assumed.

Implements exactly the specification pre-registered in docs/FINANCING_SPEC.md.
That file was committed and pushed BEFORE this script was ever run; if you are
reading a history where the spec and the first result land in the same commit,
the pre-registration is void and the result must be discarded.

This is NOT the kill-rule test. KILL_RULE.md is locked and its "net of cost"
guardrail names slippage, commissions, and borrow - not financing. The kill-rule
verdict is adjudicated borrow-complete by scripts/cost_sensitivity.py. This gate
is a separate, stricter check that Engine A must clear before paper trading.

Run in the Godzilla .venv (PowerShell), from C:\\trading\\LLM_MODEL3:
    python data\\fred_rates.py          (once, to populate the rate series)
    python scripts\\financing_gate.py
"""
import os
import sys

import pandas as pd

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)
from data.tiingo_eod import load_panel  # noqa: E402
from data import fred_rates  # noqa: E402
from validation import backtest, costs  # noqa: E402
import models.engine_a as ea  # noqa: E402

# --- pre-registered constants (docs/FINANCING_SPEC.md; do not edit to fit results) ---
KILL_BAR = 0.40
TURNOVER_BPS = 2.0
BORROW_STRESS = 1.0
DEBIT_SPREAD = 0.0100        # +100 bps over DTB3 on borrowed cash
CREDIT_SPREAD = 0.0025       # -25 bps under DTB3 on positive cash, floored at 0
SENSITIVITY_DEBIT_SPREADS = (0.0050, 0.0100, 0.0200, 0.0400)
ADJUDICATING_MODE = "ex_ante"   # the a-priori spec, 18c3239


def rate_legs(index: pd.DatetimeIndex):
    base = fred_rates.align_to(index)
    debit = base + DEBIT_SPREAD
    credit = (base - CREDIT_SPREAD).clip(lower=0.0)
    return base, debit, credit


def evaluate(w, rets, debit, credit, turnover_bps=TURNOVER_BPS):
    extra = costs.total_extra_cost(w, borrow_stress=BORROW_STRESS,
                                   debit_rate=debit, credit_rate=credit)
    bt = backtest.run(w, rets, cost_bps=turnover_bps, extra_cost=extra)
    return backtest.metrics(bt, first_active=ea.first_active_date(w))


def _row(label, m):
    verdict = "PASS" if (m["net_sharpe"] >= KILL_BAR
                         and m["rolling1y_frac_positive"] > 0.5) else "FAIL"
    print(f"  {label:<44s} {m['net_sharpe']:>6.2f}  {m['ann_return']:>7.2%}  "
          f"{m['ann_vol']:>6.2%}  {m['max_drawdown']:>7.1%}  "
          f"{m['rolling1y_frac_positive']:>5.0%}   {verdict}")


def leak_check(px, mode, debit, credit):
    """Re-run the lag test on the FINAL cost basis.

    Additive diagnostics only - does not touch the gate spec or its result. A
    deliberately leaked lag-0 book (positions decided on same-day information)
    must score far higher than the causal lag-1 book, and lag-2 must decay
    further. Monotonic decay is evidence the harness detects look-ahead and that
    the reported number sits on the honest side of it.
    """
    out = []
    for lag in (0, 1, 2):
        w, rets = ea.build_weights(px, lag=lag, vol_target_mode=mode)
        out.append(evaluate(w, rets, debit, credit)["net_sharpe"])
    return out


def main():
    print("Loading ETF panel...")
    px = load_panel().pivot(index="date", columns="ticker",
                            values="adj_close").sort_index()
    print(f"  panel: {px.shape[0]} days x {px.shape[1]} ETFs, "
          f"{px.index.min().date()} -> {px.index.max().date()}")

    for mode in (ADJUDICATING_MODE, "realized"):
        w, rets = ea.build_weights(px, vol_target_mode=mode)
        fa = ea.first_active_date(w)
        w_eval = w.loc[fa:]
        base, debit, credit = rate_legs(w.index)

        tag = ("A-PRIORI SPEC (18c3239) - THE GATE"
               if mode == ADJUDICATING_MODE
               else "vol-calibrated (edadfda) - reported, not the gate")
        print(f"\n{'=' * 98}")
        print(f"ENGINE A - {tag}")
        print(f"{'=' * 98}")
        print(f"  DTB3 over the eval window: mean {base.loc[fa:].mean():.2%}, "
              f"min {base.loc[fa:].min():.2%}, max {base.loc[fa:].max():.2%}")
        print(f"  effective debit  = DTB3 +{DEBIT_SPREAD * 1e4:.0f}bps  "
              f"-> mean {debit.loc[fa:].mean():.2%}")
        print(f"  effective credit = DTB3 -{CREDIT_SPREAD * 1e4:.0f}bps  "
              f"-> mean {credit.loc[fa:].mean():.2%}")

        fin = costs.financing_cost(w_eval, debit.loc[fa:], credit.loc[fa:])
        bor = costs.borrow_cost(w_eval, stress=BORROW_STRESS)
        print(f"  measured drag: borrow {bor.mean() * 252:.3%}/yr, "
              f"financing {fin.mean() * 252:.3%}/yr")

        print(f"\n  {'scenario':<44s} {'Sharpe':>6s}  {'ann ret':>7s}  {'vol':>6s}  "
              f"{'maxDD':>7s}  {'roll+':>5s}   verdict")
        print(f"  {'-' * 90}")
        _row("borrow only (the kill-rule cost basis)",
             evaluate(w, rets, 0.0, 0.0))
        m_gate = evaluate(w, rets, debit, credit)
        _row("+ MEASURED financing (DTB3 +100/-25)  [GATE]", m_gate)
        print(f"  {'-' * 90}")
        for sp in SENSITIVITY_DEBIT_SPREADS:
            d = fred_rates.align_to(w.index) + sp
            _row(f"+ financing @ DTB3 +{sp * 1e4:.0f}bps",
                 evaluate(w, rets, d, credit))

        if mode == ADJUDICATING_MODE:
            passed = (m_gate["net_sharpe"] >= KILL_BAR
                      and m_gate["rolling1y_frac_positive"] > 0.5)
            print(f"\n  {'*' * 90}")
            print(f"  PRE-PAPER REALISM GATE: {'PASS' if passed else 'FAIL'}")
            print(f"    net Sharpe {m_gate['net_sharpe']:.2f} vs bar {KILL_BAR:.2f}; "
                  f"{m_gate['rolling1y_frac_positive']:.0%} of rolling years positive "
                  f"vs bar >50%")
            print(f"    (kill-rule verdict is unaffected either way; it is "
                  f"adjudicated borrow-complete)")
            print(f"  {'*' * 90}")

    print(f"\n{'=' * 98}")
    print("LEAK RE-CHECK on the final cost basis (borrow + measured financing)")
    print("  expect lag0 >> lag1 > lag2; lag0 is deliberately leaked and must NOT be")
    print("  close to lag1. A flat or inverted profile means the harness is not")
    print("  detecting look-ahead and every number above is suspect.")
    print(f"{'=' * 98}")
    _, debit, credit = rate_legs(px.index)
    for mode in (ADJUDICATING_MODE, "realized"):
        s0, s1, s2 = leak_check(px, mode, debit, credit)
        ok = s0 > s1 > s2
        print(f"  {mode:9s} lag0 {s0:.2f} -> lag1 {s1:.2f} -> lag2 {s2:.2f}   "
              f"monotonic decay: {ok}   {'OK' if ok else 'INVESTIGATE'}")


if __name__ == "__main__":
    main()
