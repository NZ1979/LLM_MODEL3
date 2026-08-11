"""Engine B P4 (Spec 2) - deterministic MD&A / Risk-Factors section extraction.

Implements docs/ENGINE_B_P4_SPEC2.md section 1.3. Extraction is MECHANICAL (regex
over parsed text), NEVER the LLM, so the point-in-time boundary of what text
belongs to a filing is set by a parser that cannot hallucinate or peek. Handles
BOTH modern HTML / inline-XBRL and old plain-.txt SGML filings.

Coverage honesty (Rule 18): Risk Factors (Item 1A) was mandatory only for 10-K
fiscal years ending after 2005-12-01, so pre-2006 10-Ks legitimately have no Risk
Factors section -> that section returns None and is COUNTED, never zero-filled.
"""
from __future__ import annotations

import re

MIN_SECTION_CHARS = 200   # a located span shorter than this is a TOC artefact -> None

try:
    from bs4 import BeautifulSoup
    _HAVE_BS4 = True
except Exception:   # pragma: no cover - lxml/bs4 present on Godzilla .venv
    _HAVE_BS4 = False


# ---------------------------------------------------------------------------
# Text extraction from the two on-disk formats
# ---------------------------------------------------------------------------
def html_to_text(html: str) -> str:
    """Render filing HTML / inline-XBRL to plain text with block separators."""
    if _HAVE_BS4:
        soup = BeautifulSoup(html, "lxml")
        for tag in soup(["script", "style"]):
            tag.decompose()
        text = soup.get_text("\n")
    else:   # regex fallback (used only if bs4/lxml missing)
        text = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", html)
        text = re.sub(r"(?s)<[^>]+>", "\n", text)
    text = re.sub(r"&nbsp;", " ", text, flags=re.I)
    text = re.sub(r"&amp;", "&", text, flags=re.I)
    text = re.sub(r"&#\d+;", " ", text)
    return _normalize_ws(text)


_DOC_RE = re.compile(r"(?is)<DOCUMENT>(.*?)</DOCUMENT>")
_TYPE_RE = re.compile(r"(?is)<TYPE>\s*([^\s<]+)")
_TEXT_RE = re.compile(r"(?is)<TEXT>(.*?)</TEXT>")


def sgml_primary_text(sgml: str, form: str) -> str:
    """Extract the primary 10-K/10-Q document body from an old full-submission
    .txt (SGML). Picks the <DOCUMENT> whose <TYPE> matches the qualifying form;
    falls back to the first/largest document body if none matches."""
    from data.edgar_ingest import base_form
    want = base_form(form)
    candidates = []
    for block in _DOC_RE.findall(sgml):
        tm = _TYPE_RE.search(block)
        dtype = (tm.group(1).upper() if tm else "")
        body_m = _TEXT_RE.search(block)
        body = body_m.group(1) if body_m else ""
        candidates.append((dtype, body))
    if not candidates:
        body = sgml
    else:
        matched = [b for t, b in candidates if t == want or t.rstrip("/A") == want]
        body = max(matched, key=len) if matched else max((b for _, b in candidates), key=len)
    # strip any residual tags, decode a couple of entities
    body = re.sub(r"(?s)<[^>]+>", "\n", body)
    body = re.sub(r"&nbsp;", " ", body, flags=re.I)
    body = re.sub(r"&amp;", "&", body, flags=re.I)
    return _normalize_ws(body)


def _normalize_ws(text: str) -> str:
    text = text.replace("\xa0", " ").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n[ \t]*", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# ---------------------------------------------------------------------------
# Section location (the "longest candidate" heuristic beats the table-of-contents)
# ---------------------------------------------------------------------------
def _item_start(num: str, title: str | None = None) -> re.Pattern:
    """A start header like 'Item 7.' or 'Item 1A. Risk Factors'. Tolerant of
    whitespace/punctuation. If a title is given, require it near the number to
    reduce table-of-contents false hits."""
    core = rf"item\s*{num}\s*[\.\:\)\-]?"
    if title:
        core += rf"\s*{title}"
    return re.compile(core, re.IGNORECASE)


def _first_of(*nums_titles) -> re.Pattern:
    """An end header matching the first of several 'Item N' markers."""
    alts = []
    for num in nums_titles:
        alts.append(rf"item\s*{num}\s*[\.\:\)\-]?")
    return re.compile("|".join(alts), re.IGNORECASE)


def _locate(text: str, start_re: re.Pattern, end_re: re.Pattern) -> str | None:
    """All start positions; for each, the span to the next end marker after it;
    return the LONGEST span (the real section, not its TOC line). None if the best
    span is shorter than MIN_SECTION_CHARS (absent section)."""
    best = None
    for sm in start_re.finditer(text):
        s = sm.end()
        em = end_re.search(text, s)
        span = text[s:em.start()] if em else text[s:]
        if best is None or len(span) > len(best):
            best = span
    if best is None:
        return None
    best = best.strip()
    return best if len(best) >= MIN_SECTION_CHARS else None


def extract_sections(raw: str, form: str, is_html: bool) -> dict:
    """Return {'mdna': text|None, 'risk_factors': text|None} for a filing.

    Item map (Spec 2 sec 1.3):
      10-K*: MD&A = Item 7 -> Item 7A/8 ; Risk Factors = Item 1A -> Item 1B/2
      10-Q*: MD&A = Item 2 -> Item 3/4  ; Risk Factors = Item 1A -> next item
    """
    from data.edgar_ingest import base_form
    text = html_to_text(raw) if is_html else sgml_primary_text(raw, form)
    bf = base_form(form)

    if bf.startswith("10-Q"):
        mdna = _locate(text,
                       _item_start("2", r"management'?s"),
                       _first_of("3", "4"))
        rf = _locate(text,
                     _item_start("1A", r"risk\s+factors"),
                     _first_of("2", "3", "5", "6"))
    else:  # 10-K and all historical annual variants
        mdna = _locate(text,
                       _item_start("7", r"management'?s"),
                       _first_of("7A", "8"))
        rf = _locate(text,
                     _item_start("1A", r"risk\s+factors"),
                     _first_of("1B", "2"))
    return {"mdna": mdna, "risk_factors": rf}
