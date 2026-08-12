"""Engine B microcap experiment - realistic per-name transaction cost model.

docs/ENGINE_B_MICROCAP_SPEC.md "The realistic cost model (the crux - fixed a
priori)". Per-side cost in bps for trading a name, charged on realised turnover
each rebalance:

    cost_bps_per_side = half_spread_bps(tier) + IMPACT_K * sqrt(participation)
                        + COMMISSION_BPS
    participation     = position_notional / dollarvol_60   (60-td median daily $vol at T)

  half_spread by tier (a priori): liquid 10 / micro 50 / nano 150 bps
  IMPACT_K = 100 bps  (sqrt impact: 1% of ADV ~10bps, 10% ~32bps, 100% ~100bps)
  commissions = 1 bp/side
  AUM-aware: position_notional = weight * AUM, so impact grows with book size.
  The whole model is reported scaled 0.5x / 1x / 2x; the decision rule needs
  survival at 2x.

NEW module - leaves the frozen flat-cost harness path
(validation/engine_b_harness.py::_curve_metrics) untouched. Nothing here reads
the panel; it is pure arithmetic over per-name inputs and is unit-tested on
synthetic inputs (tests/test_engine_b_microcap_synthetic.py).

Tier boundaries match the universe size bands: nano [$10M,$50M), micro
[$50M,$300M), liquid [$300M, ...). A name at exactly a boundary tiers to the
higher band's spread cost is the cheaper side, so the convention below (< cut)
is the marginally *less* conservative choice only at an exact, measure-zero
marketcap; it never affects which names are HELD (that is the screen's job).
"""
from __future__ import annotations

import numpy as np

HALF_SPREAD_BPS = {"liquid": 10.0, "micro": 50.0, "nano": 150.0}
IMPACT_K = 100.0          # bps of impact at 100% of ADV participation
COMMISSION_BPS = 1.0      # per side
COST_SCALES = (0.5, 1.0, 2.0)

_NANO_MAX_M = 50.0
_MICRO_MAX_M = 300.0


def tier_for_marketcap(mktcap_m):
    """Tier name(s) by as-of-T marketcap ($M). Scalar -> str; array -> np.ndarray[str]."""
    arr = np.asarray(mktcap_m, dtype=float)
    out = np.where(arr < _NANO_MAX_M, "nano",
                   np.where(arr < _MICRO_MAX_M, "micro", "liquid"))
    if out.ndim == 0:
        return str(out)
    return out


def half_spread_for(mktcap_m):
    """Per-name half-spread in bps from the marketcap tier. Scalar or array."""
    tiers = tier_for_marketcap(mktcap_m)
    if isinstance(tiers, str):
        return HALF_SPREAD_BPS[tiers]
    lut = np.vectorize(HALF_SPREAD_BPS.__getitem__)
    return lut(tiers).astype(float)


def side_cost_bps(participation, half_spread_bps, scale: float = 1.0):
    """Per-side cost in bps. Vectorised over participation / half_spread arrays.

    participation = position_notional / dollarvol_60 (>= 0; a fraction of ADV).
    half_spread_bps = per-name half spread (see half_spread_for).
    scale multiplies the WHOLE model (the 0.5x/1x/2x sensitivity).
    """
    part = np.clip(np.asarray(participation, dtype=float), 0.0, None)
    hs = np.asarray(half_spread_bps, dtype=float)
    return (hs + IMPACT_K * np.sqrt(part) + COMMISSION_BPS) * float(scale)
