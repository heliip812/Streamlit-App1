"""US policy-rate inputs with independent fallbacks.

Composes the raw inputs the Fed policy-path section needs — the overnight
anchor (EFFR), the target range, and the short-end Treasury curve — from
FRED first, falling back per-piece to official keyless government APIs that
don't sit behind FRED's WAF:

- Curve: Treasury.gov's own daily par yield curve CSV
- EFFR: NY Fed's markets API

Each piece degrades independently (a FRED outage doesn't lose the curve if
Treasury.gov is up), and the returned `status` lines say exactly which source
supplied each piece so the page can surface why something is missing instead
of a generic "unavailable". Returns a plain dict; data/central_banks.py
adapts it into the registry's PolicyInputs shape.
"""

from __future__ import annotations

import io
from datetime import date

import pandas as pd
import requests

from . import fred
from .constants import (
    FRED_EFFR_SERIES,
    FRED_TARGET_LOWER_SERIES,
    FRED_TARGET_UPPER_SERIES,
    FRED_YIELD_SERIES,
    NYFED_EFFR_URL,
    TREASURY_YIELD_CSV_URL,
)

_REQUEST_TIMEOUT = 30
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
}

# Treasury.gov CSV column -> maturity in years, matching FRED_YIELD_SERIES's
# coverage so either source produces the same curve shape.
_TREASURY_COLUMNS = {"1 Mo": 1 / 12, "3 Mo": 0.25, "6 Mo": 0.5, "1 Yr": 1.0, "2 Yr": 2.0}


def _nyfed_effr() -> float | None:
    """Latest EFFR from the NY Fed markets API, or None on any failure."""
    try:
        resp = requests.get(NYFED_EFFR_URL, headers=_HEADERS, timeout=_REQUEST_TIMEOUT)
        resp.raise_for_status()
        rates = resp.json().get("refRates") or []
        value = rates[0].get("percentRate") if rates else None
        return float(value) if value is not None else None
    except (requests.RequestException, ValueError, KeyError, IndexError, TypeError):
        return None


def _treasury_yields() -> dict[float, float]:
    """Latest short-end par yields from Treasury.gov's daily CSV, or {}."""
    url = TREASURY_YIELD_CSV_URL.format(year=date.today().year)
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=_REQUEST_TIMEOUT)
        resp.raise_for_status()
        df = pd.read_csv(io.StringIO(resp.text))
    except (requests.RequestException, ValueError, pd.errors.ParserError):
        return {}

    if "Date" not in df.columns:
        return {}
    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
    df = df.dropna(subset=["Date"]).sort_values("Date")
    if df.empty:
        return {}

    latest = df.iloc[-1]
    out = {}
    for column, maturity_years in _TREASURY_COLUMNS.items():
        if column not in df.columns:
            continue
        value = pd.to_numeric(pd.Series([latest[column]]), errors="coerce").iloc[0]
        if pd.notna(value):
            out[maturity_years] = float(value)
    return out


def fetch_policy_inputs() -> dict:
    """US inputs: {"anchor", "target_range", "yields", "status"}.

    anchor: EFFR (float | None); target_range: (lower, upper) | None;
    yields: {maturity_years: rate}; status: human-readable per-piece source
    lines for the page's diagnostic caption.
    """
    fred_series = (FRED_EFFR_SERIES, FRED_TARGET_UPPER_SERIES, FRED_TARGET_LOWER_SERIES) + tuple(FRED_YIELD_SERIES)
    fred_data = fred.fetch_fred_latest(fred_series)
    status = []

    yields = {FRED_YIELD_SERIES[sid]: fred_data[sid] for sid in FRED_YIELD_SERIES if sid in fred_data}
    if yields:
        status.append("Curve: FRED")
    else:
        yields = _treasury_yields()
        status.append("Curve: Treasury.gov (FRED unavailable)" if yields else "Curve: unavailable (FRED and Treasury.gov both failed)")

    anchor = fred_data.get(FRED_EFFR_SERIES)
    if anchor is not None:
        status.append("EFFR: FRED")
    else:
        anchor = _nyfed_effr()
        status.append("EFFR: NY Fed (FRED unavailable)" if anchor is not None else "EFFR: unavailable — using the manual anchor")

    target_range = None
    if FRED_TARGET_LOWER_SERIES in fred_data and FRED_TARGET_UPPER_SERIES in fred_data:
        target_range = (fred_data[FRED_TARGET_LOWER_SERIES], fred_data[FRED_TARGET_UPPER_SERIES])

    return {"anchor": anchor, "target_range": target_range, "yields": yields, "status": status}
