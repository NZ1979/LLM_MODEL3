"""Engine A-2 (gross-capped) - the single pre-registered evaluation.

Implements docs/ENGINE_A_CAPPED_SPEC.md exactly. That spec was committed and
pushed with no result under it; this script produces the one evaluation it
authorises.

ONE cap level, ONE run. If A-2 misses, it misses - the response is NOT a
different cap. See the spec's "Failure handling, fixed in advance".

Engine A's own kill-rule verdict (net Sharpe 0.59, borrow-complete) is unaffected
by anything this script prints.

Run in the Godzilla .venv (PowerShell), from C:\\trading\\LLM_MODEL3:
    python scripts\\evaluate_capped.py
"""
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)
from data.tiingo_eod import load_panel  # noqa: E402
from data import fred_rates  # noqa: E402
from validation import backtest, costs  # noqa: E402
import models.engine_a as ea  # noqa: E402

# --- pre-registered, do not edit to fit results (docs/ENGINE_A_CAPPED_SPEC.md) ---
GROSS_CAP = 2.0
VOL_TARGET_MODE = "ex_ante"
TURNOVER_BPS = 2.0
BORROW_STRESS = 1.0
DEBIT_SPREAD = 0.0100
CREDIT_SPREAD = 0.0025
SENSITIVITY_SPREADS = (0.0050, 0.0100, 0.0200, 0.0400)
REQUIRED_SPREAD_FOR_PAPER = 0.0200   # A-2 must also clear the bar at +200bps
BAR = 0.40


def _ok(m):
    return m["net_sharpe"] >= BAR and m["rolling1y_frac_positive"] > 0.5


def _row(label, m):
    print(f"  {label:<44s} {m['net_sharpe']:>6.2f}  {m['ann_return']:>7.2%}  "
          f"{m['ann_vol']:>6.2%}  {m['max_drawdown']:>7.1%}  "
          f"{m['rolling1y_frac_positive']:>5.0%}   {'PASS' if _ok(m) else 'FAIL'}")


