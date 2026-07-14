import pandas as pd
import plotly.express as px
import streamlit as st

from analytics import curve_kink, drop_outliers, flow_vs_average, trend_signal
from config import EQUITIES_COMMODITIES_LOOKBACK
from data.sources import get_dtcc_trades
from ui import empty_state, metric_row, raw_data_expander, render, render_trading_signals, sidebar_date_range
from viz_theme import CATEGORICAL

st.set_page_config(page_title="Equities & Commodities — Derivatives Monitor", page_icon="📈", layout="wide")
st.title("Equity & commodity derivatives")
st.caption("Equity and commodity swaps/options reported to DTCC's Swap Data Repository.")

start_day, end_day = sidebar_date_range(EQUITIES_COMMODITIES_LOOKBACK, "eqco")

# A selectbox (rather than st.tabs) so only the chosen asset class is
# fetched — Streamlit renders every tab's body on every rerun regardless of
# which is visually selected, which was needlessly fetching both Equities
# (by far the largest DTCC file, ~800k rows/day) and Commodities every time.
choice = st.radio("Asset class", ["Equities", "Commodities"], horizontal=True)
asset_code, color = {"Equities": ("EQUITIES", CATEGORICAL[3]), "Commodities": ("COMMODITIES", CATEGORICAL[4])}[choice]

if choice == "Commodities":
    st.caption(
        "This is OTC commodity swap data (real trades from DTCC's SDR) — not "
        "exchange-traded futures settlement prices, which require a paid CME/ICE feed. "
        "For free commodity **futures positioning** (open interest, net long/short by "
        "trader category), see the CFTC Positioning page."
    )

df = get_dtcc_trades(asset_code, start_day, end_day)
new_trades = df[df["is_new_trade"]].copy() if not df.empty else df

if new_trades.empty:
    empty_state("No trades found in this date range. Try widening it.")

metric_row(
    [
        ("Total notional", f"${new_trades['notional_usd_approx'].sum() / 1e9:,.1f}B"),
        ("Trades", f"{len(new_trades):,}"),
        ("Cleared", f"{(new_trades['Cleared'] == 'Y').mean() * 100:,.0f}%"),
    ]
)

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
    render(fig)

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
    render(fig, hide_weekends=True)

TENOR_BINS = [-1, 2, 9, 45, 135, 270, 100000]
TENOR_LABELS = ["Spot", "1W", "1M", "3M", "6M", "1Y+"]
new_trades["tenor_bucket"] = pd.cut(new_trades["tenor_days"], bins=TENOR_BINS, labels=TENOR_LABELS)

st.subheader("Tenor mix")
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
    color_discrete_sequence=[color],
    labels={"tenor_bucket": "", "notional_usd_approx": "Notional traded ($)"},
)
render(fig)

st.subheader("Level curve by tenor")
underlier_counts = new_trades["UPI Underlier Name"].value_counts()
underlier_choice = st.selectbox("Underlier", underlier_counts.index.tolist())
curve_df = new_trades[(new_trades["UPI Underlier Name"] == underlier_choice) & new_trades["level"].notna()]
curve_df = curve_df.loc[drop_outliers(curve_df["level"]).index]
curve_points = (
    curve_df.dropna(subset=["tenor_bucket"])
    .groupby("tenor_bucket", observed=True)
    .agg(median_level=("level", "median"), trades=("level", "size"))
    .reindex(TENOR_LABELS)
    .dropna()
    .reset_index()
)
if curve_points.empty:
    st.write(f"No usable price/rate levels for {underlier_choice} in this window.")
else:
    fig = px.line(
        curve_points,
        x="tenor_bucket",
        y="median_level",
        markers=True,
        color_discrete_sequence=[color],
        hover_data={"trades": True},
        labels={"tenor_bucket": "Tenor", "median_level": "Median executed level"},
    )
    fig.update_traces(marker=dict(size=10), line=dict(width=3))
    render(fig)

    TENOR_MIDPOINTS_DAYS = dict(zip(TENOR_LABELS, [1, 7, 30, 90, 180, 365]))
    trend_bucket = curve_df["tenor_bucket"].value_counts().idxmax()
    daily = curve_df[curve_df["tenor_bucket"] == trend_bucket].groupby("_trade_date")["level"].median()
    by_day_bucket = curve_df.dropna(subset=["tenor_bucket"]).groupby(["_trade_date", "tenor_bucket"], observed=True)["notional_usd_approx"].sum()

    render_trading_signals(
        trend=trend_signal(daily),
        trend_label=f"{trend_bucket} level",
        fmt_value=lambda v: f"{v:.4f}",
        fmt_delta=lambda v: f"{v:+.4f}",
        kink=curve_kink(curve_points.assign(x=curve_points["tenor_bucket"].map(TENOR_MIDPOINTS_DAYS)), "tenor_bucket", "x", "median_level"),
        flow=flow_vs_average(by_day_bucket, curve_df["_trade_date"].max()),
        intro=(
            f"Directional context for {underlier_choice} derived from self-reported OTC trade prints "
            "within the date range selected above (widen it for more history) — not executable "
            "quotes, and not a substitute for a live pricing feed."
        ),
    )

raw_data_expander(
    curve_df,
    columns={
        "_trade_date": "Date",
        "tenor_bucket": "Tenor",
        "level": "Executed level",
        "notional_usd_approx": "Notional (USD)",
        "Cleared": "Cleared",
    },
    label=f"Show {underlier_choice} trade-level detail",
)

st.caption(
    "Notional figures only include trades with a USD-denominated leg (no synthetic "
    "FX conversion), so non-USD-only trades are excluded."
)
