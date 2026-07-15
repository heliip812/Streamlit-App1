from datetime import date

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from analytics import curve_kink, drop_outliers, flow_vs_average, sample_for_scatter, trend_signal
from config import RATES_LOOKBACK
from data.constants import (
    CURRENT_EFFR_DEFAULT,
    CURRENT_ESTR_DEFAULT,
    ECB_MEETING_DATES_FALLBACK,
    FOMC_MEETING_DATES_FALLBACK,
    FRED_EFFR_SERIES,
    FRED_TARGET_LOWER_SERIES,
    FRED_TARGET_UPPER_SERIES,
    FRED_YIELD_SERIES,
    SEP_AS_OF,
    SEP_DOT_PLOT_MEDIAN,
)
from data.sources import get_dtcc_trades, get_ecb_rates, get_fred_rates, get_meeting_dates
from fed_path import implied_forward_path, implied_rate_at
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

# --- Central bank policy path (market-implied) -------------------------------
# A distinct data source (government yield curves, not DTCC) but a natural fit
# on the rates page. Uses st.info rather than empty_state on failure so a
# missing rates feed never halts the DTCC content above it.


def _render_policy_path(path, anchor_rate, meeting_dates, meeting_source, *, meeting_label, yaxis_title, dot_plot=None, dot_label=None):
    """Shared render of an implied-path chart + per-meeting table for either
    central bank: the path plotted against calendar dates, an optional
    dot-plot overlay (Fed only), and the interpolated implied rate at each
    upcoming meeting."""
    today = date.today()
    path_dates = [today + pd.Timedelta(days=round(h * 365)) for h in path["horizon_years"]]
    last_date = path_dates[-1]

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=path_dates,
            y=path["rate"],
            mode="lines+markers",
            line=dict(color=CATEGORICAL[0], width=3),
            marker=dict(size=8),
            name="Market-implied path",
        )
    )
    if dot_plot:
        dots = [(date(y, 12, 31), r) for y, r in sorted(dot_plot.items()) if date(y, 12, 31) <= last_date]
        if dots:
            fig.add_trace(
                go.Scatter(
                    x=[d for d, _ in dots],
                    y=[r for _, r in dots],
                    mode="markers",
                    marker=dict(color=CATEGORICAL[5], size=13, symbol="diamond"),
                    name=dot_label,
                )
            )
    fig.update_layout(yaxis_title=yaxis_title, legend_title=None, hovermode="x unified")
    render(fig)

    with st.expander(f"Implied rate at each upcoming {meeting_label} meeting"):
        prior_rate = anchor_rate
        rows = []
        for meeting in sorted(meeting_dates):
            if meeting < today or meeting > last_date:
                continue
            rate = implied_rate_at(path, (meeting - today).days / 365.0)
            if rate is None:
                continue
            rows.append(
                {
                    "Meeting": meeting.strftime("%d %b %Y"),
                    "Implied rate (%)": round(rate, 3),
                    "Cumulative vs now (bps)": round((rate - anchor_rate) * 100, 0),
                    "Change since prior meeting (bps)": round((rate - prior_rate) * 100, 0),
                }
            )
            prior_rate = rate
        if rows:
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        else:
            st.caption(f"No upcoming {meeting_label} meetings fall within the curve's horizon.")
        st.caption(
            f"Meeting dates: {meeting_source}. Implied rates are read off the government-curve "
            "forward path at each meeting date (interpolated), not a meeting-by-meeting "
            "probability model — the curve reflects continuous expectations, not discrete "
            "decisions."
        )


st.divider()
st.subheader("Central bank policy path (market-implied)")
st.caption(
    "Where the market expects policy rates to go, implied by each central bank's short-end "
    "government curve — FRED's Treasury curve for the Fed, the ECB Data Portal's euro-area "
    "curve for the ECB (both free and keyless). A government-curve proxy: small term premium "
    "and safe-haven collateral richness make it read marginally more dovish than a pure OIS "
    "measure — good for direction and rough magnitude, not a live policy-expectations curve."
)
central_bank = st.radio("Central bank", ["Federal Reserve", "ECB"], horizontal=True)
today = date.today()
year_end_horizon = (date(today.year, 12, 31) - today).days / 365.0

