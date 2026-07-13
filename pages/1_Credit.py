from datetime import date, timedelta

import plotly.express as px
import streamlit as st

from data.sources import get_dtcc_trades
from viz_theme import CATEGORICAL

st.set_page_config(page_title="Credit — Derivatives Monitor", page_icon="📈", layout="wide")
st.title("Credit derivatives")
st.caption("CDS single names and index trades reported to DTCC's Swap Data Repository.")

with st.sidebar:
    as_of = st.date_input("As of date", value=date.today() - timedelta(days=1), key="credit_as_of")
    lookback_days = st.slider("Lookback window (days)", 3, 30, 7, key="credit_lookback")

df = get_dtcc_trades("CREDITS", as_of, lookback_days)
new_trades = df[df["is_new_trade"]].copy() if not df.empty else df

if new_trades.empty:
    st.info("No credit trades found in this window. Try an earlier 'as of' date — DTCC publishes with a short lag.")
    st.stop()

index_trades = new_trades[new_trades["is_index"]]
single_name_trades = new_trades[~new_trades["is_index"]]

c1, c2, c3, c4 = st.columns(4)
c1.metric("Total notional", f"${new_trades['notional_usd_approx'].sum() / 1e9:,.1f}B")
c2.metric("Trades", f"{len(new_trades):,}")
c3.metric("Index share of notional", f"{index_trades['notional_usd_approx'].sum() / new_trades['notional_usd_approx'].sum() * 100:,.0f}%")
c4.metric("Cleared", f"{(new_trades['Cleared'] == 'Y').mean() * 100:,.0f}%")

st.subheader("Daily notional traded — index vs. single name")
daily = (
    new_trades.groupby(["_trade_date", "is_index"])["notional_usd_approx"]
    .sum()
    .reset_index()
    .replace({"is_index": {True: "Index (CDX/iTraxx)", False: "Single name"}})
)
fig = px.bar(
    daily,
    x="_trade_date",
    y="notional_usd_approx",
    color="is_index",
    color_discrete_sequence=[CATEGORICAL[0], CATEGORICAL[1]],
    labels={"_trade_date": "", "notional_usd_approx": "Notional traded ($)", "is_index": ""},
)
fig.update_layout(legend_title=None, margin=dict(l=10, r=10, t=10, b=10), bargap=0.15)
st.plotly_chart(fig, use_container_width=True, theme="streamlit")

col_left, col_right = st.columns(2)

with col_left:
    st.subheader("Most active index trades")
    if index_trades.empty:
        st.write("No index trades in this window.")
    else:
        top_index = (
            index_trades.groupby("UPI Underlier Name")
            .agg(
                notional=("notional_usd_approx", "sum"),
                trades=("notional_usd_approx", "size"),
                median_spread=("level", "median"),
            )
            .sort_values("notional", ascending=False)
            .head(10)
            .reset_index()
        )
        top_index["notional"] = top_index["notional"] / 1e9
        st.dataframe(
            top_index.rename(
                columns={
                    "UPI Underlier Name": "Index",
                    "notional": "Notional ($B)",
                    "trades": "Trades",
                    "median_spread": "Median spread/rate",
                }
            ),
            use_container_width=True,
            hide_index=True,
        )

with col_right:
    st.subheader("Most active single names")
    if single_name_trades.empty:
        st.write("No single-name trades in this window.")
    else:
        top_names = (
            single_name_trades.groupby("UPI Underlier Name")
            .agg(
                notional=("notional_usd_approx", "sum"),
                trades=("notional_usd_approx", "size"),
                median_spread=("level", "median"),
            )
            .sort_values("notional", ascending=False)
            .head(10)
            .reset_index()
        )
        top_names["notional"] = top_names["notional"] / 1e9
        st.dataframe(
            top_names.rename(
                columns={
                    "UPI Underlier Name": "Reference entity",
                    "notional": "Notional ($B)",
                    "trades": "Trades",
                    "median_spread": "Median spread/rate",
                }
            ),
            use_container_width=True,
            hide_index=True,
        )

st.caption(
    "Spread/rate levels are derived from individual reported trades, not an official "
    "composite fixing — treat as indicative, particularly for thinly traded names. "
    "Notional figures only include trades with a USD-denominated leg (no synthetic "
    "FX conversion), so non-USD-only trades (e.g. EUR-only iTraxx) are excluded."
)
