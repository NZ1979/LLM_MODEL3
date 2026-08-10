# Engine A cost completeness - results of record

**Run date:** 2026-08-10, Godzilla (America/Denver).
**Code:** commit `618f18c` (`docs/FINANCING_SPEC.md` + cost model, pre-registered
and pushed with no results in it).
**Data:** Tiingo adjusted EOD, 22 ETFs, panel 2000-01-03 -> 2026-08-07 (6689
days), re-pulled 2026-08-10, integrity check PASS (3 soft zero-volume flags:
XLRE 2, EFA 1, IEF 9). FRED `DTB3` 1954-01-04 -> 2026-08-06, 18140 observations.

VERIFIED [terminal output pasted from Godzilla, both scripts]. Everything below
is measured, not inferred.

## What was owed and what closed it

At commit `edadfda` the harness charged only 2 bps per unit of turnover.
`KILL_RULE.md` requires borrow on any short leg. That was the debt. Modelling it
surfaced a second, larger gap - margin financing on leverage - handled as a
separate pre-registered gate (`docs/FINANCING_SPEC.md`).

## Measured exposure (why these costs are not rounding errors)

| variant | mean gross | p95 | max | mean short | days short | days borrowing cash | mean borrowed |
|---|---|---|---|---|---|---|---|
| a-priori `ex_ante` | 3.70x | 5.67x | 6.81x | 0.93x | 92% | 66% | 1.30x NAV |
| calibrated `realized` | 2.72x | 4.54x | 5.97x | 0.66x | 92% | 58% | 0.82x NAV |

Measured annual drag: borrow **0.525%** and financing **3.276%** (a-priori);
borrow **0.375%** and financing **1.919%** (calibrated).

## 1. Kill-rule verdict - borrow-complete

The locked bar: net OOS Sharpe >= 0.40 AND positive in a clear majority of
rolling windows. Adjudicated on the a-priori spec (`18c3239`), which is where the
official verdict lives.

| cost basis | Sharpe | ann ret | vol | maxDD | roll-1y +ve | verdict |
|---|---|---|---|---|---|---|
| 2 bps turnover only (as originally evaluated) | 0.61 | +14.37% | 23.64% | -48.4% | 80% | PASS |
| **+ borrow @ a-priori table** | **0.59** | **+13.85%** | **23.64%** | **-48.9%** | **80%** | **PASS** |
| + borrow @ 3x stress | 0.54 | +12.80% | 23.64% | -49.9% | 78% | PASS |
| + borrow @ 10x stress | 0.39 | +9.12% | 23.64% | -54.1% | 71% | FAIL |

**Engine A PASSES the kill rule on a borrow-complete cost basis at net Sharpe
0.59.** Borrow costs 0.02 of Sharpe. It survives a 3x rate stress and only breaks
at 10x, which is far outside the plausible range for ETFs this liquid. The debt
named in `KILL_RULE.md` is closed.

Calibrated variant for reference (not adjudicating): 0.71 -> **0.69**
borrow-complete, and still 0.48 at 10x stress.

## 2. Pre-paper financing gate - measured, not assumed

Spec pre-registered in `docs/FINANCING_SPEC.md` and committed before this run:
debit = `DTB3` + 100 bps on borrowed cash, credit = max(`DTB3` - 25 bps, 0) on
positive cash, cash balance `c = 1 + short - long`. Over the evaluation window
`DTB3` averaged **1.77%** (min -0.05%, max 5.36%), giving a mean effective debit
of 2.77% and mean credit of 1.58%.

| a-priori spec | Sharpe | ann ret | maxDD | roll-1y +ve | verdict |
|---|---|---|---|---|---|
| borrow only (the kill-rule basis) | 0.59 | +13.85% | -48.9% | 80% | PASS |
| **+ measured financing (DTB3 +100/-25)** | **0.45** | **+10.57%** | **-47.5%** | **73%** | **PASS** |
| + financing @ DTB3 +50 bps | 0.47 | +11.22% | -47.4% | 74% | PASS |
| + financing @ DTB3 +200 bps | 0.39 | +9.27% | -47.7% | 70% | **FAIL** |
| + financing @ DTB3 +400 bps | 0.28 | +6.67% | -51.6% | 64% | **FAIL** |

**GATE: PASS at net Sharpe 0.45, 73% of rolling years positive.**