if central_bank == "Federal Reserve":
    fred_series = (FRED_EFFR_SERIES, FRED_TARGET_UPPER_SERIES, FRED_TARGET_LOWER_SERIES) + tuple(FRED_YIELD_SERIES)
    fred_data = get_fred_rates(fred_series)
    yields_by_years = {FRED_YIELD_SERIES[sid]: fred_data[sid] for sid in FRED_YIELD_SERIES if sid in fred_data}
    if not yields_by_years:
        st.info(
            "FRED Treasury series aren't available right now (FRED is unreachable outside "
            "Streamlit Cloud, and can briefly rate-limit). The rest of this page is unaffected."
        )
    else:
        anchor = float(fred_data.get(FRED_EFFR_SERIES, CURRENT_EFFR_DEFAULT))
        path = implied_forward_path(yields_by_years, anchor_rate=anchor)
        year_end_rate = implied_rate_at(path, year_end_horizon)
        upper, lower = fred_data.get(FRED_TARGET_UPPER_SERIES), fred_data.get(FRED_TARGET_LOWER_SERIES)
        metric_row(
            [
                ("Current EFFR", f"{anchor:.2f}%"),
                ("Target range", f"{lower:.2f}–{upper:.2f}%" if upper is not None and lower is not None else "N/A"),
                (
                    f"Implied by end-{today.year}",
                    f"{year_end_rate:.2f}%" if year_end_rate is not None else "N/A",
                    f"{(year_end_rate - anchor) * 100:+.0f} bps" if year_end_rate is not None else None,
                ),
            ]
        )
        scraped = get_meeting_dates("fomc")
        meetings = scraped or FOMC_MEETING_DATES_FALLBACK
        source = "live from the Fed calendar" if scraped else "fallback list in constants.py (verify against federalreserve.gov)"
        _render_policy_path(
            path,
            anchor,
            meetings,
            source,
            meeting_label="FOMC",
            yaxis_title="Fed funds rate (%)",
            dot_plot=SEP_DOT_PLOT_MEDIAN,
            dot_label=f"Dot plot median — {SEP_AS_OF}",
        )
else:
    ecb_data = get_ecb_rates()
    yields_by_years = ecb_data.get("yields", {})
    if not yields_by_years:
        st.info(
            "ECB Data Portal series aren't available right now (unreachable outside Streamlit "
            "Cloud, and can briefly rate-limit). The rest of this page is unaffected."
        )
    else:
        estr, dfr_anchor = ecb_data.get("estr"), ecb_data.get("dfr")
        anchor = estr if estr is not None else (dfr_anchor if dfr_anchor is not None else CURRENT_ESTR_DEFAULT)
        path = implied_forward_path(yields_by_years, anchor_rate=anchor)
        year_end_rate = implied_rate_at(path, year_end_horizon)
        dfr, mro = ecb_data.get("dfr"), ecb_data.get("mro")
        metric_row(
            [
                ("€STR (overnight)", f"{anchor:.2f}%"),
                (
                    "Deposit facility / MRO",
                    f"{dfr:.2f}% / {mro:.2f}%" if dfr is not None and mro is not None else "N/A",
                ),
                (
                    f"Implied by end-{today.year}",
                    f"{year_end_rate:.2f}%" if year_end_rate is not None else "N/A",
                    f"{(year_end_rate - anchor) * 100:+.0f} bps" if year_end_rate is not None else None,
                ),
            ]
        )
        scraped = get_meeting_dates("ecb")
        meetings = scraped or ECB_MEETING_DATES_FALLBACK
        source = "live from the ECB calendar" if scraped else "fallback list in constants.py (verify against ecb.europa.eu)"
        _render_policy_path(
            path,
            anchor,
            meetings,
            source,
            meeting_label="ECB Governing Council",
            yaxis_title="ECB policy rate (%)",
        )
