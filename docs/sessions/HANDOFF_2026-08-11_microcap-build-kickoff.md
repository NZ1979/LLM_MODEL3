# HANDOFF 2026-08-11 — Microcap experiment: build kickoff

Anchors (verify first): date 2026-08-11 (America/Denver); working dir
`C:\trading\LLM_MODEL3`; workstation Godzilla. Verify HEAD with `git log` (do not
trust any remembered SHA). Partition hard-rule holds. Pulls/runs on Godzilla `.venv`
(sandbox firewalled); git from PowerShell on Godzilla (Rule 24/27). Discipline is
unchanged: pre-register unrun → implement → synthetic-test → **freeze/commit before
any real run** → run → audit. Kill rule locked; no goalpost moves.

This handoff supersedes `HANDOFF_2026-08-11_P4-built-P5-kickoff.md` as the active
direction. That doc remains valid for P4/P5 background.

---

## Part 1 — Detailed summary of this session (2026-08-11)

### 1a. What was built (now parked)
The full Engine B **P4 LLM-feature pipeline** was pre-registered (Spec 2, `27d78dc`)
and built end-to-end: EDGAR ingestion, the leak-critical CIK→permaticker window
attribution (validated on real data — the WaMu→Mr.Cooper continuation split held),
deterministic MD&A/Risk-Factors extraction (modern HTML + old SGML), the masked
temperature-0 Anthropic extractor, the sec-5 hindsight audit, and corpus/extraction/
compare runners — three green test suites, nine commits (`27d78dc`→`93f2b89`), all
pushed. A real pilot ran: 150 names → 4,291 filings; Sonnet-4.5 extraction of 200
filings cost ~$7 (2.17M tokens, ~$0.029/filing); Haiku-4.5 agreed with Sonnet on the
core MD&A features. **P4 is complete, working, and PARKED** — see the prior handoff
and `[[kill-rule-reading]]` for full state and open items.

### 1b. The strategic reassessment that redirected the project
On request, an honest viability read was done, and it changed the plan. The chain of
reasoning, recorded so it isn't relitigated:

- **Making money is the primary objective** (operator, explicit).
- **Rigor measures edge; it does not create it** (metal-detector analogy). The
  excellent methodology here guarantees the results are *trustworthy*, not that a
  large edge *exists*.
- **"Superior hardware" is not a trading edge** for daily/weekly systematic equity —
  the edge is signal + data, not FLOPS. Hardware is the edge only in HFT (excluded by
  charter, and unwinnable from a desktop) or in cheap large-scale local NLP/alt-data
  over thousands of under-covered names (which points back to microcaps).
- **The proven edge is real but thin:** Engine B mechanical baseline net rank-IC
  0.025 (build) / 0.050 (hold-out), long-only D10 Sharpe ~0.54, deep drawdown; Engine
  A closed (passed at 0.59 but not implementable — needed 3.7× leverage). As a
  standalone profitable business the realistic odds are low (~10–20%); as a small,
  real, self-run edge, higher but modest.
- **Cross-sectional alpha concentrates in small/illiquid, under-covered names** and
  decays in liquid large caps (robust literature finding; charter §4). A small
  individual can trade the microcap tail that large funds physically cannot — a
  genuine structural edge. This is also where the operator's two real advantages
  (small size + compute) compound.
- **Shorter/intraday horizons are worse for microcaps,** not better: net edge =
  gross edge − (cost/trade × frequency), and microcaps have the market's widest
  spreads, so raising frequency there is the worst possible move. Intraday is the
  HFT/microstructure game (unwinnable from a desktop; no intraday data; charter
  excludes it). Under-coverage means microcap mispricings correct *slowly* → patience
  is the edge; longer holds win.
- **Operator circumstances (age 65):** the objective shifts from maximize-edge to
  grow-while-controlling-drawdown-and-sequence-risk; can't spend years validating.
  This made microcaps wrong **as the core** (deepest drawdowns, fraud/delisting tail,
  slow to gain confidence).
- **The resolving reframe — a defined-risk satellite (~$100k):** the operator will
  ring-fence ~$100k of true risk capital for a higher-risk/higher-return sleeve, core
  untouched. This dissolves both microcap objections: at $100k, *small size is a real
  edge* (you can trade illiquids funds can't) and the *downside is bounded* (risk
  capital). Microcaps, wrong at $500k-as-core, are the right build at $100k-as-satellite.
- **The honest hurdle:** the benchmark for the sleeve is NOT cash — it's a one-click
  factor/trend ETF (momentum, small-cap value, managed-futures). Anything *built* must
  beat that net of costs and the operator's time. **Microcaps are the one place a
  custom model can beat a buyable ETF, because no ETF fishes there.** Everything
  liquid is already packaged cheaply; building it adds nothing.
- **Timeline fits:** the rigorous 25-year survivorship-free backtest *is* the
  confidence — no need for years of forward paper. Deploy timeline is a fast backtest
  (days) → short paper sanity check (weeks–months) → live. A healthy 65-year-old's
  ~20-year horizon is ample to run a real edge.
