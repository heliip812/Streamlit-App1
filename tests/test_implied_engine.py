from datetime import date

import pandas as pd

import implied_engine as eng
from data.meetings import Meeting


def _mt(bank, decision, effective):
    return Meeting(bank, decision, effective, "")


def test_adjust_ff_converts_price_and_basis():
    raw = pd.DataFrame({"contract_month": ["2026-09"], "raw_price": [95.70]})
    adj = eng.adjust_ff(raw, basis_bp=-4.5)
    assert round(adj["implied_avg_effr"].iloc[0], 3) == 4.30
    # policy = EFFR - basis; basis -4.5bp -> policy 4.5bp ABOVE the EFFR print
    assert round(adj["implied_avg_policy"].iloc[0], 4) == 4.345


def test_fed_same_month_deconvolution_recovers_r_post():
    # Sep 2026 (30 days), effective 17 Sep: avg = r_pre*16/30 + r_post*14/30.
    r_pre, r_post = 4.30, 4.05
    avg = r_pre * 16 / 30 + r_post * 14 / 30
    adj = pd.DataFrame({"contract_month": ["2026-09"], "implied_avg_policy": [avg]})
    mts = [_mt("fed", date(2026, 9, 16), date(2026, 9, 17))]

    path = eng.path_from_monthly_avg(adj, current_policy=r_pre, meetings=mts)

    assert round(path["implied_rate"].iloc[0], 3) == 4.05
    assert path["method"].iloc[0] == "same-month deconvolution"
    assert path["step_bp"].iloc[0] == -25.0
    assert path["direction"].iloc[0] == "cut"
    assert path["prob_25bp_move"].iloc[0] == 1.0


def test_fed_late_month_meeting_uses_next_month_proxy():
    # Effective 29 Sep leaves 2/30 post-window (<10%) -> read October's
    # meeting-free contract, which embeds the new rate for its full month.
    adj = pd.DataFrame(
        {"contract_month": ["2026-09", "2026-10"], "implied_avg_policy": [4.28, 4.05]}
    )
    mts = [_mt("fed", date(2026, 9, 28), date(2026, 9, 29))]

    path = eng.path_from_monthly_avg(adj, current_policy=4.30, meetings=mts)

    assert path["method"].iloc[0] == "next-month proxy"
    assert round(path["implied_rate"].iloc[0], 3) == 4.05


def test_fed_meeting_free_month_reanchors_running_rate():
    # August has no meeting: its contract average replaces the running rate
    # before September's solve (self-correcting basis drift).
    r_post = 4.00
    sep_avg = 4.20 * 16 / 30 + r_post * 14 / 30
    adj = pd.DataFrame({"contract_month": ["2026-08", "2026-09"], "implied_avg_policy": [4.20, sep_avg]})
    mts = [_mt("fed", date(2026, 9, 16), date(2026, 9, 17))]

    path = eng.path_from_monthly_avg(adj, current_policy=4.33, meetings=mts)

    assert round(path["implied_rate"].iloc[0], 3) == 4.00  # anchored at 4.20, not 4.33


def test_ecb_quarterly_equal_step_fit_recovers_single_cut():
    # Q3 contract (Jul-Sep 2026, 92 days), one meeting effective 29 Jul:
    # avg = r_run*(28/92) + (r_run+step)*(64/92).
    r_run, step = 2.00, -0.25
    avg = r_run * 28 / 92 + (r_run + step) * 64 / 92
    adj = pd.DataFrame({"contract_month": ["2026-07"], "implied_avg_policy": [avg]})
    mts = [_mt("ecb", date(2026, 7, 23), date(2026, 7, 29))]

    path = eng.path_from_quarterly_avg(adj, current_policy=r_run, meetings=mts)

    assert round(path["implied_rate"].iloc[0], 3) == 1.75
    assert path["method"].iloc[0] == "quarterly equal-step fit"


def test_ecb_two_meetings_in_quarter_share_equal_steps():
    # Two meetings in one quarter cannot be separately identified; the fit
    # assumes equal steps, so both rows carry the same step.
    r_run = 2.00
    q_start, e1, e2, q_end = date(2026, 10, 1), date(2026, 11, 4), date(2026, 12, 23), date(2027, 1, 1)
    n = (q_end - q_start).days
    w = [(e1 - q_start).days / n, (e2 - e1).days / n, (q_end - e2).days / n]
    step = -0.25
    avg = w[0] * r_run + w[1] * (r_run + step) + w[2] * (r_run + 2 * step)
    adj = pd.DataFrame({"contract_month": ["2026-10"], "implied_avg_policy": [avg]})
    mts = [_mt("ecb", date(2026, 10, 29), e1), _mt("ecb", date(2026, 12, 17), e2)]

    path = eng.path_from_quarterly_avg(adj, current_policy=r_run, meetings=mts)

    assert len(path) == 2
    assert round(path["step_bp"].iloc[0], 1) == -25.0
    assert round(path["implied_rate"].iloc[1], 3) == 1.50


def test_boe_forward_windowing_averages_between_effectives():
    # Piecewise-flat forward curve: 4.0 out to 0.15y, then 3.75. A meeting
    # effective ~0.16y out should read ~3.75 from its post-window.
    asof = date(2026, 7, 20)
    adj = pd.DataFrame(
        {
            "horizon_years": [0.0, 0.15, 0.1501, 1.0],
            "fwd_policy": [4.0, 4.0, 3.75, 3.75],
        }
    )
    effective = date(2026, 9, 17)  # ~0.16y after asof
    mts = [Meeting("boe", date(2026, 9, 17), effective, "")]

    path = eng.path_from_forward_curve(adj, current_policy=4.0, meetings=mts, asof=asof)

    assert round(path["implied_rate"].iloc[0], 2) == 3.75
    assert path["method"].iloc[0] == "OIS forward windowing"
    assert path["step_bp"].iloc[0] == -25.0


def test_parse_estr_csv_accepts_contract_price_and_rejects_garbage():
    import io

    good = io.StringIO("contract,price\n2026-09,98.15\n2026-12,98.30\n")
    df = eng.parse_estr_futures_csv(good)
    assert list(df["contract_month"]) == ["2026-09", "2026-12"]

    assert eng.parse_estr_futures_csv(io.StringIO("nonsense,columns\n1,2\n")) is None


def test_curve_fallback_path_reads_effective_dates():
    curve = pd.DataFrame({"horizon_years": [0.0, 0.5, 1.0], "rate": [4.33, 4.0, 3.8]})
    asof = date(2026, 7, 20)
    mts = [_mt("fed", date(2026, 9, 16), date(2026, 9, 17))]

    path = eng.path_from_yield_curve(curve, 4.33, mts, asof, source_label="curve forward (proxy)")

    assert len(path) == 1
    assert path["method"].iloc[0] == "curve forward (proxy)"
    assert 3.8 < path["implied_rate"].iloc[0] < 4.33


def test_meeting_table_reports_deconvolution_weights():
    mts = [_mt("fed", date(2026, 9, 16), date(2026, 9, 17))]
    table = eng.meeting_table(mts)
    assert table["lag_days"].iloc[0] == 1
    assert round(table["pre_weight"].iloc[0], 3) == round(16 / 30, 3)
    assert round(table["post_weight"].iloc[0], 3) == round(14 / 30, 3)
