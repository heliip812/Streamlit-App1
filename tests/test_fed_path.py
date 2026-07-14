import pandas as pd

from fed_path import implied_forward_path, implied_rate_at


def test_forward_path_prefixes_anchor_and_computes_forwards():
    # 3M yield 4.0 (avg rate over 0-3M), 6M yield 3.8. The implied forward
    # over the 3-6M window is (3.8*0.5 - 4.0*0.25) / 0.25 = 3.6.
    path = implied_forward_path({0.25: 4.0, 0.5: 3.8}, anchor_rate=4.33)

    assert list(path["horizon_years"]) == [0.0, 0.25, 0.5]
    assert path.loc[0, "rate"] == 4.33  # anchor at horizon 0
    assert round(path.loc[1, "rate"], 4) == 4.0  # first segment == its yield
    assert round(path.loc[2, "rate"], 4) == 3.6  # implied 3-6M forward


def test_forward_path_orders_maturities():
    # Supplied out of order; must still chain shortest-to-longest.
    path = implied_forward_path({0.5: 3.8, 0.25: 4.0}, anchor_rate=4.33)

    assert list(path["horizon_years"]) == [0.0, 0.25, 0.5]


def test_forward_path_with_no_yields_is_just_the_anchor():
    path = implied_forward_path({}, anchor_rate=4.10)

    assert list(path["horizon_years"]) == [0.0]
    assert path.loc[0, "rate"] == 4.10


def test_implied_rate_at_interpolates_between_points():
    path = pd.DataFrame({"horizon_years": [0.0, 0.25, 0.5], "rate": [4.33, 4.0, 3.6]})

    # Midway between the 0.25 (4.0) and 0.5 (3.6) points.
    assert round(implied_rate_at(path, 0.375), 4) == 3.8


def test_implied_rate_at_clamps_beyond_range():
    path = pd.DataFrame({"horizon_years": [0.0, 0.5], "rate": [4.33, 3.6]})

    assert implied_rate_at(path, 5.0) == 3.6  # clamps to far end, no extrapolation
    assert implied_rate_at(path, -1.0) == 4.33  # clamps to near end


def test_implied_rate_at_empty_path_returns_none():
    assert implied_rate_at(pd.DataFrame(columns=["horizon_years", "rate"]), 1.0) is None
