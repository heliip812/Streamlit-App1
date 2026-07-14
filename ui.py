"""Shared Streamlit widgets used across every page.

Extracted because the same three patterns — a sidebar date+lookback pair,
a row of st.metric tiles, and "apply standard chart chrome then render" —
were copy-pasted nearly verbatim into every page. Keeping them here means
a future page (a new asset class, a new report type) is a few function
calls instead of re-deriving the same boilerplate again.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Literal

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

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


def metric_row(metrics: list[tuple[str, ...]]) -> None:
    """A row of st.metric tiles from (label, value) or (label, value, delta) tuples."""
    cols = st.columns(len(metrics))
    for col, metric in zip(cols, metrics):
        col.metric(*metric)


def empty_state(message: str, kind: Literal["info", "warning"] = "info") -> None:
    """Standard 'nothing to show' banner that halts the rest of the page's script run."""
    (st.info if kind == "info" else st.warning)(message)
    st.stop()
