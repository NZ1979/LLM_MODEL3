# scripts/ - verifiers and one-off utilities

Standalone scripts for probing data sources, verifying setup, and one-off data tasks. Not part of the engine code paths.

- `probe_polygon.py` - confirms the Polygon key works, how far back the plan returns adjusted daily ETF bars, and the exact response field names. Stdlib only; run on Godzilla (the Cowork sandbox is firewalled off polygon.io). Never logs the key or request URL (preflight Rule 22).

Rule: scripts that hit Polygon run on Godzilla, not in the sandbox. Anything reading credentials uses `.env` via environment, never hardcoded.
