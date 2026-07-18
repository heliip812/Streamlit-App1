from datetime import date, datetime
from unittest.mock import Mock, patch

import pandas as pd
import requests

from data import boe, boj


def _fake_response(text):
    resp = Mock()
    resp.raise_for_status = Mock()
    resp.text = text
    return resp


def test_boe_iadb_takes_latest_bank_rate():
    csv_text = "DATE,IUDBEDR\n30 Jun 2026,3.75\n01 Jul 2026,3.75\n"
    with patch("data.boe.requests.get", return_value=_fake_response(csv_text)):
        out = boe._fetch_iadb(("IUDBEDR",))

    assert out["IUDBEDR"] == 3.75


def test_boe_extract_short_end_from_spot_sheet():
    # A header=None spot-curve sheet: title/blank rows, a maturity header row,
    # then dated yield rows. The maturity row is found relative to the first
    # dated row, and the latest dated row's yields are returned.
    df = pd.DataFrame(
        [
            ["United Kingdom sterling OIS spot curve", None, None, None],
            [None, None, None, None],
            ["years:", 0.5, 1.0, 2.0],
            [datetime(2026, 7, 10), 4.10, 3.95, 3.70],
            [datetime(2026, 7, 13), 4.08, 3.92, 3.68],
        ]
    )

    assert boe._extract_short_end(df) == {0.5: 4.08, 1.0: 3.92, 2.0: 3.68}


def test_boe_extract_short_end_empty_without_dated_rows():
    df = pd.DataFrame([["years:", 0.5, 1.0, 2.0], ["no", "dates", "here", "x"]])
    assert boe._extract_short_end(df) == {}


def test_boe_extract_history_returns_all_dated_rows():
    df = pd.DataFrame(
        [
            ["United Kingdom sterling OIS spot curve", None, None, None],
            ["years:", 0.5, 1.0, 2.0],
            [datetime(2026, 7, 10), 4.10, 3.95, 3.70],
            [datetime(2026, 7, 13), 4.08, 3.92, 3.68],
        ]
    )

    history = boe._extract_history(df)

    assert set(history) == {date(2026, 7, 10), date(2026, 7, 13)}
    assert history[date(2026, 7, 13)] == {0.5: 4.08, 1.0: 3.92, 2.0: 3.68}


def test_boe_policy_inputs_combines_curve_and_bank_rate():
    history = {date(2026, 7, 10): {0.5: 4.10}, date(2026, 7, 13): {0.5: 4.05, 1.0: 3.90, 2.0: 3.65}}
    with (
        patch("data.boe._fetch_ois_history", return_value=history),
        patch("data.boe._fetch_iadb", return_value={"IUDBEDR": 3.75}),
    ):
        out = boe.fetch_boe_policy_inputs()

    assert out["bank_rate"] == 3.75
    assert out["yields"] == {0.5: 4.05, 1.0: 3.90, 2.0: 3.65}  # latest dated curve
    assert date(2026, 7, 10) in out["history"]
    assert any("OIS spreadsheet" in line for line in out["status"])


def test_boe_reports_unavailable_curve_on_failure():
    with (
        patch("data.boe._fetch_ois_history", return_value={}),
        patch("data.boe._fetch_iadb", return_value={}),
    ):
        out = boe.fetch_boe_policy_inputs()

    assert out["yields"] == {}
    assert any("unavailable" in line for line in out["status"])


def test_boj_jgb_history_parses_rows():
    # The MOF file has a metadata line before the header (parsed with header=1).
    csv_text = (
        "Average Compound Yield etc. (metadata line)\n"
        "Date,1Y,2Y,5Y,10Y\n"
        "2026-07-10,0.54,0.68,0.90,1.20\n"
        "2026-07-13,0.55,0.70,0.92,1.22\n"
    )
    with patch("data.boj.requests.get", return_value=_fake_response(csv_text)):
        history = boj._jgb_history()

    assert set(history) == {date(2026, 7, 10), date(2026, 7, 13)}
    assert history[date(2026, 7, 13)] == {1.0: 0.55, 2.0: 0.70}  # only mapped maturities


def test_boj_fetch_derives_latest_curve_from_history():
    with patch("data.boj._jgb_history", return_value={date(2026, 7, 10): {1.0: 0.54}, date(2026, 7, 13): {1.0: 0.55, 2.0: 0.70}}):
        out = boj.fetch_boj_policy_inputs()

    assert out["yields"] == {1.0: 0.55, 2.0: 0.70}
    assert date(2026, 7, 10) in out["history"]


def test_boj_reports_unavailable_on_failure():
    with patch("data.boj.requests.get", side_effect=requests.ConnectionError("boom")):
        out = boj.fetch_boj_policy_inputs()

    assert out["yields"] == {}
    assert any("unavailable" in line for line in out["status"])
