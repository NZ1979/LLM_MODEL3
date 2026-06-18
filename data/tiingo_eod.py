"""Engine A ETF EOD ingestion - Tiingo -> point-in-time parquet data lake.

Run on Godzilla (network); the Cowork sandbox is firewalled off external APIs.

Pipeline per ticker:
  fetch_raw()  -> Tiingo daily/<ticker>/prices JSON (urllib, stdlib)
  normalize()  -> tidy pandas DataFrame, verified columns (see SCHEMA below)
  save()       -> data/raw/tiingo_eod/<TICKER>.parquet  (immutable raw vendor pull)

pull_universe() loops the locked ETF universe, writes one parquet per ticker, and
prints a FAIL-LOUD coverage report (per-ticker row counts + date ranges; any ticker
that errors or returns zero rows is listed and forces a non-zero exit). It also writes
_pull_metadata.json recording the UTC pull time per ticker (point-in-time provenance:
when each series was knowable to us).

SCHEMA (parquet columns), built against the Tiingo response verified 2026-06-17:
  ticker        str
  date          datetime64[ns]  (trading date, tz-naive, normalized to midnight)
  open high low close volume                 raw bars
  adj_open adj_high adj_low adj_close adj_volume   split+dividend adjusted (use for signals)
  div_cash      float   cash dividend on date
  split_factor  float   split factor on date

PIT note: Tiingo's adjusted series is back-adjusted, so the whole adj_* history
restates when a new corporate action lands. For trend signals computed on adjusted
*returns* this is correct and standard (returns between two dates stay accurate).
The raw o/h/l/c are kept alongside so nothing is lost. _pull_metadata.json stamps
when we pulled, so a backtest can reason about as-of provenance later.

Usage, in the Godzilla .venv (PowerShell), from C:\\trading\\LLM_MODEL3:
    .\\.venv\\Scripts\\Activate.ps1
    pip install -r requirements.txt        # first time: pandas, pyarrow
    python data\\tiingo_eod.py              # pull whole universe
    python data\\tiingo_eod.py SPY GLD      # pull specific tickers
"""
import datetime as dt
import json
import os
import sys
import time
import urllib.error
import urllib.request

import pandas as pd

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)
from config.universe import ETF_UNIVERSE, HISTORY_START  # noqa: E402

ENV_PATH = os.path.join(REPO_ROOT, ".env")
RAW_DIR = os.path.join(REPO_ROOT, "data", "raw", "tiingo_eod")
TIINGO_BASE = "https://api.tiingo.com/tiingo/daily"

# Tiingo raw field -> our parquet column
FIELD_MAP = {
    "open": "open", "high": "high", "low": "low", "close": "close", "volume": "volume",
    "adjOpen": "adj_open", "adjHigh": "adj_high", "adjLow": "adj_low",
    "adjClose": "adj_close", "adjVolume": "adj_volume",
    "divCash": "div_cash", "splitFactor": "split_factor",
}
COLUMNS = ["ticker", "date"] + list(FIELD_MAP.values())


