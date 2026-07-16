"""Bank of Japan policy inputs from the Japan MOF JGB yield CSV.

Japan's Ministry of Finance publishes daily JGB yields as a keyless CSV; we
take the latest row's short maturities as the curve. The BoJ has no clean
live policy-rate feed, so the anchor is supplied by the caller (a constant,
overridable in the sidebar). Column headers in constants.BOJ_YIELD_COLUMNS
are best-effort — correct them if the curve shows unavailable on deploy.

Returns partial/empty (never raises) on any failure; unreachable from the
build sandbox, so verified live only on deploy.
"""

from __future__ import annotations

import io

import pandas as pd
import requests

from .constants import BOJ_JGB_CSV_URL, BOJ_JGB_HEADER_ROW, BOJ_YIELD_COLUMNS

_REQUEST_TIMEOUT = 30
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
}


def _jgb_yields() -> dict[float, float]:
    """Latest-row short JGB yields keyed by maturity in years, or {} on failure."""
    try:
        resp = requests.get(BOJ_JGB_CSV_URL, headers=_HEADERS, timeout=_REQUEST_TIMEOUT)
        resp.raise_for_status()
        # The MOF file carries a metadata row before the real header.
        df = pd.read_csv(io.StringIO(resp.text), header=BOJ_JGB_HEADER_ROW)
    except (requests.RequestException, ValueError, pd.errors.ParserError):
        return {}

    if df.empty:
        return {}
    df.columns = [str(c).strip() for c in df.columns]
    latest = df.iloc[-1]
    out = {}
    for maturity_years, candidates in BOJ_YIELD_COLUMNS.items():
        for column in candidates:
            if column not in df.columns:
                continue
            value = pd.to_numeric(pd.Series([latest[column]]), errors="coerce").iloc[0]
            if pd.notna(value):
                out[maturity_years] = float(value)
                break
    return out


def fetch_boj_policy_inputs() -> dict:
    """{"yields": {maturity_years: rate}, "status": [...]}"""
    yields = _jgb_yields()
    status = ["Curve: MOF JGB" if yields else "Curve: unavailable (MOF JGB — check the CSV columns)"]
    return {"yields": yields, "status": status}
