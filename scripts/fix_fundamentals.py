#!/usr/bin/env python
"""Revalidate + promote fundamentals_SUSPECT.parquet without re-downloading.

The Phase-2 bulk ingest flagged fundamentals SUSPECT because it checked for a
column named `date`, but the BULK fundamentals export uses the classic SF1 name
`datekey` for the filing date (the query API renames it `date`). The parquet is
fine; this script auto-detects the filing-date column, validates, and if clean
renames fundamentals_SUSPECT.parquet -> fundamentals.parquet + writes metadata.

Run on GODZILLA in the repo .venv. Requires duckdb.

Usage (from C:\\trading\\LLM_MODEL3):
    python scripts\\fix_fundamentals.py
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    import duckdb
except ImportError:
    sys.exit("FAIL: duckdb not installed.")

_REPO = Path(__file__).resolve().parent.parent
RAW = _REPO / "data" / "raw" / "sharadar"
SUSPECT = RAW / "fundamentals_SUSPECT.parquet"
CLEAN = RAW / "fundamentals.parquet"
FILING_CANDIDATES = ["datekey", "date"]


def _posix(p: Path) -> str:
    return str(p).replace("\\", "/")


def main() -> None:
    if not SUSPECT.exists():
        sys.exit(f"FAIL: {SUSPECT} not found (nothing to promote).")
    con = duckdb.connect()
    p = _posix(SUSPECT)
    cols = [d[0] for d in con.execute(f"SELECT * FROM read_parquet('{p}') LIMIT 0").description]
    print(f"columns ({len(cols)}): {cols}")

    filing = next((c for c in FILING_CANDIDATES if c in cols), None)
    print(f"filing-date column detected: {filing!r}")

    keycols = ["ticker", "dimension"] + ([filing] if filing else [])
    checks = [("filing-date column present (datekey/date)", filing is not None, filing)]
    n = con.execute(f"SELECT count(*) FROM read_parquet('{p}')").fetchone()[0]
    checks.append(("rows > 0", n > 0, int(n)))
    for kc in keycols:
        nulls = con.execute(f"SELECT count(*) FROM read_parquet('{p}') WHERE \"{kc}\" IS NULL").fetchone()[0]
        checks.append((f"'{kc}' no nulls", nulls == 0, int(nulls)))

    info = {"rows": int(n), "columns": cols, "filing_col": filing}
    if filing:
        lo, hi = con.execute(f"SELECT min(\"{filing}\"), max(\"{filing}\") FROM read_parquet('{p}')").fetchone()
        info["filing_range"] = [str(lo), str(hi)]
        print(f"  rows={n}  tickers={con.execute(f'SELECT count(DISTINCT ticker) FROM read_parquet({chr(39)+p+chr(39)})').fetchone()[0]}"
              f"  {filing} range={lo}..{hi}")
        dims = con.execute(f"SELECT dimension, count(*) FROM read_parquet('{p}') GROUP BY dimension ORDER BY 1").fetchall()
        print(f"  dimensions: {dims}")
        # PIT sanity: filing date should generally be AFTER reportperiod
        if "reportperiod" in cols:
            lag = con.execute(
                f"SELECT median(datediff('day', CAST(reportperiod AS DATE), CAST(\"{filing}\" AS DATE))) "
                f"FROM read_parquet('{p}') WHERE dimension='ARQ'"
            ).fetchone()[0]
            print(f"  median filing lag (ARQ, {filing} - reportperiod): {lag} days")
            checks.append(("PIT lag positive (ARQ)", lag is not None and lag > 0, lag))
    con.close()

    print("integrity:")
    for label, ok, detail in checks:
        print(f"  [{'OK ' if ok else 'BAD'}] {label} :: {detail}")
    passed = all(ok for _, ok, _ in checks)
    if not passed:
        sys.exit("FAIL: revalidation failed - leaving SUSPECT in place.")

    os.replace(SUSPECT, CLEAN)
    meta = {"source": "sharadar_direct_bulk", "endpoint": "fundamentals",
            "pulled_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "integrity_pass": True, "file": CLEAN.name, "promoted_from": SUSPECT.name, **info}
    (RAW / "_fundamentals_metadata.json").write_text(json.dumps(meta, indent=2, default=str))
    print(f"\n  promoted -> {CLEAN.relative_to(_REPO)}  ({CLEAN.stat().st_size/1e6:.1f} MB)")
    print("  fundamentals OK.")


if __name__ == "__main__":
    main()
