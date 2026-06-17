# models/ — strategy logic

The two engines. Built only after the validation harness exists, in the order set by the build sequence.

## Engine A — multi-asset ETF trend following (P2)

Time-series trend momentum across the ~22-ETF basket, blended multi-timeframe, volatility-targeted positions, risk-parity weighting. Built first because it doubles as the leak-free-harness proof: trend following is the most replicated result in quant, so a clean harness should reproduce a modest positive net Sharpe. A too-good result means the harness is leaking.

## Engine B — cross-sectional ML equity ranker (P3 baseline, P4 LLM layer)

Ranks the liquid small/mid-cap universe by forward return. P3 builds the **mechanical baseline** (no ML/LLM). P4 adds the gradient-boosted/neural model and the LLM feature group, then measures marginal IC against the baseline and applies the kill rule. Concentrated long or long-short (~50–150 names) per the aggressive mandate.

## Combination (P5)

Vol-target each engine, weight by inverse correlation. Engine A is ballast; capital tilts toward B for upside.

## Rules

- No model is trusted until it clears the purged/embargoed walk-forward, net of costs.
- The LLM is a feature extractor, never the predictor. If its marginal IC is statistically indistinguishable from the baseline, the layer is dropped.
