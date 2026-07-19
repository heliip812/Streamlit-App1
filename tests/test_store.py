from datetime import date

import pandas as pd
import pytest

from data import store


@pytest.fixture(autouse=True)
def _tmp_db(tmp_path, monkeypatch):
    monkeypatch.setenv("CB_SNAPSHOT_DB", str(tmp_path / "snapshots.db"))
    # The lazy S3 pull is per-process; force it to a no-op for tests.
    monkeypatch.setattr(store, "_pulled", True)
    yield


def _path_df(divs):
    return pd.DataFrame(
        {
            "decision": [date(2026, 9, 16), date(2026, 10, 28), date(2026, 12, 9), date(2027, 1, 27)][: len(divs)],
            "implied_rate": [4.0] * len(divs),
            "model_rate": [4.0 + d / 100 for d in divs],
            "divergence_bp": divs,
            "step_bp": [-25.0] * len(divs),
            "method": ["same-month deconvolution"] * len(divs),
        }
    )


def test_paths_roundtrip_and_method_preserved():
    store.save_paths(date(2026, 7, 20), "fed", _path_df([12.0, 8.0, 5.0]))
    df = store.load_paths("fed")
    assert len(df) == 3
    assert set(df["method"]) == {"same-month deconvolution"}


def test_divergence_history_means_front_three():
    # Four meetings saved; history must average only the front 3 per asof.
    store.save_paths(date(2026, 7, 20), "fed", _path_df([30.0, 20.0, 10.0, 100.0]))
    store.save_paths(date(2026, 7, 21), "fed", _path_df([15.0, 15.0, 15.0, 100.0]))
    h = store.divergence_history("fed")
    assert len(h) == 2
    assert round(h.iloc[0], 1) == 20.0  # (30+20+10)/3, 100 excluded
    assert round(h.iloc[1], 1) == 15.0


def test_zscore_requires_min_observations():
    short = pd.Series(range(10), dtype=float)
    assert store.zscore(short) is None
    longer = pd.Series([0.0] * 19 + [10.0])
    z = store.zscore(longer)
    assert z is not None and z > 2


def test_signals_and_fx_roundtrip():
    store.save_signal(date(2026, 7, 20), "fed_outright", "NEUTRAL", 3.0, 0)
    store.save_signal(date(2026, 7, 21), "fed_outright", "Pay rates", 14.0, 1)
    store.save_fx(date(2026, 7, 21), "EUR/USD", 1.09)

    sigs = store.load_signals().sort_values("asof")
    assert list(sigs["signal"]) == ["NEUTRAL", "Pay rates"]  # flip detectable
    fx = store.load_fx()
    assert fx["spot"].iloc[0] == 1.09
