from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

from src.import_ibkr import DB_PATH, import_csv, load_executions
from src.metrics import all_metric_tables, daily_pnl, largest_trades, summary_metrics
from src.reconstruct_spreads import reconstruct_spreads
from src.rules import append_rule_results
from src.scenarios import simulate_scenarios

st.set_page_config(page_title="IBKR 0DTE Spread Analyzer", layout="wide")

DATA_DIR = Path(__file__).resolve().parent / "data"
RAW_DIR = DATA_DIR / "raw"
RAW_DIR.mkdir(parents=True, exist_ok=True)


def get_spreads() -> tuple[pd.DataFrame, pd.DataFrame]:
    executions = load_executions(DB_PATH)
    spreads = append_rule_results(reconstruct_spreads(executions))
    return executions, spreads


def show_upload() -> None:
    st.header("Upload CSV")
    uploaded = st.file_uploader("IBKR Activity/Flex CSV", type=["csv"])
    if uploaded is not None:
        raw_path = RAW_DIR / uploaded.name
        raw_path.write_bytes(uploaded.getvalue())
        imported = import_csv(raw_path, DB_PATH)
        st.success(f"Imported {len(imported)} raw option executions.")
        st.dataframe(imported, use_container_width=True)
    st.caption("Raw executions remain visible for audit. Reconstruction confidence is marked high/medium/low.")


def show_daily_review(spreads: pd.DataFrame) -> None:
    st.header("Daily Review")
    if spreads.empty:
        st.info("Upload an IBKR CSV to see daily review metrics.")
        return
    selected_date = st.selectbox("Trade date", sorted(spreads["date"].unique(), reverse=True))
    day = spreads.loc[spreads["date"] == selected_date]
    summary = summary_metrics(day)
    biggest_win, biggest_loss = largest_trades(day, 1)

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total P&L", f"${summary['total_pnl']:,.2f}")
    col2.metric("NDX P&L", f"${day.loc[day['underlying'] == 'NDX', 'realized_pnl'].sum():,.2f}")
    col3.metric("SPX P&L", f"${day.loc[day['underlying'] == 'SPX', 'realized_pnl'].sum():,.2f}")
    col4.metric("Trades", int(summary["trade_count"]))

    c1, c2 = st.columns(2)
    c1.subheader("Biggest winner")
    c1.dataframe(biggest_win, use_container_width=True)
    c2.subheader("Biggest loser")
    c2.dataframe(biggest_loss, use_container_width=True)

    st.subheader("Rule violations")
    rule_cols = [col for col in day.columns if col.endswith("_ok") or col in {"stopped_correctly", "no_risk_expansion", "target_reached", "runner_managed", "overall_rule_score"}]
    violations = day.loc[(day.get("overall_rule_score", 100) < 100), ["spread_id", "strategy", *rule_cols]]
    st.dataframe(violations, use_container_width=True)

    st.subheader("Reconstructed spreads")
    st.dataframe(day, use_container_width=True)


def show_reconstructed(executions: pd.DataFrame, spreads: pd.DataFrame) -> None:
    st.header("Reconstructed Trades")
    st.subheader("Raw executions for audit")
    st.dataframe(executions, use_container_width=True)
    st.subheader("Spread table")
    st.dataframe(spreads, use_container_width=True)


def show_rule_violations(spreads: pd.DataFrame) -> None:
    st.header("Rule Violations")
    if spreads.empty:
        st.info("No reconstructed spreads yet.")
        return
    flagged = spreads.loc[spreads["overall_rule_score"] < 100].copy()
    st.dataframe(flagged, use_container_width=True)


def show_expectancy(spreads: pd.DataFrame) -> None:
    st.header("Expectancy")
    if spreads.empty:
        st.info("No reconstructed spreads yet.")
        return
    tables = all_metric_tables(spreads)
    st.json(tables["summary"])
    for name, table in tables.items():
        if name == "summary":
            continue
        st.subheader(name.replace("_", " ").title())
        st.dataframe(table, use_container_width=True)


def show_scenarios(spreads: pd.DataFrame) -> None:
    st.header("Scenario Simulator")
    event_file = st.file_uploader("Optional event calendar CSV with a date column", type=["csv"], key="events")
    event_path = None
    if event_file is not None:
        event_path = DATA_DIR / "processed" / event_file.name
        event_path.write_bytes(event_file.getvalue())
    st.dataframe(simulate_scenarios(spreads, event_path), use_container_width=True)


def show_biggest(spreads: pd.DataFrame) -> None:
    st.header("Biggest Winners/Losers")
    wins, losses = largest_trades(spreads, 20)
    c1, c2 = st.columns(2)
    c1.subheader("Winners")
    c1.dataframe(wins, use_container_width=True)
    c2.subheader("Losers")
    c2.dataframe(losses, use_container_width=True)


def main() -> None:
    st.title("IBKR 0DTE NDX/SPX Spread Analyzer")
    page = st.sidebar.radio(
        "Page",
        [
            "Upload CSV",
            "Daily Review",
            "Reconstructed Trades",
            "Rule Violations",
            "Expectancy",
            "Scenario Simulator",
            "Biggest Winners/Losers",
        ],
    )
    executions, spreads = get_spreads()
    if page == "Upload CSV":
        show_upload()
    elif page == "Daily Review":
        show_daily_review(spreads)
    elif page == "Reconstructed Trades":
        show_reconstructed(executions, spreads)
    elif page == "Rule Violations":
        show_rule_violations(spreads)
    elif page == "Expectancy":
        show_expectancy(spreads)
    elif page == "Scenario Simulator":
        show_scenarios(spreads)
    else:
        show_biggest(spreads)


if __name__ == "__main__":
    main()
