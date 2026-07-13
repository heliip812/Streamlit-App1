from datetime import date, timedelta

import pandas as pd
import plotly.express as px
import streamlit as st

from data.sources import get_dtcc_trades
from viz_theme import CATEGORICAL

st.set_page_config(page_title="Rates — Derivatives Monitor", page_icon="📈", layout="wide")
st.title("Rates derivatives")
st.caption("Interest rate swaps reported to DTCC's Swap Data Repository.")

with st.sidebar:
    as_of = st.date_input("As of date", value=date.today() - timedelta(days=1), key="rates_as_of")
    lookback_days = st.slider("Lookback window (days)", 3, 30, 7, key="rates_lookback")

df = get_dtcc_trades("RATES", as_of, lookback_days)
new_trades = df[df["is_new_trade"]].copy() if not df.empty else df

if new_trades.empty:
    st.info("No rates trades found in this window. Try an earlier 'as of' date — DTCC publishes with a short lag.")
    st.stop()

c1, c2, c3 = st.columns(3)
c1.metric("Total notional", f"${new_trades['notional_usd_approx'].sum() / 1e9:,.1f}B")
c2.metric("Trades", f"{len(new_trades):,}")
c3.metric("Cleared", f"{(new_trades['Cleared'] == 'Y').mean() * 100:,.0f}%")

bins = [0, 1, 2, 5, 10, 30, 100]
labels = ["<1Y", "1-2Y", "2-5Y", "5-10Y", "10-30Y", "30Y+"]
new_trades["tenor_bucket"] = pd.cut(new_trades["tenor_years"], bins=bins, labels=labels)

col_left, col_right = st.columns(2)

with col_left:
    st.subheader("Notional by tenor bucket")
    tenor_notional = (
        new_trades.dropna(subset=["tenor_bucket"])
        .groupby("tenor_bucket", observed=True)["notional_usd_approx"]
        .sum()
        .reindex(labels)
        .fillna(0)
        .reset_index()
    )
    fig = px.bar(
        tenor_notional,
        x="tenor_bucket",
        y="notional_usd_approx",
        color_discrete_sequence=[CATEGORICAL[0]],
        labels={"tenor_bucket": "", "notional_usd_approx": "Notional traded ($)"},
    )
    fig.update_layout(margin=dict(l=10, r=10, t=10, b=10))
    st.plotly_chart(fig, use_container_width=True, theme="streamlit")

with col_right:
    st.subheader("Trades by currency")
    by_ccy = (
        new_trades.groupby("Notional currency-Leg 1")
        .size()
        .sort_values(ascending=False)
        .head(8)
        .reset_index(name="trades")
    )
    fig = px.bar(
        by_ccy,
        x="Notional currency-Leg 1",
        y="trades",
        color_discrete_sequence=[CATEGORICAL[1]],
        labels={"Notional currency-Leg 1": "", "trades": "Trade count"},
    )
    fig.update_layout(margin=dict(l=10, r=10, t=10, b=10))
    st.plotly_chart(fig, use_container_width=True, theme="streamlit")

st.subheader("Fixed rate levels by tenor")
scatter_df = new_trades.dropna(subset=["level", "tenor_years"])
scatter_df = scatter_df[(scatter_df["tenor_years"] > 0) & (scatter_df["tenor_years"] < 51)]
if scatter_df.empty:
    st.write("No fixed-rate levels available in this window.")
else:
    fig = px.scatter(
        scatter_df,
        x="tenor_years",
        y="level",
        color_discrete_sequence=[CATEGORICAL[0]],
        opacity=0.5,
        labels={"tenor_years": "Tenor (years)", "level": "Fixed rate"},
    )
    fig.update_traces(marker=dict(size=6))
    fig.update_layout(margin=dict(l=10, r=10, t=10, b=10))
    st.plotly_chart(fig, use_container_width=True, theme="streamlit")

st.caption(
    "Rate levels are derived from individual reported trades, not an official curve — "
    "expect noise from off-market/package trades and non-vanilla structures. "
    "'Total notional' only includes trades with a USD-denominated leg (no synthetic "
    "FX conversion); the currency chart shows trade count instead of notional for the "
    "same reason."
)
