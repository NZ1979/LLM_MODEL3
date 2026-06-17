# validation/ - the leak-prevention core

The harness that decides whether anything ships. Built before any strategy logic is trusted. If this is wrong, every downstream result is fiction, so this folder carries the most scrutiny in the repo.

## Components

- **Purged, embargoed walk-forward cross-validation.** Train past → test future. Purge training samples whose label window overlaps the test fold. Embargo gap so multi-day forward-return labels can't bleed backward into training.
- **Mechanical baselines.** A no-ML benchmark for each engine, used to prove the harness is leak-free before any ML/LLM result is believed, and as the comparison bar for Engine B's LLM layer.
- **Cost model.** Slippage, commissions, and borrow (for short legs). All reported edge is net of cost.
- **Hold-out protocol.** A final set touched exactly once, after model and hyperparameters are frozen.

## Rules

- A backtest that looks too good is assumed to be leaking until the harness is proven otherwise.
- Kill-rule metrics (Sharpe, IC, decile monotonicity, baseline delta) are computed here, from out-of-sample output only. See `KILL_RULE.md`.
- Gross-only or in-sample numbers never count toward a threshold.
