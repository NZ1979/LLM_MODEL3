"""Engine B (P3) - cross-sectional walk-forward harness.

Implements docs/ENGINE_B_BASELINE_SPEC.md section "Evaluation and
pre-registered conditions". All numbers are OUT-OF-SAMPLE by construction (the
mechanical baseline has no trained parameters, so every month is effectively
out-of-sample) and NET of cost. Gross-only figures count toward nothing
(KILL_RULE.md).

Metrics:
  1. Rank-IC     - monthly cross-sectional Spearman(composite, T->T+21 return),
                   mean + Newey-West (HAC) t-stat + the IC time series.
  2. Decile monotonicity - mean forward return and Sharpe by composite decile.
  3. Tradeable form - equal-weight LONG-ONLY top-decile (D10), monthly, net of
                   cost, with cost sensitivity at 5/10/20 bps/side. The
                   long-short D10-D1 spread is reported as a DIAGNOSTIC only.

Leakage discipline: a name held at T whose forward label is missing (delisted
with no recorded return, or forward window incomplete) is DROPPED from that
month's portfolio return and COUNTED (Rule 18), never filled with zero. A
too-good result (IC > ~0.10 monthly or a perfectly monotone high-Sharpe decile
staircase) is assumed leaking until the harness is proven; the leak-audit
controls in leak_audit() plant a known look-ahead and confirm the harness would
flag it.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats

MONTHS_PER_YEAR = 12
N_DECILES = 10
COST_SIDES_BPS = (5.0, 10.0, 20.0)   # sensitivity grid (bps per side)
COST_DEFAULT_BPS = 10.0              # pre-registered baseline (spec "Cost basis")
SHUFFLE_SEED = 20260810             # fixed -> the shuffle control is reproducible


# ----------------------------------------------------------------------------
# 1. Rank-IC
# ----------------------------------------------------------------------------
def rank_ic_series(panel: pd.DataFrame, score_col: str = "composite",
                   ret_col: str = "fwd_ret_21") -> pd.DataFrame:
    """Per-date Spearman rank-IC between score and forward return.

    Uses only rows that are ranked (score present) AND have a valid forward
    label. Returns a frame indexed by date with columns: ic, n (names used),
    n_missing_label (ranked names dropped for a missing forward label).
    """
    rows = []
    for date, g in panel.groupby("date", sort=True):
        gr = g[g[score_col].notna()]
        n_missing = int(gr[ret_col].isna().sum())
        gv = gr[gr[ret_col].notna()]
        if len(gv) >= 5 and gv[score_col].nunique() > 1 and gv[ret_col].nunique() > 1:
            ic = stats.spearmanr(gv[score_col], gv[ret_col]).correlation
        else:
            ic = np.nan
        rows.append((date, ic, len(gv), n_missing))
    return pd.DataFrame(rows, columns=["date", "ic", "n", "n_missing_label"]).set_index("date")


def _newey_west_tstat(x: pd.Series, maxlags: int | None = None) -> tuple[float, float]:
    """Mean of x and its Newey-West (HAC) t-stat against zero.

    Monthly 21-day-forward labels barely overlap month-to-month, but a small HAC
    lag guards residual autocorrelation. Default maxlags = int(n**0.25)+1.
    Falls back to statsmodels; if unavailable, uses a plain t-stat.
    """
    v = x.dropna().values.astype(float)
    if len(v) < 3:
        return (float(np.mean(v)) if len(v) else float("nan"), float("nan"))
    mean = float(np.mean(v))
    if maxlags is None:
        maxlags = int(len(v) ** 0.25) + 1
    try:
        import statsmodels.api as sm
        res = sm.OLS(v, np.ones((len(v), 1))).fit(
            cov_type="HAC", cov_kwds={"maxlags": maxlags})
        return (float(res.params[0]), float(res.tvalues[0]))
    except Exception:  # noqa: BLE001 - statsmodels missing/edge; degrade visibly
        se = np.std(v, ddof=1) / np.sqrt(len(v))
        return (mean, mean / se if se > 0 else float("nan"))


def ic_summary(ic: pd.DataFrame) -> dict:
    s = ic["ic"].dropna()
    mean, t = _newey_west_tstat(ic["ic"])
    return {
        "n_months": int(len(s)),
        "mean_ic": mean,
        "median_ic": float(s.median()) if len(s) else float("nan"),
        "std_ic": float(s.std(ddof=1)) if len(s) > 1 else float("nan"),
        "nw_tstat": t,
        "frac_positive": float((s > 0).mean()) if len(s) else float("nan"),
        "hit_rate_ic": float((s > 0).mean()) if len(s) else float("nan"),
    }


# ----------------------------------------------------------------------------
# 2. Decile monotonicity
# ----------------------------------------------------------------------------
def decile_table(panel: pd.DataFrame, ret_col: str = "fwd_ret_21") -> pd.DataFrame:
    """Mean forward return and annualised Sharpe per composite decile.

    Each month, average the forward return within a decile (equal weight), then
    take the time series of those monthly decile means; Sharpe = mean/std*sqrt(12).
    """
    d = panel[panel["decile"].notna() & panel[ret_col].notna()].copy()
    d["decile"] = d["decile"].astype(int)
    # monthly equal-weight mean return per decile
    monthly = d.groupby(["date", "decile"])[ret_col].mean().unstack("decile")
    rows = []
    for dec in range(1, N_DECILES + 1):
        if dec not in monthly.columns:
            rows.append((dec, np.nan, np.nan, 0))
            continue
        s = monthly[dec].dropna()
        mean_m = s.mean()
        sharpe = (s.mean() / s.std(ddof=1) * np.sqrt(MONTHS_PER_YEAR)
                  if s.std(ddof=1) > 0 else np.nan)
        rows.append((dec, float(mean_m), float(sharpe), int(len(s))))
    tab = pd.DataFrame(rows, columns=["decile", "mean_fwd_ret", "sharpe", "n_months"])
    return tab.set_index("decile")


def monotonicity(tab: pd.DataFrame) -> dict:
    """Spearman rank correlation of decile number vs mean return and vs Sharpe,
    plus the fraction of adjacent decile steps that increase (near-monotone)."""
    t = tab.dropna(subset=["mean_fwd_ret"])
    if len(t) < 3:
        return {"spearman_ret": float("nan"), "spearman_sharpe": float("nan"),
                "frac_adjacent_up_ret": float("nan"), "d10_minus_d1_ret": float("nan")}
    sp_ret = stats.spearmanr(t.index, t["mean_fwd_ret"]).correlation
    ts = tab.dropna(subset=["sharpe"])
    sp_sh = stats.spearmanr(ts.index, ts["sharpe"]).correlation if len(ts) >= 3 else float("nan")
    steps = t["mean_fwd_ret"].diff().dropna()
    frac_up = float((steps > 0).mean()) if len(steps) else float("nan")
    d1 = tab.loc[1, "mean_fwd_ret"] if 1 in tab.index else np.nan
    d10 = tab.loc[N_DECILES, "mean_fwd_ret"] if N_DECILES in tab.index else np.nan
    return {
        "spearman_ret": float(sp_ret),
        "spearman_sharpe": float(sp_sh),
        "frac_adjacent_up_ret": frac_up,
        "d10_minus_d1_ret": float(d10 - d1),
    }


# ----------------------------------------------------------------------------
# 3. Tradeable form - long-only top decile (+ long-short diagnostic)
# ----------------------------------------------------------------------------
def _equal_weight_series(members_by_date: dict[pd.Timestamp, set], sign: float = 1.0):
    """Build per-date equal-weight target-weight dicts {permaticker: w}."""
    weights = {}
    for date, members in members_by_date.items():
        n = len(members)
        w = sign / n if n else 0.0
        weights[date] = {pt: w for pt in members}
    return weights


def _portfolio_monthly(panel: pd.DataFrame, decile_pick, ret_col="fwd_ret_21"):
    """Return per-month (gross_ret, turnover, n_held, n_dropped_label) for an
    equal-weight portfolio of the names selected by decile_pick(row-> bool mask).

    decile_pick is a dict date-> set(permaticker) of intended holdings.
    Gross monthly return = equal-weight mean of forward returns of held names
    that HAVE a valid label; names missing a label are dropped and counted.
    Turnover = sum_i |w_t(i) - w_{t-1}(i)| over the intended equal weights
    (charged per side downstream).
    """
    dates = sorted(decile_pick.keys())
    lab = (panel[panel[ret_col].notna()]
           .set_index(["date", "permaticker"])[ret_col])
    intended = {d: set(decile_pick[d]) for d in dates}
    prev_w = {}
    rows = []
    for d in dates:
        members = intended[d]
        n = len(members)
        w = {pt: 1.0 / n for pt in members} if n else {}
        # turnover vs previous month's intended weights
        keys = set(w) | set(prev_w)
        turnover = sum(abs(w.get(k, 0.0) - prev_w.get(k, 0.0)) for k in keys)
        # gross return over names with a valid label
        held_labels = [(pt, lab.get((d, pt), np.nan)) for pt in members]
        valid = [(pt, r) for pt, r in held_labels if pd.notna(r)]
        n_drop = n - len(valid)
        if valid:
            gross = float(np.mean([r for _, r in valid]))
        else:
            gross = np.nan
        rows.append((d, gross, turnover, len(valid), n_drop))
        prev_w = w
    return pd.DataFrame(rows, columns=["date", "gross", "turnover",
                                       "n_held", "n_dropped_label"]).set_index("date")


def _curve_metrics(monthly: pd.DataFrame, cost_bps_side: float) -> dict:
    """Net-of-cost metrics for a monthly gross/turnover series."""
    m = monthly.dropna(subset=["gross"]).copy()
    cost = m["turnover"] * (cost_bps_side / 1e4)   # bps per side on traded notional
    net = m["gross"] - cost
    if len(net) < 2 or net.std(ddof=1) == 0:
        return {"months": int(len(net)), "ann_return": float("nan"),
                "ann_vol": float("nan"), "sharpe": float("nan"),
                "cagr": float("nan"), "max_drawdown": float("nan"),
                "avg_turnover": float(m["turnover"].mean()) if len(m) else float("nan"),
                "net_mean_monthly": float(net.mean()) if len(net) else float("nan")}
    ann_ret = float(net.mean() * MONTHS_PER_YEAR)
    ann_vol = float(net.std(ddof=1) * np.sqrt(MONTHS_PER_YEAR))
    sharpe = ann_ret / ann_vol if ann_vol > 0 else float("nan")
    equity = (1.0 + net).cumprod()
    years = len(net) / MONTHS_PER_YEAR
    cagr = float(equity.iloc[-1] ** (1 / years) - 1) if years > 0 else float("nan")
    dd = float((equity / equity.cummax() - 1.0).min())
    return {"months": int(len(net)), "ann_return": ann_ret, "ann_vol": ann_vol,
            "sharpe": sharpe, "cagr": cagr, "max_drawdown": dd,
            "avg_turnover": float(m["turnover"].mean()),
            "net_mean_monthly": float(net.mean())}


def long_only_top_decile(panel: pd.DataFrame, ret_col="fwd_ret_21") -> dict:
    """Equal-weight long-only D10 portfolio, net of cost, with cost sensitivity."""
    d = panel[panel["decile"] == N_DECILES]
    pick = {dt: set(g["permaticker"]) for dt, g in d.groupby("date")}
    monthly = _portfolio_monthly(panel, pick, ret_col)
    out = {"monthly": monthly,
           "by_cost": {b: _curve_metrics(monthly, b) for b in COST_SIDES_BPS},
           "baseline": _curve_metrics(monthly, COST_DEFAULT_BPS),
           "total_dropped_label": int(monthly["n_dropped_label"].sum())}
    return out


def long_short_spread(panel: pd.DataFrame, ret_col="fwd_ret_21") -> dict:
    """DIAGNOSTIC ONLY - equal-weight D10 long / D1 short spread, net of cost.

    Not a tradeable claim (shorting/borrow/financing costs are exactly what made
    Engine A unimplementable); reported for colour per the spec.
    """
    long_d = panel[panel["decile"] == N_DECILES]
    short_d = panel[panel["decile"] == 1]
    long_pick = {dt: set(g["permaticker"]) for dt, g in long_d.groupby("date")}
    short_pick = {dt: set(g["permaticker"]) for dt, g in short_d.groupby("date")}
    ml = _portfolio_monthly(panel, long_pick, ret_col)
    ms = _portfolio_monthly(panel, short_pick, ret_col)
    spread = pd.DataFrame(index=sorted(set(ml.index) | set(ms.index)))
    spread["gross"] = ml["gross"].reindex(spread.index) - ms["gross"].reindex(spread.index)
    spread["turnover"] = (ml["turnover"].reindex(spread.index).fillna(0)
                          + ms["turnover"].reindex(spread.index).fillna(0))
    return {"monthly": spread, "baseline": _curve_metrics(spread, COST_DEFAULT_BPS)}


# ----------------------------------------------------------------------------
# Leak audit - plant a known look-ahead and confirm the harness would flag it
# ----------------------------------------------------------------------------
def leak_audit(panel: pd.DataFrame, ret_col="fwd_ret_21") -> dict:
    """Controls that prove the harness is sensitive to look-ahead.

    - cheat: set the score = the realised forward return. A leak-free harness
      MUST then report IC ~ +1 and a perfect decile staircase. This is the
      load-bearing test: it shows that IF a real leak existed, the harness would
      land squarely in the 'assume leakage' zone (IC > 0.10), so a modest real
      IC is trustworthy.
    - shuffle: permute the forward return across names within each date. IC must
      collapse to ~0 (no spurious signal manufactured by the pipeline).
    """
    p = panel[panel[ret_col].notna()].copy()

    cheat = p.copy()
    cheat["composite"] = cheat[ret_col]
    # rebuild deciles on the cheat score within each date
    cheat["decile"] = np.nan
    for dt, g in cheat.groupby("date"):
        if len(g) >= N_DECILES:
            dec = pd.qcut(g[ret_col].rank(method="first"), N_DECILES,
                          labels=list(range(1, N_DECILES + 1)))
            cheat.loc[g.index, "decile"] = dec.astype(int).values
    cheat_ic = ic_summary(rank_ic_series(cheat))
    cheat_mono = monotonicity(decile_table(cheat, ret_col))

    # within-date RANDOM permutation of the forward return (seeded -> reproducible).
    # A roll/shift is NOT sufficient: with sector-clustered permatickers, neighbours
    # share market/sector moves, so a one-position roll leaves real cross-sectional
    # correlation intact and manufactures a spurious IC. A true permutation removes
    # it, so a non-zero shuffle IC then means a genuine pipeline leak, not an artefact.
    rgen = np.random.default_rng(SHUFFLE_SEED)
    shuf = p.copy()
    shuf["composite"] = np.nan
    for dt, g in shuf.groupby("date"):
        shuf.loc[g.index, "composite"] = rgen.permutation(g[ret_col].values)
    shuf_ic = ic_summary(rank_ic_series(shuf))

    return {
        "cheat_mean_ic": cheat_ic["mean_ic"],
        "cheat_spearman_decile": cheat_mono["spearman_ret"],
        "shuffle_mean_ic": shuf_ic["mean_ic"],
        "shuffle_nw_t": shuf_ic["nw_tstat"],
    }


# ----------------------------------------------------------------------------
# Top-level evaluate
# ----------------------------------------------------------------------------
def evaluate(panel: pd.DataFrame, ret_col="fwd_ret_21") -> dict:
    """Run the full pre-registered metric set on a scored+labelled panel.

    `panel` must carry: date, permaticker, composite, decile, and `ret_col`.
    Returns a dict of all metrics (no printing - see scripts/run_engine_b_baseline.py).
    """
    ic = rank_ic_series(panel, ret_col=ret_col)
    tab = decile_table(panel, ret_col)
    return {
        "ic_series": ic,
        "ic_summary": ic_summary(ic),
        "decile_table": tab,
        "monotonicity": monotonicity(tab),
        "long_only": long_only_top_decile(panel, ret_col),
        "long_short": long_short_spread(panel, ret_col),
    }
