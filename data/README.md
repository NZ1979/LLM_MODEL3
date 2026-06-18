# data/ - point-in-time data lake

Holds all market data, stored so every value is stamped with the time it was **knowable**. No restated fundamentals, no survivorship bias, no look-ahead.

## Contents (built in P1)

- **ETF daily history** (easy): corporate-action-adjusted daily bars for the ~22-ETF Engine A universe from **Tiingo** (30+ yr). Polygon's plan caps at 5 yr, so Tiingo is the deep-history source for Engine A; see charter §8.
- **Survivorship-corrected equity panel** (hard, leak-prone - deferred to P3): the Engine B universe including delisted/acquired names, with as-reported (not restated) fundamentals and publish-time stamps. Source TBD at P3 (Norgate Data is the leading candidate; see charter §8).

## Rules

- Point-in-time everything. A feature may only use data available at its timestamp.
- Raw vendor pulls are immutable; derived/cleaned artifacts are separate and reproducible.
- Data artifacts are gitignored. This folder holds loaders, schemas, and docs - not large binaries.
- Secrets (Polygon key) come from environment variables, never committed.
