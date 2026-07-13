"""Ingestion of CFTC Commitments of Traders (Traders in Financial Futures) data.

Free, public, unauthenticated Socrata API published weekly by the CFTC.
Reference: https://publicreporting.cftc.gov/stories/s/Commitments-of-Traders/r4w3-av2u/
"""

from __future__ import annotations

import pandas as pd
import requests

from .constants import CFTC_BASE_URL, CFTC_TFF_RESOURCE_ID

_REQUEST_TIMEOUT = 30

_SELECT = ",".join(
    [
        "report_date_as_yyyy_mm_dd",
        "market_and_exchange_names",
        "open_interest_all",
        "dealer_positions_long_all",
        "dealer_positions_short_all",
        "asset_mgr_positions_long",
        "asset_mgr_positions_short",
        "lev_money_positions_long",
        "lev_money_positions_short",
        "other_rept_positions_long",
        "other_rept_positions_short",
    ]
)


def fetch_positioning(contract_names: list[str], weeks: int = 26) -> pd.DataFrame:
    """Fetch recent TFF positioning for a set of contracts.

    Returns an empty DataFrame (rather than raising) on any network or
    upstream failure, so a single flaky call doesn't take down the page —
    the caller is expected to show a friendly "data unavailable" state.
    """
    or_clause = " OR ".join(f"upper(market_and_exchange_names) like '%{name}%'" for name in contract_names)
    params = {
        "$select": _SELECT,
        "$where": or_clause,
        "$order": "report_date_as_yyyy_mm_dd DESC",
        "$limit": str(weeks * len(contract_names) * 2),
    }
    url = f"{CFTC_BASE_URL}/{CFTC_TFF_RESOURCE_ID}.json"

    try:
        resp = requests.get(url, params=params, timeout=_REQUEST_TIMEOUT)
        resp.raise_for_status()
        records = resp.json()
    except (requests.RequestException, ValueError):
        return pd.DataFrame()

    if not records:
        return pd.DataFrame()

    df = pd.DataFrame.from_records(records)
    numeric_cols = [c for c in df.columns if c not in ("report_date_as_yyyy_mm_dd", "market_and_exchange_names")]
    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df["report_date"] = pd.to_datetime(df["report_date_as_yyyy_mm_dd"], errors="coerce")
    df["dealer_net"] = df["dealer_positions_long_all"] - df["dealer_positions_short_all"]
    df["asset_mgr_net"] = df["asset_mgr_positions_long"] - df["asset_mgr_positions_short"]
    df["lev_money_net"] = df["lev_money_positions_long"] - df["lev_money_positions_short"]
    df["other_net"] = df["other_rept_positions_long"] - df["other_rept_positions_short"]

    return df.sort_values("report_date")
