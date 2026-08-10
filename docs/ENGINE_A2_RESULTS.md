# Engine A-2 (gross-capped 2.0x) - result of the single pre-registered evaluation

**Run date:** 2026-08-10, Godzilla (America/Denver).
**Spec:** `docs/ENGINE_A_CAPPED_SPEC.md`, committed unrun at `c91b7fe`; this
result was produced after that commit was pushed.
**Data:** Tiingo adjusted EOD, 22 ETFs, 2000-01-03 -> 2026-08-07. FRED `DTB3`.

VERIFIED [terminal output pasted from Godzilla].

## Verdict

**ENGINE A-2 IS NOT PROPOSED FOR PAPER TRADING.** Conditions 1-3 pass;
conditions 4 and 5 fail.

| condition | requirement | result | verdict |
|---|---|---|---|
| 1. borrow-complete | Sharpe >= 0.40, majority windows +ve | **0.44**, 78% | PASS |
| 2. measured financing (DTB3 +100/-25) | Sharpe >= 0.40, majority +ve | **0.42**, 76% | PASS |
| 3. no gross breach of 2.0x | 0 breaches | 0 breaches | PASS |
| 4. clears bar at DTB3 +200 bps | Sharpe >= 0.40 | **0.40** (below 0.40 unrounded) | **FAIL** |
| 5. clears bar with zero cash credit | Sharpe >= 0.40 | **0.38**, 75% | **FAIL** |
| (worst case: +200 bps and no credit) | reported | 0.35, 73% | - |

Condition 4 fails on the third decimal. **That is still a fail.** The entire
purpose of pre-registering a bar is that a near-miss is a miss; rounding 0.399 up
to clear a 0.40 threshold is the goalpost move this project exists to prevent. It
is recorded here precisely so no later session can rediscover it as "essentially a
pass".

## Full results

| cost basis | Sharpe | ann ret | vol | maxDD | roll-1y +ve |
|---|---|---|---|---|---|
| borrow-complete | 0.44 | +6.83% | 15.45% | -41.8% | 78% |
| + measured financing | 0.42 | +6.50% | 15.44% | -40.6% | 76% |
| + financing @ DTB3 +50 bps | 0.43 | +6.67% | 15.44% | -40.6% | 77% |
| + financing @ DTB3 +200 bps | 0.40 | +6.16% | 15.44% | -40.6% | 75% |
| + financing @ DTB3 +400 bps | 0.36 | +5.49% | 15.44% | -40.6% | 72% |
| + zero cash credit | 0.38 | +5.81% | 15.45% | -41.8% | 75% |
| + 200 bps and zero credit | 0.35 | +5.48% | 15.45% | -41.8% | 73% |

Exposure: mean gross **1.97x** (uncapped 3.70x), p95 2.00x, max 2.00x, 0
breaches. The cap binds on **92%** of days. Measured drag: borrow 0.311%/yr,
financing 0.331%/yr - both collapse relative to the uncapped engine (0.525% and
3.276%), exactly as intended.

Leak check on the final cost basis: lag0 0.82 -> lag1 0.42 -> lag2 0.35. Leaked-
vs-causal gap +0.40, monotonic. The harness still detects look-ahead.

## Scoring the prediction recorded before the run

`ENGINE_A_CAPPED_SPEC.md` predicted: return and volatility fall substantially,
drawdown shrinks, financing drag collapses, and the Sharpe direction is genuinely
uncertain because the cap binds unevenly rather than scaling uniformly.

Outcome: return 13.85% -> 6.83%, vol 23.64% -> 15.45%, drawdown -48.9% -> -41.8%,
financing drag 3.276% -> 0.331%. All as predicted. Sharpe fell 0.59 -> 0.44.

The spec also said a materially lower Sharpe "would mean Engine A's edge was
substantially a leverage artefact." That reads as **partly** confirmed, and the
distinction matters:

- The edge is **not purely** a leverage artefact. A 47% cut in average exposure
  cost only 25% of the Sharpe, and the capped engine still beats the mechanical
  baseline (0.31). Something real survives.
- But the surviving edge is **too thin to be safely implementable**. At 0.44
  borrow-complete it has 0.04 of headroom over the bar, and it does not survive
  either of the two assumptions most likely to be wrong in a real account.

## Why conditions 4 and 5 were the right bars, on reflection

Both are stricter than `KILL_RULE.md` and both were added by reasoning, not
inherited. Being explicit about that, since A-2 would have "passed" on conditions
1-3 alone:

- **Condition 4** existed because A-2's entire reason for existing was to remove
  Engine A's dependence on institutional financing. Engine A failed at +200 bps;
  an A-2 that also fails at +200 bps has not solved the problem it was built to
  solve. Passing conditions 1-3 while failing 4 is precisely the outcome the
  condition was written to catch.
- **Condition 5** was added after a synthetic smoke test revealed that a capped
  book carries a large positive cash balance, so the financing term can become a
  net *credit*. Without this stress, A-2 would have been scored partly on the
  assumption that a broker pays DTB3 - 25 bps on idle cash. The measured result
  confirms the concern was real: removing the credit costs 0.04 of Sharpe and
  flips condition 2 from pass to fail.

## What this means

Engine A has a **real but thin** edge that does not survive implementable
constraints with any margin of safety:

- Uncapped, it clears the kill rule comfortably (0.59) but needs 3.70x mean gross
  and institutional financing - unimplementable in practice.
- Capped to what a Reg T account can hold, it clears the kill-rule bar (0.44) but
  fails once financing costs or cash-credit assumptions move against it by an
  amount well inside normal broker variation.

Both statements are true simultaneously. Neither retroactively invalidates the
other.

## Consequences, per the pre-registered failure handling

1. **Do NOT evaluate another cap level.** A second cap requires a fresh, dated
   pre-registration justifying why 2.0x was wrong on grounds independent of this
   result. No such grounds currently exist - 2.0x was chosen from the Reg T
   rulebook, not fitted.
2. **Engine A's kill-rule verdict stands unchanged at net Sharpe 0.59,
   borrow-complete.** It passed honestly on the basis the locked rule specified.
   This document does not revise it.
3. **`docs/PAPER_TRADING_PLAN.md` does not activate.** Its status gate requires
   A-2 to clear all conditions.
4. **A project-level decision is now owed** per `PROJECT_CHARTER.md`. That
   decision belongs to the operator and is not made here.

## Provenance

- `c91b7fe` - A-2 spec pre-registered, unrun
- this document - the single evaluation that spec authorised
