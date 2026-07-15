from unittest.mock import Mock, patch

import requests

from data import boe, boj


def _fake_response(text):
    resp = Mock()
    resp.raise_for_status = Mock()
    resp.text = text
    return resp


def test_boe_iadb_takes_latest_value_per_code():
    csv_text = "DATE,IUDBEDR,IUDMNPY,IUDSNPY\n30 Jun 2026,3.75,3.80,3.60\n01 Jul 2026,3.75,,3.58\n"
    with patch("data.boe.requests.get", return_value=_fake_response(csv_text)):
        out = boe._fetch_iadb(("IUDBEDR", "IUDMNPY", "IUDSNPY"))

    assert out["IUDBEDR"] == 3.75
    assert out["IUDMNPY"] == 3.80  # blank on the last row -> falls back to prior real value
    assert out["IUDSNPY"] == 3.58


def test_boe_policy_inputs_maps_codes_to_maturities():
    # BOE_YIELD_CODES maps IUDMNPY->1.0, IUDSNPY->2.0 (best-effort defaults).
    fake = {"IUDBEDR": 3.75, "IUDMNPY": 3.80, "IUDSNPY": 3.60}
    with patch("data.boe._fetch_iadb", return_value=fake):
        out = boe.fetch_boe_policy_inputs()

    assert out["bank_rate"] == 3.75
    assert out["yields"] == {1.0: 3.80, 2.0: 3.60}
    assert any("BoE IADB" in line for line in out["status"])


def test_boe_reports_unavailable_curve_on_failure():
    with patch("data.boe.requests.get", side_effect=requests.ConnectionError("boom")):
        out = boe.fetch_boe_policy_inputs()

    assert out["yields"] == {}
    assert any("unavailable" in line for line in out["status"])


def test_boj_jgb_parses_latest_row():
    csv_text = "Date,1Y,2Y,5Y,10Y\n2026-07-10,0.54,0.68,0.90,1.20\n2026-07-13,0.55,0.70,0.92,1.22\n"
    with patch("data.boj.requests.get", return_value=_fake_response(csv_text)):
        out = boj._jgb_yields()

    assert out == {1.0: 0.55, 2.0: 0.70}  # latest row, only mapped maturities


def test_boj_reports_unavailable_on_failure():
    with patch("data.boj.requests.get", side_effect=requests.ConnectionError("boom")):
        out = boj.fetch_boj_policy_inputs()

    assert out["yields"] == {}
    assert any("unavailable" in line for line in out["status"])
