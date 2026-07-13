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

from . import cftc, dtcc
from .constants import DTCC_ASSET_CLASSES


# Streamlit's cache keeps every distinct call's result resident until its
# TTL expires or max_entries is exceeded — a user browsing through several
# pages (each with its own asset class/date/lookback combination) can
# otherwise accumulate multiple large frames simultaneously and push total
# memory past Streamlit Cloud's 1GB per-app limit even though any single
# page load is individually well within it. max_entries bounds that.
@st.cache_data(ttl=CACHE_TTL_SECONDS, max_entries=1, show_spinner="Fetching DTCC swap data repository trades...")
def get_dtcc_trades(asset_class_code: str, end_day: date, lookback_days: int) -> pd.DataFrame:
    return dtcc.get_recent_trades(asset_class_code, end_day, lookback_days)


@st.cache_data(ttl=CACHE_TTL_SECONDS, max_entries=2, show_spinner="Fetching CFTC positioning data...")
def get_cftc_positioning(contract_names: tuple[str, ...], weeks: int, report: str = "financial") -> pd.DataFrame:
    return cftc.fetch_positioning(list(contract_names), weeks, report)


@st.cache_data(ttl=CACHE_TTL_SECONDS, max_entries=1, show_spinner="Fetching cross-asset overview...")
def get_all_asset_classes(end_day: date, lookback_days: int) -> dict[str, pd.DataFrame]:
    # Deliberately sequential across asset classes (each asset class still
    # fetches its own days concurrently): running all five concurrently
    # stacks their peak memory on top of each other and was observed to
    # spike well past Streamlit Cloud's 1GB per-app limit.
    return {label: dtcc.get_recent_trades(code, end_day, lookback_days) for code, label in DTCC_ASSET_CLASSES.items()}
