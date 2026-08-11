# LLM_Model3 - Session Handoff, 2026-08-11 (Engine B / P3 complete, P4 kickoff)

Workstation Godzilla (Albuquerque, America/Denver). Working dir C:\trading\LLM_MODEL3.
Paper/backtest only; no paper trading running. Partition hard-rule held: no access
to C:\trading\LLM_SWING_MODEL\ or C:\trading\LLM model\; no DB/script/code/git
crossing. (Follows HANDOFF_2026-08-10_EngineB-P3.md, which opened P3 and ingested
the panel.)

## What this session did

Built, froze, measured, and recorded the **Engine B (P3) mechanical baseline** end
to end, under strict pre-registration discipline. All work is on origin/main
(NZ1979/LLM_MODEL3), HEAD `30d489a`. No modelling shortcut was taken: the harness
is proven leak-free before any result was trusted.

### 1. Implementation (frozen before any real run - the A-2 discipline)

- `data/sharadar_panel.py` - the leak-critical timing layer. permaticker attribution
  via a date-range join (recycling-safe; fails loud on overlapping windows),
  trailing windows on the name's own rows, 12-1 momentum and the 21-day forward
  label anchored on the market calendar, ART fundamentals joined datekey <= T,
  delisting folded into the label. Every read is as-of (<=) T. DuckDB.
- `models/engine_b_universe.py` - the six PIT screens + coverage funnel.
- `models/engine_b_factors.py` - five equal-weight factors (mom 12-1, value EY+B/P,
  quality gross-profitability, low-vol, size), cross-sectional winsorise+z within
  each date, composite, deciles.
- `validation/engine_b_harness.py` - rank-IC + Newey-West t, decile Sharpe
  monotonicity, long-only top-decile net of cost (5/10/20 bps sensitivity),
  long-short diagnostic, and a leak audit (cheat control + 25-seed permutation null).
- `scripts/run_engine_b_baseline.py` - the measuring run; `--span build|holdout`;
  hold-out gated by `--confirm-holdout`; results PRINTED, never written (so no
  result can share a commit with the pre-registered spec).
- `tests/test_engine_b_synthetic.py` - the synthetic leak audit.

Implementation commits: `f5d1d29` (impl + synthetic audit), `0cd79ec`
(shuffle -> true seeded permutation), `8a8eac8` (25-seed permutation null + z).
**Frozen harness at measurement = `8a8eac8`.**

### 2. Harness proven leak-free (three independent ways)

- **Timing oracle (synthetic):** the DuckDB timing layer is cross-checked
  field-by-field against an independent pandas re-implementation - 0 mismatches on
  close, marketcap, momentum, vol, dollar-vol, history, fundamentals, forward
  label/status. Recycled-ticker attribution splits correctly; overlapping windows
  fail loud; a filing dated after T is not used at T.
- **Cheat control (real panel):** score = realised forward return -> IC +1.000 and
  a perfect decile staircase on both spans. So a real look-ahead would land in the
  "assume leakage" zone; a modest real IC is therefore trustworthy.
- **Permutation null (real panel, 25 seeds):** null centred at ~0; real IC sits
  +11.7 SD (build) / +16.2 SD (hold-out) above chance.

Process note worth carrying: the shuffle control tripped mid-session (a roll-by-1
picked up permaticker-adjacency correlation). It was diagnosed (proven in the
sandbox), fixed to a true seeded permutation, then upgraded to a 25-seed
permutation test - not waved past. That is the discipline working.

### 3. Results (net 10 bps/side, out-of-sample) - docs/ENGINE_B_BASELINE_RESULTS.md (bb3b8e9)

| metric | Build 1998-2020 | Hold-out 2021-2026 |
|---|---|---|
| months | 265 | 66 |
| mean rank-IC | +0.0254 | +0.0496 |
| Newey-West t | +2.93 | +3.81 |
| months IC>0 | 60% | 74% |
| Spearman(decile, ret / Sharpe) | 0.87 / 0.92 | 0.95 / 0.96 |
| long-only D10 Sharpe / CAGR / maxDD | 0.54 / 9.6% / -59.7% | 0.57 / 10.4% / -21.1% |
| eligible names/month (median) | 1,262 | 1,565 |

