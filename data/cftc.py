"""Ingestion of CFTC Commitments of Traders data.

Free, public, unauthenticated Socrata API published weekly by the CFTC.
Two report types are supported, each with its own trader categories:

- "financial" — Traders in Financial Futures (rates, FX, equity index):
  Dealer, Asset Manager, Leveraged Funds, Other Reportables
- "commodities" — Disaggregated report (physical commodities): Producer/
  Merchant, Swap Dealer, Managed Money, Other Reportables

Reference: https://publicreporting.cftc.gov/stories/s/Commitments-of-Traders/r4w3-av2u/
"""

from __future__ import annotations

import pandas as pd
import requests

from .constants import CFTC_BASE_URL, CFTC_DISAGG_RESOURCE_ID, CFTC_TFF_RESOURCE_ID

_REQUEST_TIMEOUT = 30

# category -> (net-column name, substrings that must all appear, case-
# insensitive, in a column name for it to be that category's position
# field). Matched by substring rather than an exact hardcoded name because
# this report's schema can't be verified by a live test fetch from this
# environment (its host is blocked by this sandbox's own network policy,
# separate from any CFTC/DTCC issue) — substring matching is resilient to
# a minor naming detail being off (CFTC's own schema has at least one
# known inconsistency: a stray double underscore in one Disaggregated
# report column that was never fixed for backwards compatibility).
_REPORT_CATEGORIES: dict[str, list[tuple[str, str, tuple[str, ...]]]] = {
    "financial": [
        ("Dealer", "dealer_net", ("dealer", "positions")),
        ("Asset manager", "asset_mgr_net", ("asset_mgr", "positions")),
        ("Leveraged funds", "lev_money_net", ("lev_money", "positions")),
        ("Other reportables", "other_net", ("other_rept", "positions")),
    ],
    "commodities": [
        ("Producer/Merchant", "prod_merc_net", ("prod_merc", "positions")),
        ("Swap dealer", "swap_net", ("swap", "positions")),
        ("Managed money", "m_money_net", ("m_money", "positions")),
        ("Other reportables", "other_net", ("other_rept", "positions")),
    ],
}

_RESOURCE_IDS = {"financial": CFTC_TFF_RESOURCE_ID, "commodities": CFTC_DISAGG_RESOURCE_ID}


def category_columns(report: str) -> list[tuple[str, str]]:
    """(category label, net-position column) pairs for a report, in display order."""
    return [(category, net_col) for category, net_col, _ in _REPORT_CATEGORIES[report]]


def _find_column(columns: list[str], *substrings: str) -> str | None:
    for col in columns:
        lower = col.lower()
        if all(s in lower for s in substrings):
            return col
    return None


def fetch_positioning(contract_names: list[str], weeks: int = 26, report: str = "financial") -> pd.DataFrame:
    """Fetch recent positioning for a set of contracts.

    Returns an empty DataFrame (rather than raising) on any network or
    upstream failure, so a single flaky call doesn't take down the page —
    the caller is expected to show a friendly "data unavailable" state.
    """
    or_clause = " OR ".join(f"upper(market_and_exchange_names) like '%{name}%'" for name in contract_names)
    params = {
        "$where": or_clause,
        "$order": "report_date_as_yyyy_mm_dd DESC",
        "$limit": str(weeks * len(contract_names) * 2),
    }
    url = f"{CFTC_BASE_URL}/{_RESOURCE_IDS[report]}.json"

    try:
        resp = requests.get(url, params=params, timeout=_REQUEST_TIMEOUT)
        resp.raise_for_status()
        records = resp.json()
    except (requests.RequestException, ValueError):
        return pd.DataFrame()

    if not records:
        return pd.DataFrame()

    df = pd.DataFrame.from_records(records)
    columns = list(df.columns)

    for col in columns:
        if col not in ("report_date_as_yyyy_mm_dd", "market_and_exchange_names"):
            df[col] = pd.to_numeric(df[col], errors="coerce")

    df["report_date"] = pd.to_datetime(df["report_date_as_yyyy_mm_dd"], errors="coerce")
    if "open_interest_all" not in df.columns:
        df["open_interest_all"] = pd.NA

    for _category, net_col, substrings in _REPORT_CATEGORIES[report]:
        long_col = _find_column(columns, *substrings, "long")
        short_col = _find_column(columns, *substrings, "short")
        df[net_col] = df[long_col] - df[short_col] if long_col and short_col else pd.NA

    return df.sort_values("report_date")
