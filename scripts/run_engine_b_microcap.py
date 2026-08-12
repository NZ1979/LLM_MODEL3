"""Engine B microcap experiment - measuring run (docs/ENGINE_B_MICROCAP_SPEC.md).

Screen the microcap tiers -> frozen five factors -> frozen IC/decile/leak audit
-> buffered quarterly long-only book under the realistic microcap cost model, over
the tier x AUM x cost-scale grid, with the passive benchmark (equal-weight
eligible universe + SPY). Everything PRINTED, nothing written to disk, so no
result can share the pre-registered spec's commit.

DISCIPLINE (A-2): commit this + the new modules BEFORE any run on the real panel.
Build/leak-audit on 1998-2020 first; touch 2021+ ONCE, only after the build is
clean.

  python scripts/run_engine_b_microcap.py --span build
  python scripts/run_engine_b_microcap.py --span holdout --confirm-holdout

Run on GODZILLA in the repo .venv (the panel parquet lives there; the sandbox is
firewalled). Reads data/raw/sharadar/*.parquet and (for SPY) data/raw/tiingo_eod/SPY.parquet.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from data import sharadar_panel as sp              # noqa: E402
from models import engine_b_universe_micro as ebum  # noqa: E402
from models import engine_b_factors as ebf          # noqa: E402
from models import engine_b_portfolio as ebp        # noqa: E402
from validation import engine_b_harness as ebh      # noqa: E402
from validation import costs_microcap as cm         # noqa: E402

SPANS = {
    "build":   ("1998-01-01", "2020-12-31"),
    "holdout": ("2021-01-01", "2026-12-31"),
}
DEFAULT_RAW = _REPO / "data" / "raw" / "sharadar"
SPY_PARQUET = _REPO / "data" / "raw" / "tiingo_eod" / "SPY.parquet"

# a-priori grids (fixed here before any result; no dredge)
AUM_GRID = (0.1e6, 0.5e6, 2.0e6, 5.0e6)     # $0.1M / $0.5M / $2M / $5M (addendum)
LIQUID_BASELINE_IC = 0.0254                  # frozen build IC (docs/ENGINE_B_BASELINE_RESULTS.md)
LIQUID_BASELINE_D10_SHARPE = 0.54            # frozen naive-D10 long-only Sharpe (reference only)
SLEEVE_AUM_FOR_DECISION = (0.5e6, 2.0e6)     # decision rule reads net Sharpe at $0.5-2M
DECISION_MARGIN = 0.20                        # net Sharpe must beat liquid by >= this


def _fmt(x, pct=False, dp=2):
    if x is None or (isinstance(x, float) and not np.isfinite(x)):
        return "  n/a"
    return f"{x*100:.{dp}f}%" if pct else f"{x:.{dp}f}"


def score_band(built: pd.DataFrame, bands: ebum.UniverseBands) -> dict:
    """Screen -> factors -> harness panel for one band. Returns pieces + delist rate."""
    screened = ebum.screen(built, bands)
    ucov = ebum.coverage_report(screened)
    elig = screened[screened["eligible"]].copy()
    scores = ebf.compute_scores(elig)
    rank_cov = ebf.ranking_coverage(scores)
    panel = scores.merge(
        built[["date", "permaticker", "fwd_ret_21", "fwd_status",
               "dollarvol_60", "mktcap_T"]],
        on=["date", "permaticker"], how="left")
    # delisting rate among eligible name-months (Rule 18). `elig` already carries
    # fwd_status (a column of the built panel copied through the screen).
    n_elig = len(elig)
    n_delist = int((elig["fwd_status"] == "delisted_partial").sum())
    delist_rate = (n_delist / n_elig) if n_elig else float("nan")
    return dict(panel=panel, ucov=ucov, rank_cov=rank_cov,
                n_elig=n_elig, delist_rate=delist_rate,
                median_eligible=int(ucov["eligible"].median()) if len(ucov) else 0)


def spy_monthly(reb_dates) -> pd.Series | None:
    """SPY month-to-month total return aligned to the rebalance dates (adj_close).

    Returns a Series indexed by rebalance date (T_m return = level[T_{m+1}]/level[T_m]-1)
    or None if the SPY parquet is absent (degrade loud in the caller, Rule 18).
    """
    if not SPY_PARQUET.exists():
        return None
    spy = pd.read_parquet(SPY_PARQUET)
    col = "adj_close" if "adj_close" in spy.columns else "close"
    spy = spy[["date", col]].dropna().sort_values("date")
    dts = spy["date"].values.astype("datetime64[ns]")
    vals = spy[col].values.astype(float)

    def asof(T):
        k = np.searchsorted(dts, np.datetime64(pd.Timestamp(T)), side="right") - 1
        return float(vals[k]) if k >= 0 else np.nan

    reb = sorted(reb_dates)
    levels = np.array([asof(T) for T in reb])
    rets = levels[1:] / levels[:-1] - 1.0
    return pd.Series(rets, index=pd.DatetimeIndex(reb[:-1]))


def print_band(name: str, sb: dict, run_leak: bool, aum_grid, cost_scales,
               spy_stats: dict | None) -> dict:
    """Print one band's IC/decile/leak + the AUM x cost book grid. Return a summary."""
    panel = sb["panel"]
    W = 82
    print("\n" + "=" * W)
    print(f"BAND: {name}   [median eligible {sb['median_eligible']}/month, "
          f"delisting rate {_fmt(sb['delist_rate'], pct=True)} of eligible name-months]")
    print("=" * W)

    res = ebh.evaluate(panel)
    ic = res["ic_summary"]
    mono = res["monotonicity"]
    print(f"[IC] mean {ic['mean_ic']:+.4f} (median {ic['median_ic']:+.4f}), "
          f"NW-t {ic['nw_tstat']:+.2f}, IC>0 {_fmt(ic['frac_positive'], pct=True, dp=0)} "
          f"of {ic['n_months']} mo   vs liquid baseline +{LIQUID_BASELINE_IC:.4f}")
    print(f"[DECILE] Spearman(dec,ret) {_fmt(mono['spearman_ret'])}, "
          f"Spearman(dec,Sharpe) {_fmt(mono['spearman_sharpe'])}, "
          f"D10-D1 {_fmt(mono['d10_minus_d1_ret'], pct=True)}")

    if run_leak:
        audit = ebh.leak_audit(panel)
        print(f"[LEAK] cheat IC {audit['cheat_mean_ic']:+.3f} / decile "
              f"{audit['cheat_spearman_decile']:+.3f} (expect ~+1); null mean "
              f"{audit['shuffle_null_mean']:+.4f} SD {audit['shuffle_null_sd']:.4f}; "
              f"real IC {audit['real_mean_ic']:+.4f} = {audit['real_vs_null_z']:+.1f} SD "
              f"above null")
        if ic["mean_ic"] > 0.12 or (np.isfinite(mono["spearman_ret"])
                                    and mono["spearman_ret"] > 0.99
                                    and np.isfinite(mono["spearman_sharpe"])
                                    and mono["spearman_sharpe"] > 0.99):
            print("  ** IC > 0.12 or a perfect staircase => ASSUME LEAKAGE. Audit "
                  "survivorship/join before trusting (spec 'Anticipated outcome'). **")

    # passive benchmark: equal-weight eligible universe
    ewu = ebp.equal_weight_universe(panel)["stats"]
    print(f"[BENCHMARK] equal-weight eligible universe (gross, hold-all): "
          f"Sharpe {_fmt(ewu['sharpe'])}, CAGR {_fmt(ewu['cagr'], pct=True)}, "
          f"maxDD {_fmt(ewu['max_drawdown'], pct=True)}")
    if spy_stats is not None:
        print(f"            SPY (Tiingo adj_close, gross): Sharpe {_fmt(spy_stats['sharpe'])}, "
              f"CAGR {_fmt(spy_stats['cagr'], pct=True)}, maxDD {_fmt(spy_stats['max_drawdown'], pct=True)}")
    else:
        print("            SPY benchmark UNAVAILABLE: no data/raw/tiingo_eod/SPY.parquet "
              "(run `python data/tiingo_eod.py SPY` on Godzilla to enable).")

    # book grid: AUM x cost-scale
    print("\n[BOOK] buffered quarterly long-only, NET of realistic cost")
    print(f"  {'AUM':>7}  {'cost':>4}  {'Sharpe':>6}  {'CAGR':>7}  {'maxDD':>7}  "
          f"{'turn/reb':>8}  {'nHeld':>5}  {'inv%':>5}  {'partMean':>8}")
    grid = {}
    for aum in aum_grid:
        for cs in cost_scales:
            bk = ebp.build_book(panel, aum=aum, cost_scale=cs)
            st = bk["net_stats"]
            dg = bk["diagnostics"]
            grid[(aum, cs)] = dict(stats=st, diag=dg)
            print(f"  {aum/1e6:>5.1f}M  {cs:>3.1f}x  {_fmt(st['sharpe']):>6}  "
                  f"{_fmt(st['cagr'], pct=True):>7}  {_fmt(st['max_drawdown'], pct=True):>7}  "
                  f"{_fmt(dg['avg_turnover_reb_months']):>8}  {dg['median_n_held']:>5}  "
                  f"{_fmt(dg['avg_invested_frac'], pct=True, dp=0):>5}  {_fmt(dg['avg_participation']):>8}")
    return {"ic": ic, "mono": mono, "grid": grid, "ewu": ewu}


