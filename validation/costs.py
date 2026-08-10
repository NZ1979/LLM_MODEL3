"""Realistic-cost components for Engine A: stock-borrow and margin financing.

KILL_RULE.md, "Guardrails on interpreting these":
    "Net of cost" means after modeled slippage, commissions, and (for any short
    leg) borrow. Gross-only results do not count toward any threshold.

Through commit edadfda the harness charged ONLY 2 bps per unit of turnover.
Engine A shorts down-trending ETFs (short exposure averages ~0.66x NAV and is
non-zero on 92% of days) and runs levered (gross exposure averages ~2.7x NAV),
so two costs were missing. This module supplies both.

------------------------------------------------------------------------------
1. BORROW (the debt named in KILL_RULE.md)
------------------------------------------------------------------------------
Charged daily on gross short notional: rate_i * |min(w_i, 0)| / 252.

Historical ETF borrow rates are not observable in our data lake (Tiingo gives
prices, not securities-lending fees), so these are ASSUMPTIONS, fixed A PRIORI
here before any cost-inclusive result was computed. They are set at the
pessimistic end of the general-collateral range for each name so that the base
case is already conservative, and scripts/cost_sensitivity.py then stresses them
by 3x and 10x. The honest claim is not "these are the true rates" but "the
result survives rates far worse than these."

Tiering rationale (a priori, from lending-supply depth, not from results):
  deep   30 bps/yr - very large AUM, deep and stable lending supply
  normal 50 bps/yr - liquid but shallower books
  tight 125 bps/yr - small AUM and/or persistent hedging demand (HYG is a
                     standard credit hedge; USO/DBC are small commodity funds;
                     XLRE is the smallest sector SPDR)

------------------------------------------------------------------------------
2. MARGIN FINANCING (a gap found while modelling borrow, 2026-08-10)
------------------------------------------------------------------------------
Not named in the kill rule, but "realistic costs" in PROJECT_CHARTER.md cannot
mean ignoring the cost of leverage when the book averages 2.7x gross. With NAV
normalised to 1, long notional L and short notional S:

    net cash  c = 1 + S - L

c < 0 means the account is borrowing cash and pays (rf + broker spread);
c > 0 means it holds cash and would earn interest. We charge the debit and, by
default, credit NOTHING on the balance - deliberately one-sided in the
conservative direction. Rates are swept flat rather than fitted to a historical
rf path: a flat 6% all-in debit is worse than any plausible 2001-2026 path, so
surviving it is a stronger statement than surviving a fitted path.

Nothing in this module touches the engine. Engine A's parameters remain exactly
as evaluated a priori; no goalpost moves.
"""
import pandas as pd

TRADING_DAYS = 252

_DEEP = 30.0
_NORMAL = 50.0
_TIGHT = 125.0

# ticker -> annualised borrow rate in bps. Fixed a priori 2026-08-10.
BORROW_BPS = {
    # deep lending supply
    "SPY": _DEEP, "GLD": _DEEP, "TLT": _DEEP, "IEF": _DEEP, "SHY": _DEEP,
    "EFA": _DEEP, "LQD": _DEEP,
    # liquid, shallower books
    "XLK": _NORMAL, "XLF": _NORMAL, "XLE": _NORMAL, "XLV": _NORMAL,
    "XLI": _NORMAL, "XLY": _NORMAL, "XLP": _NORMAL, "XLU": _NORMAL,
    "XLB": _NORMAL, "EEM": _NORMAL, "VNQ": _NORMAL,
    # small AUM and/or persistent hedging demand
    "HYG": _TIGHT, "USO": _TIGHT, "DBC": _TIGHT, "XLRE": _TIGHT,
}


def short_notional(weights: pd.DataFrame) -> pd.Series:
    """Gross short exposure per day, as a fraction of NAV (positive number)."""
    return (-weights.clip(upper=0.0)).sum(axis=1)


def long_notional(weights: pd.DataFrame) -> pd.Series:
    return weights.clip(lower=0.0).sum(axis=1)


def net_cash(weights: pd.DataFrame) -> pd.Series:
    """Cash balance with NAV normalised to 1. Negative = borrowing on margin."""
    return 1.0 + short_notional(weights) - long_notional(weights)


def borrow_cost(weights: pd.DataFrame, borrow_bps: dict = None,
                stress: float = 1.0) -> pd.Series:
    """Daily borrow cost as a fraction of NAV. stress multiplies every rate.

    Fails loud on a ticker with no assigned rate rather than silently treating
    it as free to borrow.
    """
    rates = dict(BORROW_BPS if borrow_bps is None else borrow_bps)
    missing = [t for t in weights.columns if t not in rates]
    if missing:
        raise KeyError(f"no borrow rate assigned for: {sorted(missing)}")

    shorts = -weights.clip(upper=0.0)                      # positive notional
    rate = pd.Series({t: rates[t] for t in weights.columns}) * stress / 1e4
    return shorts.mul(rate, axis=1).sum(axis=1) / TRADING_DAYS


def financing_cost(weights: pd.DataFrame, debit_rate, credit_rate=0.0) -> pd.Series:
    """Daily cost of carrying the book's cash balance, as a fraction of NAV.

    debit_rate  - annualised all-in rate paid on borrowed cash (rf + spread).
    credit_rate - annualised rate earned on a positive cash balance.

    Each may be a scalar (the flat-rate sensitivity sweep) or a pd.Series indexed
    by date (the measured path per docs/FINANCING_SPEC.md). A Series is aligned
    to the weight index and must cover it fully - a missing rate raises rather
    than defaulting to zero, since a zero rate would understate the cost and
    flatter the strategy.
    """
    c = net_cash(weights)
    d = _as_rate(debit_rate, c.index, "debit_rate")
    k = _as_rate(credit_rate, c.index, "credit_rate")
    return ((-c.clip(upper=0.0)) * d - c.clip(lower=0.0) * k) / TRADING_DAYS


def _as_rate(rate, index: pd.Index, name: str):
    if isinstance(rate, pd.Series):
        aligned = rate.reindex(index)
        if aligned.isna().any():
            raise ValueError(
                f"{name}: {int(aligned.isna().sum())} dates uncovered by the rate "
                f"series; refusing to substitute zero")
        return aligned
    return float(rate)


def total_extra_cost(weights: pd.DataFrame, borrow_stress: float = 1.0,
                     debit_rate=0.0, credit_rate=0.0,
                     include_borrow: bool = True) -> pd.Series:
    """Borrow + financing, ready to hand to backtest.run(extra_cost=...)."""
    out = pd.Series(0.0, index=weights.index)
    if include_borrow:
        out = out + borrow_cost(weights, stress=borrow_stress)
    has_fin = isinstance(debit_rate, pd.Series) or isinstance(credit_rate, pd.Series) \
        or bool(debit_rate) or bool(credit_rate)
    if has_fin:
        out = out + financing_cost(weights, debit_rate, credit_rate)
    return out
