"""Engine A ETF universe - locked 2026-06-17 (PROJECT_CHARTER.md section 4).

~22 liquid ETFs spanning asset classes, chosen for trend following:
diversification across uncorrelated asset classes, not symbol count.
Edit here; the loader and (later) the backtest both import from this file.

Note: ETFs have different inception dates, so histories start at different
points (e.g. SPY 1993, XLRE 2015). That is expected; the trend engine handles
assets entering the universe over time. The coverage report surfaces per-ETF
start dates so short-history names are visible, not silently assumed deep.
"""

# ticker -> asset class
UNIVERSE_BY_CLASS = {
    "SPY": "us_equity_broad",
    "XLK": "us_equity_sector",
    "XLF": "us_equity_sector",
    "XLE": "us_equity_sector",
    "XLV": "us_equity_sector",
    "XLI": "us_equity_sector",
    "XLY": "us_equity_sector",
    "XLP": "us_equity_sector",
    "XLU": "us_equity_sector",
    "XLB": "us_equity_sector",
    "XLRE": "us_equity_sector",
    "EFA": "intl_equity",
    "EEM": "intl_equity",
    "TLT": "bonds",
    "IEF": "bonds",
    "LQD": "bonds",
    "HYG": "bonds",
    "SHY": "cash_proxy",
    "DBC": "commodities",
    "USO": "commodities",
    "GLD": "gold",
    "VNQ": "reit",
}

ETF_UNIVERSE = list(UNIVERSE_BY_CLASS.keys())

# Earliest date we attempt to pull; vendor returns from each ETF's inception onward.
HISTORY_START = "2000-01-01"

assert len(ETF_UNIVERSE) == 22, f"expected 22 ETFs, got {len(ETF_UNIVERSE)}"
