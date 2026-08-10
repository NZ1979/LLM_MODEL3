"""Engine B (P3) - point-in-time panel assembly (the timing layer).

This is the ONLY place that touches the trailing/forward time windows and the
ticker->permaticker attribution, so it is the leak-critical module. It reads the
four Sharadar parquets and emits one tidy cross-section row per
(rebalance_date T, permaticker), with every field computed as-of T:

  close_T        closeadj as-of (<=) T
  mktcap_T       daily.marketcap as-of (<=) T ($millions)
  mom_12_1       closeadj[T-21 mkt days] / closeadj[T-252 mkt days] - 1
  vol_252        stddev of the name's daily returns over its trailing 252 rows
  dollarvol_60   median(closeadj*volume) over the name's trailing 60 rows
  hist_days      count of the name's trading days <= T
  eps,bvps,gp,assets   dimension ART, latest datekey <= T (PIT filing join)
  category,exchange    from the securities master (for the universe screen)
  fwd_ret_21     closeadj[T+21 mkt days] / close_T - 1  (delisting-folded)
  fwd_status     'ok' | 'delisted_partial' | 'incomplete_window' | 'no_forward_price'

IDENTITY KEY IS permaticker. The price/daily/fundamentals tables are keyed by
the *ticker string*, which is recycled after delisting (BSC->ETN, SHLD->ETF), so
a row is attributed to the permaticker whose [firstpricedate, lastpricedate]
window contains that row's date. If any (ticker, date) maps to more than one
permaticker (overlapping windows), that is a survivorship-leak hazard and the
build FAILS LOUD (Rule 18/19) rather than silently grafting identities.

A name delisted before T (its last price date < T) is NOT in the universe at T
(the spec keeps a name for rebalances <= its delisting, not after).

Trailing windows (vol_252, dollarvol_60, hist_days) use the NAME's own trading
rows; the 12-1 momentum and the forward label use the MARKET calendar (distinct
trade dates across the panel) so a name's own gaps cannot shift the horizon.
All "value at T" reads are as-of (<=) joins, never forward.

Run on GODZILLA in the repo .venv (the panel parquet lives there; the sandbox is
firewalled and cannot read it). Requires duckdb. The synthetic tests exercise
this exact SQL on small in-memory tables and cross-check every field against an
independent pandas oracle (tests/test_engine_b_synthetic.py).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

try:
    import duckdb
except ImportError:  # pragma: no cover
    sys.exit("FAIL: duckdb not installed (pip install duckdb).")

MOM_SKIP = 21        # 12-1 momentum: skip most-recent 21 market days
MOM_LOOKBACK = 252   # ... measured back to 252 market days
VOL_WINDOW = 252     # trailing name-rows for realised vol
DOLLARVOL_WINDOW = 60  # trailing name-rows for median dollar volume
FWD_HORIZON = 21     # forward label horizon, market days

FUND_COLS = ("eps", "bvps", "gp", "assets")


def _fail(msg: str) -> None:
    sys.exit(f"FAIL: {msg}")


def _register_parquets(con, raw_dir: Path) -> None:
    raw = Path(raw_dir)
    need = {"tickers": raw / "tickers.parquet",
            "sep": raw / "sep_prices.parquet",
            "daily": raw / "daily.parquet",
            "fund": raw / "fundamentals.parquet"}
    for name, p in need.items():
        if not p.exists():
            _fail(f"missing panel parquet: {p}")
        posix = str(p).replace("\\", "/")
        con.execute(f"CREATE OR REPLACE VIEW {name}_raw AS "
                    f"SELECT * FROM read_parquet('{posix}')")


def _build(con, span_start: str, span_end: str, verbose: bool = True) -> pd.DataFrame:
    """Assemble the cross-section from views tickers_raw/sep_raw/daily_raw/fund_raw.

    span_start/span_end bound the REBALANCE dates (inclusive). Price/fundamental
    DATA outside the span is still used for trailing windows and to complete the
    forward label of the last in-span rebalances - that is data, not evaluation.
    """
    def log(*a):
        if verbose:
            print(*a)

    # --- securities master: identity + attribution windows -------------------
    con.execute("""
        CREATE OR REPLACE TEMP TABLE master AS
        SELECT permaticker, ticker,
               CAST(firstpricedate AS DATE) AS firstdate,
               CAST(lastpricedate  AS DATE) AS lastdate,
               category, exchange, isdelisted
        FROM tickers_raw
        WHERE ticker IS NOT NULL AND firstpricedate IS NOT NULL
              AND lastpricedate IS NOT NULL
    """)

    # --- ATTRIBUTION AMBIGUITY CHECK (the survivorship-leak tripwire) --------
    amb = con.execute("""
        SELECT count(*) FROM (
            SELECT s.ticker, s.date
            FROM sep_raw s
            JOIN master m ON s.ticker = m.ticker
                         AND s.date BETWEEN m.firstdate AND m.lastdate
            GROUP BY 1, 2
            HAVING count(*) > 1
        )
    """).fetchone()[0]
    if amb and amb > 0:
        _fail(f"attribution ambiguity: {amb} (ticker,date) pairs map to >1 "
              f"permaticker (overlapping firstpricedate/lastpricedate windows). "
              f"Survivorship-leak hazard - refusing to graft identities.")
    log("  attribution: 0 ambiguous (ticker,date) pairs [OK]")

    # --- attributed price panel; per-name seq + daily return (pass 1) --------
    con.execute("""
        CREATE OR REPLACE TEMP TABLE px AS
        SELECT m.permaticker, s.date, s.closeadj, s.volume
        FROM sep_raw s
        JOIN master m ON s.ticker = m.ticker
                     AND s.date BETWEEN m.firstdate AND m.lastdate
        WHERE s.closeadj IS NOT NULL
    """)
    con.execute("""
        CREATE OR REPLACE TEMP TABLE px_ret AS
        SELECT permaticker, date, closeadj, volume,
               row_number() OVER w AS seq,
               closeadj / lag(closeadj) OVER w - 1 AS ret
        FROM px
        WINDOW w AS (PARTITION BY permaticker ORDER BY date)
    """)
    # pass 2: rolling vol (std of returns) as a scalar window (cheap). The
    # trailing-60 median dollar-volume is computed later at the as-of-T rows only
    # (a bounded seq range-join), NOT as a 60-wide array_agg window over the full
    # 46M-row panel - that would materialise ~46M lists and can exhaust memory.
    con.execute(f"""
        CREATE OR REPLACE TEMP TABLE pxseq AS
        SELECT permaticker, date, closeadj, volume, seq, ret,
               closeadj * volume AS dv,
               stddev_samp(ret) OVER (
                   PARTITION BY permaticker ORDER BY date
                   ROWS BETWEEN {VOL_WINDOW - 1} PRECEDING AND CURRENT ROW) AS vol_252
        FROM px_ret
    """)

    # --- market calendar + rebalance dates (last market day per month) -------
    con.execute("""
        CREATE OR REPLACE TEMP TABLE cal AS
        SELECT cal_date, row_number() OVER (ORDER BY cal_date) AS idx
        FROM (SELECT DISTINCT date AS cal_date FROM px)
    """)
    con.execute(f"""
        CREATE OR REPLACE TEMP TABLE rebal AS
        SELECT cal_date AS T, idx AS idx_T
        FROM cal
        WHERE (date_trunc('month', cal_date), cal_date) IN (
                  SELECT date_trunc('month', cal_date), max(cal_date)
                  FROM cal GROUP BY 1)
          AND cal_date BETWEEN DATE '{span_start}' AND DATE '{span_end}'
    """)
    nreb = con.execute("SELECT count(*) FROM rebal").fetchone()[0]
    if nreb == 0:
        _fail(f"no rebalance dates in [{span_start}, {span_end}] - empty span.")
    log(f"  rebalance dates in span: {nreb}")

    # anchor dates from the market calendar (T-21, T-252, T+21)
    con.execute(f"""
        CREATE OR REPLACE TEMP TABLE anchors AS
        SELECT r.T, r.idx_T,
               c1.cal_date AS d_m21,
               c2.cal_date AS d_m252,
               c3.cal_date AS d_p21
        FROM rebal r
        LEFT JOIN cal c1 ON c1.idx = r.idx_T - {MOM_SKIP}
        LEFT JOIN cal c2 ON c2.idx = r.idx_T - {MOM_LOOKBACK}
        LEFT JOIN cal c3 ON c3.idx = r.idx_T + {FWD_HORIZON}
    """)

    # --- per (permaticker, T): as-of-T price row ----------------------------
    con.execute("""
        CREATE OR REPLACE TEMP TABLE feat_T AS
        SELECT probe.T, probe.idx_T, probe.permaticker, p.date AS asof_date,
               p.closeadj AS close_T, p.seq AS hist_days, p.vol_252
        FROM (SELECT r.T, r.idx_T, n.permaticker
              FROM rebal r CROSS JOIN (SELECT DISTINCT permaticker FROM pxseq) n) probe
        ASOF JOIN pxseq p
             ON p.permaticker = probe.permaticker AND p.date <= probe.T
    """)

    # trailing-60-row median dollar volume, at the as-of-T rows only (bounded)
    con.execute(f"""
        CREATE OR REPLACE TEMP TABLE dollarvol_T AS
        SELECT f.T, f.permaticker, median(p.dv) AS dollarvol_60
        FROM feat_T f
        JOIN pxseq p ON p.permaticker = f.permaticker
                    AND p.seq BETWEEN f.hist_days - {DOLLARVOL_WINDOW - 1} AND f.hist_days
        GROUP BY f.T, f.permaticker
    """)

    # momentum anchor prices (as-of the market-day anchors)
    for col, dcol in (("c_m21", "d_m21"), ("c_m252", "d_m252"), ("c_p21", "d_p21")):
        con.execute(f"""
            CREATE OR REPLACE TEMP TABLE tmp_{col} AS
            SELECT probe.T, probe.permaticker,
                   p.closeadj AS {col}, p.date AS {col}_date
            FROM (SELECT f.T, f.permaticker, a.{dcol} AS anchor_date
                  FROM feat_T f JOIN anchors a ON a.T = f.T) probe
            ASOF JOIN pxseq p
                 ON p.permaticker = probe.permaticker AND p.date <= probe.anchor_date
        """)

    # marketcap as-of T (attributed from daily, same window logic)
    con.execute("""
        CREATE OR REPLACE TEMP TABLE daily_attr AS
        SELECT m.permaticker, d.date, d.marketcap
        FROM daily_raw d
        JOIN master m ON d.ticker = m.ticker
                     AND d.date BETWEEN m.firstdate AND m.lastdate
        WHERE d.marketcap IS NOT NULL
    """)
    con.execute("""
        CREATE OR REPLACE TEMP TABLE mc_T AS
        SELECT f.T, f.permaticker, p.marketcap AS mktcap_T
        FROM feat_T f
        ASOF JOIN daily_attr p
             ON p.permaticker = f.permaticker AND p.date <= f.T
    """)

    # fundamentals ART, latest datekey <= T (the PIT filing join)
    con.execute("""
        CREATE OR REPLACE TEMP TABLE fund_attr AS
        SELECT m.permaticker, CAST(fr.datekey AS DATE) AS datekey,
               fr.eps, fr.bvps, fr.gp, fr.assets
        FROM fund_raw fr
        JOIN master m ON fr.ticker = m.ticker
                     AND CAST(fr.datekey AS DATE) BETWEEN m.firstdate AND m.lastdate
        WHERE fr.dimension = 'ART'
    """)
    con.execute("""
        CREATE OR REPLACE TEMP TABLE fund_T AS
        SELECT f.T, f.permaticker, p.datekey AS fund_datekey,
               p.eps, p.bvps, p.gp, p.assets
        FROM feat_T f
        ASOF JOIN fund_attr p
             ON p.permaticker = f.permaticker AND p.datekey <= f.T
    """)

    # securities master fields + delisting date (one row per permaticker)
    con.execute("""
        CREATE OR REPLACE TEMP TABLE meta AS
        SELECT permaticker, any_value(category) AS category,
               any_value(exchange) AS exchange,
               max(lastdate) AS lastdate, any_value(isdelisted) AS isdelisted
        FROM master GROUP BY permaticker
    """)

    # --- assemble; drop names already delisted before T (T > lastdate) -------
    df = con.execute("""
        SELECT f.T AS date, f.permaticker,
               f.close_T, f.hist_days, f.vol_252, dv.dollarvol_60,
               mc.mktcap_T,
               m21.c_m21, m252.c_m252, p21.c_p21, p21.c_p21_date,
               a.d_p21,
               fu.eps, fu.bvps, fu.gp, fu.assets,
               me.category, me.exchange, me.lastdate, me.isdelisted
        FROM feat_T f
        JOIN anchors a ON a.T = f.T
        JOIN meta me ON me.permaticker = f.permaticker
        LEFT JOIN dollarvol_T dv ON dv.T = f.T AND dv.permaticker = f.permaticker
        LEFT JOIN tmp_c_m21  m21  ON m21.T = f.T AND m21.permaticker = f.permaticker
        LEFT JOIN tmp_c_m252 m252 ON m252.T = f.T AND m252.permaticker = f.permaticker
        LEFT JOIN tmp_c_p21  p21  ON p21.T = f.T AND p21.permaticker = f.permaticker
        LEFT JOIN mc_T   mc ON mc.T = f.T AND mc.permaticker = f.permaticker
        LEFT JOIN fund_T fu ON fu.T = f.T AND fu.permaticker = f.permaticker
        WHERE f.T <= me.lastdate
    """).fetchdf()

    # momentum (12-1)
    df["mom_12_1"] = df["c_m21"] / df["c_m252"] - 1.0

    # --- forward label with delisting fold + status (pandas, for clarity) ----
    horizon_exists = df["d_p21"].notna()               # T+21 market day inside panel
    fwd = df["c_p21"] / df["close_T"] - 1.0
    status = pd.Series("ok", index=df.index)

    # name delisted at/inside the forward window -> as-of gives last price (fold)
    delisted_partial = df["lastdate"].notna() & horizon_exists & (df["lastdate"] < df["d_p21"])
    status = status.mask(delisted_partial, "delisted_partial")

    # forward horizon runs past the panel end for a still-live name -> no label
    incomplete = ~horizon_exists
    fwd = fwd.mask(incomplete)
    status = status.mask(incomplete, "incomplete_window")

    # live name but forward as-of price fell back to T's own bar (no forward
    # trade though the horizon exists) -> unusable, exclude and count
    stuck = horizon_exists & (df["c_p21_date"] == df["date"]) & ~delisted_partial
    fwd = fwd.mask(stuck)
    status = status.mask(stuck, "no_forward_price")

    df["fwd_ret_21"] = fwd
    df["fwd_status"] = status

    keep = ["date", "permaticker", "close_T", "mktcap_T", "dollarvol_60",
            "hist_days", "mom_12_1", "vol_252", *FUND_COLS,
            "category", "exchange", "fwd_ret_21", "fwd_status"]
    out = df[keep].sort_values(["date", "permaticker"]).reset_index(drop=True)
    log(f"  cross-section rows: {len(out):,} over {out['date'].nunique()} rebalances")
    return out


def build_panel_from_parquet(raw_dir, span_start: str, span_end: str,
                             verbose: bool = True) -> pd.DataFrame:
    """Open DuckDB, read the four Sharadar parquets, assemble the cross-section."""
    con = duckdb.connect()
    con.execute("PRAGMA threads=4")
    try:
        _register_parquets(con, raw_dir)
        return _build(con, span_start, span_end, verbose=verbose)
    finally:
        con.close()