This is the pre-registered "clean harness, modest real edge" outcome (anticipated
IC 0.02-0.05), nowhere near the 0.10 leakage line. The **2021+ hold-out is SPENT**
(touched once). Universe funnel healthy; delistings folded into labels (build
10,929; hold-out 4,985); no silent drops.

### 4. Adjudication

The two kill-rule conditions that apply to the mechanical baseline itself - IC > 0
and statistically distinguishable, and monotone decile Sharpe - are MET on both
spans. This establishes the **P4 benchmark IC (~0.025 build, ~0.050 hold-out)** and
proves the harness. It does NOT by itself ship or kill Engine B (charter / spec).

## Two open items (operator's to settle)

1. **Tradeable form:** the naive equal-weight long-only top decile is NOT it - deep
   drawdown (build -60%, hold-out -21%) and D10 is not even the best decile. P5
   construction will weight the mid-upper deciles and/or vol-target.
2. **Open kill-rule reading:** the Engine B clause is three ANDs (incl. the >=20%
   LLM lift) yet its closing sentence says Engine B can "stand or fall on the
   mechanical baseline alone" if the LLM is dropped. Whether the mechanical baseline
   alone can ship, or the >=20% LLM lift is mandatory, is a reading of the LOCKED
   kill rule the operator must confirm (dated decision in KILL_RULE.md) before P4
   concludes. Not changed here.

## Commits this session (all pushed, origin/main)

- f5d1d29 - P3 impl (universe/factors/harness/PIT panel) + synthetic leak audit
- 0cd79ec - fix leak-audit shuffle to a true seeded permutation
- 8a8eac8 - 25-seed permutation null + z; faster positional shuffle
- bb3b8e9 - record mechanical baseline results
- 30d489a - prior session handoff committed

## State: Engine A CLOSED. Engine B P3 mechanical baseline COMPLETE. Next is P4.

---

## Ready-to-paste kickoff prompt for the next session (P4)

Continue LLM_Model3 at C:\trading\LLM_MODEL3 on Godzilla (America/Denver). Verify
anchors first: run `date && TZ=America/Denver date`, confirm the working dir is
C:\trading\LLM_MODEL3 (NOT LLM_SWING_MODEL, NOT "LLM model"), and confirm the
workstation is Godzilla. Re-read CLAUDE.md, CLAUDE_PREFLIGHT.md (the 33-rule book),
PROJECT_CHARTER.md, and KILL_RULE.md before any operational step. Partition
hard-rule holds: no access to C:\trading\LLM_SWING_MODEL\ or C:\trading\LLM model\;
no DB/script/code/git crossing.

