"""Market-implied Fed policy path from 30-Day Fed Funds futures (CME 'ZQ').

Pure, dependency-light functions (pandas only, no Streamlit, no network) so
the substantive logic — turning a strip of futures prices into a per-meeting
expected policy rate and hike/cut/hold probabilities — is fully unit-tested
independently of the data source that supplies the prices.

Method (the standard CME FedWatch construction):

A 30-Day Fed Funds future for month M settles to 100 − (the average daily
effective fed funds rate, EFFR, over month M). So `100 − price` is the
market's expected *average* EFFR for that month. When a single FOMC decision
falls in month M and takes effect on day d, that month's average splits into
the days before d (at the rate prevailing entering the month) and the days
from d onward (at the post-decision rate):

    implied_avg = rate_before · (n1/N) + rate_after · (n2/N)

with N days in the month, n1 days before the effective date and n2 = N − n1
after. Solving for `rate_after` recovers the market-implied rate the meeting
is priced to leave in place; chaining meeting to meeting walks the whole
expected path forward. `step_probabilities` then splits each expected change
across the two adjacent 25bp outcomes that bracket it.

Everything here is an approximation of a live curve, not a live curve: it
uses the range/EFFR anchor the caller supplies, assumes one decision per
contract month, and inherits whatever staleness the delayed futures feed has.
"""

from __future__ import annotations

import calendar
import math
from dataclasses import dataclass
from datetime import date, timedelta

import pandas as pd


def implied_rates(futures: pd.DataFrame) -> pd.DataFrame:
    """Attach `implied_rate` (= 100 − price) and a month `Period` to a strip.

    `futures` needs a `contract_month` (any month-resolvable date/timestamp)
    and a `price` column. Rows without a price are dropped; the result is
    sorted front-to-back by contract month.
    """
    out = futures.dropna(subset=["price"]).copy()
    out["implied_rate"] = 100.0 - out["price"].astype(float)
    out["contract_month"] = pd.to_datetime(out["contract_month"]).dt.to_period("M")
    return out.sort_values("contract_month").reset_index(drop=True)


@dataclass
class MeetingExpectation:
    meeting_date: date
    rate_before: float  # implied rate prevailing entering the meeting
    rate_after: float  # implied rate the meeting is priced to leave in place
    change: float  # rate_after − rate_before, in rate points (e.g. -0.25)


def meeting_expectations(
    futures: pd.DataFrame,
    meeting_dates: list[date],
    current_rate: float,
    as_of: date | None = None,
) -> list[MeetingExpectation]:
    """Walk the implied policy rate forward across FOMC meetings.

    `current_rate` anchors the front of the path — pass the current effective
    fed funds rate (EFFR), not the range midpoint, so the first computed
    change isn't polluted by the few-bp gap between EFFR and the midpoint.
    Meetings before `as_of` are skipped. Stops once the strip runs out of
    contract months to price a meeting from, rather than extrapolating past
    the available data.

    Rate extraction prefers *adjacent meeting-free months* over the
    single-month split: a month with no meeting sits entirely at one rate,
    so month M+1's contract (when meeting-free) already equals the
    post-meeting rate directly, and month M−1's equals the rate entering the
    meeting. That avoids the tiny-denominator blow-up the intra-month split
    suffers for meetings late in a month (e.g. a decision on the 28th leaves
    only 2-3 days to divide by). The intra-month split is used only as a
    fallback when a clean neighbour isn't available.
    """
    strip = implied_rates(futures)
    by_month = dict(zip(strip["contract_month"], strip["implied_rate"]))

    meetings = sorted(meeting_dates)
    if as_of is not None:
        meetings = [m for m in meetings if m >= as_of]
    # Months whose contract's average is "contaminated" by a decision landing
    # in them — not usable as a clean constant-rate reference for a neighbour.
    meeting_months = {pd.Period(m + timedelta(days=1), freq="M") for m in meetings}

    results: list[MeetingExpectation] = []
    chained_rate = current_rate
    for meeting in meetings:
        # A new target takes effect the day after the decision, so the split
        # point within the month is the effective date, not the meeting date.
        effective = meeting + timedelta(days=1)
        period = pd.Period(effective, freq="M")
        prior, following = period - 1, period + 1

        # Rate entering the meeting: the prior month's own implied rate when
        # that month is meeting-free (a clean constant), else carry forward
        # the last post-meeting rate (or the front anchor for the first one).
        if prior in by_month and prior not in meeting_months:
            rate_before = by_month[prior]
        else:
            rate_before = chained_rate

        # Post-meeting rate: read it straight off the next month's contract
        # when that month is meeting-free; otherwise split this month.
        if following in by_month and following not in meeting_months:
            rate_after = by_month[following]
        elif period in by_month:
            days_in_month = calendar.monthrange(effective.year, effective.month)[1]
            n1 = effective.day - 1  # days at the old rate, before the effective date
            n2 = days_in_month - n1
            if n2 <= 0:
                continue
            rate_after = (by_month[period] - rate_before * (n1 / days_in_month)) / (n2 / days_in_month)
        else:
            break  # neither this month nor a clean next month is in the strip

        results.append(
            MeetingExpectation(
                meeting_date=meeting,
                rate_before=rate_before,
                rate_after=rate_after,
                change=rate_after - rate_before,
            )
        )
        chained_rate = rate_after

    return results


def step_probabilities(change: float, step: float = 0.25) -> list[tuple[float, float]]:
    """Split an expected rate change across the two adjacent `step`-sized moves.

    Returns [(move_in_rate_points, probability), ...] sorted by move, with
    probabilities summing to 1. An expected change of −0.10 becomes a 40%
    chance of a 25bp cut and a 60% chance of no change; an exact multiple of
    `step` returns a single certain outcome. This is the standard FedWatch
    simplification (only the two bracketing 25bp outcomes carry probability),
    not a full distribution over every possible move.
    """
    quotient = change / step
    lower = math.floor(quotient)
    upper = math.ceil(quotient)
    if lower == upper:
        return [(lower * step, 1.0)]
    prob_upper = quotient - lower
    prob_lower = upper - quotient
    return sorted([(lower * step, prob_lower), (upper * step, prob_upper)])
