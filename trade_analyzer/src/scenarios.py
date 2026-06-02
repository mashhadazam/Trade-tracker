from __future__ import annotations

from pathlib import Path

import pandas as pd


def load_event_calendar(path: str | Path | None) -> set[str]:
    if not path:
        return set()
    events = pd.read_csv(path)
    date_col = next((col for col in events.columns if col.lower() in {"date", "event_date"}), events.columns[0])
    return set(pd.to_datetime(events[date_col], errors="coerce").dt.date.astype(str))


def simulate_scenarios(spreads: pd.DataFrame, event_calendar: str | Path | None = None) -> pd.DataFrame:
    if spreads.empty:
        return pd.DataFrame(columns=["scenario", "trade_count", "total_pnl", "expectancy"])
    df = spreads.copy()
    df["entry_time"] = pd.to_datetime(df["entry_time"], errors="coerce")
    df["realized_pnl"] = pd.to_numeric(df["realized_pnl"], errors="coerce").fillna(0.0)
    df["entry_credit_or_debit"] = pd.to_numeric(df["entry_credit_or_debit"], errors="coerce").fillna(0.0)
    df["quantity"] = pd.to_numeric(df["quantity"], errors="coerce").fillna(1.0)

    scenarios: list[tuple[str, pd.Series]] = []
    scenarios.append(("Actual", df["realized_pnl"]))
    two_x_stop = df.apply(
        lambda row: max(row["realized_pnl"], -(abs(row["entry_credit_or_debit"]) * 2 * row["quantity"] * 100)), axis=1
    )
    scenarios.append(("2x stop loss", two_x_stop))

    no_add_flags = ["added_to_loser", "same_short_strike_added", "hedge_widened", "width_expanded", "size_increased"]
    no_add_mask = ~df[no_add_flags].fillna(False).any(axis=1)
    scenarios.append(("No adding/no widening", df.loc[no_add_mask, "realized_pnl"]))

    scenarios.append(("Take profit at 60%", df["realized_pnl"].clip(upper=abs(df["entry_credit_or_debit"]) * 0.6 * df["quantity"] * 100)))
    scenarios.append(("Take profit at 70%", df["realized_pnl"].clip(upper=abs(df["entry_credit_or_debit"]) * 0.7 * df["quantity"] * 100)))
    half_runner = (abs(df["entry_credit_or_debit"]) * 0.6 * df["quantity"] * 100 * 0.5) + (df["realized_pnl"].clip(lower=0) * 0.5)
    scenarios.append(("Half at 60%, runner", half_runner))
    before_2 = df["entry_time"].dt.time < pd.Timestamp("14:00").time()
    scenarios.append(("Skip trades after 2 PM", df.loc[before_2, "realized_pnl"]))

    event_dates = load_event_calendar(event_calendar)
    if event_dates:
        scenarios.append(("Skip NFP/CPI/FOMC calendar days", df.loc[~df["date"].isin(event_dates), "realized_pnl"]))

    rows = []
    for name, pnl in scenarios:
        rows.append({
            "scenario": name,
            "trade_count": int(len(pnl)),
            "total_pnl": round(float(pnl.sum()), 2),
            "expectancy": round(float(pnl.mean()), 2) if len(pnl) else 0.0,
        })
    return pd.DataFrame(rows)
