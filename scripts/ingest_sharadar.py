#!/usr/bin/env python
"""LLM_Model3 Engine B (P3) - Sharadar point-in-time panel ingest.

Phase 1 (this file): ingest the EQUITY SECURITIES MASTER (tickers, table=stocks)
into data/raw/sharadar/tickers.parquet, keyed on permaticker, with fail-loud
integrity checks (Rule 18/19). Also probes the BULK download endpoint so the
big-table ingest (prices/daily/fundamentals) can be designed against a verified
contract rather than a guess.

IDENTITY KEY is permaticker, NEVER the ticker string (tickers are recycled after
delisting -> keying on ticker is survivorship leakage).

Run on GODZILLA in the repo .venv only (sandbox is firewalled). Never prints the key.

Usage (Godzilla .venv, from C:\\trading\\LLM_MODEL3):
    python scripts\\ingest_sharadar.py
"""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "data"))
import sharadar_client as sc  # noqa: E402

RAW = _REPO / "data" / "raw" / "sharadar"
TICKER_FIELDS = (
    "permaticker,ticker,name,exchange,isdelisted,category,sector,industry,"
    "siccode,scalemarketcap,scalerevenue,currency,location,"
    "firstpricedate,lastpricedate,firstquarter,lastquarter"
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def ingest_tickers(key) -> None:
    print("\n== INGEST: equity securities master (tickers, table=stocks) ==")
    df, status = sc.paginate("tickers", key, table="stocks", fields=TICKER_FIELDS)
    if status != "complete":
        sys.exit(f"FAIL: tickers pull status={status!r} - refusing to write a "
                 f"possibly-partial master (Rule 19). Investigate before retrying.")

    raw_rows = len(df)
    if "permaticker" in df.columns:
        df = df.drop_duplicates(subset=["permaticker"]).reset_index(drop=True)
    n = len(df)
    ndel = int((df.get("isdelisted").astype(str) == "Y").sum()) if "isdelisted" in df else -1

    # ---- integrity (all critical) ----
    checks = [
        ("rows in plausible range 15k-30k", 15000 <= n <= 30000, n),
        ("permaticker present", "permaticker" in df.columns, list(df.columns)[:6]),
        ("permaticker non-null", "permaticker" in df and df["permaticker"].notna().all(),
         int(df["permaticker"].isna().sum()) if "permaticker" in df else "n/a"),
        ("permaticker unique", "permaticker" in df and df["permaticker"].is_unique,
         n - df["permaticker"].nunique() if "permaticker" in df else "n/a"),
        ("isdelisted has Y and N", "isdelisted" in df and
         {"Y", "N"}.issubset(set(df["isdelisted"].dropna().astype(str).unique())),
         sorted(df["isdelisted"].dropna().astype(str).unique().tolist()) if "isdelisted" in df else "n/a"),
        ("delisted majority (survivorship-free)", ndel > n * 0.4, ndel),
    ]
    print(f"\n  raw rows={raw_rows}  distinct permatickers={n}  delisted(Y)={ndel}")
    print("  integrity:")
    for label, ok, detail in checks:
        print(f"    [{'OK ' if ok else 'BAD'}] {label} :: {detail}")
    passed = all(ok for _, ok, _ in checks)

    RAW.mkdir(parents=True, exist_ok=True)
    out = RAW / ("tickers.parquet" if passed else "tickers_SUSPECT.parquet")
    df.to_parquet(out, index=False)
    meta = {
        "source": "sharadar_direct", "endpoint": "tickers", "filter": "table=stocks",
        "pulled_utc": _now(), "rows": n, "delisted_Y": ndel,
        "integrity_pass": passed, "file": out.name,
        "columns": list(df.columns),
    }
    (RAW / "_tickers_metadata.json").write_text(json.dumps(meta, indent=2))
    print(f"\n  wrote {out.relative_to(_REPO)}  ({out.stat().st_size/1e6:.2f} MB)")
    if not passed:
        sys.exit("FAIL: integrity checks failed - wrote tickers_SUSPECT.parquet, "
                 "not the clean file. Do not build on this.")
    print("  tickers master OK.")


def bulk_probe(key, endpoint: str = "tickers") -> None:
    """Learn the bulk contract without depending on it. Reports mechanics only."""
    print("\n== PROBE: bulk full-table download (years=full) ==")
    params = {"table": "stocks", "years": "full", "format": "csv"}
    url = f"{sc.BASE}/{endpoint}?{urllib.parse.urlencode({**params, 'api_key': key})}"
    safe = sc.safe_url(endpoint, params)
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=sc._UA), timeout=180) as r:
            chunk = r.read(4000)
            final = r.geturl()
            ct = r.headers.get("Content-Type", "?")
            ce = r.headers.get("Content-Encoding", "?")
            cl = r.headers.get("Content-Length", "?")
            code = getattr(r, "status", "?")
    except urllib.error.HTTPError as e:
        print(f"  HTTP {e.code} :: {safe}\n  body: {e.read().decode('utf-8','replace')[:300]}")
        return
    except Exception as e:  # noqa: BLE001
        print(f"  ERROR :: {safe}\n  {type(e).__name__}: {e}")
        return
    # redact: show only scheme+host+path and the NAMES of query params, never values
    u = urllib.parse.urlparse(final)
    qnames = [p.split("=", 1)[0] for p in u.query.split("&")] if u.query else []
    is_gzip = chunk[:2] == b"\x1f\x8b"
    print(f"  request     : {safe}")
    print(f"  status      : {code}")
    print(f"  final url   : {u.scheme}://{u.netloc}{u.path}  ?params={qnames}  (redirected={u.netloc not in sc.BASE})")
    print(f"  content-type: {ct}   content-encoding: {ce}   content-length: {cl}")
    print(f"  gzip magic  : {is_gzip}")
    if is_gzip:
        print("  -> bulk returns a gzip stream; big-table ingest will stream+gunzip this.")
    else:
        preview = chunk.decode("utf-8", "replace").splitlines()[:3]
        print("  first lines :")
        for ln in preview:
            print(f"    {ln[:160]}")


def main() -> None:
    key = sc.load_key()
    print(f"Key loaded (len={len(key)}). Repo: {_REPO}")
    ingest_tickers(key)
    bulk_probe(key)
    print("\n== DONE - paste this whole output back ==")


if __name__ == "__main__":
    main()