def main() -> None:
    ap = argparse.ArgumentParser(description="Engine B microcap experiment measuring run")
    ap.add_argument("--span", choices=list(SPANS), required=True)
    ap.add_argument("--raw-dir", default=str(DEFAULT_RAW))
    ap.add_argument("--confirm-holdout", action="store_true")
    ap.add_argument("--quick", action="store_true",
                    help="primary micro band only (skip nano/full-tail/sensitivities) - dev smoke")
    args = ap.parse_args()

    span = SPANS[args.span]
    if args.span == "holdout" and not args.confirm_holdout:
        sys.exit("REFUSED: the 2021+ hold-out is touched ONCE, only after the build "
                 "run is audited clean. Re-run with --confirm-holdout if that is the case.")

    print(f"Assembling PIT panel for span '{args.span}' {span} ...")
    built = sp.build_panel_from_parquet(args.raw_dir, span[0], span[1], verbose=True)
    reb_dates = sorted(built["date"].unique())
    spy = spy_monthly(reb_dates)
    spy_stats = ebp.curve_stats(spy) if spy is not None else None

    W = 82
    print("\n" + "#" * W)
    print(f"# ENGINE B MICROCAP EXPERIMENT - span '{args.span}' [{span[0]} .. {span[1]}]")
    print("#   per docs/ENGINE_B_MICROCAP_SPEC.md - all book figures NET of realistic cost")
    print("#   cost model: half-spread liquid/micro/nano = "
          f"{cm.HALF_SPREAD_BPS['liquid']:.0f}/{cm.HALF_SPREAD_BPS['micro']:.0f}/"
          f"{cm.HALF_SPREAD_BPS['nano']:.0f} bps, IMPACT_K={cm.IMPACT_K:.0f}, "
          f"commission {cm.COMMISSION_BPS:.0f}bps/side")
    print("#" * W)

    summaries = {}
    # primary band + size tiers + liquid comparison, all at primary floors ($250k, $5)
    bands = [("micro (PRIMARY)", ebum.MICRO, True),
             ("liquid (comparison)", ebum.BASELINE, True)]
    if not args.quick:
        bands += [("nano", ebum.NANO, True),
                  ("full_tail", ebum.FULL_TAIL, True)]
    for name, band, leak in bands:
        sb = score_band(built, band)
        summaries[name] = print_band(name, sb, leak, AUM_GRID, cm.COST_SCALES, spy_stats)

    # a-priori sensitivities on the MICRO band: liquidity {100k,250k,500k} x price {2,5}
    if not args.quick:
        print("\n" + "=" * W)
        print("MICRO-BAND SENSITIVITIES (IC and net Sharpe @ $1M AUM, 1x cost)")
        print("=" * W)
        print(f"  {'liq floor':>9}  {'px floor':>8}  {'meanIC':>7}  {'NW-t':>5}  {'netSharpe':>9}  {'medElig':>7}")
        for liq in (100_000.0, 250_000.0, 500_000.0):
            for px in (2.0, 5.0):
                b = ebum.with_floors(ebum.MICRO, dollarvol_min=liq, price_min=px)
                sb = score_band(built, b)
                panel = sb["panel"]
                ic = ebh.ic_summary(ebh.rank_ic_series(panel))
                bk = ebp.build_book(panel, aum=1.0e6, cost_scale=1.0)
                print(f"  {liq/1e3:>7.0f}k  {px:>7.0f}$  {ic['mean_ic']:>+7.4f}  "
                      f"{ic['nw_tstat']:>+5.1f}  {_fmt(bk['net_stats']['sharpe']):>9}  "
                      f"{sb['median_eligible']:>7}")

    # ---- decision-rule readout (build-span portion; holdout evaluated once) ----
    print("\n" + "#" * W)
    print("# DECISION-RULE READOUT (a priori; both spans must pass to adopt microcaps)")
    print("#" * W)
    micro = summaries.get("micro (PRIMARY)")
    liquid = summaries.get("liquid (comparison)")
    if micro and liquid:
        def sharpe_at(summ, cs):
            vals = [summ["grid"][(aum, cs)]["stats"]["sharpe"]
                    for aum in SLEEVE_AUM_FOR_DECISION
                    if (aum, cs) in summ["grid"]]
            vals = [v for v in vals if np.isfinite(v)]
            return float(np.mean(vals)) if vals else float("nan")
        micro_1x = sharpe_at(micro, 1.0)
        micro_2x = sharpe_at(micro, 2.0)
        liquid_1x = sharpe_at(liquid, 1.0)
        margin_1x = micro_1x - liquid_1x
        margin_2x = micro_2x - liquid_1x
        print(f"  net tradeable Sharpe @ $0.5-2M (mean), same construction+cost:")
        print(f"    micro  1x cost: {_fmt(micro_1x)}   2x cost: {_fmt(micro_2x)}")
        print(f"    liquid 1x cost: {_fmt(liquid_1x)}   (frozen naive-D10 reference "
              f"{LIQUID_BASELINE_D10_SHARPE:.2f})")
        print(f"  margin over liquid: 1x {_fmt(margin_1x)}  |  2x {_fmt(margin_2x)}  "
              f"(need >= +{DECISION_MARGIN:.2f} on BOTH, and IC>0 + monotone)")
        ic_ok = micro["ic"]["mean_ic"] > 0
        mono_ok = (np.isfinite(micro["mono"]["spearman_sharpe"])
                   and micro["mono"]["spearman_sharpe"] > 0.5)
        margin_ok = (margin_1x >= DECISION_MARGIN) and (margin_2x >= DECISION_MARGIN)
        verdict = "QUALIFIES (this span)" if (ic_ok and mono_ok and margin_ok) else "does NOT qualify (this span)"
        print(f"  THIS-SPAN READ: IC>0 {ic_ok}, monotone {mono_ok}, "
              f"margin>=+{DECISION_MARGIN:.2f} both-cost {margin_ok}  ->  {verdict}")
        print("  (Adoption requires BOTH the 1998-2020 build AND the once-touched 2021+ "
              "hold-out to qualify. A higher gross IC alone does NOT qualify.)")
    print("\n(Results printed only - NOT written to disk. Paste this whole output back.)")


if __name__ == "__main__":
    main()
