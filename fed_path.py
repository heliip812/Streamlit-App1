"""Market-implied Fed policy path from the short-end Treasury curve.

Pure, dependency-light functions (pandas only, no Streamlit, no network) so
the logic — turning a handful of constant-maturity Treasury yields into an
implied forward short-rate path, then reading that path at arbitrary horizons
— is fully unit-tested independently of the FRED data that supplies the yields.

Method: a yield to maturity `t` is (roughly) the market's expected average
short rate over the next `t` years, so the *forward* rate implied between two
maturities is the expected average short rate over that future window:

    forward(t_a, t_b) = (y(t_b)·t_b − y(t_a)·t_a) / (t_b − t_a)

Chaining the forwards across the short-end maturities traces out where the
market expects the policy rate to go — a Fed-path proxy. It is only a proxy:
these are par yields used as if they were zero rates, they carry a little term
premium, and T-bills trade slightly rich, so the path reads marginally more
dovish than a pure OIS/futures measure. Good for direction and rough
magnitude, not a substitute for a real policy-expectations curve.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def implied_forward_path(yields_by_years: dict[float, float], anchor_rate: float) -> pd.DataFrame:
    """Implied forward short-rate path from maturity->yield points.

    `yields_by_years` maps a maturity in years to its annualised yield (in
    percent); `anchor_rate` is the current overnight rate (EFFR), placed at
    horizon 0. Returns a DataFrame [horizon_years, rate] with one row per
    maturity, each the implied average short rate over the segment ending at
    that maturity, prefixed by the (0, anchor_rate) point. Fewer than one
    maturity yields just the anchor point.
    """
    points: list[tuple[float, float]] = [(0.0, anchor_rate)]
    prev_t, prev_yt = 0.0, 0.0  # previous maturity, and yield*maturity at it
    for maturity, yld in sorted(yields_by_years.items()):
        year_times_yield = yld * maturity
        segment = maturity - prev_t
        forward = (year_times_yield - prev_yt) / segment if segment > 0 else yld
        points.append((maturity, forward))
        prev_t, prev_yt = maturity, year_times_yield
    return pd.DataFrame(points, columns=["horizon_years", "rate"])


def implied_rate_at(path: pd.DataFrame, horizon_years: float) -> float | None:
    """Linearly interpolate the implied path to an arbitrary horizon (years).

    Horizons beyond the path's range clamp to its nearest endpoint rather than
    extrapolating. Returns None for an empty path.
    """
    if path.empty:
        return None
    ordered = path.sort_values("horizon_years")
    # np.interp clamps to the endpoints for out-of-range horizons.
    return float(np.interp(horizon_years, ordered["horizon_years"], ordered["rate"]))
