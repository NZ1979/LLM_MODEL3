# FINANCING_SPEC.md - Engine A margin-financing cost

**Pre-registered 2026-08-10 (America/Denver), Godzilla, BEFORE any result was
computed under this specification.** Committed and pushed prior to the measuring
run. If a later session finds this file and the measured result in the same
commit, the pre-registration is void and the result must be discarded and re-run.

## Why this file exists

While modelling the stock-borrow cost owed at commit `edadfda`, a second and much
larger unmodelled cost surfaced: **margin financing on leverage**.

Measured exposure of Engine A (2001-2026, at `edadfda`):

| variant | mean gross | p95 gross | max gross | mean short | days borrowing cash | mean borrowed |
|---|---|---|---|---|---|---|
| a-priori (`18c3239`, ex_ante vol target) | 3.70x | 5.67x | 6.81x | 0.93x | 66% | 1.30x NAV |
| calibrated (`edadfda`, realized vol target) | 2.71x | 4.54x | 5.97x | 0.66x | 58% | 0.82x NAV |

Borrow, the cost `KILL_RULE.md` actually names, is small: 0.53%/yr on the
a-priori variant, moving net Sharpe 0.61 -> 0.59. Financing is roughly ten times
larger. Under an a-priori flat 4% debit it costs 5.21%/yr and takes the a-priori
variant to 0.37. Break-even against the 0.40 bar is a 3.4% flat rate.

A flat rate is an assumption, and 3.4% sits inside the range of defensible
assumptions - which means the flat-rate sweep cannot adjudicate anything. Picking
a friendlier flat rate after seeing 0.37 would be a goalpost move. The remedy is
to replace the assumption with a **measurement**: the actual historical
short-rate path, with the rate spec fixed in advance. That is this file.

## Status of this cost under the locked kill rule

**Financing is NOT part of the kill-rule test.** `KILL_RULE.md` is locked and its
"net of cost" guardrail names slippage, commissions, and borrow. Adding a cost to
a locked bar after seeing results would tighten it retroactively, which is the
same class of error as loosening it.

Operator decision, 2026-08-10: the kill-rule verdict is adjudicated
**borrow-complete**. Financing is a separate **pre-paper realism gate** recorded
here. Engine A may not go to paper trading until this gate is evaluated and the
result recorded, whatever it says.

## The specification (fixed in advance, evaluated once)

**Rate source.** FRED series `DTB3` - 3-Month Treasury Bill, Secondary Market
Rate, Discount Basis, daily, percent per annum. Chosen because it is a daily
series covering the whole 2000-2026 backtest span from a free public source, and
because a 3-month bill is the conventional benchmark for broker cash rates.
Loader: `data/fred_rates.py`. Stored at `data/raw/fred/DTB3.parquet`.

**Alignment.** Reindex to the ETF panel's trading days and forward-fill (bill
rates are step functions between quotes; forward-fill is causal). No
back-filling. Any date before the series starts is a hard error, not a zero.

**Rates applied, with NAV normalised to 1, long notional L, short notional S,
and cash balance `c = 1 + S - L`:**

- Debit (when `c < 0`, the account is borrowing):
  `debit_rate_t = DTB3_t + 100 bps`
- Credit (when `c > 0`, the account holds cash):
  `credit_rate_t = max(DTB3_t - 25 bps, 0)`

Daily charge = `(max(-c, 0) * debit_rate_t - max(c, 0) * credit_rate_t) / 252`.

**Justification of the two spreads, fixed a priori:**

- **+100 bps debit.** Mid-range for a portfolio-margin book of liquid ETFs at a
  competitive prime broker. Retail Reg T margin is far worse (300-600 bps over
  benchmark); a large institutional book is better (25-50 bps). 100 bps is the
  honest middle for an account that can actually be opened at this size.
- **-25 bps credit.** Brokers pay slightly under the benchmark on credit
  balances. Crediting cash at all is a correction, not a concession: the prior
  flat-rate model credited zero, which is an accounting error, not conservatism.
  The 25 bps haircut keeps the correction from over-crediting.

Note that `c` already nets short-sale proceeds against long financing, which is
the standard prime-broker treatment. Short proceeds therefore reduce the debit
directly; they are not double-counted against the separate borrow fee, which is
charged on short notional in `validation/costs.py`.

**Sensitivity to be reported alongside the measured result** (so the measurement
is not itself a single point estimate): debit spread at +50, +100, +200, +400 bps
over `DTB3`, holding the credit spread at -25 bps.

## Pre-registered pass condition for the realism gate

Evaluated on the **a-priori variant** (`vol_target_mode="ex_ante"`), 2 bps
turnover, borrow at the `validation/costs.py` table, financing per the spec
above, over the full 2001-2026 span:

- **Gate PASSES** iff net Sharpe >= 0.40 AND positive in a clear majority of
  rolling 1-year windows - the same two conditions as the kill rule, applied to a
  cost basis the kill rule does not require.
- **Gate FAILS** otherwise.

A FAIL does not retroactively fail the kill rule. It means Engine A as currently
specified is not implementable at its evaluated leverage, and the response is a
new a-priori variant with a genuine gross-exposure cap, evaluated once as a
separate candidate - not a re-tuning of the existing engine.

## Known leverage-implementability finding (documented, not fixed)

`models/engine_a.py` sets `LEV_CAP = 2.5`, but that caps the **vol-target
multiplier**, not gross exposure. Pre-overlay gross (`w_base`) averages 7.37x, so
realised gross lands at 2.71x mean / 5.97x max on the calibrated variant and
3.70x / 6.81x on the a-priori one. Gross exceeds 2.0x on 71% of days, above what
a Reg T account permits overnight.

This is recorded, deliberately **not** patched. Changing the cap alters engine
parameters after adjudication; any capped version is a new candidate requiring
its own single evaluation. Carried into `docs/PAPER_TRADING_PLAN.md`.

## Changelog

- 2026-08-10 - Created and pre-registered. Rate source, spreads, alignment rule,
  sensitivity grid, and pass condition fixed before the measuring run. Operator
  decisions recorded: financing treated as a separate pre-paper realism gate
  rather than folded into the locked kill rule; leverage-cap finding documented
  rather than patched.
