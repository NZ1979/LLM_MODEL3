"""Engine B P4 (Spec 2) - synthetic-data correctness + leak-trap suite.

Run in the Claude-side sandbox (or Godzilla .venv) on SYNTHETIC data ONLY, with
NO network and NO real LLM. Gates every real EDGAR fetch/extraction (Spec 2 sec 6,
the A-2 discipline: this code is frozen/committed before any real corpus is built).

Hard PASS/FAIL, exits non-zero on any failure (Rule 18). The seven load-bearing
assertions from docs/ENGINE_B_P4_SPEC2.md section 6:

  1. Successor-entity filing rejected by the window rule (WaMu->COOP analogue);
     gap filing unattributed and dropped.
  2. Overlapping windows on one CIK fail loud (AttributionAmbiguityError).
  3. A filing dated after T is not used at T.
  4. Strictly-before-T: a filing accepted exactly on T is not used at T.
  5. Staleness cap (18 months) -> NaN features.
  6. NaN fall-back (not fill): a ranked name with no filing keeps its mechanical
     factors and gets NaN LLM columns; counted.
  7. Section extraction on BOTH modern HTML and old plain-.txt; a pre-2006 10-K
     with no Item 1A yields NaN Risk-Factors features.

Plus unit checks on the ingestion pure helpers and the identity masking.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from data import edgar_ingest as ing            # noqa: E402
from data import edgar_sections as sec          # noqa: E402
from data.edgar_attribution import (            # noqa: E402
    attribute_filings, asof_join, AttributionAmbiguityError, _STALENESS_DAYS)
from features import edgar_llm_features as elf   # noqa: E402

_FAILS: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    tag = "PASS" if cond else "FAIL"
    print(f"  [{tag}] {name}" + (f" :: {detail}" if detail else ""))
    if not cond:
        _FAILS.append(name)


def _ts(s):
    return pd.Timestamp(s)


# ---------------------------------------------------------------------------
def test_ingest_helpers():
    print("\n[INGEST] pure helpers (form set, urls, acceptance date, assembly)")
    check("10-K qualifies", ing.is_qualifying("10-K"))
    check("10-Q qualifies", ing.is_qualifying("10-Q"))
    check("10-K405 qualifies", ing.is_qualifying("10-K405"))
    check("10-KSB qualifies", ing.is_qualifying("10-KSB"))
    check("10-K/A excluded", not ing.is_qualifying("10-K/A"))
    check("8-K excluded", not ing.is_qualifying("8-K"))
    check("10-K/A is a qualifying amendment", ing.is_qualifying_amendment("10-K/A"))
    check("canon_cik handles str/int/float/leading-zeros",
          ing.canon_cik("0000806085") == "806085" and ing.canon_cik(933136) == "933136"
          and ing.canon_cik("933136.0") == "933136")
    check("canon_cik null/nan -> '' (no-CIK names, not filled)",
          ing.canon_cik(None) == "" and ing.canon_cik(float("nan")) == ""
          and ing.canon_cik("nan") == "" and ing.canon_cik("") == "")
    check("acceptance date parses to ET date",
          ing.acceptance_date("2008-03-31T16:34:54.000Z") == _ts("2008-03-31"))
    check("acceptance date pre-2002 day precision",
          ing.acceptance_date("1998-02-13T00:00:00Z") == _ts("1998-02-13"))

    url = ing.primary_doc_url(806085, "0000806085-08-000042", "lehman10k.htm")
    check("primary doc url (CIK no leading zeros, accession keeps them)", url ==
          "https://www.sec.gov/Archives/edgar/data/806085/000080608508000042/lehman10k.htm", url)
    urls, is_html = ing.doc_fetch_plan(806085, "0000806085-98-000010", "")
    check("blank primaryDocument -> full .txt (no-dash then dashed), not html",
          (not is_html) and urls[0].endswith("/000080608598000010.txt")
          and urls[1].endswith("/0000806085-98-000010.txt"), str(urls))

    recent = {
        "form": ["10-K", "10-K/A", "8-K", "10-Q", "4"],
        "accessionNumber": ["a-1", "a-2", "a-3", "a-4", "a-5"],
        "filingDate": ["2010-03-01", "2010-04-01", "2010-02-01", "2010-05-01", "2010-01-01"],
        "acceptanceDateTime": ["2010-03-01T16:00:00Z", "2010-04-01T16:00:00Z",
                               "2010-02-01T16:00:00Z", "2010-05-01T16:00:00Z",
                               "2010-01-01T16:00:00Z"],
        "reportDate": ["2009-12-31", "2009-12-31", "", "2010-03-31", ""],
        "primaryDocument": ["k.htm", "ka.htm", "8k.htm", "q.htm", "4.xml"],
    }
    rows = ing.assemble_filing_rows(recent, [], cik=806085)
    kept = set(rows["accession"])
    check("assemble keeps only qualifying non-amendment forms",
          kept == {"a-1", "a-4"}, str(sorted(kept)))
    check("assemble stamps acceptance_date",
          rows.loc[rows.accession == "a-1", "acceptance_date"].iloc[0] == _ts("2010-03-01"))
    check("qualifying amendments counted (not used)",
          ing.count_qualifying_amendments(recent, []) == 1)


# ---------------------------------------------------------------------------
def test_attribution_successor():
    print("\n[1] successor-entity rejected by the window rule (WaMu->COOP analogue)")
    bridge = pd.DataFrame([
        {"permaticker": "PT_A", "cik": "999", "firstpricedate": "2000-01-01", "lastpricedate": "2008-10-15"},
        {"permaticker": "PT_B", "cik": "999", "firstpricedate": "2018-06-01", "lastpricedate": "2025-01-01"},
    ])
    filings = pd.DataFrame([
        {"cik": "999", "accession": "A", "acceptance_date": _ts("2005-06-01")},  # -> PT_A
        {"cik": "999", "accession": "B", "acceptance_date": _ts("2020-03-15")},  # -> PT_B
        {"cik": "999", "accession": "C", "acceptance_date": _ts("2012-01-01")},  # gap -> dropped
    ])
    attributed, stats = attribute_filings(filings, bridge)
    amap = dict(zip(attributed["accession"], attributed["permaticker"]))
    check("2005 filing -> PT_A only", amap.get("A") == "PT_A", str(amap))
    check("2020 filing -> PT_B only (never PT_A)", amap.get("B") == "PT_B", str(amap))
    check("gap filing 2012 unattributed & dropped", "C" not in amap, str(amap))
    check("gap counted in stats", stats["n_unattributed_gap"] == 1, str(stats))


def test_attribution_ambiguity():
    print("\n[2] overlapping windows on one CIK fail loud")
    bridge = pd.DataFrame([
        {"permaticker": "PT_X", "cik": "888", "firstpricedate": "2000-01-01", "lastpricedate": "2010-12-31"},
        {"permaticker": "PT_Y", "cik": "888", "firstpricedate": "2005-01-01", "lastpricedate": "2015-12-31"},
    ])
    filings = pd.DataFrame([
        {"cik": "888", "accession": "D", "acceptance_date": _ts("2007-06-01")},  # in both windows
    ])
    raised = False
    try:
        attribute_filings(filings, bridge)
    except AttributionAmbiguityError:
        raised = True
    check("overlapping windows raise AttributionAmbiguityError", raised)


def _ranked_frame(dates, permatickers):
    """Minimal ranked cross-section carrying the five mechanical z-scores."""
    rows = []
    for d in dates:
        for i, pt in enumerate(permatickers):
            rows.append({"date": _ts(d), "permaticker": pt, "ranked": True,
                         "momentum": 0.1 * i, "value": -0.1 * i, "quality": 0.2,
                         "lowvol": 0.0, "size": 0.05 * i})
    return pd.DataFrame(rows)


def test_asof_after_T():
    print("\n[3] a filing dated after T is not used at T")
    feats = pd.DataFrame([
        {"permaticker": "P", "acceptance_date": _ts("2010-02-10"), "mdna_tone": 0.5},
        {"permaticker": "P", "acceptance_date": _ts("2010-05-12"), "mdna_tone": -0.5},
    ])
    ranked = _ranked_frame(["2010-01-31", "2010-03-31"], ["P"])
    joined = asof_join(ranked, feats, ["mdna_tone"])
    at_jan = joined[joined.date == _ts("2010-01-31")].iloc[0]
    at_mar = joined[joined.date == _ts("2010-03-31")].iloc[0]
    check("before any filing -> no_filing / NaN", at_jan["llm_status"] == "no_filing"
          and pd.isna(at_jan["mdna_tone"]))
    check("at T uses the prior (Feb) filing, not the later (May) one",
          at_mar["llm_status"] == "ok" and at_mar["mdna_tone"] == 0.5, str(at_mar["mdna_tone"]))


def test_strictly_before_T():
    print("\n[4] strictly-before-T: a filing accepted exactly on T is not used at T")
    feats = pd.DataFrame([
        {"permaticker": "P", "acceptance_date": _ts("2010-03-31"), "mdna_tone": 0.7},
    ])
    ranked = _ranked_frame(["2010-03-31", "2010-04-30"], ["P"])
    joined = asof_join(ranked, feats, ["mdna_tone"])
    at_T = joined[joined.date == _ts("2010-03-31")].iloc[0]
    at_next = joined[joined.date == _ts("2010-04-30")].iloc[0]
    check("filing on T not used at T", at_T["llm_status"] == "no_filing" and pd.isna(at_T["mdna_tone"]))
    check("filing used at the next rebalance", at_next["llm_status"] == "ok"
          and at_next["mdna_tone"] == 0.7)


def test_staleness():
    print(f"\n[5] staleness cap (18 months = {_STALENESS_DAYS} days) -> NaN")
    feats = pd.DataFrame([
        {"permaticker": "P", "acceptance_date": _ts("2008-01-15"), "mdna_tone": 0.3},
    ])
    ranked = _ranked_frame(["2009-03-31", "2010-06-30"], ["P"])
    joined = asof_join(ranked, feats, ["mdna_tone"])
    fresh = joined[joined.date == _ts("2009-03-31")].iloc[0]
    stale = joined[joined.date == _ts("2010-06-30")].iloc[0]
    check("within 18mo used", fresh["llm_status"] == "ok" and fresh["mdna_tone"] == 0.3)
    check("beyond 18mo -> stale / NaN", stale["llm_status"] == "stale" and pd.isna(stale["mdna_tone"]))


def test_nan_fallback_not_fill():
    print("\n[6] NaN fall-back (not fill): ranked name w/o filing keeps factors, NaN LLM")
    feats = pd.DataFrame([
        {"permaticker": "HASFILING", "acceptance_date": _ts("2010-02-10"),
         **{c: 0.4 for c in elf.FEATURE_COLS}},
    ])
    ranked = _ranked_frame(["2010-03-31"], ["HASFILING", "NOFILING"])
    joined = asof_join(ranked, feats, elf.FEATURE_COLS)
    normed = elf.normalize_within_date(joined)
    matrix = elf.m2_feature_matrix(normed)
    rep = elf.nan_llm_report(normed)

    nofile = normed[normed.permaticker == "NOFILING"].iloc[0]
    check("no-filing name keeps mechanical factors",
          nofile["momentum"] == 0.1 and not pd.isna(nofile["size"]))
    check("no-filing LLM feature is NaN, not 0",
          pd.isna(nofile["mdna_tone"]) and pd.isna(nofile["mdna_tone_z"]))
    check("M2 matrix carries mechanical + *_z columns",
          "momentum" in matrix.columns and "mdna_tone_z" in matrix.columns)
    check("nan_llm report counts the gap", rep["nan_llm"] == 1 and rep["with_llm"] == 1, str(rep))


# ---------------------------------------------------------------------------
_FILLER = ("The registrant continued operations across its segments and describes "
           "the period in narrative detail with sufficient length to exceed the "
           "minimum-section threshold used by the deterministic parser. ") * 4


def _modern_10k_html():
    return f"""<html><body>
    <table><tr><td>Item 1A. Risk Factors</td><td>5</td></tr>
    <tr><td>Item 1B. Unresolved Staff Comments</td><td>9</td></tr>
    <tr><td>Item 2. Properties</td><td>10</td></tr>
    <tr><td>Item 7. Management's Discussion and Analysis</td><td>20</td></tr>
    <tr><td>Item 7A. Quantitative Disclosures</td><td>40</td></tr>
    <tr><td>Item 8. Financial Statements</td><td>41</td></tr></table>
    <p>Item 1A. Risk Factors</p>
    <p>Our business faces material risks including competition and regulation. {_FILLER}
    We may be adversely affected by litigation and by liquidity constraints.</p>
    <p>Item 1B. Unresolved Staff Comments</p><p>None.</p>
    <p>Item 2. Properties</p><p>We lease offices.</p>
    <p>Item 7. Management&#8217;s Discussion and Analysis of Financial Condition</p>
    <p>See Item 8 for the financial statements referenced below. Revenue rose and
    management discusses results of operations and liquidity. {_FILLER}
    Cash flow and capital resources are described here at length.</p>
    <p>Item 7A. Quantitative Disclosures</p><p>Market risk.</p>
    <p>Item 8. Financial Statements</p><p>See attached.</p>
    </body></html>"""


def _old_10k_txt():
    body = f"""
    PART I
    Item 1. Business
    The Company operates in one segment.
    Item 2. Properties
    The Company owns facilities.
    PART II
    Item 7. Management's Discussion and Analysis of Financial Condition and Results
    Results of operations improved during the year and management discusses
    liquidity and capital resources. {_FILLER}
    Item 8. Financial Statements and Supplementary Data
    Reference is made to the financial statements.
    """
    return f"""<SEC-DOCUMENT>0000912057-99-001234.txt
    <DOCUMENT><TYPE>10-K<SEQUENCE>1<TEXT>{body}</TEXT></DOCUMENT>
    <DOCUMENT><TYPE>EX-27<SEQUENCE>2<TEXT>financial data schedule</TEXT></DOCUMENT>
    </SEC-DOCUMENT>"""


def test_sections_both_formats():
    print("\n[7] section extraction on modern HTML and old .txt; pre-2006 no Item 1A")
    modern = sec.extract_sections(_modern_10k_html(), "10-K", is_html=True)
    check("HTML: MD&A found", modern["mdna"] is not None and "results of operations" in modern["mdna"].lower())
    check("HTML: Risk Factors found", modern["risk_factors"] is not None
          and "material risks" in modern["risk_factors"].lower())
    check("HTML: MD&A did not swallow Item 8",
          modern["mdna"] is not None and "see attached" not in modern["mdna"].lower())

    old = sec.extract_sections(_old_10k_txt(), "10-K", is_html=False)
    check("old .txt: MD&A found", old["mdna"] is not None and "liquidity" in old["mdna"].lower())
    check("pre-2006 10-K: no Item 1A -> Risk Factors NaN/None (counted)",
          old["risk_factors"] is None)


def test_masking():
    print("\n[MASK] identity masking redacts name/ticker/CIK/dates")
    text = ("Washington Mutual Inc reported that in fiscal 2007 the Company's WM "
            "results improved; on March 31, 2008 the board met. CIK 0000933136.")
    masked = elf.mask_identity(text, name="Washington Mutual Inc", ticker="WM", cik=933136)
    check("company name redacted", "Washington" not in masked and "Mutual" not in masked, masked)
    check("ticker redacted", " WM " not in f" {masked} ", masked)
    check("years redacted", "2007" not in masked and "2008" not in masked, masked)
    check("explicit date redacted", "March 31" not in masked, masked)
    check("CIK redacted", "933136" not in masked, masked)
    check("descriptive words kept", "results improved" in masked)


# ---------------------------------------------------------------------------
def main():
    print("=" * 74)
    print("ENGINE B P4 SPEC 2 - SYNTHETIC INGESTION/ATTRIBUTION/JOIN/EXTRACTION SUITE")
    print("  synthetic only; no network, no real LLM (gates real extraction, Spec 2 sec 6)")
    print("=" * 74)
    test_ingest_helpers()
    test_attribution_successor()
    test_attribution_ambiguity()
    test_asof_after_T()
    test_strictly_before_T()
    test_staleness()
    test_nan_fallback_not_fill()
    test_sections_both_formats()
    test_masking()

    print("\n" + "=" * 74)
    if _FAILS:
        print(f"RESULT: {len(_FAILS)} FAILURE(S): {_FAILS}")
        sys.exit(1)
    print("RESULT: ALL CHECKS PASSED (synthetic). Safe to freeze/commit before any "
          "real EDGAR fetch or LLM extraction on Godzilla.")
    print("=" * 74)


if __name__ == "__main__":
    main()
