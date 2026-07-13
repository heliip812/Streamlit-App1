"""Cleaning and enrichment of raw DTCC trade rows into analysis-ready columns.

Split out from client.py: this operates purely on an in-memory DataFrame
with DTCC's original column names, so it has no knowledge of HTTP, zip
files, or S3 — any future source that hands over a same-shaped raw frame
could reuse this directly.
"""

from __future__ import annotations

from datetime import date

import pandas as pd

from ..constants import CDS_INDEX_PATTERNS, NEW_TRADE_ACTION_TYPES
from .client import fetch_recent

# DTCC represents an undisclosed/masked notional with a sentinel value
# (typically 99,999,999,999,999,999,999.99999) rather than a real trade
# size. Real swap notionals never approach this, so treat anything at or
# above the threshold as "not disclosed" rather than a literal number.
_MASKED_NOTIONAL_THRESHOLD = 1e14


def _to_numeric(series: pd.Series | None) -> pd.Series:
    """DTCC comma-formats large numeric fields (Price, Exchange rate, and
    occasionally Spread) — e.g. "16,097.59" — which pd.to_numeric silently
    turns into NaN instead of erroring, so this must run before it rather
    than being an obviously-missing step.
    """
    if series is None:
        return pd.Series(dtype=float)
    cleaned = series.astype(str).str.replace(",", "", regex=False)
    return pd.to_numeric(cleaned, errors="coerce")


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
    out["tenor_days"] = (out["expiration_date"] - out["effective_date"]).dt.days
    out["tenor_years"] = out["tenor_days"] / 365.25

    rate = _to_numeric(out.get("Fixed rate-Leg 1"))
    spread = _to_numeric(out.get("Spread-Leg 1"))
    price = _to_numeric(out.get("Price"))
    # FX forwards/swaps don't populate rate/spread/price — the executed
    # level is "Exchange rate" instead.
    exchange_rate = _to_numeric(out.get("Exchange rate"))
    out["level"] = rate.fillna(spread).fillna(price).fillna(exchange_rate)

    underlier = out.get("UPI Underlier Name", pd.Series(dtype=object)).astype(str).str.upper()
    out["is_index"] = underlier.str.contains("|".join(CDS_INDEX_PATTERNS), na=False)

    return out


def get_recent_trades(asset_class_code: str, end_day: date, lookback_days: int) -> pd.DataFrame:
    """Fetch + normalize in one call. This is the seam other data sources plug into."""
    raw = fetch_recent(asset_class_code, end_day, lookback_days)
    return normalize(raw)
