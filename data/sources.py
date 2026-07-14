"""Cached facade over the raw data-source modules.

Every page should call through here rather than importing dtcc/cftc
directly — this is the single seam where caching lives today, and where a
future paid feed (Markit, ICE Data, Bloomberg) would plug in alongside the
free ones behind the same function signatures.
"""

from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

from config import CACHE_TTL_SECONDS

from . import cftc, dtcc, fred, s3_cache
from .constants import DTCC_ASSET_CLASSES


# Streamlit's cache keeps every distinct call's result resident until its
# TTL expires or max_entries is exceeded — a user browsing through several
# pages (each with its own asset class/date/lookback combination) can
# otherwise accumulate multiple large frames simultaneously and push total
# memory past Streamlit Cloud's 1GB per-app limit even though any single
# page load is individually well within it. max_entries bounds that.
@st.cache_data(ttl=CACHE_TTL_SECONDS, max_entries=1, show_spinner="Fetching DTCC swap data repository trades...")
def get_dtcc_trades(asset_class_code: str, start_day: date, end_day: date) -> pd.DataFrame:
    return dtcc.get_recent_trades(asset_class_code, start_day, end_day)


@st.cache_data(ttl=CACHE_TTL_SECONDS, max_entries=2, show_spinner="Fetching CFTC positioning data...")
def get_cftc_positioning(contract_names: tuple[str, ...], weeks: int, report: str = "financial") -> pd.DataFrame:
    return cftc.fetch_positioning(list(contract_names), weeks, report)


@st.cache_data(ttl=CACHE_TTL_SECONDS, max_entries=1, show_spinner="Fetching FRED rates data...")
def get_fred_rates(series_ids: tuple[str, ...]) -> dict[str, float]:
    return fred.fetch_fred_latest(series_ids)


@st.cache_data(ttl=CACHE_TTL_SECONDS, max_entries=1, show_spinner="Fetching cross-asset overview...")
def get_all_asset_classes(start_day: date, end_day: date) -> dict[str, pd.DataFrame]:
    # Deliberately sequential across asset classes: running all five
    # concurrently stacks their peak memory on top of each other and was
    # observed to spike well past Streamlit Cloud's 1GB per-app limit.
    return {label: dtcc.get_recent_trades(code, start_day, end_day) for code, label in DTCC_ASSET_CLASSES.items()}


@st.cache_data(ttl=300, show_spinner=False)
def get_s3_cache_status() -> tuple[bool, str]:
    """Cached briefly (5 min, not the usual hour) since this does a real S3
    round-trip — long enough to avoid re-checking on every widget
    interaction, short enough to notice if a bucket/permission issue gets
    fixed without waiting for the app to restart.
    """
    return s3_cache.health_check()
