# HANDOFF 2026-08-11 — P4 pipeline built & validated; pivot to P5

Anchors (verify at the top of the next session): date 2026-08-11 (America/Denver);
working dir `C:\trading\LLM_MODEL3`; workstation Godzilla. HEAD at wrap: **93f2b89**
(verify with `git log`, don't trust this line). Partition hard-rule holds. Data
pulls / EDGAR fetches / extraction run on Godzilla `.venv` (the sandbox is
firewalled); git runs from PowerShell on Godzilla (Rule 24/27).

---

## Part 1 — Summary of today (2026-08-11)

**What got built and committed (all pre-registered / A-2 discipline, no result under any spec commit):**

1. **Engine B P4 Spec 2 pre-registered and committed unrun** (`27d78dc`, +truncation
   addendum later): `docs/ENGINE_B_P4_SPEC2.md`. Fixes the EDGAR ingestion contract,
   the leak-critical CIK→permaticker window attribution, the (date, permaticker)
   feature join, the ten document-descriptive LLM features, the extraction
   model/prompt/masking, and the sec-5 hindsight-leakage audit with a-priori
   thresholds — all against the *verified* EDGAR submissions schema.

2. **The full P4 ingestion/attribution/parse pipeline built and VALIDATED ON REAL
   DATA** (`1388be2` → `29bc881`). `data/edgar_ingest.py`,
   `data/edgar_attribution.py`, `data/edgar_sections.py`,
   `features/edgar_llm_features.py`, plus `tests/test_edgar_synthetic.py` and
   `scripts/edgar_smoke_test.py`. The real-filing smoke test (Lehman/Bear/WaMu/Kraft)
   confirmed the load-bearing pieces on real filings:
   - **Attribution works:** WaMu CIK 933136 split cleanly to permaticker 197327
     (1996–2008) vs 124183 (Mr. Cooper/COOP successor, 2015–2025); the 13 gap filings
     dropped; WaMu's post-2008 filings did NOT graft onto WaMu. The CIK-continuation
     leak defense holds on real data.
   - **Section extraction works** on both modern HTML (inline-XBRL) and old SGML
     `.txt`; Risk Factors present post-2006, correctly absent pre-2006.
   - Two real-data bugs found and fixed via the smoke test: `canon_cik` crashed on the
     bridge's null CIKs (`ba51c04`); MD&A returned None on modern HTML from a blanked
     apostrophe entity + straight-quote-only regex (`29bc881`).

3. **The LLM extractor + audit + runners built** (`5816bb3`, `d23269c`, `6f9ac87`,
   `93f2b89`): `AnthropicExtractor` (masked, temperature-0, forced-JSON, disk-cached,
   head-12k+tail-4k truncation), `features/edgar_audit.py` (the sec-5 decision rules),
   `scripts/build_edgar_corpus.py`, `scripts/extract_llm_features.py`,
   `scripts/compare_extractors.py`, and `tests/test_edgar_extract.py` +
   `tests/test_edgar_audit.py` (all green in the sandbox). More real-data fixes:
   NaN/missing-section coercion (`d23269c`), non-numeric model output like Haiku's
   `<UNKNOWN>` → NaN (`93f2b89`).

4. **Pilot run (real EDGAR + real LLM, on Godzilla):**
   - Corpus: 150 names → 4,291 filings; MD&A found on 91%, RF handled correctly
     (present post-2006, none pre-2006). **14 dual-class CIKs were dropped as
     "ambiguous"** — a known bug (see Part 4).
   - Extraction (Sonnet 4.5, 200 filings): MD&A features 98.5% coverage, in-range,
     sane means. Cost: **2,166,652 tokens ≈ $7** (~$0.029/filing on Sonnet 4.5).
   - Haiku-4.5 vs Sonnet-4.5 comparison on the same 200: agrees well on the core MD&A
     features (Spearman 0.82–0.90 on tone/forward-tone/uncertainty/liquidity), fuzzier
     on complexity (0.64) and change (0.60); RF too undersampled here to judge (n≈20).

5. **Strategic reassessment (the important part).** On request, gave a realistic
   viability read. Engine A is closed (passed backtest, not implementable). Engine B's
   proven edge is real but thin (net IC 0.025–0.05, long-only D10 Sharpe ~0.5, deep
   drawdown, D10 not even the best decile). The LLM layer is, by its own
   pre-registration, most likely to add nothing distinguishable. **Conclusion: the
   highest-information, lowest-cost next step is P5 (turn the proven Engine B baseline
   into a real, cost-modeled, paper-traded book) — NOT more spend on the P4 LLM
   layer.** Decision: **prioritize P5; park P4 with all state preserved.**

**Commits today (in order):** `27d78dc` (Spec 2) → `1388be2` (P4 core) → `ba51c04`
(canon_cik fix) → `29bc881` (parser fixes) → `5816bb3` (extractor phase) → `d23269c`
(NaN fix) → `6f9ac87` (--out + compare) → `93f2b89` (`<UNKNOWN>` fix). All pushed to
`origin/main`.

---

## Part 2 — Project state snapshot

- **Engine A: CLOSED.** Kill-rule PASS (net Sharpe 0.59) but not implementable (3.70x
  mean gross; fails at DTB3+200bps); capped A-2 missed. Not to be re-tuned. Ballast is
  gone; Engine B stands alone.
- **Engine B mechanical baseline: FROZEN & MEASURED, clears its kill-rule ship
  condition** (harness `8a8eac8`, results `bb3b8e9`; `docs/ENGINE_B_BASELINE_RESULTS.md`):
  - Build 1998–2020: mean rank-IC **+0.0254** (NW t 2.93), decile Spearman 0.92,
    long-only D10 Sharpe **0.54**, maxDD **−59.7%**, turnover 0.55/reb.
  - Hold-out 2021+ (**SPENT** — touched once): IC **+0.0496**, Sharpe 0.57, maxDD −21.1%.
  - The results doc itself flags: the naive equal-weight long-only D10 is **NOT the
    tradeable form** (drawdown too deep; D10 not the best decile). That gap is exactly
    what P5 must close.
- **Engine B kill-rule reading A** (`776a60d`): the mechanical baseline can ship
  Engine B on its own (IC>0 + monotone deciles, net, OOS — both met). The ≥20% LLM
  lift gates only whether the LLM layer is *included*. So P5 does not need P4.
- **P4 (LLM layer): built, pilot-run, PARKED.** See Part 4.
- **The 2021+ hold-out is spent** (mechanical IC measured there once). Any new
  model/construction tested on 2021+ is no longer a clean OOS — see Part 3 geometry.

---

## Part 3 — P5 objective and detailed plan

**Goal:** decide whether Engine B is worth real capital by turning the proven
mechanical signal into a properly-constructed, cost- and capacity-modeled, long-only
book, and validating it forward via paper trading — before any real money (charter §7,
P5). This is the cheap test that determines the whole program's viability.

**Discipline (unchanged):** pre-register the construction and cost model in a dated
spec, commit it UNRUN, then implement, synthetic-test, freeze, and measure — same A-2
process that produced the trustworthy baseline. Construction choices (which deciles,
vol target, caps, turnover buffer) are dredgeable, so they are fixed a priori.

### 3.1 First task — pre-register `docs/ENGINE_B_P5_CONSTRUCTION_SPEC.md` (unrun)

Fix, before any measurement:

**(a) Book construction (long-only; shorting killed Engine A).** Decide and freeze:
- Selection: top-decile is a straw man. Prefer a **score-weighted long book over the
  top quintile (D9–D10) or a smooth rank/z-tilt**, to avoid the D10 "lottery/junk"
  softening the results doc noted, and to cut concentration.
- Within-book weighting: equal vs score-tilted, with a **per-name cap** (e.g. ≤ 2–3%
  of the book AND ≤ a small % of the name's trailing ADV, so orders are executable).
- Name count target ~50–150 (charter). At $500k that's $3k–10k/position — fine under
  the existing $5M-ADV screen.
- **Volatility targeting** to a fixed annual vol (mandate is aggressive, 25–35% DD
  tolerance → a target around 15–20% is a defensible starting point). Long-only in a
  cash account means vol-targeting is mostly *de-risking to cash/SHY* in high-vol
  regimes rather than levering up. Fix the target and the trailing-vol estimator.
- Rebalance monthly (signal cadence). Add a **turnover buffer / hysteresis** (only
  trade names crossing a rank threshold) to cut cost — pre-register the buffer width.

**(b) Realistic cost & capacity model** (beyond the baseline's flat 10bps):
- Slippage that **scales with participation**: base bps + a square-root market-impact
  term ~ `k · sqrt(order_notional / ADV)`, per name. Fix `k` and the base a priori.
- Commissions ~1bp.
- **Capacity curve:** sweep AUM ($0.5M / $2M / $10M / $50M) and report where net
  Sharpe degrades — this tells you how much the edge can hold and whether it can ever
  be more than a personal return-enhancer.

**(c) Evaluation geometry (read carefully — the hold-out is spent):**
- Develop and freeze the construction on **1998–2020 only.**
- The 2021+ hold-out was already touched for the mechanical IC, so constructed metrics
  there are **semi-in-sample** (the signal's behaviour on that span is known). Report
  them but label them as such — they are NOT a fresh OOS test.
- **The genuine OOS test for P5 is forward paper trading** (unseen future). Treat it as
  the real gate, not the 2021+ numbers.
- Benchmark net returns against **SPY, a small/mid ETF (IJR/IJH), and an equal-weight
  version of the eligible universe** — the constructed book must beat passive *net of
  everything* to justify the effort and capital.

**(d) Paper-trading ship bar (a priori, before paper starts):** e.g. paper-trade N
months (say 6–12), require live net Sharpe within a set tolerance of the backtest, max
drawdown within tolerance, and no operational failures — only then consider small real
money. Fix N and the tolerances in the spec.

### 3.2 Implementation (after the spec is committed unrun)

Reuse the frozen pieces — do NOT modify them:
- `data/sharadar_panel.build_panel_from_parquet` → the PIT panel (unchanged).
- `models/engine_b_factors.compute_scores` → `composite`/`decile`/`ranked` per
  (date, permaticker) (unchanged).
- `validation/engine_b_harness.py` → `decile_table`, `long_only_top_decile`, the
  cost-curve helpers (`_curve_metrics`, `_portfolio_monthly`) — extend, don't edit.
- `validation/costs.py`, `validation/backtest.py` (Engine A's; adapt the impact model).
- `scripts/run_engine_b_baseline.py` → template for a new `scripts/run_engine_b_portfolio.py`.

Build `models/engine_b_portfolio.py` (construction: selection → weights → vol-target →
caps → turnover buffer) and a cost/capacity module, synthetic-test the construction
mechanics (weights sum to 1, caps respected, turnover buffer reduces trades, vol-target
scales exposure), freeze/commit, then run on 1998–2020 and report net Sharpe/CAGR/maxDD/
turnover + the capacity curve + the benchmark comparison. Then stand up the monthly
paper loop on Godzilla (pick a paper execution venue — LLM_Model3 has no broker yet;
this is a scoped decision) with monitoring of realized vs expected IC, turnover, and
slippage.

### 3.3 Strategic context to carry forward (honest framing)

P5 is the decision point, not a formality. The proven edge is modest (net IC 0.025–0.05,
naive Sharpe ~0.5, deep drawdown). If proper construction + realistic costs leave a
respectable net Sharpe that beats passive small/mid exposure, Engine B is worth paper
trading and possibly small real capital, and *then* the P4 LLM layer becomes an
interesting "push it higher" question. If construction/costs erode it, that is a
decisive, cheap answer that saves the P4 spend. Either outcome is a good use of the next
session. Do not let a weak P5 result trigger goalpost-moves — the kill rule is locked.

---

## Part 4 — P4 parked state (preserve; resume only if P5 validates the edge)

All P4 code is built, committed, and pushed; ingestion/attribution/parse validated on
real data; the extractor + sec-5 audit rules + corpus/extraction/compare runners done
and green; the pilot run once (Sonnet 4.5, ~$7). **P4 is optional upside and is
deferred behind P5.** If resumed, the open items are:

- **Model + cost decision (unresolved):** Sonnet 5 (recommended — newer & cheaper than
  the 4.5 piloted, tighter on the subtle features) vs Haiku 4.5 (budget, ~$700 batch);
  and whether to build the **Batch API** path (−50%). Full build est. ~100k–300k
  filings ≈ ~$700 (Haiku+batch) to ~$4,300 (Sonnet 4.5 standard). Pin the exact
  eligible-name count (free, panel screen) before committing.
- **Share-class attribution bug (must fix before any full build):** the fail-loud
  ambiguity check drops dual-class companies (one CIK, overlapping share-class windows,
  one 10-K) — 14/150 in the pilot. Fix: attribute a filing to *all* contemporaneous
  overlapping-window permatickers (share classes correctly share the issuer's text);
  the WaMu→COOP successor case stays protected by *disjoint* windows. Needs a dated
  Spec 2 correction (correctness fix, independent of results) + update synthetic test
  #2 to expect multi-attribution instead of fail-loud.
- **Section-aware carry-forward at the panel join (to build):** Risk-Factors update
  annually, MD&A quarterly. Carry each section's features forward from its own last
  filing (RF from the last 10-K) so RF features aren't NaN most months. Both stay
  strictly acceptance-date < T. Note as a Spec 2 join refinement.
- **Still to build for P4:** the audit label-join runner (join masked-probe shifts to
  `fwd_ret_21` from the panel to drive the sec-5 rejection tests), and the M1/M2
  LightGBM walk-forward harness from Spec 1 (CV, delta test, adjudication).

Full P4 detail is in `[[kill-rule-reading]]` memory and `docs/ENGINE_B_P4_SPEC.md` /
`docs/ENGINE_B_P4_SPEC2.md`.

---

## Part 5 — First steps for the P5 session

1. Verify anchors; re-read `CLAUDE.md`, `CLAUDE_PREFLIGHT.md`, `PROJECT_CHARTER.md`,
   `KILL_RULE.md`, `docs/ENGINE_B_BASELINE_SPEC.md`, `docs/ENGINE_B_BASELINE_RESULTS.md`,
   and `docs/PAPER_TRADING_PLAN.md` (dormant, Engine A — adapt for Engine B).
2. Confirm HEAD and clean tree via `git log` / `git status`.
3. Draft and commit `docs/ENGINE_B_P5_CONSTRUCTION_SPEC.md` **unrun** (§3.1), verify
   with `git log` (no result under it).
4. Implement construction + cost/capacity; synthetic-test; freeze/commit; run on
   1998–2020; report net metrics + capacity curve + benchmark comparison.
5. If it clears a sensible net-Sharpe bar vs passive, stand up the monthly paper loop
   and pre-register the paper→real-money gate.

Do NOT re-tune the frozen mechanical baseline, Spec 1, or Spec 2 to chase a number
(needs a fresh dated pre-registration). The 2021+ hold-out is spent; forward paper
trading is the real OOS. No real money until P5 construction holds AND paper trading
clears the pre-registered bar.
