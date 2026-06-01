from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from .import_ibkr import DB_PATH, load_executions

INDEX_ROOTS = {"NDX", "NDXP", "SPX", "SPXW"}
CLUSTER_WINDOW = pd.Timedelta(minutes=5)

SPREAD_COLUMNS = [
    "spread_id",
    "date",
    "underlying",
    "strategy",
    "option_type",
    "short_strike",
    "long_strike",
    "width",
    "quantity",
    "entry_time",
    "exit_time",
    "entry_credit_or_debit",
    "close_credit_or_debit",
    "realized_pnl",
    "max_theoretical_risk",
    "hold_minutes",
    "reconstruction_confidence",
    "entry_execution_ids",
    "exit_execution_ids",
    "added_to_loser",
    "same_short_strike_added",
    "hedge_moved",
    "hedge_widened",
    "width_expanded",
    "size_increased",
    "entered_after_2pm",
    "held_after_315pm",
]


@dataclass(frozen=True)
class CandidateSpread:
    side_at_short: str
    option_type: str
    short_strike: float
    long_strike: float
    strategy: str


def canonical_underlying(value: Any) -> str:
    text = str(value or "").upper()
    if text.startswith("NDX"):
        return "NDX"
    if text.startswith("SPX"):
        return "SPX"
    return text


def prepare_executions(executions: pd.DataFrame) -> pd.DataFrame:
    df = executions.copy()
    if df.empty:
        return df
    df["timestamp_dt"] = pd.to_datetime(df["timestamp"], errors="coerce")
    df["date"] = pd.to_datetime(df["trade_date"], errors="coerce").dt.date.astype(str)
    df["expiry"] = pd.to_datetime(df["expiry"], errors="coerce").dt.date.astype(str)
    df["underlying_root"] = df["underlying"].apply(canonical_underlying)
    df["price"] = pd.to_numeric(df["price"], errors="coerce").fillna(0.0)
    df["quantity"] = pd.to_numeric(df["quantity"], errors="coerce").fillna(0.0).abs()
    df["strike"] = pd.to_numeric(df["strike"], errors="coerce")
    df["realized_pnl"] = pd.to_numeric(df["realized_pnl"], errors="coerce").fillna(0.0)
    df["commission"] = pd.to_numeric(df["commission"], errors="coerce").fillna(0.0)
    df["side"] = df["side"].astype(str).str.upper()
    df["option_type"] = df["option_type"].astype(str).str.upper()
    mask = (
        df["underlying"].astype(str).str.upper().isin(INDEX_ROOTS)
        | df["symbol"].astype(str).str.upper().isin(INDEX_ROOTS)
        | df["underlying_root"].isin({"NDX", "SPX"})
    )
    df = df.loc[mask].copy()
    df = df.loc[df["date"] == df["expiry"]].copy()
    return df.sort_values(["timestamp_dt", "execution_id"]).reset_index(drop=True)


def signed_premium(row: pd.Series) -> float:
    return float(row["price"]) if row["side"] == "SELL" else -float(row["price"])


def classify_two_legs(short_leg: pd.Series, long_leg: pd.Series) -> str | None:
    option_type = short_leg["option_type"]
    short_strike = float(short_leg["strike"])
    long_strike = float(long_leg["strike"])
    if option_type == "P" and short_strike > long_strike:
        return "Bull Put Credit Spread"
    if option_type == "C" and short_strike < long_strike:
        return "Bear Call Credit Spread"
    if option_type == "C" and short_strike > long_strike:
        return "Call Debit Spread"
    if option_type == "P" and short_strike < long_strike:
        return "Put Debit Spread"
    return None