- Realistic expectation if it works: low-to-mid-teens return, high vol, deep
  drawdowns — better than conservative securities, but the edge *over* a factor ETF is
  the uncertain part, which the test decides. Guardrails: not financial advice; $100k
  must be true risk capital; **no leverage or options** even here; keep the core
  conservative; a fee-only fiduciary advisor is the right call for the whole-picture
  question.

### 1c. The decision
**Build and run the microcap-tail experiment** (already pre-registered) as the test of
whether a real, capturable net edge exists for a ~$100k risk sleeve. Spec committed
unrun: `docs/ENGINE_B_MICROCAP_SPEC.md`. If it beats the benchmark net of honest
costs, deploy the sleeve after a short paper check; if not, the honest answer is buy a
factor ETF and don't overbuild. Either way, an answer in days.

### 1d. Artifacts created this session
`docs/ENGINE_B_P4_SPEC2.md` (+truncation addendum), the P4 pipeline (9 commits),
`docs/sessions/HANDOFF_2026-08-11_P4-built-P5-kickoff.md`, and
**`docs/ENGINE_B_MICROCAP_SPEC.md`** (the build target). Memory updated:
`[[p5-pivot]]`, `[[kill-rule-reading]]`.

---

## Part 2 — Current project state

- **Engine A:** CLOSED (passed backtest, not implementable). An *implementable*
  trend/risk-premia sleeve remains a good future "core" idea (see prior handoff), but
  is NOT this build.
- **Engine B mechanical baseline:** FROZEN & MEASURED on the *liquid* $300M–$15B band
  (harness `8a8eac8`, results `bb3b8e9`): build IC +0.0254, D10 Sharpe 0.54, maxDD
  −59.7%; hold-out 2021+ IC +0.0496 (**spent** for that liquid universe). **Do not
  modify.**
- **P4 LLM layer:** built, pilot-run, parked.
- **Microcap experiment:** pre-registered UNRUN (`docs/ENGINE_B_MICROCAP_SPEC.md`);
  **this is the build.**
- The microcap universe has **never been evaluated**, so its 1998–2020 is a clean
  build span and its 2021+ is a clean once-touch hold-out.

---

## Part 3 — The build (implement `docs/ENGINE_B_MICROCAP_SPEC.md`)

Read the spec first — it fixes every parameter a priori. Summary of what to build,
with the frozen invariant called out.

### 3a. Small pre-run spec addenda (append to the spec, dated, BEFORE running)
Two knowable-at-time refinements to record in the spec's changelog before any result:
1. **Add AUM = $0.1M to the reported capacity grid** (the operator's actual sleeve is
   ~$100k; at that size impact is lowest and most of the edge is captured). Grid
   becomes $0.1M / $0.5M / $2M / $5M. This is a *reported* point, not a tuning knob.
2. **Fix the in-backtest benchmark:** the passive comparison is the **equal-weight
   microcap eligible universe** ("just hold all of them") plus **SPY** (via Tiingo,
   the Engine A ETF source). The *live decision* benchmark (a real small-cap-value or
   momentum ETF, e.g. VBR/IJS or MTUM, or a managed-futures ETF) is chosen at paper
   time. Record which ETF a priori when paper trading is set up.

### 3b. Components to build
Reuse frozen, do NOT edit the frozen result paths:

1. **Parameterised universe screen.** The frozen `models/engine_b_universe.py::screen`
   uses hardcoded baseline bands. Provide a parameterised screen (size/liquidity/price
   bands as arguments) for the microcap runs **without changing baseline behaviour**.
   REQUIRED INVARIANT CHECK: after refactor, re-running the frozen baseline
   (`scripts/run_engine_b_baseline.py --span build`) must reproduce `bb3b8e9`'s numbers
   **exactly** (IC +0.0254 etc.). If it can't be guaranteed, add a *separate* screen
   function/module for microcaps and leave `screen` byte-for-byte untouched.
2. **Realistic cost module** (`validation/costs_microcap.py`, new):
   `cost_bps_per_side = half_spread_bps(tier) + IMPACT_K*sqrt(participation)`;
   `participation = position_notional / dollarvol_60`; tiers liquid=10 / micro=50 /
   nano=150 bps; `IMPACT_K=100`; commissions 1bp; AUM-aware; cost-scale 0.5×/1×/2×.
   Leave the frozen flat-cost harness path intact.
3. **Low-turnover buffered long-only construction**
   (`models/engine_b_portfolio.py`, new — shared with future P5): quarterly rebalance;
   hysteresis (buy at D10, hold until below D8 — carry a holdings set across months);
   equal weight capped at min(1/N, 10×dollarvol_60/AUM, 3% of book), renormalised;
   ~50–100 names; monthly net return series (compound held names' monthly returns,
   charge the per-name realistic cost on realised turnover at rebalance months);
   report turnover, participation, n_held, delisting rate.
