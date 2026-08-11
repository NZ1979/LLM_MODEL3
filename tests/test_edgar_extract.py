"""Engine B P4 (Spec 2) - LLM extractor logic suite (no network, no real LLM).

Exercises truncation (sec 4.5), prompt assembly (no identity leak), the forced
structured-output parse, and the load-bearing NaN-enforcement + caching in
AnthropicExtractor via a FAKE Anthropic client. Gates the extractor before any
real API call. Hard PASS/FAIL, exits non-zero on failure (Rule 18).
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import numpy as np

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from features import edgar_llm_features as elf   # noqa: E402

_FAILS: list[str] = []


def check(name, cond, detail=""):
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" :: {detail}" if detail else ""))
    if not cond:
        _FAILS.append(name)


# --- fake Anthropic client (records calls, returns a forced tool_use block) ----
class _Block:
    def __init__(self, inp):
        self.type = "tool_use"
        self.name = elf.SCORE_TOOL["name"]
        self.input = inp


class _Resp:
    def __init__(self, inp):
        self.content = [_Block(inp)]


class FakeClient:
    def __init__(self, values):
        self._values = values
        self.calls = 0
        self.messages = self

    def create(self, **kwargs):   # mimics client.messages.create
        self.calls += 1
        self.last_kwargs = kwargs
        return _Resp(dict(self._values))


def test_truncation():
    print("\n[TRUNC] head 12k + tail 4k (Spec 2 sec 4.5)")
    short = "x" * 5000
    t, tr = elf.truncate_section(short)
    check("short section untouched", t == short and tr is False)
    long = "H" * 20000 + "T" * 5000
    t, tr = elf.truncate_section(long)
    check("long section truncated flag", tr is True)
    check("keeps 12k head + 4k tail + marker",
          t.startswith("H" * 12000) and t.endswith("T" * 4000) and elf.TRUNC_MARK in t,
          f"len={len(t)}")
    check("None section -> (None, False)", elf.truncate_section(None) == (None, False))


def test_prepare_and_prompt():
    print("\n[PREP] mask+truncate, prompt carries no identity")
    body = "Acme Corporation reported in 2019 that Acme’s liquidity improved. " + "z" * 30000
    masked, tr = elf.prepare_for_extraction(body, name="Acme Corporation", ticker="ACME", cik=12345)
    check("prepared text is masked", "Acme" not in masked and "[COMPANY]" in masked)
    check("prepared text truncated", tr is True and len(masked) <= elf.HEAD_CHARS + elf.TAIL_CHARS + len(elf.TRUNC_MARK))
    prompt = elf.build_user_prompt(masked, None, None, None)
    check("prompt marks Risk Factors absent", "RISK FACTORS: NOT PRESENT" in prompt)
    check("prompt marks no prior", "No prior MD&A" in prompt)
    check("prompt has no raw identity", "Acme" not in prompt and "ACME" not in prompt)


def test_extractor_nan_enforcement():
    print("\n[EXTRACT] NaN enforced for absent sections/priors; range clamped")
    # model (mischievously) returns all fields, some out of range
    allvals = {f: 0.5 for f in elf.FEATURE_COLS}
    allvals["mdna_tone"] = 5.0        # out of [-1,1] -> clamp to 1.0
    allvals["rf_severity"] = -3.0     # out of [0,1] -> clamp to 0.0
    fake = FakeClient(allvals)
    ext = elf.AnthropicExtractor(model="fake-model", client=fake)

    # only MD&A present, no RF, no priors
    out = ext.extract(mdna="some md and a text", rf=None, prior_mdna=None, prior_rf=None)
    check("mdna_tone clamped to 1.0", out["mdna_tone"] == 1.0, str(out["mdna_tone"]))
    check("RF features NaN when RF absent", all(np.isnan(out[f]) for f in elf.RF_FEATS))
    check("mdna_change NaN when no prior", np.isnan(out["mdna_change"]))
    check("present mdna feature kept", out["mdna_uncertainty"] == 0.5)

    # both sections absent -> no API call, all NaN
    calls_before = fake.calls
    out2 = ext.extract(mdna=None, rf=None, prior_mdna=None, prior_rf=None)
    check("no API call when both sections absent", fake.calls == calls_before)
    check("all NaN when nothing to score", all(np.isnan(out2[f]) for f in elf.FEATURE_COLS))

    # rf present + prior rf -> rf_change scored, clamped
    out3 = ext.extract(mdna=None, rf="risk text", prior_mdna=None, prior_rf="old risk text")
    check("rf_severity clamped to 0.0", out3["rf_severity"] == 0.0)
    check("rf_change scored when prior present", out3["rf_change"] == 0.5)
    check("mdna features NaN when mdna absent", all(np.isnan(out3[f]) for f in elf.MDNA_FEATS))


def test_extractor_cache():
    print("\n[CACHE] content-hash cache avoids re-calling the model")
    with tempfile.TemporaryDirectory() as d:
        fake = FakeClient({f: 0.3 for f in elf.FEATURE_COLS})
        ext = elf.AnthropicExtractor(model="fake-model", client=fake, cache_dir=d)
        a = ext.extract(mdna="text one", rf="risk one", prior_mdna=None, prior_rf=None)
        n1 = fake.calls
        b = ext.extract(mdna="text one", rf="risk one", prior_mdna=None, prior_rf=None)
        check("second identical call hits cache (no new API call)", fake.calls == n1)
        check("cache hit counter advanced", ext.cache_hits == 1)
        check("cached result matches", a["mdna_uncertainty"] == b["mdna_uncertainty"] == 0.3)
        check("different text triggers a new call",
              (ext.extract(mdna="text two", rf=None, prior_mdna=None, prior_rf=None) or True)
              and fake.calls == n1 + 1)


def main():
    print("=" * 74)
    print("ENGINE B P4 SPEC 2 - LLM EXTRACTOR LOGIC SUITE (no network, fake client)")
    print("=" * 74)
    test_truncation()
    test_prepare_and_prompt()
    test_extractor_nan_enforcement()
    test_extractor_cache()
    print("\n" + "=" * 74)
    if _FAILS:
        print(f"RESULT: {len(_FAILS)} FAILURE(S): {_FAILS}")
        sys.exit(1)
    print("RESULT: ALL CHECKS PASSED. Extractor logic safe; real run needs Godzilla "
          "+ anthropic + ANTHROPIC_API_KEY.")
    print("=" * 74)


if __name__ == "__main__":
    main()
