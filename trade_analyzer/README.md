# IBKR 0DTE Spread Analyzer

Local Streamlit MVP for importing IBKR Flex/Activity CSV executions, storing raw option fills in SQLite, reconstructing 0DTE NDX/SPX vertical spreads, scoring rule compliance, and reviewing expectancy/scenario metrics.

## Run

```bash
cd trade_analyzer
python -m pip install -r requirements.txt
streamlit run app.py
```

## CLI import and reconstruction

```bash
python -m src.import_ibkr data/raw/example.csv --db db/trades.db
python -m src.reconstruct_spreads --db db/trades.db
```

## Current MVP behavior

- Flexible IBKR column mapping for common Activity/Flex CSV headers.
- Raw executions are stored in `db/trades.db` table `executions` for audit.
- 0DTE NDX/NDXP and SPX/SPXW option executions are grouped by same trade date/expiry, underlying, option type, and fills within a five-minute window.
- Reconstructed verticals are labeled as bull put credit spreads, bear call credit spreads, call debit spreads, or put debit spreads.
- Reconstruction confidence is marked `high`, `medium`, or `low` depending on fill count, order consistency, and time spread.
- Risk expansion and rule-compliance fields are attached to reconstructed spread rows.
- Streamlit pages include upload, daily review, reconstructed trades, rule violations, expectancy, scenarios, and biggest winners/losers.
