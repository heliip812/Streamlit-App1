import plotly.express as px
import streamlit as st

from config import FX_LOOKBACK
from data.sources import get_dtcc_trades
from ui import empty_state, metric_row, render, sidebar_date_and_lookback
from viz_theme import CATEGORICAL

st.set_page_config(page_title="FX — Derivatives Monitor", page_icon="📈", layout="wide")
st.title("FX derivatives")
st.caption("FX swaps, forwards and options reported to DTCC's Swap Data Repository.")

as_of, lookback_days = sidebar_date_and_lookback(FX_LOOKBACK, "fx")

df = get_dtcc_trades("FOREX", as_of, lookback_days)
new_trades = df[df["is_new_trade"]].copy() if not df.empty else df

if new_trades.empty:
    empty_state("No FX trades found in this window. Try an earlier 'as of' date — DTCC publishes with a short lag.")

new_trades["pair"] = (
    new_trades["Notional currency-Leg 1"].fillna("?") + "/" + new_trades["Notional currency-Leg 2"].fillna("?")
)

metric_row(
    [
        ("Total notional", f"${new_trades['notional_usd_approx'].sum() / 1e9:,.1f}B"),
        ("Trades", f"{len(new_trades):,}"),
        ("Cleared", f"{(new_trades['Cleared'] == 'Y').mean() * 100:,.0f}%"),
    ]
)

col_left, col_right = st.columns(2)

with col_left:
    st.subheader("Most active currency pairs")
    by_pair = (
        new_trades.groupby("pair")["notional_usd_approx"]
        .sum()
        .sort_values(ascending=False)
        .head(10)
        .reset_index()
    )
    fig = px.bar(
        by_pair,
        x="pair",
        y="notional_usd_approx",
        color_discrete_sequence=[CATEGORICAL[2]],
        labels={"pair": "", "notional_usd_approx": "Notional traded ($)"},
    )
    render(fig)

with col_right:
    st.subheader("Daily notional volume")
    daily = new_trades.groupby("_trade_date")["notional_usd_approx"].sum().reset_index()
    fig = px.line(
        daily,
        x="_trade_date",
        y="notional_usd_approx",
        markers=True,
        color_discrete_sequence=[CATEGORICAL[2]],
        labels={"_trade_date": "", "notional_usd_approx": "Notional traded ($)"},
    )
    render(fig)

st.caption(
    "Currency pair labels reflect DTCC's leg currency order and are not normalized to "
    "market convention. Notional is the USD-denominated leg's reported amount (no "
    "synthetic FX conversion); cross pairs with neither leg in USD are excluded."
)
