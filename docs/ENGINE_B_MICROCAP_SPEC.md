# ENGINE_B_MICROCAP_SPEC.md — Engine B microcap-tail universe experiment

**Pre-registered 2026-08-11 (America/Denver), Godzilla. NO RESULT COMPUTED UNDER
THIS SPEC EXISTS AT THE TIME OF THIS COMMIT.** This file fixes the universe change,
the realistic microcap cost model, the low-turnover long-only construction, the
evaluation geometry, and the a-priori decision rule **before** any microcap IC or
net return has been computed. If a later session finds this file and a result under
it in the same commit, the pre-registration is void and the result must be
discarded and re-run.

## Why this exists (a NEW question, not a re-tune)

The frozen mechanical baseline (`docs/ENGINE_B_BASELINE_SPEC.md`, results
`bb3b8e9`) deliberately screened to a **liquid small/mid band ($300M–$15B)** and
found a small, clean edge: build rank-IC +0.0254, long-only D10 Sharpe ~0.54, net of
a flat 10bps/side. That result **stands and is not re-opened here.**

This spec asks a **different, previously-untested question**, grounded in two facts
that are knowable a priori and independent of any result:

1. **Cross-sectional equity alpha concentrates in small, illiquid, under-covered
   names and decays in large liquid ones** — one of the most robust findings in the
   literature, and cited in `PROJECT_CHARTER.md` §4 ("concentrates in microcaps…
   decays ~57% net of costs in liquid large-caps").
2. **At ~$500k an individual can actually trade the microcap tail that large funds
   physically cannot** (a $2B fund would move a $500k-ADV stock). That size is a
   structural advantage the liquid-universe baseline throws away.

The charter excluded microcaps ("not microcaps at this capital") on **capacity /
scalability** grounds — correct for building a large-AUM fund, but the question here
is whether **$500k of the operator's own capital** can capture a materially larger
net edge in the tail. That is a legitimate, separately-dated experiment (charter §9
allows appended dated decisions), **not** a goalpost-move on the frozen baseline.

**The bar is NET tradeable Sharpe, not IC.** Microcaps have bigger *gross* edge and
*savage* costs; the whole point is to find out whether an honest cost model and a
low-turnover construction leave anything. This spec is built to make it easy for the
answer to be "no."

## Data of record

Same frozen panel as the baseline (`data/raw/sharadar/*.parquet`; identity key
`permaticker`). **The microcap names are already in the built panel** — the baseline
screen filtered them out, so this experiment is a change of *screen + cost +
construction*, nothing new ingested. `data/sharadar_panel.py`,
`models/engine_b_factors.py`, and the IC/decile parts of
`validation/engine_b_harness.py` are **reused unchanged**; the realistic cost model
and the low-turnover construction are **new modules** (do not edit the frozen
flat-cost path).

## The universe (point-in-time, reconstructed at each rebalance)

Identical construction rules to the baseline (§"The universe") EXCEPT the size,
liquidity, and price screens. A name is eligible for month T iff, using data with
effective date ≤ T:

1. **Security type:** `tickers.category` in {Domestic Common Stock, Domestic Common
   Stock Primary Class} (same).
2. **Listing:** NYSE / NASDAQ / NYSEMKT (same — OTC/pink **excluded**; that is where
   the worst fraud and illiquidity live, and an honest first test should not lean on
   it).
3. **Size band (CHANGED):** `daily.marketcap` at T in the **microcap band
   [$50M, $300M]** (primary). Reported a-priori tiers (fixed now, no dredge):
   - **nano** [$10M, $50M] (reported separately — the extreme tail),
   - **full tail** [$10M, $300M] (combined),
   - the frozen **liquid** [$300M, $15B] is the comparison benchmark (already
     measured — not recomputed).
4. **Liquidity floor (CHANGED):** trailing 60-day median dollar volume ≥ **$250k**
   (primary; the baseline's $5M would exclude almost all microcaps). Sensitivities
   reported at ≥$100k and ≥$500k.
5. **Price floor (CHANGED):** `closeadj` at T ≥ **$5** (primary — avoids the worst
   sub-$5 microstructure/bid-ask-bounce pseudo-alpha). Sensitivity reported at ≥$2.
6. **History:** ≥252 trading days before T (same).

**Survivorship is load-bearing here.** Microcaps delist far more often; the panel is
survivorship-free and the delisting return is folded into the label (baseline
`fwd_status`: `delisted_partial`). This is exactly why most microcap backtests are
worthless (survivorship bias makes dead strategies look brilliant) and why this one
can be honest. The delisting rate in each band is **reported** (Rule 18) and is
expected to be high.

## Factors and label (UNCHANGED — for comparability and no dredge)

The **identical frozen five equal-weight z-scored factors** from
`models/engine_b_factors.py` (12-1 momentum, value = EY+B/P, quality = gross
profitability, low-vol, size), winsorised ±3 SD then z-scored within each date's
eligible universe. **No factor is changed, added, or reweighted** — the only
differences from the baseline are the universe, the cost model, and the construction.
Label: forward 21-day total return from `closeadj`, delisting folded in (same).

## The realistic cost model (the crux — fixed a priori)

The baseline's flat 10bps/side is absurd for microcaps. Per-side cost in bps, per
name, on realised turnover each rebalance:

    cost_bps_per_side = half_spread_bps(tier) + IMPACT_K * sqrt(participation)
    participation     = position_notional / (60-day median daily $volume at T)

- **half_spread_bps by tier (a priori):** liquid [$300M–15B] = **10**;
  microcap [$50–300M] = **50**; nano [$10–50M] = **150**.
- **IMPACT_K = 100 bps** (square-root impact: trading 1% of ADV ≈ 10bps of impact,
  10% of ADV ≈ 32bps, 100% ≈ 100bps).
- **Commissions:** 1 bp/side (negligible vs the spread; kept for completeness).
- **AUM-dependent:** `position_notional` depends on the book's AUM, so impact grows
  with size. Evaluate at **AUM = $0.5M, $2M, $5M** to trace the capacity curve.
- **Cost sensitivity:** report the whole model scaled **0.5× / 1× / 2×**. The
  decision rule (below) requires survival at 2×.

This model is deliberately conservative. If a net edge survives it, that is
meaningful; if it evaporates, that is the honest and expected microcap outcome.

## Low-turnover long-only construction (mandatory for microcaps)

Monthly full-turnover in microcaps pays the spread every month and dies. Fixed a
priori:

- **Long-only** (borrow is unavailable/prohibitive in microcaps; shorting is out —
  the same constraint that governs the rest of the program).
- **Quarterly rebalance** (every 3 months), not monthly — cuts turnover ~3×. The
  monthly rank-IC is still *measured* (signal quality, comparable to the baseline),
  but the *portfolio* trades quarterly.
- **Hysteresis / buffer:** a name is **bought when it enters the top decile (D10)**
  and **held until it falls below the top 3 deciles (below D8)**. This band-hold
  rule sharply reduces churn versus rebalancing the whole D10 each period.
- **Equal weight within the book, capped per name** at the smaller of (a) an
  equal-weight target and (b) a size cap = **10 × the name's 60-day median daily
  $volume** (so a full position could be exited over a few days) AND ≤ **3% of the
  book**. Diversify to **~50–100 names** to blunt idiosyncratic microcap blow-ups.
- Turnover, realised participation, and the number of names actually held are
  **reported**.

## Evaluation and pre-registered conditions

The microcap universe has **never been evaluated**, so:

- **Build / leak-audit: 1998–2020.** Run first, audited clean.
- **Hold-out: 2021-01-01 → present, touched ONCE**, only after the build is clean.
  This is a genuine unseen slice for the microcap universe (the baseline's single
  2021+ touch was on the *liquid* cross-section, a different universe).

Metrics (all net of the realistic cost model, out-of-sample), reported for the
primary band and every a-priori tier/sensitivity:

1. **Mean monthly rank-IC** and NW t-stat, vs the liquid baseline's +0.0254 — *is the
   signal larger in the tail?*
2. **Decile monotonicity** (Spearman of decile vs mean return and vs Sharpe).
3. **NET tradeable Sharpe / CAGR / maxDD / turnover** of the low-turnover long-only
   book, at each **AUM ($0.5M/$2M/$5M)** and each **cost scale (0.5×/1×/2×)** — *is it
   capturable?* This is the number the decision rule uses.
4. **Coverage & denominators (Rule 18):** eligible names/month per band, delisting
   rate, name-months dropped for no ART fundamental, names actually held.
5. **Leak audit** reused from the frozen harness (cheat control + permutation null).

## Pre-registered decision rule (a priori)

The microcap universe **replaces** the liquid small/mid band as Engine B's primary
universe for full P5 / paper trading **iff**, on BOTH the 1998–2020 build and the
once-touched 2021+ hold-out:

- its **net-of-realistic-cost tradeable Sharpe** (at $0.5M–$2M AUM, 1× cost) exceeds
  the liquid baseline's tradeable Sharpe by a **material margin ≥ +0.20 annualised
  Sharpe**, **AND**
- that advantage **survives 2× cost** (still above the liquid baseline), **AND**
- IC > 0 and (near-)monotone decile Sharpe hold (the always-on Engine B conditions).

Otherwise, **Engine B stays on the liquid small/mid universe** and this experiment is
recorded as an informative negative. A higher *gross IC* alone does **not** qualify —
the bar is net tradeable Sharpe, because the whole risk is that costs eat the edge.
If it qualifies, append a dated decision to `PROJECT_CHARTER.md` §9 revising the
microcap exclusion, and carry the winning universe + construction into full P5
(paper trading, the paper→real-money gate).

## Anticipated outcome, recorded before the run

Recorded so a result that merely matches expectation cannot be sold as a discovery,
and a too-good result triggers a leak hunt:

- **Gross rank-IC in microcaps expected HIGHER** than the liquid +0.0254 — plausibly
  0.04–0.09. **IC > ~0.12, or a perfect decile staircase ⇒ assume leakage /
  residual survivorship** (audit before trusting, even though the panel is
  survivorship-free).
- **Net tradeable Sharpe: genuinely uncertain — this is why we test.** Most likely
  honest outcome: the gross edge is bigger but the realistic cost model + capacity
  claw back much of it, leaving net Sharpe **comparable to or only modestly different
  from** the liquid baseline. A clear, cost-robust, hold-out-confirmed improvement
  would be a real finding and would redirect P5 to microcaps. A collapse net of
  costs is the **base-rate outcome and an acceptable, informative result** — it tells
  you the tail is not capturable at your frictions and to stay liquid.
- **Capacity:** net Sharpe expected to **degrade as AUM rises $0.5M→$5M**; the
  capacity curve quantifies the ceiling (a few million at most).

## Failure handling, fixed in advance

- A **too-good** gross IC is a **leak/survivorship to be found**, not an edge to bank.
- A **weak or negative net** result is **not** a licence to re-tune the bands, the
  cost model, the impact constant, the buffer, the rebalance frequency, or the AUM
  grid to rescue it. Any such change needs a fresh, separately dated pre-registration
  stating why the original choice was wrong on grounds independent of its result.
- The 2021+ hold-out is touched **once**. Examining it and then changing the spec
  burns it.
- The **frozen liquid baseline is not modified**; this is additive.
- No premature victory: a result requires the new cost/construction/screen code to be
  synthetic-tested and **frozen/committed before** any measuring run touches the panel
  (A-2 discipline), the leak audit to pass, and the metrics shown to the operator
  (Rule 14/27). Pulls/runs on Godzilla `.venv`; git from PowerShell on Godzilla.

## Live-trading risks NOT captured by this backtest (carry to P5/paper)

Even a passing net Sharpe understates microcap difficulty: halts, sudden delistings,
outright fraud, borrow impossibility, gappy fills, and worse data quality. These are
real and appear only in live/paper trading — the paper-trading stage (P5) is where
they get tested, and the paper→real-money gate must account for them.

## Implementation plan (after this spec is committed unrun)

1. Parameterised universe screen (config-driven size/liquidity/price bands) — **add**
   to `models/engine_b_universe.py` or a variant; do **not** edit the frozen baseline
   screen path.
2. Realistic cost module (tiered half-spread + √-impact, AUM-aware) — **new**, e.g.
   `validation/costs_microcap.py`; leave the frozen flat-cost harness path intact.
3. Low-turnover long-only construction (D10-in / <D8-out buffer, quarterly, capped) —
   **new**, e.g. `models/engine_b_portfolio.py` (shared with P5).
4. `scripts/run_engine_b_microcap.py` — screen → factors (frozen) → construction →
   realistic-cost evaluation → the tier/AUM/cost grid. Committed before it is run.
5. Synthetic-test the new screen, cost model, and buffer construction (weights within
   caps, turnover reduced by the buffer, cost rises with participation, delisting
   folded) BEFORE any real run. Then run 1998–2020, audit, then 2021+ once.

## Changelog

- 2026-08-11 — Created and pre-registered. Universe change (microcap band $50–300M +
  nano/full-tail tiers, $250k liquidity floor, $5 price floor, all with a-priori
  sensitivities), realistic tiered-spread + √-impact AUM-aware cost model, low-turnover
  long-only buffered construction, evaluation geometry (build 1998–2020 + one 2021+
  hold-out touch), the net-tradeable-Sharpe ≥ +0.20 decision rule, anticipated outcome
  and failure handling — all fixed before any microcap IC or net return was computed.
  Frozen liquid baseline untouched; factors unchanged. No result exists under this
  spec at commit time.
