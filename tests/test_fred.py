from unittest.mock import Mock, patch

import requests

from data import fred


def _fake_response(csv_text):
    resp = Mock()
    resp.raise_for_status = Mock()
    resp.text = csv_text
    return resp


def test_fetch_returns_latest_non_missing_per_series():
    # FRED prints "." for days a series has no observation; the latest real
    # value must win, per column, independent of the others' gaps.
    csv_text = (
        "observation_date,DFF,DGS3MO\n"
        "2026-07-10,4.33,4.20\n"
        "2026-07-11,4.33,.\n"
        "2026-07-12,.,4.18\n"
    )

    with patch("data.fred.requests.get", return_value=_fake_response(csv_text)):
        out = fred.fetch_fred_latest(("DFF", "DGS3MO"))

    assert out["DFF"] == 4.33  # last real DFF (07-11), not the "." on 07-12
    assert out["DGS3MO"] == 4.18  # last real DGS3MO (07-12)


def test_fetch_omits_series_absent_from_response():
    csv_text = "observation_date,DFF\n2026-07-10,4.33\n"

    with patch("data.fred.requests.get", return_value=_fake_response(csv_text)):
        out = fred.fetch_fred_latest(("DFF", "DGS3MO"))

    assert out == {"DFF": 4.33}  # DGS3MO not in the CSV -> omitted, no crash


def test_fetch_returns_empty_on_network_error():
    with patch("data.fred.requests.get", side_effect=requests.ConnectionError("boom")):
        assert fred.fetch_fred_latest(("DFF",)) == {}


def test_fetch_returns_empty_for_no_series():
    assert fred.fetch_fred_latest(()) == {}
