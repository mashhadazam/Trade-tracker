from __future__ import annotations

import pandas as pd

RULE_COLUMNS = [
    "spread_id",
    "credit_ok",
    "width_ok",
    "size_ok",
    "entered_time_ok",
    "stopped_correctly",
    "no_risk_expansion",
    "target_reached",
    "runner_managed",
    "overall_rule_score",
]

CREDIT_STRATEGIES = {"Bull Put Credit Spread", "Bear Call Credit Spread"}


def evaluate_rules(spreads: pd.DataFrame, max_spreads: int = 2) -> pd.DataFrame:
    if spreads.empty:
        return pd.DataFrame(columns=RULE_COLUMNS)
    df = spreads.copy()
    df["entry_time"] = pd.to_datetime(df["entry_time"], errors="coerce")
    df["exit_time"] = pd.to_datetime(df["exit_time"], errors="coerce")

    day_counts = df.groupby("date")["spread_id"].transform("count")
    is_credit = df["strategy"].isin(CREDIT_STRATEGIES)
    credit = pd.to_numeric(df["entry_credit_or_debit"], errors="coerce").fillna(0.0)
    close = pd.to_numeric(df["close_credit_or_debit"], errors="coerce").fillna(0.0)
    pnl = pd.to_numeric(df["realized_pnl"], errors="coerce").fillna(0.0)

    risk_flags = [
        "added_to_loser",
        "same_short_strike_added",
        "hedge_moved",
        "hedge_widened",
        "width_expanded",
        "size_increased",
    ]
    out = pd.DataFrame({"spread_id": df["spread_id"]})
    out["credit_ok"] = (~is_credit) | (credit >= 1.0)
    out["width_ok"] = pd.to_numeric(df["width"], errors="coerce").fillna(0.0) <= 50
    out["size_ok"] = day_counts <= max_spreads
    out["entered_time_ok"] = df["entry_time"].dt.time < pd.Timestamp("14:30").time()
    out["stopped_correctly"] = (~is_credit) | (pnl >= -(2 * credit.abs() * pd.to_numeric(df["quantity"], errors="coerce").fillna(1) * 100))
    out["no_risk_expansion"] = ~df[risk_flags].fillna(False).any(axis=1)
    out["target_reached"] = (~is_credit) | ((close.abs() <= credit.abs() * 0.4) | (pnl > 0))
    out["runner_managed"] = (~df["held_after_315pm"].fillna(False)) | (pnl >= 0)
    bool_cols = [column for column in RULE_COLUMNS if column not in {"spread_id", "overall_rule_score"}]
    out["overall_rule_score"] = (out[bool_cols].sum(axis=1) / len(bool_cols) * 100).round(1)
    return out[RULE_COLUMNS]


def append_rule_results(spreads: pd.DataFrame) -> pd.DataFrame:
    rules = evaluate_rules(spreads)
    if spreads.empty:
        return spreads.copy()
    return spreads.merge(rules, on="spread_id", how="left")
