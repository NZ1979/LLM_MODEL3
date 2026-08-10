# PAPER_TRADING_PLAN.md - Engine A

Drafted 2026-08-10, Godzilla (America/Denver). **Paper only. No real money**
under any circumstance until this plan's exit criteria are met and the operator
records a dated decision. `CLAUDE.md`: "No real money until an engine clears
`KILL_RULE.md` AND survives paper trading."

## 0. Status gate - what may be papered, and what may not

| result | status | source |
|---|---|---|
| Engine A kill rule, borrow-complete | **PASS**, net Sharpe 0.59 | `COST_COMPLETENESS_RESULTS.md` |
| Engine A pre-paper financing gate | **PASS**, 0.45 | ditto |
| Engine A implementability | **FAIL** | 3.70x mean gross / 6.81x peak; fails at DTB3 +200 bps |
| Engine A-2 (gross-capped 2.0x) | **FAIL** - conditions 4 and 5 missed | `ENGINE_A2_RESULTS.md` |

> **THIS PLAN IS DORMANT AS OF 2026-08-10.** A-2 was evaluated and missed
> conditions 4 (DTB3 +200 bps: 0.40, below the bar unrounded) and 5 (zero cash
> credit: 0.38). Per `ENGINE_A_CAPPED_SPEC.md` the response is NOT another cap
> level. Sections 1-7 below are retained as the plan that would apply if a
> future candidate clears its gate; none of it activates now.

**Nothing goes to paper until A-2 is evaluated.** Engine A itself is validated but
unimplementable: the account type that could hold 6.81x gross is the same one
whose financing costs take it below the bar. Papering it would generate fills
that no real account could have achieved, which is the "fail loud, never fake"
rule applied to execution rather than data.

If A-2 clears all five pre-registered conditions, **A-2 is what gets papered**,
and everything below applies to it. If A-2 misses, this plan does not activate;
see section 8.

## 1. What paper trading is for

Not to re-measure edge. The backtest already did that, over 25 years, leak-tested.
Paper trading tests the assumptions the backtest could not:

1. **Fills.** Does 2 bps/side survive a real weekly rebalance across 22 ETFs?
2. **Data timing.** Does the signal computable at decision time match the signal
   the backtest used? Vendor restatements, late adjustments, dividend timing.
3. **Borrow availability.** Modelled as a rate. In reality a short can be
   unavailable or recalled. Never tested.
4. **Margin mechanics.** Whether the book can actually be held at the modelled
   exposure through a drawdown without forced deleveraging.
5. **Operational reliability.** Does the pipeline run unattended, every week,
   without silent failure?

Items 3-5 are the ones most likely to kill this, and none of them are visible in
a backtest.

## 2. Instrument and sizing

- **Universe:** the locked 22 ETFs in `config/universe.py`. No additions.
- **Engine:** A-2, `vol_target_mode="ex_ante"`, `gross_cap=2.0`. Parameters
  frozen. Any change restarts the paper period from day one.
- **Notional:** a fixed simulated NAV, chosen once and never resized mid-period.
  Recommend sizing to the smallest account that would realistically be traded, so
  fill assumptions are conservative rather than flattering.
- **Rebalance:** weekly, `W-FRI`, on the close. Signal computed from data through
  Thursday's close, order list generated Friday, executed at Friday's close.
  This preserves the backtest's one-day lag - do not shorten it because live data
  happens to be available sooner.

## 3. What is recorded, every week, without exception

Weekly, to a durable log (parquet, in the data lake, gitignored):

- target weights, prior weights, implied turnover
- for each order: intended price, assumed fill, actual/simulated fill, slippage
  in bps
- realised gross exposure, long/short notional, cash balance
- borrow rate quoted per short name, and any unavailable or recalled name
- margin requirement as a fraction of NAV
- daily NAV, gross and net of every modelled cost

**Slippage tracked against the 2 bps assumption is the single most important
number in the whole exercise.** The cost sensitivity showed the a-priori spec had
a break-even turnover cost of 0.4 bps/side once financing was charged at flat 4%.
Even for A-2, if realised slippage runs materially above 2 bps, the edge is gone
and no amount of paper duration will fix it.

