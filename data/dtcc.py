"""Ingestion of DTCC Swap Data Repository (SDR) public dissemination data.

DTCC publishes real, trade-level OTC derivatives data free of charge under
Dodd-Frank Part 43/45 reporting rules: one cumulative CSV (zipped) per asset
class per calendar day, containing every publicly disseminated swap trade
(price/rate, notional, counterparty-anonymized) for that day.

Reference: https://www.dtcc.com/public-reporting
"""

from __future__ import annotations

import io
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

import pandas as pd
import requests

from .constants import CDS_INDEX_PATTERNS, DTCC_BASE_URL, NEW_TRADE_ACTION_TYPES

_COLUMNS = [
    "Action type",
    "Asset Class",
    "Execution Timestamp",
    "Effective Date",
    "Expiration Date",
    "Cleared",
    "Block trade election indicator",
    "Notional amount-Leg 1",
    "Notional amount-Leg 2",
    "Notional currency-Leg 1",
    "Notional currency-Leg 2",
    "Fixed rate-Leg 1",
    "Spread-Leg 1",
    "Price",
    "UPI Underlier Name",
]

_REQUEST_TIMEOUT = 30


def _slice_url(asset_class_code: str, day: date) -> str:
    return f"{DTCC_BASE_URL}/CFTC_CUMULATIVE_{asset_class_code}_{day:%Y_%m_%d}.zip"


def fetch_day(asset_class_code: str, day: date) -> pd.DataFrame:
    """Fetch and lightly parse one asset class's cumulative slice for one day.

    Returns an empty DataFrame (not an error) for weekends/holidays or any
    day DTCC has not published a file for, since that's an expected gap
    rather than a failure.
    """
    url = _slice_url(asset_class_code, day)
    try:
        resp = requests.get(url, timeout=_REQUEST_TIMEOUT)
    except requests.RequestException:
        return pd.DataFrame(columns=_COLUMNS)

    if resp.status_code != 200 or not resp.content:
        return pd.DataFrame(columns=_COLUMNS)

    try:
        with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
            csv_name = next(n for n in zf.namelist() if n.lower().endswith(".csv"))
            with zf.open(csv_name) as f:
                df = pd.read_csv(f, usecols=lambda c: c in _COLUMNS, low_memory=False)
    except (zipfile.BadZipFile, StopIteration, ValueError):
        return pd.DataFrame(columns=_COLUMNS)

    df["_trade_date"] = day
    return df


def fetch_recent(asset_class_code: str, end_day: date, lookback_days: int) -> pd.DataFrame:
    """Fetch and concatenate several days of a slice, skipping missing days.

    Days are fetched concurrently — this is pure I/O wait on independent
    HTTP requests, and lookback windows of a week or more make the naive
    serial version too slow for a good first-load experience.
    """
    days = [end_day - timedelta(days=i) for i in range(lookback_days)]
    with ThreadPoolExecutor(max_workers=min(8, len(days))) as pool:
        results = pool.map(lambda day: fetch_day(asset_class_code, day), days)
    frames = [df for df in results if not df.empty]
    if not frames:
        return pd.DataFrame(columns=_COLUMNS + ["_trade_date"])
    return pd.concat(frames, ignore_index=True)


# DTCC represents an undisclosed/masked notional with a sentinel value
# (typically 99,999,999,999,999,999,999.99999) rather than a real trade
# size. Real swap notionals never approach this, so treat anything at or
# above the threshold as "not disclosed" rather than a literal number.
_MASKED_NOTIONAL_THRESHOLD = 1e14


def _clean_notional(series: pd.Series) -> pd.Series:
    """DTCC caps very large notionals with a trailing '+' and formats with commas."""
    cleaned = (
        series.astype(str)
        .str.replace(",", "", regex=False)
        .str.replace("+", "", regex=False)
    )
    values = pd.to_numeric(cleaned, errors="coerce")
    return values.where(values < _MASKED_NOTIONAL_THRESHOLD)


def normalize(df: pd.DataFrame) -> pd.DataFrame:
    """Turn a raw DTCC slice into a tidy frame with derived analytics columns.

    Notional is reported per-leg in that leg's own currency, and for
    cross-currency instruments (FX swaps/forwards especially) leg 1 and
    leg 2 can be in wildly different-valued currencies (e.g. IDR vs USD,
    a ~18,000x face-value gap). Summing "Notional amount-Leg 1" across
    trades regardless of currency — as if it were all USD — silently
    inflates totals by orders of magnitude. ``notional_usd_approx`` is
    therefore only populated when one of the two legs is actually
    USD-denominated (using that leg's reported amount directly, with no
    synthetic FX conversion); otherwise it's left NaN and excluded from
    USD aggregates. ``notional_local`` keeps leg 1's raw amount in its own
    currency, for same-currency breakdowns only.
    """
    if df.empty:
        return df

    out = df.copy()
    raw_notional_1 = out.get("Notional amount-Leg 1", pd.Series(dtype=object))
    raw_notional_2 = out.get("Notional amount-Leg 2", pd.Series(dtype=object))
    notional_1 = _clean_notional(raw_notional_1)
    notional_2 = _clean_notional(raw_notional_2)
    ccy_1 = out.get("Notional currency-Leg 1", pd.Series(dtype=object))
    ccy_2 = out.get("Notional currency-Leg 2", pd.Series(dtype=object))

    out["notional_local"] = notional_1
    out["notional_usd_approx"] = notional_1.where(ccy_1 == "USD", notional_2.where(ccy_2 == "USD"))
    out["is_new_trade"] = out["Action type"].isin(NEW_TRADE_ACTION_TYPES)
    out["is_capped_notional"] = raw_notional_1.astype(str).str.contains(r"\+", regex=True)
    out["is_notional_masked"] = notional_1.isna() & raw_notional_1.notna()

    out["execution_ts"] = pd.to_datetime(out["Execution Timestamp"], errors="coerce", utc=True)
    out["effective_date"] = pd.to_datetime(out["Effective Date"], errors="coerce")
    out["expiration_date"] = pd.to_datetime(out["Expiration Date"], errors="coerce")
    out["tenor_years"] = (out["expiration_date"] - out["effective_date"]).dt.days / 365.25

    rate = pd.to_numeric(out.get("Fixed rate-Leg 1"), errors="coerce")
    spread = pd.to_numeric(out.get("Spread-Leg 1"), errors="coerce")
    price = pd.to_numeric(out.get("Price"), errors="coerce")
    out["level"] = rate.fillna(spread).fillna(price)

    underlier = out.get("UPI Underlier Name", pd.Series(dtype=object)).astype(str).str.upper()
    out["is_index"] = underlier.str.contains("|".join(CDS_INDEX_PATTERNS), na=False)

    return out


def get_recent_trades(asset_class_code: str, end_day: date, lookback_days: int) -> pd.DataFrame:
    """Fetch + normalize in one call. This is the seam other data sources plug into."""
    raw = fetch_recent(asset_class_code, end_day, lookback_days)
    return normalize(raw)
