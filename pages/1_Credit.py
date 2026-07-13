import pandas as pd
import plotly.express as px
import streamlit as st

from analytics import drop_outliers
from config import CREDIT_LOOKBACK
from data.sources import get_dtcc_trades
from ui import empty_state, metric_row, render, sidebar_date_and_lookback
from viz_theme import CATEGORICAL

st.set_page_config(page_title="Credit — Derivatives Monitor", page_icon="📈", layout="wide")
st.title("Credit derivatives")
st.caption("CDS single names and index trades reported to DTCC's Swap Data Repository.")

as_of, lookback_days = sidebar_date_and_lookback(CREDIT_LOOKBACK, "credit")

df = get_dtcc_trades("CREDITS", as_of, lookback_days)
new_trades = df[df["is_new_trade"]].copy() if not df.empty else df

if new_trades.empty:
    empty_state("No credit trades found in this window. Try an earlier 'as of' date — DTCC publishes with a short lag.")

index_trades = new_trades[new_trades["is_index"]]
single_name_trades = new_trades[~new_trades["is_index"]]

metric_row(
    [
        ("Total notional", f"${new_trades['notional_usd_approx'].sum() / 1e9:,.1f}B"),
        ("Trades", f"{len(new_trades):,}"),
        ("Index share of notional", f"{index_trades['notional_usd_approx'].sum() / new_trades['notional_usd_approx'].sum() * 100:,.0f}%"),
        ("Cleared", f"{(new_trades['Cleared'] == 'Y').mean() * 100:,.0f}%"),
    ]
)

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
fig.update_layout(legend_title=None, bargap=0.15)
render(fig)

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

st.subheader("Spread curve by tenor")
st.caption(
    "CDS liquidity concentrates overwhelmingly at the 5Y 'on-the-run' tenor, so this is "
    "a thin curve compared to rates — treat non-5Y points as indicative at best. Index "
    "trades also often report the fixed standard coupon (e.g. 100bps for CDX.NA.IG) "
    "rather than the traded market spread, since the actual market level for a "
    "standardized index is expressed as an upfront price DTCC doesn't disclose here — "
    "so this curve is directional, not a substitute for a real quoted spread."
)
if index_trades.empty:
    st.write("No index trades in this window to build a curve from.")
else:
    top_names = index_trades["UPI Underlier Name"].value_counts()
    index_choice = st.selectbox("Index", top_names.index.tolist())
    curve_df = index_trades[
        (index_trades["UPI Underlier Name"] == index_choice) & index_trades["level"].notna()
    ].copy()
    curve_df = curve_df.loc[drop_outliers(curve_df["level"]).index]

    tenor_bins = [0, 2, 4, 6, 8.5, 12]
    tenor_labels = ["1Y", "3Y", "5Y", "7Y", "10Y"]
    curve_df["tenor_bucket"] = pd.cut(curve_df["tenor_years"], bins=tenor_bins, labels=tenor_labels)
    curve_points = (
        curve_df.dropna(subset=["tenor_bucket"])
        .groupby("tenor_bucket", observed=True)
        .agg(median_spread=("level", "median"), trades=("level", "size"))
        .reindex(tenor_labels)
        .dropna()
        .reset_index()
    )

    if curve_points.empty:
        st.write(f"No usable spread levels for {index_choice} in this window.")
    else:
        fig = px.line(
            curve_points,
            x="tenor_bucket",
            y="median_spread",
            markers=True,
            color_discrete_sequence=[CATEGORICAL[0]],
            hover_data={"trades": True},
            labels={"tenor_bucket": "Tenor", "median_spread": "Median spread/rate"},
        )
        fig.update_traces(marker=dict(size=10), line=dict(width=3))
        render(fig)

st.caption(
    "Spread/rate levels are derived from individual reported trades, not an official "
    "composite fixing — treat as indicative, particularly for thinly traded names. "
    "Notional figures only include trades with a USD-denominated leg (no synthetic "
    "FX conversion), so non-USD-only trades (e.g. EUR-only iTraxx) are excluded."
)
