#!/usr/bin/env python
"""LLM_Model3 Engine B (P3) - Sharadar bulk full-table ingest (Phase 2).

Downloads a full table via the verified bulk contract and converts it to parquet:
  {BASE}/{endpoint}?years=full&format=csv  -> HTTP 302 -> signed DO Spaces URL
  -> ZIP containing {table}.csv  -> DuckDB CSV->parquet (whole-file type detection)
  -> data/raw/sharadar/{name}.parquet + _{name}_metadata.json

DuckDB is used for the conversion because it type-detects across the ENTIRE file
(SAMPLE_SIZE=-1); the fundamentals table has sparse columns (null early, populated
later) that trip streaming/first-block type inference and mis-type financial fields.

IDENTITY KEY is permaticker/ticker (NEVER assume ticker uniqueness across time).
Fail-loud (Rule 18/19): a partial download or failed conversion never leaves a
"clean" parquet behind.

Run on GODZILLA in the repo .venv only (sandbox firewalled). Never prints the key.
Requires duckdb (pip install duckdb).

Usage (Godzilla .venv, from C:\\trading\\LLM_MODEL3):
    python scripts\\ingest_sharadar_bulk.py daily
    python scripts\\ingest_sharadar_bulk.py stocks
    python scripts\\ingest_sharadar_bulk.py fundamentals
"""
from __future__ import annotations

import json
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "data"))
import sharadar_client as sc  # noqa: E402

try:
    import duckdb
except ImportError:
    sys.exit("FAIL: duckdb not installed. Run:  .\\.venv\\Scripts\\python.exe -m pip install duckdb")

RAW = _REPO / "data" / "raw" / "sharadar"

# endpoint + its natural output name + key columns to sanity-check
SPECS = {
    "daily":        {"endpoint": "daily",        "name": "daily",        "keycols": ["ticker", "date"]},
    "stocks":       {"endpoint": "stocks",       "name": "sep_prices",   "keycols": ["ticker", "date"]},
    # NOTE: bulk fundamentals uses the classic SF1 filing-date name `datekey`
    # (the query API renames it `date`). Bulk = datekey.
    "fundamentals": {"endpoint": "fundamentals", "name": "fundamentals", "keycols": ["ticker", "dimension", "datekey"]},
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _posix(p: Path) -> str:
    return str(p).replace("\\", "/")


def download_bulk_zip(endpoint: str, key: str, dest: Path, params: dict | None = None) -> int:
    """Stream the bulk ZIP (following the 302 redirect) to `dest`. Returns bytes written."""
    q = {"years": "full", "format": "csv", **(params or {})}
    url = f"{sc.BASE}/{endpoint}?{urllib.parse.urlencode({**q, 'api_key': key})}"
    safe = sc.safe_url(endpoint, q)
    print(f"  downloading bulk :: {safe}")
    written = 0
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=sc._UA), timeout=600) as r:
            total = int(r.headers.get("Content-Length", 0) or 0)
            next_mark = 25 * 1024 * 1024
            with open(dest, "wb") as f:
                while True:
                    chunk = r.read(1024 * 1024)
                    if not chunk:
                        break
                    f.write(chunk)
                    written += len(chunk)
                    if written >= next_mark:
                        pct = f" ({written/total*100:.0f}%)" if total else ""
                        print(f"    {written/1e6:.0f} MB{pct}")
                        next_mark += 25 * 1024 * 1024
    except urllib.error.HTTPError as e:
        sys.exit(f"FAIL: bulk download HTTP {e.code} :: {safe}\n  {e.read().decode('utf-8','replace')[:300]}")
    except Exception as e:  # noqa: BLE001
        sys.exit(f"FAIL: bulk download error :: {safe}\n  {type(e).__name__}: {e}")
    if written == 0:
        sys.exit("FAIL: bulk download produced 0 bytes.")
    print(f"  downloaded {written/1e6:.1f} MB -> {dest.name}")
    return written


def unzip_one_csv(zip_path: Path, workdir: Path) -> Path:
    if not zipfile.is_zipfile(zip_path):
        head = zip_path.read_bytes()[:200]
        sys.exit(f"FAIL: downloaded file is not a zip. First bytes: {head[:80]!r}")
    with zipfile.ZipFile(zip_path) as z:
        csvs = [n for n in z.namelist() if n.lower().endswith(".csv")]
        if len(csvs) != 1:
            sys.exit(f"FAIL: expected exactly one CSV in the zip, found {z.namelist()}")
        z.extract(csvs[0], workdir)
    return workdir / csvs[0]


