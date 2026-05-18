# Trade Tracker

A small local trading journal for logging trades, reviewing risk, and checking dashboard stats.

## Project Structure

```text
trade-tracker/
├── app.py                 # Local web server and JSON API
├── static/
│   ├── index.html         # Browser UI
│   ├── styles.css         # UI styling
│   └── app.js             # Frontend behavior
├── data/
│   └── .gitkeep           # SQLite DB is created here locally
├── tests/
│   └── test_api.py        # API smoke tests
├── requirements.txt       # Runtime dependencies
└── README.md
```

## Run Locally

From PowerShell in this folder:

```powershell
python .\app.py
```

Then open:

```text
http://localhost:8000
```

## API Smoke Tests

In another PowerShell window:

```powershell
Invoke-RestMethod http://localhost:8000/api/health
Invoke-RestMethod http://localhost:8000/api/rules
```

Create a trade:

```powershell
$body = @{
  symbol = 'AAPL'
  side = 'LONG'
  setup_tag = 'Breakout'
  qty = 10
  entry_price = 190
  risk_amount = 100
  pnl = 50
} | ConvertTo-Json

Invoke-RestMethod -Method POST -Uri http://localhost:8000/api/trades -ContentType 'application/json' -Body $body
Invoke-RestMethod http://localhost:8000/api/trades
Invoke-RestMethod http://localhost:8000/api/dashboard
```

## Run Tests

```powershell
python -m unittest discover -s tests
```

## API Endpoints

- `GET /api/health` - server health check
- `GET /api/rules` - journal validation rules and allowed sides
- `GET /api/trades` - list all trades
- `POST /api/trades` - create a trade
- `GET /api/dashboard` - summary metrics
