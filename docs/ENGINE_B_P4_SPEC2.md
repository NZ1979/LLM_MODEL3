# ENGINE_B_P4_SPEC2.md - Engine B P4 Spec 2: EDGAR ingestion + the LLM feature layer

**Pre-registered 2026-08-11 (America/Denver), Godzilla. NO RESULT COMPUTED UNDER
THIS SPEC EXISTS AT THE TIME OF THIS COMMIT.** This file fixes the EDGAR
point-in-time data contract, the leak-critical CIK->permaticker window
attribution, the (date, permaticker) feature join, the concrete LLM feature list
and extraction (model, prompt, normalisation), and the hindsight-leakage audit
with a-priori sample sizes and thresholds - **before** any filing is fetched, any
section is extracted, any LLM feature is computed, and any marginal IC is
measured. If a later session finds this file and a result under it in the same
commit, the pre-registration is void and the result must be discarded and re-run.

This is **Spec 2 of two.** Spec 1 (`docs/ENGINE_B_P4_SPEC.md`, commit `203fb63`)
fixed everything LLM-independent: the out-of-sample geometry (freeze the whole
pipeline on 1998-2020, one delta touch on 2021+), the purged+embargoed
walk-forward CV (17 outer folds 2004-2020, nested inner hyperparameter
selection), the **M0/M1/M2 comparison ladder**, the LightGBM model class and
frozen grid (seed 20260811), the delta test (paired per-date IC diff, NW t +
block bootstrap, >=20% relative on the mean-IC ratio), the kill-rule adjudication
(locked >=20% bar + mandatory no-LLM honesty gate + always-on IC>0/monotone
deciles), the training-harness leak audit, and the LLM leakage-guard **posture**.
Spec 2 instantiates the deferred pieces against the real, verified EDGAR schema.
Nothing in Spec 2 alters a `KILL_RULE.md` threshold or any Spec 1 decision; where
the two touch, Spec 1 governs.

## Context and stakes (unchanged from Spec 1)

Per `KILL_RULE.md` (2026-08-11, reading A; commit `776a60d`) and Spec 1: the
mechanical baseline already clears Engine B's kill-rule ship condition on its own
(`docs/ENGINE_B_BASELINE_RESULTS.md`, harness `8a8eac8`). **P4 is optional
upside.** The LLM is a feature extractor whose marginal IC is measured against the
M0 mechanical benchmark, **never the predictor** (charter 1). The frozen benchmark
the LLM layer must beat by >=20% relative on the build span is **M0 build-span
mean rank-IC +0.0254**. If the LLM layer fails any pre-registered condition, it is
dropped and Engine B ships on the mechanical baseline - an acceptable,
pre-committed outcome, not a failure.

## Verified inputs this spec builds on (read, not assumed)

- **CIK bridge** (`data/raw/sharadar/permaticker_cik.parquet`, commit `39162cb`,
  gitignored). Columns: `permaticker, ticker, name, cik, secfilings, isdelisted,
  firstpricedate, lastpricedate`. `cik` is the canonical integer as a string, no
  leading zeros. Coverage 99.53% overall / **99.40% among delisted**; **0
  permatickers map to >1 CIK**; one CIK **can** back multiple permatickers (share
  classes and successor entities - the load-bearing case below). 104 no-CIK names
  (mostly preferreds), counted not filled.
- **EDGAR submissions API** (probe `scripts/probe_edgar_submissions.py`, commit
  `0d49af9`, VERIFIED on Godzilla). Endpoint
  `https://data.sec.gov/submissions/CIK{cik:010d}.json`; needs a fair-access
  User-Agent built from `.env` key `SEC_EDGAR_CONTACT` (gitignored); ~10 req/sec
  ceiling. `filings.recent` holds the most-recent ~1000 filings as parallel arrays
  (`form, accessionNumber, filingDate, acceptanceDateTime, reportDate,
  primaryDocument, primaryDocDescription`); older history lives in the
  supplementary `filings.files[]` JSONs (`{name, filingCount, filingFrom,
  filingTo}`), fetched at `https://data.sec.gov/submissions/{name}`.
  **`acceptanceDateTime` is the point-in-time knowable-at-time stamp** (distinct
  from `filingDate`/`reportDate`); pre-~2002 filings carry day precision
  (`00:00:00Z`) which is sufficient at monthly-rebalance granularity. Pre-2001
  coverage back to 1994-1996 confirmed for delisted names via the supplementary
  files. Do **not** trust `entityName` for identity (it shows the filer's *current*
  name).
