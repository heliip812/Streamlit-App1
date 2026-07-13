import pandas as pd

from data.dtcc import normalize


def _raw_row(**overrides):
    row = {
        "Action type": "NEWT",
        "Asset Class": "CR",
        "Execution Timestamp": "2026-07-10T20:27:14Z",
        "Effective Date": "2026-07-10",
        "Expiration Date": "2031-07-10",
        "Cleared": "Y",
        "Block trade election indicator": "FALSE",
        "Notional amount-Leg 1": "10,000,000",
        "Notional amount-Leg 2": "10,000,000",
        "Notional currency-Leg 1": "USD",
        "Notional currency-Leg 2": "USD",
        "Fixed rate-Leg 1": None,
        "Spread-Leg 1": "0.0125",
        "Price": None,
        "UPI Underlier Name": "CDX.NA.IG.40",
    }
    row.update(overrides)
    return row


def test_normalize_parses_notional_and_flags_index_trades():
    df = pd.DataFrame([_raw_row(), _raw_row(**{"UPI Underlier Name": "SOME CORP", "Action type": "CORR"})])

    out = normalize(df)

    assert out.loc[0, "notional_usd_approx"] == 10_000_000
    assert out.loc[0, "is_index"] is True or bool(out.loc[0, "is_index"])
    assert bool(out.loc[1, "is_index"]) is False
    assert bool(out.loc[0, "is_new_trade"]) is True
    assert bool(out.loc[1, "is_new_trade"]) is False


def test_normalize_strips_capped_notional_marker():
    df = pd.DataFrame([_raw_row(**{"Notional amount-Leg 1": "650,000,000+"})])

    out = normalize(df)

    assert out.loc[0, "notional_usd_approx"] == 650_000_000
    assert bool(out.loc[0, "is_capped_notional"]) is True


def test_normalize_handles_empty_frame():
    out = normalize(pd.DataFrame())
    assert out.empty


def test_normalize_excludes_masked_notional_sentinel():
    df = pd.DataFrame([_raw_row(**{"Notional amount-Leg 1": "99,999,999,999,999,999,999.99999"})])

    out = normalize(df)

    assert pd.isna(out.loc[0, "notional_usd_approx"])
    assert bool(out.loc[0, "is_notional_masked"]) is True


def test_normalize_uses_usd_leg_for_cross_currency_trade():
    # e.g. an IDR/USD FX swap: leg 1 notional is in IDR (huge face value),
    # leg 2 is the economically-equivalent USD amount.
    df = pd.DataFrame(
        [
            _raw_row(
                **{
                    "Notional amount-Leg 1": "360,000,000,000",
                    "Notional currency-Leg 1": "IDR",
                    "Notional amount-Leg 2": "19,891,425",
                    "Notional currency-Leg 2": "USD",
                }
            )
        ]
    )

    out = normalize(df)

    assert out.loc[0, "notional_usd_approx"] == 19_891_425
    assert out.loc[0, "notional_local"] == 360_000_000_000


def test_normalize_excludes_same_currency_non_usd_trade_from_usd_total():
    df = pd.DataFrame(
        [
            _raw_row(
                **{
                    "Notional amount-Leg 1": "5,000,000",
                    "Notional currency-Leg 1": "EUR",
                    "Notional amount-Leg 2": "5,000,000",
                    "Notional currency-Leg 2": "EUR",
                }
            )
        ]
    )

    out = normalize(df)

    assert pd.isna(out.loc[0, "notional_usd_approx"])
    assert out.loc[0, "notional_local"] == 5_000_000