STATE as of 2026-08-11 (verify against git log, don't trust this framing):
- Engine A is CLOSED (research result, not tradeable). Do not reopen it.
- Engine B (P3) mechanical baseline is BUILT, FROZEN, and MEASURED CLEAN. HEAD is
  30d489a. Implementation commits: f5d1d29 (universe/factors/harness/PIT panel +
  synthetic leak audit), 0cd79ec (shuffle->true permutation), 8a8eac8 (25-seed
  permutation null). Frozen harness at measurement = 8a8eac8. Results recorded in
  docs/ENGINE_B_BASELINE_RESULTS.md (commit bb3b8e9).
- Benchmark IC (net 10 bps/side, OOS): build 1998-2020 mean rank-IC +0.0254
  (NW-t 2.93); hold-out 2021+ +0.0496 (NW-t 3.81). Deciles near-monotone
  (Spearman 0.87/0.95). Harness proven leak-free (synthetic field-by-field oracle,
  cheat control IC=+1.0, 25-seed permutation null with real IC 11.7/16.2 SD above
  chance). The 2021+ hold-out is SPENT (touched once by the mechanical baseline).
- Files: data/sharadar_panel.py, models/engine_b_universe.py,
  models/engine_b_factors.py, validation/engine_b_harness.py,
  scripts/run_engine_b_baseline.py (--span build|holdout, holdout gated by
  --confirm-holdout, results printed never written), tests/test_engine_b_synthetic.py.
  Panel: data/raw/sharadar/*.parquet, keyed on permaticker.
- DO NOT re-tune, re-run, or re-adjudicate the frozen mechanical baseline to chase
  a number. Any change to it needs a fresh, dated pre-registration stating why the
  original choice was wrong on grounds independent of its result.

P4 OBJECTIVE: add the LLM-as-feature layer to Engine B and measure its MARGINAL
information coefficient against the frozen mechanical baseline. The LLM is NEVER
the predictor (charter section 1) - it is only a feature extractor whose marginal
value is measured, never assumed. Per KILL_RULE.md, Engine B's LLM layer ships only
if baseline+LLM IC exceeds the mechanical-baseline IC by >=20% relative AND
statistically distinguishable; if indistinguishable, the LLM is dropped.

DO THIS BEFORE ANY MODELLING (same discipline that worked in P3: pre-register the
spec, commit it UNRUN, verify with git log, synthetic-test the harness path before
real data, touch any hold-out once, fail loud, no premature victory, git from
PowerShell on Godzilla). Settle and pre-register, in order:

1. HOLD-OUT / OOS GEOMETRY - the thorniest, settle first. The 2021+ hold-out is
   already spent on the mechanical baseline, so it cannot serve as a fresh, unseen
   test for a P4 model tuned to beat a now-known number. Decide and pre-register the
   P4 out-of-sample: a newly reserved period, a carve of untouched data, or a
   defined single touch - and the purged+embargoed walk-forward CV geometry on the
   training span (the LLM/ML layer DOES train, unlike the mechanical baseline, so
   purge overlapping label windows and embargo >= the 21-day horizon).

2. COMPARISON DEFINITION - the kill rule compares "baseline+LLM IC" to "the
   mechanical-baseline IC". To isolate the LLM's TRUE marginal value, also measure
   an ML model over the 5 mechanical factors WITHOUT any LLM feature, so the LLM
   gain is separated from the ML-fitting gain. Pre-register which comparison is the
   kill-rule test and which is diagnostic.

3. PREDICTOR MODEL - pre-register the model class (charter: gradient-boosted /
   neural ranker), the feature set, the training/CV protocol, the hyperparameter
   search, and exactly how IC and the >=20% delta significance are computed. No
   fitting choices made after seeing results.

4. RESOLVE THE OPEN KILL-RULE READING with the operator and record a dated decision
   in KILL_RULE.md: its Engine B clause is written as three ANDs (including the
   >=20% LLM lift) yet its closing sentence says Engine B can "stand or fall on the
   mechanical baseline alone" if the LLM is dropped. Whether a mechanical baseline
   that clears IC>0 + monotone deciles can ship on its own, or the >=20% LLM lift is
   mandatory, must be settled before P4 concludes.

DATA PREREQUISITE + THE CENTRAL LEAKAGE TRAP: the panel is Sharadar price +
fundamentals only - there is NO text. LLM feature extraction needs a point-in-time,
survivorship-aware text source (news / filings / transcripts) stamped by
knowable-at-time, sourced and integrity-validated like the Sharadar panel was in P3.
This is likely the first P4 sub-task. CRITICAL: an LLM run over historical text has
hindsight from its own training corpus (it "knows" Lehman failed), which can leak
the future into a supposedly point-in-time feature - this is exactly the trap that
made the sibling LLM_SWING_MODEL un-backtestable (charter section 1), and it is the
reason the LLM is a feature extractor measured for marginal IC, never the predictor.
Pre-register how P4 guards against LLM training-hindsight leakage before extracting
any feature, and audit for it (a too-good marginal IC is assumed leaking until
proven otherwise).
