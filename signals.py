"""Trading signals from the model-vs-market divergence.

Convention: divergence = model_rate − market_implied_rate (bp) at a meeting.
Positive means the model is more hawkish than the market prices. Pure functions
(no Streamlit/network) so the logic is unit-tested; the page supplies the two
paths and the per-bank divergences.

- Outright: model more hawkish → market underprices hikes / overprices cuts →
  pay fixed / short futures. Dovish → receive. |div| ≥ strong → high conviction.
- Spread: the difference of two banks' divergences → widener / tightener.
- FX: relative hawkish repricing supports that currency → long the hawkish leg.
"""

from __future__ import annotations

import math

import pandas as pd

from config import FX_PAIRS, SIGNAL_STRONG_BP, SIGNAL_THRESHOLD_BP

_CURRENCY = {"fed": "USD", "ecb": "EUR", "boe": "GBP", "boj": "JPY"}


def _nan(x) -> bool:
    return x is None or (isinstance(x, float) and math.isnan(x))


def merge_paths(market: pd.DataFrame, model: pd.DataFrame) -> pd.DataFrame:
    """Join a market path (meeting, implied_rate) and model path (meeting,
    model_rate) on meeting date and add the bp divergence."""
    merged = pd.merge(market, model, on="meeting", how="inner")
    merged["divergence_bp"] = (merged["model_rate"] - merged["implied_rate"]) * 100.0
    return merged


def outright_signal(merged: pd.DataFrame, horizon_meetings: int = 3) -> dict:
    """Mean divergence over the next `horizon_meetings` → an outright call."""
    if merged.empty:
        return {"signal": "NO DATA", "divergence_bp": float("nan"), "conviction": 0}
    div = float(merged.head(horizon_meetings)["divergence_bp"].mean())
    if abs(div) < SIGNAL_THRESHOLD_BP:
        return {"signal": "NEUTRAL", "divergence_bp": round(div, 1), "conviction": 0}
    if div > 0:
        signal = "Pay rates / short futures (market too dovish vs model)"
    else:
        signal = "Receive rates / long futures (market too hawkish vs model)"
    conviction = 2 if abs(div) > SIGNAL_STRONG_BP else 1
    return {"signal": signal, "divergence_bp": round(div, 1), "conviction": conviction}


def spread_signal(bank_a: str, div_a: float, bank_b: str, div_b: float) -> dict:
    """Relative divergence between two banks → widener / tightener."""
    if _nan(div_a) or _nan(div_b):
        return {"pair": f"{bank_a.upper()}/{bank_b.upper()}", "signal": "NO DATA", "rel_divergence_bp": float("nan"), "conviction": 0}
    rel = div_a - div_b
    pair = f"{bank_a.upper()}/{bank_b.upper()}"
    if abs(rel) < SIGNAL_THRESHOLD_BP:
        return {"pair": pair, "signal": "NEUTRAL", "rel_divergence_bp": round(rel, 1), "conviction": 0}
    if rel > 0:
        signal = f"Pay {bank_a.upper()} vs receive {bank_b.upper()} (widener)"
    else:
        signal = f"Receive {bank_a.upper()} vs pay {bank_b.upper()} (tightener)"
    return {"pair": pair, "signal": signal, "rel_divergence_bp": round(rel, 1), "conviction": 2 if abs(rel) > SIGNAL_STRONG_BP else 1}


def fx_signal(bank_a: str, div_a: float, bank_b: str, div_b: float) -> dict:
    """Relative hawkish repricing → long the hawkish currency."""
    pair = FX_PAIRS.get(frozenset({bank_a, bank_b}), f"{bank_a.upper()}/{bank_b.upper()}")
    if _nan(div_a) or _nan(div_b):
        return {"pair": pair, "signal": "NO DATA", "rel_divergence_bp": float("nan"), "conviction": 0}
    rel = div_a - div_b
    if abs(rel) < SIGNAL_THRESHOLD_BP:
        return {"pair": pair, "signal": "NEUTRAL", "rel_divergence_bp": round(rel, 1), "conviction": 0}
    long_leg = _CURRENCY[bank_a] if rel > 0 else _CURRENCY[bank_b]
    short_leg = _CURRENCY[bank_b] if rel > 0 else _CURRENCY[bank_a]
    return {
        "pair": pair,
        "signal": f"Long {long_leg} / short {short_leg} (relative hawkish repricing)",
        "rel_divergence_bp": round(rel, 1),
        "conviction": 2 if abs(rel) > SIGNAL_STRONG_BP else 1,
    }


def build_signal_table(divergences: dict) -> pd.DataFrame:
    """Every cross-bank spread + FX signal from {bank_code: mean divergence bp}."""
    banks = list(divergences)
    rows = []
    for i in range(len(banks)):
        for j in range(i + 1, len(banks)):
            a, b = banks[i], banks[j]
            spread = spread_signal(a, divergences[a], b, divergences[b])
            fx = fx_signal(a, divergences[a], b, divergences[b])
            rows.append({"type": "Rates spread", **spread})
            rows.append({"type": "FX", **fx})
    return pd.DataFrame(rows)
