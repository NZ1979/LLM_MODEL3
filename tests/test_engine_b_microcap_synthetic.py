"""Engine B microcap experiment - synthetic correctness + leak audit suite.

Run in the Claude-side sandbox (or Godzilla .venv) on SYNTHETIC data ONLY, so the
microcap result on the real panel stays UNOBSERVED until this code is committed
(A-2 discipline). Mirrors tests/test_engine_b_synthetic.py.

Checks (each a hard PASS/FAIL, non-zero exit on any failure - Rule 18):

  1. BASELINE INVARIANT - the parameterised screen with the BASELINE bands
     reproduces the frozen screen's `eligible` column row-for-row (guarantees the
     frozen baseline bb3b8e9 is untouched by the refactor).
  2. BAND SELECTION - the parameterised screen admits exactly the intended
     size/liquidity/price band and rejects names outside it.
  3. COST MONOTONICITY - side cost rises with participation and with tier
     (micro > liquid; larger order/ADV -> higher bps); tiers map by marketcap.
  4. WEIGHT CAPS - capped_weights never exceeds min(size_cap, MAX_WEIGHT), sums to
     min(1, sum caps); capacity binds (sum<1, cash residual) when liquidity is thin.
  5. BUFFER TURNOVER - the D10-in/<D8-out quarterly buffer has STRICTLY lower
     turnover than a naive monthly-D10 rebalance on the same signal.
  6. DELISTING FOLD - a name delisting mid-hold REALISES its delisting return in
     that month (not a silent drop) and is counted.
  7. BOOK SMOKE + CAPACITY - end-to-end screen->factors->book on a microcap panel
     runs, recovers a positive book, and invested fraction FALLS as AUM rises.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

import duckdb  # noqa: E402,F401  (imported for parity / availability check)
from data import sharadar_panel as sp  # noqa: E402
from models import engine_b_universe as ebu  # noqa: E402
from models import engine_b_universe_micro as ebum  # noqa: E402
from models import engine_b_factors as ebf  # noqa: E402
from models import engine_b_portfolio as ebp  # noqa: E402
from validation import costs_microcap as cm  # noqa: E402
from tests.test_engine_b_synthetic import make_panel, _run_build  # noqa: E402

_FAILS: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    tag = "PASS" if cond else "FAIL"
    print(f"  [{tag}] {name}" + (f" :: {detail}" if detail else ""))
    if not cond:
        _FAILS.append(name)


# ---------------------------------------------------------------------------
def _synth_cross_section() -> pd.DataFrame:
    """A hand-built cross-section (one date) spanning size/liquidity/price bands."""
    rows = [
        # (pt, mktcap, dollarvol, price)  - all Domestic Common Stock, NYSE, 300 hist
        (1, 150.0, 1_000_000, 10.0),   # micro, liquid enough, priced -> micro-eligible
        (2, 40.0, 800_000, 8.0),       # nano
        (3, 500.0, 6_000_000, 20.0),   # liquid small/mid (baseline band)
        (4, 150.0, 100_000, 10.0),     # micro size but below $250k liquidity floor
        (5, 150.0, 1_000_000, 3.0),    # micro size/liq but below $5 price floor
        (6, 8.0, 900_000, 12.0),       # below nano floor ($10M)
        (7, 20000.0, 50_000_000, 100.0),  # mega-cap (above baseline $15B)
        (8, 250.0, 400_000, 6.0),      # micro, on the $250k floor edge (>=250k ok)
    ]
    df = pd.DataFrame([
        dict(date=pd.Timestamp("2015-06-30"), permaticker=pt,
             category="Domestic Common Stock", exchange="NYSE",
             close_T=px, mktcap_T=mc, dollarvol_60=dv, hist_days=300)
        for pt, mc, dv, px in rows
    ])
    return df


def test_baseline_invariant():
    print("\n[1] BASELINE INVARIANT - parameterised screen == frozen screen (BASELINE bands)")
    # on a real _build output (realistic dtypes/NaNs)
    tk, sep, daily, fund = make_panel(seed=7)
    built = _run_build(tk, sep, daily, fund, "2016-01-01", "2019-05-31")
    frozen = ebu.screen(built)["eligible"].to_numpy()
    param = ebum.screen(built, ebum.BASELINE)["eligible"].to_numpy()
    n_diff = int((frozen != param).sum())
    check("frozen vs parameterised(BASELINE) eligible identical (real _build)",
          n_diff == 0, f"{n_diff} of {len(frozen)} rows differ")
    # and on the hand-built cross-section
    df = _synth_cross_section()
    f2 = ebu.screen(df)["eligible"].to_numpy()
    p2 = ebum.screen(df, ebum.BASELINE)["eligible"].to_numpy()
    check("frozen vs parameterised(BASELINE) eligible identical (hand-built)",
          bool((f2 == p2).all()), f"frozen={f2.tolist()} param={p2.tolist()}")


def test_band_selection():
    print("\n[2] BAND SELECTION - micro/nano/full-tail screens admit the right names")
    df = _synth_cross_section()
    micro = ebum.screen(df, ebum.MICRO).set_index("permaticker")["eligible"]
    check("micro admits the $150M/$1M/$10 name (pt1)", bool(micro.loc[1]))
    check("micro rejects the $500M name (pt3, above $300M)", not bool(micro.loc[3]))
    check("micro rejects the $40M name (pt2, below $50M)", not bool(micro.loc[2]))
    check("micro rejects the sub-$250k-liquidity name (pt4)", not bool(micro.loc[4]))
    check("micro rejects the sub-$5 price name (pt5)", not bool(micro.loc[5]))
    check("micro admits the $250k-liquidity edge name (pt8, >=250k)", bool(micro.loc[8]))
    nano = ebum.screen(df, ebum.NANO).set_index("permaticker")["eligible"]
    check("nano admits the $40M name (pt2)", bool(nano.loc[2]))
    check("nano rejects the $8M name (pt6, below $10M)", not bool(nano.loc[6]))
    check("nano rejects the $150M name (pt1, above $50M)", not bool(nano.loc[1]))
    ft = ebum.screen(df, ebum.FULL_TAIL).set_index("permaticker")["eligible"]
    check("full-tail admits both micro (pt1) and nano (pt2)",
          bool(ft.loc[1]) and bool(ft.loc[2]))
    check("full-tail rejects the $500M liquid name (pt3)", not bool(ft.loc[3]))
    # sensitivity floors compose
    b = ebum.with_floors(ebum.MICRO, dollarvol_min=100_000.0, price_min=2.0)
    loose = ebum.screen(df, b).set_index("permaticker")["eligible"]
    check("loosened floors ($100k/$2) now admit pt4 and pt5",
          bool(loose.loc[4]) and bool(loose.loc[5]))


def test_cost_monotonicity():
    print("\n[3] COST MONOTONICITY - participation, tier, and marketcap tiering")
    hs_micro = cm.HALF_SPREAD_BPS["micro"]
    c_lo = cm.side_cost_bps(0.01, hs_micro)
    c_hi = cm.side_cost_bps(0.25, hs_micro)
    check("cost rises with participation (micro)", c_hi > c_lo, f"{c_lo:.1f} -> {c_hi:.1f} bps")
    c_liq = cm.side_cost_bps(0.05, cm.HALF_SPREAD_BPS["liquid"])
    c_mic = cm.side_cost_bps(0.05, cm.HALF_SPREAD_BPS["micro"])
    c_nan = cm.side_cost_bps(0.05, cm.HALF_SPREAD_BPS["nano"])
    check("micro cost > liquid cost at equal participation", c_mic > c_liq,
          f"liquid {c_liq:.1f} < micro {c_mic:.1f}")
    check("nano cost > micro cost at equal participation", c_nan > c_mic,
          f"micro {c_mic:.1f} < nano {c_nan:.1f}")
    check("cost scales linearly with the 2x sensitivity",
          abs(cm.side_cost_bps(0.05, hs_micro, scale=2.0)
              - 2 * cm.side_cost_bps(0.05, hs_micro, scale=1.0)) < 1e-9)
    check("tier_for_marketcap: 30->nano, 150->micro, 1000->liquid",
          cm.tier_for_marketcap(30.0) == "nano"
          and cm.tier_for_marketcap(150.0) == "micro"
          and cm.tier_for_marketcap(1000.0) == "liquid")
    arr = cm.half_spread_for(np.array([30.0, 150.0, 1000.0]))
    check("half_spread_for vectorises", arr.tolist()
          == [cm.HALF_SPREAD_BPS["nano"], cm.HALF_SPREAD_BPS["micro"], cm.HALF_SPREAD_BPS["liquid"]])


def test_weight_caps():
    print("\n[4] WEIGHT CAPS - water-fill respects caps and surfaces capacity")
    params = ebp.BookParams()  # max_weight 0.03, adv_mult 10
    # 50 names so EW target (1/50 = 2%) is BELOW the 3% cap -> EW binds, sum=1.
    # (With < 34 names the 3% cap alone prevents full investment - that is the cap
    # working as specified, not a defect; the book targets ~50-100 names.)
    names = list(range(50))
    dv_big = {pt: 5_000_000.0 for pt in names}
    w = ebp.capped_weights(names, dv_big, aum=1_000_000.0, params=params)
    check("generous liquidity, 50 names -> equal weight ~1/n", abs(w[0] - 1 / 50) < 1e-9,
          f"w0={w[0]:.4f}")
    check("generous liquidity, 50 names -> fully invested (sum~1)",
          abs(sum(w.values()) - 1.0) < 1e-9, f"sum={sum(w.values()):.4f}")
    # and the 3% cap correctly prevents full investment with too few names
    few = ebp.capped_weights(list(range(20)), {pt: 5e6 for pt in range(20)},
                             aum=1_000_000.0, params=params)
    check("20 names at 3% cap -> intentionally not fully invested (~60%)",
          abs(sum(few.values()) - 0.60) < 1e-9, f"sum={sum(few.values()):.4f}")
    # thin liquidity for all: size cap binds below EW -> sum < 1 (cash), each <= cap.
    # 20 names x 0.02 cap = 0.40 invested, 0.60 cash.
    thin_names = list(range(20))
    dv_small = {pt: 2_000.0 for pt in thin_names}  # 10*2000/1e6 = 0.02 cap < 1/20=0.05
    w2 = ebp.capped_weights(thin_names, dv_small, aum=1_000_000.0, params=params)
    cap = 10 * 2_000.0 / 1_000_000.0
    check("thin liquidity -> every weight at the size cap", all(abs(v - cap) < 1e-9 for v in w2.values()),
          f"cap={cap:.4f}, w0={w2[0]:.4f}")
    check("thin liquidity -> capacity binds (sum<1, cash residual)",
          sum(w2.values()) < 0.9999, f"sum={sum(w2.values()):.4f}")
    # 3% hard cap: one huge-liquidity name cannot exceed max_weight
    dv_mix = {0: 1e12}
    dv_mix.update({pt: 5_000_000.0 for pt in names[1:]})
    w3 = ebp.capped_weights(names, dv_mix, aum=1_000_000.0, params=params)
    check("no weight exceeds MAX_WEIGHT (3%)", max(w3.values()) <= params.max_weight + 1e-12,
          f"max={max(w3.values()):.4f}")
    check("all weights within their caps and sum<=1",
          all(v <= params.max_weight + 1e-12 for v in w3.values())
          and sum(w3.values()) <= 1.0 + 1e-9)


def _scored_panel(n_months=12, seed=0, generous_liq=True, rotate=True):
    """Synthetic scored+labelled panel with controllable decile membership.

    30 names; a stable top group stays in D9/D10 across months, a rotating group
    churns D10 membership month to month (so naive monthly-D10 has real turnover).
    """
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2015-01-31", periods=n_months, freq="ME")
    n = 30
    rows = []
    dv = 5_000_000.0 if generous_liq else 300_000.0
    for mi, d in enumerate(dates):
        # base composite: names 0..9 always highest (stable), 10..19 rotate, 20..29 low
        comp = np.zeros(n)
        comp[:10] = 5.0 + rng.normal(0, 0.1, 10)          # stable leaders
        rot = np.arange(10, 20)
        if rotate:
            rng.shuffle(rot)
        comp[10:20] = np.linspace(4.0, 1.0, 10)[np.argsort(rot)]  # churn mid
        comp[20:] = -2.0 + rng.normal(0, 0.1, 10)          # laggards
        order = np.argsort(np.argsort(comp))  # ranks
        dec = (order / n * 10).astype(int) + 1
        dec = np.clip(dec, 1, 10)
        for pt in range(n):
            rows.append(dict(date=d, permaticker=pt, decile=int(dec[pt]),
                             composite=float(comp[pt]),
                             fwd_ret_21=float(0.01 * (dec[pt] - 5) + rng.normal(0, 0.02)),
                             fwd_status="ok", dollarvol_60=dv, mktcap_T=150.0))
    return pd.DataFrame(rows)


def _naive_monthly_d10_turnover(panel):
    dates = sorted(panel["date"].unique())
    by = {d: g.set_index("permaticker") for d, g in panel.groupby("date")}
    prev = {}
    turns = []
    for d in dates:
        present = by[d]
        names = list(present[present["decile"] == 10].index)
        n = len(names)
        w = {pt: 1.0 / n for pt in names} if n else {}
        keys = set(w) | set(prev)
        turns.append(sum(abs(w.get(k, 0.0) - prev.get(k, 0.0)) for k in keys))
        prev = w
    return float(np.mean(turns))


def test_buffer_turnover():
    print("\n[5] BUFFER TURNOVER - quarterly D10-in/<D8-out < naive monthly-D10")
    panel = _scored_panel(n_months=12, seed=1, generous_liq=True, rotate=True)
    naive = _naive_monthly_d10_turnover(panel)
    bk = ebp.build_book(panel, aum=1_000_000.0, cost_scale=1.0)
    buffered = float(bk["monthly"]["turnover"].mean())
    check("naive monthly-D10 has real turnover (>0)", naive > 0.0, f"naive avg turnover={naive:.3f}")
    check("buffered avg turnover strictly < naive", buffered < naive,
          f"buffered={buffered:.3f} < naive={naive:.3f}")
    reb = bk["diagnostics"]["n_rebalances"]
    check("book trades only on rebalance months (~1/3 of months)",
          reb <= (12 // 3) + 1, f"{reb} rebalances over 12 months")
    check("book holds a diversified set", bk["diagnostics"]["median_n_held"] >= 5,
          f"median n_held={bk['diagnostics']['median_n_held']}")


def test_delisting_fold():
    print("\n[6] DELISTING FOLD - a mid-hold delist realises its return, not a silent drop")
    # single quarter: buy at month 0; name X delists at month 1 with fwd_ret_21=-0.9,
    # all other held names earn 0 that month -> book month-1 gross must = w_X * -0.9.
    dates = pd.date_range("2015-01-31", periods=3, freq="ME")
    n = 12
    rows = []
    for mi, d in enumerate(dates):
        for pt in range(n):
            dec = 10 if pt < 11 else 1
            ret = 0.0
            status = "ok"
            present = True
            if pt == 0 and mi == 1:            # X delists at month 1
                ret, status = -0.9, "delisted_partial"
            if pt == 0 and mi == 2:            # gone from the panel afterwards
                present = False
            if present:
                rows.append(dict(date=d, permaticker=pt, decile=dec, composite=float(dec),
                                 fwd_ret_21=ret, fwd_status=status,
                                 dollarvol_60=5_000_000.0, mktcap_T=150.0))
    panel = pd.DataFrame(rows)
    # max_weight=1.0 removes the per-name cap so weights are pure EW 1/11 -> this
    # isolates the delisting-fold logic from the (separately tested) 3% cap.
    bk = ebp.build_book(panel, aum=1_000_000.0, cost_scale=1.0,
                        params=ebp.BookParams(rebalance_every=3, max_weight=1.0))
    m = bk["monthly"]
    w_x = 1.0 / 11  # equal weight among the 11 D10 names, no cap, generous liquidity
    gross_m1 = float(m["gross"].iloc[1])
    check("delisting name X is counted as delisted-held at month 1",
          int(m["n_delisted_held"].iloc[1]) >= 1, f"n_delisted_held={int(m['n_delisted_held'].iloc[1])}")
    check("book realises X's -90% return (not a silent drop)",
          abs(gross_m1 - w_x * (-0.9)) < 1e-6,
          f"gross_m1={gross_m1:.5f} expected={w_x * -0.9:.5f}")


def _micro_built(seed=5, n_names=120, n_months=30):
    """A built-panel-shaped microcap cross-section with a planted momentum signal."""
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2015-01-31", periods=n_months, freq="ME")
    alphas = np.linspace(-0.02, 0.02, n_names)
    rng.shuffle(alphas)
    rows = []
    # a few names delist partway
    delist_at = {i: rng.integers(8, n_months) for i in range(0, n_names, 25)}
    for pt in range(n_names):
        mc = float(rng.uniform(30.0, 280.0))          # microcap band
        dv = float(rng.uniform(3e5, 5e6))             # above the $250k floor
        base_ret = alphas[pt]
        for mi, d in enumerate(dates):
            if pt in delist_at and mi > delist_at[pt]:
                continue
            status = "ok"
            r = base_ret + rng.normal(0, 0.05)
            if pt in delist_at and mi == delist_at[pt]:
                status, r = "delisted_partial", -0.6
            rows.append(dict(date=d, permaticker=pt,
                             close_T=float(rng.uniform(6, 40)), mktcap_T=mc,
                             dollarvol_60=dv, hist_days=400,
                             mom_12_1=base_ret * 20 + rng.normal(0, 0.05),
                             vol_252=float(rng.uniform(0.01, 0.04)),
                             eps=float(rng.uniform(0.2, 5)), bvps=float(rng.uniform(2, 40)),
                             gp=float(rng.uniform(50, 500)), assets=float(rng.uniform(200, 3000)),
                             category="Domestic Common Stock", exchange="NASDAQ",
                             fwd_ret_21=r, fwd_status=status))
    return pd.DataFrame(rows)


def test_book_smoke_and_capacity():
    print("\n[7] BOOK SMOKE + CAPACITY - end-to-end microcap screen->factors->book")
    built = _micro_built()
    screened = ebum.screen(built, ebum.MICRO)
    elig = screened[screened["eligible"]].copy()
    check("micro screen admits a workable universe", elig["permaticker"].nunique() >= 30,
          f"{elig['permaticker'].nunique()} names eligible")
    scores = ebf.compute_scores(elig)
    panel = scores.merge(built[["date", "permaticker", "fwd_ret_21", "fwd_status",
                                "dollarvol_60", "mktcap_T"]],
                         on=["date", "permaticker"], how="left")
    part = {}
    cost = {}
    inv = {}
    sharpe = {}
    for aum in (0.1e6, 0.5e6, 2.0e6, 5.0e6):
        bk = ebp.build_book(panel, aum=aum, cost_scale=1.0)
        part[aum] = bk["diagnostics"]["avg_participation"]
        cost[aum] = float(bk["monthly"]["cost"].sum())
        inv[aum] = bk["diagnostics"]["avg_invested_frac"]
        sharpe[aum] = bk["net_stats"]["sharpe"]
    check("book produces finite net Sharpe at $0.5M", np.isfinite(sharpe[0.5e6]),
          f"sharpe@0.5M={sharpe[0.5e6]:.2f}")
    # in the $0.1-5M range the binding capacity channel is IMPACT COST (participation),
    # not the position-size cap (which only bites ~>$80M in-band): participation and
    # total cost must both RISE with AUM.
    check("participation rises with AUM (impact channel)", part[5.0e6] > part[0.1e6],
          f"part@0.1M={part[0.1e6]:.4f} -> part@5M={part[5.0e6]:.4f}")
    check("total realised cost rises with AUM", cost[5.0e6] > cost[0.1e6],
          f"cost@0.1M={cost[0.1e6]:.4f} -> cost@5M={cost[5.0e6]:.4f}")
    # at a deliberately large AUM the size cap DOES bind -> invested fraction drops
    big = ebp.build_book(panel, aum=200.0e6, cost_scale=1.0)
    check("size cap engages at $200M -> invested fraction falls vs $0.1M",
          big["diagnostics"]["avg_invested_frac"] < inv[0.1e6] - 1e-6,
          f"inv@0.1M={inv[0.1e6]:.2f} -> inv@200M={big['diagnostics']['avg_invested_frac']:.2f}")
    check("planted momentum -> positive book gross at small AUM",
          ebp.build_book(panel, aum=0.1e6, cost_scale=1.0)["gross_stats"]["ann_return"] > 0,
          "gross ann_return > 0")


def main():
    print("=" * 78)
    print("ENGINE B MICROCAP - SYNTHETIC CORRECTNESS + LEAK AUDIT  (real panel NOT touched)")
    print("=" * 78)
    test_baseline_invariant()
    test_band_selection()
    test_cost_monotonicity()
    test_weight_caps()
    test_buffer_turnover()
    test_delisting_fold()
    test_book_smoke_and_capacity()
    print("\n" + "=" * 78)
    if _FAILS:
        print(f"RESULT: {len(_FAILS)} FAILED -> {_FAILS}")
        sys.exit(1)
    print("RESULT: ALL CHECKS PASSED")


if __name__ == "__main__":
    main()
