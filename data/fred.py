"""Ingestion of FRED (Federal Reserve Economic Data) series.

FRED's `fredgraph.csv` endpoint is free, keyless, and built for programmatic
access — it doesn't bot-block the way CME's quotes endpoint does, which makes
it the stable source behind the Fed-path section. One request pulls every
series we need (effective fed funds rate, target-range bounds, short-end
Treasury yields) as columns; we keep only the latest observation of each.

Like data/cftc.py this returns an empty result (never raises) on any network
or parsing failure, and — as with every external host — it's unreachable from
the build sandbox's allowlist proxy, so it's exercised by mocked unit tests
and verified live only once deployed.
"""

from __future__ import annotations

import io
from datetime import date, timedelta

import pandas as pd
import requests

from .constants import FRED_CSV_URL

_REQUEST_TIMEOUT = 30
# fredgraph.csv sits behind the FRED website's WAF, which can challenge
# clients that don't look like a browser — the default python-requests agent
# is exactly what it screens for. A browser UA plus one immediate retry gets
# past transient challenges; persistent failures fall through to the
# independent Treasury.gov / NY Fed fallbacks in us_rates.py.
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
}


def fetch_fred_latest(series_ids: tuple[str, ...], lookback_days: int = 21) -> dict[str, float]:
    """Latest available value of each FRED series, keyed by series id.

    Series with no recent observation (FRED prints "." for missing days) or
    that FRED doesn't return are simply omitted from the result, so callers
    should treat a missing key as "unavailable" rather than assuming every id
    is present. `lookback_days` bounds the CSV to recent rows so the latest
    non-missing value is cheap to find.
    """
    if not series_ids:
        return {}

    params = {
        "id": ",".join(series_ids),
        "cosd": (date.today() - timedelta(days=lookback_days)).isoformat(),
    }
    df = None
    for attempt in (0, 1):
        try:
            resp = requests.get(FRED_CSV_URL, params=params, headers=_HEADERS, timeout=_REQUEST_TIMEOUT)
            resp.raise_for_status()
            df = pd.read_csv(io.StringIO(resp.text))
            break
        except (requests.RequestException, ValueError, pd.errors.ParserError):
            if attempt == 1:
                return {}

    latest: dict[str, float] = {}
    for series_id in series_ids:
        if series_id not in df.columns:
            continue
        values = pd.to_numeric(df[series_id], errors="coerce").dropna()
        if not values.empty:
            latest[series_id] = float(values.iloc[-1])
    return latest
