"""Ingestion of CME 30-Day Fed Funds futures ("ZQ") delayed quotes.

Feeds the market-implied Fed policy path (see fed_path.py). Returns a tidy
frame of one row per contract month with its settlement price; everything
downstream works off that, so the exact upstream shape is contained here.

Like data/cftc.py this returns an empty DataFrame (never raises) on any
network or parsing failure, so a flaky feed shows a friendly empty state
instead of a stack trace — and, as with CFTC, the CME host is unreachable
from the build sandbox, so this is exercised by mocked unit tests and
verified live only once deployed.

CME's quotes endpoint returns JSON shaped roughly:

    {"quotes": [
        {"expirationDate": "20260130", "priorSettle": "95.705", "last": "95.71", ...},
        ...
    ]}

Only the expiration month and a settlement price are used; `priorSettle` is
preferred over `last` because the last-trade field is often blank outside
trading hours on a delayed feed.
"""

from __future__ import annotations

import pandas as pd
import requests

from .constants import CME_QUOTES_URL

_REQUEST_TIMEOUT = 30
# A browser-ish UA: CME's public endpoint tends to reject the default
# python-requests agent. Harmless if it turns out to be unnecessary.
_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; DerivativesMonitor/1.0)"}


def _to_price(quote: dict) -> float | None:
    for field in ("priorSettle", "last", "settlementPrice"):
        raw = quote.get(field)
        if raw in (None, "", "-", "0"):
            continue
        try:
            return float(str(raw).replace(",", ""))
        except ValueError:
            continue
    return None


def _to_month(quote: dict) -> pd.Timestamp | None:
    raw = quote.get("expirationDate") or quote.get("expirationMonth")
    if not raw:
        return None
    parsed = pd.to_datetime(str(raw), errors="coerce")
    if pd.isna(parsed):
        return None
    return parsed.normalize().replace(day=1)


def fetch_fed_funds_futures() -> pd.DataFrame:
    """Fetch the current 30-Day Fed Funds futures strip.

    Returns a DataFrame with `contract_month` (first of month) and `price`
    (settlement, in 100 − rate terms), one row per contract, front-to-back —
    or an empty DataFrame on any failure.
    """
    try:
        resp = requests.get(CME_QUOTES_URL, headers=_HEADERS, timeout=_REQUEST_TIMEOUT)
        resp.raise_for_status()
        payload = resp.json()
    except (requests.RequestException, ValueError):
        return pd.DataFrame(columns=["contract_month", "price"])

    quotes = payload.get("quotes") if isinstance(payload, dict) else None
    if not quotes:
        return pd.DataFrame(columns=["contract_month", "price"])

    rows = []
    for quote in quotes:
        month = _to_month(quote)
        price = _to_price(quote)
        if month is not None and price is not None:
            rows.append({"contract_month": month, "price": price})

    if not rows:
        return pd.DataFrame(columns=["contract_month", "price"])

    df = pd.DataFrame(rows).drop_duplicates(subset="contract_month")
    return df.sort_values("contract_month").reset_index(drop=True)