def cluster_executions(df: pd.DataFrame) -> list[pd.DataFrame]:
    clusters: list[pd.DataFrame] = []
    for _, group in df.groupby(["date", "underlying_root", "expiry", "option_type"], dropna=False):
        current: list[int] = []
        cluster_start = None
        for idx, row in group.sort_values("timestamp_dt").iterrows():
            timestamp = row["timestamp_dt"]
            if cluster_start is None or timestamp - cluster_start <= CLUSTER_WINDOW:
                current.append(idx)
                cluster_start = timestamp if cluster_start is None else cluster_start
            else:
                clusters.append(df.loc[current].copy())
                current = [idx]
                cluster_start = timestamp
        if current:
            clusters.append(df.loc[current].copy())
    return clusters


def build_entry_from_cluster(cluster: pd.DataFrame, sequence: int) -> dict[str, Any] | None:
    if len(cluster) < 2 or cluster["strike"].nunique() < 2:
        return None
    sells = cluster.loc[cluster["side"] == "SELL"].sort_values("strike")
    buys = cluster.loc[cluster["side"] == "BUY"].sort_values("strike")
    if sells.empty or buys.empty:
        return None

    pairs: list[tuple[pd.Series, pd.Series, str]] = []
    for _, sell in sells.iterrows():
        candidate_buys = buys.loc[buys["strike"] != sell["strike"]]
        if candidate_buys.empty:
            continue
        candidate_buys = candidate_buys.assign(distance=(candidate_buys["strike"] - sell["strike"]).abs())
        buy = candidate_buys.sort_values("distance").iloc[0]
        strategy = classify_two_legs(sell, buy)
        if strategy:
            pairs.append((sell, buy, strategy))
    if not pairs:
        return None

    sell, buy, strategy = pairs[0]
    quantity = min(abs(float(sell["quantity"])), abs(float(buy["quantity"])))
    premium = signed_premium(sell) + signed_premium(buy)
    width = abs(float(sell["strike"]) - float(buy["strike"]))
    is_credit = premium > 0
    max_risk = (width - premium if is_credit else abs(premium)) * quantity * 100
    confidence = "high" if len(cluster) == 2 and cluster["order_id"].nunique() <= 1 else "medium"
    if cluster["timestamp_dt"].max() - cluster["timestamp_dt"].min() > pd.Timedelta(minutes=2):
        confidence = "low"

    spread_id = f"{sell['date']}-{sell['underlying_root']}-{sequence:04d}"
    return {
        "spread_id": spread_id,
        "date": sell["date"],
        "underlying": sell["underlying_root"],
        "strategy": strategy,
        "option_type": sell["option_type"],
        "short_strike": float(sell["strike"]),
        "long_strike": float(buy["strike"]),
        "width": width,
        "quantity": quantity,
        "entry_time": cluster["timestamp_dt"].min(),
        "exit_time": pd.NaT,
        "entry_credit_or_debit": round(premium, 2),
        "close_credit_or_debit": 0.0,
        "realized_pnl": round(float(cluster["realized_pnl"].sum() + cluster["commission"].sum()), 2),
        "max_theoretical_risk": round(max_risk, 2),
        "hold_minutes": None,
        "reconstruction_confidence": confidence,
        "entry_execution_ids": ",".join(cluster["execution_id"].astype(str)),
        "exit_execution_ids": "",
    }


def match_exit_clusters(spreads: list[dict[str, Any]], clusters: list[pd.DataFrame]) -> None:
    for spread in spreads:
        entry_time = spread["entry_time"]
        matches: list[pd.DataFrame] = []
        for cluster in clusters:
            if cluster["timestamp_dt"].min() <= entry_time:
                continue
            if canonical_underlying(cluster["underlying_root"].iloc[0]) != spread["underlying"]:
                continue
            if cluster["option_type"].iloc[0] != spread["option_type"]:
                continue
            strikes = set(cluster["strike"].astype(float))
            if {spread["short_strike"], spread["long_strike"]}.issubset(strikes):
                close_short = cluster.loc[(cluster["strike"] == spread["short_strike"]) & (cluster["side"] == "BUY")]
                close_long = cluster.loc[(cluster["strike"] == spread["long_strike"]) & (cluster["side"] == "SELL")]
                if not close_short.empty and not close_long.empty:
                    matches.append(cluster)
        if not matches:
            continue
        exit_cluster = min(matches, key=lambda item: item["timestamp_dt"].min())
        close_premium = float(exit_cluster.apply(signed_premium, axis=1).sum())
        spread["exit_time"] = exit_cluster["timestamp_dt"].max()
        spread["close_credit_or_debit"] = round(close_premium, 2)
        spread["realized_pnl"] = round(float(spread["realized_pnl"] + exit_cluster["realized_pnl"].sum() + exit_cluster["commission"].sum()), 2)
        spread["hold_minutes"] = round((spread["exit_time"] - spread["entry_time"]).total_seconds() / 60, 2)
        spread["exit_execution_ids"] = ",".join(exit_cluster["execution_id"].astype(str))
        if spread["reconstruction_confidence"] == "high" and len(exit_cluster) != 2:
            spread["reconstruction_confidence"] = "medium"


