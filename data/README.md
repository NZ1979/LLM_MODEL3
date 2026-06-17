# data/ - point-in-time data lake

Holds all market data, stored so every value is stamped with the time it was **knowable**. No restated fundamentals, no survivorship bias, no look-ahead.

## Contents (built in P1)

- **ETF daily history** (easy): split/dividend-adjusted daily bars for the ~22-ETF Engine A universe from Polygon. 15-20+ years.
- **Survivorship-corrected equity panel** (hard, leak-prone - deferred): the Engine B universe including delisted/acquired names, with as-reported (not restated) fundamentals and publish-time stamps.

## Rules

- Point-in-time everything. A feature may only use data available at its timestamp.
- Raw vendor pulls are immutable; derived/cleaned artifacts are separate and reproducible.
- Data artifacts are gitignored. This folder holds loaders, schemas, and docs - not large binaries.
- Secrets (Polygon key) come from environment variables, never committed.