Calibrated variant: 0.57 measured, and still PASS at +400 bps (0.42).

### The caveat that matters more than the pass

The a-priori spec **fails at a +200 bps debit spread**. Retail Reg T margin runs
300-600 bps over benchmark. So the gate passes only on the assumption of
portfolio margin at roughly institutional financing rates. Combined with the
leverage finding below, the honest conclusion is:

> **The a-priori spec as adjudicated is not implementable in a retail account at
> any financing cost that would also let it pass.**

That is not a kill-rule failure - the kill rule is about edge, and the edge is
there. It is an implementability failure, and it is what
`docs/ENGINE_A_CAPPED_SPEC.md` exists to address.

## 3. Flat-rate sensitivity (superseded by the measured path, kept for the record)

A-priori spec: 0.48 at flat 2%, 0.37 at 4%, 0.26 at 6%, 0.15 at 8%. Break-even
flat financing rate **3.4%**; break-even turnover cost at flat 4% financing is
0.4 bps/side. Calibrated: 0.59 / 0.49 / 0.39 / 0.29, break-even 5.7% and
5.2 bps/side.

The flat-rate grid straddles the bar within the range of defensible assumptions,
which is precisely why it was replaced by the measured `DTB3` path under a spec
fixed in advance.

## 4. Leverage-cap defect (found, documented, deliberately unpatched)

`models/engine_a.py` sets `LEV_CAP = 2.5`, but that bounds the **vol-target
multiplier**, not gross exposure. Pre-overlay gross (`w_base`) averages 7.37x and
the multiplier averages 0.44, so realised gross lands at the levels tabled above.
Gross exceeds 2.0x on **71%** of days and 4.0x on **15%** of days.

Not patched in this work. Changing it alters engine parameters after
adjudication; a capped engine is a new candidate requiring its own single
evaluation. See `docs/ENGINE_A_CAPPED_SPEC.md`.

## 5. Verification performed

- **Reproduction.** Both variants reproduce their committed numbers bit-for-bit
  from HEAD via `vol_target_mode` (0.61 / 0.71 at 2 bps, including the +32.9%
  2008 figure for the a-priori spec).
- **Backward compatibility.** `backtest.run(extra_cost=None)` is the default and
  reproduces every pre-`edadfda` result unchanged.
- **Arithmetic cross-check.** Drag reconciles independently of the harness:
  13.85% - 3.276% = 10.57% observed; 10.57 / 23.63 = 0.447 -> 0.45 reported.
- **Leak test.** Monotonic decay on the cost-complete engine (a-priori
  lag0 0.84 -> lag1 0.37 -> lag2 0.29; calibrated 0.96 -> 0.49 -> 0.41). VERIFIED
  on the 2026-06-17 panel at flat 4% financing. A re-check on the refreshed panel
  at the measured rate path is now built into `scripts/financing_gate.py`. Cost
  terms are subtracted after weights are formed and cannot introduce look-ahead,
  so this is confirmation rather than an open risk.
- **Fail-loud paths tested.** Missing borrow rate raises; a rate series not
  covering the panel raises rather than substituting zero; non-positive gross cap
  raises.

## 6. What is still not modelled

Stated plainly rather than buried:

- **Slippage and market impact.** Only a flat per-unit-turnover charge. At 2 bps
  this is optimistic for a levered weekly rebalance; the sensitivity grid shows
  the a-priori spec is highly sensitive here (break-even 0.4 bps once financing
  is charged at flat 4%, 5.2 bps for the calibrated variant).
- **Borrow availability.** Rates are modelled; the assumption that a short is
  *available at all* is not. Recall risk is unmodelled.
- **Historical borrow rates are assumptions**, not observations. The 3x and 10x
  stress rows exist because of that.
- **Dividend/withholding treatment on short legs.** Short positions owe
  dividends; adjusted-close returns embed them on the long side symmetrically, so
  this is approximately handled, but not explicitly modelled.
- **Margin-call path dependence.** A -48.9% drawdown at 3.70x gross would very
  likely trigger forced deleveraging before the modelled recovery. The backtest
  assumes the position is held through.

The last item is material and argues in the same direction as the gross-cap work.

## Provenance

- `618f18c` - cost model + pre-registered financing spec (no results)
- this document - results computed under that commit
