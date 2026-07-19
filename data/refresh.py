"""Daily refresh job: fetch everything, compute paths + signals, snapshot.

Run manually, from the app's "Refresh & snapshot" button, or on a schedule:
    python -m data.refresh --fred-key YOUR_KEY
Cron (weekdays 07:30 UK, after the BoE publishes its curve):
    30 7 * * 1-5 cd /path/to/app && python -m data.refresh --fred-key $FRED_KEY

No Streamlit imports — this must run headless on the writer box. Market
paths prefer the brief's instruments (Fed: ZQ deconvolution; BoE: OIS
forward windowing; ECB: an injected Eurex €STR path when the app supplies
one) and fall back per bank to this app's always-on government/OIS curve
forwards, with the `method` column recording which produced each number.
"""

from __future__ import annotations

import argparse
from datetime import date

import pandas as pd

import implied_engine as eng
from config import FX_PAIRS
from fed_path import implied_forward_path
from policy_model import model_path
from signals import fx_signal, outright_signal, spread_signal

from . import cb_calendar, cb_market, macro, store
from .central_banks import CENTRAL_BANKS
from .meetings import meetings_for

BASIS_BP = {"fed": -4.5, "ecb": -8.0, "boe": -4.0, "boj": 0.0}


def _anchor(inputs) -> float | None:
    if inputs.anchor_rate is not None:
        return inputs.anchor_rate
    if inputs.yields:
        return inputs.yields[min(inputs.yields)]
    return None


def _scraped_decisions(calendar_code: str) -> list[date]:
    fetcher = cb_calendar.FETCHERS.get(calendar_code)
    try:
        return fetcher() if fetcher else []
    except Exception:
        return []


def build_market_path(spec, anchor: float, meetings, curve_path, asof: date, extra: pd.DataFrame | None = None) -> pd.DataFrame:
    """Preferred instrument-based path, else the curve-forward fallback."""
    if extra is not None and not extra.empty:
        return extra
    if spec.code == "fed":
        raw = cb_market.fetch_ff_futures_raw()
        if not raw.empty:
            path = eng.path_from_monthly_avg(eng.adjust_ff(raw, BASIS_BP["fed"]), anchor, meetings)
            if not path.empty:
                return path
    if spec.code == "boe":
        raw = cb_market.fetch_boe_ois_forward_raw()
        if not raw.empty:
            path = eng.path_from_forward_curve(eng.adjust_boe(raw, BASIS_BP["boe"]), anchor, meetings, asof)
            if not path.empty:
                return path
    return eng.path_from_yield_curve(curve_path, anchor, meetings, asof)


def run(fred_key: str | None = None, asof: date | None = None, extra_market_paths: dict[str, pd.DataFrame] | None = None, model_params: dict | None = None) -> dict:
    """Full refresh. extra_market_paths lets the app inject the ECB path
    (built from an uploaded Eurex CSV) into the same snapshot."""
    asof = asof or date.today()
    params = model_params or {}
    summary, divergences = {}, {}

    for spec in CENTRAL_BANKS:
        inputs = spec.fetch()
        anchor = _anchor(inputs)
        if anchor is None:
            continue
        curve_path = implied_forward_path(inputs.yields, anchor_rate=anchor) if inputs.yields else pd.DataFrame()
        meetings = meetings_for(spec.code, _scraped_decisions(spec.calendar_code), asof)
        market = build_market_path(spec, anchor, meetings, curve_path, asof, (extra_market_paths or {}).get(spec.code))
        if market.empty:
            continue
        merged = market.copy()
        if fred_key:
            macro_inputs = macro.fetch_macro(spec.macro_series, fred_key)
            model = model_path(
                list(market["decision"]), current_rate=anchor, macro=macro_inputs,
                inflation_target=spec.inflation_target, neutral=params.get("neutral", spec.neutral_nominal),
                a=params.get("a", 0.5), b=params.get("b", 0.5), inertia=params.get("inertia", 0.25),
            ).rename(columns={"meeting": "decision"})
            merged = pd.merge(market, model[["decision", "model_rate"]], on="decision", how="left")
            merged["divergence_bp"] = (merged["model_rate"] - merged["implied_rate"]) * 100.0
        store.save_paths(asof, spec.code, merged)
        summary[spec.code] = merged
        if "divergence_bp" in merged:
            usable = merged.dropna(subset=["divergence_bp"])
            if not usable.empty:
                sig = outright_signal(usable)
                divergences[spec.code] = sig["divergence_bp"]
                store.save_signal(asof, f"{spec.code}_outright", sig["signal"], sig["divergence_bp"], sig["conviction"])

    banks = list(divergences)
    for i in range(len(banks)):
        for j in range(i + 1, len(banks)):
            a, b = banks[i], banks[j]
            s = spread_signal(a, divergences[a], b, divergences[b])
            store.save_signal(asof, f"{a}_{b}_spread", s["signal"], s["rel_divergence_bp"], s["conviction"])
            f = fx_signal(a, divergences[a], b, divergences[b])
            store.save_signal(asof, f"{a}_{b}_fx", f["signal"], f.get("rel_divergence_bp", float("nan")), f["conviction"])

    for pair, spot in cb_market.fetch_fx_spots(list(FX_PAIRS.values())).items():
        store.save_fx(asof, pair, spot)

    try:
        from . import s3sync

        if s3sync.enabled():
            pushed = s3sync.push_db(store.db_path())
            print(f"S3 push: {'ok' if pushed else 'FAILED'}")
    except Exception as exc:  # noqa: BLE001
        print(f"S3 push skipped: {exc}")
    return summary


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--fred-key", default=None)
    args = ap.parse_args()
    result = run(args.fred_key)
    for bank, df in result.items():
        print(f"\n{bank}:\n", df.to_string(index=False))
