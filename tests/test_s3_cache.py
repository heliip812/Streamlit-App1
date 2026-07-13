from datetime import date
from unittest.mock import Mock, patch

from data import s3_cache


def test_read_day_is_noop_without_aws_secrets():
    assert s3_cache.read_day("CREDITS", date(2026, 7, 9)) is None


def test_write_day_is_noop_without_aws_secrets():
    import pandas as pd

    # Should not raise even though there's nowhere to write to.
    s3_cache.write_day("CREDITS", date(2026, 7, 9), pd.DataFrame({"a": [1]}))


def test_health_check_reports_unconfigured():
    ok, message = s3_cache.health_check()
    assert ok is False
    assert "No [aws] secrets" in message


def test_health_check_reports_client_init_failure():
    cfg = {"access_key_id": "x", "secret_access_key": "y", "region_name": "us-east-1", "bucket_name": "b"}
    with patch("data.s3_cache._config", return_value=cfg), patch("data.s3_cache._client", return_value=None):
        ok, message = s3_cache.health_check()
    assert ok is False
    assert "failed to initialize" in message


def test_health_check_reports_success_on_round_trip():
    cfg = {"access_key_id": "x", "secret_access_key": "y", "region_name": "us-east-1", "bucket_name": "my-bucket"}
    client = Mock()
    client.get_object.return_value = {"Body": Mock(read=Mock(return_value=b"ok"))}
    with patch("data.s3_cache._config", return_value=cfg), patch("data.s3_cache._client", return_value=client):
        ok, message = s3_cache.health_check()
    assert ok is True
    assert "my-bucket" in message
    client.put_object.assert_called_once()


def test_health_check_reports_round_trip_failure():
    cfg = {"access_key_id": "x", "secret_access_key": "y", "region_name": "us-east-1", "bucket_name": "my-bucket"}
    client = Mock()
    client.put_object.side_effect = Exception("Access Denied")
    with patch("data.s3_cache._config", return_value=cfg), patch("data.s3_cache._client", return_value=client):
        ok, message = s3_cache.health_check()
    assert ok is False
    assert "Access Denied" in message
