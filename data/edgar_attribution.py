"""Engine B P4 (Spec 2) - the leak-critical CIK->permaticker window attribution
and the point-in-time (date, permaticker) feature join.

Implements docs/ENGINE_B_P4_SPEC2.md sections 2-3. This is the CIK-level analogue
of the panel's ticker-recycling defence (data/sharadar_panel.py): a CIK can
persist through bankruptcy/merger and be re-named (WaMu CIK 933136 -> Mr. Cooper
COOP), so filings are attributed to a permaticker ONLY inside that permaticker's
[firstpricedate, lastpricedate] window, and used at rebalance T ONLY when the
acceptance date is strictly before T. Overlapping windows on one CIK fail loud;
filings in no window are dropped and counted; never trust EDGAR entityName.

Pure pandas, deterministic, fully exercised by tests/test_edgar_synthetic.py.
"""
from __future__ import annotations

import pandas as pd

from data.edgar_ingest import canon_cik

# Spec 2 sec 3 - a filing older than this at T is stale -> NaN features (counted).
STALENESS_CAP_MONTHS = 18
_STALENESS_DAYS = int(round(30.4375 * STALENESS_CAP_MONTHS))   # ~548 days


class AttributionAmbiguityError(Exception):
    """Raised (fail loud, Rule 18/19) when one accession maps to >1 permaticker -
    i.e. two permatickers share a CIK with OVERLAPPING price windows. The runner
    converts this to a non-zero exit + a SUSPECT artefact, never grafts."""


def _prep_bridge(bridge: pd.DataFrame) -> pd.DataFrame:
    b = bridge.copy()
    b["cik"] = b["cik"].map(canon_cik)
    b = b[b["cik"] != ""]
    b["firstpricedate"] = pd.to_datetime(b["firstpricedate"]).dt.normalize()
    b["lastpricedate"] = pd.to_datetime(b["lastpricedate"]).dt.normalize()
    return b[["permaticker", "cik", "firstpricedate", "lastpricedate"]]


def attribute_filings(filings: pd.DataFrame, bridge: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Attribute each filing to exactly one permaticker via (CIK match + window).

    filings: must carry `cik`, `accession`, `acceptance_date` (Timestamp).
    bridge:  `permaticker`, `cik`, `firstpricedate`, `lastpricedate`.

    Returns (attributed, stats):
      attributed - filings with a `permaticker` column, one row per accession, ONLY
                   rows whose acceptance date falls in exactly one permaticker's
                   window for its CIK.
      stats      - denominators for the coverage funnel (Rule 18).

    Raises AttributionAmbiguityError if any accession falls in >1 window.
    """
    f = filings.copy()
    f["cik"] = f["cik"].map(canon_cik)
    f["acceptance_date"] = pd.to_datetime(f["acceptance_date"]).dt.normalize()
    b = _prep_bridge(bridge)

    m = f.merge(b, on="cik", how="left")
    in_win = (
        m["permaticker"].notna()
        & (m["acceptance_date"] >= m["firstpricedate"])
        & (m["acceptance_date"] <= m["lastpricedate"])
    )
    matched = m[in_win].copy()

    # ambiguity tripwire: an accession in >1 permaticker's window (overlap)
    per_acc = matched.groupby("accession")["permaticker"].nunique()
    ambiguous = per_acc[per_acc > 1]
    if len(ambiguous) > 0:
        acc0 = ambiguous.index[0]
        pts = sorted(matched.loc[matched["accession"] == acc0, "permaticker"].unique().tolist())
        raise AttributionAmbiguityError(
            f"{len(ambiguous)} accession(s) map to >1 permaticker (overlapping "
            f"[firstpricedate,lastpricedate] windows on a shared CIK). "
            f"e.g. accession={acc0} -> permatickers {pts}. Refusing to graft "
            f"identities (survivorship-leak hazard).")

    attributed = matched.drop_duplicates(subset=["accession"]).reset_index(drop=True)

    n_total = int(f["accession"].nunique())
    n_attr = int(attributed["accession"].nunique())
    has_cik_match = int(f[f["cik"].isin(set(b["cik"]))]["accession"].nunique())
    stats = {
        "n_filings": n_total,
        "n_no_cik_in_bridge": n_total - has_cik_match,
        "n_attributed": n_attr,
        "n_unattributed_gap": has_cik_match - n_attr,  # CIK known but no window held the date
    }
    return attributed, stats


def asof_join(ranked_panel: pd.DataFrame, feat_by_filing: pd.DataFrame,
              feature_cols: list[str],
              staleness_days: int = _STALENESS_DAYS) -> pd.DataFrame:
    """Attach each (date T, permaticker)'s as-of latest qualifying filing.

    ranked_panel:   rows to attach features to, carrying `date`, `permaticker`
                    (typically the ranked cross-section from compute_scores).
    feat_by_filing: `permaticker`, `acceptance_date`, and the raw feature_cols;
                    one row per attributed filing.

    Selection: the filing with the greatest acceptance_date STRICTLY BEFORE T
    (allow_exact_matches=False => acceptance_date < T, Spec 2 sec 2). Carry-forward
    is automatic. A selected filing older than staleness_days at T -> NaN features
    (stale). No qualifying filing -> NaN features (fall back to M1 behaviour, never
    filled). Adds `llm_asof_date` and `llm_status` in {ok, stale, no_filing}.
    """
    left = ranked_panel.copy()
    left["date"] = pd.to_datetime(left["date"]).dt.normalize()
    order = left.index  # preserve caller ordering
    left = left.reset_index(drop=True)

    right = feat_by_filing.copy()
    right["acceptance_date"] = pd.to_datetime(right["acceptance_date"]).dt.normalize()
    right = right.dropna(subset=["acceptance_date"])
    right = (right.sort_values("acceptance_date")
                  .drop_duplicates(subset=["permaticker", "acceptance_date"], keep="last"))

    ls = left.sort_values("date").reset_index()   # 'index' keeps the row id
    merged = pd.merge_asof(
        ls, right[["permaticker", "acceptance_date", *feature_cols]],
        left_on="date", right_on="acceptance_date", by="permaticker",
        direction="backward", allow_exact_matches=False,
    )

    age_days = (merged["date"] - merged["acceptance_date"]).dt.days
    stale = merged["acceptance_date"].notna() & (age_days > staleness_days)
    no_filing = merged["acceptance_date"].isna()

    merged["llm_status"] = "ok"
    merged.loc[stale, "llm_status"] = "stale"
    merged.loc[no_filing, "llm_status"] = "no_filing"
    merged["llm_asof_date"] = merged["acceptance_date"]

    # NaN the features for stale / no_filing (never fill)
    blank = stale | no_filing
    for c in feature_cols:
        merged.loc[blank, c] = pd.NA
    merged.loc[stale, "llm_asof_date"] = pd.NaT

    merged = merged.drop(columns=["acceptance_date"])
    out = merged.set_index("index").reindex(order)
    return out


def coverage_funnel(joined: pd.DataFrame, feature_cols: list[str]) -> dict:
    """Rule-18 denominators for the (date, permaticker) join over the build span."""
    n = len(joined)
    status = joined["llm_status"].value_counts()
    any_feature = joined[feature_cols].notna().any(axis=1)
    return {
        "ranked_name_months": int(n),
        "with_ok_filing": int(status.get("ok", 0)),
        "stale_dropped": int(status.get("stale", 0)),
        "no_filing_dropped": int(status.get("no_filing", 0)),
        "with_any_llm_feature": int(any_feature.sum()),
        "nan_llm_name_months": int((~any_feature).sum()),
    }
