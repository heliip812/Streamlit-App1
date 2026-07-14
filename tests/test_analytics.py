from datetime import date

import pandas as pd

from analytics import curve_kink, drop_outliers, flow_vs_average, sample_for_scatter, trend_signal


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


def test_sample_for_scatter_caps_large_frames():
    df = pd.DataFrame({"x": range(10000)})

    out = sample_for_scatter(df, max_points=500)

    assert len(out) == 500


def test_sample_for_scatter_leaves_small_frames_untouched():
    df = pd.DataFrame({"x": range(50)})

    out = sample_for_scatter(df, max_points=500)

    assert len(out) == 50


def test_trend_signal_computes_change_and_percentile():
    series = pd.Series(
        [0.038, 0.039, 0.040, 0.041, 0.040],
        index=[date(2026, 7, i) for i in range(6, 11)],
    )

    signal = trend_signal(series)

    assert signal.latest_value == 0.040
    assert round(signal.change, 4) == round(0.040 - 0.041, 4)
    assert signal.n_periods == 5
    assert signal.percentile == 80.0  # 4 of 5 values <= 0.040


def test_trend_signal_handles_single_period():
    signal = trend_signal(pd.Series([0.04], index=[date(2026, 7, 10)]))

    assert signal.latest_value == 0.04
    assert signal.change is None
    assert signal.n_periods == 1


def test_trend_signal_returns_none_for_empty_series():
    assert trend_signal(pd.Series(dtype=float)) is None


def test_curve_kink_finds_largest_deviation_from_neighbors():
    # A clean upward slope except the 3rd point, which sits well above
    # a straight line drawn between its neighbors.
    points = pd.DataFrame(
        {
            "bucket": ["1Y", "3Y", "5Y", "7Y", "10Y"],
            "x": [1, 3, 5, 7, 10],
            "y": [0.03, 0.035, 0.06, 0.045, 0.05],
        }
    )

    result = curve_kink(points, label_col="bucket", x_col="x", y_col="y")

    assert result is not None
    bucket, deviation = result
    assert bucket == "5Y"
    assert deviation > 0


def test_curve_kink_returns_none_with_fewer_than_three_points():
    points = pd.DataFrame({"bucket": ["1Y", "5Y"], "x": [1, 5], "y": [0.03, 0.04]})
    assert curve_kink(points, "bucket", "x", "y") is None


def test_flow_vs_average_flags_unusual_bucket():
    idx = pd.MultiIndex.from_tuples(
        [
            (date(2026, 7, 6), "<1Y"), (date(2026, 7, 7), "<1Y"), (date(2026, 7, 8), "<1Y"),
            (date(2026, 7, 6), "1-2Y"), (date(2026, 7, 7), "1-2Y"), (date(2026, 7, 8), "1-2Y"),
        ],
        names=["day", "bucket"],
    )
    series = pd.Series([100, 100, 350, 200, 200, 210], index=idx)

    result = flow_vs_average(series, latest_period=date(2026, 7, 8))

    assert result is not None
    bucket, ratio = result
    assert bucket == "<1Y"
    # window average includes the latest day itself: (100+100+350)/3
    assert round(ratio, 3) == round(350 / ((100 + 100 + 350) / 3), 3)


def test_flow_vs_average_excludes_thin_buckets():
    idx = pd.MultiIndex.from_tuples(
        [
            (date(2026, 7, 6), "big"), (date(2026, 7, 7), "big"),
            (date(2026, 7, 6), "tiny"), (date(2026, 7, 7), "tiny"),
        ],
        names=["day", "bucket"],
    )
    # "tiny" averages 1, and a single trade of 100 would be a meaningless "100x" spike.
    series = pd.Series([100000, 100000, 1, 100], index=idx)

    result = flow_vs_average(series, latest_period=date(2026, 7, 7))

    assert result is None or result[0] != "tiny"


def test_flow_vs_average_returns_none_when_period_missing():
    idx = pd.MultiIndex.from_tuples([(date(2026, 7, 6), "a")], names=["day", "bucket"])
    series = pd.Series([100], index=idx)

    assert flow_vs_average(series, latest_period=date(2026, 7, 9)) is None
