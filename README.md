# LLM_Model3

Systematic equities/ETF research program. Two low-correlation engines, each backtested independently, both gated by a pre-committed kill rule. The design exists so **edge is measured on history before time or capital is risked**, and so the LLM is never the predictor - only a feature extractor whose marginal value is measured.

Workstation: Godzilla (Albuquerque, NM / America/Denver). Paper/backtest only by default.

## Read order

1. `PROJECT_CHARTER.md` - why this exists, partition, locked constraints, two-engine design, validation discipline, build sequence. **Start here.**
2. `KILL_RULE.md` - the pre-committed, locked ship/stop thresholds.
3. `CLAUDE_PREFLIGHT.md` - the operational rulebook: 33 numbered rules (credential handling, verification-before-conclusion, fail-loud, session anchors, partition discipline, durability). Non-negotiable.
4. `CLAUDE.md` - operating posture and partition rules for future agent sessions.
5. This file - repo map.

## Repo map

| Path | Purpose |
|------|---------|
| `PROJECT_CHARTER.md` | Source-of-truth design document. |
| `KILL_RULE.md` | Locked ship/stop thresholds for Engine A and Engine B. |
| `CLAUDE_PREFLIGHT.md` | Operational rulebook - 33 numbered rules. |
| `CLAUDE.md` | Context + operating posture + partition rules for agent sessions. |
| `data/` | Point-in-time data lake. ETF history (P1, easy) and the survivorship-corrected equity panel (P1, hard - deferred). |
| `features/` | Feature engineering. PIT-stamped factors; the LLM feature group lives here as one input to Engine B. |
| `models/` | Engine A trend system and Engine B cross-sectional ranker. |
| `validation/` | Purged/embargoed walk-forward harness, mechanical baselines, cost models. The leak-prevention core. |
| `research/` | Notebooks, scratch analysis, experiment logs. Nothing here is load-bearing for production. |
| `.env.example` | Template for required environment variables (secrets via env only). |
| `requirements.txt` | Python dependencies. |
| `.gitignore` | Excludes secrets, data artifacts, caches. |

## Build sequence

P0 scaffold (this) → P1 PIT data lake → P2 Engine A (also proves the harness is leak-free) → P3 Engine B mechanical baseline → P4 add LLM features to B + measure marginal IC + apply kill rule → P5 combine, cost/capacity model, paper, then small real money.

## Partition

Isolated from `C:\trading\LLM_SWING_MODEL\` (separate project) and `C:\trading\LLM model\` (legacy archive, read-only). No cross-folder DB access, script execution, or shared git history. See `PROJECT_CHARTER.md` §2.

## Setup (once)

```powershell
# from C:\trading\LLM_MODEL3
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env   # then fill in real keys; .env is gitignored
```
