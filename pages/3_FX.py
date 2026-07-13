import pandas as pd
import plotly.express as px
import streamlit as st

from analytics import drop_outliers
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

TENOR_BINS = [-1, 2, 9, 45, 135, 270, 100000]
TENOR_LABELS = ["Spot", "1W", "1M", "3M", "6M", "1Y+"]
new_trades["tenor_bucket"] = pd.cut(new_trades["tenor_days"], bins=TENOR_BINS, labels=TENOR_LABELS)

metric_row(
    [
        ("Total notional", f"${new_trades['notional_usd_approx'].sum() / 1e9:,.1f}B"),
        ("Trades", f"{len(new_trades):,}"),
        ("Spot share of trades", f"{(new_trades['tenor_bucket'] == 'Spot').mean() * 100:,.0f}%"),
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

st.subheader("Spot vs. tenor")
st.caption("'Spot' = settlement within 2 days of execution; everything longer is a forward/swap tenor bucket.")
tenor_notional = (
    new_trades.dropna(subset=["tenor_bucket"])
    .groupby("tenor_bucket", observed=True)["notional_usd_approx"]
    .sum()
    .reindex(TENOR_LABELS)
    .fillna(0)
    .reset_index()
)
fig = px.bar(
    tenor_notional,
    x="tenor_bucket",
    y="notional_usd_approx",
    color_discrete_sequence=[CATEGORICAL[3]],
    labels={"tenor_bucket": "", "notional_usd_approx": "Notional traded ($)"},
)
render(fig)

st.subheader("Forward curve (executed rate by tenor)")
pair_counts = new_trades["pair"].value_counts()
pair_choice = st.selectbox("Currency pair", pair_counts.index.tolist())
curve_df = new_trades[(new_trades["pair"] == pair_choice) & new_trades["level"].notna()]
curve_df = curve_df.loc[drop_outliers(curve_df["level"]).index]
curve_points = (
    curve_df.dropna(subset=["tenor_bucket"])
    .groupby("tenor_bucket", observed=True)
    .agg(median_rate=("level", "median"), trades=("level", "size"))
    .reindex(TENOR_LABELS)
    .dropna()
    .reset_index()
)
if curve_points.empty:
    st.write(f"No usable exchange rate levels for {pair_choice} in this window.")
else:
    fig = px.line(
        curve_points,
        x="tenor_bucket",
        y="median_rate",
        markers=True,
        color_discrete_sequence=[CATEGORICAL[2]],
        hover_data={"trades": True},
        labels={"tenor_bucket": "Tenor", "median_rate": "Median executed rate"},
    )
    fig.update_traces(marker=dict(size=10), line=dict(width=3))
    render(fig)

st.caption(
    "Currency pair labels reflect DTCC's leg currency order and are not normalized to "
    "market convention. Notional is the USD-denominated leg's reported amount (no "
    "synthetic FX conversion); cross pairs with neither leg in USD are excluded. The "
    "forward curve moves with forward points as well as spot, so a rising/falling curve "
    "isn't necessarily a spot rate view."
)
