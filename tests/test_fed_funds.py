from unittest.mock import Mock, patch

import requests

from data import fed_funds


def _fake_response(payload):
    resp = Mock()
    resp.raise_for_status = Mock()
    resp.json = Mock(return_value=payload)
    return resp


def test_fetch_parses_strip_and_sorts_front_to_back():
    payload = {
        "quotes": [
            {"expirationDate": "20260430", "priorSettle": "95.920", "last": "95.925"},
            {"expirationDate": "20260330", "priorSettle": "95.775", "last": ""},
        ]
    }

    with patch("data.fed_funds.requests.get", return_value=_fake_response(payload)):
        df = fed_funds.fetch_fed_funds_futures()

    assert list(df["contract_month"].dt.strftime("%Y-%m")) == ["2026-03", "2026-04"]
    assert df.iloc[0]["price"] == 95.775
    # Blank `last` must not stop it falling back to priorSettle.
    assert df.iloc[1]["price"] == 95.920


def test_fetch_prefers_prior_settle_but_falls_back_to_last():
    payload = {"quotes": [{"expirationDate": "20260330", "priorSettle": "", "last": "95.71"}]}

    with patch("data.fed_funds.requests.get", return_value=_fake_response(payload)):
        df = fed_funds.fetch_fed_funds_futures()

    assert df.iloc[0]["price"] == 95.71


def test_fetch_returns_empty_on_network_error():
    with patch("data.fed_funds.requests.get", side_effect=requests.ConnectionError("boom")):
        df = fed_funds.fetch_fed_funds_futures()

    assert df.empty
    assert list(df.columns) == ["contract_month", "price"]


def test_fetch_returns_empty_on_unexpected_payload():
    with patch("data.fed_funds.requests.get", return_value=_fake_response({"noquotes": []})):
        df = fed_funds.fetch_fed_funds_futures()

    assert df.empty


def test_fetch_skips_unparseable_rows():
    payload = {
        "quotes": [
            {"expirationDate": "garbage", "priorSettle": "95.7"},
            {"expirationDate": "20260330", "priorSettle": "not-a-number"},
            {"expirationDate": "20260330", "priorSettle": "95.775"},
        ]
    }

    with patch("data.fed_funds.requests.get", return_value=_fake_response(payload)):
        df = fed_funds.fetch_fed_funds_futures()

    assert len(df) == 1
    assert df.iloc[0]["price"] == 95.775