def load_token() -> str:
    if not os.path.exists(ENV_PATH):
        sys.exit(f"FAIL: no .env at {ENV_PATH}. Copy .env.example to .env and add TIINGO_API_KEY.")
    token = ""
    with open(ENV_PATH, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line.startswith("TIINGO_API_KEY=") and not line.startswith("#"):
                token = line.split("=", 1)[1].strip()
    if not token:
        sys.exit("FAIL: TIINGO_API_KEY empty in .env. Get a free token at https://www.tiingo.com")
    return token


def fetch_raw(ticker: str, token: str, start_date: str = HISTORY_START) -> list:
    """Return the list of daily bars from Tiingo. Never logs the URL (Rule 22: token is a query param)."""
    url = f"{TIINGO_BASE}/{ticker}/prices?startDate={start_date}&format=json&token={token}"
    req = urllib.request.Request(url, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.load(resp)
    if not isinstance(data, list):
        raise ValueError(f"{ticker}: expected list of bars, got {type(data).__name__}: {str(data)[:200]}")
    return data


def normalize(ticker: str, raw: list) -> pd.DataFrame:
    """Tidy DataFrame with verified columns; fail loud on missing fields."""
    if not raw:
        raise ValueError(f"{ticker}: zero bars returned")
    rows = []
    for bar in raw:
        missing = [k for k in FIELD_MAP if k not in bar] + (["date"] if "date" not in bar else [])
        if missing:
            raise ValueError(f"{ticker}: bar missing fields {missing}: {str(bar)[:200]}")
        row = {"ticker": ticker, "date": pd.to_datetime(bar["date"], utc=True).tz_localize(None).normalize()}
        for src, dst in FIELD_MAP.items():
            row[dst] = bar[src]
        rows.append(row)
    df = pd.DataFrame(rows, columns=COLUMNS).sort_values("date").reset_index(drop=True)
    # integrity: no duplicate dates, monotonic
    dupes = df["date"].duplicated().sum()
    if dupes:
        raise ValueError(f"{ticker}: {dupes} duplicate dates after normalize")
    return df


def save(df: pd.DataFrame, ticker: str) -> str:
    os.makedirs(RAW_DIR, exist_ok=True)
    path = os.path.join(RAW_DIR, f"{ticker}.parquet")
    df.to_parquet(path, index=False)
    return path


def pull_universe(tickers: list, token: str, pause_s: float = 0.3) -> int:
    """Pull each ticker; print a fail-loud coverage report. Return process exit code."""
    coverage = []
    failures = []
    meta = {}
    for i, ticker in enumerate(tickers, 1):
        try:
            raw = fetch_raw(ticker, token)
            df = normalize(ticker, raw)
            save(df, ticker)
            coverage.append((ticker, len(df), df["date"].min().date().isoformat(),
                             df["date"].max().date().isoformat()))
            meta[ticker] = {"rows": len(df), "pulled_utc": dt.datetime.now(dt.timezone.utc).isoformat()}
            print(f"  [{i:>2}/{len(tickers)}] {ticker:<5} {len(df):>5} bars  "
                  f"{coverage[-1][2]} -> {coverage[-1][3]}")
        except (urllib.error.HTTPError, urllib.error.URLError, ValueError) as e:
            detail = e.read().decode(errors="replace")[:200] if isinstance(e, urllib.error.HTTPError) else str(e)[:200]
            failures.append((ticker, f"{type(e).__name__}: {detail}"))
            print(f"  [{i:>2}/{len(tickers)}] {ticker:<5} FAILED  {failures[-1][1]}")
        if pause_s and i < len(tickers):
            time.sleep(pause_s)

    if meta:
        os.makedirs(RAW_DIR, exist_ok=True)
        with open(os.path.join(RAW_DIR, "_pull_metadata.json"), "w", encoding="utf-8") as fh:
            json.dump(meta, fh, indent=2)

    print(f"\nCoverage: {len(coverage)}/{len(tickers)} tickers pulled, saved to {RAW_DIR}")
    if failures:
        print(f"\nFAIL-LOUD: {len(failures)} ticker(s) did not load:")
        for t, msg in failures:
            print(f"  - {t}: {msg}")
        print("Data lake is INCOMPLETE. Fix these before trusting any backtest.")
        return 1
    print("All tickers loaded cleanly.")
    return 0


def load_panel(tickers: list = None) -> pd.DataFrame:
    """Read saved parquets into one long-format panel (utility for the backtest later)."""
    tickers = tickers or ETF_UNIVERSE
    frames = []
    for ticker in tickers:
        path = os.path.join(RAW_DIR, f"{ticker}.parquet")
        if not os.path.exists(path):
            raise FileNotFoundError(f"{ticker}: no parquet at {path}. Run the pull first.")
        frames.append(pd.read_parquet(path))
    return pd.concat(frames, ignore_index=True).sort_values(["ticker", "date"]).reset_index(drop=True)


def main() -> None:
    tickers = sys.argv[1:] or ETF_UNIVERSE
    token = load_token()
    print(f"Pulling {len(tickers)} ETF(s) from Tiingo since {HISTORY_START}...\n")
    sys.exit(pull_universe(tickers, token))


if __name__ == "__main__":
    main()
