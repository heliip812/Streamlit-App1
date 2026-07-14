from datetime import date

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from analytics import curve_kink, drop_outliers, flow_vs_average, sample_for_scatter, trend_signal
from config import RATES_LOOKBACK
from data.constants import (
    CURRENT_EFFR_DEFAULT,
    FOMC_MEETING_DATES_2026,
    SEP_AS_OF,
    SEP_DOT_PLOT_MEDIAN,
)
from data.sources import get_dtcc_trades, get_fed_funds_futures
from fed_path import meeting_expectations, step_probabilities
from ui import empty_state, metric_row, raw_data_expander, render, render_trading_signals, sidebar_date_range
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
TENOR_MIDPOINTS = dict(zip(labels, [0.5, 1.5, 3.5, 7.5, 20, 40]))
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
            x=curve_points["tenor_bucket"].map(TENOR_MIDPOINTS),
            y=curve_points["level"],
            mode="lines+markers",
            name=f"{currency} median curve",
            line=dict(color=CATEGORICAL[5], width=3),
            marker=dict(size=9),
        )
    )
    fig.update_layout(xaxis_title="Tenor (years)", yaxis_title="Fixed rate", legend_title=None)
    render(fig)

if not curve_df.empty and not curve_points.empty:
    trend_bucket = curve_df["tenor_bucket"].value_counts().idxmax()
    daily = curve_df[curve_df["tenor_bucket"] == trend_bucket].groupby("_trade_date")["level"].median()
    by_day_bucket = new_trades.dropna(subset=["tenor_bucket"]).groupby(["_trade_date", "tenor_bucket"], observed=True)["notional_usd_approx"].sum()

    render_trading_signals(
        trend=trend_signal(daily),
        trend_label=f"{trend_bucket} level",
        fmt_value=lambda v: f"{v:.4f}",
        fmt_delta=lambda v: f"{v:+.4f}",
        kink=curve_kink(curve_points.assign(x=curve_points["tenor_bucket"].map(TENOR_MIDPOINTS)), "tenor_bucket", "x", "level"),
        flow=flow_vs_average(by_day_bucket, new_trades["_trade_date"].max()),
        intro=(
            "Directional context derived from self-reported OTC trade prints within the date "
            "range selected above (widen it for more history) — not executable quotes, and not "
            "a substitute for a live pricing feed."
        ),
    )

raw_data_expander(
    curve_df,
    columns={
        "_trade_date": "Date",
        "tenor_bucket": "Tenor",
        "level": "Fixed rate",
        "notional_usd_approx": "Notional (USD)",
        "Cleared": "Cleared",
    },
    label=f"Show {currency} trade-level detail",
)

st.caption(
    "Rate levels are derived from individual reported trades, not an official curve — "
    "expect noise from off-market/package trades and non-vanilla structures. "
    "'Total notional' only includes trades with a USD-denominated leg (no synthetic "
    "FX conversion); the currency chart shows trade count instead of notional for the "
    "same reason."
)

# --- Fed policy path (market-implied) ----------------------------------------
# A distinct data source (CME Fed Funds futures, not DTCC) but a natural fit on
# the rates page. Uses st.info rather than empty_state on failure so a missing
# CME feed never halts the DTCC content above it.
st.divider()
st.subheader("Fed policy path (market-implied)")
st.caption(
    "The policy-rate path priced into CME 30-Day Fed Funds futures (the input behind "
    "CME's FedWatch), with per-meeting hike/cut/hold probabilities. Delayed free data, "
    "and the one section here sourced from CME rather than DTCC — an approximation of a "
    "live curve, not a live curve."
)

with st.sidebar:
    current_effr = st.number_input(
        "Current effective fed funds rate (EFFR), %",
        min_value=0.0,
        max_value=10.0,
        value=float(CURRENT_EFFR_DEFAULT),
        step=0.01,
        format="%.2f",
        help=(
            "Anchors the front of the implied Fed path below. Set to the current EFFR "
            "(NY Fed / FRED series EFFR); the default is a placeholder."
        ),
    )

fed_futures = get_fed_funds_futures()
fed_expectations = (
    meeting_expectations(fed_futures, FOMC_MEETING_DATES_2026, current_rate=current_effr, as_of=date.today())
    if not fed_futures.empty
    else []
)

if not fed_expectations:
    st.info(
        "Fed Funds futures aren't available right now — the CME feed is delayed and "
        "occasionally blocks automated requests, and is unreachable outside Streamlit "
        "Cloud. The rest of this page is unaffected."
    )
else:
    next_meeting = fed_expectations[0]
    next_probs = step_probabilities(next_meeting.change)
    most_likely_move, most_likely_prob = max(next_probs, key=lambda o: o[1])
    final_rate = fed_expectations[-1].rate_after
    metric_row(
        [
            ("Next meeting", next_meeting.meeting_date.strftime("%d %b %Y")),
            (
                "Priced for next meeting",
                f"{most_likely_move * 100:+.0f} bps" if most_likely_move else "No change",
                f"{most_likely_prob * 100:.0f}% likely",
            ),
            ("Implied cuts to year-end", f"{(final_rate - current_effr) * 100:+.0f} bps"),
        ]
    )

    fed_path_df = pd.DataFrame(
        {
            "date": [date.today()] + [e.meeting_date for e in fed_expectations],
            "rate": [current_effr] + [e.rate_after for e in fed_expectations],
        }
    )
    fed_fig = go.Figure()
    fed_fig.add_trace(
        go.Scatter(
            x=fed_path_df["date"],
            y=fed_path_df["rate"],
            mode="lines+markers",
            line=dict(color=CATEGORICAL[0], width=3, shape="hv"),
            marker=dict(size=8),
            name="Market-implied (futures)",
        )
    )
    last_year = fed_expectations[-1].meeting_date.year
    fed_dots = [(date(y, 12, 31), r) for y, r in sorted(SEP_DOT_PLOT_MEDIAN.items()) if y <= last_year]
    if fed_dots:
        fed_fig.add_trace(
            go.Scatter(
                x=[d for d, _ in fed_dots],
                y=[r for _, r in fed_dots],
                mode="markers",
                marker=dict(color=CATEGORICAL[5], size=13, symbol="diamond"),
                name=f"Dot plot median — {SEP_AS_OF}",
            )
        )
    fed_fig.update_layout(yaxis_title="Fed funds rate (%)", legend_title=None, hovermode="x unified")
    render(fed_fig)

    with st.expander("Per-meeting expectations & outcome probabilities"):
        fed_rows = []
        for exp in fed_expectations:
            move, prob = max(step_probabilities(exp.change), key=lambda o: o[1])
            fed_rows.append(
                {
                    "Meeting": exp.meeting_date.strftime("%d %b %Y"),
                    "Implied rate after (%)": round(exp.rate_after, 3),
                    "Expected change (bps)": round(exp.change * 100, 1),
                    "Most likely move": "No change" if move == 0 else f"{move * 100:+.0f} bps",
                    "Probability": f"{prob * 100:.0f}%",
                }
            )
        st.dataframe(pd.DataFrame(fed_rows), use_container_width=True, hide_index=True)
        st.caption(
            "Method: a 30-Day Fed Funds future settles to 100 − the month's average EFFR, so "
            "`100 − price` is the expected average rate; adjacent meeting-free months (or an "
            "in-month split) recover the rate each meeting is priced to leave in place. Meeting "
            "dates, the EFFR anchor and the dot-plot overlay are hand-maintained in "
            "data/constants.py — verify and update after each meeting / SEP release."
        )
