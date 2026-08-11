"""Engine B (P3) - synthetic-data leak audit and correctness suite.

Run in the Claude-side sandbox (or Godzilla .venv) on SYNTHETIC data ONLY, so
that Engine B's performance on the real panel stays UNOBSERVED until this code
is committed (the A-2 discipline: commit before any measuring run).

Six checks, each a hard PASS/FAIL (exits non-zero on any failure, Rule 18):

  1. TIMING ORACLE  - data/sharadar_panel._build (DuckDB windows/ASOF) is
     cross-checked field-by-field against an INDEPENDENT pandas re-implementation
     on the same synthetic tables. A windowing/label leak would make the two
     disagree. This is the load-bearing correctness test for the timing layer.
  2. ATTRIBUTION    - a recycled ticker (two permatickers, disjoint windows) is
     split to the correct permaticker; prices never graft across the recycle.
  3. AMBIGUITY FAIL - overlapping windows for one ticker make _build fail loud.
  4. PIT FUND JOIN  - a filing dated just AFTER T is NOT used at T (datekey<=T).
  5. POSITIVE + NULL - a planted momentum signal yields clearly positive rank-IC
     and a rising decile staircase; pure noise yields IC ~ 0. Proves the harness
     can see real signal without manufacturing it.
  6. LEAK TRIPWIRE  - scoring on the realised forward return (a deliberate
     look-ahead) drives IC ~ +1 and a perfect staircase; a within-date shuffle
     drives IC ~ 0. Proves the harness lands in the 'assume leakage' zone when a
     look-ahead exists, so a modest real IC is trustworthy.
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

import duckdb  # noqa: E402
from data import sharadar_panel as sp  # noqa: E402
from models import engine_b_universe as ebu  # noqa: E402
from models import engine_b_factors as ebf  # noqa: E402
from validation import engine_b_harness as ebh  # noqa: E402

TOL = 1e-6
_FAILS: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    tag = "PASS" if cond else "FAIL"
    print(f"  [{tag}] {name}" + (f" :: {detail}" if detail else ""))
    if not cond:
        _FAILS.append(name)


# ---------------------------------------------------------------------------
# Synthetic panel generator
# ---------------------------------------------------------------------------
def _bdays(start: str, end: str) -> pd.DatetimeIndex:
    return pd.bdate_range(start, end)


def make_panel(seed: int, n_names: int = 30, alpha_scale: float = 0.0009,
               sigma: float = 0.02, start="2015-01-01", end="2019-12-31"):
    """Generate synthetic Sharadar-shaped tables with a planted momentum signal.

    Each name i has a fixed latent daily drift alpha_i spread across names, so
    both its trailing momentum and its forward return are monotone in alpha_i
    (a genuine, non-leaking cross-sectional signal). alpha_scale=0 -> pure noise.
    Includes one recycled ticker and one mid-panel delisting.
    """
    rng = np.random.default_rng(seed)
    days = _bdays(start, end)
    nd = len(days)
    alphas = np.linspace(-alpha_scale, alpha_scale, n_names)
    rng.shuffle(alphas)
    # common market + sector shocks make returns cross-sectionally correlated, with
    # sectors on CONTIGUOUS permaticker blocks (as in the real panel). This exercises
    # the leak-audit shuffle control under realistic adjacency: a naive roll-by-1
    # shuffle would trip on it; a true permutation must not.
    n_sectors = max(2, n_names // 8)
    sector_of = np.repeat(np.arange(n_sectors),
                          int(np.ceil(n_names / n_sectors)))[:n_names]
    mkt = 0.006 * rng.standard_normal(nd)
    sec = 0.005 * rng.standard_normal((nd, n_sectors))

    tickers, sep, daily, fund = [], [], [], []
    permaticker = 1000
    for i in range(n_names):
        tkr = f"SYN{i:02d}"
        p0 = float(rng.uniform(15, 90))
        rets = alphas[i] + mkt + sec[:, sector_of[i]] + sigma * rng.standard_normal(nd)
        px = p0 * np.exp(np.cumsum(rets))
        vol = rng.uniform(0.8e6, 3e6, len(days))
        # a couple of deliberately illiquid / out-of-band names for the screen
        mktcap = float(rng.uniform(400, 12000))
        if i == 0:
            mktcap = 120.0            # below the $300M floor
        if i == 1:
            mktcap = 22000.0          # above the $15B cap
        if i == 2:
            vol = vol * 0.002         # illiquid: dollar-vol below $5M

        # mid-panel delisting for name i==3 (last price ~ 2018-06)
        last_idx = len(days) - 1
        if i == 3:
            last_idx = int(np.searchsorted(days, np.datetime64("2018-06-15")))
        dd = days[: last_idx + 1]
        pxx = px[: last_idx + 1]
        vv = vol[: last_idx + 1]

        first, last = dd[0], dd[-1]
        isdel = "Y" if i == 3 else "N"
        tickers.append(dict(permaticker=permaticker, ticker=tkr,
                            firstpricedate=str(first.date()), lastpricedate=str(last.date()),
                            category="Domestic Common Stock", exchange="NYSE", isdelisted=isdel))
        for d, c, v in zip(dd, pxx, vv):
            sep.append(dict(ticker=tkr, date=d, closeadj=float(c), volume=float(v)))
        # daily marketcap (roughly constant per name)
        for d in dd:
            daily.append(dict(ticker=tkr, date=d, marketcap=mktcap))
        # quarterly ART filings; values vary across names (noise factors)
        for q in pd.date_range(first, last, freq="QS"):
            datekey = q + pd.Timedelta(days=40)   # filed 40d after quarter start
            if datekey > last:
                continue
            fund.append(dict(ticker=tkr, dimension="ART", datekey=str(datekey.date()),
                             eps=float(rng.uniform(0.2, 5.0)),
                             bvps=float(rng.uniform(2.0, 40.0)),
                             gp=float(rng.uniform(50, 500)),
                             assets=float(rng.uniform(200, 3000))))
        permaticker += 1

    # recycled ticker RECY: permaticker A (2015) then B (2018), disjoint windows
    for tag, (a_start, a_end), pm in (("A", ("2015-01-05", "2016-06-30"), permaticker),
                                       ("B", ("2018-01-05", "2019-06-30"), permaticker + 1)):
        dd = _bdays(a_start, a_end)
        base = 30.0 if tag == "A" else 55.0
        pxx = base * np.exp(np.cumsum(0.02 * rng.standard_normal(len(dd))))
        tickers.append(dict(permaticker=pm, ticker="RECY",
                            firstpricedate=str(dd[0].date()), lastpricedate=str(dd[-1].date()),
                            category="Domestic Common Stock", exchange="NASDAQ",
                            isdelisted="Y" if tag == "A" else "N"))
        for d, c in zip(dd, pxx):
            sep.append(dict(ticker="RECY", date=d, closeadj=float(c), volume=2e6))
            daily.append(dict(ticker="RECY", date=d, marketcap=1500.0))
    permaticker += 2

    return (pd.DataFrame(tickers), pd.DataFrame(sep),
            pd.DataFrame(daily), pd.DataFrame(fund))


def _run_build(tickers, sep, daily, fund, span_start, span_end, verbose=False):
    con = duckdb.connect()
    con.register("tickers_raw", tickers)
    con.register("sep_raw", sep)
    con.register("daily_raw", daily)
    con.register("fund_raw", fund)
    try:
        return sp._build(con, span_start, span_end, verbose=verbose)
    finally:
        con.close()


# ---------------------------------------------------------------------------
# Independent pandas ORACLE of the timing layer (structurally different code)
# ---------------------------------------------------------------------------
def _asof(dates: np.ndarray, values: np.ndarray, query) -> float:
    """Last value whose date <= query, else NaN. dates sorted ascending."""
    q = np.datetime64(pd.Timestamp(query))
    k = np.searchsorted(dates, q, side="right") - 1
    return float(values[k]) if k >= 0 else np.nan


def _asof_date(dates: np.ndarray, query):
    q = np.datetime64(pd.Timestamp(query))
    k = np.searchsorted(dates, q, side="right") - 1
    return pd.Timestamp(dates[k]) if k >= 0 else pd.NaT


def oracle(tickers, sep, daily, fund, span_start, span_end) -> pd.DataFrame:
    tk = tickers.copy()
    tk["firstdate"] = pd.to_datetime(tk["firstpricedate"])
    tk["lastdate"] = pd.to_datetime(tk["lastpricedate"])

    def attribute(df, datecol):
        d = df.copy()
        d[datecol] = pd.to_datetime(d[datecol])
        out = d.merge(tk[["permaticker", "ticker", "firstdate", "lastdate",
                          "category", "exchange"]], on="ticker", how="inner")
        out = out[(out[datecol] >= out["firstdate"]) & (out[datecol] <= out["lastdate"])]
        return out

    px = attribute(sep, "date").sort_values(["permaticker", "date"])
    dly = attribute(daily, "date")
    fnd = attribute(fund, "datekey")
    fnd = fnd[fnd["dimension"] == "ART"]

    # per-name arrays
    names = {}
    for pm, g in px.groupby("permaticker"):
        g = g.sort_values("date")
        dates = g["date"].values.astype("datetime64[ns]")
        close = g["closeadj"].values.astype(float)
        vol = g["volume"].values.astype(float)
        ret = np.concatenate([[np.nan], close[1:] / close[:-1] - 1.0])
        names[pm] = dict(dates=dates, close=close, vol=vol, ret=ret)

    # market calendar + rebalances
    cal = np.sort(px["date"].unique().astype("datetime64[ns]"))
    cal_s = pd.Series(range(1, len(cal) + 1), index=pd.DatetimeIndex(cal))  # date->idx
    month_end = (pd.DatetimeIndex(cal).to_frame(index=False, name="d")
                 .assign(ym=lambda x: x["d"].dt.to_period("M"))
                 .groupby("ym")["d"].max())
    reb = [t for t in month_end if span_start <= str(t.date()) <= span_end]
    idx_of = {pd.Timestamp(d): i for i, d in zip(range(1, len(cal) + 1), cal)}
    cal_dt = pd.DatetimeIndex(cal)

    def cal_date_at(idx):
        return cal_dt[idx - 1] if 1 <= idx <= len(cal_dt) else pd.NaT

    meta = tk.groupby("permaticker").agg(
        category=("category", "first"), exchange=("exchange", "first"),
        lastdate=("lastdate", "max")).reset_index()
    meta_map = meta.set_index("permaticker")

    rows = []
    for T in reb:
        idx_T = idx_of[pd.Timestamp(T)]
        d_m21 = cal_date_at(idx_T - sp.MOM_SKIP)
        d_m252 = cal_date_at(idx_T - sp.MOM_LOOKBACK)
        d_p21 = cal_date_at(idx_T + sp.FWD_HORIZON)
        for pm, nm in names.items():
            dates, close, vol, ret = nm["dates"], nm["close"], nm["vol"], nm["ret"]
            k = np.searchsorted(dates, np.datetime64(T), side="right") - 1
            if k < 0:
                continue
            lastdate = meta_map.loc[pm, "lastdate"]
            if T > lastdate:
                continue
            close_T = float(close[k])
            hist_days = k + 1
            # vol_252: stddev_samp of last 252 rows' ret, NaNs dropped, >=2
            w = ret[max(0, k - (sp.VOL_WINDOW - 1)): k + 1]
            w = w[~np.isnan(w)]
            vol_252 = float(np.std(w, ddof=1)) if len(w) >= 2 else np.nan
            # dollarvol_60: median of last 60 rows' closeadj*volume
            dv = (close * vol)[max(0, k - (sp.DOLLARVOL_WINDOW - 1)): k + 1]
            dollarvol_60 = float(np.median(dv))
            c_m21 = _asof(dates, close, d_m21) if pd.notna(d_m21) else np.nan
            c_m252 = _asof(dates, close, d_m252) if pd.notna(d_m252) else np.nan
            mom = c_m21 / c_m252 - 1.0 if (pd.notna(c_m21) and pd.notna(c_m252)) else np.nan
            # marketcap as-of T
            dg = dly[dly["permaticker"] == pm].sort_values("date")
            mc = _asof(dg["date"].values.astype("datetime64[ns]"),
                       dg["marketcap"].values.astype(float), T) if len(dg) else np.nan
            # fundamentals ART latest datekey <= T
            fg = fnd[fnd["permaticker"] == pm].sort_values("datekey")
            eps = bvps = gp = assets = np.nan
            if len(fg):
                fdates = fg["datekey"].values.astype("datetime64[ns]")
                j = np.searchsorted(fdates, np.datetime64(T), side="right") - 1
                if j >= 0:
                    eps = float(fg["eps"].values[j]); bvps = float(fg["bvps"].values[j])
                    gp = float(fg["gp"].values[j]); assets = float(fg["assets"].values[j])
            # forward label
            if pd.isna(d_p21):
                fwd, status = np.nan, "incomplete_window"
            else:
                c_p21 = _asof(dates, close, d_p21)
                c_p21_date = _asof_date(dates, d_p21)
                delisted_partial = pd.notna(lastdate) and lastdate < d_p21
                if delisted_partial:
                    fwd, status = c_p21 / close_T - 1.0, "delisted_partial"
                elif c_p21_date == pd.Timestamp(T):
                    fwd, status = np.nan, "no_forward_price"
                else:
                    fwd, status = c_p21 / close_T - 1.0, "ok"
            rows.append(dict(date=pd.Timestamp(T), permaticker=pm, close_T=close_T,
                             mktcap_T=mc, dollarvol_60=dollarvol_60, hist_days=hist_days,
                             mom_12_1=mom, vol_252=vol_252, eps=eps, bvps=bvps, gp=gp,
                             assets=assets, category=meta_map.loc[pm, "category"],
                             exchange=meta_map.loc[pm, "exchange"],
                             fwd_ret_21=fwd, fwd_status=status))
    return pd.DataFrame(rows).sort_values(["date", "permaticker"]).reset_index(drop=True)


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------
def test_timing_oracle():
    print("\n[1] TIMING vs independent pandas oracle")
    tk, sep, daily, fund = make_panel(seed=7)
    built = _run_build(tk, sep, daily, fund, "2016-01-01", "2019-05-31")
    orc = oracle(tk, sep, daily, fund, "2016-01-01", "2019-05-31")

    b = built.set_index(["date", "permaticker"]).sort_index()
    o = orc.set_index(["date", "permaticker"]).sort_index()
    check("same (date,permaticker) key set", b.index.equals(o.index),
          f"built={len(b)} oracle={len(o)}")
    common = b.index.intersection(o.index)
    b, o = b.loc[common], o.loc[common]
    for col in ["close_T", "mktcap_T", "dollarvol_60", "hist_days", "mom_12_1",
                "vol_252", "eps", "bvps", "gp", "assets", "fwd_ret_21"]:
        bx, ox = b[col].astype(float), o[col].astype(float)
        both_nan = bx.isna() & ox.isna()
        close = ((bx - ox).abs() <= TOL * (1 + ox.abs())) | both_nan
        n_bad = int((~close).sum())
        worst = float((bx - ox).abs().replace([np.inf], np.nan).max()) if len(bx) else 0.0
        check(f"col {col} matches oracle", n_bad == 0,
              f"{n_bad} mismatches, worst abs diff {worst:.2e}")
    check("fwd_status matches oracle", (b["fwd_status"] == o["fwd_status"]).all(),
          f"{int((b['fwd_status'] != o['fwd_status']).sum())} mismatches")
    # the delisting name must produce at least one delisted_partial label
    check("delisting folds into a label",
          (built["fwd_status"] == "delisted_partial").any())


def test_attribution_recycle():
    print("\n[2] ATTRIBUTION - recycled ticker splits to correct permaticker")
    tk, sep, daily, fund = make_panel(seed=7)
    built = _run_build(tk, sep, daily, fund, "2015-06-01", "2019-05-31")
    recy = tk[tk["ticker"] == "RECY"]
    pm_a = int(recy.iloc[0]["permaticker"]); pm_b = int(recy.iloc[1]["permaticker"])
    a_rows = built[built["permaticker"] == pm_a]
    b_rows = built[built["permaticker"] == pm_b]
    # A only appears in its window (2015-2016), B only in 2018-2019; never overlap
    a_ok = (a_rows["date"] <= pd.Timestamp("2016-06-30")).all() if len(a_rows) else True
    b_ok = (b_rows["date"] >= pd.Timestamp("2018-01-01")).all() if len(b_rows) else True
    check("recycled ticker A dates within A's window", a_ok, f"{len(a_rows)} A-rows")
    check("recycled ticker B dates within B's window", b_ok, f"{len(b_rows)} B-rows")
    check("A and B are distinct permatickers present", len(a_rows) > 0 and len(b_rows) > 0)


def test_ambiguity_fails_loud():
    print("\n[3] AMBIGUITY - overlapping windows for one ticker fail loud")
    days = _bdays("2015-01-01", "2015-12-31")
    sep = pd.DataFrame([dict(ticker="DUP", date=d, closeadj=10.0, volume=1e6) for d in days])
    daily = pd.DataFrame([dict(ticker="DUP", date=d, marketcap=1000.0) for d in days])
    fund = pd.DataFrame(columns=["ticker", "dimension", "datekey", "eps", "bvps", "gp", "assets"])
    tk = pd.DataFrame([
        dict(permaticker=1, ticker="DUP", firstpricedate="2015-01-01",
             lastpricedate="2015-12-31", category="Domestic Common Stock",
             exchange="NYSE", isdelisted="N"),
        dict(permaticker=2, ticker="DUP", firstpricedate="2015-06-01",  # OVERLAP
             lastpricedate="2015-12-31", category="Domestic Common Stock",
             exchange="NYSE", isdelisted="N"),
    ])
    failed = False
    try:
        _run_build(tk, sep, daily, fund, "2015-02-01", "2015-11-30")
    except SystemExit:
        failed = True
    check("overlapping-window ticker triggers fail-loud", failed)


def test_pit_fundamental_join():
    print("\n[4] PIT FUND JOIN - a filing dated after T is not used at T")
    days = _bdays("2015-01-01", "2016-12-31")
    tk = pd.DataFrame([dict(permaticker=1, ticker="PIT", firstpricedate="2015-01-01",
                            lastpricedate="2016-12-31", category="Domestic Common Stock",
                            exchange="NYSE", isdelisted="N")])
    sep = pd.DataFrame([dict(ticker="PIT", date=d, closeadj=20.0, volume=2e6) for d in days])
    daily = pd.DataFrame([dict(ticker="PIT", date=d, marketcap=1000.0) for d in days])
    # rebalance at 2015-06-30 (last biz day of June). Two filings straddle it.
    fund = pd.DataFrame([
        dict(ticker="PIT", dimension="ART", datekey="2015-05-15", eps=1.0, bvps=10.0, gp=100.0, assets=1000.0),
        dict(ticker="PIT", dimension="ART", datekey="2015-07-15", eps=9.0, bvps=90.0, gp=900.0, assets=1000.0),
    ])
    built = _run_build(tk, sep, daily, fund, "2015-06-01", "2015-06-30")
    jun = built[(built["permaticker"] == 1)]
    eps_used = jun["eps"].iloc[0] if len(jun) else None
    check("June rebalance uses the MAY filing (eps=1.0), not July (eps=9.0)",
          eps_used == 1.0, f"eps used = {eps_used}")


def _pipeline_metrics(tk, sep, daily, fund, span):
    built = _run_build(tk, sep, daily, fund, *span)
    screened = ebu.screen(built)
    elig = screened[screened["eligible"]].copy()
    scores = ebf.compute_scores(elig)
    panel = scores.merge(built[["date", "permaticker", "fwd_ret_21", "fwd_status"]],
                         on=["date", "permaticker"], how="left")
    res = ebh.evaluate(panel)
    return built, panel, res


def _decile_by(panel: pd.DataFrame, score_col: str) -> pd.DataFrame:
    """Return a copy of panel with 'decile' assigned from score_col within date."""
    p = panel.copy()
    p["decile"] = np.nan
    for _, g in p.groupby("date"):
        v = g[score_col].dropna()
        if len(v) >= ebh.N_DECILES:
            dec = pd.qcut(g[score_col].rank(method="first"), ebh.N_DECILES,
                          labels=list(range(1, ebh.N_DECILES + 1)))
            p.loc[g.index, "decile"] = dec.astype(float)
    return p


def test_positive_and_null():
    print("\n[5] POSITIVE (planted signal) and NULL (noise) controls")
    # The planted signal lives in the MOMENTUM channel (alpha_i drives both the
    # trailing momentum and the forward return). On these exploding synthetic
    # prices the value factor (eps/price with random eps) becomes spuriously
    # anti-momentum and partly cancels it in the equal-weight composite - a real
    # momentum/value offset. So the control proves the harness RECOVERS the
    # planted signal on the momentum factor itself; the composite is checked only
    # for not being perversely negative.
    tk, sep, daily, fund = make_panel(seed=11, n_names=100, alpha_scale=0.0012, sigma=0.010)
    _, panel, res = _pipeline_metrics(tk, sep, daily, fund, ("2016-01-01", "2019-05-31"))
    ic_mom = ebh.ic_summary(ebh.rank_ic_series(panel, score_col="momentum"))
    check("positive control: momentum rank-IC clearly > 0", ic_mom["mean_ic"] > 0.05,
          f"mean_ic={ic_mom['mean_ic']:.3f}, NW-t={ic_mom['nw_tstat']:.2f}")
    check("positive control: momentum NW t-stat significant", ic_mom["nw_tstat"] > 2.0,
          f"NW-t={ic_mom['nw_tstat']:.2f}")
    mono = ebh.monotonicity(ebh.decile_table(_decile_by(panel, "momentum")))
    check("positive control: decile return rises with momentum decile",
          mono["spearman_ret"] > 0.4, f"spearman(decile,ret)={mono['spearman_ret']:.2f}")
    check("positive control: composite IC not perversely negative",
          res["ic_summary"]["mean_ic"] > -0.03, f"composite_ic={res['ic_summary']['mean_ic']:.3f}")
    apos = ebh.leak_audit(panel, score_col="momentum", reps=15)
    check("positive control: real momentum IC sits far above the permutation null",
          apos["real_vs_null_z"] > 4.0,
          f"z={apos['real_vs_null_z']:.1f} (null_mean={apos['shuffle_null_mean']:.4f}, "
          f"null_sd={apos['shuffle_null_sd']:.4f})")

    # null: no alpha -> IC ~ 0, insignificant
    tk0, sep0, daily0, fund0 = make_panel(seed=11, n_names=100, alpha_scale=0.0, sigma=0.010)
    _, panel0, res0 = _pipeline_metrics(tk0, sep0, daily0, fund0, ("2016-01-01", "2019-05-31"))
    ic0 = ebh.ic_summary(ebh.rank_ic_series(panel0, score_col="momentum"))
    check("null control: |momentum rank-IC| small", abs(ic0["mean_ic"]) < 0.05,
          f"mean_ic={ic0['mean_ic']:.3f}")
    check("null control: momentum NW t-stat insignificant", abs(ic0["nw_tstat"]) < 2.5,
          f"NW-t={ic0['nw_tstat']:.2f}")


def test_leak_tripwire():
    print("\n[6] LEAK TRIPWIRE - harness flags a planted look-ahead")
    tk, sep, daily, fund = make_panel(seed=3, n_names=40, alpha_scale=0.0)
    built, panel, _ = _pipeline_metrics(tk, sep, daily, fund, ("2016-01-01", "2019-05-31"))
    audit = ebh.leak_audit(panel, reps=15)
    check("cheat score (=fwd return) drives IC ~ +1", audit["cheat_mean_ic"] > 0.95,
          f"cheat_ic={audit['cheat_mean_ic']:.3f}")
    check("cheat score gives a perfect decile staircase",
          audit["cheat_spearman_decile"] > 0.99, f"spearman={audit['cheat_spearman_decile']:.3f}")
    check("permutation null centred at ~0 (no manufactured signal)",
          abs(audit["shuffle_null_mean"]) < 0.01,
          f"null_mean={audit['shuffle_null_mean']:.4f}, null_sd={audit['shuffle_null_sd']:.4f}")
    check("null panel: real IC not far above its own permutation null",
          abs(audit["real_vs_null_z"]) < 4.0, f"z={audit['real_vs_null_z']:.2f}")


def main():
    print("=" * 74)
    print("ENGINE B (P3) - SYNTHETIC LEAK AUDIT  (real panel NOT touched)")
    print("=" * 74)
    test_timing_oracle()
    test_attribution_recycle()
    test_ambiguity_fails_loud()
    test_pit_fundamental_join()
    test_positive_and_null()
    test_leak_tripwire()
    print("\n" + "=" * 74)
    if _FAILS:
        print(f"RESULT: {len(_FAILS)} FAILED -> {_FAILS}")
        sys.exit(1)
    print("RESULT: ALL CHECKS PASSED")


if __name__ == "__main__":
    main()
