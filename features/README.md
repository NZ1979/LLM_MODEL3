# features/ — feature engineering

Transforms PIT data into model inputs. Every feature is stamped with the time it was knowable; nothing here may peek forward.

## Scope

- **Engine A:** multi-timeframe trend signals, realized volatility (for vol-targeting), correlation estimates (for inverse-correlation weighting).
- **Engine B factor groups:** momentum, value, quality, low-vol, size, post-earnings-announcement drift / earnings-surprise, liquidity.
- **LLM feature group:** lives here as ONE input group for Engine B. Its marginal information coefficient is measured against the mechanical baseline (see `KILL_RULE.md`). It is never the predictor.

## Rules

- A feature's timestamp is the moment its inputs were all knowable, not the moment the underlying event occurred.
- Each feature is defined once, reused by baseline and model alike, so the baseline-vs-LLM comparison is apples-to-apples.
