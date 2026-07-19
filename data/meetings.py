"""Meeting calendars with decision AND effective dates.

The effective date is what matters for futures deconvolution — a contract
averaging the overnight rate only feels the new rate from the day the change
takes effect, not the day it is announced.

Conventions (per the CB-dashboard brief):
- fed: target-range change is effective the next business day after the
  decision (per FOMC implementation notes).
- ecb: rate changes take effect the following Wednesday (first MRO
  settlement after the decision), ~6 calendar days later. Verified example:
  cut announced 5 Jun 2025 was effective 11 Jun 2025.
- boe: Bank Rate is effective immediately on the announcement day (12:00).
- boj: assumed next business day (not covered by the brief; flagged in-app).

Decision dates come from the live calendar scrape when available, else the
maintained fallback lists in constants.py; this module attaches the
effective-date convention either way. Extend/verify each December.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from .constants import (
    BOE_MEETING_DATES_FALLBACK,
    BOJ_MEETING_DATES_FALLBACK,
    ECB_MEETING_DATES_FALLBACK,
    FOMC_MEETING_DATES_FALLBACK,
)


@dataclass(frozen=True)
class Meeting:
    bank: str  # registry code ("fed", "ecb", "boe", "boj")
    decision: date  # announcement day
    effective: date  # day the new rate starts applying
    note: str = ""


def _next_business_day(d: date) -> date:
    nd = d + timedelta(days=1)
    while nd.weekday() >= 5:
        nd += timedelta(days=1)
    return nd


def _next_wednesday(d: date) -> date:
    days_ahead = (2 - d.weekday()) % 7  # Wednesday = 2
    days_ahead = 7 if days_ahead == 0 else days_ahead
    return d + timedelta(days=days_ahead)


def _same_day(d: date) -> date:
    return d


EFFECTIVE_RULES = {
    "fed": _next_business_day,
    "ecb": _next_wednesday,
    "boe": _same_day,
    "boj": _next_business_day,
}

CONVENTION_NOTES = {
    "fed": "Effective the next business day after the decision (FOMC implementation note).",
    "ecb": "Effective the following Wednesday (first MRO settlement), ~6 days after the decision.",
    "boe": "Effective immediately on the announcement day (12:00 London).",
    "boj": "Assumed effective the next business day (convention not covered by the brief — verify).",
}

# Curated notes for known dates (SEP/dot-plot meetings, tentative 2027 rows).
_NOTES = {
    ("fed", date(2026, 9, 16)): "SEP/dot plot",
    ("fed", date(2026, 12, 9)): "SEP/dot plot",
    ("ecb", date(2026, 9, 10)): "projections",
    ("ecb", date(2026, 12, 17)): "projections",
    ("boe", date(2026, 7, 30)): "MPR + press conf",
    ("boe", date(2026, 11, 5)): "MPR + press conf",
}

_FALLBACK_DECISIONS = {
    "fed": FOMC_MEETING_DATES_FALLBACK,
    "ecb": ECB_MEETING_DATES_FALLBACK,
    "boe": BOE_MEETING_DATES_FALLBACK,
    "boj": BOJ_MEETING_DATES_FALLBACK,
}


def effective_date(bank_code: str, decision: date) -> date:
    return EFFECTIVE_RULES.get(bank_code, _next_business_day)(decision)


def to_meetings(bank_code: str, decisions: list[date]) -> list[Meeting]:
    out = []
    for d in sorted(decisions):
        note = _NOTES.get((bank_code, d), "tentative" if d.year >= 2027 else "")
        out.append(Meeting(bank_code, d, effective_date(bank_code, d), note))
    return out


def meetings_for(bank_code: str, scraped_decisions: list[date] | None = None, asof: date | None = None) -> list[Meeting]:
    """Upcoming meetings from scraped decisions (if any are upcoming) else the
    maintained fallback list, with effective dates attached."""
    asof = asof or date.today()
    scraped_upcoming = [d for d in (scraped_decisions or []) if d >= asof]
    decisions = scraped_upcoming or [d for d in _FALLBACK_DECISIONS.get(bank_code, []) if d >= asof]
    return to_meetings(bank_code, decisions)
