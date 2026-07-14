"""Best-effort scraping of central-bank meeting calendars.

Neither the Fed nor the ECB publishes its meeting calendar as a clean API —
only as HTML — so these parsers are deliberately conservative: they extract
dates, validate that the result looks sane (enough dates, all in a plausible
year window), and return an empty list otherwise. Callers fall back to a
maintained list in constants.py, so a scrape that fails or a page whose layout
changed degrades to the fallback rather than showing wrong dates.

Like every external host the calendar pages are unreachable from the build
sandbox, so the fetch is verified live only on deploy; the parsers themselves
are unit-tested against representative HTML.
"""

from __future__ import annotations

import re
from datetime import date

import requests

from .constants import ECB_CALENDAR_URL, FOMC_CALENDAR_URL

_REQUEST_TIMEOUT = 30
_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; DerivativesMonitor/1.0)"}

_MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
}
_MONTH_NAMES = "|".join(_MONTHS)

# "2026 FOMC Meetings" style year headers, and two-day meeting ranges like
# "January 27-28" (the decision — and the date that matters — is the 2nd day).
# Targeting the DD-DD range specifically avoids picking up single-day "Minutes"
# release dates elsewhere on the page.
_FOMC_YEAR_RE = re.compile(r"(20\d\d)\s+FOMC", re.IGNORECASE)
_FOMC_MEETING_RE = re.compile(rf"({_MONTH_NAMES})\s+\d{{1,2}}\s*[-–/]\s*(\d{{1,2}})", re.IGNORECASE)

# ECB dates render as "5 February 2026" / "5-6 February 2026" (take the last day).
_ECB_DATE_RE = re.compile(rf"(?:\d{{1,2}}\s*[-–]\s*)?(\d{{1,2}})\s+({_MONTH_NAMES})\s+(20\d\d)", re.IGNORECASE)


def _plausible(dates: list[date], *, minimum: int = 4) -> list[date]:
    """Accept a scrape only if it yields enough dates in a sane year window."""
    this_year = date.today().year
    kept = sorted({d for d in dates if this_year - 1 <= d.year <= this_year + 2})
    return kept if len(kept) >= minimum else []


def _fetch(url: str) -> str | None:
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=_REQUEST_TIMEOUT)
        resp.raise_for_status()
        return resp.text
    except requests.RequestException:
        return None


def parse_fomc(html: str) -> list[date]:
    """Extract FOMC decision dates from the Fed calendar HTML (each meeting
    assigned to the most recent preceding year header)."""
    year_markers = [(m.start(), int(m.group(1))) for m in _FOMC_YEAR_RE.finditer(html)]
    dates = []
    for match in _FOMC_MEETING_RE.finditer(html):
        preceding = [year for pos, year in year_markers if pos < match.start()]
        if not preceding:
            continue
        month = _MONTHS[match.group(1).lower()]
        day = int(match.group(2))
        try:
            dates.append(date(preceding[-1], month, day))
        except ValueError:
            continue
    return _plausible(dates)


def parse_ecb(html: str) -> list[date]:
    """Extract ECB meeting dates from the calendar HTML (last day of any range)."""
    dates = []
    for match in _ECB_DATE_RE.finditer(html):
        day, month_name, year = int(match.group(1)), match.group(2).lower(), int(match.group(3))
        try:
            dates.append(date(year, _MONTHS[month_name], day))
        except ValueError:
            continue
    return _plausible(dates)


def fetch_fomc_dates() -> list[date]:
    """Scraped FOMC decision dates, or [] (caller falls back to constants)."""
    html = _fetch(FOMC_CALENDAR_URL)
    return parse_fomc(html) if html else []


def fetch_ecb_dates() -> list[date]:
    """Scraped ECB meeting dates, or [] (caller falls back to constants)."""
    html = _fetch(ECB_CALENDAR_URL)
    return parse_ecb(html) if html else []
