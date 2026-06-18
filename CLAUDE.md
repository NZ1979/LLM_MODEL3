# CLAUDE.md - LLM_Model3

Guidance for any agent session working in this repository. Read `CLAUDE_PREFLIGHT.md` (the operational rulebook - 33 numbered rules, non-negotiable), `PROJECT_CHARTER.md`, and `KILL_RULE.md` before any operational step.

## What this project is

A systematic equities/ETF research program with two low-correlation engines (Engine A: multi-asset ETF trend following; Engine B: cross-sectional ML equity ranker). Edge is measured on history before risking time or capital. **The LLM is never the predictor** - only a feature extractor whose marginal information coefficient is measured against a mechanical baseline. Full design is in `PROJECT_CHARTER.md`; this file is operating posture and partition rules.

## Session anchors - verify at the start of every session

State these back before recommending any command or edit:

1. **Date/time** - run `date && TZ=America/Denver date` and quote the verified Mountain time. Session env headers drift; don't trust remembered framing.
2. **Working directory** - confirm it is `C:\trading\LLM_MODEL3` (NOT `LLM_SWING_MODEL`, NOT `LLM model`).
3. **Workstation** - Godzilla, in Albuquerque NM (America/Denver). A sandbox hostname is not proof of the workstation; tag as ASSUMED if you can't verify on the box.

## Partition discipline (hard rule)

LLM_Model3 is operationally isolated from two siblings on Godzilla:

- `C:\trading\LLM_SWING_MODEL\` - separate LLM-catalyst swing project (paper). No shared DB, no executing its scripts, no importing its code.
- `C:\trading\LLM model\` - legacy intraday archive, read-only. No cross-folder DB access, no cross-folder script execution, no shared git history.

The design docs at `LLM_SWING_MODEL\docs\LLM_Model3_CHARTER_PROPOSAL.md` and `...\LLM_Model3_EDGE_DESIGN.md` may be **read** for reference but **not** imported as code. `PROJECT_CHARTER.md` in this repo is the source of truth; conflicts resolve in its favor.

Tripwire strings - their appearance in a command means a partition check before sending: `LLM_SWING_MODEL`, `LLM model`, any DB path or script path outside `C:\trading\LLM_MODEL3\`.

## Operating posture (inherited, enforced)

The full rulebook is `CLAUDE_PREFLIGHT.md` (33 numbered rules ported from the swing model and re-anchored to LLM_Model3). The items below are the loud-and-visible subset so they can't be skipped because the file wasn't opened.


- **Honesty tagging.** Prefix factual/operational claims with `VERIFIED [source]`, `INFERRED [basis]`, or `ASSUMED`. Untagged state claims are violations.
- **Fail loud, never fake.** No placeholder/synthetic data passed off as real. Surface gaps as visible errors, not silent degradation. Priority: works on real data > visible fallback with a banner > clear error > (never) silent fake-fine.
- **Don't declare victory prematurely.** `py_compile`/tests passing ≠ done. "Works" requires end-to-end evidence shown to the operator. When a command's output determines the next step, emit that command and **stop** - wait for the operator to paste results.
- **Verify before generating operational artifacts.** Read real column names, function signatures, and paths before writing code or commands against them.
- **No leakage, ever.** Point-in-time features, purged+embargoed walk-forward, mechanical baseline before any ML/LLM, hold-out touched once, realistic costs. A too-good backtest is assumed leaking until proven otherwise. See `PROJECT_CHARTER.md` §5.
- **No real money** until an engine clears `KILL_RULE.md` AND survives paper trading. Paper/backtest only by default.
- **Kill rule is locked.** No goalpost moves. Changes require a dated operator decision in `KILL_RULE.md`.

## Git durability

Code on disk is not shipped. Before any session wrap, the operator commits and pushes from PowerShell on Godzilla (agents do not run git from a sandbox). A wrap may not use "done/shipped/complete" until the push lands. Accurate interim framing: "code on disk, NOT yet committed."

## Secrets

Environment variables only - never in tracked files. `.env` is gitignored; `.env.example` is the template. ETF data source is Polygon (key via env).

## Conventions

- Times in any schedule/config are America/Denver unless stated; handle DST.
- Python: use the repo `.venv`. Dependencies in `requirements.txt`.
- Build sequence is P0→P5 (see `PROJECT_CHARTER.md` §7). Don't build strategy logic ahead of the sequence.
- **Engine A focus (operator directive 2026-06-17):** do not build or discuss Engine B (cross-sectional ML, equity panel, Norgate, LLM features) until Engine A is built, run, and adjudicated by the kill rule. Keep all attention on Engine A until then.
