"""A rule-based 'own model' for the policy path, to compare against the market.

A Taylor-gap core plus a momentum overlay, mapped to hike/hold/cut
probabilities and iterated across the meeting calendar — the same construction
as the reference dashboard, kept as pure functions (no Streamlit, no network)
so the logic is fully unit-tested and the macro inputs are injected by the
caller.

    r* = neutral + a·(core inflation − target) + b·(NAIRU − unemployment)
    expected move = inertia·(r* − r) + momentum tilt

The neutral rate, target, and the a/b/inertia weights are the user's view
(sidebar sliders), not fixed truth — this is a research scaffold, not a
forecast. Every macro input is optional: a missing (NaN) series contributes
zero to its gap rather than breaking the path.
"""

from __future__ import annotations

import math
from datetime import date

import pandas as pd


def _is_num(x) -> bool:
    return x is not None and not (isinstance(x, float) and math.isnan(x))


def taylor_star(
    core_infl_yoy: float,
    unemployment: float,
    nairu: float,
    *,
    inflation_target: float,
    neutral: float,
    a: float,
    b: float,
) -> float:
    """The Taylor-rule implied neutral-consistent policy rate r* (percent)."""
    infl_gap = (core_infl_yoy - inflation_target) if _is_num(core_infl_yoy) else 0.0
    u_gap = (nairu - unemployment) if _is_num(unemployment) and _is_num(nairu) else 0.0
    return neutral + a * infl_gap + b * u_gap


def momentum_adjustment(core_infl_3m: float, core_infl_yoy: float, nfci: float) -> float:
    """A small bp tilt: inflation re-acceleration is hawkish, tight financial
    conditions are dovish. Bounded so it never dominates the Taylor core."""
    adj = 0.0
    if _is_num(core_infl_3m) and _is_num(core_infl_yoy):
        adj += max(-8.0, min(8.0, (core_infl_3m - core_infl_yoy) * 4.0))
    if _is_num(nfci):
        adj += max(-6.0, min(6.0, -nfci * 5.0))
    return adj


def meeting_probabilities(gap_bp: float, momentum_adj_bp: float = 0.0, *, inertia: float, temp: float = 12.0, step_bp: float = 25.0) -> dict:
    """Map a policy gap (r* − r, in bp) to {p_hike, p_hold, p_cut, expected_move_bp}.

    `inertia` is the fraction of the gap the bank closes per meeting; `temp` is
    the logistic temperature in bp (smaller = more decisive).
    """
    expected_move = inertia * gap_bp + momentum_adj_bp
    p_hike = 1.0 / (1.0 + math.exp(-(expected_move - step_bp / 2) / temp))
    p_cut = 1.0 / (1.0 + math.exp((expected_move + step_bp / 2) / temp))
    p_hold = max(1.0 - p_hike - p_cut, 0.0)
    total = p_hike + p_cut + p_hold
    return {
        "p_hike": p_hike / total,
        "p_hold": p_hold / total,
        "p_cut": p_cut / total,
        "expected_move_bp": expected_move,
    }


def model_path(
    meetings: list[date],
    current_rate: float,
    macro: dict,
    *,
    inflation_target: float,
    neutral: float,
    a: float,
    b: float,
    inertia: float,
    step_bp: float = 25.0,
) -> pd.DataFrame:
    """Iterate the rule forward across the meeting calendar into a path.

    `macro` supplies core_infl_yoy / core_infl_3m / unemployment / nairu / nfci
    (any may be missing). Returns one row per meeting with the model rate,
    discretised step, and hike/hold/cut probabilities.
    """
    star = taylor_star(
        macro.get("core_infl_yoy", float("nan")),
        macro.get("unemployment", float("nan")),
        macro.get("nairu", float("nan")),
        inflation_target=inflation_target,
        neutral=neutral,
        a=a,
        b=b,
    )
    momentum = momentum_adjustment(
        macro.get("core_infl_3m", float("nan")),
        macro.get("core_infl_yoy", float("nan")),
        macro.get("nfci", float("nan")),
    )

    rate = current_rate
    rows = []
    for i, meeting in enumerate(sorted(meetings)):
        gap_bp = (star - rate) * 100.0
        probs = meeting_probabilities(gap_bp, momentum if i == 0 else momentum * 0.5, inertia=inertia, step_bp=step_bp)
        # Discretise the expected move to the nearest whole step for the path.
        step = step_bp * round(probs["expected_move_bp"] / step_bp)
        step = max(-2 * step_bp, min(2 * step_bp, step))
        rate = rate + step / 100.0
        rows.append(
            {
                "meeting": meeting,
                "model_rate": round(rate, 3),
                "model_step_bp": step,
                "model_direction": "hike" if step > 0 else ("cut" if step < 0 else "hold"),
                "p_hike": round(probs["p_hike"], 2),
                "p_hold": round(probs["p_hold"], 2),
                "p_cut": round(probs["p_cut"], 2),
                "r_star": round(star, 2),
            }
        )
    return pd.DataFrame(rows)
