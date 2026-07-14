from datetime import date

from data import cb_calendar

# Representative FOMC calendar markup: two years, two-day meeting ranges, and a
# single-day "Minutes" release that must NOT be mistaken for a meeting.
_FOMC_HTML = """
<div class="panel-heading">2025 FOMC Meetings</div>
<div>January 28-29</div>
<div>March 18-19</div>
<div class="panel-heading">2026 FOMC Meetings</div>
<div>January 27-28</div>
<div>Minutes: February 18</div>
<div>March 17-18</div>
<div>July 28-29</div>
<div>December 8-9</div>
"""

_ECB_HTML = """
<table>
<tr><td>5 February 2026</td></tr>
<tr><td>18-19 March 2026</td></tr>
<tr><td>30 April 2026</td></tr>
<tr><td>4 June 2026</td></tr>
</table>
"""


def test_parse_fomc_takes_second_day_and_assigns_year():
    dates = cb_calendar.parse_fomc(_FOMC_HTML)

    assert date(2026, 3, 18) in dates  # second day of "March 17-18"
    assert date(2026, 7, 29) in dates
    assert date(2026, 12, 9) in dates
    assert date(2025, 1, 29) in dates  # assigned to the 2025 header


def test_parse_fomc_ignores_single_day_minutes_release():
    dates = cb_calendar.parse_fomc(_FOMC_HTML)

    assert date(2026, 2, 18) not in dates  # "Minutes: February 18" is not a range


def test_parse_ecb_takes_last_day_of_range():
    dates = cb_calendar.parse_ecb(_ECB_HTML)

    assert date(2026, 2, 5) in dates
    assert date(2026, 3, 19) in dates  # last day of "18-19 March"
    assert date(2026, 4, 30) in dates


def test_parsers_return_empty_when_too_few_dates():
    # A single date is below the plausibility floor -> reject, so the caller
    # falls back to the maintained list rather than trusting a thin scrape.
    assert cb_calendar.parse_fomc("<div>2026 FOMC Meetings</div><div>March 17-18</div>") == []
    assert cb_calendar.parse_ecb("<td>5 February 2026</td>") == []
