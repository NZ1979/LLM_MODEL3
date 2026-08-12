"""Engine B microcap experiment - low-turnover buffered long-only construction.

docs/ENGINE_B_MICROCAP_SPEC.md "Low-turnover long-only construction (mandatory
for microcaps)". Turns the monthly cross-sectional signal into a *tradeable*
book that trades only quarterly, with a hold-band buffer to blunt churn and
per-name liquidity/size caps, then charges the realistic microcap cost
(validation/costs_microcap.py) on realised turnover. Shared with future P5.

Fixed a priori (spec + build-kickoff handoff):
  - LONG-ONLY (no borrow in microcaps).
  - QUARTERLY rebalance (every 3rd monthly rebalance date). The monthly rank-IC
    is still measured elsewhere (signal quality); the PORTFOLIO trades quarterly.
  - HYSTERESIS / buffer: a name is BOUGHT when it is in the top decile (D10) and
    HELD until it falls below the top 3 deciles (decile < 8). Held names still in
    D8-D10 are retained across a rebalance; churn is only new entries + exits.
  - EQUAL WEIGHT, capped per name at the smaller of an EW target, a liquidity
    size cap = ADV_MULT * dollarvol_60 / AUM (a full position exits over a few
    days), and MAX_WEIGHT (3% of book). Diversify to ~TARGET_N (50-100) names.
  - Turnover, realised participation, names held, and delisting rate reported.

--- Implementation clarifications, fixed BEFORE any result (recorded in the spec
    changelog as pre-run addenda, analogous to the baseline's implicit-point
    clarifications) --------------------------------------------------------------
1. participation for a per-name trade uses max(w_old, w_new) * AUM / dollarvol_60
   - the LARGER of the pre- and post-rebalance position - so both new entries and
   full exits carry impact (a literal position_notional would zero the impact of
   an exit). Conservative: it never understates impact.
2. Weight caps are applied by iterative water-filling to respect
   min(size_cap_i, MAX_WEIGHT) while distributing to names with room. If the caps
   cannot absorb the whole book (every eligible name is liquidity-constrained -
   the high-AUM regime), the residual is held as CASH (0 return) and the invested
   fraction is reported. This is exactly how capacity binds and must be visible,
   not hidden.
3. Monthly-return mechanics: target weights are bought at each quarterly rebalance
   and HELD (buy-and-hold) through the quarter - no intra-quarter trades, so no
   intra-quarter cost. Each month the book earns sum_i w_i * r_i where r_i is the
   held name's forward 21-day return (fwd_ret_21, delisting folded via fwd_status);
   a held name that is absent or has no valid label that month contributes 0 to
   that weight (cash), is counted, and its capital is not fabricated into a
   return. Realised-turnover cost is charged only at rebalance months, aligned to
   the same month whose forward return the freshly-traded book then earns.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from validation import costs_microcap as cm

MONTHS_PER_YEAR = 12
TOP_DECILE = 10


@dataclass(frozen=True)
class BookParams:
    target_n: int = 75          # aim ~50-100 names (fixed a priori, mid-range)
    buy_decile: int = 10        # buy when decile == this (D10)
    hold_min_decile: int = 8    # hold until decile < this (drop when decile < 8)
    rebalance_every: int = 3    # quarterly (every 3rd monthly rebalance date)
    max_weight: float = 0.03    # <= 3% of book per name
    adv_mult: float = 10.0      # size cap = adv_mult * dollarvol_60 / AUM


# ----------------------------------------------------------------------------
# weight construction (iterative water-fill under per-name caps)
# ----------------------------------------------------------------------------
def capped_weights(names, dollarvol, aum: float, params: BookParams) -> dict:
    """Equal-weight target with per-name caps, by iterative water-filling.

    names: iterable of permatickers to hold.
    dollarvol: dict permaticker -> 60-td median daily $volume at T.
    Returns {permaticker: weight}. Weights are each <= min(size_cap_i, MAX_WEIGHT)
    and sum to min(1, sum of caps); any shortfall is implicit cash.
    """
    names = list(names)
    n = len(names)
    if n == 0:
        return {}
    caps = {}
    for pt in names:
        dv = dollarvol.get(pt, np.nan)
        size_cap = (params.adv_mult * dv / aum) if (dv is not None and np.isfinite(dv)) else 0.0
        caps[pt] = max(0.0, min(params.max_weight, size_cap))
    w = {pt: 0.0 for pt in names}
    active = set(pt for pt in names if caps[pt] > 0.0)
    remaining = 1.0
    # water-fill: distribute the remaining book equally among names with room,
    # clip at each cap, repeat until nothing left to place or no room remains.
    for _ in range(n + 2):
        if not active or remaining <= 1e-12:
            break
        share = remaining / len(active)
        newly_capped = []
        for pt in list(active):
            room = caps[pt] - w[pt]
            add = min(share, room)
            w[pt] += add
            if caps[pt] - w[pt] <= 1e-15:
                newly_capped.append(pt)
        remaining = 1.0 - sum(w.values())
        if not newly_capped:
            break  # everyone absorbed their share without capping -> done
        for pt in newly_capped:
            active.discard(pt)
    return w


# ----------------------------------------------------------------------------
# the book: quarterly buffered rebalance over the monthly scored panel
# ----------------------------------------------------------------------------
def build_book(panel: pd.DataFrame, aum: float, cost_scale: float = 1.0,
               params: BookParams = BookParams()) -> dict:
    """Run the buffered quarterly long-only book over a scored+labelled panel.

    `panel` rows are one per (date, permaticker) and MUST carry:
        date, permaticker, decile, composite, fwd_ret_21, fwd_status,
        dollarvol_60, mktcap_T
    (decile/composite from models/engine_b_factors.compute_scores; the rest merged
    back from the built panel). AUM in dollars. cost_scale multiplies the whole
    cost model (0.5/1/2). Returns a dict with the monthly series and diagnostics.
    """
    need = ["date", "permaticker", "decile", "composite", "fwd_ret_21",
            "dollarvol_60", "mktcap_T"]
    missing = [c for c in need if c not in panel.columns]
    if missing:
        raise ValueError(f"build_book: panel missing columns: {missing}")

    dates = sorted(panel["date"].unique())
    by_date = {d: g.set_index("permaticker") for d, g in panel.groupby("date", sort=True)}

    held: dict = {}          # permaticker -> target weight (from last rebalance)
    rows = []
    for i, d in enumerate(dates):
        present = by_date[d]
        is_reb = (i % params.rebalance_every == 0)

        if is_reb:
            dec = present["decile"]
            # retain held names still in the hold band (D8-D10) and still present
            retained = [pt for pt in held
                        if pt in present.index and pd.notna(dec.get(pt))
                        and int(dec.get(pt)) >= params.hold_min_decile]
            # candidate new entries: top-decile names not already retained,
            # ordered by composite (best first) so the book fills with the strongest
            d10 = present[(present["decile"] == params.buy_decile)]
            d10 = d10[~d10.index.isin(retained)].sort_values("composite", ascending=False)
            n_add = max(0, params.target_n - len(retained))
            adds = list(d10.index[:n_add])
            new_names = retained + adds

            dv_map = {pt: float(present.at[pt, "dollarvol_60"])
                      for pt in new_names if pd.notna(present.at[pt, "dollarvol_60"])}
            new_w = capped_weights(new_names, dv_map, aum, params)

            # realised turnover + per-name cost vs the previous target weights
            keys = set(new_w) | set(held)
            turnover = sum(abs(new_w.get(k, 0.0) - held.get(k, 0.0)) for k in keys)
            month_cost, parts = _rebalance_cost(keys, new_w, held, present, aum,
                                                cost_scale)
            held = {pt: w for pt, w in new_w.items() if w > 0.0}
        else:
            turnover = 0.0
            month_cost = 0.0
            parts = []

        # month gross return: sum_i w_i * r_i, cash (missing/absent) contributes 0
        gross = 0.0
        n_valid = 0
        n_missing = 0
        n_delisted = 0
        for pt, w in held.items():
            if pt in present.index:
                r = present.at[pt, "fwd_ret_21"]
                stat = present.at[pt, "fwd_status"] if "fwd_status" in present.columns else "ok"
                if pd.notna(r):
                    gross += w * float(r)
                    n_valid += 1
                    if stat == "delisted_partial":
                        n_delisted += 1
                else:
                    n_missing += 1
            else:
                n_missing += 1

        invested = float(sum(held.values()))
        part_mean = float(np.mean(parts)) if parts else np.nan
        part_max = float(np.max(parts)) if parts else np.nan
        rows.append(dict(date=d, is_rebalance=is_reb, gross=gross, cost=month_cost,
                         net=gross - month_cost, turnover=turnover,
                         n_held=len(held), invested_frac=invested,
                         part_mean=part_mean, part_max=part_max,
                         n_valid=n_valid, n_missing_label=n_missing,
                         n_delisted_held=n_delisted))

    monthly = pd.DataFrame(rows).set_index("date")
    stats = curve_stats(monthly["net"])
    stats_gross = curve_stats(monthly["gross"])
    diag = {
        "avg_turnover_all_months": float(monthly["turnover"].mean()),
        "avg_turnover_reb_months": float(
            monthly.loc[monthly["is_rebalance"], "turnover"].mean()),
        "median_n_held": int(monthly["n_held"].median()),
        "avg_invested_frac": float(monthly["invested_frac"].mean()),
        "avg_participation": float(monthly["part_mean"].mean(skipna=True)),
        "max_participation": float(monthly["part_max"].max(skipna=True)),
        "total_delisted_held_months": int(monthly["n_delisted_held"].sum()),
        "total_missing_label_held_months": int(monthly["n_missing_label"].sum()),
        "n_rebalances": int(monthly["is_rebalance"].sum()),
    }
    return {"monthly": monthly, "net_stats": stats, "gross_stats": stats_gross,
            "diagnostics": diag, "aum": aum, "cost_scale": cost_scale}


def _rebalance_cost(keys, new_w, old_w, present, aum, cost_scale):
    """Per-name realised-turnover cost at a rebalance. Returns (total, participations).

    total is a fraction of the book (ready to subtract from the month's return).
    participations is the list of per-traded-name participation values (diagnostic).
    """
    total = 0.0
    parts = []
    for pt in keys:
        traded = abs(new_w.get(pt, 0.0) - old_w.get(pt, 0.0))
        if traded <= 0.0:
            continue
        if pt not in present.index:
            # exiting a name that has left the panel (delisted): no market to trade
            # into; the delisting return was already realised. Charge nothing extra.
            continue
        dv = present.at[pt, "dollarvol_60"]
        mc = present.at[pt, "mktcap_T"]
        if pd.isna(dv) or dv <= 0 or pd.isna(mc):
            # no liquidity data -> cannot model impact; charge the tier half-spread
            # + commission at zero participation (fail visible, not silent-free)
            participation = 0.0
            mc = mc if pd.notna(mc) else 0.0
        else:
            position_notional = max(new_w.get(pt, 0.0), old_w.get(pt, 0.0)) * aum
            participation = position_notional / float(dv)
        hs = cm.half_spread_for(float(mc))
        side_bps = float(cm.side_cost_bps(participation, hs, scale=cost_scale))
        total += side_bps / 1e4 * traded
        parts.append(participation)
    return total, parts


# ----------------------------------------------------------------------------
# metrics
# ----------------------------------------------------------------------------
def curve_stats(net: pd.Series) -> dict:
    """Annualised stats for a monthly (net or gross) return series."""
    s = net.dropna()
    if len(s) < 2 or s.std(ddof=1) == 0:
        return {"months": int(len(s)), "ann_return": float("nan"),
                "ann_vol": float("nan"), "sharpe": float("nan"),
                "cagr": float("nan"), "max_drawdown": float("nan")}
    ann_ret = float(s.mean() * MONTHS_PER_YEAR)
    ann_vol = float(s.std(ddof=1) * np.sqrt(MONTHS_PER_YEAR))
    sharpe = ann_ret / ann_vol if ann_vol > 0 else float("nan")
    equity = (1.0 + s).cumprod()
    years = len(s) / MONTHS_PER_YEAR
    cagr = float(equity.iloc[-1] ** (1 / years) - 1) if years > 0 else float("nan")
    dd = float((equity / equity.cummax() - 1.0).min())
    return {"months": int(len(s)), "ann_return": ann_ret, "ann_vol": ann_vol,
            "sharpe": sharpe, "cagr": cagr, "max_drawdown": dd}


def equal_weight_universe(panel: pd.DataFrame, ret_col: str = "fwd_ret_21") -> dict:
    """Passive in-backtest benchmark: 'just hold all of them'.

    Monthly cross-sectional equal-weight mean forward return over the eligible +
    valid-label names (the same set that enters the IC). Gross (a buy-and-hold
    universe index; near-zero incremental turnover), per the spec addendum. The
    live-decision benchmark (a real small-cap-value / momentum ETF) is chosen at
    paper time, not here.
    """
    d = panel[panel[ret_col].notna()]
    monthly = d.groupby("date")[ret_col].mean()
    return {"monthly": monthly, "stats": curve_stats(monthly)}
