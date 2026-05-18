from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
DATA_DIR = BASE_DIR / "data"
DB_PATH = Path(os.environ.get("TRADE_TRACKER_DB", DATA_DIR / "trades.db"))
HOST = os.environ.get("TRADE_TRACKER_HOST", "127.0.0.1")
PORT = int(os.environ.get("TRADE_TRACKER_PORT", "8000"))
SIDES = {"LONG", "SHORT"}


def get_connection() -> sqlite3.Connection:
    DATA_DIR.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with get_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                setup_tag TEXT NOT NULL,
                qty REAL NOT NULL,
                entry_price REAL NOT NULL,
                risk_amount REAL NOT NULL,
                pnl REAL NOT NULL,
                notes TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            )
            """
        )


def row_to_trade(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "symbol": row["symbol"],
        "side": row["side"],
        "setup_tag": row["setup_tag"],
        "qty": row["qty"],
        "entry_price": row["entry_price"],
        "risk_amount": row["risk_amount"],
        "pnl": row["pnl"],
        "notes": row["notes"],
        "created_at": row["created_at"],
    }


def parse_positive_number(value: Any, field: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be a number") from exc
    if number <= 0:
        raise ValueError(f"{field} must be greater than 0")
    return number


def parse_number(value: Any, field: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be a number") from exc


def validate_trade(payload: dict[str, Any]) -> dict[str, Any]:
    symbol = str(payload.get("symbol", "")).strip().upper()
    side = str(payload.get("side", "")).strip().upper()
    setup_tag = str(payload.get("setup_tag", "")).strip()
    notes = str(payload.get("notes", "")).strip()

    if not symbol:
        raise ValueError("symbol is required")
    if side not in SIDES:
        raise ValueError("side must be LONG or SHORT")
    if not setup_tag:
        raise ValueError("setup_tag is required")

    return {
        "symbol": symbol,
        "side": side,
        "setup_tag": setup_tag,
        "qty": parse_positive_number(payload.get("qty"), "qty"),
        "entry_price": parse_positive_number(payload.get("entry_price"), "entry_price"),
        "risk_amount": parse_positive_number(payload.get("risk_amount"), "risk_amount"),
        "pnl": parse_number(payload.get("pnl"), "pnl"),
        "notes": notes,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def create_trade(payload: dict[str, Any]) -> dict[str, Any]:
    trade = validate_trade(payload)
    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO trades (
                symbol, side, setup_tag, qty, entry_price, risk_amount, pnl, notes, created_at
            ) VALUES (
                :symbol, :side, :setup_tag, :qty, :entry_price, :risk_amount, :pnl, :notes, :created_at
            )
            """,
            trade,
        )
        row = conn.execute("SELECT * FROM trades WHERE id = ?", (cursor.lastrowid,)).fetchone()
    return row_to_trade(row)


def list_trades() -> list[dict[str, Any]]:
    with get_connection() as conn:
        rows = conn.execute("SELECT * FROM trades ORDER BY created_at DESC, id DESC").fetchall()
    return [row_to_trade(row) for row in rows]


def dashboard() -> dict[str, Any]:
    trades = list_trades()
    total_pnl = sum(trade["pnl"] for trade in trades)
    wins = [trade for trade in trades if trade["pnl"] > 0]
    losses = [trade for trade in trades if trade["pnl"] < 0]
    total_risk = sum(trade["risk_amount"] for trade in trades)

    return {
        "trade_count": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round((len(wins) / len(trades)) * 100, 2) if trades else 0,
        "total_pnl": round(total_pnl, 2),
        "average_pnl": round(total_pnl / len(trades), 2) if trades else 0,
        "total_risk": round(total_risk, 2),
        "r_multiple": round(total_pnl / total_risk, 2) if total_risk else 0,
    }


class TradeTrackerHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, directory=str(STATIC_DIR), **kwargs)

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/health":
            self.send_json({"ok": True})
        elif path == "/api/rules":
            self.send_json(
                {
                    "required_fields": [
                        "symbol",
                        "side",
                        "setup_tag",
                        "qty",
                        "entry_price",
                        "risk_amount",
                        "pnl",
                    ],
                    "allowed_sides": sorted(SIDES),
                }
            )
        elif path == "/api/trades":
            self.send_json(list_trades())
        elif path == "/api/dashboard":
            self.send_json(dashboard())
        else:
            super().do_GET()

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path != "/api/trades":
            self.send_json({"error": "Not found"}, HTTPStatus.NOT_FOUND)
            return

        try:
            payload = self.read_json()
            trade = create_trade(payload)
        except ValueError as exc:
            self.send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return

        self.send_json(trade, HTTPStatus.CREATED)

    def read_json(self) -> dict[str, Any]:
        content_length = int(self.headers.get("Content-Length", "0"))
        raw_body = self.rfile.read(content_length).decode("utf-8")
        try:
            payload = json.loads(raw_body or "{}")
        except json.JSONDecodeError as exc:
            raise ValueError("request body must be valid JSON") from exc
        if not isinstance(payload, dict):
            raise ValueError("request body must be a JSON object")
        return payload

    def send_json(self, body: Any, status: HTTPStatus = HTTPStatus.OK) -> None:
        data = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format: str, *args: Any) -> None:
        return


def run() -> None:
    init_db()
    server = ThreadingHTTPServer((HOST, PORT), TradeTrackerHandler)
    print(f"Trade Tracker running at http://{HOST}:{PORT}")
    server.serve_forever()


if __name__ == "__main__":
    run()
