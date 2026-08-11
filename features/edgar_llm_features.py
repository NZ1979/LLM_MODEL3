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

import re

import numpy as np
import pandas as pd

from models.engine_b_factors import _winsorize_z

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
