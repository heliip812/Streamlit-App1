from datetime import date

from data import meetings


def test_fed_effective_is_next_business_day():
    # Wednesday decision -> Thursday effective; Friday decision -> Monday.
    assert meetings.effective_date("fed", date(2026, 7, 29)) == date(2026, 7, 30)
    assert meetings.effective_date("fed", date(2026, 9, 18)) == date(2026, 9, 21)


def test_ecb_effective_is_following_wednesday():
    # Brief's verified example: cut announced Thu 5 Jun 2025 -> Wed 11 Jun 2025.
    assert meetings.effective_date("ecb", date(2025, 6, 5)) == date(2025, 6, 11)
    # A Wednesday decision rolls a full week, never same-day.
    assert meetings.effective_date("ecb", date(2026, 10, 28)) == date(2026, 11, 4)


def test_boe_effective_is_same_day():
    assert meetings.effective_date("boe", date(2026, 9, 17)) == date(2026, 9, 17)


def test_meetings_for_prefers_upcoming_scraped_else_fallback():
    asof = date(2026, 7, 20)
    scraped = [date(2026, 6, 4), date(2026, 9, 10)]  # one past, one upcoming
    mts = meetings.meetings_for("ecb", scraped, asof)
    assert [m.decision for m in mts] == [date(2026, 9, 10)]

    # Past-only scrape -> fallback list (upcoming portion), with notes attached.
    mts = meetings.meetings_for("fed", [date(2026, 6, 17)], asof)
    assert mts[0].decision == date(2026, 7, 29)
    assert any(m.note == "SEP/dot plot" for m in mts)
    assert any(m.note == "tentative" for m in mts if m.decision.year == 2027)
