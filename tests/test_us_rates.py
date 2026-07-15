from unittest.mock import Mock, patch

import requests

from data import us_rates


def _fake_response(*, text=None, json_data=None):
    resp = Mock()
    resp.raise_for_status = Mock()
    if text is not None:
        resp.text = text
    if json_data is not None:
        resp.json = Mock(return_value=json_data)
    return resp


_FULL_FRED = {
    "DFF": 4.33,
    "DFEDTARU": 4.50,
    "DFEDTARL": 4.25,
    "DGS1MO": 4.30,
    "DGS3MO": 4.20,
    "DGS6MO": 4.05,
    "DGS1": 3.85,
    "DGS2": 3.70,
}


def test_prefers_fred_and_skips_fallbacks_when_available():
    treasury = Mock()
    nyfed = Mock()
    with (
        patch("data.us_rates.fred.fetch_fred_latest", return_value=_FULL_FRED),
        patch.object(us_rates, "_treasury_yields", treasury),
        patch.object(us_rates, "_nyfed_effr", nyfed),
    ):
        out = us_rates.fetch_policy_inputs()

    assert out["anchor"] == 4.33
    assert out["target_range"] == (4.25, 4.50)
    assert out["yields"][0.25] == 4.20
    assert any("FRED" in line for line in out["status"])
    treasury.assert_not_called()
    nyfed.assert_not_called()


def test_falls_back_to_treasury_and_nyfed_when_fred_empty():
    with (
        patch("data.us_rates.fred.fetch_fred_latest", return_value={}),
        patch.object(us_rates, "_treasury_yields", return_value={0.25: 4.21, 2.0: 3.72}),
        patch.object(us_rates, "_nyfed_effr", return_value=4.33),
    ):
        out = us_rates.fetch_policy_inputs()

    assert out["yields"] == {0.25: 4.21, 2.0: 3.72}
    assert out["anchor"] == 4.33
    assert out["target_range"] is None  # only FRED carries the range
    assert any("Treasury.gov" in line for line in out["status"])
    assert any("NY Fed" in line for line in out["status"])


def test_reports_unavailable_when_everything_fails():
    with (
        patch("data.us_rates.fred.fetch_fred_latest", return_value={}),
        patch.object(us_rates, "_treasury_yields", return_value={}),
        patch.object(us_rates, "_nyfed_effr", return_value=None),
    ):
        out = us_rates.fetch_policy_inputs()

    assert out["yields"] == {}
    assert out["anchor"] is None
    assert any("unavailable" in line for line in out["status"])


def test_treasury_parser_takes_latest_date_and_skips_missing():
    # Rows deliberately out of order; "2 Yr" missing on the latest row must be
    # skipped, not carried from an older row.
    csv_text = (
        'Date,"1 Mo","2 Mo","3 Mo","6 Mo","1 Yr","2 Yr"\n'
        "07/10/2026,4.31,4.28,4.22,4.07,3.87,3.72\n"
        "07/13/2026,4.30,4.27,4.20,4.05,3.85,\n"
    )
    with patch("data.us_rates.requests.get", return_value=_fake_response(text=csv_text)):
        out = us_rates._treasury_yields()

    assert out[0.25] == 4.20  # from the 07/13 row
    assert 2.0 not in out  # blank on the latest row -> omitted
    assert 1 / 12 in out


def test_treasury_parser_empty_on_network_error():
    with patch("data.us_rates.requests.get", side_effect=requests.ConnectionError("boom")):
        assert us_rates._treasury_yields() == {}


def test_nyfed_parser_reads_percent_rate():
    payload = {"refRates": [{"effectiveDate": "2026-07-13", "type": "EFFR", "percentRate": 4.33}]}
    with patch("data.us_rates.requests.get", return_value=_fake_response(json_data=payload)):
        assert us_rates._nyfed_effr() == 4.33


def test_nyfed_parser_none_on_bad_payload():
    with patch("data.us_rates.requests.get", return_value=_fake_response(json_data={"refRates": []})):
        assert us_rates._nyfed_effr() is None
