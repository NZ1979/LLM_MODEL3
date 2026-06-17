# PROJECT_CHARTER.md - LLM_Model3

Status: P0 scaffold. Date created: 2026-06-17 (Mountain). Workstation: Godzilla (Albuquerque, NM / America/Denver).

## 1. Why this project exists

LLM_Model3 is a systematic equities/ETF research program whose central design choice is that **edge must be measurable on history before any time or capital is risked.**

The sibling project, `LLM_SWING_MODEL`, uses a pretrained LLM *as the predictor*. That makes it intrinsically un-backtestable: the model has hindsight over any historical window inside its training data, so a historical backtest measures memory, not forecasting. That project has been forced into slow forward-paper-only validation, has shown no proven edge after months, and its parameters were repeatedly over-tuned against a handful of losing trades.

LLM_Model3 is the corrective.

**Guiding principle:** harvest documented, persistent edges in places where competition is thinner. Do not hunt for a secret signal. **Never let the LLM be the predictor.** The LLM, if used at all, is a *feature extractor* whose marginal value is measured against a mechanical baseline, never assumed.

## 2. Partition (hard rule)

LLM_Model3 is operationally isolated from two sibling projects on Godzilla:

- `C:\trading\LLM_SWING_MODEL\` - separate LLM-catalyst swing project, still running paper. **No** shared DB, **no** executing its scripts, **no** importing its code.
- `C:\trading\LLM model\` - legacy intraday archive, read-only. **No** cross-folder DB access, **no** cross-folder script execution, **no** shared git history.

The two design docs in `LLM_SWING_MODEL\docs\` (`LLM_Model3_CHARTER_PROPOSAL.md`, `LLM_Model3_EDGE_DESIGN.md`) may be **read** for reference but **not** imported. This charter is the source of truth; anything those docs say that conflicts with this file loses.

## 3. Locked operator constraints

- **Markets:** equities and ETFs only. No crypto, no futures, no options.
- **Capital:** $500k+. Capacity-constrained microcap edges are mostly out of reach; favor liquid ETFs and liquid small/mid-cap equities.
- **Risk posture:** aggressive. Maximize edge, accept large (25-35%) drawdowns.
- **Operations:** light-touch / mostly automated. Daily or weekly systematic rebalance. No intraday.
- **Money:** paper/backtest only by default. No real money until an engine clears the kill rule AND survives paper trading.

## 4. The design - two low-correlation engines

Each engine is independently backtested. Combine by vol-targeting each and weighting by inverse correlation. Engine A is ballast; capital tilts toward B for upside.

### Engine A - CORE / ballast: multi-asset trend following via liquid ETFs

Time-series (trend) momentum across a diversified ETF basket spanning asset classes without leaving an equities/ETF account. Blended multi-timeframe trend signal, volatility-targeted positions, risk-parity weighting. This is the highest-probability path to a real, persistent, net-of-cost edge: trend following is the most replicated result in quant. 15-20+ years of clean ETF data; capacity is a non-issue at $500k; weekly rebalance is light-touch. It is the ballast that lets Engine B run aggressive without sinking the program.

**Approved universe (~22 ETFs, locked 2026-06-17):**

- Equity sectors & regions: SPY, XLK, XLF, XLE, XLV, XLI, XLY, XLP, XLU, XLB, XLRE, EFA, EEM
- Bonds: TLT, IEF, LQD, HYG
- Commodities: DBC, USO
- Gold: GLD
- REITs: VNQ
- Cash / risk-off proxy: SHY

### Engine B - ALPHA / the gamble: cross-sectional ML on a broad liquid equity universe (small/mid-cap tilt)

Rank a broad liquid universe (Russell 1000 down into liquid small/mid-caps, NOT microcaps at this capital) by forward return using gradient-boosted / neural models over a wide factor set: momentum, value, quality, low-vol, size, post-earnings-announcement drift / earnings-surprise, liquidity. The **LLM-as-feature-extractor** layer lives here as ONE feature group whose marginal information coefficient is measured against a mechanical baseline, never as the predictor. Run concentrated long, or long-short, per the aggressive mandate (~50-150 names).

**Honest assessment of B:** the literature shows cross-sectional ML equity alpha concentrates in microcaps and decays ~57% net of costs in liquid large-caps. At $500k+ we can't fully fish the microcap tail, so Engine B's net edge is genuinely uncertain. The kill rule adjudicates it. Engine A is the high-probability anchor that carries the program if B fails.

### Program expectation

Realistic: Sharpe ~0.7-1.2, drawdowns 25-35%. A solid systematic program with losing years, not a money printer.

## 5. Validation discipline (build before any strategy)

1. **Point-in-time everything** - features stamped with the time they were knowable; as-reported (not restated) fundamentals; publish-time stamps; survivorship-corrected universes (include delisted/acquired names).
2. **Purged, embargoed walk-forward cross-validation** - train past → test future; purge training samples whose label window overlaps the test fold; embargo gap so multi-day forward-return labels can't bleed backward.
3. **Mechanical baseline before ML/LLM** - prove each engine's harness is leak-free against a no-ML benchmark first. If a trend backtest looks too good, the harness is leaking; fix it before trusting any Engine B result.
4. **Hold-out touched once** - at the very end, after model and hyperparameters are frozen.
5. **Realistic costs** - model slippage, commissions, borrow per market; report net edge only.

## 6. Kill rule

The pre-committed thresholds live in `KILL_RULE.md` and were **locked by the operator on 2026-06-17**. No goalpost moves after seeing results.

## 7. Build sequence

- **P0 (this session):** scaffold - charter, kill rule, README, CLAUDE.md, repo skeleton, config files, git init. *(complete when committed)*
- **P1:** PIT data lake. ETF history is easy; the survivorship-corrected equity panel for Engine B is the hard, leak-prone part - defer it.
- **P2:** build Engine A first. Doubles as the leak-free-harness proof.
- **P3:** Engine B mechanical baseline.
- **P4:** add LLM features to B, measure marginal IC, apply the kill rule.
- **P5:** combine engines, cost/capacity model, paper trade, then small real money.

## 8. Data source

ETF price history: **Polygon** (split/dividend-adjusted daily bars, 15-20yr history), locked 2026-06-17. Key availability to LLM_Model3 to be confirmed on Godzilla before P1. Secrets via environment variables only; see `.env.example`.
