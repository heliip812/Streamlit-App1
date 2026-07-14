"""Small, dependency-free data-shaping helpers shared across pages.

Not Streamlit-specific (unlike ui.py) and not DTCC-specific (unlike
data/dtcc/normalize.py) — just pandas operations more than one page needs.

The three signal functions (trend_signal, curve_kink, flow_vs_average) back
every page's "Trading signals" section — extracted here once several pages
needed the identical computation (percentile rank of a level, deviation
from a curve's neighbors, today's flow vs. the window average) over
different underlying series, so each page just supplies its own grouping
and calls the same tested logic.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


def drop_outliers(series: pd.Series, lower: float = 0.01, upper: float = 0.99) -> pd.Series:
    """Percentile-clip a series to the given band, dropping values outside it.

    DTCC's "level" field (rate/spread/price/exchange-rate, whichever a trade
    populates) mixes wildly different units and conventions across products —
    decimal-fraction rates, percentage-point rates, CDS spreads, FX exchange
    rates that are legitimately in the thousands for some pairs — and
    occasionally a placeholder sentinel (e.g. a repeating-9s value) rather
    than a real number. A single hardcoded threshold can't separate signal
    from noise across all of that, but a percentile clip relative to the
    selection's *own* distribution (one currency, one pair, one tenor) can.
    """
    if series.empty:
        return series
    bounds = series.quantile([lower, upper])
    return series[series.between(bounds.iloc[0], bounds.iloc[1])]


def sample_for_scatter(df: pd.DataFrame, max_points: int = 5000, random_state: int = 0) -> pd.DataFrame:
    """Downsample a frame before plotting every row as a raw scatter marker.

    Widening a lookback window scales the row count linearly, but a raw
    "every individual trade" scatter doesn't get more informative past a
    few thousand points — it just gets slower to render and heavier to
    serialize. This was the actual driver behind a memory crash at a wider
    lookback (a single scatter trace with tens of thousands of markers is
    expensive on the server side building/serializing the figure, well
    before the browser ever sees it) — aggregate views (medians, sums)
    should keep using the full frame; only the raw-point visualization
    needs capping.
    """
    if len(df) <= max_points:
        return df
    return df.sample(n=max_points, random_state=random_state)


@dataclass
class TrendSignal:
    latest_value: float
    change: float | None  # None if fewer than 2 periods
    percentile: float  # 0-100, latest value's rank within the series
    n_periods: int


def trend_signal(series: pd.Series) -> TrendSignal | None:
    """Latest value, period-over-period change, and percentile rank within
    a sorted-by-period series (e.g. daily median level, weekly net
    position) — the "is this rich/cheap vs. its own recent history" signal
    used on every page, and (applied to CFTC net positioning) the
    "positioning extreme" signal too: a percentile near 0 or 100 there is
    the classic contrarian flag.
    """
    clean = series.dropna()
    if clean.empty:
        return None
    ordered = clean.sort_index()
    latest = ordered.iloc[-1]
    change = latest - ordered.iloc[-2] if len(ordered) >= 2 else None
    percentile = (ordered <= latest).mean() * 100
    return TrendSignal(latest_value=latest, change=change, percentile=percentile, n_periods=len(ordered))


def curve_kink(points: pd.DataFrame, label_col: str, x_col: str, y_col: str) -> tuple[str, float] | None:
    """Which interior point on a curve deviates most from a straight line
    through its immediate neighbors — a butterfly/kink relative-value
    signal. Returns (label, signed deviation) for the single largest
    deviation, or None with fewer than 3 points.
    """
    pts = points.dropna(subset=[x_col, y_col]).sort_values(x_col).reset_index(drop=True)
    if len(pts) < 3:
        return None
    deviations = []
    for i in range(1, len(pts) - 1):
        x0, y0 = pts.loc[i - 1, x_col], pts.loc[i - 1, y_col]
        x1, y1 = pts.loc[i, x_col], pts.loc[i, y_col]
        x2, y2 = pts.loc[i + 1, x_col], pts.loc[i + 1, y_col]
        if x2 == x0:
            continue
        interpolated = y0 + (y2 - y0) * (x1 - x0) / (x2 - x0)
        deviations.append((pts.loc[i, label_col], y1 - interpolated))
    if not deviations:
        return None
    return max(deviations, key=lambda d: abs(d[1]))


def flow_vs_average(by_period_bucket: pd.Series, latest_period: object, min_share: float = 0.01) -> tuple[str, float] | None:
    """Which bucket's latest-period total is furthest (as a ratio) from
    that bucket's own average across the period, e.g. "today's <1Y
    notional is 2.3x its window average". `by_period_bucket` is a Series
    with a 2-level (period, bucket) MultiIndex already summed per
    period+bucket. Buckets under `min_share` of total volume are excluded
    so a near-zero average can't turn one trivial trade into a
    meaningless "50x normal" spike. Returns None if nothing qualifies.
    """
    period_level, bucket_level = by_period_bucket.index.names
    window_avg = by_period_bucket.groupby(bucket_level, observed=True).mean()
    if latest_period not in by_period_bucket.index.get_level_values(period_level):
        return None
    latest_by_bucket = by_period_bucket.xs(latest_period, level=period_level)
    material = window_avg[window_avg > window_avg.sum() * min_share]
    ratios = (latest_by_bucket / material).dropna()
    if ratios.empty:
        return None
    bucket = ratios.idxmax()
    return bucket, ratios[bucket]
