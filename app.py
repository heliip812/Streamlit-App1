from datetime import date, timedelta

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from data.constants import DTCC_ASSET_CLASSES
from data.sources import get_all_asset_classes
from viz_theme import CATEGORICAL

st.set_page_config(page_title="Derivatives Market Monitor", page_icon="📈", layout="wide")

st.title("Derivatives Market Monitor")
st.caption(
    "Trade-level liquidity across credit, rates, FX, equity and commodity derivatives, "
    "sourced from public regulatory disclosures."
)

with st.sidebar:
    st.header("Settings")
    as_of = st.date_input("As of date", value=date.today() - timedelta(days=1))
    lookback_days = st.slider("Lookback window (calendar days)", min_value=3, max_value=21, value=3)
    st.divider()
    st.markdown(
        "**Sources**\n\n"
        "- [DTCC SDR public dissemination](https://www.dtcc.com/public-reporting) "
        "— real trade prints (Dodd-Frank Part 43/45), free, no auth\n"
        "- [CFTC Commitments of Traders](https://www.cftc.gov/MarketReports/CommitmentsofTraders/index.htm) "
        "— weekly futures positioning, free\n\n"
        "Official CDX/iTraxx index levels require a licensed Markit/ICE data feed "
        "and are **not** included — figures here are derived from actual reported "
        "trades, not composite index fixings.\n\n"
        "Some trades report notional as undisclosed (masked by DTCC); these are "
        "excluded from volume totals rather than guessed at, so figures are a "
        "floor, not an exact total. Notional totals only include trades with a "
        "USD-denominated leg (no synthetic FX conversion), so non-USD activity "
        "(e.g. EUR-only swaps) is under-represented here."
    )

data_by_class = get_all_asset_classes(as_of, lookback_days)

latest_day_rows = []
trend_frames = []
for label, df in data_by_class.items():
    new_trades = df[df["is_new_trade"]] if not df.empty else df
    if new_trades.empty:
        latest_day_rows.append({"Asset class": label, "Notional (latest day)": 0, "Trades (latest day)": 0})
        continue

    latest_day = new_trades["_trade_date"].max()
    latest = new_trades[new_trades["_trade_date"] == latest_day]
    latest_day_rows.append(
        {
            "Asset class": label,
            "Notional (latest day)": latest["notional_usd_approx"].sum(),
            "Trades (latest day)": len(latest),
        }
    )

    daily = new_trades.groupby("_trade_date")["notional_usd_approx"].sum().reset_index()
    daily["Asset class"] = label
    trend_frames.append(daily)

summary_df = pd.DataFrame(latest_day_rows)

st.subheader("Latest trading day, by asset class")
cols = st.columns(len(summary_df))
for col, (_, row) in zip(cols, summary_df.iterrows()):
    notional_bn = row["Notional (latest day)"] / 1e9
    col.metric(row["Asset class"], f"${notional_bn:,.1f}B", f"{int(row['Trades (latest day)']):,} trades")

st.subheader(f"Notional volume trend — last {lookback_days} days")
if trend_frames:
    trend_df = pd.concat(trend_frames, ignore_index=True)
    fig = go.Figure()
    for i, label in enumerate(DTCC_ASSET_CLASSES.values()):
        series = trend_df[trend_df["Asset class"] == label].sort_values("_trade_date")
        if series.empty:
            continue
        fig.add_trace(
            go.Scatter(
                x=series["_trade_date"],
                y=series["notional_usd_approx"] / 1e9,
                mode="lines+markers",
                name=label,
                line=dict(color=CATEGORICAL[i % len(CATEGORICAL)], width=2),
                marker=dict(size=6),
            )
        )
    fig.update_layout(
        yaxis_title="Notional traded ($B)",
        xaxis_title=None,
        legend_title=None,
        hovermode="x unified",
        margin=dict(l=10, r=10, t=10, b=10),
    )
    st.plotly_chart(fig, use_container_width=True, theme="streamlit")
else:
    st.info("No trades found in this window yet — try an earlier 'as of' date.")

st.divider()
st.markdown(
    "Use the pages in the sidebar for a closer look at **Credit** (CDS names & index), "
    "**Rates**, **FX**, **Equities & Commodities**, and **CFTC positioning**."
)
