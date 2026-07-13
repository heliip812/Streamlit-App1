from unittest.mock import Mock, patch

import requests

from data import cftc


def _fake_response(records):
    resp = Mock()
    resp.raise_for_status = Mock()
    resp.json = Mock(return_value=records)
    return resp


def test_fetch_positioning_computes_net_for_financial_report():
    records = [
        {
            "report_date_as_yyyy_mm_dd": "2026-07-07T00:00:00.000",
            "market_and_exchange_names": "10-YEAR U.S. TREASURY NOTES - CBOT",
            "open_interest_all": "100",
            "dealer_positions_long_all": "40",
            "dealer_positions_short_all": "10",
            "asset_mgr_positions_long": "20",
            "asset_mgr_positions_short": "5",
            "lev_money_positions_long": "15",
            "lev_money_positions_short": "25",
            "other_rept_positions_long": "5",
            "other_rept_positions_short": "5",
        }
    ]

    with patch("data.cftc.requests.get", return_value=_fake_response(records)):
        df = cftc.fetch_positioning(["10-YEAR"], weeks=8, report="financial")

    assert df.loc[0, "dealer_net"] == 30
    assert df.loc[0, "asset_mgr_net"] == 15
    assert df.loc[0, "lev_money_net"] == -10
    assert df.loc[0, "other_net"] == 0


def test_fetch_positioning_handles_disaggregated_column_naming_variants():
    # Real CFTC schema has at least one known naming inconsistency (a stray
    # double underscore); the fuzzy matcher should tolerate that rather
    # than silently producing wrong nets.
    records = [
        {
            "report_date_as_yyyy_mm_dd": "2026-07-07T00:00:00.000",
            "market_and_exchange_names": "WTI-PHYSICAL - NYMEX",
            "open_interest_all": "1000",
            "prod_merc_positions_long": "300",
            "prod_merc_positions_short": "200",
            "swap__positions_long_all": "150",
            "swap__positions_short_all": "100",
            "m_money_positions_long_all": "80",
            "m_money_positions_short_all": "60",
            "other_rept_positions_long": "20",
            "other_rept_positions_short": "10",
        }
    ]

    with patch("data.cftc.requests.get", return_value=_fake_response(records)):
        df = cftc.fetch_positioning(["WTI"], weeks=8, report="commodities")

    assert df.loc[0, "prod_merc_net"] == 100
    assert df.loc[0, "swap_net"] == 50
    assert df.loc[0, "m_money_net"] == 20
    assert df.loc[0, "other_net"] == 10


def test_fetch_positioning_returns_empty_frame_on_network_error():
    with patch("data.cftc.requests.get", side_effect=requests.ConnectionError("boom")):
        df = cftc.fetch_positioning(["WTI"], weeks=8, report="commodities")
    assert df.empty


def test_category_columns_matches_report():
    financial = cftc.category_columns("financial")
    assert ("Dealer", "dealer_net") in financial

    commodities = cftc.category_columns("commodities")
    assert ("Swap dealer", "swap_net") in commodities
