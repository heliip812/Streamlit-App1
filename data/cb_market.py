"""Raw market-data fetchers for the implied-path engine (STAGE 1).

Network only — no math (that lives in implied_engine.py) and no Streamlit
(cached wrappers live in data/sources.py; data/refresh.py calls these
directly so the CLI job runs without Streamlit). Everything degrades to an
empty/None result on failure, per the brief.

Known limitation carried through the UI: Yahoo ZQ quotes are delayed and can
be stale in deferred months — verify against CME settlements before acting.
"""

from __future__ import annotations

import io
import zipfile
from datetime import date

import pandas as pd
import requests

from .constants import BOE_YIELD_CURVE_ZIP_URL

MONTH_CODES = {1: "F", 2: "G", 3: "H", 4: "J", 5: "K", 6: "M", 7: "N", 8: "Q", 9: "U", 10: "V", 11: "X", 12: "Z"}

# Yahoo tickers for the FX overlay, keyed by this app's pair labels.
FX_TICKERS = {
    "EUR/USD": "EURUSD=X",
    "GBP/USD": "GBPUSD=X",
    "USD/JPY": "USDJPY=X",
    "EUR/GBP": "EURGBP=X",
    "EUR/JPY": "EURJPY=X",
    "GBP/JPY": "GBPJPY=X",
}

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
}


def zq_ticker(year: int, month: int) -> str:
    return f"ZQ{MONTH_CODES[month]}{str(year)[-2:]}.CBT"


def fetch_ff_futures_raw(n_months: int = 14) -> pd.DataFrame:
    """STAGE 1 (Fed): raw ZQ settlement-ish closes from Yahoo Finance."""
    try:
        import yfinance as yf
    except Exception:
        return pd.DataFrame()

    today = date.today()
    rows, y, m = [], today.year, today.month
    for _ in range(n_months):
        tkr = zq_ticker(y, m)
        try:
            h = yf.Ticker(tkr).history(period="5d")
            if len(h):
                rows.append(
                    {
                        "contract_month": f"{y}-{m:02d}", "ticker": tkr,
                        "raw_price": round(float(h["Close"].iloc[-1]), 4),
                        "quote_date": str(h.index[-1].date()),
                    }
                )
        except Exception:
            pass
        m += 1
        if m > 12:
            m, y = 1, y + 1
    return pd.DataFrame(rows)


def fetch_boe_ois_forward_raw() -> pd.DataFrame:
    """STAGE 1 (BoE): the daily OIS instantaneous-forward curve from the
    Bank's latest-yield-curve zip (columns: horizon_years, fwd_rate)."""
    try:
        r = requests.get(BOE_YIELD_CURVE_ZIP_URL, headers=_HEADERS, timeout=60)
        r.raise_for_status()
        zf = zipfile.ZipFile(io.BytesIO(r.content))
        name = next(n for n in zf.namelist() if "ois" in n.lower() and n.lower().endswith((".xlsx", ".xls")))
        xl = pd.ExcelFile(zf.open(name))
        sheet = next(s for s in xl.sheet_names if "fwd" in s.lower() or "forward" in s.lower())
        df = xl.parse(sheet, header=3).dropna(how="all").reset_index(drop=True)
        tenors = pd.to_numeric(df.iloc[0, 1:], errors="coerce")
        last = df.iloc[-1]
        rates = pd.to_numeric(last[1:], errors="coerce")
        out = pd.DataFrame({"horizon_years": tenors.values, "fwd_rate": rates.values, "curve_date": [last.iloc[0]] * len(rates)})
        return out.dropna(subset=["horizon_years", "fwd_rate"])
    except Exception:
        return pd.DataFrame()


def fetch_fx_spots(pairs: list[str] | None = None) -> dict[str, float]:
    """Latest FX spots per pair label (via Yahoo), for the signals overlay."""
    try:
        import yfinance as yf
    except Exception:
        return {}
    out = {}
    for pair in pairs or list(FX_TICKERS):
        tkr = FX_TICKERS.get(pair)
        if not tkr:
            continue
        try:
            h = yf.Ticker(tkr).history(period="2d")
            if len(h):
                out[pair] = float(h["Close"].iloc[-1])
        except Exception:
            pass
    return out
