from unittest.mock import patch

from data import cb_calendar, central_banks


def test_registry_entries_are_complete_and_unique():
    codes = [spec.code for spec in central_banks.CENTRAL_BANKS]
    labels = [spec.label for spec in central_banks.CENTRAL_BANKS]

    assert len(codes) == len(set(codes))
    assert len(labels) == len(set(labels))
    for spec in central_banks.CENTRAL_BANKS:
        # A calendar_code may or may not have a live scraper (banks without one
        # rely on the fallback), but every spec MUST carry a non-empty fallback
        # so meeting dates always render, and fetch must be callable.
        assert spec.meeting_fallback
        assert callable(spec.fetch)


def test_calendar_codes_with_scrapers_resolve():
    # Any code that claims a scraper must actually have one registered.
    scraped = {"fomc", "ecb"}
    assert scraped <= set(cb_calendar.FETCHERS)


def test_get_spec_resolves_by_code_and_label():
    assert central_banks.get_spec("fed").code == "fed"
    assert central_banks.get_spec("Federal Reserve").code == "fed"
    assert central_banks.get_spec("ECB").code == "ecb"


def test_fed_adapter_formats_target_range_metric():
    raw = {"anchor": 4.33, "target_range": (4.25, 4.50), "yields": {0.25: 4.2}, "status": ["Curve: FRED"]}
    with patch("data.central_banks.us_rates.fetch_policy_inputs", return_value=raw):
        inputs = central_banks.fetch_inputs("fed")

    assert inputs.anchor_rate == 4.33
    assert inputs.yields == {0.25: 4.2}
    assert ("Target range", "4.25–4.50%") in inputs.metrics


def test_ecb_adapter_prefers_estr_and_formats_metrics():
    raw = {"estr": 1.92, "dfr": 1.75, "mro": 2.00, "yields": {0.25: 1.85}}
    with patch("data.central_banks.ecb.fetch_ecb_policy_inputs", return_value=raw):
        inputs = central_banks.fetch_inputs("ecb")

    assert inputs.anchor_rate == 1.92
    assert ("Deposit facility / MRO", "1.75% / 2.00%") in inputs.metrics
    assert any("ECB Data Portal" in line for line in inputs.status)


def test_ecb_adapter_falls_back_to_deposit_rate_anchor():
    raw = {"estr": None, "dfr": 1.75, "mro": None, "yields": {}}
    with patch("data.central_banks.ecb.fetch_ecb_policy_inputs", return_value=raw):
        inputs = central_banks.fetch_inputs("ecb")

    assert inputs.anchor_rate == 1.75
    assert inputs.yields == {}
    assert any("unavailable" in line for line in inputs.status)


def test_boe_adapter_passes_through_bank_rate_and_curve():
    raw = {"bank_rate": 3.75, "yields": {1.0: 3.80, 2.0: 3.60}, "status": ["Curve: BoE IADB", "Bank Rate: BoE IADB"]}
    with patch("data.central_banks.boe.fetch_boe_policy_inputs", return_value=raw):
        inputs = central_banks.fetch_inputs("boe")

    assert inputs.anchor_rate == 3.75
    assert inputs.yields == {1.0: 3.80, 2.0: 3.60}


def test_boj_adapter_has_no_live_anchor():
    raw = {"yields": {1.0: 0.55, 2.0: 0.70}, "status": ["Curve: MOF JGB"]}
    with patch("data.central_banks.boj.fetch_boj_policy_inputs", return_value=raw):
        inputs = central_banks.fetch_inputs("boj")

    assert inputs.anchor_rate is None  # page supplies the anchor from the sidebar/fallback
    assert inputs.yields == {1.0: 0.55, 2.0: 0.70}
    assert any("manual anchor" in line for line in inputs.status)
