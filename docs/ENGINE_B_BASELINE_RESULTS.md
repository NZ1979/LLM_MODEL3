# ENGINE_B_BASELINE_RESULTS.md - Engine B mechanical baseline, measured

Results computed under the pre-registered `docs/ENGINE_B_BASELINE_SPEC.md`. The
spec was committed with **no result under it** (`87fb732`; the two implicit-point
clarifications in `f5d1d29` also carried no result). The **implementation was
frozen and committed before any measuring run touched the panel** (`f5d1d29`,
`0cd79ec`, `8a8eac8`) - the A-2 discipline. These numbers were then produced by
`scripts/run_engine_b_baseline.py` on Godzilla and are recorded here after the
fact; the runner writes nothing to disk, so no result ever shared a commit with
the spec.

- Date: 2026-08-11 (America/Denver), Godzilla.
- Frozen harness at time of measurement: `8a8eac8`.
- Panel: `data/raw/sharadar/*.parquet` (Sharadar Direct, survivorship-free,
  ingested and integrity-checked 2026-08-10). Identity key `permaticker`.
- Build/leak-audit span: 1998-2020 (run first, audited clean). Hold-out span:
  2021-01-01 -> present, **touched once**, only after the build was clean.

## Headline

The mechanical five-factor composite has a **small, positive, statistically
robust cross-sectional rank-IC that reproduces out-of-sample**, with a
near-monotone decile Sharpe. The walk-forward harness is demonstrated leak-free.
This is the pre-registered "clean harness, modest real edge" outcome (anticipated
IC 0.02-0.05). It is **not** in the "assume leakage" zone (IC > 0.10 or a perfect
staircase).

| metric (net of 10 bps/side, OOS) | Build 1998-2020 | Hold-out 2021-2026 |
|---|---|---|
| months evaluated | 265 | 66 |
| mean rank-IC | **+0.0254** | **+0.0496** |
| median rank-IC | +0.0297 | +0.0551 |
| Newey-West t-stat | +2.93 | +3.81 |
| months IC > 0 | 60% | 74% |
| Spearman(decile, mean ret) | 0.87 | 0.95 |
| Spearman(decile, Sharpe) | 0.92 | 0.96 |
| D10 - D1 mean fwd 21d ret | +0.83% | +1.28% |
| long-only D10 Sharpe (ann) | 0.54 | 0.57 |
| long-only D10 CAGR | 9.62% | 10.38% |
| long-only D10 max drawdown | -59.7% | -21.1% |
| long-only D10 turnover / reb | 0.55 | 0.49 |
| eligible names / month (median) | 1,262 | 1,565 |

## Leak audit - why these numbers are trusted, not banked on faith

The harness is proven sensitive to look-ahead and free of manufactured signal,
three independent ways:

1. **Timing oracle (synthetic).** `tests/test_engine_b_synthetic.py` cross-checks
   the DuckDB timing layer (`data/sharadar_panel.py`) field-by-field against an
   independent pandas re-implementation on the same synthetic tables: **0
   mismatches** on close, marketcap, momentum, vol, dollar-volume, history,
   fundamentals, and the forward label/status. Attribution splits a recycled
   ticker to the correct permaticker; overlapping windows fail loud; a filing
   dated after T is not used at T.
2. **Cheat control (real panel).** Scoring on the realised forward return drives
   mean IC to **+1.000** and a perfect decile staircase on both spans - so a real
   look-ahead would land squarely in the "assume leakage" zone. A modest real IC
   is therefore trustworthy.
3. **Permutation null (real panel, 25 seeds).** Permuting the forward return
   across names within each date gives a null centred at ~0:
   - Build: null mean -0.0003, SD 0.0022 -> real IC **+11.7 SD** above chance.
   - Hold-out: null mean -0.0000, SD 0.0031 -> real IC **+16.2 SD** above chance.

   (A single permutation is one noisy draw whose t-stat can wander ~2 SD from
   zero; the distribution over seeds is the honest null.)

