# KILL_RULE.md — LLM_Model3

**Pre-committed. Written before any result. No goalpost moves after seeing results.**

Status: **LOCKED by operator on 2026-06-17.** (Proposed thresholds were approved as written. Any change from here requires an explicit, dated operator decision recorded in this file's changelog, and invalidates results computed under the prior bar.)

These thresholds exist so the program has a bounded effort budget and cannot be rescued by retroactive rationalization. The failure mode they prevent: tuning parameters against a handful of trades, redefining "success" downward after a disappointing backtest, and running a no-edge strategy on hope.

## Engine A — multi-asset trend following (ETFs)

**Ships iff**, over a correctly purged/embargoed walk-forward:

- Net-of-cost out-of-sample **Sharpe ≥ 0.4**, AND
- **Positive in a clear majority of rolling walk-forward windows.**

Judge trend by net OOS Sharpe + consistency across windows — **not** by decile monotonicity (that test is for the cross-sectional ranker, not a time-series trend system).

## Engine B — cross-sectional ML equity ranker

**Ships iff**, net of costs, out-of-sample:

- **IC > 0**, AND
- **Monotonic Sharpe-by-prediction-decile**, AND
- The **baseline+LLM model's IC exceeds the mechanical-baseline IC by a statistically distinguishable margin of ≥20% relative.**

If the baseline+LLM delta over the mechanical baseline is **statistically indistinguishable**, the LLM adds nothing and **that layer is dropped** — Engine B then stands or falls on the mechanical baseline alone.

## Project-level

**Pivot or stop the project if, after a clean walk-forward, neither engine clears its bar.**

## Guardrails on interpreting these

- "Net of cost" means after modeled slippage, commissions, and (for any short leg) borrow. Gross-only results do not count toward any threshold.
- "Out-of-sample" means produced by the purged/embargoed walk-forward harness, or the once-touched hold-out. In-sample or leaky numbers do not count.
- A backtest that looks too good is assumed leaking until the harness is proven otherwise.
- The hold-out set is touched **once**, after model and hyperparameters are frozen.

## Changelog

- 2026-06-17 — Thresholds locked by operator as proposed (Engine A Sharpe ≥0.4 + majority positive windows; Engine B positive IC + monotonic decile Sharpe + ≥20% relative IC over mechanical baseline; project stop if neither clears). No prior versions.
