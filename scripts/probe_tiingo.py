"""Probe Tiingo ETF access before building the Engine A data lake.

Run on Godzilla (has network access; the Cowork sandbox is firewalled off external APIs).
Stdlib only - no venv or pip install required.

What it checks:
  1. The TIINGO_API_KEY in .env authenticates.
  2. How far back Tiingo returns adjusted daily bars (we expect 20+ years for SPY).
  3. The exact JSON field names, so the loader is built against verified output
     (Tiingo exposes both raw o/h/l/c/v and adjusted adj* fields plus divCash/splitFactor).

Safety: never prints the API token or the request URL (the token is a URL query param;
logging the URL would leak it - CLAUDE_PREFLIGHT Rule 22).

Usage, in a normal PowerShell window on Godzilla, from C:\\trading\\LLM_MODEL3:
    python scripts\\probe_tiingo.py
"""
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
            if line.startswith("TIINGO_API_KEY=") and not line.startswith("#"):
                key = line.split("=", 1)[1].strip()
    if not key:
        sys.exit("FAIL: TIINGO_API_KEY is empty in .env. Get a token at https://www.tiingo.com")
    return key


def main() -> None:
    key = load_env_key()
    url = (
        f"https://api.tiingo.com/tiingo/daily/{TEST_TICKER}/prices"
        f"?startDate=2000-01-01&format=json&token={key}"
    )
    req = urllib.request.Request(url, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.load(resp)
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")[:400]  # body is safe; URL is not
        sys.exit(f"FAIL: HTTP {e.code} {e.reason}\n{body}")
    except Exception as e:  # noqa: BLE001 - fail loud with context
        sys.exit(f"FAIL: {type(e).__name__}: {str(e)[:200]}")

    if not isinstance(data, list) or not data:
        sys.exit(f"FAIL: expected a non-empty list of bars, got: {str(data)[:300]}")

    data.sort(key=lambda r: r.get("date", ""))
    first, last = data[0], data[-1]

    print(f"token length: {len(key)}")
    print(f"bars returned: {len(data)}")
    print(f"oldest bar date: {first.get('date')}")
    print(f"newest bar date: {last.get('date')}")
    print(f"\nfield names in each bar: {sorted(first.keys())}")
    print(f"sample (oldest) bar: {first}")
    print(f"sample (newest) bar: {last}")


if __name__ == "__main__":
    main()
