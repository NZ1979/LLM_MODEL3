# ENGINE_B_BASELINE_SPEC.md - Engine B mechanical cross-sectional baseline

**Pre-registered 2026-08-10 (America/Denver), Godzilla. NO RESULT COMPUTED UNDER
THIS SPEC EXISTS AT THE TIME OF THIS COMMIT.** This file fixes the point-in-time
universe, the mechanical factor baseline, the label, the walk-forward geometry,
the cost basis, and the pass/leakage conditions **before** any cross-sectional IC
or decile return has been computed on the Sharadar panel. If a later session
finds this file and a result under it in the same commit, the pre-registration is
void and the result must be discarded and re-run.

The panel it runs on was ingested and integrity-checked 2026-08-10
(`data/raw/sharadar/*.parquet`; see `[[llm-model3-engine-b-panel]]` and
`_*_metadata.json`). No modelling has touched it.

## Why this exists

Per `PROJECT_CHARTER.md` §5.3 and the build sequence (P3), **a mechanical baseline
must be built and measured before any ML or LLM layer.** Its job is not to be the
final strategy. Its job is to (a) prove the walk-forward harness is leak-free on
real cross-sectional equity data, and (b) establish the honest benchmark IC that
the LLM-as-feature layer (P4) must beat by >=20% relative, or be dropped, per
`KILL_RULE.md`. **The LLM is never the predictor** (charter §1).

The failure mode this guards against: dredging factor definitions, universe
thresholds, or the label horizon against the data, finding a combination with a
flattering IC, and reporting it as though it were one honest evaluation.
Everything below is fixed a priori. There are **no fitted parameters** in the
mechanical baseline - factor weights are equal, not optimised - so there is
nothing to tune post hoc.

## Data of record

- `data/raw/sharadar/tickers.parquet` - securities master, keyed on `permaticker`.
- `data/raw/sharadar/daily.parquet` - `marketcap` ($millions), valuation ratios; by `ticker,date`.
- `data/raw/sharadar/sep_prices.parquet` - OHLCV, `closeadj` (split+div adjusted); by `ticker,date`.
- `data/raw/sharadar/fundamentals.parquet` - SF1, 112 fields; by `ticker,dimension,datekey`.

**Identity key is `permaticker`, never the ticker string** (tickers are recycled
after delisting; keying on ticker grafts a dead company's identity onto its
successor - a survivorship leak proven on this panel: BSC->ETN, SHLD->ETF).

## The universe (point-in-time, reconstructed at each rebalance)

Membership at rebalance date T uses ONLY information knowable at T. A name is
eligible for month T iff, using data with effective date <= T:

1. **Security type:** `tickers.category` in {`Domestic Common Stock`,
   `Domestic Common Stock Primary Class`}. Excludes ADRs, preferred, warrants,
   secondary share classes (avoids double-counting one issuer), and funds.
2. **Listing:** `exchange` in {NYSE, NASDAQ, NYSEMKT}. Excludes OTC/pink.
3. **Size band:** `daily.marketcap` at T in **[$300M, $15B]**. Excludes microcaps
   (< $300M - capacity/quality; charter says not microcaps) and mega-caps
   (> $15B - where documented cross-sectional alpha decays net of costs, charter
   §4 "Honest assessment of B"). This is the "liquid small/mid" band.
4. **Liquidity:** trailing 60-trading-day median dollar volume
   (`closeadj * volume`) at T **>= $5M**. At $500k a 1-3% position is a small
   fraction of daily volume, so the book is executable.
5. **Price floor:** `closeadj` at T **>= $5** (excludes penny-stock microstructure
   noise and bid-ask-bounce pseudo-alpha that is not tradeable).
6. **History:** >= 252 trading days of price history before T (needed for the
   momentum and volatility factors). Names short of this are ineligible that month
   only, not dropped from the panel.

**Survivorship:** a name delisted at date D is in the universe for every rebalance
<= D and is NOT retroactively removed. Its delisting outcome enters the label
(below). The panel is 72% delisted names by design; excluding them is the leak.

## Rebalance and label

- **Rebalance:** monthly, on the last trading day of each calendar month.
- **Label:** forward 21-trading-day total return from `closeadj` (T -> T+21).
- **Delisting returns:** if a name delists inside the forward window, the label is
  the return to its last available `closeadj` (bankruptcies to ~0 are captured, not
  dropped). A name with no forward price and no recorded delisting return is
  excluded from that month's label set and the exclusion is counted and reported
  (Rule 18) - never silently filled.

## The mechanical baseline (no ML, no fitting)

At each rebalance T, over the eligible universe, compute five factor scores. Each
raw factor is cross-sectionally winsorised at +/-3 SD then z-scored **within that
date's universe** (no cross-date standardisation - no leakage across time):

1. **Momentum (12-1):** `closeadj` return from T-252 to T-21 (skip the last 21
   days to avoid short-term reversal contamination).
2. **Value:** equal-weight average of the z-scores of earnings yield
   (`eps`_ART / price) and book-to-price (`bvps`_ART / price). Fundamentals from
   dimension **ART** (as-reported trailing-twelve-month) with `datekey <= T`.
3. **Quality:** gross profitability = `gp`_ART / `assets`_ART (Novy-Marx), ART with
   `datekey <= T`. (ROE is null in ARQ because averaged denominators are absent;
   ART carries it - so quality uses ART throughout.)
