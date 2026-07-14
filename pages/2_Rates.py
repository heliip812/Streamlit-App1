import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from analytics import drop_outliers, sample_for_scatter
from config import RATES_LOOKBACK
from data.sources import get_dtcc_trades
from ui import empty_state, metric_row, render, sidebar_date_range
from viz_theme import CATEGORICAL

st.set_page_config(page_title="Rates — Derivatives Monitor", page_icon="📈", layout="wide")
st.title("Rates derivatives")
st.caption("Interest rate swaps reported to DTCC's Swap Data Repository.")

start_day, end_day = sidebar_date_range(RATES_LOOKBACK, "rates")

df = get_dtcc_trades("RATES", start_day, end_day)
new_trades = df[df["is_new_trade"]].copy() if not df.empty else df

if new_trades.empty:
    empty_state("No rates trades found in this date range. Try widening it — DTCC publishes with a short lag.")

metric_row(
    [
        ("Total notional", f"${new_trades['notional_usd_approx'].sum() / 1e9:,.1f}B"),
        ("Trades", f"{len(new_trades):,}"),
        ("Cleared", f"{(new_trades['Cleared'] == 'Y').mean() * 100:,.0f}%"),
    ]
)

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
    render(fig)

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
    render(fig)

st.subheader("Yield curve (spot proxy)")
st.caption(
    "Rates differ enormously by currency (e.g. JPY near 0% vs USD ~4%), so the curve "
    "below is built for one currency at a time — the short end (<1Y) is the closest "
    "proxy to a 'spot' rate this data offers."
)
currency_counts = new_trades["Notional currency-Leg 1"].value_counts()
currency_options = [c for c in currency_counts.index if c] or ["USD"]
default_index = currency_options.index("USD") if "USD" in currency_options else 0
currency = st.selectbox("Currency", currency_options, index=default_index)

curve_df = new_trades[
    (new_trades["Notional currency-Leg 1"] == currency)
    & new_trades["level"].notna()
    & new_trades["tenor_years"].between(0, 50, inclusive="right")
].copy()
curve_df = curve_df.loc[drop_outliers(curve_df["level"]).index]
curve_df["tenor_bucket"] = pd.cut(curve_df["tenor_years"], bins=bins, labels=labels)
curve_points = (
    curve_df.dropna(subset=["tenor_bucket"])
    .groupby("tenor_bucket", observed=True)["level"]
    .median()
    .reindex(labels)
    .dropna()
    .reset_index()
    if not curve_df.empty
    else pd.DataFrame(columns=["tenor_bucket", "level"])
)

if curve_df.empty:
    st.write(f"No fixed-rate levels available for {currency} in this window.")
else:
    scatter_sample = sample_for_scatter(curve_df)
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=scatter_sample["tenor_years"],
            y=scatter_sample["level"],
            mode="markers",
            name="Individual trades" if len(scatter_sample) == len(curve_df) else f"Individual trades (sample of {len(scatter_sample):,})",
            marker=dict(color=CATEGORICAL[0], size=6, opacity=0.35),
        )
    )
    fig.add_trace(
        go.Scatter(
            x=curve_points["tenor_bucket"].map(dict(zip(labels, [0.5, 1.5, 3.5, 7.5, 20, 40]))),
            y=curve_points["level"],
            mode="lines+markers",
            name=f"{currency} median curve",
            line=dict(color=CATEGORICAL[5], width=3),
            marker=dict(size=9),
        )
    )
    fig.update_layout(xaxis_title="Tenor (years)", yaxis_title="Fixed rate", legend_title=None)
    render(fig)

st.subheader("Trading signals")
st.caption(
    "Directional context derived from self-reported OTC trade prints within the date "
    "range selected above (widen it for more history) — not executable quotes, and not "
    "a substitute for a live pricing feed."
)

if curve_df.empty or curve_points.empty:
    st.write("Not enough data in this window to compute signals.")
else:
    trend_col, rv_col, flow_col = st.columns(3)

    with trend_col:
        st.markdown("**Trend**")
        bucket_counts = curve_df["tenor_bucket"].value_counts()
        trend_bucket = bucket_counts.idxmax()
        daily = curve_df[curve_df["tenor_bucket"] == trend_bucket].groupby("_trade_date")["level"].median().sort_index()
        if len(daily) >= 2:
            latest_val, prior_val = daily.iloc[-1], daily.iloc[-2]
            pct_rank = (daily <= latest_val).mean() * 100
            st.metric(f"{trend_bucket} level", f"{latest_val:.4f}", f"{latest_val - prior_val:+.4f} vs prior day")
            st.caption(f"{pct_rank:.0f}th percentile of {len(daily)} days in this window")
        else:
            st.write(f"Only one day of {trend_bucket} data in this window.")

    with rv_col:
        st.markdown("**Relative value (curve shape)**")
        midpoints = dict(zip(labels, [0.5, 1.5, 3.5, 7.5, 20, 40]))
        pts = curve_points.assign(x=curve_points["tenor_bucket"].map(midpoints)).sort_values("x").reset_index(drop=True)
        deviations = [
            (
                pts.loc[i, "tenor_bucket"],
                pts.loc[i, "level"]
                - (
                    pts.loc[i - 1, "level"]
                    + (pts.loc[i + 1, "level"] - pts.loc[i - 1, "level"])
                    * (pts.loc[i, "x"] - pts.loc[i - 1, "x"])
                    / (pts.loc[i + 1, "x"] - pts.loc[i - 1, "x"])
                ),
            )
            for i in range(1, len(pts) - 1)
        ]
        if deviations:
            bucket, deviation = max(deviations, key=lambda d: abs(d[1]))
            direction = "above" if deviation > 0 else "below"
            st.metric(f"Largest kink: {bucket}", f"{deviation:+.4f}", f"{direction} its neighbors' trend line")
        else:
            st.write("Need at least 3 curve points to assess shape.")

    with flow_col:
        st.markdown("**Flow vs. window average**")
        by_day_bucket = (
            new_trades.dropna(subset=["tenor_bucket"])
            .groupby(["_trade_date", "tenor_bucket"], observed=True)["notional_usd_approx"]
            .sum()
        )
        window_avg = by_day_bucket.groupby("tenor_bucket", observed=True).mean()
        latest_day = new_trades["_trade_date"].max()
        latest_by_bucket = by_day_bucket.xs(latest_day, level="_trade_date", drop_level=True) if latest_day in by_day_bucket.index.get_level_values("_trade_date") else pd.Series(dtype=float)
        # Ignore buckets too thin to be a meaningful baseline (avoids a near-zero
        # average turning a trivial trade into a false "50x normal" spike).
        material = window_avg[window_avg > window_avg.sum() * 0.01]
        ratios = (latest_by_bucket / material).dropna()
        if ratios.empty:
            st.write("Not enough data to compare today's flow to the window average.")
        else:
            bucket = ratios.idxmax()
            st.metric(f"{bucket} notional today", f"{ratios[bucket]:.1f}x", "of this window's average daily notional")

st.caption(
    "Rate levels are derived from individual reported trades, not an official curve — "
    "expect noise from off-market/package trades and non-vanilla structures. "
    "'Total notional' only includes trades with a USD-denominated leg (no synthetic "
    "FX conversion); the currency chart shows trade count instead of notional for the "
    "same reason."
)
