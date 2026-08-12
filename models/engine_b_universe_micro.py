"""Engine B microcap experiment - parameterised point-in-time universe screen.

A SEPARATE module so the frozen baseline screen (models/engine_b_universe.py) is
left byte-for-byte untouched, per docs/ENGINE_B_MICROCAP_SPEC.md implementation
plan step 1 and the build-kickoff handoff (the invariant: re-running the frozen
baseline must reproduce bb3b8e9 exactly). Nothing here imports forward or edits
the frozen path.

Only the size / liquidity / price bands are parameterised. The category, listing
and history rules are IDENTICAL to the baseline and are IMPORTED from the frozen
module (CATEGORY_OK, EXCHANGE_OK, HISTORY_MIN_DAYS) rather than re-stated, so they
cannot silently drift. Column contract and the eligibility logic mirror the frozen
screen exactly; with the BASELINE bands this reproduces the frozen screen's
`eligible` column row-for-row (asserted by the baseline-invariant check in
tests/test_engine_b_microcap_synthetic.py).

Identity key is `permaticker` (attribution happens upstream in data/sharadar_panel.py).
Pure pandas, no I/O, no timing logic - threshold masks on columns already as-of T.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from models import engine_b_universe as ebu  # frozen; import constants, never edit


@dataclass(frozen=True)
class UniverseBands:
    """Size/liquidity/price band for one universe tier (all fixed a priori)."""
    mktcap_min_m: float     # $millions, inclusive
    mktcap_max_m: float     # $millions, inclusive
    dollarvol_min: float    # $ trailing 60-td median dollar volume, inclusive
    price_min: float        # closeadj at T, inclusive
    label: str = ""


# --- a-priori bands (docs/ENGINE_B_MICROCAP_SPEC.md "The universe" + addenda) ---
# BASELINE must equal the frozen baseline screen exactly (invariant check).
BASELINE = UniverseBands(ebu.MKTCAP_MIN_M, ebu.MKTCAP_MAX_M,
                         ebu.DOLLARVOL_MIN, ebu.PRICE_MIN, "liquid")
# Primary microcap band and the a-priori tiers/sensitivities. Liquidity floor
# $250k, price floor $5 are the primary; sensitivities are separate bands built
# by with_floors() in the runner (no dredge - all fixed before any result).
MICRO = UniverseBands(50.0, 300.0, 250_000.0, 5.0, "micro")
NANO = UniverseBands(10.0, 50.0, 250_000.0, 5.0, "nano")
FULL_TAIL = UniverseBands(10.0, 300.0, 250_000.0, 5.0, "full_tail")


def with_floors(bands: UniverseBands, dollarvol_min: float | None = None,
                price_min: float | None = None) -> UniverseBands:
    """Return a copy of `bands` with the liquidity and/or price floor overridden.

    Used to build the a-priori sensitivity variants (liquidity >=$100k/$250k/$500k,
    price >=$2/$5) without restating the size band. Not a tuning knob - the grid is
    fixed in the runner before any result is computed.
    """
    return UniverseBands(
        bands.mktcap_min_m, bands.mktcap_max_m,
        bands.dollarvol_min if dollarvol_min is None else dollarvol_min,
        bands.price_min if price_min is None else price_min,
        bands.label,
    )


def eligibility_mask(df: pd.DataFrame, bands: UniverseBands) -> pd.DataFrame:
    """Per-row boolean frame: one column per screen plus 'eligible'.

    Same contract as models/engine_b_universe.eligibility_mask, with the size,
    liquidity and price thresholds taken from `bands`. No row is dropped; callers
    filter on 'eligible' and report counts (Rule 18).
    """
    ebu._check_cols(df)  # reuse the frozen required-column contract
    m = pd.DataFrame(index=df.index)
    m["type_ok"] = df["category"].isin(ebu.CATEGORY_OK)
    m["listing_ok"] = df["exchange"].isin(ebu.EXCHANGE_OK)
    mc = df["mktcap_T"]
    m["size_ok"] = mc.notna() & (mc >= bands.mktcap_min_m) & (mc <= bands.mktcap_max_m)
    dv = df["dollarvol_60"]
    m["liquidity_ok"] = dv.notna() & (dv >= bands.dollarvol_min)
    px = df["close_T"]
    m["price_ok"] = px.notna() & (px >= bands.price_min)
    m["history_ok"] = df["hist_days"].notna() & (df["hist_days"] >= ebu.HISTORY_MIN_DAYS)
    m["eligible"] = (
        m["type_ok"] & m["listing_ok"] & m["size_ok"]
        & m["liquidity_ok"] & m["price_ok"] & m["history_ok"]
    )
    return m


def screen(df: pd.DataFrame, bands: UniverseBands) -> pd.DataFrame:
    """Attach the eligibility columns to a copy of df and return it."""
    m = eligibility_mask(df, bands)
    out = df.copy()
    for c in m.columns:
        out[c] = m[c].values
    return out


def coverage_report(df_screened: pd.DataFrame) -> pd.DataFrame:
    """Per-rebalance-date screen funnel. Identical to the frozen report - reused."""
    return ebu.coverage_report(df_screened)
