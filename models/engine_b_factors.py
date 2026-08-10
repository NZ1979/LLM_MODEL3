"""Engine B (P3) - mechanical five-factor composite.

Implements docs/ENGINE_B_BASELINE_SPEC.md section "The mechanical baseline".
Five equal-weight factors, no fitted parameters:

  1. Momentum (12-1):  closeadj[T-21] / closeadj[T-252] - 1      (raw: mom_12_1)
  2. Value:            0.5 * (z(earnings_yield) + z(book/price))
                       earnings_yield = eps_ART / close_T
                       book/price     = bvps_ART / close_T
  3. Quality:          gross profitability = gp_ART / assets_ART  (Novy-Marx)
  4. Low-volatility:   -std(daily returns, trailing 252d)         (raw: vol_252)
  5. Size:             -ln(marketcap_T)

All fundamentals are dimension ART, joined with datekey <= T (done upstream in
data/sharadar_panel.py). Each raw factor is cross-sectionally winsorised at
+/-3 SD then z-scored WITHIN that date's eligible universe (no cross-date
standardisation - no leakage across time). The composite is the equal-weight
mean of the five factor z-scores; names are bucketed into deciles (D10 =
highest expected return).

Missing-fundamentals handling (a point the pre-registered spec left implicit,
fixed here BEFORE any result was computed - see the SPEC changelog): momentum,
low-vol and size are always computable for an eligible name (price history is
guaranteed by the history screen); value and quality need an ART filing with
datekey <= T. A name with no such filing has NaN value/quality and CANNOT have
the five-factor composite the spec defines, so it is excluded from that month's
ranked set and the exclusion is COUNTED and reported (Rule 18) - never filled.
This is a ranking-set restriction, not a change to the pre-registered universe:
the name stays in the panel and is eligible again the moment it has a filing.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

FACTORS = ("momentum", "value", "quality", "lowvol", "size")
WINSOR_SD = 3.0
N_DECILES = 10


def _winsorize_z(x: pd.Series) -> pd.Series:
    """Cross-sectional winsorise at +/-WINSOR_SD then z-score.

    Winsorisation clips to [mu - k*sd, mu + k*sd] using the raw cross-section
    mean/sd; the returned z-score uses the winsorised series' own mean/sd.
    NaNs pass through as NaN (they carry no rank). If sd == 0 (degenerate
    cross-section) returns all zeros for the non-NaN entries.
    """
    x = x.astype(float)
    v = x.dropna()
    if len(v) == 0:
        return x
    mu, sd = v.mean(), v.std(ddof=0)
    if sd == 0 or not np.isfinite(sd):
        return x.where(x.isna(), 0.0)
    lo, hi = mu - WINSOR_SD * sd, mu + WINSOR_SD * sd
    xc = x.clip(lower=lo, upper=hi)
    vc = xc.dropna()
    mu2, sd2 = vc.mean(), vc.std(ddof=0)
    if sd2 == 0 or not np.isfinite(sd2):
        return x.where(x.isna(), 0.0)
    return (xc - mu2) / sd2


def _raw_factors_one_date(g: pd.DataFrame) -> pd.DataFrame:
    """Compute the five raw factor columns for one date's eligible cross-section.

    `g` holds only eligible rows for a single rebalance date. Returns a frame
    indexed like `g` with the five z-scored factors and the composite.
    """
    out = pd.DataFrame(index=g.index)

    # 1. Momentum (already a return; higher = better)
    out["momentum"] = _winsorize_z(g["mom_12_1"])

    # 2. Value: blend of z(earnings yield) and z(book/price)
    price = g["close_T"].replace(0.0, np.nan)
    ey = g["eps"] / price          # earnings yield
    bp = g["bvps"] / price         # book-to-price
    value_raw = 0.5 * (_winsorize_z(ey) + _winsorize_z(bp))
    out["value"] = _winsorize_z(value_raw)

    # 3. Quality: gross profitability (higher = better)
    assets = g["assets"].replace(0.0, np.nan)
    gp_a = g["gp"] / assets
    out["quality"] = _winsorize_z(gp_a)

    # 4. Low-vol: negative of trailing realised vol (lower vol = higher score)
    out["lowvol"] = _winsorize_z(-g["vol_252"])

    # 5. Size: negative log market cap (smaller = higher score)
    mc = g["mktcap_T"].replace(0.0, np.nan)
    out["size"] = _winsorize_z(-np.log(mc))

    return out


def compute_scores(df_eligible: pd.DataFrame) -> pd.DataFrame:
    """Compute per-(date, permaticker) factor z-scores, composite and decile.

    Input: the eligible cross-section (rows already filtered to eligible==True),
    carrying columns: date, permaticker, mom_12_1, close_T, eps, bvps, gp,
    assets, vol_252, mktcap_T.

    Output: a frame with the five factor z-scores, 'composite', 'decile'
    (1..10, 10 = highest composite), and a boolean 'ranked' flag. Only names
    with all five factors present are ranked; the rest are returned with
    ranked=False and NaN decile (counted by ranking_coverage()).
    """
    need = ["date", "permaticker", "mom_12_1", "close_T", "eps", "bvps",
            "gp", "assets", "vol_252", "mktcap_T"]
    missing = [c for c in need if c not in df_eligible.columns]
    if missing:
        raise ValueError(f"compute_scores: missing columns: {missing}")

    parts = []
    for date, g in df_eligible.groupby("date", sort=True):
        fac = _raw_factors_one_date(g)
        fac.insert(0, "date", date)
        fac["permaticker"] = g["permaticker"].values
        # a name is rankable iff all five factor z-scores are present
        fac["ranked"] = fac[list(FACTORS)].notna().all(axis=1)
        # composite: equal-weight mean of the five z-scores (only for ranked)
        comp = fac[list(FACTORS)].mean(axis=1)
        fac["composite"] = comp.where(fac["ranked"])
        # deciles computed WITHIN the ranked set for this date
        fac["decile"] = np.nan
        r = fac.loc[fac["ranked"]]
        if len(r) >= N_DECILES:
            # qcut on the ranked composite; labels 1..10, 10 = highest
            dec = pd.qcut(r["composite"].rank(method="first"),
                          N_DECILES, labels=list(range(1, N_DECILES + 1)))
            fac.loc[r.index, "decile"] = dec.astype(int).values
        parts.append(fac)

    if not parts:
        return pd.DataFrame(columns=["date", "permaticker", *FACTORS,
                                     "ranked", "composite", "decile"])
    return pd.concat(parts, ignore_index=True)


def ranking_coverage(scores: pd.DataFrame) -> pd.DataFrame:
    """Per-date: eligible count vs ranked count vs dropped-for-no-fundamental.

    Surfaces how many eligible names could not be ranked because they lacked an
    ART fundamental filing at T (Rule 18). A month where this is large is a
    visible data-coverage caveat, not a silent drop.
    """
    g = scores.groupby("date")
    rep = pd.DataFrame({
        "eligible": g.size(),
        "ranked": g["ranked"].sum(),
    })
    rep["dropped_no_fundamental"] = rep["eligible"] - rep["ranked"]
    return rep.astype(int)
