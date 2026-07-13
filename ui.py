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


def _recent_business_days(n: int = 120) -> list[date]:
    """DTCC/CFTC only publish on business days, so weekends are never a
    meaningful 'as of' choice — a selectbox restricted to business days
    (newest first) rules them out entirely, rather than letting a user
    pick a Saturday and only discovering there's no data after the fact.
    Doesn't account for market holidays, just weekdays.
    """
    end = date.today() - timedelta(days=1)
    return list(pd.bdate_range(end=end, periods=n).date)[::-1]


def sidebar_date_and_lookback(
    cfg: RangeConfig, key_prefix: str, label: str = "Lookback window (days)"
) -> tuple[date, int]:
    """The 'as of date' + lookback slider pair every page shows in its sidebar."""
    with st.sidebar:
        as_of = st.selectbox(
            "As of date",
            options=_recent_business_days(),
            format_func=lambda d: d.strftime("%Y-%m-%d (%a)"),
            key=f"{key_prefix}_as_of",
        )
        lookback = st.slider(label, cfg.min_value, cfg.max_value, cfg.default, key=f"{key_prefix}_lookback")
    return as_of, lookback


def render(fig: go.Figure) -> None:
    """Apply the shared chart margin and render through Streamlit's theme."""
    fig.update_layout(margin=CHART_MARGIN)
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
