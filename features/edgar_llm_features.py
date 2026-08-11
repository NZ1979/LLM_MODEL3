"""Engine B P4 (Spec 2) - the LLM feature layer: masking, extraction, and the
within-date normalisation + join into the Spec 1 M2 feature matrix.

Implements docs/ENGINE_B_P4_SPEC2.md sections 4-5. Ten document-descriptive,
LLM-scored features (so Spec 1's no-LLM honesty gate cleanly isolates the LLM).
Production features are extracted from IDENTITY-MASKED text; the masked-vs-unmasked
hindsight probe (section 5) is the load-bearing leakage guard. The real extractor
(Anthropic) runs ONLY on Godzilla .venv; the deterministic masking and the join
are unit-tested in the sandbox with a StubExtractor.

The LLM is a feature extractor whose marginal IC is measured, NEVER the predictor
(charter 1). The prompt forbids predicting returns or using any post-filing
knowledge.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import numpy as np
import pandas as pd

from models.engine_b_factors import _winsorize_z

# Spec 2 sec 4.5 (addendum) - section-length truncation, fixed a priori. Sections
# run 350 chars .. ~214k chars (smoke test); the largest is ~50k tokens.
HEAD_CHARS = 12000
TAIL_CHARS = 4000
TRUNC_MARK = "\n\n...[SECTION TRUNCATED - MIDDLE OMITTED]...\n\n"

# which features come from which section (used to enforce NaN when a section or a
# prior filing is absent - Spec 2 sec 3/4.1)
MDNA_FEATS = ("mdna_tone", "mdna_forward_tone", "mdna_uncertainty",
              "mdna_complexity", "mdna_liquidity_stress", "mdna_change")
RF_FEATS = ("rf_severity", "rf_specificity", "rf_litigation", "rf_change")
CHANGE_FEATS = {"mdna_change": "prior_mdna", "rf_change": "prior_rf"}

# Spec 2 sec 4.1 - the ten features (name, low, high). All document-descriptive.
FEATURE_RANGES = {
    "mdna_tone": (-1.0, 1.0),
    "mdna_forward_tone": (-1.0, 1.0),
    "mdna_uncertainty": (0.0, 1.0),
    "mdna_complexity": (0.0, 1.0),
    "mdna_liquidity_stress": (0.0, 1.0),
    "mdna_change": (0.0, 1.0),          # vs prior MD&A; NaN for first filing
    "rf_severity": (0.0, 1.0),
    "rf_specificity": (0.0, 1.0),
    "rf_litigation": (0.0, 1.0),
    "rf_change": (0.0, 1.0),            # vs prior Risk Factors; NaN for first filing
}
FEATURE_COLS = list(FEATURE_RANGES)

# Spec 2 sec 4.4 - fixed, versioned. The prompt NEVER contains ticker/name/date/price.
PROMPT_VERSION = "p4s2-v1"
SYSTEM_PROMPT = (
    "You are a financial-document analyst. You are given an excerpt from a "
    "company's SEC filing (its Management's Discussion and Analysis, or its Risk "
    "Factors) as written on an unknown historical date. The company's name and all "
    "dates have been removed. Score ONLY what this text says, as a careful reader "
    "on the filing date would - describe the document, do not judge whether it is "
    "good or bad news for an investor. You must NOT try to identify the company or "
    "the date. You must NOT predict or imply anything about future stock returns, "
    "prices, performance, bankruptcy, or any outcome after the filing. If you find "
    "yourself using knowledge of what happened to any company, stop and score only "
    "the words on the page. Return ONLY the requested JSON scores."
)


# ---------------------------------------------------------------------------
# Identity masking (deterministic; Spec 2 sec 4.3). Production = masked text.
# ---------------------------------------------------------------------------
_YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")
_DATE_RE = re.compile(
    r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+\d{1,2},?\s*(?:\b(?:19|20)\d{2}\b)?",
    re.IGNORECASE)
_NUMERIC_DATE_RE = re.compile(r"\b\d{1,2}/\d{1,2}/\d{2,4}\b")


def _name_tokens(name: str) -> list[str]:
    """Distinctive tokens of a registrant name, minus corporate-suffix noise."""
    stop = {"inc", "corp", "corporation", "company", "co", "ltd", "llc", "lp",
            "plc", "the", "and", "of", "group", "holdings", "holding", "trust",
            "sa", "nv", "ag", "class", "common", "stock", "&"}
    toks = re.findall(r"[A-Za-z][A-Za-z\-']+", str(name or ""))
    return [t for t in toks if len(t) >= 3 and t.lower() not in stop]


def mask_identity(text: str, name: str | None = None, ticker: str | None = None,
                  cik=None, extra_aliases: list[str] | None = None) -> str:
    """Redact registrant name tokens, ticker, CIK, and all dates/years. Dollar
    amounts and operational descriptors are kept (descriptive, not identity)."""
    if text is None:
        return None
    out = text
    aliases = list(extra_aliases or [])
    aliases += _name_tokens(name)
    # longest-first so multi-word names redact before their fragments
    for a in sorted({a for a in aliases if a}, key=len, reverse=True):
        out = re.sub(rf"\b{re.escape(a)}\b", "[COMPANY]", out, flags=re.IGNORECASE)
    if ticker:
        out = re.sub(rf"\b{re.escape(str(ticker))}\b", "[TICKER]", out)
    if cik is not None and str(cik).strip():
        out = re.sub(rf"\b0*{re.escape(str(int(str(cik))))}\b", "[CIK]", out)
    out = _DATE_RE.sub("[DATE]", out)
    out = _NUMERIC_DATE_RE.sub("[DATE]", out)
    out = _YEAR_RE.sub("[YEAR]", out)
    return out


# ---------------------------------------------------------------------------
# Extractor interface. Real = Anthropic (Godzilla). Stub = deterministic (tests).
# ---------------------------------------------------------------------------
class BaseExtractor:
    def extract(self, mdna: str | None, risk_factors: str | None,
                prior_mdna: str | None, prior_risk_factors: str | None) -> dict:
        raise NotImplementedError

    def _clip(self, values: dict) -> dict:
        out = {}
        for k, (lo, hi) in FEATURE_RANGES.items():
            v = values.get(k, np.nan)
            if v is None or (isinstance(v, float) and not np.isfinite(v)):
                out[k] = np.nan
            else:
                out[k] = float(min(max(float(v), lo), hi))
        # change features require a prior; enforced by the caller passing None prior
        return out


class StubExtractor(BaseExtractor):
    """Deterministic surrogate for sandbox tests - maps text statistics to bounded
    features. NOT a real signal; only exercises the masking/join/normalisation
    plumbing without any network or model."""
    def extract(self, mdna, risk_factors, prior_mdna, prior_risk_factors) -> dict:
        def dens(t, word):
            if not t:
                return np.nan
            toks = t.split()
            return float(min(1.0, sum(w.lower().startswith(word) for w in toks) / max(1, len(toks)) * 20))

        def tone(t):
            return np.nan if not t else float(np.tanh((len(t) % 7 - 3) / 3.0))

        def change(cur, prior):
            if not cur or not prior:
                return np.nan
            a, b = set(cur.lower().split()), set(prior.lower().split())
            return float(1.0 - len(a & b) / max(1, len(a | b)))

        vals = {
            "mdna_tone": tone(mdna),
            "mdna_forward_tone": tone(mdna),
            "mdna_uncertainty": dens(mdna, "may"),
            "mdna_complexity": np.nan if not mdna else float(min(1.0, len(mdna) / 5000.0)),
            "mdna_liquidity_stress": dens(mdna, "liquid"),
            "mdna_change": change(mdna, prior_mdna),
            "rf_severity": dens(risk_factors, "risk"),
            "rf_specificity": np.nan if not risk_factors else float(1.0 - dens(risk_factors, "general")),
            "rf_litigation": dens(risk_factors, "litig"),
            "rf_change": change(risk_factors, prior_risk_factors),
        }
        return self._clip(vals)


# ---------------------------------------------------------------------------
# Truncation + prompt assembly + the real Anthropic extractor (Godzilla only)
# ---------------------------------------------------------------------------
def truncate_section(text):
    """Head 12k + tail 4k chars (Spec 2 sec 4.5). Returns (text_or_None, truncated)."""
    if text is None:
        return None, False
    if len(text) <= HEAD_CHARS + TAIL_CHARS:
        return text, False
    return text[:HEAD_CHARS] + TRUNC_MARK + text[-TAIL_CHARS:], True


def prepare_for_extraction(section, name=None, ticker=None, cik=None, mask=True):
    """Mask identity (production default) then truncate. Returns (text, truncated)."""
    if section is None:
        return None, False
    t = mask_identity(section, name=name, ticker=ticker, cik=cik) if mask else section
    return truncate_section(t)


# Per-feature rubric shown to the model via the tool schema. Purely descriptive;
# no field may reference price, return, or any post-filing outcome (Spec 2 sec 4).
RUBRICS = {
    "mdna_tone": "Overall tone of the results and business conditions as described in the MD&A: -1 very negative, 0 neutral, +1 very positive. Describe the language, not investment merit.",
    "mdna_forward_tone": "Tone of the forward-looking statements as written (expectations, plans, outlook): -1 to +1. Not a return forecast.",
    "mdna_uncertainty": "Density of hedging / uncertainty / 'cannot predict' / 'depends on' language in the MD&A: 0 none, 1 pervasive.",
    "mdna_complexity": "Readability/obfuscation of the MD&A: 0 plain and clear, 1 dense, jargon-heavy, convoluted.",
    "mdna_liquidity_stress": "Prominence of liquidity, going-concern, covenant or financing-stress language in the MD&A: 0 none, 1 dominant.",
    "mdna_change": "Magnitude of change of this MD&A versus the prior filing's MD&A provided: 0 essentially identical, 1 substantially rewritten. Score only if a prior MD&A is provided.",
    "rf_severity": "Overall gravity/severity of the risks as described in the Risk Factors: 0 mild, 1 grave.",
    "rf_specificity": "How company-specific vs boilerplate the Risk Factors read: 0 generic boilerplate, 1 highly specific.",
    "rf_litigation": "Prominence of litigation / regulatory / legal-exposure language in the Risk Factors: 0 none, 1 dominant.",
    "rf_change": "Magnitude of change of these Risk Factors versus the prior filing's Risk Factors provided: 0 identical, 1 substantially changed. Score only if prior Risk Factors are provided.",
}

SCORE_TOOL = {
    "name": "score_filing",
    "description": ("Return document-descriptive scores for the filing text. Score ONLY "
                    "what the text says. Do not identify the company or date. Do not "
                    "predict returns or any outcome after the filing. Omit any field "
                    "whose source section was not provided."),
    "input_schema": {
        "type": "object",
        "properties": {f: {"type": "number", "description": RUBRICS[f]} for f in FEATURE_COLS},
        "required": [],
        "additionalProperties": False,
    },
}


def build_user_prompt(mdna, rf, prior_mdna, prior_rf) -> str:
    """Assemble the user message from masked+truncated section texts. Contains NO
    ticker/name/date/price - the inputs are pre-masked (Spec 2 sec 4.3/4.4)."""
    p = ["Score the filing text below by calling score_filing. Score only sections "
         "that are present; omit fields for any section marked NOT PRESENT.", ""]
    p += (["=== MD&A (current) ===", mdna, ""] if mdna
          else ["=== MD&A: NOT PRESENT (omit mdna_tone/forward_tone/uncertainty/complexity/liquidity_stress) ===", ""])
    p += (["=== RISK FACTORS (current) ===", rf, ""] if rf
          else ["=== RISK FACTORS: NOT PRESENT (omit rf_severity/specificity/litigation) ===", ""])
    p += (["=== MD&A (prior filing, for mdna_change) ===", prior_mdna, ""] if prior_mdna
          else ["=== No prior MD&A (omit mdna_change) ===", ""])
    p += (["=== RISK FACTORS (prior filing, for rf_change) ===", prior_rf, ""] if prior_rf
          else ["=== No prior Risk Factors (omit rf_change) ===", ""])
    return "\n".join(p)


def _tool_input(resp) -> dict:
    """Pull the score_filing tool_use input from an Anthropic Messages response."""
    for block in (getattr(resp, "content", None) or []):
        if getattr(block, "type", None) == "tool_use" and getattr(block, "name", "") == SCORE_TOOL["name"]:
            return dict(getattr(block, "input", None) or {})
    return {}


class AnthropicExtractor(BaseExtractor):
    """Real LLM feature extractor (Godzilla .venv; needs `anthropic` + ANTHROPIC_API_KEY).

    Receives sections ALREADY masked + truncated by the runner. temperature=0,
    forced structured tool output, content-hash disk cache so re-runs are free and
    the feature corpus is frozen (Spec 2 sec 4.2). The model id + cutoff are the
    caller's responsibility to record in run metadata (Spec 2 sec 4.2 / charter).
    """
    def __init__(self, model: str, cache_dir=None, max_tokens: int = 1024, client=None):
        if not model:
            raise ValueError("AnthropicExtractor: model id required and recorded (Spec 2 sec 4.2). "
                             "Set it explicitly / via env; do not default silently.")
        self.model = model
        self.cache_dir = Path(cache_dir) if cache_dir else None
        self.max_tokens = max_tokens
        self._client = client
        self.calls = 0
        self.cache_hits = 0

    def _client_or_make(self):
        if self._client is None:
            import anthropic  # lazy - Godzilla only
            self._client = anthropic.Anthropic()   # reads ANTHROPIC_API_KEY from env
        return self._client

    def _cache_key(self, mdna, rf, prior_mdna, prior_rf) -> str:
        payload = json.dumps([self.model, PROMPT_VERSION, mdna, rf, prior_mdna, prior_rf],
                             ensure_ascii=False)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def extract(self, mdna, rf, prior_mdna, prior_rf) -> dict:
        if not mdna and not rf:
            return {f: np.nan for f in FEATURE_COLS}     # nothing to score, no API call
        if self.cache_dir is not None:
            cp = self.cache_dir / f"{self._cache_key(mdna, rf, prior_mdna, prior_rf)}.json"
            if cp.exists():
                self.cache_hits += 1
                return self._finalize(json.loads(cp.read_text()), mdna, rf, prior_mdna, prior_rf)
        resp = self._client_or_make().messages.create(
            model=self.model, max_tokens=self.max_tokens, temperature=0,
            system=SYSTEM_PROMPT, tools=[SCORE_TOOL],
            tool_choice={"type": "tool", "name": SCORE_TOOL["name"]},
            messages=[{"role": "user",
                       "content": build_user_prompt(mdna, rf, prior_mdna, prior_rf)}])
        raw = _tool_input(resp)
        self.calls += 1
        if self.cache_dir is not None:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            (self.cache_dir / f"{self._cache_key(mdna, rf, prior_mdna, prior_rf)}.json").write_text(json.dumps(raw))
        return self._finalize(raw, mdna, rf, prior_mdna, prior_rf)

    def _finalize(self, raw, mdna, rf, prior_mdna, prior_rf) -> dict:
        vals = self._clip(raw if isinstance(raw, dict) else {})
        # enforce NaN where the source section / prior is absent - never let a score
        # stand for text the model did not see (Spec 2 sec 3/4.1)
        if not mdna:
            for f in MDNA_FEATS:
                vals[f] = np.nan
        if not rf:
            for f in RF_FEATS:
                vals[f] = np.nan
        if not prior_mdna:
            vals["mdna_change"] = np.nan
        if not prior_rf:
            vals["rf_change"] = np.nan
        return vals


# ---------------------------------------------------------------------------
# Normalise (within-date winsor+z) and join into the M2 feature matrix
# ---------------------------------------------------------------------------
def normalize_within_date(joined: pd.DataFrame, feature_cols: list[str] = FEATURE_COLS,
                          ranked_only: bool = True) -> pd.DataFrame:
    """Cross-sectionally winsorise (+/-3 SD) then z-score each raw LLM feature
    WITHIN each date's ranked universe - identical transform to the mechanical
    factors (reuse engine_b_factors._winsorize_z). No cross-date statistic is fit,
    so nothing leaks across the train/test boundary (Spec 1 / Spec 2 sec 3). NaN
    stays NaN. Adds `<feat>_z` columns."""
    df = joined.copy()
    mask = df["ranked"] if (ranked_only and "ranked" in df.columns) else pd.Series(True, index=df.index)
    for c in feature_cols:
        zc = f"{c}_z"
        df[zc] = np.nan
        sub = df[mask]
        parts = []
        for _, g in sub.groupby("date", sort=False):
            parts.append(_winsorize_z(g[c].astype(float)))
        if parts:
            z = pd.concat(parts)
            df.loc[z.index, zc] = z.values
    return df


def m2_feature_matrix(scores_with_llm: pd.DataFrame,
                      mechanical=("momentum", "value", "quality", "lowvol", "size"),
                      feature_cols: list[str] = FEATURE_COLS) -> pd.DataFrame:
    """The M2 design matrix: the five mechanical z-scores + the normalised LLM
    z-scores, on the ranked rows. LightGBM consumes NaN natively (a NaN-LLM name
    is scored on its mechanical factors alone = M1 behaviour, Spec 2 sec 3)."""
    z_cols = [f"{c}_z" for c in feature_cols]
    cols = ["date", "permaticker", *mechanical, *z_cols]
    have = [c for c in cols if c in scores_with_llm.columns]
    r = scores_with_llm
    if "ranked" in r.columns:
        r = r[r["ranked"]]
    return r[have].reset_index(drop=True)


def nan_llm_report(scores_with_llm: pd.DataFrame, feature_cols: list[str] = FEATURE_COLS) -> dict:
    """Count NaN-LLM name-months among ranked rows (Rule 18)."""
    r = scores_with_llm
    if "ranked" in r.columns:
        r = r[r["ranked"]]
    z_cols = [f"{c}_z" for c in feature_cols if f"{c}_z" in r.columns]
    any_feat = r[z_cols].notna().any(axis=1) if z_cols else pd.Series(False, index=r.index)
    return {"ranked_name_months": int(len(r)),
            "with_llm": int(any_feat.sum()),
            "nan_llm": int((~any_feat).sum())}
