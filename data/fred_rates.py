"""FRED short-rate loader - the benchmark leg of Engine A's financing cost.

Pulls FRED series DTB3 (3-Month Treasury Bill, Secondary Market Rate, Discount
Basis, daily, percent per annum) and stores it in the data lake alongside the
Tiingo ETF parquets. Spec and justification: docs/FINANCING_SPEC.md.

FRED's CSV endpoint is public and needs no API key, so nothing here touches .env
and nothing is logged that could leak a credential (preflight Rules 21-22).

Fails loud, never fakes (Rule 18): a short series, a gap at the front of the
backtest span, or an unparseable payload raises rather than silently
forward-filling a zero rate - a zero rate would understate financing cost and
flatter the strategy, which is the exact failure mode this file exists to close.

Run in the Godzilla .venv (PowerShell), from C:\\trading\\LLM_MODEL3:
    python data\\fred_rates.py
"""
import datetime as dt
import io
import json
import os
import sys
import urllib.error
import urllib.request

import pandas as pd

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

RAW_DIR = os.path.join(REPO_ROOT, "data", "raw", "fred")
FRED_CSV = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}"
SERIES = "DTB3"
HISTORY_START = "1999-01-01"   # earlier than the ETF panel so alignment never front-gaps


def fetch_csv(series: str = SERIES) -> pd.DataFrame:
    url = FRED_CSV.format(series=series)
    req = urllib.request.Request(url, headers={"User-Agent": "LLM_MODEL3/1.0"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        payload = resp.read().decode("utf-8", errors="replace")
    if "," not in payload.splitlines()[0]:
        raise ValueError(f"{series}: unexpected payload head: {payload[:200]!r}")
    df = pd.read_csv(io.StringIO(payload))
    return df


def normalize(df: pd.DataFrame, series: str = SERIES) -> pd.DataFrame:
    """-> columns [date, rate] with rate as a DECIMAL (0.0525 = 5.25%)."""
    cols = {c.lower(): c for c in df.columns}
    date_col = cols.get("observation_date") or cols.get("date")
    if date_col is None:
        raise ValueError(f"{series}: no date column in {list(df.columns)}")
    value_col = next((c for c in df.columns if c != date_col), None)
    if value_col is None:
        raise ValueError(f"{series}: no value column in {list(df.columns)}")

    out = pd.DataFrame({
        "date": pd.to_datetime(df[date_col]).dt.normalize(),
        # FRED marks missing observations with '.'
        "rate": pd.to_numeric(df[value_col], errors="coerce") / 100.0,
    })
    out = out.dropna(subset=["rate"]).sort_values("date").reset_index(drop=True)

    if out.empty:
        raise ValueError(f"{series}: zero usable observations")
    if out["date"].duplicated().any():
        raise ValueError(f"{series}: duplicate dates after normalize")
    if out["date"].min() > pd.Timestamp(HISTORY_START):
        raise ValueError(
            f"{series}: series starts {out['date'].min().date()}, later than required "
            f"{HISTORY_START}; cannot cover the backtest span")
    if not ((out["rate"] >= -0.01) & (out["rate"] < 0.25)).all():
        bad = out.loc[~((out["rate"] >= -0.01) & (out["rate"] < 0.25))]
        raise ValueError(f"{series}: {len(bad)} implausible rates, e.g. {bad.head(3).to_dict('records')}")
    return out


def save(df: pd.DataFrame, series: str = SERIES) -> str:
    os.makedirs(RAW_DIR, exist_ok=True)
    path = os.path.join(RAW_DIR, f"{series}.parquet")
    df.to_parquet(path, index=False)
    meta = {
        series: {
            "rows": len(df),
            "start": df["date"].min().date().isoformat(),
            "end": df["date"].max().date().isoformat(),
            "pulled_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
            "units": "decimal annual rate (0.0525 = 5.25%)",
            "source": "FRED fredgraph.csv, no API key",
        }
    }
    with open(os.path.join(RAW_DIR, "_pull_metadata.json"), "w", encoding="utf-8") as fh:
        json.dump(meta, fh, indent=2)
    return path


def load_rate(series: str = SERIES) -> pd.Series:
    """Saved series as a pd.Series indexed by date, values = decimal annual rate."""
    path = os.path.join(RAW_DIR, f"{series}.parquet")
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"{series}: no parquet at {path}. Run `python data\\fred_rates.py` first.")
    df = pd.read_parquet(path)
    return df.set_index("date")["rate"].sort_index()


def align_to(index: pd.DatetimeIndex, series: str = SERIES) -> pd.Series:
    """Forward-fill the rate onto trading days. Causal; never back-fills.

    Fails loud if the rate series starts after the requested index does, rather
    than emitting a zero rate for the uncovered head.
    """
    rate = load_rate(series)
    if rate.index.min() > index.min():
        raise ValueError(
            f"{series} starts {rate.index.min().date()} but the panel starts "
            f"{index.min().date()}; refusing to fabricate a rate for the gap.")
    aligned = rate.reindex(rate.index.union(index)).ffill().reindex(index)
    if aligned.isna().any():
        raise ValueError(f"{series}: {int(aligned.isna().sum())} NaN rates after alignment")
    return aligned


def main() -> None:
    print(f"Pulling FRED {SERIES} (3-month T-bill, daily)...")
    try:
        raw = fetch_csv(SERIES)
        df = normalize(raw, SERIES)
    except (urllib.error.HTTPError, urllib.error.URLError, ValueError) as e:
        detail = e.read().decode(errors="replace")[:200] if isinstance(e, urllib.error.HTTPError) else str(e)[:300]
        sys.exit(f"FAIL: {type(e).__name__}: {detail}")
    path = save(df, SERIES)
    print(f"  {len(df)} observations  {df['date'].min().date()} -> {df['date'].max().date()}")
    print(f"  mean {df['rate'].mean():.2%}  min {df['rate'].min():.2%}  max {df['rate'].max():.2%}")
    since2001 = df[df['date'] >= '2001-01-01']['rate']
    print(f"  mean since 2001: {since2001.mean():.2%}")
    print(f"  saved -> {path}")


if __name__ == "__main__":
    main()