- **The frozen panel + harness.** `data/sharadar_panel.py` (timing layer, keyed
  `(date, permaticker)`, rebalance = last market day of each month, forward label
  `fwd_ret_21` with delisting folded in and `fwd_status`), the universe screen
  `models/engine_b_universe.py`, the five equal-weight z-score factors
  `models/engine_b_factors.py` (columns `momentum, value, quality, lowvol, size`,
  plus `composite`, `decile`, `ranked`), and the scoring harness
  `validation/engine_b_harness.py::evaluate` (consumes a panel carrying `date,
  permaticker, composite, decile, fwd_ret_21`). These are FROZEN; Spec 2 adds
  columns, it does not modify them.

Anything below described as an EDGAR **fetch path** or **section-extraction**
mechanism is *designed here* and is VERIFIED only up to the submissions API. The
document fetch and the section parser are gated behind the synthetic tests and a
small real-filing smoke test (below) before any full extraction run - honesty per
Rule 28/14.

---

## 1. Ingestion contract

### 1.1 Form set

Qualifying **feature-bearing** forms, matched by prefix on the `form` string:

- Annual: `10-K`, and the historical variants `10-K405` (pre-2003, the checked-box
  §16 variant), `10-KSB` and `10-KSB405` (small-business, pre-2009), `10-KT`
  (transition-period annual).
- Quarterly: `10-Q`, and `10-QT` (transition-period quarterly).

**Amendment (`/A`) decision: excluded from the feature stream, counted.** `10-K/A`,
`10-Q/A`, `10-KSB/A`, etc. are **not** used to produce features. Rationale, fixed
in advance: (a) MD&A and Risk Factors are core sections of the *original* periodic
report; amendments overwhelmingly restate exhibits, Part III proxy content, or
financial statements, not the two narrative sections; (b) admitting `/A` requires
messy section-presence and second-acceptance-stamp logic for little narrative
signal; (c) excluding data is conservative - it can only cost signal, never leak.
Every qualifying name whose latest filing at T is an unused `/A` is **counted** in
the coverage funnel (Rule 18) so the exclusion is visible. If a later analysis
shows `/A` narrative changes matter, that is a fresh, separately dated
pre-registration.

### 1.2 Fetch path (runs on Godzilla `.venv`; sandbox is firewalled - charter 8)

1. **Submissions traversal.** For each CIK in the build/hold-out universe, fetch
   `CIK{cik:010d}.json`, then fetch **every** `filings.files[].name`. Union
   `filings.recent` with all supplementary rows into one filing table. Keep only
   rows whose `form` is in the qualifying set (1.1). This is mandatory: `recent`
   caps at ~1000 and a long-lived or post-bankruptcy CIK (Lehman) can push all real
   10-Ks into the supplementary files.
2. **Primary-document fetch.** With `accession = accessionNumber` and
   `acc_nodash = accession.replace('-','')`:
   - Modern filings: `https://www.sec.gov/Archives/edgar/data/{cik_int}/{acc_nodash}/{primaryDocument}`
     (`cik_int` = the plain integer CIK, no leading zeros).
   - Old filings where `primaryDocument` is blank (common pre-~2001): fall back to
     the complete submission text file
     `https://www.sec.gov/Archives/edgar/data/{cik_int}/{acc_nodash}.txt`.
