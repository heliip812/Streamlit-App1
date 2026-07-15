"""Bank of England policy inputs from the IADB keyless CSV export.

Pulls Bank Rate (the anchor) and short gilt par yields (the curve) from the
BoE Interactive Database. Bank Rate's code is solid; the gilt-curve codes in
constants.BOE_YIELD_CODES are best-effort and the first thing to correct if
the curve shows unavailable on deploy. Returns partial/empty (never raises)
on any failure so the section degrades to a friendly state; unreachable from
the build sandbox, so verified live only on deploy.
"""

from __future__ import annotations

import io
from datetime import date, timedelta

import pandas as pd
import requests

from .constants import BOE_BANK_RATE_CODE, BOE_IADB_URL, BOE_YIELD_CODES

_REQUEST_TIMEOUT = 30
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
}


def _fetch_iadb(codes: tuple[str, ...]) -> dict[str, float]:
    """Latest value of each IADB series code, keyed by code, or {} on failure.

    The IADB CSV has a Date column plus one column per requested code; missing
    observations are blank, so we take each column's last non-null value.
    """
    if not codes:
        return {}
    today = date.today()
    params = {
        "csv.x": "yes",
        "Datefrom": (today - timedelta(days=30)).strftime("%d/%b/%Y"),
        "Dateto": today.strftime("%d/%b/%Y"),
        "SeriesCodes": ",".join(codes),
        "UsingCodes": "Y",
        "CSVF": "TN",
        "VPD": "Y",
        "VFD": "N",
    }
    try:
        resp = requests.get(BOE_IADB_URL, params=params, headers=_HEADERS, timeout=_REQUEST_TIMEOUT)
        resp.raise_for_status()
        df = pd.read_csv(io.StringIO(resp.text))
    except (requests.RequestException, ValueError, pd.errors.ParserError):
        return {}

    out = {}
    for code in codes:
        if code not in df.columns:
            continue
        values = pd.to_numeric(df[code], errors="coerce").dropna()
        if not values.empty:
            out[code] = float(values.iloc[-1])
    return out


def fetch_boe_policy_inputs() -> dict:
    """{"bank_rate": float | None, "yields": {maturity_years: rate}, "status": [...]}"""
    data = _fetch_iadb((BOE_BANK_RATE_CODE, *BOE_YIELD_CODES))
    yields = {maturity: data[code] for code, maturity in BOE_YIELD_CODES.items() if code in data}
    status = [
        "Curve: BoE IADB" if yields else "Curve: unavailable (BoE IADB — check series codes)",
        "Bank Rate: BoE IADB" if BOE_BANK_RATE_CODE in data else "Bank Rate: unavailable — using the manual anchor",
    ]
    return {"bank_rate": data.get(BOE_BANK_RATE_CODE), "yields": yields, "status": status}