4. **Runner** (`scripts/run_engine_b_microcap.py`): grid over tier (micro primary /
   nano / full-tail) × AUM ($0.1M/$0.5M/$2M/$5M) × cost-scale (0.5×/1×/2×) ×
   sensitivities (liquidity ≥$100k/$250k/$500k, price ≥$2/$5). Reports, per cell: mean
   monthly rank-IC + NW t (vs liquid +0.0254), decile monotonicity, NET tradeable
   Sharpe/CAGR/maxDD/turnover, coverage/denominators (Rule 18), leak audit (reuse the
   frozen cheat-control + permutation null). Prints benchmark comparison (equal-weight
   universe + SPY). Results PRINTED, never written to disk (so no result shares the
   spec commit).

### 3c. Synthetic tests (must pass before any real run)
Mirror `tests/test_engine_b_synthetic.py`. Assert, on synthetic tables: the
parameterised screen selects the intended band; the cost model rises with
participation and tier (micro > liquid; larger order/ADV → higher bps); the buffer
construction (D10-in/<D8-out, quarterly) has **strictly lower turnover** than a naive
monthly-D10 rebalance; per-name weights respect the caps and sum to 1; delisting is
folded into the held-name return (a name delisting mid-hold realises its delisting
return, not a silent drop). And the baseline-invariant check from 3b.

### 3d. Run sequence (Godzilla `.venv`, after freeze/commit)
1. Build/leak-audit on **1998–2020** first; confirm the leak audit is clean and IC
   isn't in the "assume leakage" zone (>0.12 or a perfect staircase → hunt for
   survivorship/leak before trusting).
2. Only then, **one touch** of the **2021+** hold-out.
3. Apply the a-priori decision rule: microcaps qualify for the sleeve iff NET
   tradeable Sharpe beats the liquid baseline by **≥ +0.20 annualised on BOTH spans**
   AND survives 2× cost, with IC>0 + monotone deciles. Higher gross IC alone does not
   qualify.

### 3e. Deliverable of the build session
A frozen, committed implementation; the printed 1998–2020 + 2021+ metric grid with the
benchmark comparison; and a clear read on whether a real net edge exists for the $100k
sleeve. If yes → next is a short paper-trading setup (pick the live ETF benchmark,
pick a paper broker — none exists in the repo yet — automate the quarterly rebalance
on Godzilla, pre-register the paper→real-money gate). If no → recommend a factor ETF
and stop overbuilding.

---

## Part 4 — First steps for the build session

1. Verify anchors; re-read `CLAUDE.md`, `CLAUDE_PREFLIGHT.md`, `PROJECT_CHARTER.md`,
   `KILL_RULE.md`, `docs/ENGINE_B_BASELINE_SPEC.md`, `docs/ENGINE_B_BASELINE_RESULTS.md`,
   and **`docs/ENGINE_B_MICROCAP_SPEC.md`**. Confirm HEAD / clean tree.
2. Append the two dated spec addenda (§3a) to `docs/ENGINE_B_MICROCAP_SPEC.md`; commit
   (still no result under it).
3. Build the four components (§3b), reusing frozen `data/sharadar_panel.py` +
   `models/engine_b_factors.py` + the IC/decile parts of
   `validation/engine_b_harness.py`.
4. Write and pass the synthetic tests (§3c), including the baseline-invariant check.
5. **Freeze/commit unrun**, verify with `git log`.
6. Run 1998–2020 on Godzilla, audit; then 2021+ once; record results in a new
   `docs/ENGINE_B_MICROCAP_RESULTS.md` (results file, committed after the fact, never
   in the same commit as the spec).
7. Apply the decision rule; report to the operator; recommend deploy-with-paper or
   buy-the-ETF.

---

## Part 5 — Guardrails and framing to preserve

- **This is a ~$100k defined-risk satellite**, not the core. Size for a −40% year to
  be annoying, not damaging. Core stays conservative and untouched.
- **The bar is NET tradeable Sharpe beating a buyable factor/trend ETF**, not gross
  IC. Microcaps justify a custom build only because no ETF can fish there.
- **No leverage, no options.** Long-only only (borrow is unavailable in microcaps
  anyway).
- **Survivorship handling is load-bearing** — most microcap backtests are worthless
  from survivorship bias; the panel is survivorship-free, which is the whole reason
  this test can be honest. Show the delisting rate.
- **Do not modify the frozen liquid baseline, Spec 1, Spec 2, or the microcap spec's
  fixed parameters to chase a number** — any change needs a fresh dated
  pre-registration.
- Not financial advice; the operator should weigh the whole picture with a fee-only
  fiduciary. Live microcap risks (halts, fraud, gappy fills, borrow) appear only in
  paper/live and must gate real money.
- P4 (LLM layer) stays parked; it becomes an optional upside research sleeve only if
  the core money path is validated first.
