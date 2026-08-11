"""Engine B P4 (Spec 2) - LLM hindsight-leakage audit statistics.

Implements docs/ENGINE_B_P4_SPEC2.md section 5 with the a-priori-frozen constants.
Pure functions over numpy arrays, unit-tested in tests/test_edgar_audit.py. The
runner that joins each sampled filing to its forward-return label (from the panel)
and drives these tests lives in the full-extraction step; the DECISION RULES are
fixed here now so they cannot be tuned to a result.

A feature is DROPPED from M2 if it fails the masked hindsight-probe (5.1) or is
quarantined by the marginal-IC ceiling (5.2). If all features are rejected, the
LLM layer is dropped and Engine B ships on the mechanical baseline (reading A).
"""
from __future__ import annotations

import numpy as np
from scipy import stats

# Spec 2 sec 5.4 - frozen a priori (must not be changed to rescue a result)
PROBE_N = 1000
PROBE_SEED = 20260811
RHO_REJECT = 0.05
P_REJECT = 0.01
IDENTITY_SENS_K = 0.5          # flag if mean|shift| > K * feature SD
SINGLE_FEATURE_IC_CEIL = 0.08
GROUP_IC_CEIL = 0.10
LEXICON_AGREE_FLOOR = 0.40


def _finite_pair(a, b):
    a = np.asarray(a, float)
    b = np.asarray(b, float)
    m = np.isfinite(a) & np.isfinite(b)
    return a[m], b[m]


def masked_probe(shift, fwd_ret, rho_thresh=RHO_REJECT, p_thresh=P_REJECT) -> dict:
    """5.1 - does the masked-vs-unmasked feature shift correlate with the forward
    return? Reject the feature if |rho| >= rho_thresh AND p < p_thresh (identity
    is smuggling hindsight through it)."""
    x, y = _finite_pair(shift, fwd_ret)
    if len(x) < 20 or np.std(x) == 0 or np.std(y) == 0:
        return {"rho": float("nan"), "p": float("nan"), "n": int(len(x)), "reject": False}
    rho, p = stats.spearmanr(x, y)
    reject = bool(abs(rho) >= rho_thresh and p < p_thresh)
    return {"rho": float(rho), "p": float(p), "n": int(len(x)), "reject": reject}


def identity_sensitivity(shift, feature_values, k=IDENTITY_SENS_K) -> dict:
    """5.1 magnitude flag - a large masked-vs-unmasked shift relative to the
    feature's own SD is a smell even if it does not linearly track returns."""
    s, _ = _finite_pair(shift, shift)
    fv = np.asarray(feature_values, float)
    fv = fv[np.isfinite(fv)]
    sd = float(np.std(fv)) if len(fv) > 1 else float("nan")
    mean_abs = float(np.mean(np.abs(s))) if len(s) else float("nan")
    flag = bool(np.isfinite(sd) and sd > 0 and mean_abs > k * sd)
    return {"mean_abs_shift": mean_abs, "feature_sd": sd, "flag": flag}


def within_date_mean_ic(dates, scores, fwd_ret) -> float:
    """A single feature's mean within-date Spearman rank-IC vs the forward return."""
    dates = np.asarray(dates)
    scores = np.asarray(scores, float)
    fwd = np.asarray(fwd_ret, float)
    ics = []
    for d in np.unique(dates):
        m = (dates == d) & np.isfinite(scores) & np.isfinite(fwd)
        if m.sum() >= 5 and np.std(scores[m]) > 0 and np.std(fwd[m]) > 0:
            ics.append(stats.spearmanr(scores[m], fwd[m]).correlation)
    return float(np.nanmean(ics)) if ics else float("nan")


def ic_ceiling(mean_ic, ceil=SINGLE_FEATURE_IC_CEIL) -> dict:
    """5.2 - a single feature whose |mean IC| exceeds the ceiling is assumed leaking
    (too-good) and is quarantined until an enhanced probe clears it."""
    quarantine = bool(np.isfinite(mean_ic) and abs(mean_ic) > ceil)
    return {"mean_ic": float(mean_ic), "ceiling": ceil, "quarantine": quarantine}


def lexicon_agreement(llm_tone, lm_tone, floor=LEXICON_AGREE_FLOOR) -> dict:
    """5.3 - the LLM tone must agree with a deterministic Loughran-McDonald lexicon
    tone (which cannot have hindsight). Spearman below the floor => the LLM tone is
    not tracking the actual document language; flag for review."""
    x, y = _finite_pair(llm_tone, lm_tone)
    if len(x) < 20 or np.std(x) == 0 or np.std(y) == 0:
        return {"spearman": float("nan"), "n": int(len(x)), "agrees": False}
    rho = stats.spearmanr(x, y).correlation
    return {"spearman": float(rho), "n": int(len(x)), "agrees": bool(rho >= floor)}


def lm_tone(text: str, lm_negative: set, lm_positive: set) -> float:
    """Deterministic Loughran-McDonald net tone = (pos - neg) / total finance words
    in the text. Hindsight-free by construction. Word lists are supplied by the
    caller (the LM master dictionary loaded on Godzilla)."""
    if not text:
        return float("nan")
    words = [w.strip(".,;:()[]\"'").upper() for w in text.split()]
    pos = sum(w in lm_positive for w in words)
    neg = sum(w in lm_negative for w in words)
    tot = pos + neg
    return float((pos - neg) / tot) if tot else 0.0