3. **Rate + politeness.** Single-threaded, <= 8 req/sec (under SEC's 10), UA
   `LLM_Model3/1.0 (research; {SEC_EDGAR_CONTACT})`, exponential backoff on
   429/503, hard-fail-loud after N retries with the offending URL (never the key).
4. **Local corpus cache (gitignored).** Every fetched raw document is written once
   to `data/raw/edgar/{cik}/{acc_nodash}.{ext}` and never re-fetched. The cache is
   the frozen text corpus - it makes extraction reproducible and bounds EDGAR load.

### 1.3 Section extraction (deterministic parse - the LLM does NOT choose text)

Extraction of section spans is **mechanical**, not LLM-driven, so the
point-in-time boundary of what text belongs to a filing is set by a parser, never
by a model that could hallucinate or peek. Two target sections: **MD&A** and
**Risk Factors**.

- **Modern HTML / inline-XBRL** (>=~2001): strip XBRL/`ix:` tags and scripts,
  render to text with block separators, then locate sections by Item headers on the
  normalised text.
- **Old plain-`.txt` SGML** (pre-~2001): parse the SGML `<DOCUMENT>` blocks, take
  the `<TEXT>` body of the primary 10-K/10-Q document, strip tabular filler, then
  locate sections by Item headers.
- **Section boundaries (regex on normalised text):**
  - 10-K MD&A: `Item 7.` "Management's Discussion and Analysis" -> next of
    `Item 7A` / `Item 8`.
  - 10-K Risk Factors: `Item 1A.` "Risk Factors" -> next of `Item 1B` / `Item 2`.
  - 10-Q MD&A: Part I `Item 2.` "Management's Discussion" -> `Item 3` / `Item 4`.
  - 10-Q Risk Factors: Part II `Item 1A.` -> next `Item`.
- **Coverage honesty (fixed in advance).** Risk Factors (Item 1A) became mandatory
  only for 10-K fiscal years ending after **2005-12-01** (SEC Release 33-8591);
  pre-2006 10-Ks and many 10-Qs legitimately have **no** Risk Factors section.
  MD&A goes back to the 1990s. A document with no locatable section yields **NaN**
  for that section's features and is **counted** in a `section_not_found` bucket by
  form and year (Rule 18) - never zero-filled. This means Risk-Factors-derived
  features are sparse before 2006 by construction, and the coverage funnel must
  show it.

### 1.4 Storage format

Three gitignored artefacts under `data/raw/edgar/`, all keyed so nothing depends
on the recycled ticker string:

- `filings_index.parquet` - one row per fetched qualifying filing:
  `permaticker, cik, accession, form, is_amendment, filing_date, acceptance_datetime
  (UTC), acceptance_date_et, report_date, primary_document, fetch_status`.
- `sections.parquet` - one row per (accession, section):
  `permaticker, cik, accession, form, acceptance_datetime, section
  {mdna|risk_factors}, char_len, extraction_status, text` (zstd-compressed;
  section text stored inline - MD&A/RF are tens of KB).
- `features_llm.parquet` - one row per accession: `permaticker, cik, accession,
  acceptance_datetime, acceptance_date_et, report_date, form` plus the **raw**
  (un-normalised) LLM feature columns of section 4. Normalisation is applied at
  join time in the CV (within-date, fit needs no cross-date statistic), so the
  stored feature is raw and re-usable.

---

## 2. The leak-critical attribution rule (load-bearing)

This is the CIK-level analogue of the panel's ticker-recycling defence and the
single most important part of Spec 2. A CIK can persist through bankruptcy/merger
and be re-named, so pulling *all* of a CIK's filings and attaching them to one
name grafts a successor's future onto a dead company. Worked case:
**WaMu CIK 933136 -> Mr. Cooper (COOP)**; that CIK's filings run continuously from
WaMu (1990s) to Mr. Cooper (2020s). The bridge maps WaMu's permaticker **and**
COOP's permaticker to the same CIK 933136; the filings must be split between them
by time, never merged.

**Attribution rule (fixed):**

1. A filing under `cik` is attributed to permaticker `P` **iff** `P.cik == cik`
   **and** `firstpricedate(P) <= acceptance_date_et(filing) <= lastpricedate(P)`.
   The window comes from the bridge, not from EDGAR `entityName` (which shows the
   current name). A CIK backing several permatickers (share classes / successors)
   is expected and **safe only under this window split**.
2. A filing is **usable at rebalance T iff `acceptance_date_et(filing) < T`**
   (strictly before the rebalance date). Rationale: `acceptanceDateTime` can be
   intraday and a filing accepted after the 16:00 ET close on T is not knowable at
   T's close; requiring strictly-before-T removes all same-day ambiguity at the
   cost of at most one rebalance of recency (month-end filings are rare). This is
   marginally more conservative than the panel's `datekey <= T` on fundamentals -
   deliberately, in the leak-safe direction. Comparison is on the **ET date
   component**, so intraday timezone never matters at monthly granularity.

**Fail-loud attribution-ambiguity check (analogue of `sharadar_panel.py`'s
`attribution ambiguity` tripwire).** After attribution, assert that **no single
`accession` maps to more than one permaticker**. Two permatickers sharing a CIK
with **overlapping** `[firstpricedate, lastpricedate]` windows would let a filing
in the overlap attribute to both -> `sys.exit` non-zero with the offending
`(cik, accession, [permatickers])`, refusing to graft identities (Rule 18/19).
Also count and **drop** filings whose CIK matches a permaticker but whose
`acceptance_date_et` falls in **no** window of any permaticker on that CIK (e.g.
the gap between a dead name and its later successor) - these are `unattributed`,
reported, never forced onto the nearest name. This is the mechanism that keeps
post-2008 WaMu-CIK filings off WaMu's permaticker.

**Coverage funnel over the 1998-2020 build universe (Rule 18, denominators
shown).** Over the same eligible universe the baseline screens produce, report the
monthly funnel and its drop reasons:

```
eligible name-months
  -> with a resolvable CIK              (drop: no CIK - counted)
  -> with >=1 qualifying filing,
     acceptance_date_et < T, in-window  (drop: no prior filing - counted)
  -> not stale (section 3 cap)          (drop: stale filing - counted)
  -> MD&A extracted                     (drop: section_not_found - counted)
  -> Risk Factors extracted             (drop: section_not_found - counted, sparse pre-2006)
  -> complete LLM feature vector
```

Names that fall out at any step get **NaN** LLM features and fall back to M1
behaviour (section 3); every drop is counted, never filled.

---

## 3. Feature join

LLM features become **per-(date, permaticker) columns** that slot beside the five
mechanical z-scores in the Spec 1 M2 feature matrix.

- **As-of selection.** At rebalance T for permaticker P, take the attributed
  qualifying filing with the **greatest `acceptance_datetime` subject to
  `acceptance_date_et < T`** and to the window rule (section 2). Its `features_llm`
  row is P's LLM feature vector at T. Because selection always takes the latest
  qualifying filing <= T, carry-forward between filings is automatic (no explicit
  fill).
- **Staleness cap (fixed a priori): 18 months.** If the selected filing's
  `acceptance_date_et` is more than **18 months** before T, the LLM features are
  set to **NaN** (stale) and counted. Rationale: a normally-reporting name files a
  10-Q every <=3 months; >18 months of silence means the name has stopped periodic
  reporting (typically pre-delisting distress) and its narrative is no longer a
  point-in-time description of the current business. 18 months tolerates a late
  annual filer plus one skipped quarter without collapsing coverage.
- **NaN fall-back, never fill.** A name with no qualifying filing at T (no CIK, no
  prior in-window filing, extraction failed, or stale) gets **NaN** LLM feature
  columns - it is **not** dropped and **not** zero-filled. In M2's LightGBM, NaN is
  a first-class input (the tree learns a default split direction), so a NaN-LLM
  name is effectively scored on its five mechanical factors alone - exactly the M1
  behaviour Spec 1 requires. The count of NaN-LLM name-months per month is reported.
- **Row set.** LLM features left-join on `(date, permaticker)` onto the **ranked**
  cross-section from `engine_b_factors.compute_scores` (names that have the
  five-factor composite). Names that are `ranked == False` (missing fundamentals)
  are already outside M1/M2's train/score set and are not resurrected by having a
  filing.
- **Normalisation.** Each raw LLM feature is **cross-sectionally winsorised at
  +/-3 SD then z-scored within that date's ranked universe**, identical to the
  mechanical factors (reuse `engine_b_factors._winsorize_z`). This is a within-date
  transform with **no cross-date statistic**, so there is nothing to fit on
  training rows and nothing to leak across the train/test boundary - consistent
  with Spec 1 ("cross-sectional standardisation is within-date only") and the
  frozen `engine_b_factors.py`. Any future feature that needs a *global* fit would
  be fit on training rows only; none here does.
- **M1 vs M2 remain identical except the feature set** (Spec 1): M1 = the five
  z-scores; M2 = the five z-scores **plus** the surviving LLM feature columns.
  Same LightGBM spec, same folds. Any M2-M1 IC difference is therefore
  attributable to the LLM feature group, which is why the group is kept **purely
  LLM-scored** (section 4) - so gate (b) of Spec 1 cleanly answers "is it the LLM?"

---

## 4. The concrete LLM feature list + extraction

### 4.1 The feature list (document-descriptive only; all LLM-scored)

Every feature describes the **filing's own text**, never a prediction of the
outcome. The group is deliberately **all LLM-scored** (no mechanical text metric is
bundled in) so that Spec 1's no-LLM honesty gate isolates the LLM's contribution.
The operator-chosen categories - tone, uncertainty/litigation, readability/
complexity, topic presence, change-vs-prior - map to these ten features:

MD&A (Item 7 / 10-Q Item 2):
1. `mdna_tone` in [-1, 1] - overall tone of the results and conditions as
   described.
2. `mdna_forward_tone` in [-1, 1] - tone of the forward-looking statements *as
   written* (not a return forecast; the sentiment of the language).
3. `mdna_uncertainty` in [0, 1] - density of hedging / "cannot predict" /
   "depends on" language.
4. `mdna_complexity` in [0, 1] - readability/obfuscation (dense, jargon-heavy,
   convoluted vs plain).
5. `mdna_liquidity_stress` in [0, 1] - prominence of liquidity / going-concern /
   financing-stress / covenant language (topic presence).
6. `mdna_change` in [0, 1] - magnitude of change vs the same issuer's immediately
   prior qualifying MD&A (LLM given both texts; scores degree/nature of change).

Risk Factors (Item 1A):
7. `rf_severity` in [0, 1] - overall gravity of the risks as described.
8. `rf_specificity` in [0, 1] - company-specific vs boilerplate.
9. `rf_litigation` in [0, 1] - prominence of litigation/regulatory exposure.
10. `rf_change` in [0, 1] - magnitude of change vs the prior qualifying Risk
    Factors (LLM given both texts).

For features 6 and 10 (change), the prior filing is by construction strictly older
(earlier acceptance), so it is fully point-in-time. The **first** qualifying filing
of a name (no prior) yields NaN change features, counted. All ten are bounded and
purely descriptive; none may reference price, return, or any post-filing outcome.

### 4.2 Extraction model + decoding (recorded, fixed)

- **Model:** a fixed Claude model via the `.env` `ANTHROPIC_API_KEY` (charter
  secrets). The **exact model identifier and its training cutoff are recorded in
  the run metadata at extraction time** (Rule 28). Per Spec 1, cutoff-restriction is
  **not** a usable primary guard - any modern model has hindsight over all of
  1998-2020 - so model identity is for the audit trail; the masked-probe (section
  5) is the load-bearing guard.
- **Decoding:** `temperature = 0`, fixed system+user prompt, **structured JSON /
  tool output** with the ten bounded fields, refusal to emit any field outside its
  range (re-ask once, else that field is NaN and counted). Deterministic +
  reproducible.
- **Caching:** each call keyed by a content hash of (masked section text[, masked
  prior text], prompt version); cached to disk so re-runs are free and the feature
  corpus is frozen. Prompt version is stamped into the cache key and the metadata.

### 4.3 Identity masking (default ON for production features)

Before any text reaches the model, a **deterministic** pre-processor redacts
identity and time anchors: the registrant name (from the filing header and the
bridge `name`), ticker, CIK, and all explicit dates/4-digit years, replaced with
`[COMPANY]` / `[DATE]` / `[YEAR]`. Dollar amounts and operational descriptors are
**kept** (they are descriptive, not identity). **Production features are extracted
from the masked text**, so the production feature never sees who or when. This is
the maximally hindsight-resistant default; the masked-probe audit (section 5) then
tests that masking actually neutralised hindsight by comparing against an unmasked
extraction on a sample. Masking is logged (what was redacted per document).

### 4.4 The prompt (forbids prediction and future knowledge)

System prompt (fixed, versioned):

> You are a financial-document analyst. You are given an excerpt from a company's
> SEC filing (its Management's Discussion and Analysis, or its Risk Factors) as
> written on an unknown historical date. The company's name and all dates have been
> removed. Score **only what this text says**, as a careful reader on the filing
> date would - describe the document, do not judge whether it is good or bad news
> for an investor. You must **not** try to identify the company or the date. You
> must **not** predict or imply anything about future stock returns, prices,
> performance, bankruptcy, or any outcome after the filing. If you find yourself
> using knowledge of what happened to any company, stop and score only the words on
> the page. Return **only** the requested JSON scores.

The user prompt supplies the masked section text (and, for change features, the
masked prior section text) plus the exact rubric and range for each field. The
prompt **never** contains the ticker, the name, the date, or any price/return
data. A single fixed rubric string per feature is stored with the spec's
implementation and versioned into the cache key.

### 4.5 Section-length truncation (addendum, 2026-08-11, fixed before any extraction)

The real-filing smoke test (Lehman/Bear/WaMu/Kraft) showed extracted sections
range from ~350 chars (incorporation-by-reference filings, legitimately tiny) to
~214k chars (Lehman's 2008 MD&A) - the largest being ~50k tokens, over a single
clean LLM call. Truncation rule, fixed a priori (operator decision, 2026-08-11):
**head 12,000 chars + tail 4,000 chars.** A section with `len <= 16,000` is sent
whole; a longer one is sent as `text[:12000] + <truncation marker> + text[-4000:]`.
This keeps the opening narrative (where overall tone, overview and the leading
risks sit) and the closing (liquidity/outlook, final risk items), drops the dense
tabular middle, and bounds tokens/cost deterministically. The `truncated` flag and
the original `char_len` are recorded per section (Rule 18). This rule is frozen
here before any extraction; changing it later to move a result requires a fresh
dated pre-registration.

---

## 5. The LLM hindsight-leakage audit (concrete thresholds, fixed a priori)

Instantiates Spec 1's posture. All sample sizes and thresholds are fixed **before**
any extraction; a feature failing a gate is dropped/quarantined, and the surviving
set is the frozen M2 group. If **all** features are rejected, the LLM layer is
dropped and Engine B ships on the mechanical baseline (reading A) - a pre-committed,
acceptable outcome.

### 5.1 Masked hindsight-probe (the load-bearing audit)

- **Sample:** `N = 1000` filings from the **1998-2020 build** universe, **stratified
  by year** (so 2001-02 and 2008-09 stress years are represented) and **by
  delisted vs surviving** name (so the sample is not survivor-skewed). Fixed seed
  `20260811`.
- **Two extractions per sampled filing** and per feature k: the masked/production
  value `m` (section 4.3) and an **unmasked** value `u` (identity + dates present).
  Shift `d = u - m`.
- **Label proxy:** the `fwd_ret_21` of the name at the first rebalance where that
  filing is the as-of filing (the return the feature would be used to rank).
- **Test per feature k:** `rho_k = Spearman(d_k, fwd_ret_21)` across the N filings.
- **Rejection (a priori):** reject feature k if **`|rho_k| >= 0.05` and its
  two-sided p-value `< 0.01`**. Meaning: knowing who/when moves the feature in a
  direction that lines up with the future -> hindsight is leaking through k.
  Rejected features are dropped from M2 and recorded. (N=1000 gives power to detect
  `rho ~ 0.05`.)
- **Magnitude flag:** if `mean(|d_k|) > 0.5 SD` of feature k, flag k as
  identity-sensitive even when `rho_k` is insignificant, and inspect manually
  (documented) before keeping it - a large identity sensitivity is a smell.

### 5.2 Marginal-IC ceiling (too-good => assume leaking)

- Before any M2 CV result is trusted, compute each surviving LLM feature's
  **standalone within-date rank-IC** vs `fwd_ret_21` on the build span. **Any single
  LLM feature with `|mean rank-IC| > 0.08` is assumed leaking** and is quarantined
  until it passes an enhanced probe (extracted from the *whole* filing vs just the
  section, and re-scored by a *second independent* model); only then may it enter
  M2. The 0.08 ceiling is deliberately tighter than the panel's 0.10: no single
  text feature should individually out-IC the entire five-factor composite (~0.025)
  by more than ~3x without suspicion.
- **Group ceiling:** if M2's build-span CV mean IC exceeds ~`0.10`, the whole result
  is assumed leaking (charter 5.3, Spec 1) and audited before anything is banked -
  not celebrated.

### 5.3 Deterministic lexicon cross-check (hindsight-free anchor)

For the tone and uncertainty features, compute a **Loughran-McDonald** finance-
lexicon analogue on the same section (fraction of LM-negative / LM-uncertainty
words) - fully deterministic, so it *cannot* have hindsight. Require
`Spearman(LLM tone, LM tone) >= 0.4` across the sample: agreement bounds how far
the LLM can drift from the actual language. Where the LLM tone **diverges** from the
lexicon in a way that correlates with `fwd_ret_21`, flag that divergence as
suspected hindsight (feeds 5.1). This is a cheap external-validity floor, not a
model feature, so it does not touch the M0/M1/M2 ladder.

### 5.4 A-priori constants (frozen by this commit)

`probe N = 1000; seed = 20260811; reject if |rho| >= 0.05 & p < 0.01;
identity-sensitivity flag at mean|d| > 0.5 SD; single-feature IC ceiling 0.08;
group IC ceiling 0.10; LM-agreement floor 0.40; staleness cap 18 months; rate
<= 8 req/sec; usable iff acceptance_date_et < T.` None of these may be changed to
rescue a weak or a too-good result; a change requires a fresh, separately dated
pre-registration stating why the original choice was wrong on grounds independent
of its result.

---

## 6. Synthetic tests (must pass before any real EDGAR fetch or extraction)

Mirror `tests/test_engine_b_synthetic.py`: build small in-memory EDGAR fixtures
(a synthetic `permaticker_cik` with windows, synthetic submissions rows, synthetic
HTML and old-`.txt` documents) and cross-check the ingestion + attribution + join
logic field-by-field against an independent pandas oracle. Required, pre-registered
assertions:

1. **Successor-entity rejected by the window rule.** CIK 999 backs `PT_A`
   (window `[2000-01-01, 2008-10-15]`, the WaMu analogue) and `PT_B`
   (`[2018-06-01, 2025-01-01]`, the successor). A filing accepted 2020-03-15
   attributes to `PT_B` **only, never** `PT_A`; a filing accepted 2005-06-01
   attributes to `PT_A` **only**; a filing accepted 2012-01-01 (in the gap) is
   **unattributed and dropped**, grafted onto neither. Counted.
2. **Overlapping windows fail loud.** Two permatickers sharing a CIK with
   overlapping windows + a filing in the overlap -> the ambiguity check exits
   non-zero with the offending `(cik, accession)`; it never silently picks one.
3. **A filing after T is not used at T.** Filings accepted 2010-02-10 and
   2010-05-12; at T=2010-03-31 the as-of feature is the 2010-02-10 filing, never
   the 2010-05-12 one; at T=2010-01-31 (before any filing) -> NaN features, counted.
4. **Strictly-before-T.** A filing accepted exactly on T=2010-03-31 is **not** used
   at the 2010-03-31 rebalance, but **is** used at 2010-04-30.
5. **Staleness cap.** A 2008-01-15 filing with no successor -> NaN (stale) at
   T=2010-06-30 (>18 mo), used at T=2009-03-31 (<18 mo). Counted.
6. **NaN fall-back, not fill.** A ranked name with no qualifying filing keeps its
   five mechanical factors and gets **NaN** (not 0) LLM columns; the NaN-LLM
   name-month count is reported.
7. **Both extraction formats.** A synthetic modern HTML 10-K (Item 7 / Item 1A
   headers) and an old plain-`.txt` SGML 10-K both yield the correct MD&A / Risk
   Factors spans vs the oracle; a pre-2006 10-K with no Item 1A yields NaN
   risk-factor features, counted.

A small **real-filing smoke test** (a handful of known CIKs: Lehman, Bear, WaMu,
plus one active name) confirms the live document fetch + parser on modern HTML and
an old `.txt` before the full extraction run. Only after 1-7 and the smoke test
pass does any full fetch/extraction proceed.

---

## 7. Anticipated outcome, recorded before the run

Recorded so a result that merely matches expectation cannot be sold as a discovery,
and a too-good result triggers a leak hunt, not a celebration (consistent with Spec
1's expectations):

- **Most likely honest outcome:** the LLM features carry a small, noisy, largely
  redundant signal; M2's marginal IC over M0 is positive but below the >=20% bar
  and/or statistically indistinguishable, or is matched by M1 (ML fitting, not the
  LLM). The LLM layer is **dropped**; Engine B ships on the mechanical baseline.
  Acceptable and pre-committed.
- **A genuine edge** (M2 clears >=20% over M0 **and** beats M1 significantly, with
  all features surviving the masked-probe and under the IC ceilings) would be a
  surprising, publishable marginal result - and is therefore held to the full audit
  before it is believed.
- **A large M2 gain that fails the masked-probe or breaches an IC ceiling is
  hindsight leakage, not edge** - the exact failure mode that made the sibling
  `LLM_SWING_MODEL` un-backtestable (charter 1). Find the leak, fix the
  feature/attribution, re-run on the build span.

## 8. Failure handling, fixed in advance

- A **too-good** feature or M2 result is a **leak to be found** (in the window
  attribution, the section parse, the masking, or LLM hindsight), not an edge to be
  banked. Fix and re-run on the build span.
- A **weak or indistinguishable** marginal IC is **not** a licence to re-tune the
  feature list, the prompt, the model, the masking, the thresholds, the join, or
  the CV to rescue it. Any such change requires a fresh, separately dated
  pre-registration stating why the original choice was wrong on grounds independent
  of its result.
- The **2021+ hold-out stays untouched** until a model clears the Spec 1 build-span
  bar; then it gets the single pre-registered delta touch. Examining it and then
  changing the pipeline burns it (Spec 1).
- **No premature victory.** `py_compile`/unit tests passing is not a result. A P4
  result requires the synthetic tests + smoke test to have passed, the leak audits
  (this file + Spec 1's training-harness audit) to have cleared, and the metrics to
  have been produced by the frozen pipeline on the real corpus, shown to the
  operator (Rule 14, Rule 27). All EDGAR/extraction pulls run on Godzilla `.venv`;
  git runs from PowerShell on Godzilla (Rule 24/27).

## 9. What Spec 2 does NOT change

No `KILL_RULE.md` threshold; no Spec 1 decision (OOS geometry, CV, M0/M1/M2 ladder,
LightGBM grid, delta test, adjudication, training-harness leak audit); no frozen
mechanical baseline, panel, universe, factors, or harness. Spec 2 only adds the
EDGAR corpus, the attribution, the LLM feature columns, and their audit.

## Changelog

- 2026-08-11 - Created and pre-registered (Spec 2 of 2), against the verified EDGAR
  submissions schema (probe `0d49af9`) and the CIK bridge (`39162cb`). Fixes: the
  ingestion contract (form set incl. historical 10-K405/10-KSB/10-KT and 10-Q
  variants; `/A` excluded and counted; submissions traversal of recent +
  filings.files[]; primaryDocument fetch with `.txt` full-submission fallback;
  8 req/sec; gitignored corpus cache; deterministic MD&A/Risk-Factors extraction
  over modern HTML and old SGML `.txt`, with pre-2006 Risk-Factors sparsity counted;
  storage schema). The leak-critical CIK->permaticker window attribution (in-window
  + acceptance_date_et < T, fail-loud ambiguity check, unattributed-gap drop, WaMu/
  COOP worked case) and the 1998-2020 coverage funnel. The (date, permaticker)
  feature join (as-of latest qualifying filing, 18-month staleness cap, NaN
  fall-back to M1 behaviour, within-date winsor+z, slots into the Spec 1 M2 matrix).
  The ten document-descriptive LLM-scored features, the fixed extraction model/
  decoding/caching, default-on identity masking, and the return-forbidding prompt.
  The hindsight-leakage audit with a-priori constants (masked-probe N=1000 seed
  20260811, reject |rho|>=0.05 & p<0.01, single-feature IC ceiling 0.08, group
  ceiling 0.10, LM-lexicon agreement floor 0.40). The synthetic + smoke tests
  gating any real extraction. Anticipated outcome and failure handling. **No result
  exists under this spec at commit time.**
- 2026-08-11 (addendum) - Section-length truncation rule fixed a priori (sec 4.5):
  head 12,000 + tail 4,000 chars, whole if <=16,000. Motivated by the real-filing
  smoke test showing sections up to ~214k chars (>50k tokens). Fixed before any
  extraction; still no result exists under this spec.
