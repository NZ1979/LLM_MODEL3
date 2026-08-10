# ENGINE_A_CAPPED_SPEC.md - Engine A-2, gross-capped variant

**Pre-registered 2026-08-10 (America/Denver), Godzilla. NO RESULT COMPUTED UNDER
THIS SPEC EXISTS AT THE TIME OF THIS COMMIT.** The implementation was tested only
against synthetic weight matrices, deliberately without touching price data, so
that its performance was unobserved when the spec was fixed. If a later session
finds this file and a result under it in the same commit, the pre-registration is
void and the result must be discarded and re-run.

## Why this variant exists

Engine A as adjudicated PASSES the kill rule borrow-complete (net Sharpe 0.59)
and PASSES the pre-paper financing gate (0.45). It is nonetheless **not
implementable**, for two reasons measured in `docs/COST_COMPLETENESS_RESULTS.md`:

1. **Exposure.** Gross averages 3.70x NAV, peaks at 6.81x, and exceeds 2.0x on
   71% of days. A Reg T margin account cannot hold that overnight.
2. **Financing.** The gate passes at DTB3 +100 bps but **fails at +200 bps**
   (0.39). Retail margin runs 300-600 bps over benchmark. So the account type
   that could hold the exposure is the same one whose financing costs sink it.

Those two constraints close on each other. Reducing gross exposure attacks both
at once: it is what a Reg T account can hold, and it shrinks the borrowed cash
balance that financing is charged on.

## Status: a NEW candidate, not a re-tune

This is **Engine A-2**, a separate a-priori candidate evaluated **once**. It does
not replace, revise, or rescue the adjudicated Engine A, whose verdict stands at
0.59 borrow-complete regardless of what A-2 does. If A-2 misses, it misses, and
Engine A remains a validated-but-unimplementable result.

Stating the failure mode this guards against: running caps at 1.5x, 2x, 2.5x,
3x, picking the best, and reporting it as though it were one honest evaluation.
**One cap level. One evaluation. Fixed below, before any run.**

## The specification

Engine A-2 is Engine A with **exactly one change**: a cap on total gross
exposure. Every other parameter is inherited unchanged - lookbacks (63/126/252),
`VOL_WINDOW` 60, `VOL_FLOOR` 0.05, `TARGET_PORT_VOL` 0.15, `LEV_CAP` 2.5,
weekly `W-FRI` rebalance, 1-day lag, the same 22-ETF universe and 4 macro classes.

**Cap: `GROSS_CAP = 2.0`** - total gross exposure (sum of absolute weights) may
not exceed 2.0x NAV on any day.

Chosen a priori, before any evaluation, because 2.0x is the Reg T overnight
limit. It is a **constraint imported from the brokerage rulebook, not a parameter
selected for performance** - which is exactly why it is defensible to fix without
searching.

**Vol-target mode: `ex_ante`** - the a-priori overlay from `18c3239`. A-2 is
built on the adjudicated spec, not on the post-hoc calibration.

**Mechanics** (`models.engine_a.apply_gross_cap`):

```
gross_t = sum(|w_t|)
scale_t = min(GROSS_CAP / gross_t, 1.0)      # scale down only, never up
w_t     = w_t * scale_t
```

Applied to weights that are already lagged, using a scalar derived from those
same weights. It introduces no new information and cannot leak: knowing
yesterday's position means knowing its gross today. It is a constraint, not a
leverage target, so it never adds exposure on a quiet day. Direction and relative
sizing within the book are preserved exactly - a capped day is a pure rescale.

## Cost basis for the evaluation

Identical to the basis used for Engine A, so results are directly comparable:

- turnover 2 bps/side
- borrow per the a-priori table in `validation/costs.py`
- financing per `docs/FINANCING_SPEC.md` (DTB3 +100 bps debit, DTB3 -25 bps
  credit, floored at 0)

## Pre-registered pass conditions

Both must hold, on the full 2001-2026 span:

1. **Kill-rule basis (borrow-complete):** net Sharpe >= 0.40 AND positive in a
   clear majority of rolling 1-year windows.
2. **Financing gate (measured DTB3 path):** net Sharpe >= 0.40 AND positive in a
   clear majority of rolling 1-year windows.

**Additionally reported, and pre-committed as the reason this variant exists** -
these are recorded whatever they say, and condition 3 is a hard requirement
because a variant that still cannot be held is not a solution:

3. Realised gross exposure must not exceed 2.0x on any day (mechanical check).
4. Financing sensitivity at DTB3 +50 / +100 / +200 / +400 bps. **A-2 is only
   proposed for paper trading if it also clears the bar at +200 bps**, since that
   is the spread at which Engine A failed and the whole point of A-2 is to remove
   the dependence on institutional financing.
5. **Zero-cash-credit stress.** A book capped at 2.0x gross carries a large
   positive cash balance, so the measured financing term may be a net *credit*
   rather than a cost. That would mean A-2 passes partly on the assumption that a
   broker pays DTB3 - 25 bps on idle cash, which the debit grid above cannot
   detect. A-2 must therefore also clear the bar with the credit rate set to
   **zero**. The combined worst case (+200 bps debit and zero credit) is reported
   alongside. Added 2026-08-10, before any run under this spec - it can only make
   the gate stricter, never rescue a failing result.

## Anticipated outcome, recorded before the run

Recording the prediction so it can be scored honestly afterwards, and so a
result that merely matches expectation cannot later be presented as a discovery:

Capping gross at 2.0x removes roughly half the a-priori variant's average
exposure (3.70x -> <=2.0x). Expect annual return and volatility to fall
substantially, drawdown to shrink from -48.9%, and financing drag to fall sharply
because the borrowed cash balance collapses. Sharpe is scale-invariant with
respect to a *constant* leverage change, so the direction of the Sharpe move is
genuinely uncertain: the cap binds unevenly across time, which changes the return
profile rather than merely scaling it. It will bind hardest in calm, high-leverage
periods, which for a trend system are often the profitable ones. **A materially
lower Sharpe than 0.45 is a plausible and acceptable outcome, and would mean
Engine A's edge was substantially a leverage artefact.**

## Failure handling, fixed in advance

If A-2 misses either bar, the response is **not** a different cap level. It is to
record that Engine A's edge does not survive implementable leverage, leave the
adjudicated Engine A result standing as-is, and take the project-level decision in
`PROJECT_CHARTER.md` about where effort goes next. A second cap level may only be
evaluated under a fresh, separately dated pre-registration that states why the
first was wrong on grounds independent of its result.

## Changelog

- 2026-08-10 - Created and pre-registered. Cap level, vol-target mode, cost
  basis, pass conditions, sensitivity requirement, anticipated outcome, and
  failure handling all fixed before the first run. Implementation verified
  against synthetic weights only.