## 4. Duration

**Minimum 6 months, minimum 26 rebalances.** A trend system's payoff is
concentrated in a few regime changes; a 6-month window may contain none. So the
duration is a floor for *operational* validation, not a claim that it re-tests
edge - and this must not be misread later as a second confirmation of the
backtest.

## 5. Monitoring metrics and their reference values

Compared against the A-2 backtest distribution, not against a target:

| metric | reference | check |
|---|---|---|
| realised slippage | 2 bps/side assumed | rolling mean, weekly |
| realised gross exposure | <= 2.0x by construction | any breach is a code defect |
| tracking vs backtest-implied returns | should differ only by fills/timing | weekly diff decomposition |
| borrow availability | 100% assumed | count of unavailable/recalled names |
| drawdown | A-2 backtest max | monitored, not a stop |

Attribute weekly return difference into: signal difference (data timing),
execution difference (slippage), and cost difference (borrow/financing actuals vs
modelled). If a divergence cannot be attributed to one of those three, that is a
bug, and it is investigated before the next rebalance.

## 6. Pre-registered failure conditions

Fixed now, before any paper trading, so they cannot be softened later. **Any one
of these stops the paper period and returns Engine A to the bench:**

1. **Slippage.** Realised mean slippage exceeds 2x the modelled 2 bps/side
   (i.e. > 4 bps) over any trailing 8-rebalance window.
2. **Borrow.** Any required short is unavailable or recalled on more than 10% of
   rebalances, or a name in the 4 largest short positions is unavailable twice.
3. **Margin.** The book cannot be held at target exposure at any point, or a
   simulated margin call occurs.
4. **Signal integrity.** The live-computed signal differs from the
   backtest-recomputed signal for the same date on more than 2 occasions, for any
   reason other than a known vendor restatement.
5. **Operational.** More than one missed or late rebalance.
6. **Unexplained divergence.** Cumulative return difference from the
   backtest-implied path exceeds 5% of NAV without attribution to fills, timing,
   or costs.

Note what is *not* in this list: a drawdown, or a period of poor returns.
Six months of losses is entirely consistent with the backtest (2001, 2012, 2016
and 2023 were all losing years) and is **not** a failure condition. Adding one
later would be a goalpost move in the same family the kill rule forbids.

## 7. Exit criteria - what "survived paper trading" means

All of the following, after the minimum duration:

- no failure condition in section 6 triggered
- realised slippage within the modelled 2 bps/side on a trailing basis
- every weekly return difference attributable to fills, timing, or costs
- borrow obtained for every required short, every rebalance
- the pipeline ran unattended for the full period with no silent failure

Meeting these does **not** authorise real money. It authorises the operator to
make a dated, recorded decision about real money, with sizing addressed
separately. That distinction is deliberate.

## 8. If Engine A-2 fails its evaluation

Per `ENGINE_A_CAPPED_SPEC.md`, the response is **not** another cap level. It is:

- record that Engine A's measured edge does not survive implementable leverage
- leave Engine A's kill-rule verdict standing as-is (0.59 borrow-complete - it
  passed, honestly, on the basis the locked rule specified)
- take the project-level decision in `PROJECT_CHARTER.md` about where effort goes

That decision is the operator's. The Engine B directive is unblocked either way.

## 9. Open items before this plan can activate

1. Evaluate Engine A-2 (`scripts/evaluate_capped.py`) - the blocking item.
2. Choose the simulated NAV and record it here.
3. Build the weekly runner and the paper log schema. Does not exist yet.
4. Decide the borrow-quote source for live rates. `validation/costs.py` holds
   assumptions, not quotes.
5. Confirm the ETF data pull can run reliably on the Friday schedule, with
   fail-loud alerting on a missed pull.

**VERIFIED status of this document:** it is a plan, not a running system. Nothing
in sections 2-7 has been implemented or tested. No paper trading has occurred.
