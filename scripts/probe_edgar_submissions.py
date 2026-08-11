#!/usr/bin/env python
"""LLM_Model3 Engine B (P4) - probe the SEC EDGAR submissions API.

Read-only de-risking before designing the EDGAR filings ingestion (Spec 2). For a
few known CIKs (from the permaticker->CIK bridge) it confirms:
  - the submissions endpoint works with our User-Agent (SEC fair-access needs one),
  - `acceptanceDateTime` is present (the point-in-time knowable-at-time stamp -
    distinct from filingDate/reportDate),
  - 10-K / 10-Q filings are present and countable,
  - coverage reaches back to 1998-2000 for DELISTED names (the survivorship case;
    EDGAR full-text SEARCH is 2001+, but the archives/submissions reach the 1990s),
  - where older filings live (filings.recent holds the most recent ~1000; the rest
    are in the supplementary filings.files JSONs).

Prints only; writes nothing. SEC fair-access: set SEC_EDGAR_CONTACT in .env
(gitignored) to a valid contact email; the UA is built from it. Rate-limited well
under SEC's 10 req/sec.

Run on GODZILLA in the repo .venv (consistent with all data pulls; charter 8).

Usage (Godzilla .venv, from C:\\trading\\LLM_MODEL3):
    python scripts\\probe_edgar_submissions.py
"""
from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
from collections import Counter
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
ENV = _REPO / ".env"
BASE = "https://data.sec.gov/submissions/CIK{cik10}.json"

# known CIKs from the bridge probe: (label, cik, delisted?)
PROBE_CIKS = [
    ("LEHMAN BROTHERS", "806085", True),
    ("BEAR STEARNS", "777001", True),
    ("WASHINGTON MUTUAL", "933136", True),
    ("ENRON", "1024401", True),
    ("KRAFT HEINZ (active)", "1637459", False),
]


def load_contact(env_path: Path = ENV) -> str:
    if not env_path.exists():
        sys.exit(f"FAIL: .env not found at {env_path}")
    for line in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
        s = line.strip()
        if s.startswith("SEC_EDGAR_CONTACT="):
            v = s.split("=", 1)[1].strip().strip('"').strip("'")
            if v:
                return v
    sys.exit("FAIL: SEC_EDGAR_CONTACT not set in .env. Add one line (gitignored):\n"
             "    SEC_EDGAR_CONTACT=you@example.com\n"
             "SEC fair-access requires a real contact in the User-Agent.")


def fetch_json(cik: str, ua: str):
    url = BASE.format(cik10=cik.zfill(10))
    req = urllib.request.Request(url, headers={"User-Agent": ua,
                                               "Accept-Encoding": "gzip, deflate",
                                               "Host": "data.sec.gov"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            raw = r.read()
            # data.sec.gov may gzip; urllib doesn't auto-decode -> handle
            if raw[:2] == b"\x1f\x8b":
                import gzip
                raw = gzip.decompress(raw)
            return json.loads(raw.decode("utf-8", "replace")), None
    except urllib.error.HTTPError as e:
        return None, f"HTTP {e.code} ({e.reason})"
    except Exception as e:  # noqa: BLE001 - fail loud with context
        return None, f"{type(e).__name__}: {e}"


def main() -> None:
    contact = load_contact()
    ua = f"LLM_Model3/1.0 (research; {contact})"
    print(f"UA contact loaded from .env (len={len(contact)}). Probing {len(PROBE_CIKS)} CIKs.\n")

    for label, cik, delisted in PROBE_CIKS:
        print("=" * 72)
        print(f"{label}  CIK={cik.zfill(10)}  delisted={delisted}")
        data, err = fetch_json(cik, ua)
        if err:
            print(f"  ERROR: {err}")
            if "403" in err:
                print("  -> 403 usually means the User-Agent was rejected. Check SEC_EDGAR_CONTACT.")
            time.sleep(0.3)
            continue

        print(f"  entityName: {data.get('name')!r}   sic: {data.get('sic')} "
              f"{data.get('sicDescription')!r}   tickers: {data.get('tickers')}")
        recent = (data.get("filings", {}) or {}).get("recent", {}) or {}
        forms = recent.get("form", []) or []
        fdates = recent.get("filingDate", []) or []
        adt = recent.get("acceptanceDateTime", []) or []
        rdate = recent.get("reportDate", []) or []
        pdoc = recent.get("primaryDocument", []) or []
        acc = recent.get("accessionNumber", []) or []
        n = len(forms)
        fc = Counter(forms)
        n10k = sum(v for k, v in fc.items() if k.startswith("10-K"))
        n10q = sum(v for k, v in fc.items() if k.startswith("10-Q"))
        print(f"  filings.recent: {n} rows;  10-K*={n10k}  10-Q*={n10q}  "
              f"(top forms: {dict(fc.most_common(6))})")
        if fdates:
            print(f"  filingDate range (recent): {min(fdates)} .. {max(fdates)}")
        print(f"  acceptanceDateTime present: {bool(adt)}  reportDate present: {bool(rdate)}")

        # show one 10-K example row (the PIT stamp + primary doc)
        idx = next((i for i, f in enumerate(forms) if str(f).startswith("10-K")), None)
        if idx is not None:
            print(f"  example 10-K: filingDate={fdates[idx] if idx < len(fdates) else '?'}  "
                  f"acceptanceDateTime={adt[idx] if idx < len(adt) else '?'}  "
                  f"reportDate={rdate[idx] if idx < len(rdate) else '?'}")
            print(f"    accession={acc[idx] if idx < len(acc) else '?'}  "
                  f"primaryDocument={pdoc[idx] if idx < len(pdoc) else '?'}")

        # supplementary (older) filing files - where pre-'recent' history lives
        files = (data.get("filings", {}) or {}).get("files", []) or []
        if files:
            print(f"  supplementary filings.files: {len(files)} (older history)")
            for f in files[:4]:
                print(f"    {f.get('name')}  count={f.get('filingCount')}  "
                      f"{f.get('filingFrom')}..{f.get('filingTo')}")
        else:
            print("  supplementary filings.files: none (recent holds full history)")
        time.sleep(0.3)   # SEC fair-access: well under 10 req/sec

    print("\n" + "=" * 72)
    print("READ: confirm (1) no 403 (UA accepted), (2) acceptanceDateTime present,")
    print("(3) 10-K/10-Q counts non-zero, (4) delisted names reach back to 1998-2000")
    print("(via recent or files ranges). Then we design the ingestion + pre-register Spec 2.")
    print("\n== DONE - paste this whole output back ==")


if __name__ == "__main__":
    main()
