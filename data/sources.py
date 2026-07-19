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

from . import cb_calendar, cb_market, central_banks, cftc, dtcc, macro, s3_cache
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


# One cached entry per central bank in the registry. A failed fetch must NOT
# sit in this cache for the full TTL (that pinned a single bad FRED call as
# "unavailable" for an hour on the deployed app) — the page clears this cache
# whenever the returned curve is empty, so the next interaction retries.
@st.cache_data(ttl=CACHE_TTL_SECONDS, max_entries=8, show_spinner="Fetching policy-rate data...")
def get_policy_inputs(bank_code: str) -> central_banks.PolicyInputs:
    return central_banks.fetch_inputs(bank_code)


# Meeting calendars change a few times a year, so a day-long TTL is plenty and
# keeps the best-effort scrape off the critical path on most loads. As with
# get_policy_inputs, the page clears this on an empty (failed) scrape.
@st.cache_data(ttl=86400, max_entries=8, show_spinner=False)
def get_meeting_dates(calendar_code: str) -> list:
    fetcher = cb_calendar.FETCHERS.get(calendar_code)
    return fetcher() if fetcher else []


# Macro readings for the own-model, keyed by (bank, key). The key is part of
# the cache key so switching FRED keys re-fetches; a failed pull isn't cached
# long enough to matter (macro updates monthly anyway).
@st.cache_data(ttl=CACHE_TTL_SECONDS, max_entries=8, show_spinner="Fetching FRED macro data...")
def get_macro(bank_code: str, fred_key: str) -> dict:
    return macro.fetch_macro(central_banks.get_spec(bank_code).macro_series, fred_key)


# Raw quotes for the Methodology tab's implied engine. Fetched only when the
# user asks (they're slow — 14 Yahoo tickers), and cached briefly so a rerun
# doesn't refetch. The daily refresh job bypasses these (no Streamlit there).
@st.cache_data(ttl=900, max_entries=1, show_spinner="Fetching Fed Funds futures (Yahoo, ~15s)...")
def get_zq_futures(n_months: int = 14) -> pd.DataFrame:
    return cb_market.fetch_ff_futures_raw(n_months)


@st.cache_data(ttl=CACHE_TTL_SECONDS, max_entries=1, show_spinner="Fetching BoE OIS forward curve...")
def get_boe_forward_curve() -> pd.DataFrame:
    return cb_market.fetch_boe_ois_forward_raw()


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