def add_risk_expansion_flags(spreads_df: pd.DataFrame) -> pd.DataFrame:
    df = spreads_df.sort_values(["date", "entry_time", "spread_id"]).copy()
    flag_columns = [
        "added_to_loser",
        "same_short_strike_added",
        "hedge_moved",
        "hedge_widened",
        "width_expanded",
        "size_increased",
        "entered_after_2pm",
        "held_after_315pm",
    ]
    for column in flag_columns:
        df[column] = False

    df["entered_after_2pm"] = df["entry_time"].dt.time >= pd.Timestamp("14:00").time()
    df["held_after_315pm"] = df["exit_time"].notna() & (df["exit_time"].dt.time > pd.Timestamp("15:15").time())

    for _, day in df.groupby("date"):
        previous: list[pd.Series] = []
        for idx, row in day.iterrows():
            same_family = [item for item in previous if item["underlying"] == row["underlying"] and item["option_type"] == row["option_type"]]
            if same_family:
                df.at[idx, "same_short_strike_added"] = any(item["short_strike"] == row["short_strike"] for item in same_family)
                df.at[idx, "hedge_moved"] = any(item["long_strike"] != row["long_strike"] for item in same_family)
                df.at[idx, "hedge_widened"] = any(row["width"] > item["width"] and item["short_strike"] == row["short_strike"] for item in same_family)
                df.at[idx, "width_expanded"] = any(row["width"] > item["width"] for item in same_family)
                df.at[idx, "size_increased"] = any(row["quantity"] > item["quantity"] for item in same_family)
                df.at[idx, "added_to_loser"] = any(float(item["realized_pnl"] or 0) < 0 for item in same_family)
            previous.append(row)
    return df[SPREAD_COLUMNS]


def reconstruct_spreads(executions: pd.DataFrame) -> pd.DataFrame:
    prepared = prepare_executions(executions)
    if prepared.empty:
        return pd.DataFrame(columns=SPREAD_COLUMNS)
    clusters = cluster_executions(prepared)
    entries: list[dict[str, Any]] = []
    for sequence, cluster in enumerate(clusters, start=1):
        entry = build_entry_from_cluster(cluster, sequence)
        if entry is not None:
            entries.append(entry)
    match_exit_clusters(entries, clusters)
    if not entries:
        return pd.DataFrame(columns=SPREAD_COLUMNS)
    spreads = pd.DataFrame(entries)
    spreads["entry_time"] = pd.to_datetime(spreads["entry_time"], errors="coerce")
    spreads["exit_time"] = pd.to_datetime(spreads["exit_time"], errors="coerce")
    return add_risk_expansion_flags(spreads)


def reconstruct_from_db(db_path: str | Path = DB_PATH) -> pd.DataFrame:
    return reconstruct_spreads(load_executions(db_path))


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Reconstruct 0DTE NDX/SPX option spreads from stored executions.")
    parser.add_argument("--db", default=str(DB_PATH), help="SQLite database path")
    args = parser.parse_args()
    table = reconstruct_from_db(args.db)
    print(table.to_string(index=False))