def csv_to_parquet(csv_path: Path, out_path: Path) -> None:
    con = duckdb.connect()
    src, dst = _posix(csv_path), _posix(out_path)
    con.execute(
        f"COPY (SELECT * FROM read_csv('{src}', AUTO_DETECT=TRUE, SAMPLE_SIZE=-1, "
        f"HEADER=TRUE, IGNORE_ERRORS=FALSE)) "
        f"TO '{dst}' (FORMAT PARQUET, COMPRESSION ZSTD)"
    )
    con.close()


def integrity(out_path: Path, keycols: list[str]) -> dict:
    con = duckdb.connect()
    p = _posix(out_path)
    cols = [d[0] for d in con.execute(f"SELECT * FROM read_parquet('{p}') LIMIT 0").description]
    n = con.execute(f"SELECT count(*) FROM read_parquet('{p}')").fetchone()[0]
    info = {"rows": int(n), "columns": cols}
    checks = [("rows > 0", n > 0, n)]
    for kc in keycols:
        present = kc in cols
        checks.append((f"key col '{kc}' present", present, present))
        if present:
            nulls = con.execute(f"SELECT count(*) FROM read_parquet('{p}') WHERE \"{kc}\" IS NULL").fetchone()[0]
            checks.append((f"'{kc}' no nulls", nulls == 0, int(nulls)))
    if "date" in cols:
        lo, hi = con.execute(f"SELECT min(date), max(date) FROM read_parquet('{p}')").fetchone()
        info["date_range"] = [str(lo), str(hi)]
    if "ticker" in cols:
        info["distinct_tickers"] = int(con.execute(f"SELECT count(DISTINCT ticker) FROM read_parquet('{p}')").fetchone()[0])
    con.close()
    info["checks"] = checks
    return info


def ingest(table: str) -> None:
    if table not in SPECS:
        sys.exit(f"FAIL: unknown table {table!r}. Choices: {list(SPECS)}")
    spec = SPECS[table]
    key = sc.load_key()
    RAW.mkdir(parents=True, exist_ok=True)
    out = RAW / f"{spec['name']}.parquet"
    print(f"\n== BULK INGEST: {table} -> {out.name} ==")

    with tempfile.TemporaryDirectory() as td:
        tdp = Path(td)
        zpath = tdp / f"{table}.zip"
        download_bulk_zip(spec["endpoint"], key, zpath)
        csv_path = unzip_one_csv(zpath, tdp)
        size_mb = csv_path.stat().st_size / 1e6
        print(f"  unzipped csv: {csv_path.name} ({size_mb:.1f} MB)")
        tmp_parquet = tdp / f"{spec['name']}.parquet"
        print("  converting CSV -> parquet (DuckDB, whole-file type detect)...")
        csv_to_parquet(csv_path, tmp_parquet)
        info = integrity(tmp_parquet, spec["keycols"])
        passed = all(ok for _, ok, _ in info["checks"])
        print(f"  rows={info['rows']}  cols={len(info['columns'])}"
              + (f"  tickers={info.get('distinct_tickers')}" if 'distinct_tickers' in info else "")
              + (f"  dates={info.get('date_range')}" if 'date_range' in info else ""))
        print("  integrity:")
        for label, ok, detail in info["checks"]:
            print(f"    [{'OK ' if ok else 'BAD'}] {label} :: {detail}")

        final = out if passed else RAW / f"{spec['name']}_SUSPECT.parquet"
        # move converted parquet from temp to data/raw (copy bytes; temp dir is deleted on exit)
        final.write_bytes(tmp_parquet.read_bytes())

    meta = {"source": "sharadar_direct_bulk", "endpoint": spec["endpoint"],
            "pulled_utc": _now(), "integrity_pass": passed, "file": final.name, **info}
    (RAW / f"_{spec['name']}_metadata.json").write_text(json.dumps(meta, indent=2, default=str))
    print(f"  wrote {final.relative_to(_REPO)}  ({final.stat().st_size/1e6:.1f} MB)")
    if not passed:
        sys.exit("FAIL: integrity failed - wrote *_SUSPECT.parquet, not the clean file.")
    print(f"  {table} OK.")


def main() -> None:
    tables = sys.argv[1:]
    if not tables:
        sys.exit(f"Usage: python scripts/ingest_sharadar_bulk.py <table> [table ...]\n  tables: {list(SPECS)}")
    for t in tables:
        ingest(t)
    print("\n== DONE - paste this whole output back ==")


if __name__ == "__main__":
    main()
