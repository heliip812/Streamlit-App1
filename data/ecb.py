"""Ingestion of ECB Data Portal series (the euro-area counterpart to FRED).

The ECB Data Portal is free, keyless, and built for programmatic access. Each
series is one small CSV request; we fetch each maturity/rate separately so the
value maps unambiguously to its key, and normalise everything into a plain
dict the Fed-path math (fed_path.py) can consume directly.

Like every external host it's unreachable from the build sandbox's allowlist
proxy, so this is exercised by mocked unit tests and verified live on deploy.
Returns partial/empty results (never raises) on any failure, so the ECB
section degrades to a friendly empty state.
"""

from __future__ import annotations

import io

import pandas as pd
import requests

from .constants import (
    ECB_DATA_URL,
    ECB_DFR_KEY,
    ECB_ESTR_KEY,
    ECB_MRO_KEY,
    ECB_YIELD_KEYS,
)

_REQUEST_TIMEOUT = 30


def _fetch_latest_value(dataflow_key: str) -> float | None:
    """Latest observation of one ECB series, or None on any failure.

    `dataflow_key` is "{DATAFLOW}/{KEY}" (e.g. "FM/B.U2.EUR.4F.KR.DFR.LEV").
    The csvdata response carries a TIME_PERIOD/OBS_VALUE pair per row; we take
    the last non-missing OBS_VALUE.
    """
    url = f"{ECB_DATA_URL}/{dataflow_key}"
    try:
        resp = requests.get(
            url,
            params={"lastNObservations": "1", "format": "csvdata"},
            timeout=_REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        df = pd.read_csv(io.StringIO(resp.text))
    except (requests.RequestException, ValueError, pd.errors.ParserError):
        return None

    if "OBS_VALUE" not in df.columns:
        return None
    values = pd.to_numeric(df["OBS_VALUE"], errors="coerce").dropna()
    return float(values.iloc[-1]) if not values.empty else None


def fetch_ecb_policy_inputs() -> dict:
    """Normalised ECB inputs for the implied-path section.

    Returns {"estr", "dfr", "mro": float | None, "yields": {maturity_years:
    rate}}. Any series the portal doesn't return is None (or omitted from
    `yields`); an empty `yields` dict means the curve is unavailable and the
    caller should show an empty state.
    """
    yields = {}
    for maturity_years, key in ECB_YIELD_KEYS.items():
        value = _fetch_latest_value(key)
        if value is not None:
            yields[maturity_years] = value

    return {
        "estr": _fetch_latest_value(ECB_ESTR_KEY),
        "dfr": _fetch_latest_value(ECB_DFR_KEY),
        "mro": _fetch_latest_value(ECB_MRO_KEY),
        "yields": yields,
    }
