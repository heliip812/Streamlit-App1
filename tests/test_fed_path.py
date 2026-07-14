from datetime import date

import pandas as pd

from fed_path import implied_rates, meeting_expectations, step_probabilities


def test_implied_rates_inverts_price_and_sorts():
    futures = pd.DataFrame(
        {
            "contract_month": [date(2026, 4, 1), date(2026, 3, 1)],
            "price": [95.92, 95.775],
        }
    )

    out = implied_rates(futures)

    # Sorted front-to-back, and implied_rate = 100 - price.
    assert list(out["contract_month"].astype(str)) == ["2026-03", "2026-04"]
    assert round(out.iloc[0]["implied_rate"], 3) == round(100 - 95.775, 3)


def test_meeting_expectations_recovers_a_priced_cut():
    # Construct a March contract whose implied average is exactly consistent
    # with a 25bp cut (4.33 -> 4.08) taking effect March 19 (meeting Mar 18).
    n1, n_days = 18, 31  # days before the effective date; days in March
    implied_avg = 4.33 * (n1 / n_days) + 4.08 * ((n_days - n1) / n_days)
    futures = pd.DataFrame(
        {"contract_month": [date(2026, 3, 1)], "price": [100 - implied_avg]}
    )

    result = meeting_expectations(futures, [date(2026, 3, 18)], current_rate=4.33)

    assert len(result) == 1
    assert round(result[0].rate_after, 4) == 4.08
    assert round(result[0].change, 4) == -0.25


def test_meeting_expectations_chains_rate_forward():
    # March prices a cut to 4.08; April prices no further change. April's
    # anchor must be March's *post-meeting* rate, not the original 4.33.
    march_avg = 4.33 * (18 / 31) + 4.08 * (13 / 31)
    april_avg = 4.08  # flat all month -> average is just the rate
    futures = pd.DataFrame(
        {
            "contract_month": [date(2026, 3, 1), date(2026, 4, 1)],
            "price": [100 - march_avg, 100 - april_avg],
        }
    )

    result = meeting_expectations(
        futures, [date(2026, 3, 18), date(2026, 4, 29)], current_rate=4.33
    )

    assert len(result) == 2
    assert round(result[1].rate_before, 4) == 4.08
    assert round(result[1].change, 4) == 0.0


def test_meeting_expectations_reads_clean_neighbours_for_month_end_meeting():
    # An Oct 28 decision (effective Oct 29) leaves only 3 October days at the
    # new rate — the intra-month split would be noise-amplified. With Sept and
    # Nov both meeting-free, the rate is read straight off those contracts:
    # entering rate = Sept (4.00), post rate = Nov (3.75), a clean 25bp cut,
    # regardless of what the (contaminated) October contract prints.
    futures = pd.DataFrame(
        {
            "contract_month": [date(2026, 9, 1), date(2026, 10, 1), date(2026, 11, 1)],
            "price": [96.00, 95.90, 96.25],  # implied 4.00 / 4.10(noise) / 3.75
        }
    )

    result = meeting_expectations(futures, [date(2026, 10, 28)], current_rate=4.00)

    assert len(result) == 1
    assert round(result[0].rate_before, 4) == 4.00
    assert round(result[0].rate_after, 4) == 3.75
    assert round(result[0].change, 4) == -0.25


def test_meeting_expectations_stops_beyond_the_strip():
    # Only a March contract is supplied; a later meeting can't be priced.
    march_avg = 4.33 * (18 / 31) + 4.08 * (13 / 31)
    futures = pd.DataFrame(
        {"contract_month": [date(2026, 3, 1)], "price": [100 - march_avg]}
    )

    result = meeting_expectations(
        futures, [date(2026, 3, 18), date(2026, 6, 17)], current_rate=4.33
    )

    assert len(result) == 1  # June meeting dropped, not extrapolated


def test_meeting_expectations_skips_past_meetings():
    march_avg = 4.33 * (18 / 31) + 4.08 * (13 / 31)
    futures = pd.DataFrame(
        {"contract_month": [date(2026, 3, 1)], "price": [100 - march_avg]}
    )

    result = meeting_expectations(
        futures, [date(2026, 3, 18)], current_rate=4.33, as_of=date(2026, 4, 1)
    )

    assert result == []


def test_step_probabilities_partial_cut():
    outcomes = step_probabilities(-0.10)

    assert outcomes == sorted(outcomes)  # ordered by move
    probs = dict(outcomes)
    assert round(probs[-0.25], 4) == 0.40  # 25bp cut
    assert round(probs[0.0], 4) == 0.60  # no change
    assert round(sum(probs.values()), 6) == 1.0


def test_step_probabilities_beyond_one_step():
    probs = dict(step_probabilities(-0.30))

    # Brackets a 25bp and a 50bp cut.
    assert round(probs[-0.25], 4) == 0.80
    assert round(probs[-0.50], 4) == 0.20


def test_step_probabilities_exact_multiple_is_certain():
    assert step_probabilities(-0.25) == [(-0.25, 1.0)]
    assert step_probabilities(0.0) == [(0.0, 1.0)]
