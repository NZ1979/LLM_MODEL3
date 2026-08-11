"""Engine B P4 (Spec 2) - hindsight-leakage audit statistics suite (synthetic).

Confirms the frozen decision rules (sec 5) behave: a return-correlated masked-shift
is rejected, an uncorrelated one is kept; the IC ceiling quarantines a too-good
feature; lexicon agreement gates a divergent LLM tone. No network. Rule-18 hard
PASS/FAIL.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from features import edgar_audit as aud   # noqa: E402

_FAILS: list[str] = []


def check(name, cond, detail=""):
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" :: {detail}" if detail else ""))
    if not cond:
        _FAILS.append(name)


def main():
    print("=" * 74)
    print("ENGINE B P4 SPEC 2 - HINDSIGHT-LEAKAGE AUDIT STATS SUITE (synthetic)")
    print("=" * 74)
    rng = np.random.default_rng(20260811)
    n = 800

    print("\n[5.1] masked hindsight-probe")
    fwd = rng.normal(size=n)
    leak_shift = 0.6 * fwd + 0.4 * rng.normal(size=n)     # shift tracks the future
    clean_shift = rng.normal(size=n)                       # shift independent of future
    r_leak = aud.masked_probe(leak_shift, fwd)
    r_clean = aud.masked_probe(clean_shift, fwd)
    check("return-correlated shift REJECTED", r_leak["reject"] is True, str(r_leak))
    check("independent shift KEPT", r_clean["reject"] is False, str(r_clean))

    print("\n[5.1] identity-sensitivity magnitude flag")
    feat = rng.normal(scale=1.0, size=n)
    big = rng.normal(scale=1.0, size=n)      # mean|shift| ~0.8 > 0.5*sd(feat~1)
    small = rng.normal(scale=0.1, size=n)
    check("large shift flagged", aud.identity_sensitivity(big, feat)["flag"] is True)
    check("small shift not flagged", aud.identity_sensitivity(small, feat)["flag"] is False)

    print("\n[5.2] marginal-IC ceiling")
    check("IC 0.12 quarantined", aud.ic_ceiling(0.12)["quarantine"] is True)
    check("IC 0.03 clean", aud.ic_ceiling(0.03)["quarantine"] is False)

    # within-date IC: planted monotone signal -> positive
    dates = np.repeat(np.arange(20), 30)
    sc = rng.normal(size=dates.size)
    fw = sc * 0.5 + rng.normal(scale=0.5, size=dates.size)
    ic = aud.within_date_mean_ic(dates, sc, fw)
    check("within-date mean IC positive on planted signal", ic > 0.2, f"{ic:.3f}")

    print("\n[5.3] Loughran-McDonald lexicon agreement + tone")
    base = rng.normal(size=n)
    agree = base + 0.3 * rng.normal(size=n)
    indep = rng.normal(size=n)
    check("agreeing tones pass floor", aud.lexicon_agreement(base, agree)["agrees"] is True)
    check("independent tones fail floor", aud.lexicon_agreement(base, indep)["agrees"] is False)
    neg, pos = {"LOSS", "DECLINE", "RISK"}, {"GROWTH", "GAIN", "STRONG"}
    t = aud.lm_tone("Strong growth and gain despite some risk.", neg, pos)
    check("lm_tone positive when positive words dominate", t > 0, f"{t:.3f}")

    print("\n" + "=" * 74)
    if _FAILS:
        print(f"RESULT: {len(_FAILS)} FAILURE(S): {_FAILS}")
        sys.exit(1)
    print("RESULT: ALL CHECKS PASSED. Audit decision rules frozen and behaving.")
    print("=" * 74)


if __name__ == "__main__":
    main()
