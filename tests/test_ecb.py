from unittest.mock import Mock, patch

import requests

from data import ecb


def _fake_response(csv_text):
    resp = Mock()
    resp.raise_for_status = Mock()
    resp.text = csv_text
    return resp


def test_fetch_latest_value_reads_last_obs_value():
    csv_text = (
        "KEY,FREQ,TIME_PERIOD,OBS_VALUE\n"
        "FM.B...,B,2026-07-10,2.00\n"
        "FM.B...,B,2026-07-11,1.90\n"
    )

    with patch("data.ecb.requests.get", return_value=_fake_response(csv_text)):
        assert ecb._fetch_latest_value("FM/B.U2.EUR.4F.KR.DFR.LEV") == 1.90


def test_fetch_latest_value_none_on_network_error():
    with patch("data.ecb.requests.get", side_effect=requests.ConnectionError("boom")):
        assert ecb._fetch_latest_value("FM/whatever") is None


def test_fetch_latest_value_none_when_no_obs_column():
    with patch("data.ecb.requests.get", return_value=_fake_response("KEY,TIME_PERIOD\nx,2026-07-11\n")):
        assert ecb._fetch_latest_value("FM/whatever") is None


def test_fetch_policy_inputs_composes_normalised_dict():
    # Map each series key to a value so the composed dict is deterministic.
    by_key = {
        "EST/B.EU000A2X2A25.WT": 1.92,
        "FM/B.U2.EUR.4F.KR.DFR.LEV": 1.75,
        "FM/B.U2.EUR.4F.KR.MRR_FR.LEV": 2.00,
        "YC/B.U2.EUR.4F.G_N_A.SV_C_YM.SR_3M": 1.85,
        "YC/B.U2.EUR.4F.G_N_A.SV_C_YM.SR_6M": 1.80,
        "YC/B.U2.EUR.4F.G_N_A.SV_C_YM.SR_1Y": 1.70,
        "YC/B.U2.EUR.4F.G_N_A.SV_C_YM.SR_2Y": 1.60,
    }

    with patch("data.ecb._fetch_latest_value", side_effect=lambda key: by_key.get(key)):
        out = ecb.fetch_ecb_policy_inputs()

    assert out["estr"] == 1.92
    assert out["dfr"] == 1.75
    assert out["mro"] == 2.00
    assert out["yields"] == {0.25: 1.85, 0.5: 1.80, 1.0: 1.70, 2.0: 1.60}


def test_fetch_policy_inputs_omits_missing_yields():
    with patch("data.ecb._fetch_latest_value", side_effect=lambda key: 1.5 if "SR_3M" in key else None):
        out = ecb.fetch_ecb_policy_inputs()

    assert out["yields"] == {0.25: 1.5}
    assert out["estr"] is None
