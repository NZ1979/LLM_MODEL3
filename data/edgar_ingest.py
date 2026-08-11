"""Engine B P4 (Spec 2) - SEC EDGAR submissions ingestion.

Implements docs/ENGINE_B_P4_SPEC2.md section 1 (ingestion contract). The PURE
helpers here (form filtering, filing-row assembly, URL construction, acceptance-
date parsing) are unit-tested in tests/test_edgar_synthetic.py with NO network.
The network fetch (submissions JSON + primary documents) runs ONLY on Godzilla
.venv - the sandbox is firewalled from EDGAR (charter 8) - and caches every raw
document under data/raw/edgar/ (gitignored) so the corpus is frozen and re-runs
are free.

Identity is the EDGAR CIK, attributed to a permaticker by the window rule in
edgar_attribution.py; NEVER the recycled ticker string. /A amendments are
EXCLUDED from the feature stream and counted (Spec 2 sec 1.1).
"""
from __future__ import annotations

import gzip
import json
import time
import urllib.error
import urllib.request
from pathlib import Path

import pandas as pd

# Spec 2 sec 1.1 - the feature-bearing form set (base form, sans /A).
QUALIFYING_FORMS = frozenset({
    "10-K", "10-K405", "10-KSB", "10-KSB405", "10-KT",   # annual + historical
    "10-Q", "10-QT",                                     # quarterly + transition
})

SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
SUBMISSIONS_FILE_URL = "https://data.sec.gov/submissions/{name}"
ARCHIVE_DOC_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/{doc}"
ARCHIVE_TXT_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{acc}.txt"

RATE_MAX_PER_SEC = 8.0          # under SEC fair-access 10 req/sec (Spec 2 sec 1.2)
_MIN_INTERVAL = 1.0 / RATE_MAX_PER_SEC


# ---------------------------------------------------------------------------
# Pure helpers (unit-tested, no network)
# ---------------------------------------------------------------------------
def canon_cik(cik) -> str:
    """Canonical CIK: the integer as a string, no leading zeros (matches the
    bridge's `cik` column). Accepts int, float ('933136.0' from a null-bearing
    column), '0000806085', '806085'. Null / missing (None, NaN, '', '<NA>') ->
    '' (the bridge's 104 no-CIK names, counted not filled - Rule 18)."""
    if cik is None:
        return ""
    s = str(cik).strip()
    if s.lower() in ("", "nan", "none", "null", "<na>"):
        return ""
    try:
        return str(int(float(s)))
    except (ValueError, TypeError):
        return ""


def is_amendment(form: str) -> bool:
    return str(form).strip().upper().endswith("/A")


def base_form(form: str) -> str:
    """Strip a trailing /A so 10-K/A -> 10-K for the qualifying-set test."""
    f = str(form).strip().upper()
    return f[:-2] if f.endswith("/A") else f


def is_qualifying(form: str) -> bool:
    """A feature-bearing filing: a qualifying base form and NOT an amendment."""
    return (not is_amendment(form)) and base_form(form) in QUALIFYING_FORMS


def is_qualifying_amendment(form: str) -> bool:
    """An /A amendment OF a qualifying form - excluded from features but counted."""
    return is_amendment(form) and base_form(form) in QUALIFYING_FORMS


def acceptance_date(acceptance_datetime: str):
    """The ET date component of acceptanceDateTime, as a pandas Timestamp
    (normalised to midnight). Comparison is at date granularity (Spec 2 sec 2),
    so intraday timezone never matters. Pre-2002 stamps are day-precision anyway.
    Returns NaT on an unparseable/empty stamp."""
    s = str(acceptance_datetime).strip()
    if len(s) < 10:
        return pd.NaT
    return pd.to_datetime(s[:10], errors="coerce").normalize()


def _rows_from_block(block: dict) -> pd.DataFrame:
    """Turn one filings block (filings.recent OR a supplementary file payload,
    both dicts of parallel arrays) into a tidy frame."""
    forms = list(block.get("form", []) or [])
    n = len(forms)
    if n == 0:
        return pd.DataFrame(columns=["form", "accession", "filing_date",
                                     "acceptance_datetime", "report_date",
                                     "primary_document"])

    def col(k):
        v = list(block.get(k, []) or [])
        return v + [None] * (n - len(v)) if len(v) < n else v[:n]

    return pd.DataFrame({
        "form": forms,
        "accession": col("accessionNumber"),
        "filing_date": col("filingDate"),
        "acceptance_datetime": col("acceptanceDateTime"),
        "report_date": col("reportDate"),
        "primary_document": col("primaryDocument"),
    })


def assemble_filing_rows(recent: dict, files_payloads: list[dict] | None = None,
                         cik=None) -> pd.DataFrame:
    """Union filings.recent with every supplementary filings.files[] payload, keep
    only qualifying feature-bearing forms, and stamp the ET acceptance date.

    Returns one row per filing with: cik, form, accession, filing_date,
    acceptance_datetime, acceptance_date, report_date, primary_document,
    is_amendment. Qualifying /A amendments are dropped here (they are counted by
    the caller from the raw blocks, Spec 2 sec 1.1).
    """
    blocks = [recent or {}]
    blocks += list(files_payloads or [])
    frames = [_rows_from_block(b) for b in blocks]
    df = pd.concat(frames, ignore_index=True) if frames else _rows_from_block({})
    df = df.drop_duplicates(subset=["accession"]).reset_index(drop=True)
    df["is_amendment"] = df["form"].map(is_amendment)
    keep = df["form"].map(is_qualifying)
    out = df[keep].copy()
    out["acceptance_date"] = out["acceptance_datetime"].map(acceptance_date)
    if cik is not None:
        out.insert(0, "cik", canon_cik(cik))
    return out.reset_index(drop=True)


