"""Engine B (P3) - the mechanical baseline measuring run.

Implements docs/ENGINE_B_BASELINE_SPEC.md end to end: assemble the PIT panel
(data/sharadar_panel), apply the pre-registered universe screen
(models/engine_b_universe), compute the five equal-weight factors and composite
(models/engine_b_factors), then evaluate through the walk-forward harness
(validation/engine_b_harness) and print the pre-registered metric set NET of
cost.

DISCIPLINE (A-2): this script must be COMMITTED before it is ever run on the
real panel, so Engine B's performance is unobserved until the code is frozen.
Run it only after the implementation commit has landed (git log).

  Build/leak-audit span (run first, audit, then stop):
      python scripts/run_engine_b_baseline.py --span build

  Hold-out (touched ONCE, only after the build run is audited clean):
      python scripts/run_engine_b_baseline.py --span holdout --confirm-holdout

The hold-out refuses to run without --confirm-holdout so it cannot be spent
casually. Results are PRINTED, never written into the repo, so a measuring
result can never be committed alongside the spec (which would void the
pre-registration).

Run on GODZILLA in the repo .venv (the panel parquet lives there; the sandbox
is firewalled). Reads data/raw/sharadar/*.parquet.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from data import sharadar_panel as sp        # noqa: E402
from models import engine_b_universe as ebu   # noqa: E402
from models import engine_b_factors as ebf    # noqa: E402
from validation import engine_b_harness as ebh  # noqa: E402

# Pre-registered spans (docs/ENGINE_B_BASELINE_SPEC.md "Evaluation"):
#   build/leak-audit on 1998-2020; hold-out 2021+ touched once.
SPANS = {
    "build":   ("1998-01-01", "2020-12-31"),
    "holdout": ("2021-01-01", "2026-12-31"),
}
DEFAULT_RAW = _REPO / "data" / "raw" / "sharadar"


# ---------------------------------------------------------------------------
def assemble(built: pd.DataFrame):
    """Screen -> score -> attach label -> evaluate. Returns all pieces."""
    screened = ebu.screen(built)
    universe_cov = ebu.coverage_report(screened)
    elig = screened[screened["eligible"]].copy()
    scores = ebf.compute_scores(elig)
    rank_cov = ebf.ranking_coverage(scores)
    panel = scores.merge(
        built[["date", "permaticker", "fwd_ret_21", "fwd_status"]],
        on=["date", "permaticker"], how="left")
    res = ebh.evaluate(panel)
    audit = ebh.leak_audit(panel)
    return dict(built=built, screened=screened, panel=panel, res=res, audit=audit,
                universe_cov=universe_cov, rank_cov=rank_cov)


def _fmt(x, pct=False, dp=2):
    if x is None or (isinstance(x, float) and not np.isfinite(x)):
        return "  n/a"
    return f"{x*100:.{dp}f}%" if pct else f"{x:.{dp}f}"


def print_report(a: dict, span_label: str, span) -> None:
    built, res, audit = a["built"], a["res"], a["audit"]
    ic = res["ic_summary"]
    tab = res["decile_table"]
    mono = res["monotonicity"]
    lo = res["long_only"]
    ls = res["long_short"]
    W = 78

    print("\n" + "=" * W)
    print(f"ENGINE B MECHANICAL BASELINE - span '{span_label}' [{span[0]} .. {span[1]}]")
    print("  per docs/ENGINE_B_BASELINE_SPEC.md - all figures NET of cost, out-of-sample")
    print("=" * W)

    # --- coverage funnels (Rule 18: show denominators) ---------------------
    ucov = a["universe_cov"]
    rcov = a["rank_cov"]
    print("\nUNIVERSE FUNNEL (median across rebalances):")
    med = ucov.median().astype(int)
    print(f"  candidates {med['candidates']} -> type {med['type_ok']} -> listing "
          f"{med['listing_ok']} -> size {med['size_ok']} -> liquidity {med['liquidity_ok']}"
          f" -> price {med['price_ok']} -> history {med['history_ok']} -> ELIGIBLE {med['eligible']}")
    print(f"  eligible names/month: min {int(ucov['eligible'].min())}, "
          f"median {int(ucov['eligible'].median())}, max {int(ucov['eligible'].max())}")
    dropped = int(rcov["dropped_no_fundamental"].sum())
    print(f"  ranked (all 5 factors present): median {int(rcov['ranked'].median())}/month; "
          f"{dropped} eligible name-months dropped for no ART fundamental at T")

    # label coverage
    st = built["fwd_status"].value_counts()
    print("\nLABEL STATUS (forward 21d return):")
    for k in ("ok", "delisted_partial", "incomplete_window", "no_forward_price"):
        print(f"  {k:<20s} {int(st.get(k, 0)):>9,}")

    # --- 1. rank-IC --------------------------------------------------------
    print("\n[1] RANK-IC  (monthly cross-sectional Spearman, composite vs T->T+21)")
    print(f"  months evaluated:   {ic['n_months']}")
    print(f"  mean rank-IC:       {ic['mean_ic']:+.4f}   (median {ic['median_ic']:+.4f})")
    print(f"  Newey-West t-stat:  {ic['nw_tstat']:+.2f}")
    print(f"  IC > 0 in:          {_fmt(ic['frac_positive'], pct=True, dp=0)} of months")
    print("  KILL-RULE bar: IC > 0 AND statistically distinguishable from zero")

    # --- 2. deciles --------------------------------------------------------
    print("\n[2] DECILE MONOTONICITY  (D10 = highest composite)")
    print(f"  {'decile':>6}  {'mean fwd ret':>12}  {'Sharpe(ann)':>11}  {'months':>7}")
    for dec, row in tab.iterrows():
        print(f"  {int(dec):>6}  {_fmt(row['mean_fwd_ret'], pct=True):>12}  "
              f"{_fmt(row['sharpe']):>11}  {int(row['n_months']):>7}")
    print(f"  Spearman(decile, mean ret): {_fmt(mono['spearman_ret'])}   "
          f"Spearman(decile, Sharpe): {_fmt(mono['spearman_sharpe'])}")
    print(f"  D10 - D1 mean fwd ret:      {_fmt(mono['d10_minus_d1_ret'], pct=True)}   "
          f"adjacent steps up: {_fmt(mono['frac_adjacent_up_ret'], pct=True, dp=0)}")
    print("  KILL-RULE bar: Sharpe rises (near-)monotonically D1 -> D10")

    # --- 3. tradeable form -------------------------------------------------
    print("\n[3] TRADEABLE FORM - equal-weight LONG-ONLY top decile (D10), net of cost")
    print(f"  {'cost/side':>9}  {'Sharpe':>6}  {'CAGR':>7}  {'ann vol':>7}  "
          f"{'maxDD':>7}  {'turnover':>8}")
    for b in ebh.COST_SIDES_BPS:
        m = lo["by_cost"][b]
        print(f"  {b:>6.0f}bps  {_fmt(m['sharpe']):>6}  {_fmt(m['cagr'], pct=True):>7}  "
              f"{_fmt(m['ann_vol'], pct=True):>7}  {_fmt(m['max_drawdown'], pct=True):>7}  "
              f"{_fmt(m['avg_turnover']):>8}")
    base = lo["baseline"]
    print(f"  baseline (10 bps/side): Sharpe {_fmt(base['sharpe'])}, "
          f"CAGR {_fmt(base['cagr'], pct=True)}, maxDD {_fmt(base['max_drawdown'], pct=True)}, "
          f"months {base['months']}")
    print(f"  name-months dropped for missing forward label: {lo['total_dropped_label']}")
    lsb = ls["baseline"]
    print(f"  [diagnostic only] long-short D10-D1 @10bps/side: "
          f"Sharpe {_fmt(lsb['sharpe'])}, CAGR {_fmt(lsb['cagr'], pct=True)} "
          f"(NOT tradeable - shorting/borrow costs excluded)")

    # --- leak audit (harness proof) ---------------------------------------
    print("\n[LEAK AUDIT] harness sensitivity + permutation null (same panel):")
    print(f"  cheat score = realised fwd return -> mean IC {audit['cheat_mean_ic']:+.3f}, "
          f"decile Spearman {audit['cheat_spearman_decile']:+.3f}  (expect ~+1 / +1)")
    print(f"  permutation null ({audit['shuffle_reps']} seeds): mean IC "
          f"{audit['shuffle_null_mean']:+.4f}, SD {audit['shuffle_null_sd']:.4f}, "
          f"|max| {audit['shuffle_null_absmax']:.4f}  (expect mean ~0)")
    print(f"  real mean IC {audit['real_mean_ic']:+.4f} sits "
          f"{audit['real_vs_null_z']:+.1f} SD above the permutation null  "
          f"(the signal is real, not a harness artefact if this is large & positive)")

    # --- pre-registered interpretation ------------------------------------
    print("\n" + "-" * W)
    print("INTERPRETATION (pre-registered in the spec - read BEFORE reacting to numbers):")
    mic = ic["mean_ic"]
    if mic is not None and np.isfinite(mic):
        if mic > 0.10 or (np.isfinite(mono['spearman_ret']) and mono['spearman_ret'] > 0.99
                          and np.isfinite(mono['spearman_sharpe']) and mono['spearman_sharpe'] > 0.99):
            print("  IC > ~0.10 monthly and/or a perfect decile staircase => ASSUME LEAKAGE.")
            print("  Do NOT bank this. Audit the harness (fundamentals join, survivorship,")
            print("  label peek) before trusting anything (charter 5.3, Rule 14).")
        elif 0.015 <= mic <= 0.08:
            print("  IC ~0.02-0.05, noisy but positive => harness looks clean; classic")
            print("  factors carry a modest edge here. This is the benchmark the P4 LLM")
            print("  layer must beat by >=20% relative (KILL_RULE.md).")
        else:
            print("  IC ~0 or negative => harness looks clean but simple factors do not")
            print("  work net of cost in this universe. Informative, acceptable result;")
            print("  the P4 LLM layer then faces a very high bar.")
    print("  A too-good result is a leak to be found, not an edge to be banked.")
    print("=" * W)


# ---------------------------------------------------------------------------
def main() -> None:
    ap = argparse.ArgumentParser(description="Engine B mechanical baseline measuring run")
    ap.add_argument("--span", choices=list(SPANS), required=True)
    ap.add_argument("--raw-dir", default=str(DEFAULT_RAW))
    ap.add_argument("--confirm-holdout", action="store_true",
                    help="required to score the 2021+ hold-out (touched once)")
    args = ap.parse_args()

    span = SPANS[args.span]
    if args.span == "holdout" and not args.confirm_holdout:
        sys.exit("REFUSED: the 2021+ hold-out is touched ONCE, only after the build "
                 "run is audited clean. Re-run with --confirm-holdout if that is the case.")

    print(f"Assembling PIT panel for span '{args.span}' {span} ...")
    built = sp.build_panel_from_parquet(args.raw_dir, span[0], span[1], verbose=True)
    a = assemble(built)
    print_report(a, args.span, span)
    print("\n(Results printed only - NOT written to disk, so they cannot be committed "
          "alongside the pre-registered spec. Paste this whole output back.)")


if __name__ == "__main__":
    main()
