"""Shared Streamlit widgets used across every page.

Extracted because the same three patterns — a sidebar date+lookback pair,
a row of st.metric tiles, and "apply standard chart chrome then render" —
were copy-pasted nearly verbatim into every page. Keeping them here means
a future page (a new asset class, a new report type) is a few function
calls instead of re-deriving the same boilerplate again.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Callable, Literal

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from analytics import TrendSignal
from config import RangeConfig

CHART_MARGIN = dict(l=10, r=10, t=10, b=10)


def _latest_business_day() -> date:
    return pd.bdate_range(end=date.today() - timedelta(days=1), periods=1)[0].date()


def _nth_business_day_before(end: date, n: int) -> date:
    """The date n business days before (and including) `end`."""
    return pd.bdate_range(end=end, periods=n)[0].date()


def sidebar_date_range(cfg: RangeConfig, key_prefix: str) -> tuple[date, date]:
    """A calendar date-range picker (Streamlit's native two-date select mode).

    DTCC/CFTC never publish on weekends, so callers should fetch/plot
    business days only within whatever range comes back — Streamlit has no
    way to gray out specific days in the calendar widget itself, so the
    picker will still show Saturdays/Sundays as selectable even though
    they're meaningless. The range is capped to `cfg.max_value` business
    days (keeping the most recent ones if exceeded) — the safety limit
    that keeps a manually widened range from reintroducing the memory
    issues a wide window caused before.
    """
    latest = _latest_business_day()
    default_start = _nth_business_day_before(latest, cfg.default)
    with st.sidebar:
        selected = st.date_input(
            "Date range",
            value=(default_start, latest),
            max_value=latest,
            key=f"{key_prefix}_date_range",
        )
        if isinstance(selected, tuple) and len(selected) == 2:
            start, end = selected
        else:
            # Only one end picked so far (mid-selection) — treat as a single day.
            start = end = selected[0] if isinstance(selected, tuple) else selected

        business_days = pd.bdate_range(start=start, end=end)
        if len(business_days) > cfg.max_value:
            st.warning(f"Range capped at the most recent {cfg.max_value} business days for this page.")
            start = business_days[-cfg.max_value].date()

    return start, end


def render(fig: go.Figure, hide_weekends: bool = False) -> None:
    """Apply the shared chart margin and render through Streamlit's theme.

    hide_weekends compresses Sat/Sun out of a date x-axis (Plotly's
    rangebreaks) — without it, a line/bar chart over a business-day-only
    series still reserves visual space for the weekend, showing as a flat
    gap between Friday and Monday.
    """
    fig.update_layout(margin=CHART_MARGIN)
    if hide_weekends:
        fig.update_xaxes(rangebreaks=[dict(bounds=["sat", "mon"])])
    st.plotly_chart(fig, use_container_width=True, theme="streamlit")


def render_trading_signals(
    trend: TrendSignal | None,
    trend_label: str,
    fmt_value: Callable[[float], str],
    fmt_delta: Callable[[float], str],
    kink: tuple[str, float] | None,
    flow: tuple[str, float] | None,
    intro: str,
) -> None:
    """The standard three-panel 'Trading signals' row — trend (percentile +
    period-over-period change), relative value (curve-shape kink), and
    flow vs. window average — built from analytics.py's already-computed
    results so every page renders them identically. Any panel shows a
    plain "not enough data" message if its input is None rather than
    erroring, since a thin window/currency/pair selection is expected,
    not a bug.
    """
    st.subheader("Trading signals")
    st.caption(intro)
    trend_col, rv_col, flow_col = st.columns(3)

    with trend_col:
        st.markdown("**Trend**")
        if trend is None:
            st.write("Not enough data for a trend.")
        else:
            delta = fmt_delta(trend.change) + " vs prior period" if trend.change is not None else None
            st.metric(trend_label, fmt_value(trend.latest_value), delta)
            st.caption(f"{trend.percentile:.0f}th percentile of {trend.n_periods} periods in this window")

    with rv_col:
        st.markdown("**Relative value (curve shape)**")
        if kink is None:
            st.write("Need at least 3 curve points to assess shape.")
        else:
            bucket, deviation = kink
            direction = "above" if deviation > 0 else "below"
            st.metric(f"Largest kink: {bucket}", fmt_value(deviation), f"{direction} its neighbors' trend line")

    with flow_col:
        st.markdown("**Flow vs. window average**")
        if flow is None:
            st.write("Not enough data to compare flow to the window average.")
        else:
            bucket, ratio = flow
            st.metric(f"{bucket} — today", f"{ratio:.1f}x", "of this window's average")


def metric_row(metrics: list[tuple[str, ...]]) -> None:
    """A row of st.metric tiles from (label, value) or (label, value, delta) tuples."""
    cols = st.columns(len(metrics))
    for col, metric in zip(cols, metrics):
        col.metric(*metric)


def empty_state(message: str, kind: Literal["info", "warning"] = "info") -> None:
    """Standard 'nothing to show' banner that halts the rest of the page's script run."""
    (st.info if kind == "info" else st.warning)(message)
    st.stop()


def raw_data_expander(
    df: pd.DataFrame,
    columns: dict[str, str],
    label: str = "Show trade-level detail",
    max_rows: int = 2000,
) -> None:
    """A collapsed-by-default table of the underlying rows behind a page's
    charts — for anyone who wants to see more than the aggregate views
    without it cluttering the default page. `columns` maps internal column
    names to display labels and also selects which columns are shown, in
    that order. Capped at max_rows (most recent first) — this is meant for
    spot-checking specific trades, not for exporting the entire window; a
    display table with tens of thousands of rows is exactly the kind of
    thing that caused the memory issues fixed earlier.
    """
    with st.expander(label):
        shown = df.sort_values("_trade_date", ascending=False).head(max_rows) if "_trade_date" in df.columns else df.head(max_rows)
        if len(df) > max_rows:
            st.caption(f"Showing the most recent {max_rows:,} of {len(df):,} trades.")
        st.dataframe(
            shown[[c for c in columns if c in shown.columns]].rename(columns=columns),
            use_container_width=True,
            hide_index=True,
        )
