from datetime import date

import policy_model as pm


def test_taylor_star_adds_weighted_gaps():
    # r* = 3.0 + 0.5*(3-2) + 0.5*(4.5-4.0) = 3.0 + 0.5 + 0.25 = 3.75
    star = pm.taylor_star(3.0, 4.0, 4.5, inflation_target=2.0, neutral=3.0, a=0.5, b=0.5)
    assert round(star, 3) == 3.75


def test_taylor_star_ignores_missing_inputs():
    # Missing inflation and unemployment -> both gaps zero -> just the neutral.
    star = pm.taylor_star(float("nan"), float("nan"), float("nan"), inflation_target=2.0, neutral=2.5, a=1.0, b=1.0)
    assert star == 2.5


def test_momentum_is_bounded_and_signed():
    # Big re-acceleration (3m >> yoy) is hawkish but capped at +8.
    assert pm.momentum_adjustment(10.0, 2.0, float("nan")) == 8.0
    # Tight financial conditions (positive NFCI) are dovish (negative tilt).
    assert pm.momentum_adjustment(float("nan"), float("nan"), 1.0) == -5.0


def test_probabilities_sum_to_one_and_lean_correctly():
    dovish = pm.meeting_probabilities(-60.0, inertia=0.25)  # r* well below r
    hawkish = pm.meeting_probabilities(60.0, inertia=0.25)  # r* well above r

    assert round(dovish["p_hike"] + dovish["p_hold"] + dovish["p_cut"], 6) == 1.0
    assert dovish["p_cut"] > dovish["p_hike"]
    assert hawkish["p_hike"] > hawkish["p_cut"]


def test_model_path_walks_toward_r_star():
    meetings = [date(2026, 9, 16), date(2026, 10, 28), date(2026, 12, 9)]
    # Inflation above target pushes r* up to ~4.5; from 3.5 the path should rise.
    macro = {"core_infl_yoy": 4.0, "unemployment": 4.0, "nairu": 4.5}
    path = pm.model_path(meetings, current_rate=3.5, macro=macro, inflation_target=2.0, neutral=3.0, a=0.5, b=0.5, inertia=0.5)

    assert list(path["meeting"]) == meetings
    assert path["r_star"].iloc[0] > 3.5  # hawkish gap
    assert path["model_rate"].iloc[-1] >= path["model_rate"].iloc[0]  # rising path
    # steps are whole 25bp increments
    assert all(step % 25 == 0 for step in path["model_step_bp"])
