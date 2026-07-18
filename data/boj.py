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


def _row_curve(row, columns: list[str]) -> dict[float, float]:
    curve = {}
    for maturity_years, candidates in BOJ_YIELD_COLUMNS.items():
        for column in candidates:
            if column in columns:
                value = pd.to_numeric(pd.Series([row[column]]), errors="coerce").iloc[0]
                if pd.notna(value):
                    curve[maturity_years] = float(value)
                    break
    return curve


def _jgb_history(recent: int = 150) -> dict:
    """Recent short JGB curves keyed by date: {date: {maturity: yield}}, or {}.

    The all-history MOF file goes back to 1974; we keep only the last `recent`
    rows so the page can compare today's path against a prior date's without
    carrying decades of data.
    """
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
    columns = list(df.columns)
    date_col = columns[0]
    df = df.tail(recent).copy()
    df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
    df = df.dropna(subset=[date_col])

    history = {}
    for _, row in df.iterrows():
        curve = _row_curve(row, columns)
        if curve:
            history[row[date_col].date()] = curve
    return history


def fetch_boj_policy_inputs() -> dict:
    """{"yields": {maturity_years: rate}, "history": {date: curve}, "status": [...]}"""
    history = _jgb_history()
    yields = history[max(history)] if history else {}
    status = ["Curve: MOF JGB" if yields else "Curve: unavailable (MOF JGB — check the CSV columns)"]
    return {"yields": yields, "history": history, "status": status}
