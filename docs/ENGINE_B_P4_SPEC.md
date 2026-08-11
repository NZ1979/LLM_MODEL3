# ENGINE_B_P4_SPEC.md - Engine B P4: LLM-as-feature marginal-IC evaluation

**Pre-registered 2026-08-11 (America/Denver), Godzilla. NO RESULT COMPUTED UNDER
THIS SPEC EXISTS AT THE TIME OF THIS COMMIT.** This file fixes the out-of-sample
geometry, the purged+embargoed walk-forward cross-validation, the comparison
ladder, the predictor model class and search, the metrics, the kill-rule
adjudication, and the LLM training-hindsight leakage guard **before** any P4 model
is fitted or any marginal IC is computed. If a later session finds this file and a
result under it in the same commit, the pre-registration is void and the result
must be discarded and re-run.

This is **Spec 1 of two.** Spec 1 (this file) fixes everything that is
LLM-independent: it can be built and proven leak-free on 1998-2020 with no text
data. **Spec 2** (a separate, later dated pre-registration) fixes the concrete
EDGAR point-in-time data contract and the exact LLM feature list, written against
the real EDGAR schema once that source is scoped and integrity-validated (the
schema is knowable-at-time metadata, not an outcome; reading it is not "seeing
results"). The leakage-guard **posture** is locked here; the feature-specific
audits are instantiated in Spec 2.

## Context and stakes (why P4 is optional upside, not do-or-die)

Per the operator decision recorded in `KILL_RULE.md` (2026-08-11, reading A;
commit `776a60d`): the ">=20% relative LLM lift" is a gate on **including the LLM
feature layer**, not a precondition for shipping Engine B. The P3 mechanical
baseline already clears Engine B's kill-rule ship condition on its own - IC > 0
and near-monotone decile Sharpe, net of cost, on both the 1998-2020 build and the
once-touched 2021+ hold-out (`docs/ENGINE_B_BASELINE_RESULTS.md`, harness
`8a8eac8`, benchmark commit `bb3b8e9`). **P4 therefore tests optional upside:**
does an LLM feature layer add real, non-leaking marginal information coefficient
over a mechanical benchmark? If it does not, the LLM layer is dropped and Engine B
stands on the mechanical baseline (charter §1 - the LLM is never the predictor,
only a feature extractor whose marginal value is measured, never assumed).

## The frozen benchmark P4 must beat

The mechanical five-factor composite, measured under `ENGINE_B_BASELINE_SPEC.md`
with frozen harness `8a8eac8`:

| span | mean rank-IC | NW t | Spearman(decile, Sharpe) |
|---|---|---|---|
| build 1998-2020 | +0.0254 | +2.93 | 0.92 |
| hold-out 2021+ (SPENT) | +0.0496 | +3.81 | 0.96 |

The **build-span mechanical IC (+0.0254)** is the number the P4 model must beat by
>=20% relative on the build-span walk-forward to earn a hold-out delta touch. The
hold-out mechanical IC (+0.0496) is the benchmark for the single final delta touch
on 2021+.

## Out-of-sample geometry (operator decision, 2026-08-11)

The 2021+ hold-out is **spent** - the mechanical baseline scored it once, so it
cannot serve as a fresh unseen test for a model tuned to beat a now-known number.
What was observed there is *only the mechanical composite's aggregate IC*; no LLM
signal, and no P4 tuning decision, has ever touched 2021+. Decision:

1. **Develop and freeze the entire P4 pipeline on 1998-2020 only** - feature
   extraction, model class, hyperparameters, feature set, and the exact delta
   computation - via the purged+embargoed walk-forward CV below. Every modelling
   choice is made without any reference to 2021+.
2. **One pre-registered delta touch on 2021+**, at the very end, after the whole
   pipeline is frozen and committed. This is defensible precisely because no P4
   decision is informed by 2021+. It is scored **once**. If the pipeline is
   changed after this touch, 2021+ is burned and a new out-of-sample period must
   be reserved (forward time).
3. A model advances from step 1 to step 2 **only if** it clears the build-span
   kill-rule bar (below). A model that misses on the build span is not carried to
   the hold-out; the LLM layer is dropped and Engine B ships on the mechanical
   baseline. This prevents spending the single hold-out delta touch on a model
   already known to miss.

## Purged + embargoed walk-forward CV (on 1998-2020)

The mechanical baseline had **no trained parameters**, so its purge/embargo was
never load-bearing. The P4 model **trains**, so the purge/embargo is now real and
is validated leak-free in its own right (see "Leak audit" below).

- **Outer walk-forward:** expanding window, annual step. Train on all eligible
  rebalance months from 1998-01 through the end of year Y; test on the 12 monthly
  rebalances of year Y+1. First test year 2004 (>= 6 years of training history
  before the first test fold); last test year 2020. This yields **17 outer test
  folds (2004..2020)**, each scored out-of-sample.
- **Purge:** from each fold's training set, drop every training rebalance month T
  whose forward label window [T, T+21 market days] overlaps the first rebalance of
  the test fold. Since labels are 21 market days (~1 month) and rebalances are
  monthly, this purges the final training month adjacent to the test fold.
- **Embargo:** an additional **21 market days** (one label horizon) is embargoed
  on each side of every test fold, so no label window can straddle the
  train/test boundary in either direction.
- **Nested hyperparameter selection:** within each outer fold's *training* window,
  choose hyperparameters by an **inner** expanding walk-forward (same purge +
  embargo), selecting the grid point with the highest inner-validation mean
  rank-IC. Hyperparameters are **never** chosen on an outer test fold and
  **never** on 2021+. The inner CV is the only place a fitting choice is made.
- **Cross-sectional standardisation is within-date only** (as in
  `engine_b_factors.py`); no statistic crosses dates. Feature construction that
  needs a fit (e.g. an LLM-feature normalisation) is fit on training rows only and
  applied to test rows - fit statistics never see the test fold.

## The comparison ladder (three models, one harness)

All three produce a per-(date, permaticker) **score** that is fed to the existing
frozen harness (`validation/engine_b_harness.py::evaluate`) as the `composite`
column; `decile` is the within-date qcut of that score. The harness computes
rank-IC (per-date Spearman + Newey-West t), decile monotonicity, and the long-only
top-decile net-of-cost curve exactly as in P3. Only score generation differs.

1. **M0 - mechanical composite (frozen benchmark).** The equal-weight 5-factor
   composite from `engine_b_factors.py`. No training. This is the number in the
   table above; it is re-used, not re-measured.
2. **M1 - ML, no LLM (diagnostic benchmark).** LightGBM trained under the
   walk-forward CV over the **five mechanical factor z-scores only**
   (`momentum, value, quality, lowvol, size`). Isolates the gain from *ML fitting
   of the mechanical factors* from the gain from the LLM.
3. **M2 - ML + LLM (the P4 model).** The identical LightGBM spec and CV as M1,
   trained over the five factor z-scores **plus** the LLM feature group (defined
   in Spec 2). The only difference from M1 is the feature set.

M1 and M2 use the **same model spec and the same folds**, so any IC difference
between them is attributable to the LLM feature group, not to a modelling change.

## Predictor model (operator decision: gradient-boosted trees)

- **Class:** LightGBM (gradient-boosted decision trees). Same spec for M1 and M2.
- **Target:** the **within-date cross-sectional percentile rank of `fwd_ret_21`**
  (bounded [0,1]), so the model optimises for cross-sectional ordering (what
  rank-IC measures) and is robust across return regimes. Names with a missing
  forward label (`fwd_status` != usable) are excluded from training and from
  scoring for that month and counted (Rule 18) - never filled.
- **Objective:** regression (L2) on the ranked target; per-date groups.
- **Pre-registered hyperparameter grid** (searched by inner nested CV, selected on
  inner-validation mean rank-IC):
  - `num_leaves` in {15, 31, 63}
  - `min_child_samples` in {100, 500, 2000}
  - `feature_fraction` in {0.7, 1.0}
  - `lambda_l2` in {0.0, 1.0, 10.0}
  - `learning_rate` = 0.03 (fixed); `n_estimators` up to 2000 with early stopping
    (50-round patience) on the inner-validation fold.
  - All other LightGBM defaults. Random seed fixed = 20260811 (reproducible).
- **No fitting choice is made after seeing any outer test fold or the hold-out.**
  The grid above is frozen by this commit.

## Metrics and the kill-rule adjudication

For each of M0 (reference), M1, M2, on the build-span walk-forward and (only for a
model that clears the build-span bar) the once-touched 2021+ hold-out:

- **Mean rank-IC**, its Newey-West t-stat, and the monthly IC time series
  (harness `ic_summary` / `rank_ic_series`).
- **Decile monotonicity** (Spearman of decile vs mean return and vs Sharpe).
- **Long-only top-decile net-of-cost** Sharpe/CAGR/maxDD/turnover at 5/10/20 bps
  sensitivity (reported; the kill rule adjudicates on IC + decile monotonicity).

**Delta test (how ">=20% relative and statistically distinguishable" is computed),
pre-registered:** form the **paired per-date IC difference** series
`d_t = IC_M2(t) - IC_M0(t)` over the evaluation span. Report:

- the mean of `d_t` and its **Newey-West t-stat** (H0: mean delta = 0),
- a **stationary block bootstrap** (fixed 10,000 resamples, mean block length 6
  months, seed 20260811) 95% CI on both the mean delta and the **relative** uplift
  `mean(IC_M2)/mean(IC_M0) - 1`,
- the point estimate of the relative uplift.

**Kill-rule PASS for including the LLM layer requires ALL of (operator decision -
literal locked bar PLUS a mandatory no-LLM honesty gate):**

- **(a) Locked bar:** `mean(IC_M2)` exceeds `mean(IC_M0)` by **>=20% relative**
  (i.e. relative uplift point estimate >= 0.20) **AND** the paired delta
  `IC_M2 - IC_M0` is statistically distinguishable from zero (NW t significant at
  5% and the bootstrap 95% CI on the mean delta excludes zero). This is the
  `KILL_RULE.md` Engine B bar as written, comparing baseline+LLM to the mechanical
  baseline. AND
- **(b) No-LLM honesty gate:** `IC_M2` also exceeds `IC_M1` by a **positive,
  statistically distinguishable** paired margin. If M1 alone (ML over the five
  factors, no LLM) already achieves the >=20% uplift over M0, then the measured
  gain is **ML fitting, not the LLM**, and the LLM layer is **dropped** even if (a)
  passes. This gate adds a leak-honesty requirement; it does not weaken the locked
  bar. AND
- **(c)** IC_M2 > 0 and its decile Sharpe is (near-)monotone (the always-on Engine
  B conditions), net of cost, out-of-sample.

If (a)-(c) hold on the build span, the model earns the **single** 2021+ delta
touch; the same PASS conditions must **also** hold there for the LLM layer to
ship. If any condition fails, the LLM layer is dropped and Engine B ships on the
mechanical baseline (reading A). No condition here alters a `KILL_RULE.md`
threshold; the >=20% and significance requirements are the locked rule, and (b) is
an added guard against crediting the LLM for an ML-fitting gain.

## Leak audit for the training harness (P4-specific, load-bearing now)

The P3 leak audit (cheat control + 25-seed permutation null) proved the *scoring*
harness. Because M1/M2 **train**, three additional controls are pre-registered and
must pass **before** any M1/M2 result is trusted:

1. **Purge/embargo effectiveness (synthetic).** Extend
   `tests/test_engine_b_synthetic.py` with a planted label-bleed: a feature that
   equals the test-fold forward return only within the embargo window. A correct
   purge+embargo must prevent the model from using it; the audit confirms the
   train/test split leaves zero rows whose label window straddles the boundary.
2. **Permuted-label training null.** Train M1/M2 with the **training** target
   permuted within date (labels shuffled across names each date), over 25 seeds
   (seed base 20260811). Out-of-sample IC must collapse to ~0 (a null centred at
   zero); a non-zero IC means the harness leaks the label into training. Report
   the null mean/SD and the real model's SD above it, as in P3.
3. **Cheat control (reused).** Score = realised forward return still drives IC to
   ~+1; confirms the evaluation path is sensitive to look-ahead.

A P4 result is `UNVERIFIED:` until 1-3 pass. A model IC in the "too-good" zone
(mean IC > ~0.10, or a perfect decile staircase) is **assumed leaking** and
audited before anything is banked (charter §5.3, Rule 14).

## LLM training-hindsight leakage guard - posture (operator decision)

Locked posture (concrete audits instantiated in Spec 2 against the real EDGAR
features). The trap: an LLM reading a 2008 filing already "knows" the outcome from
its own training corpus, so a supposedly point-in-time text feature can smuggle the
future in - exactly what made the sibling `LLM_SWING_MODEL` un-backtestable
(charter §1). Guard:

- **Document-descriptive features only.** Features describe the filing's own
  content (tone, uncertainty/litigation language, readability/complexity, topic
  presence, change-vs-prior-filing), never a prediction of the outcome. The
  extraction prompt **forbids** predicting returns or invoking any knowledge about
  the company's future; it scores only what the document says.
- **Masked hindsight-probe audit.** For a sampled set of filings, extract each
  feature twice - once with issuer identity and dates present, once with them
  masked. A feature whose masked-vs-unmasked value shifts **in a way that
  correlates with the forward return** is carrying hindsight and is **rejected**.
  This is the load-bearing audit that a feature is genuinely point-in-time.
- **Marginal-IC ceiling.** Any LLM-feature marginal IC that lands in the too-good
  zone is assumed to be hindsight leakage until the masked-probe audit clears it.
- **Cutoff note.** Restricting to an LLM whose training cutoff predates the test
  window is **not** a usable primary guard here: any modern LLM has hindsight over
  the entire 1998-2020 build span, so cutoff-restriction would leave almost no
  clean history. This is precisely why the charter makes the LLM a feature
  extractor measured for marginal IC, never the predictor. Model identity and
  cutoff are recorded for the audit trail.

## Anticipated outcome, recorded before the run

Recorded so a result that merely matches expectation cannot later be presented as
a discovery, and so a too-good result triggers a leak audit rather than a
celebration:

- **M1 (ML, no LLM)** is expected to add a **small** IC gain over M0 from fitting
  factor interactions and non-linearities - plausibly on the order of the
  mechanical IC itself, but easily within noise. It is **not** guaranteed to clear
  +20% over M0; liquid small/mid factor ML gains are thin net of costs.
- **M2 (ML + LLM)** clearing the locked >=20% bar over M0 **and** beating M1
  significantly would be a genuine, surprising, publishable marginal edge - and is
  therefore held to the full leakage audit before it is believed. A large M2 gain
  that does **not** survive the masked-probe audit is hindsight leakage, not edge.
- **Most likely honest outcome:** M2's marginal IC over M0 is positive but small
  and/or statistically indistinguishable, or is matched by M1 (ML-fitting, not
  LLM). In that case the LLM layer is **dropped** and Engine B ships on the
  mechanical baseline. That is an acceptable, pre-committed result, not a failure.

## Failure handling, fixed in advance

- A **too-good** M1/M2 result is treated as a **leak to be found** (in the CV
  purge/embargo, the feature construction, or LLM hindsight), not an edge to be
  banked. Fix the harness/feature, re-run on the build span.
- A **weak or indistinguishable** marginal IC is **not** a licence to re-tune the
  model class, the grid, the feature set, the CV geometry, or the delta test to
  rescue it. Any such change requires a fresh, separately dated pre-registration
  stating why the original choice was wrong on grounds independent of its result.
- The 2021+ hold-out is touched **once**, only for a model that already cleared the
  build-span bar. If it is examined and then the pipeline is changed, the hold-out
  is burned and a new out-of-sample period (forward time) must be reserved.
- No premature victory: `py_compile`/unit tests passing is not a result; a P4
  result requires the training-harness leak audit to have passed and the metrics
  to have been produced by the frozen pipeline on real data, shown to the operator
  (Rule 14, Rule 27).

## Deferred to Spec 2 (pre-registered later, against the real EDGAR schema)

- The EDGAR point-in-time data contract: filing types used, the acceptance-datetime
  (knowable-at-time) stamp, the permaticker<->CIK identity join and its ambiguity
  tripwire (the survivorship-safe analogue of the panel's attribution check), and
  the coverage funnel over the 1998-2020 build universe.
- The exact LLM feature list, the extraction model + prompt, the normalisation, and
  the concrete masked-hindsight-probe and marginal-IC-ceiling thresholds.
- Spec 2 is committed with no result under it, after EDGAR is scoped and
  integrity-validated, before any feature is extracted.

## Changelog

- 2026-08-11 - Created and pre-registered (Spec 1 of 2). OOS geometry (freeze on
  1998-2020, one 2021+ delta touch), purged+embargoed walk-forward CV (17 outer
  folds 2004-2020, nested inner hyperparameter selection), the M0/M1/M2 comparison
  ladder, the LightGBM model class + frozen grid, the metrics and the delta test
  (paired per-date IC difference, NW t + block bootstrap), the kill-rule
  adjudication (locked >=20% bar + mandatory no-LLM honesty gate + always-on IC>0 /
  monotone-decile conditions), the training-harness leak audit (purge/embargo
  synthetic + permuted-label training null + cheat control), and the LLM
  training-hindsight leakage guard posture (document-descriptive features + masked
  hindsight-probe audit). Concrete EDGAR data contract and LLM feature list
  deferred to Spec 2. No result exists under this spec at commit time.
