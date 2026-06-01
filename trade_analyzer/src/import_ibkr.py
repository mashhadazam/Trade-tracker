from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Any

import pandas as pd

BASE_DIR = Path(__file__).resolve().parents[1]
DB_PATH = BASE_DIR / "db" / "trades.db"

EXECUTION_COLUMNS = [
    "execution_id",
    "order_id",
    "trade_date",
    "timestamp",
    "account",
    "underlying",
    "symbol",
    "expiry",
    "option_type",
    "strike",
    "side",
    "quantity",
    "price",
    "proceeds",
    "commission",
    "realized_pnl",
    "raw_description",
]

COLUMN_ALIASES = {
    "execution_id": ["execution_id", "executionid", "exec_id", "execid", "execution id", "exec. id"],
    "order_id": ["order_id", "orderid", "order id", "ib order id"],
    "timestamp": ["date/time", "datetime", "date time", "time", "trade time", "execution time"],
    "trade_date": ["date", "trade date", "transaction date"],
    "account": ["account", "account id", "accountid", "acct id"],
    "underlying": ["underlying", "underlying symbol", "root", "asset"],
    "symbol": ["symbol", "local symbol", "conid symbol", "ticker"],
    "expiry": ["expiry", "expiration", "expiration date", "last trade date"],
    "option_type": ["put/call", "putcall", "put call", "right", "option type", "call/put"],
    "strike": ["strike", "strike price"],
    "side": ["buy/sell", "buysell", "buy sell", "side", "transaction type"],
    "quantity": ["quantity", "qty", "shares", "contracts"],
    "price": ["price", "trade price", "avg price", "average price"],
    "proceeds": ["proceeds", "net cash", "amount", "cash amount"],
    "commission": ["commission", "commissions", "brokerage fee", "fees"],
    "realized_pnl": ["realized p&l", "realized pnl", "realized p/l", "p&l", "pnl", "realized profit/loss"],
    "raw_description": ["description", "security description", "contract description", "desc"],
    "asset_category": ["asset category", "assetcategory", "category", "security type"],
}

OPTION_DESCRIPTION_RE = re.compile(
    r"(?P<underlying>NDXP?|SPXW?)\s+"
    r"(?P<expiry>\d{4}-?\d{2}-?\d{2}|\d{1,2}/\d{1,2}/\d{2,4})\s+"
    r"(?P<strike>\d+(?:\.\d+)?)\s*(?P<option_type>[CP]|CALL|PUT)",
    re.IGNORECASE,
)


def normalise_name(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(name).strip().lower())


def build_column_map(columns: list[str]) -> dict[str, str]:
    normalised = {normalise_name(column): column for column in columns}
    mapping: dict[str, str] = {}
    for target, aliases in COLUMN_ALIASES.items():
        for alias in aliases:
            key = normalise_name(alias)
            if key in normalised:
                mapping[target] = normalised[key]
                break
    return mapping


def money_to_float(value: Any) -> float | None:
    if pd.isna(value) or value == "":
        return None
    text = str(value).strip().replace(",", "").replace("$", "")
    if text.startswith("(") and text.endswith(")"):
        text = "-" + text[1:-1]
    try:
        return float(text)
    except ValueError:
        return None


def parse_datetime_series(values: pd.Series) -> pd.Series:
    return pd.to_datetime(values, errors="coerce", utc=False).dt.tz_localize(None)


def normalise_expiry(value: Any) -> str | None:
    if pd.isna(value) or value == "":
        return None
    parsed = pd.to_datetime(str(value), errors="coerce")
    if pd.isna(parsed):
        return None
    return parsed.date().isoformat()


def normalise_option_type(value: Any) -> str | None:
    text = str(value).strip().upper()
    if text in {"C", "CALL"}:
        return "C"
    if text in {"P", "PUT"}:
        return "P"
    return None


def normalise_side(value: Any) -> str | None:
    text = str(value).strip().upper()
    if text in {"BUY", "BOT", "B", "BOUGHT"} or text.startswith("BUY"):
        return "BUY"
    if text in {"SELL", "SLD", "S", "SOLD"} or text.startswith("SELL"):
        return "SELL"
    return None


def parse_description(description: Any) -> dict[str, Any]:
    if pd.isna(description):
        return {}
    match = OPTION_DESCRIPTION_RE.search(str(description).replace("/", "-"))
    if not match:
        return {}
    data = match.groupdict()
    return {
        "underlying": data["underlying"].upper(),
        "expiry": normalise_expiry(data["expiry"]),
        "strike": money_to_float(data["strike"]),
        "option_type": normalise_option_type(data["option_type"]),
    }


