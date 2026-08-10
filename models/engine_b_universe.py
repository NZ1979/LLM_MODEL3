"""Engine B (P3) - point-in-time universe screen.

Implements the eligibility rules in docs/ENGINE_B_BASELINE_SPEC.md section
"The universe", operating on the assembled cross-section produced by
data/sharadar_panel.py. Every screen uses ONLY information knowable at the
rebalance date T; nothing here reads forward.

Identity key is `permaticker` (NEVER the ticker string - tickers are recycled
after delisting, and keying on ticker grafts a dead company's identity onto its
successor). Attribution of prices/fundamentals to permaticker happens upstream
in data/sharadar_panel.py; this module assumes each row is already the correct
(date, permaticker) point-in-time record.

Pure pandas, no I/O, no timing logic (the trailing/forward windows live in
data/sharadar_panel.py where they are cross-checked against a pandas oracle in
the synthetic tests). This module only applies threshold masks to columns that
are already as-of T.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

# --- pre-registered thresholds (docs/ENGINE_B_BASELINE_SPEC.md). Do NOT edit to
# --- fit results; a change requires a fresh dated pre-registration.
CATEGORY_OK = ("Domestic Common Stock", "Domestic Common Stock Primary Class")
EXCHANGE_OK = ("NYSE", "NASDAQ", "NYSEMKT")
MKTCAP_MIN_M = 300.0        # $millions (Sharadar marketcap is in $M)
MKTCAP_MAX_M = 15000.0      # $15B
DOLLARVOL_MIN = 5_000_000.0  # $5M trailing 60-td median dollar volume
PRICE_MIN = 5.0             # closeadj >= $5
HISTORY_MIN_DAYS = 252      # >= 252 trading days of history before T

# Columns the cross-section must carry for the screen to run.
REQUIRED_COLS = (
    "date", "permaticker", "category", "exchange",
    "close_T", "mktcap_T", "dollarvol_60", "hist_days",
)


def _check_cols(df: pd.DataFrame) -> None:
    missing = [c for c in REQUIRED_COLS if c not in df.columns]
    if missing:
        raise ValueError(f"universe: cross-section missing required columns: {missing}")


def eligibility_mask(df: pd.DataFrame) -> pd.DataFrame:
    """Return a per-row boolean frame: one column per screen plus 'eligible'.

    df is the assembled cross-section (one row per (date, permaticker), all
    fields already as-of T). No row is dropped here; callers filter on
    'eligible' and report the counts (Rule 18 - fail loud, show denominators).
    """
    _check_cols(df)
    m = pd.DataFrame(index=df.index)
    m["type_ok"] = df["category"].isin(CATEGORY_OK)
    m["listing_ok"] = df["exchange"].isin(EXCHANGE_OK)
    # size band: marketcap must be present AND inside [300M, 15B]
    mc = df["mktcap_T"]
    m["size_ok"] = mc.notna() & (mc >= MKTCAP_MIN_M) & (mc <= MKTCAP_MAX_M)
    dv = df["dollarvol_60"]
    m["liquidity_ok"] = dv.notna() & (dv >= DOLLARVOL_MIN)
    px = df["close_T"]
    m["price_ok"] = px.notna() & (px >= PRICE_MIN)
    m["history_ok"] = df["hist_days"].notna() & (df["hist_days"] >= HISTORY_MIN_DAYS)
    m["eligible"] = (
        m["type_ok"] & m["listing_ok"] & m["size_ok"]
        & m["liquidity_ok"] & m["price_ok"] & m["history_ok"]
    )
    return m


def screen(df: pd.DataFrame) -> pd.DataFrame:
    """Attach the eligibility columns to a copy of df and return it."""
    m = eligibility_mask(df)
    out = df.copy()
    for c in m.columns:
        out[c] = m[c].values
    return out


def coverage_report(df_screened: pd.DataFrame) -> pd.DataFrame:
    """Per-rebalance-date counts of candidates and survivors of each screen.

    Surfaces the funnel (Rule 18): how many names each screen removes, so a
    thin universe is visible rather than hidden behind a clean equity curve.
    """
    g = df_screened.groupby("date")
    rep = pd.DataFrame({
        "candidates": g.size(),
        "type_ok": g["type_ok"].sum(),
        "listing_ok": g["listing_ok"].sum(),
        "size_ok": g["size_ok"].sum(),
        "liquidity_ok": g["liquidity_ok"].sum(),
        "price_ok": g["price_ok"].sum(),
        "history_ok": g["history_ok"].sum(),
        "eligible": g["eligible"].sum(),
    })
    return rep.astype(int)
