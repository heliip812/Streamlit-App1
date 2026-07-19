"""Macro inputs for the own-model, from FRED (free API key required).

Uses the official FRED API via fredapi — the supported, rate-limit-friendly
path (not the fredgraph scraping route). Every series is fetched defensively:
any failure yields a missing value so the Taylor model still runs (a missing
gap just contributes zero). Returns {core_infl_yoy, core_infl_3m,
unemployment, nfci} with whatever resolved.

US series (core PCE, UNRATE, NFCI) are solid; the euro-area/UK/Japan codes in
the registry are best-effort (headline CPI / OECD unemployment) and flagged in
the UI until verified.
"""

from __future__ import annotations


def _latest(fred, code):
    try:
        series = fred.get_series(code).dropna()
        return series if not series.empty else None
    except Exception:  # noqa: BLE001 — any FRED/network error → treat as missing
        return None


def fetch_macro(macro_series: dict, fred_key: str) -> dict:
    """Latest macro readings for a bank's model, or {} if FRED is unreachable."""
    if not fred_key or not macro_series:
        return {}
    try:
        from fredapi import Fred

        fred = Fred(api_key=fred_key)
    except Exception:  # noqa: BLE001 — bad key or import failure
        return {}

    out = {}
    inflation = _latest(fred, macro_series.get("core_inflation"))
    if inflation is not None and len(inflation) > 12:
        yoy = inflation.pct_change(12).dropna() * 100.0
        if not yoy.empty:
            out["core_infl_yoy"] = float(yoy.iloc[-1])
        ann3m = ((inflation / inflation.shift(3)) ** 4 - 1).dropna() * 100.0
        if not ann3m.empty:
            out["core_infl_3m"] = float(ann3m.iloc[-1])

    unemployment = _latest(fred, macro_series.get("unemployment"))
    if unemployment is not None:
        out["unemployment"] = float(unemployment.iloc[-1])

    nfci = _latest(fred, macro_series.get("nfci"))
    if nfci is not None:
        out["nfci"] = float(nfci.iloc[-1])

    return out
