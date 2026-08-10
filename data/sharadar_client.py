#!/usr/bin/env python
"""Reusable Sharadar Direct API client for LLM_Model3 Engine B.

Verified contract (smoke test 2026-08-10):
  base   https://api.sharadar.com/v1.0/data/{endpoint}
  auth   api_key query param  (credential-in-URL -> URL logging suppressed, Rule 22)
  paging offset-based: limit (<=10000) + skip; no cursor
  filter server-side: ticker, table, lastupdated, from/to, col.gt/gte/lt/lte
         (isdelisted/category/exchange are NOT server-filterable -> filter client-side)

Runs on GODZILLA in the repo .venv only (the Cowork sandbox is firewalled from
external market APIs). Never prints the api key or a full key-bearing URL.
"""
from __future__ import annotations

import io
import logging
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import pandas as pd

# Rule 22: no HTTP client may log the api-key-bearing URL.
for _n in ("urllib3", "httpx", "httpcore", "requests", "aiohttp"):
    logging.getLogger(_n).setLevel(logging.WARNING)

BASE = "https://api.sharadar.com/v1.0/data"
REPO = Path(__file__).resolve().parent.parent
ENV = REPO / ".env"
PAGE_MAX = 10000
_UA = {"User-Agent": "LLM_Model3/1.0 (research)"}


def load_key(env_path: Path = ENV) -> str:
    if not env_path.exists():
        sys.exit(f"FAIL: .env not found at {env_path}")
    for line in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
        s = line.strip()
        if s.startswith("SHARADAR_API_KEY="):
            k = s.split("=", 1)[1].strip().strip('"').strip("'")
            if not k:
                sys.exit("FAIL: SHARADAR_API_KEY present but empty in .env")
            return k
    sys.exit("FAIL: SHARADAR_API_KEY not found in .env")


def safe_url(endpoint: str, params: dict) -> str:
    """A key-free rendering of a request, for logs/errors (Rule 22)."""
    shown = {k: v for k, v in params.items() if k != "api_key"}
    return f"{BASE}/{endpoint}?{urllib.parse.urlencode(shown)}&api_key=<redacted>"


def fetch(endpoint: str, key: str, **params):
    """One request -> DataFrame, or None on error. Diagnostics never leak the key.

    `endpoint` is the API table path (tickers/fundamentals/stocks/daily). Sharadar's
    own `table` filter is passed via **params, hence the arg name `endpoint`.
    """
    params = {k: v for k, v in params.items() if v is not None}
    params["format"] = "csv"
    url = f"{BASE}/{endpoint}?{urllib.parse.urlencode({**params, 'api_key': key})}"
    safe = safe_url(endpoint, params)
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=_UA), timeout=120) as r:
            body = r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        print(f"  HTTP {e.code} :: {safe}\n  body: {e.read().decode('utf-8', 'replace')[:400]}")
        return None
    except Exception as e:  # noqa: BLE001 - fail loud with context (Rule 18)
        print(f"  ERROR :: {safe}\n  {type(e).__name__}: {e}")
        return None
    if not body.strip():
        return pd.DataFrame()
    try:
        return pd.read_csv(io.StringIO(body))
    except Exception as e:  # noqa: BLE001
        print(f"  CSV PARSE FAIL :: {safe}\n  {type(e).__name__}: {e}\n  head: {body[:300]}")
        return None


def paginate(endpoint: str, key: str, page: int = PAGE_MAX, maxpages: int = 64, **filt):
    """Offset-paginate a table. Returns (DataFrame, status).

    status: 'complete' (a short final page ended it), 'error' (a page failed - caller
    MUST treat the result as untrustworthy), or 'truncated_maxpages' (hit the page cap).
    """
    frames, skip, status = [], 0, "truncated_maxpages"
    for _ in range(maxpages):
        df = fetch(endpoint, key, limit=page, skip=skip, **filt)
        if df is None:
            status = "error"
            break
        n = len(df)
        print(f"    page skip={skip}: rows={n}")
        if n:
            frames.append(df)
        if n < page:
            status = "complete"
            break
        skip += page
        time.sleep(0.25)
    out = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    return out, status
