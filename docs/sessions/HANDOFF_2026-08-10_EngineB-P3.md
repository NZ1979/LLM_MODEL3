# LLM_Model3 - Session Handoff, 2026-08-10 (Engine B / P3 kickoff)

Workstation Godzilla (Albuquerque, America/Denver). Working dir
`C:\trading\LLM_MODEL3`. Paper/backtest only; no paper trading running. Partition
hard-rule held: no access to `C:\trading\LLM_SWING_MODEL\` or `C:\trading\LLM model\`;
no DB/script/code/git crossing. (Second session of 2026-08-10; the earlier one
closed Engine A - see `HANDOFF_2026-08-10.md`.)

## What this session did

Opened **Engine B (P3)** and completed the hard, leak-prone data foundation end to
end: chose and validated the panel source, ingested the full survivorship-free
point-in-time panel, and pre-registered the mechanical baseline. Three clean
commits, all pushed. No modelling result has been computed on the panel.

### 1. Panel data source: Sharadar Direct (chosen over Norgate)

Norgate was the standing candidate but was **rejected**: its fundamentals are a
current snapshot only, not historical point-in-time - unusable for a cross-sectional
value/quality ranker. **Sharadar SF1** is genuinely PIT (as-reported dims stamped
with the SEC filing date), survivorship-free (~18k active+delisted), back to 1998
(fundamentals to 1990). Sharadar now sells **direct** at sharadar.com (own REST API,
launched July 2026), pricing gated by history depth: full-history Bundle **$69/mo or
$499/yr**. `SHARADAR_API_KEY` in `.env`. Personal Use License - revisit before real
money.

### 2. Smoke test: PASSED decisively

- Survivorship: 21,960 equity permatickers, **15,638 delisted vs 6,322 active** (71%
  delisted = genuinely survivorship-free). 10/10 known failures present by company
  name with correct dates (Lehman/Bear Stearns/WaMu/Enron/WorldCom/SVB/First
  Republic/Signature/Sears/Countrywide). Lehman prices 2715 bars to 2008-10-15.
- PIT: fundamentals filing-lag positive (median ~34-44 days). Factor fields 22/22
  present.
- **Key finding - ticker recycling:** BSC now resolves to an ETN, SHLD to an ETF,
  BBBY to a new entity. **Identity key MUST be `permaticker`, never the ticker
  string**, or a delisted company's identity grafts onto its successor (a
  survivorship leak). This is locked into the spec and the code.

### 3. Full panel ingested (`data/raw/sharadar/*.parquet`, + `_*_metadata.json`)

Bulk contract: `{endpoint}?years=full` -> 302 -> signed DO Spaces URL -> a **ZIP**
(not gzip) of the table CSV. Streamed to temp, unzipped, converted to parquet with
**DuckDB** (whole-file type detection - needed because sparse fundamentals columns
trip streaming inference). All integrity-checked, fail-loud.

| file | rows | span | size |
|---|---|---|---|
| tickers.parquet | 21,960 permatickers | - | 0.87 MB |
| daily.parquet | 40,042,833 | 1998-12-01 .. 2026-08-07 | 650 MB |
| sep_prices.parquet | 46,256,784 | 1997-12-31 .. 2026-08-10 | 1094 MB |
| fundamentals.parquet | 3,212,204 (112 cols) | datekey 1990-06-06 .. 2026-08-10 | 660 MB |

**Gotcha:** bulk fundamentals filing-date column is `datekey`; the *query* API
renames the same field `date`. Use `datekey` on the bulk parquet. Dims present:
ARQ/ART/ARY/MRQ/MRT/MRY. `roe/roa/roic` are null in ARQ (averaged denominators
absent) -> use **ART** for quality ratios.

### 4. Mechanical baseline pre-registered, unrun

`docs/ENGINE_B_BASELINE_SPEC.md`, committed with **no results** (verified by git log
- the commit contains only the spec). Fixes, a priori: the PIT universe (Domestic
Common Stock, NYSE/NASDAQ/NYSEMKT, marketcap $300M-$15B, 60d median dollar-vol
>=$5M, price >=$5, >=252d history, delisted names kept while alive); monthly
rebalance; 21-day forward-return label with delisting returns folded in; five
equal-weight factors (12-1 momentum, value = EY+B/P, quality = gross profitability,
low-vol, size), no fitted weights; ART fundamentals joined by `datekey <= T`; 10
bps/side slippage; purged/embargoed walk-forward; **hold-out 2021+ touched once**,
build/audit on 1998-2020; metrics per `KILL_RULE.md` (OOS rank-IC>0, monotonic
decile Sharpe). Long-only top-decile is the tradeable form (avoids the
shorting/financing costs that sank Engine A); long-short spread is diagnostic only.

## State as of end of session

Engine A: CLOSED (prior session). Engine B: **panel complete and integrity-checked;
mechanical baseline spec pre-registered and committed unrun.** Nothing modelled yet.

## Commits this session (all pushed to origin/main, NZ1979/LLM_MODEL3)

- `cda1d59` - P3 foundation: sharadar_client, tickers master ingest, smoke-test probes
- `ee497f7` - bulk-ingest full panel (daily/SEP/fundamentals) + duckdb dep + datekey fix
- `87fb732` - pre-register mechanical baseline + PIT universe spec (no results)

Working tree clean, up to date with origin/main. Panel parquet is on disk and
**gitignored** (regenerable via the ingest scripts).

## Repo map (added this session)

`data/sharadar_client.py` (reusable: load_key/fetch/paginate/safe_url),
`scripts/ingest_sharadar.py` (Phase 1 tickers + bulk probe),
`scripts/ingest_sharadar_bulk.py` (bulk zip->DuckDB->parquet, fail-loud),
`scripts/fix_fundamentals.py` (datekey revalidation),
`scripts/probe_sharadar.py`, `scripts/probe_sharadar_delisted.py` (smoke tests),
`docs/ENGINE_B_BASELINE_SPEC.md`. `requirements.txt` gained `duckdb`.

## What is NOT done - next session's work

Build the baseline **implementation** per the locked spec, then the single measuring
run:

1. **Universe screen** (PIT eligibility from tickers/daily/sep, permaticker-keyed).
2. **Factor computation** (the five factors; datekey<=T join; ART dim; cross-sectional
   winsorise+z-score within each date's universe).
3. **Walk-forward harness** (rank-IC + Newey-West t, decile Sharpe monotonicity,
   long-only top-decile net of cost; long-short spread diagnostic).
4. **Test against SYNTHETIC data only** so performance is unobserved until the code is
   committed - the A-2 discipline. Then commit the implementation.
5. **One measuring run** on **1998-2020**. Hold-out **2021+ touched once**, at the end,
   after the harness is frozen.

Leak audit is the whole point: a too-good IC (>~0.10 monthly, or a perfect decile
staircase) is assumed leaking until the harness is proven - audit before trusting
(charter §5.3, Rule 14). Expected honest result: mean monthly rank-IC ~0.02-0.05,
roughly monotonic decile Sharpe.

## Verification performed

- All ingest/client/probe code compiled and mock-tested in the sandbox before running
  on Godzilla (key-load edge cases, redaction, pagination, parquet round-trip,
  fail-loud->SUSPECT, sparse-column typing, download stream). Keys never printed.
- Panel integrity checks passed on the real pulls (row counts, non-null keys, date
  ranges, survivorship ratio). Fundamentals promoted only after datekey revalidation
  (PIT lag positive).
- Each commit verified landed via `git log` (HEAD == origin/main), not push output.

## Process notes worth carrying forward

- Data pulls run on **Godzilla `.venv`**, never the Cowork sandbox (sandbox is
  firewalled from external market APIs, 403).
- Sharadar `api_key` rides in the URL -> scripts suppress URL logging and redact any
  printed URL (Rule 22).
- `.env` belongs in `C:\trading\LLM_MODEL3\` (a key was briefly pasted into the
  partitioned `C:\trading\LLM model\` sibling and moved - watch the folder).

## Ready-to-paste kickoff prompt for the next session

Continue LLM_Model3 at `C:\trading\LLM_MODEL3` on Godzilla (America/Denver). Verify
anchors (`date && TZ=America/Denver date`; working dir; workstation) and re-read
`CLAUDE.md`, `CLAUDE_PREFLIGHT.md`, `PROJECT_CHARTER.md`, `KILL_RULE.md`. Partition
hard-rule holds: no access to `C:\trading\LLM_SWING_MODEL\` or `C:\trading\LLM model\`.

State as of 2026-08-10: Engine A is CLOSED. Engine B (P3) panel is COMPLETE and
integrity-checked in `data/raw/sharadar/*.parquet` (tickers 21,960; daily 40.0M
1998+; sep_prices 46.3M 1997+; fundamentals 3.2M 1990+, dims ARQ/ART/etc). The
mechanical-baseline + PIT-universe spec is PRE-REGISTERED and committed unrun at
`docs/ENGINE_B_BASELINE_SPEC.md` (commit 87fb732). Identity key is `permaticker`
(ticker recycling); fundamentals filing date is `datekey` on the bulk parquet; use
ART for roe/roa/roic; pulls run on Godzilla `.venv` (sandbox firewalled); duckdb is a
dependency.

This session builds the baseline IMPLEMENTATION per the locked spec, in this order:
(1) PIT universe screen; (2) five-factor computation (datekey<=T join, ART dim,
cross-sectional winsorise+z-score); (3) walk-forward harness (rank-IC + Newey-West t,
decile Sharpe monotonicity, long-only top-decile net of 10 bps/side, long-short
diagnostic). Test against SYNTHETIC data only and commit the implementation BEFORE
any measuring run (the A-2 discipline). Then ONE measuring run on 1998-2020; hold-out
2021+ is touched once, at the very end, after the harness is frozen. A too-good IC is
assumed leaking until the harness is proven (charter §5.3). Keep the posture:
pre-register anything choosable-after-results, commit unrun, verify commits with git
log, fail loud, no premature victory, git from PowerShell on Godzilla.
