"""Probe Polygon ETF access before building the P1 data lake.

Run on Godzilla (has network access; the Cowork sandbox is firewalled off polygon.io).
Stdlib only - no venv or pip install required.

What it checks:
  1. The POLYGON_API_KEY in .env authenticates.
  2. How far back the plan actually returns split/dividend-adjusted DAILY bars
     (plans differ: some cap history at 2 or 5 years).
  3. The exact JSON field names in the aggregates response, so the loader is
     built against verified output instead of guessed column names.

Safety: never prints the API key or the request URL (Polygon passes the key as a
URL query param; logging the URL would leak it - CLAUDE_PREFLIGHT Rule 22).

Usage, in a normal PowerShell window on Godzilla, from C:\\trading\\LLM_MODEL3:
    python scripts\\probe_polygon.py
"""
import datetime as dt
import json
import os
import sys
import urllib.error
import urllib.request

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV_PATH = os.path.join(REPO_ROOT, ".env")
TEST_TICKER = "SPY"


def load_env_key() -> str:
    if not os.path.exists(ENV_PATH):
        sys.exit(f"FAIL: no .env at {ENV_PATH}. Copy .env.example to .env and add your key.")
    key = ""
    with open(ENV_PATH, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line.startswith("POLYGON_API_KEY=") and not line.startswith("#"):
                key = line.split("=", 1)[1].strip()
    if not key:
        sys.exit("FAIL: POLYGON_API_KEY is empty in .env.")
    return key


def main() -> None:
    key = load_env_key()
    today = dt.date.today().isoformat()
    # Request a deliberately wide window to discover the plan's real history depth.
    url = (
        f"https://api.polygon.io/v2/aggs/ticker/{TEST_TICKER}/range/1/day/"
        f"2000-01-01/{today}?adjusted=true&sort=asc&limit=50000&apiKey={key}"
    )
    try:
        with urllib.request.urlopen(url, timeout=30) as resp:
            data = json.load(resp)
    except urllib.error.HTTPError as e:
        # Do not echo the URL (contains the key). Body is safe to show.
        body = e.read().decode(errors="replace")[:400]
        sys.exit(f"FAIL: HTTP {e.code} {e.reason}\n{body}")
    except Exception as e:  # noqa: BLE001 - fail loud with context
        sys.exit(f"FAIL: {type(e).__name__}: {str(e)[:200]}")

    status = data.get("status")
    results = data.get("results", []) or []
    count = data.get("resultsCount", len(results))

    print(f"key length: {len(key)}")
    print(f"status: {status}")
    print(f"adjusted: {data.get('adjusted')}")
    print(f"resultsCount: {count}")

    if not results:
        print("\nWARNING: zero rows returned. Either the plan has no history for this "
              "range, or the key lacks aggregates access. Body status above is the clue.")
        return

    def to_date(ms: int) -> str:
        return dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc).date().isoformat()

    first, last = results[0], results[-1]
    print(f"\noldest bar date: {to_date(first['t'])}")
    print(f"newest bar date: {to_date(last['t'])}")
    span_years = (last["t"] - first["t"]) / 1000 / 86400 / 365.25
    print(f"approx history span: {span_years:.1f} years")
    print(f"\nfield names in each bar: {sorted(first.keys())}")
    print(f"sample (oldest) bar: {first}")
    print(f"sample (newest) bar: {last}")


if __name__ == "__main__":
    main()
