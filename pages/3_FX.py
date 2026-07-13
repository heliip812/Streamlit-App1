from datetime import date, timedelta

import plotly.express as px
import streamlit as st

from data.sources import get_dtcc_trades
from viz_theme import CATEGORICAL

st.set_page_config(page_title="FX — Derivatives Monitor", page_icon="📈", layout="wide")
st.title("FX derivatives")
st.caption("FX swaps, forwards and options reported to DTCC's Swap Data Repository.")

with st.sidebar:
    as_of = st.date_input("As of date", value=date.today() - timedelta(days=1), key="fx_as_of")
    lookback_days = st.slider("Lookback window (days)", 3, 30, 7, key="fx_lookback")

df = get_dtcc_trades("FOREX", as_of, lookback_days)
new_trades = df[df["is_new_trade"]].copy() if not df.empty else df

if new_trades.empty:
    st.info("No FX trades found in this window. Try an earlier 'as of' date — DTCC publishes with a short lag.")
    st.stop()

new_trades["pair"] = (
    new_trades["Notional currency-Leg 1"].fillna("?") + "/" + new_trades["Notional currency-Leg 2"].fillna("?")
)

c1, c2, c3 = st.columns(3)
c1.metric("Total notional", f"${new_trades['notional_usd_approx'].sum() / 1e9:,.1f}B")
c2.metric("Trades", f"{len(new_trades):,}")
c3.metric("Cleared", f"{(new_trades['Cleared'] == 'Y').mean() * 100:,.0f}%")

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
    fig.update_layout(margin=dict(l=10, r=10, t=10, b=10))
    st.plotly_chart(fig, use_container_width=True, theme="streamlit")

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
    fig.update_layout(margin=dict(l=10, r=10, t=10, b=10))
    st.plotly_chart(fig, use_container_width=True, theme="streamlit")

st.caption(
    "Currency pair labels reflect DTCC's leg currency order and are not normalized to "
    "market convention. Notional is the USD-denominated leg's reported amount (no "
    "synthetic FX conversion); cross pairs with neither leg in USD are excluded."
)
