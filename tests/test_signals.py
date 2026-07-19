from datetime import date

import pandas as pd

import signals


def _merged(divs):
    """Build a merged frame with the given per-meeting divergences (bp)."""
    meetings = [date(2026, 9, 16), date(2026, 10, 28), date(2026, 12, 9)][: len(divs)]
    return pd.DataFrame({"meeting": meetings, "implied_rate": [4.0] * len(divs), "model_rate": [4.0 + d / 100 for d in divs], "divergence_bp": divs})


def test_merge_paths_computes_divergence():
    market = pd.DataFrame({"meeting": [date(2026, 9, 16)], "implied_rate": [4.00]})
    model = pd.DataFrame({"meeting": [date(2026, 9, 16)], "model_rate": [4.20]})

    merged = signals.merge_paths(market, model)

    assert round(merged["divergence_bp"].iloc[0], 1) == 20.0  # model 20bp more hawkish


def test_outright_hawkish_says_pay():
    out = signals.outright_signal(_merged([30, 28, 26]))
    assert out["conviction"] == 2  # >25bp average
    assert "Pay rates" in out["signal"]


def test_outright_dovish_says_receive():
    out = signals.outright_signal(_merged([-12, -15, -14]))
    assert out["conviction"] == 1
    assert "Receive rates" in out["signal"]


def test_outright_small_divergence_is_neutral():
    out = signals.outright_signal(_merged([3, -2, 4]))
    assert out["signal"] == "NEUTRAL"
    assert out["conviction"] == 0


def test_spread_signal_widener_and_direction():
    out = signals.spread_signal("fed", 30.0, "ecb", 5.0)  # rel +25 (not >25 -> conviction 1)
    assert "Pay FED vs receive ECB" in out["signal"]
    assert out["conviction"] == 1


def test_fx_signal_longs_the_hawkish_currency():
    out = signals.fx_signal("fed", 40.0, "ecb", 5.0)  # rel +35 -> strong, long USD
    assert out["pair"] == "EUR/USD"
    assert "Long USD / short EUR" in out["signal"]
    assert out["conviction"] == 2


def test_fx_signal_none_on_missing_divergence():
    out = signals.fx_signal("fed", float("nan"), "boj", 10.0)
    assert out["signal"] == "NO DATA"


def test_build_signal_table_covers_all_pairs():
    table = signals.build_signal_table({"fed": 30.0, "ecb": 5.0, "boe": -20.0})

    # 3 banks -> 3 pairs -> 6 rows (a spread + an FX row each).
    assert len(table) == 6
    assert set(table["type"]) == {"Rates spread", "FX"}
