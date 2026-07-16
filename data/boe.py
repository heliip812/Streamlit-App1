"""Bank of England policy inputs.

The BoE has no data API. The sterling OIS curve — the ideal market-implied
policy source — is published only as a daily Excel spreadsheet inside a ZIP on
the yield-curves page, so `_fetch_ois_curve` downloads that ZIP, finds the OIS
workbook and its spot-curve sheet, and reads the latest short-end yields.
Because the exact filenames/sheet layout can shift, the parse is deliberately
tolerant (it locates the maturity header relative to the first dated row
rather than assuming fixed positions). Bank Rate (the anchor) comes from the
keyless IADB CSV export.

Everything returns partial/empty (never raises) on failure; unreachable from
the build sandbox, so verified live only on deploy.
"""

from __future__ import annotations

import io
import zipfile
from datetime import date, datetime, timedelta

import pandas as pd
import requests

from .constants import BOE_BANK_RATE_CODE, BOE_IADB_URL, BOE_YIELD_CURVE_ZIP_URL

_REQUEST_TIMEOUT = 30
_ZIP_TIMEOUT = 60
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
}


def _fetch_iadb(codes: tuple[str, ...]) -> dict[str, float]:
    """Latest value of each IADB series code, keyed by code, or {} on failure."""
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
        if code in df.columns:
            values = pd.to_numeric(df[code], errors="coerce").dropna()
            if not values.empty:
                out[code] = float(values.iloc[-1])
    return out


def _pick_file(names: list[str], *musts: str) -> str | None:
    """First .xlsx whose (lowercased) name contains every substring in `musts`."""
    for name in names:
        low = name.lower()
        if low.endswith(".xlsx") and all(m in low for m in musts):
            return name
    return None


def _pick_spot_sheet(sheets: dict[str, pd.DataFrame]) -> pd.DataFrame | None:
    for want in ("spot curve", "spot", "curve"):
        for name, frame in sheets.items():
            if want in name.lower():
                return frame
    return None


def _extract_short_end(df: pd.DataFrame, targets=(0.5, 1.0, 2.0), tol: float = 0.06) -> dict[float, float]:
    """Pull the latest yields at the target maturities from a spot-curve sheet.

    The sheet is read with header=None: dated rows have a datetime in column 0,
    the maturity header is the nearest numeric row above the first dated row,
    and each column maps to a maturity (years). We take the last dated row and
    the columns closest to each target maturity.
    """
    data_rows = [i for i in range(len(df)) if isinstance(df.iloc[i, 0], datetime)]
    if not data_rows:
        return {}

    maturities: dict[int, float] = {}
    for i in range(data_rows[0] - 1, -1, -1):
        candidate: dict[int, float] = {}
        for j, value in enumerate(df.iloc[i]):
            try:
                years = float(value)
            except (TypeError, ValueError):
                continue
            if 0 < years <= 60:
                candidate[j] = years
        if len(candidate) >= 3:
            maturities = candidate
            break
    if not maturities:
        return {}

    last = df.iloc[data_rows[-1]]
    out: dict[float, float] = {}
    for target in targets:
        best_col, best_dist = None, tol
        for col, years in maturities.items():
            dist = abs(years - target)
            if dist <= best_dist:
                best_col, best_dist = col, dist
        if best_col is not None:
            value = pd.to_numeric(pd.Series([last[best_col]]), errors="coerce").iloc[0]
            if pd.notna(value):
                out[target] = float(value)
    return out


def _fetch_ois_curve() -> dict[float, float]:
    """Short-end sterling OIS yields from the BoE yield-curve ZIP, or {}."""
    try:
        resp = requests.get(BOE_YIELD_CURVE_ZIP_URL, headers=_HEADERS, timeout=_ZIP_TIMEOUT)
        resp.raise_for_status()
        archive = zipfile.ZipFile(io.BytesIO(resp.content))
    except (requests.RequestException, zipfile.BadZipFile, ValueError):
        return {}

    names = archive.namelist()
    # Prefer the OIS workbook; fall back to the nominal gilt (GLC) curve.
    filename = _pick_file(names, "ois", "daily") or _pick_file(names, "ois") or _pick_file(names, "glc", "nominal")
    if not filename:
        return {}
    try:
        sheets = pd.read_excel(io.BytesIO(archive.read(filename)), sheet_name=None, header=None)
    except (ValueError, KeyError, OSError, ImportError):
        return {}

    sheet = _pick_spot_sheet(sheets)
    return _extract_short_end(sheet) if sheet is not None else {}


def fetch_boe_policy_inputs() -> dict:
    """{"bank_rate": float | None, "yields": {maturity_years: rate}, "status": [...]}"""
    yields = _fetch_ois_curve()
    bank_rate = _fetch_iadb((BOE_BANK_RATE_CODE,)).get(BOE_BANK_RATE_CODE)
    status = [
        "Curve: BoE OIS spreadsheet" if yields else "Curve: unavailable (BoE OIS spreadsheet)",
        "Bank Rate: BoE IADB" if bank_rate is not None else "Bank Rate: unavailable — using the manual anchor",
    ]
    return {"bank_rate": bank_rate, "yields": yields, "status": status}
