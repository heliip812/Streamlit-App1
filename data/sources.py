"""Cached facade over the raw data-source modules.

Every page should call through here rather than importing dtcc/cftc
directly — this is the single seam where caching lives today, and where a
future paid feed (Markit, ICE Data, Bloomberg) would plug in alongside the
free ones behind the same function signatures.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date

import pandas as pd
import streamlit as st

from . import cftc, dtcc
from .constants import DTCC_ASSET_CLASSES


@st.cache_data(ttl=3600, show_spinner="Fetching DTCC swap data repository trades...")
def get_dtcc_trades(asset_class_code: str, end_day: date, lookback_days: int) -> pd.DataFrame:
    return dtcc.get_recent_trades(asset_class_code, end_day, lookback_days)


@st.cache_data(ttl=3600, show_spinner="Fetching CFTC positioning data...")
def get_cftc_positioning(contract_names: tuple[str, ...], weeks: int) -> pd.DataFrame:
    return cftc.fetch_positioning(list(contract_names), weeks)


@st.cache_data(ttl=3600, show_spinner="Fetching cross-asset overview...")
def get_all_asset_classes(end_day: date, lookback_days: int) -> dict[str, pd.DataFrame]:
    codes = list(DTCC_ASSET_CLASSES.items())
    with ThreadPoolExecutor(max_workers=len(codes)) as pool:
        results = pool.map(lambda item: dtcc.get_recent_trades(item[0], end_day, lookback_days), codes)
    return {label: df for (_, label), df in zip(codes, results)}
