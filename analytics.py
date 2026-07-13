"""Small, dependency-free data-shaping helpers shared across pages.

Not Streamlit-specific (unlike ui.py) and not DTCC-specific (unlike
data/dtcc/normalize.py) — just pandas operations more than one page needs.
"""

from __future__ import annotations

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
