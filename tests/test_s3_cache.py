from datetime import date

from data import s3_cache


def test_read_day_is_noop_without_aws_secrets():
    assert s3_cache.read_day("CREDITS", date(2026, 7, 9)) is None


def test_write_day_is_noop_without_aws_secrets():
    import pandas as pd

    # Should not raise even though there's nowhere to write to.
    s3_cache.write_day("CREDITS", date(2026, 7, 9), pd.DataFrame({"a": [1]}))