4. **Low-volatility:** negative of trailing 252-day daily-return standard deviation
   (lower realised vol -> higher score; the low-vol anomaly).
5. **Size:** negative of ln(`marketcap`) at T (smaller -> higher score; residual
   size premium within the already-size-screened band).

**Composite score** = equal-weight mean of the five factor z-scores. Names are
ranked by the composite and bucketed into **deciles** (D10 = highest expected
return). Factor weights are equal and fixed; nothing is optimised.

## Fundamentals join - the point-in-time rule

For a name at T, the fundamentals row used is the one with the **latest
`datekey <= T`** (filing date), dimension ART. Never `calendardate` or
`reportperiod` (those are period-end dates, knowable only after the filing).
Verified on this panel: median ARQ filing lag `datekey - reportperiod` is ~44
days, so using period-end as-of would leak ~6 weeks of hindsight per quarter.

## Cost basis

Net-of-cost per `KILL_RULE.md` (gross-only numbers count toward nothing):

- **Slippage:** 10 bps/side on traded notional. Small/mid single names are less
  liquid than Engine A's ETFs (2 bps), so the assumption is deliberately higher.
- **Commissions:** 1 bp/side (modern near-zero, not literally zero).
- Cost is charged on realised turnover each rebalance. Sensitivity at 5 / 10 / 20
  bps/side is reported alongside, since a decile strategy's edge can be
  cost-sensitive.

## Evaluation and pre-registered conditions

Evaluated over the harness span with a **purged, embargoed** walk-forward; embargo
>= the 21-day label horizon so a label window cannot straddle the train/test
boundary. The mechanical baseline has no trained parameters, so every month is
effectively out-of-sample; the harness geometry is fixed now for when the ML layer
(P4) is added and does train.

- **Hold-out, touched once:** the most recent stretch **2021-01-01 -> present** is
  reserved and NOT examined while the baseline and harness are built. It is scored
  exactly once, after the mechanical spec is frozen (it already is, here). Build
  and leak-audit happen on **1998-2020**.

Metrics reported (all net of cost, out-of-sample):

1. **Rank-IC:** monthly cross-sectional Spearman correlation between composite rank
   at T and the T->T+21 return. Report mean IC, its Newey-West t-stat, and the IC
   time series. Kill-rule requirement: **IC > 0** and statistically distinguishable
   from zero.
2. **Decile monotonicity:** mean forward return and Sharpe by composite decile.
   Kill-rule requirement: **Sharpe rises monotonically (or near-monotonically)
   from D1 to D10.**
3. **Tradeable form:** an equal-weight **long-only top-decile** portfolio (matches
   the equities-only mandate and avoids the shorting/borrow/financing costs that
   made Engine A unimplementable), monthly rebalanced, net of cost. Report Sharpe,
   CAGR, max drawdown, turnover. The **long-short D10-D1 spread** is reported as a
   diagnostic only.

The `KILL_RULE.md` Engine B bar in full - IC > 0, monotonic decile Sharpe, AND the
baseline+LLM IC exceeding this mechanical IC by >= 20% relative and statistically
distinguishable - is adjudicated in P4. **This spec establishes only the mechanical
benchmark and proves the harness.** It does not by itself ship or kill Engine B.

## Anticipated outcome, recorded before the run

Recorded so a result that merely matches expectation cannot later be presented as
a discovery, and so a too-good result triggers a leak audit rather than a
celebration:

A standard equal-weight 5-factor composite on liquid US small/mid-caps, 1998-2026,
net of ~10 bps/side, is expected to produce a **small but positive** mean monthly
rank-IC, order **0.02-0.05**, with a **roughly (not perfectly) monotonic** decile
Sharpe. That is what the literature says survives in this liquid, non-microcap band
net of costs. Concretely:

- **IC > ~0.10 monthly, or a perfectly monotone high-Sharpe decile staircase =>
  assume leakage** (a look-ahead in the fundamentals join, a survivorship gap, or a
  label that peeks) and audit the harness before trusting anything (charter §5.3,
  Rule 14). A too-good backtest is leaking until proven otherwise.
- **IC ~0.02-0.05, noisy but positive =>** the harness is clean and the classic
  factors carry a modest edge here; this becomes the benchmark for the LLM layer.
- **IC ~0 or negative =>** the harness is clean but simple factors do not work net
  of cost in this universe; the LLM layer then faces a very high bar and Engine B
  most likely fails its kill rule. That is an acceptable, informative result.

## Failure handling, fixed in advance

- A **too-good** result is treated as a **leak to be found**, not an edge to be
  banked. Fix the harness, re-run.
- A **weak or negative** IC is **not** a licence to re-tune factor definitions, the
  universe band, the label horizon, or the cost assumptions to rescue it. Any such
  change requires a fresh, separately dated pre-registration stating why the
  original choice was wrong on grounds independent of its result.
- The hold-out (2021+) is touched **once**. If it is examined and then the spec is
  changed, the hold-out is burned and a new out-of-sample period must be found.

## Changelog

- 2026-08-10 - Created and pre-registered. Universe (type/listing/size/liquidity/
  price/history), rebalance, label, delisting-return handling, the five equal-weight
  factors, the PIT fundamentals join (datekey), cost basis, walk-forward geometry,
  hold-out period, metrics, anticipated outcome, and failure handling all fixed
  before any IC or decile return was computed on the panel. No result exists under
  this spec at commit time.