def read_ibkr_csv(path_or_buffer: str | Path | Any) -> pd.DataFrame:
    raw = pd.read_csv(path_or_buffer)
    mapping = build_column_map(list(raw.columns))
    df = pd.DataFrame(index=raw.index)

    for column in EXECUTION_COLUMNS:
        source = mapping.get(column)
        df[column] = raw[source] if source else None

    if "asset_category" in mapping:
        asset = raw[mapping["asset_category"]].astype(str).str.lower()
        raw_option_mask = asset.str.contains("option|index", na=False)
        if raw_option_mask.any():
            df = df.loc[raw_option_mask].copy()
            raw = raw.loc[raw_option_mask].copy()

    description_col = mapping.get("raw_description")
    parsed_descriptions = raw[description_col].apply(parse_description) if description_col else pd.Series([{}] * len(df), index=df.index)

    for target in ["underlying", "expiry", "strike", "option_type"]:
        parsed_values = parsed_descriptions.apply(lambda item: item.get(target))
        df[target] = df[target].where(df[target].notna() & (df[target].astype(str).str.strip() != ""), parsed_values)

    if mapping.get("timestamp"):
        timestamps = parse_datetime_series(raw[mapping["timestamp"]])
    elif mapping.get("trade_date"):
        timestamps = parse_datetime_series(raw[mapping["trade_date"]])
    else:
        timestamps = pd.Series(pd.NaT, index=df.index)

    df["timestamp"] = timestamps.dt.strftime("%Y-%m-%d %H:%M:%S")
    df["trade_date"] = timestamps.dt.date.astype(str)
    if mapping.get("trade_date") and timestamps.isna().all():
        dates = pd.to_datetime(raw[mapping["trade_date"]], errors="coerce")
        df["trade_date"] = dates.dt.date.astype(str)
        df["timestamp"] = dates.dt.strftime("%Y-%m-%d 00:00:00")

    df["underlying"] = df["underlying"].astype(str).str.upper().replace({"NAN": None, "NONE": None})
    df["symbol"] = df["symbol"].astype(str).str.upper().replace({"NAN": None, "NONE": None})
    df["expiry"] = df["expiry"].apply(normalise_expiry)
    df["option_type"] = df["option_type"].apply(normalise_option_type)
    df["side"] = df["side"].apply(normalise_side)

    for numeric in ["strike", "quantity", "price", "proceeds", "commission", "realized_pnl"]:
        df[numeric] = df[numeric].apply(money_to_float).fillna(0.0)

    df["quantity"] = df["quantity"].abs()
    df["raw_description"] = df["raw_description"].fillna("").astype(str)
    df["execution_id"] = df["execution_id"].fillna("").astype(str)
    empty_exec = df["execution_id"].str.strip() == ""
    df.loc[empty_exec, "execution_id"] = [f"generated-{i}" for i in df.index[empty_exec]]
    df["order_id"] = df["order_id"].fillna("").astype(str)
    df["account"] = df["account"].fillna("").astype(str)

    return df[EXECUTION_COLUMNS].sort_values(["timestamp", "execution_id"]).reset_index(drop=True)


def get_connection(db_path: str | Path = DB_PATH) -> sqlite3.Connection:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: str | Path = DB_PATH) -> None:
    conn = get_connection(db_path)
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS executions (
                execution_id TEXT PRIMARY KEY,
                order_id TEXT,
                trade_date TEXT,
                timestamp TEXT,
                account TEXT,
                underlying TEXT,
                symbol TEXT,
                expiry TEXT,
                option_type TEXT,
                strike REAL,
                side TEXT,
                quantity REAL,
                price REAL,
                proceeds REAL,
                commission REAL,
                realized_pnl REAL,
                raw_description TEXT
            )
            """
        )
        conn.commit()
    finally:
        conn.close()


def store_executions(df: pd.DataFrame, db_path: str | Path = DB_PATH) -> int:
    init_db(db_path)
    records = df[EXECUTION_COLUMNS].to_dict("records")
    conn = get_connection(db_path)
    try:
        conn.executemany(
            """
            INSERT OR REPLACE INTO executions (
                execution_id, order_id, trade_date, timestamp, account, underlying, symbol,
                expiry, option_type, strike, side, quantity, price, proceeds, commission,
                realized_pnl, raw_description
            ) VALUES (
                :execution_id, :order_id, :trade_date, :timestamp, :account, :underlying, :symbol,
                :expiry, :option_type, :strike, :side, :quantity, :price, :proceeds, :commission,
                :realized_pnl, :raw_description
            )
            """,
            records,
        )
        conn.commit()
    finally:
        conn.close()
    return len(records)


def load_executions(db_path: str | Path = DB_PATH) -> pd.DataFrame:
    init_db(db_path)
    conn = get_connection(db_path)
    try:
        return pd.read_sql_query("SELECT * FROM executions ORDER BY timestamp, execution_id", conn)
    finally:
        conn.close()


def import_csv(path_or_buffer: str | Path | Any, db_path: str | Path = DB_PATH) -> pd.DataFrame:
    df = read_ibkr_csv(path_or_buffer)
    store_executions(df, db_path)
    return df


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Import IBKR Flex/Activity CSV executions into SQLite.")
    parser.add_argument("csv", help="Path to an IBKR CSV export")
    parser.add_argument("--db", default=str(DB_PATH), help="SQLite database path")
    args = parser.parse_args()
    imported = import_csv(args.csv, args.db)
    print(f"Imported {len(imported)} executions into {args.db}")
