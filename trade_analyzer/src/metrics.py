from __future__ import annotations

import pandas as pd


def _pnl(spreads: pd.DataFrame) -> pd.Series:
    return pd.to_numeric(spreads.get("realized_pnl", pd.Series(dtype=float)), errors="coerce").fillna(0.0)


def summary_metrics(spreads: pd.DataFrame) -> dict[str, float | int]:
    pnl = _pnl(spreads)
    wins = pnl[pnl > 0]
    losses = pnl[pnl < 0]
    win_rate = len(wins) / len(pnl) if len(pnl) else 0
    avg_winner = wins.mean() if len(wins) else 0
    avg_loser = losses.mean() if len(losses) else 0
    expectancy = (win_rate * avg_winner) + ((1 - win_rate) * avg_loser) if len(pnl) else 0
    return {
        "trade_count": int(len(pnl)),
        "total_pnl": round(float(pnl.sum()), 2),
        "win_rate": round(float(win_rate * 100), 2),
        "average_winner": round(float(avg_winner), 2),
        "average_loser": round(float(avg_loser), 2),
        "expectancy_per_trade": round(float(expectancy), 2),
        "expectancy_per_month_1_5_trades_day": round(float(expectancy * 1.5 * 21), 2),
    }


def daily_pnl(spreads: pd.DataFrame) -> pd.DataFrame:
    if spreads.empty:
        return pd.DataFrame(columns=["date", "total_pnl", "trade_count"])
    return spreads.assign(realized_pnl=_pnl(spreads)).groupby("date", as_index=False).agg(
        total_pnl=("realized_pnl", "sum"), trade_count=("spread_id", "count")
    )


def monthly_pnl(spreads: pd.DataFrame) -> pd.DataFrame:
    if spreads.empty:
        return pd.DataFrame(columns=["month", "total_pnl", "trade_count"])
    df = spreads.copy()
    df["month"] = pd.to_datetime(df["date"], errors="coerce").dt.to_period("M").astype(str)
    df["realized_pnl"] = _pnl(df)
    return df.groupby("month", as_index=False).agg(total_pnl=("realized_pnl", "sum"), trade_count=("spread_id", "count"))


def grouped_pnl(spreads: pd.DataFrame, column: str) -> pd.DataFrame:
    if spreads.empty or column not in spreads:
        return pd.DataFrame(columns=[column, "total_pnl", "trade_count"])
    df = spreads.copy()
    df["realized_pnl"] = _pnl(df)
    return df.groupby(column, as_index=False).agg(total_pnl=("realized_pnl", "sum"), trade_count=("spread_id", "count"))


def largest_trades(spreads: pd.DataFrame, n: int = 10) -> tuple[pd.DataFrame, pd.DataFrame]:
    if spreads.empty:
        return spreads.copy(), spreads.copy()
    df = spreads.assign(realized_pnl=_pnl(spreads))
    return df.nlargest(n, "realized_pnl"), df.nsmallest(n, "realized_pnl")


def hold_time_by_outcome(spreads: pd.DataFrame) -> pd.DataFrame:
    if spreads.empty:
        return pd.DataFrame(columns=["outcome", "average_hold_minutes"])
    df = spreads.copy()
    df["realized_pnl"] = _pnl(df)
    df["hold_minutes"] = pd.to_numeric(df["hold_minutes"], errors="coerce")
    df["outcome"] = df["realized_pnl"].apply(lambda value: "winner" if value > 0 else "loser" if value < 0 else "scratch")
    return df.groupby("outcome", as_index=False).agg(average_hold_minutes=("hold_minutes", "mean"))


def pnl_by_entry_hour(spreads: pd.DataFrame) -> pd.DataFrame:
    if spreads.empty:
        return pd.DataFrame(columns=["entry_hour", "total_pnl", "trade_count"])
    df = spreads.copy()
    df["entry_hour"] = pd.to_datetime(df["entry_time"], errors="coerce").dt.hour
    df["realized_pnl"] = _pnl(df)
    return df.groupby("entry_hour", as_index=False).agg(total_pnl=("realized_pnl", "sum"), trade_count=("spread_id", "count"))


def all_metric_tables(spreads: pd.DataFrame) -> dict[str, pd.DataFrame | dict[str, float | int]]:
    return {
        "summary": summary_metrics(spreads),
        "daily_pnl": daily_pnl(spreads),
        "monthly_pnl": monthly_pnl(spreads),
        "underlying_pnl": grouped_pnl(spreads, "underlying"),
        "strategy_pnl": grouped_pnl(spreads, "strategy"),
        "width_pnl": grouped_pnl(spreads, "width"),
        "credit_pnl": grouped_pnl(spreads, "entry_credit_or_debit"),
        "entry_hour_pnl": pnl_by_entry_hour(spreads),
        "hold_time_by_outcome": hold_time_by_outcome(spreads),
    }