def main():
    print("Loading ETF panel...")
    px = load_panel().pivot(index="date", columns="ticker",
                            values="adj_close").sort_index()
    print(f"  panel: {px.shape[0]} days x {px.shape[1]} ETFs, "
          f"{px.index.min().date()} -> {px.index.max().date()}")

    w, rets = ea.build_weights(px, vol_target_mode=VOL_TARGET_MODE,
                               gross_cap=GROSS_CAP)
    w_un, _ = ea.build_weights(px, vol_target_mode=VOL_TARGET_MODE)
    fa = ea.first_active_date(w)
    base = fred_rates.align_to(px.index)
    debit = base + DEBIT_SPREAD
    credit = (base - CREDIT_SPREAD).clip(lower=0.0)

    print(f"\n{'=' * 98}")
    print(f"ENGINE A-2 - gross-capped at {GROSS_CAP:.1f}x, vol target '{VOL_TARGET_MODE}'")
    print(f"  single pre-registered evaluation per docs/ENGINE_A_CAPPED_SPEC.md")
    print(f"{'=' * 98}")

    # condition 3: the cap must actually bind
    g = w.loc[fa:].abs().sum(axis=1)
    g_un = w_un.loc[fa:].abs().sum(axis=1)
    breaches = int((g > GROSS_CAP + 1e-9).sum())
    print(f"  gross exposure: mean {g.mean():.2f}x, p95 {g.quantile(.95):.2f}x, "
          f"max {g.max():.2f}x   (uncapped was {g_un.mean():.2f}x / "
          f"{g_un.quantile(.95):.2f}x / {g_un.max():.2f}x)")
    print(f"  cap binds on {(g_un > GROSS_CAP + 1e-9).mean():.0%} of days; "
          f"breaches of the cap: {breaches}  {'OK' if breaches == 0 else 'DEFECT'}")

    ex_b = costs.borrow_cost(w.loc[fa:], stress=BORROW_STRESS).mean() * 252
    ex_f = costs.financing_cost(w.loc[fa:], debit.loc[fa:], credit.loc[fa:]).mean() * 252
    print(f"  measured drag: borrow {ex_b:.3%}/yr, financing {ex_f:.3%}/yr")
    print(f"  cash borrowed on {(costs.net_cash(w.loc[fa:]) < 0).mean():.0%} of days")

    print(f"\n  {'cost basis':<44s} {'Sharpe':>6s}  {'ann ret':>7s}  {'vol':>6s}  "
          f"{'maxDD':>7s}  {'roll+':>5s}   verdict")
    print(f"  {'-' * 90}")

    def ev(debit_rate=0.0, credit_rate=0.0, borrow=BORROW_STRESS):
        extra = costs.total_extra_cost(w, borrow_stress=borrow,
                                       debit_rate=debit_rate, credit_rate=credit_rate)
        return backtest.metrics(
            backtest.run(w, rets, cost_bps=TURNOVER_BPS, extra_cost=extra),
            first_active=fa)

    m_kill = ev()
    _row("borrow-complete  [CONDITION 1]", m_kill)
    m_gate = ev(debit, credit)
    _row("+ measured financing  [CONDITION 2]", m_gate)
    print(f"  {'-' * 90}")
    sens = {}
    for sp in SENSITIVITY_SPREADS:
        m = ev(base + sp, credit)
        sens[sp] = m
        _row(f"+ financing @ DTB3 +{sp * 1e4:.0f}bps", m)

    # Credit-side stress. A capped book holds a large cash balance, so the
    # measured financing term can be a net CREDIT rather than a cost - which
    # would mean A-2 partly passes on the generosity of the credit assumption.
    # The debit grid above cannot detect that, so stress the credit to zero.
    print(f"  {'-' * 90}")
    m_nocredit = ev(debit, 0.0)
    _row("+ financing, ZERO credit on cash  [stress]", m_nocredit)
    m_worst = ev(base + REQUIRED_SPREAD_FOR_PAPER, 0.0)
    _row("+ DTB3 +200bps debit AND zero credit [worst]", m_worst)

    m_200 = sens[REQUIRED_SPREAD_FOR_PAPER]
    print(f"\n  {'*' * 90}")
    print(f"  CONDITION 1 borrow-complete >= {BAR:.2f}:      "
          f"{m_kill['net_sharpe']:.2f}  {'PASS' if _ok(m_kill) else 'FAIL'}")
    print(f"  CONDITION 2 measured financing >= {BAR:.2f}:   "
          f"{m_gate['net_sharpe']:.2f}  {'PASS' if _ok(m_gate) else 'FAIL'}")
    print(f"  CONDITION 3 no gross breach of {GROSS_CAP:.1f}x:      "
          f"{breaches} breaches  {'PASS' if breaches == 0 else 'FAIL'}")
    print(f"  CONDITION 4 clears bar at DTB3 +200bps:  "
          f"{m_200['net_sharpe']:.2f}  {'PASS' if _ok(m_200) else 'FAIL'}")
    print(f"  CONDITION 5 clears bar with ZERO cash credit: "
          f"{m_nocredit['net_sharpe']:.2f}  {'PASS' if _ok(m_nocredit) else 'FAIL'}")
    print(f"    (worst case, +200bps debit and no credit:  "
          f"{m_worst['net_sharpe']:.2f}  {'PASS' if _ok(m_worst) else 'FAIL'})")
    overall = (_ok(m_kill) and _ok(m_gate) and breaches == 0
               and _ok(m_200) and _ok(m_nocredit))
    print(f"\n  ENGINE A-2 PROPOSED FOR PAPER TRADING: {'YES' if overall else 'NO'}")
    if not overall:
        print("    Per the spec: do NOT try another cap level. Record the result,")
        print("    leave Engine A's verdict standing, and take the project-level")
        print("    decision in PROJECT_CHARTER.md.")
    print(f"  {'*' * 90}")

    print(f"\n{'=' * 98}")
    print("LEAK CHECK on the final cost basis")
    print(f"{'=' * 98}")
    row = []
    for lag in (0, 1, 2):
        wl, rl = ea.build_weights(px, lag=lag, vol_target_mode=VOL_TARGET_MODE,
                                  gross_cap=GROSS_CAP)
        extra = costs.total_extra_cost(wl, borrow_stress=BORROW_STRESS,
                                       debit_rate=debit, credit_rate=credit)
        row.append(backtest.metrics(
            backtest.run(wl, rl, cost_bps=TURNOVER_BPS, extra_cost=extra),
            first_active=ea.first_active_date(wl))["net_sharpe"])
    # The load-bearing test is lag0 >> lag1: a deliberately leaked book must
    # score far better than the causal one. lag1 vs lag2 is secondary colour -
    # it reflects signal persistence, and a small inversion there is not
    # evidence of leakage.
    gap = row[0] - row[1]
    primary = gap > 0.20
    print(f"  lag0 {row[0]:.2f} -> lag1 {row[1]:.2f} -> lag2 {row[2]:.2f}")
    print(f"  PRIMARY  leaked-vs-causal gap {gap:+.2f}  "
          f"{'OK - harness detects look-ahead' if primary else 'INVESTIGATE - leak test not discriminating'}")
    print(f"  secondary lag1 > lag2 decay: {row[1] > row[2]} "
          f"(informational; persistence, not leakage)")


if __name__ == "__main__":
    main()