def count_qualifying_amendments(recent: dict, files_payloads: list[dict] | None = None) -> int:
    """How many /A amendments of qualifying forms we chose NOT to use (Rule 18)."""
    blocks = [recent or {}] + list(files_payloads or [])
    forms = []
    for b in blocks:
        forms += list(b.get("form", []) or [])
    return int(sum(is_qualifying_amendment(f) for f in forms))


def primary_doc_url(cik, accession: str, primary_document: str) -> str:
    acc = str(accession).replace("-", "")
    return ARCHIVE_DOC_URL.format(cik=int(canon_cik(cik)), acc=acc, doc=primary_document)


def full_submission_url(cik, accession: str) -> str:
    acc = str(accession).replace("-", "")
    return ARCHIVE_TXT_URL.format(cik=int(canon_cik(cik)), acc=acc)


def doc_fetch_plan(cik, accession: str, primary_document) -> tuple[str, bool]:
    """(url, is_html). A blank primaryDocument (common pre-2001) -> the full
    submission .txt (SGML), parsed as plain text; else the primary document,
    treated as HTML iff its name ends in .htm/.html."""
    pd_str = "" if primary_document is None else str(primary_document).strip()
    if not pd_str or pd_str.lower() in ("nan", "none"):
        return full_submission_url(cik, accession), False
    is_html = pd_str.lower().endswith((".htm", ".html"))
    return primary_doc_url(cik, accession, pd_str), is_html


# ---------------------------------------------------------------------------
# Network (Godzilla .venv ONLY - the sandbox is firewalled). Not run in tests.
# ---------------------------------------------------------------------------
def _http_get(url: str, ua: str, timeout: int = 60) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": ua,
                                               "Accept-Encoding": "gzip, deflate"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read()
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    return raw


class RateLimiter:
    """<= RATE_MAX_PER_SEC requests/second (Spec 2 sec 1.2)."""
    def __init__(self):
        self._last = 0.0

    def wait(self) -> None:
        now = time.monotonic()
        gap = now - self._last
        if gap < _MIN_INTERVAL:
            time.sleep(_MIN_INTERVAL - gap)
        self._last = time.monotonic()


def build_ua(contact: str) -> str:
    return f"LLM_Model3/1.0 (research; {contact})"


def fetch_submissions(cik, ua: str, limiter: RateLimiter,
                      retries: int = 4) -> dict:
    """Fetch CIK{cik:010d}.json (submissions manifest). Fail loud after retries
    with the offending URL (never the key). Godzilla only."""
    url = SUBMISSIONS_URL.format(cik=int(canon_cik(cik)))
    for attempt in range(retries):
        limiter.wait()
        try:
            return json.loads(_http_get(url, ua).decode("utf-8", "replace"))
        except urllib.error.HTTPError as e:
            if e.code in (429, 503) and attempt < retries - 1:
                time.sleep(2.0 * (attempt + 1))
                continue
            raise RuntimeError(f"EDGAR submissions fetch failed HTTP {e.code} :: {url}")
    raise RuntimeError(f"EDGAR submissions fetch exhausted retries :: {url}")


def fetch_all_filing_blocks(submissions: dict, ua: str, limiter: RateLimiter) -> tuple[dict, list[dict]]:
    """Return (recent, [supplementary payloads]) - traverse filings.recent AND
    every filings.files[] (recent caps ~1000; older history lives in the files)."""
    filings = submissions.get("filings", {}) or {}
    recent = filings.get("recent", {}) or {}
    payloads = []
    for f in (filings.get("files", []) or []):
        name = f.get("name")
        if not name:
            continue
        url = SUBMISSIONS_FILE_URL.format(name=name)
        limiter.wait()
        payloads.append(json.loads(_http_get(url, ua).decode("utf-8", "replace")))
    return recent, payloads


def fetch_document(url: str, ua: str, limiter: RateLimiter, cache_path: Path | None = None,
                   retries: int = 4) -> str:
    """Fetch a filing document. If cache_path is given, read/write it (gitignored
    corpus cache); if None, fetch without caching (e.g. the read-only smoke test).
    Godzilla only."""
    if cache_path is not None:
        cache_path = Path(cache_path)
        if cache_path.exists():
            return cache_path.read_text(encoding="utf-8", errors="replace")
    for attempt in range(retries):
        limiter.wait()
        try:
            raw = _http_get(url, ua)
            break
        except urllib.error.HTTPError as e:
            if e.code in (429, 503) and attempt < retries - 1:
                time.sleep(2.0 * (attempt + 1))
                continue
            raise RuntimeError(f"EDGAR document fetch failed HTTP {e.code} :: {url}")
    else:
        raise RuntimeError(f"EDGAR document fetch exhausted retries :: {url}")
    text = raw.decode("utf-8", "replace")
    if cache_path is not None:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(text, encoding="utf-8", errors="replace")
    return text
