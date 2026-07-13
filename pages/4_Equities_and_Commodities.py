from datetime import date, timedelta

import plotly.express as px
import streamlit as st

from data.sources import get_dtcc_trades
from viz_theme import CATEGORICAL

st.set_page_config(page_title="Equities & Commodities — Derivatives Monitor", page_icon="📈", layout="wide")
st.title("Equity & commodity derivatives")
st.caption("Equity and commodity swaps/options reported to DTCC's Swap Data Repository.")

with st.sidebar:
    as_of = st.date_input("As of date", value=date.today() - timedelta(days=1), key="eqco_as_of")
    lookback_days = st.slider("Lookback window (days)", 3, 21, 3, key="eqco_lookback")

# A selectbox (rather than st.tabs) so only the chosen asset class is
# fetched — Streamlit renders every tab's body on every rerun regardless of
# which is visually selected, which was needlessly fetching both Equities
# (by far the largest DTCC file, ~800k rows/day) and Commodities every time.
choice = st.radio("Asset class", ["Equities", "Commodities"], horizontal=True)
asset_code, color = {"Equities": ("EQUITIES", CATEGORICAL[3]), "Commodities": ("COMMODITIES", CATEGORICAL[4])}[choice]

df = get_dtcc_trades(asset_code, as_of, lookback_days)
new_trades = df[df["is_new_trade"]].copy() if not df.empty else df

if new_trades.empty:
    st.info("No trades found in this window. Try an earlier 'as of' date.")
    st.stop()

c1, c2, c3 = st.columns(3)
c1.metric("Total notional", f"${new_trades['notional_usd_approx'].sum() / 1e9:,.1f}B")
c2.metric("Trades", f"{len(new_trades):,}")
c3.metric("Cleared", f"{(new_trades['Cleared'] == 'Y').mean() * 100:,.0f}%")

col_left, col_right = st.columns(2)

with col_left:
    st.subheader("Most active underliers")
    top = (
        new_trades.groupby("UPI Underlier Name")["notional_usd_approx"]
        .sum()
        .sort_values(ascending=False)
        .head(10)
        .reset_index()
    )
    fig = px.bar(
        top,
        x="UPI Underlier Name",
        y="notional_usd_approx",
        color_discrete_sequence=[color],
        labels={"UPI Underlier Name": "", "notional_usd_approx": "Notional traded ($)"},
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
        color_discrete_sequence=[color],
        labels={"_trade_date": "", "notional_usd_approx": "Notional traded ($)"},
    )
    fig.update_layout(margin=dict(l=10, r=10, t=10, b=10))
    st.plotly_chart(fig, use_container_width=True, theme="streamlit")

st.caption(
    "Notional figures only include trades with a USD-denominated leg (no synthetic "
    "FX conversion), so non-USD-only trades are excluded."
)
