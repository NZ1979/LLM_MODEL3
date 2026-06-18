# config/ - configuration

Plain-Python config the engines and loaders import. No secrets here (those live in `.env`, gitignored).

- `universe.py` - the locked Engine A ETF universe (~22 tickers) with asset-class tags, and the history start date. Edit the universe here; the data loader and the backtest both import `ETF_UNIVERSE` from it.