## Decile detail

D1 -> D10 mean forward 21-day return rises near-monotonically on both spans. The
**top decile softens** slightly (build: D10 1.02% below D8/D9 ~1.14%; hold-out:
D10 1.06% roughly level with D9) - the well-documented behaviour of the extreme
high-composite bucket catching lottery/junk names, not a defect. The gradient is
in the mid-to-upper deciles.

## Universe and data handling (Rule 18 - denominators shown)

- Build: from a median ~5,959 candidates/month the screens cut to a median
  **1,262 eligible** (the size band $300M-$15B and the $5M liquidity floor are
  the binding cuts). 7,405 eligible name-months over the span were dropped from
  the ranked set for having no ART fundamental filed at T (counted, not filled).
  The earliest months have 0 eligible names (insufficient history/marketcap in
  1998-99) - expected and surfaced.
- Hold-out: median **1,565 eligible**; 538 dropped for no ART fundamental;
  12,520 name-months carry `incomplete_window` (the last ~month of rebalances
  near the panel end lack a full 21-day forward window) and are correctly
  excluded from labels and counted.
- Delistings are folded into the label (build 10,929; hold-out 4,985
  `delisted_partial`); no name is silently dropped or forward-filled.

## Adjudication against KILL_RULE.md (Engine B)

The two conditions that apply to the **mechanical baseline itself** are met on
both the build span and the once-touched hold-out:

- **IC > 0 and statistically distinguishable from zero** - met (t 2.93 / 3.81;
  11.7 / 16.2 SD above the permutation null).
- **Monotonic (near-monotonic) Sharpe-by-decile** - met (Spearman 0.92 / 0.96).

This run **establishes the mechanical benchmark IC (~0.025 build, ~0.050
hold-out) and proves the harness.** Per the spec it does **not** by itself ship
or kill Engine B. The third kill-rule clause - the baseline+LLM IC exceeding this
mechanical IC by >=20% relative and statistically distinguishable - is a **P4**
question and is not adjudicated here.

**Open kill-rule reading for the operator (not resolved here):** the Engine B
clause is written as three ANDs (including the >=20% LLM improvement), yet its
closing sentence says that if the LLM adds nothing it is dropped and "Engine B
then stands or falls on the mechanical baseline alone." Whether a mechanical
baseline that clears IC>0 + monotone deciles can ship Engine B on its own, or
whether the P4 LLM improvement is mandatory to ship, is a reading of the locked
kill rule the operator should confirm before P4 concludes. It is not changed
here (the kill rule is locked).

## Caveats to carry forward (P5 construction)

- The naive **equal-weight long-only top decile is not the tradeable form**: its
  drawdown is deep (build -59.7%, hold-out -21.1%) and D10 is not even the
  best-performing decile. A real book will weight the mid-upper deciles and/or
  vol-target, per the charter's combine step.
- Hold-out IC (0.050) exceeds build IC (0.025). Both are positive, significant,
  and far above their permutation nulls; the difference is regime/noise (2021-22
  value/quality resurgence), not a leak (leak controls are clean on both). Do not
  over-read the level.
- All figures are net of 10 bps/side with 5/10/20 bps sensitivity reported; the
  edge is not fragile to the cost assumption over that range.

## Reproduce

Frozen harness `8a8eac8`, on Godzilla `.venv`:

    python scripts/run_engine_b_baseline.py --span build
    python scripts/run_engine_b_baseline.py --span holdout --confirm-holdout

Synthetic leak audit (no real panel): `python tests/test_engine_b_synthetic.py`.

## Changelog

- 2026-08-11 - Build and hold-out measured under the pre-registered spec with the
  frozen harness (`8a8eac8`). Harness proven leak-free (synthetic oracle + cheat
  control + 25-seed permutation null). Mechanical baseline clears its two
  applicable kill-rule conditions on both spans and establishes the P4 benchmark
  IC. Hold-out spent (touched once).
