import pandas as pd

from analytics import drop_outliers


def test_drop_outliers_removes_extreme_sentinel_value():
    # A realistic cluster of rates plus one bogus placeholder-like outlier.
    series = pd.Series([0.04, 0.041, 0.039, 0.042, 0.038, 0.04, 620000.0])

    out = drop_outliers(series, lower=0.01, upper=0.99)

    assert 620000.0 not in out.values
    assert len(out) < len(series)


def test_drop_outliers_keeps_tight_cluster_mostly_unchanged():
    series = pd.Series([1490 + i * 0.5 for i in range(40)])  # tight, evenly-spread cluster

    out = drop_outliers(series, lower=0.01, upper=0.99)

    assert len(out) >= len(series) - 2


def test_drop_outliers_handles_empty_series():
    assert drop_outliers(pd.Series(dtype=float)).empty
