from datetime import date

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from analytics import curve_kink, drop_outliers, flow_vs_average, sample_for_scatter, trend_signal
from config import RATES_LOOKBACK
from data.central_banks import CENTRAL_BANKS, get_spec
from data.sources import get_dtcc_trades, get_meeting_dates, get_policy_inputs
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


def _maturity_label(years: float) -> str:
    return {1 / 12: "1M", 0.25: "3M", 0.5: "6M", 1.0: "1Y", 2.0: "2Y"}.get(years, f"{years:g}Y")


def _render_policy_path(path, anchor_rate, meeting_dates, meeting_source, *, meeting_label, yaxis_title, dot_plot=None, dot_label=None):
    """The implied-path chart plus the per-meeting implied-rate table, shown
    inline (not collapsed) so the meeting-by-meeting detail is visible, not
    just the year-end figure."""
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

    st.markdown(f"**Implied rate at each upcoming {meeting_label} meeting**")
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
    st.caption(f"Meeting dates: {meeting_source}.")


def _render_sources_panel(spec, raw_yields, anchor_rate, status):
    """A collapsible 'show your work' panel for validation: the exact raw
    sources (tap to check them), the actual yields fetched, and the formula
    that turns them into the implied path. Shown for every bank — including
    ones with no data, so an empty curve is diagnosable from the source link."""
    with st.expander("Data source & how it's derived (for validation)"):
        st.markdown("**Live status:** " + " · ".join(status))

        st.markdown("**Raw sources** (tap to verify the numbers against the origin):")
        for label, url in spec.sources:
            st.markdown(f"- [{label}]({url})")

        if raw_yields:
            st.markdown("**Raw curve fetched** (the exact inputs to the calculation):")
            curve = pd.DataFrame(
                [{"Maturity": _maturity_label(y), "Market yield (%)": round(raw_yields[y], 3)} for y in sorted(raw_yields)]
            )
            st.dataframe(curve, use_container_width=True, hide_index=True)
            st.caption(f"Overnight anchor used: {anchor_rate:.2f}% (at horizon 0).")
        else:
            st.markdown("**Raw curve fetched:** none — the curve source above returned no usable data.")

        st.markdown(
            "**Method.** A yield to maturity *t* is (roughly) the market's expected *average* "
            "overnight rate over the next *t* years, so the implied **forward** rate between two "
            "maturities is the expected average over that future window:\n\n"
            "```\nforward(a, b) = (yield_b × b − yield_a × a) / (b − a)\n```\n\n"
            "Chaining these forwards across the maturities above, anchored at horizon 0 to the "
            "overnight rate, traces the implied path; the meeting table reads that path at each "
            "meeting date (interpolated). It is a government-curve **proxy**: it carries a little "
            "term premium and safe-haven/collateral richness, so it reads marginally more dovish "
            "than a pure OIS/futures measure — right on direction and rough magnitude, not "
            "basis-point-exact, and not a discrete hike/cut probability model."
        )


st.divider()
st.subheader("Central bank policy path (market-implied)")
st.caption(
    "Where the market expects policy rates to go, implied by each central bank's short-end "
    "government curve (free, keyless sources with independent fallbacks). A government-curve "
    "proxy: small term premium and safe-haven collateral richness make it read marginally "
    "more dovish than a pure OIS measure — good for direction and rough magnitude, not a "
    "live policy-expectations curve."
)
bank_label = st.radio("Central bank", [spec.label for spec in CENTRAL_BANKS], horizontal=True)
spec = get_spec(bank_label)
inputs = get_policy_inputs(spec.code)
scraped_meetings = get_meeting_dates(spec.calendar_code)

# A failed fetch must not sit in the cache for its full TTL looking permanent
# (one bad FRED call used to pin "unavailable" for an hour on the deployed
# app) — clear so the next interaction retries.
if not inputs.yields:
    get_policy_inputs.clear()
if not scraped_meetings:
    get_meeting_dates.clear()

st.caption(
    "Data sources — "
    + " · ".join(inputs.status)
    + f" · Meetings: {'official calendar' if scraped_meetings else 'fallback list'}"
)

with st.sidebar:
    anchor = st.number_input(
        spec.anchor_label,
        min_value=-1.0,
        max_value=10.0,
        value=float(inputs.anchor_rate if inputs.anchor_rate is not None else spec.anchor_fallback),
        step=0.01,
        format="%.2f",
        key=f"{spec.code}_anchor",
        help="Anchors the front of the implied path below; defaults to the live value when available.",
    )

if not inputs.yields:
    st.info(
        f"The {spec.label} yield-curve feed isn't available right now — the source status "
        "above says which feeds failed, and it will retry on the next interaction. Open the "
        "panel below to see (and tap) the exact source it's trying. The rest of this page is "
        "unaffected."
    )
else:
    today = date.today()
    path = implied_forward_path(inputs.yields, anchor_rate=anchor)
    year_end_rate = implied_rate_at(path, (date(today.year, 12, 31) - today).days / 365.0)
    metric_row(
        [
            (spec.anchor_metric_label, f"{anchor:.2f}%"),
            *inputs.metrics,
            (
                f"Implied by end-{today.year}",
                f"{year_end_rate:.2f}%" if year_end_rate is not None else "N/A",
                f"{(year_end_rate - anchor) * 100:+.0f} bps" if year_end_rate is not None else None,
            ),
        ]
    )
    meetings = scraped_meetings or spec.meeting_fallback
    source = (
        "live from the official calendar"
        if scraped_meetings
        else f"fallback list in constants.py (verify against {spec.calendar_hint})"
    )
    _render_policy_path(
        path,
        anchor,
        meetings,
        source,
        meeting_label=spec.meeting_label,
        yaxis_title=spec.yaxis_title,
        dot_plot=spec.dot_plot,
        dot_label=spec.dot_label,
    )

_render_sources_panel(spec, inputs.yields, anchor, inputs.status)
