"""Optional S3-backed cache for parsed DTCC daily slices.

Purely additive: if AWS isn't configured (no `[aws]` section in
`.streamlit/secrets.toml`), every function here is a silent no-op and the
app falls back to fetching straight from DTCC every time, exactly as
before. This means the app works with zero AWS setup, and gets faster/
lighter automatically once a bucket is configured.

DTCC's daily files are immutable once published, so a cached day never
goes stale — there's no TTL here, only a cache-or-not decision at write
time (see callers: only definitively-fetched days are written, not ones
that failed due to a transient network error).
"""

from __future__ import annotations

import io
from datetime import date
from functools import lru_cache

import pandas as pd
import streamlit as st


def _config() -> dict | None:
    # st.secrets raises StreamlitSecretNotFoundError (not just a missing-key
    # KeyError) when no secrets.toml exists at all, which is the default,
    # zero-AWS-setup state for this app.
    try:
        aws = st.secrets.get("aws")
    except Exception:
        return None
    if not aws:
        return None
    required = ("access_key_id", "secret_access_key", "region_name", "bucket_name")
    if not all(k in aws for k in required):
        return None
    return dict(aws)


@lru_cache(maxsize=1)
def _client():
    cfg = _config()
    if cfg is None:
        return None
    try:
        import boto3

        return boto3.client(
            "s3",
            aws_access_key_id=cfg["access_key_id"],
            aws_secret_access_key=cfg["secret_access_key"],
            region_name=cfg["region_name"],
        )
    except Exception:
        return None


def _key(asset_class_code: str, day: date) -> str:
    return f"dtcc/{asset_class_code}/{day.isoformat()}.parquet"


def read_day(asset_class_code: str, day: date) -> pd.DataFrame | None:
    """Return a cached day's frame, or None on any cache miss/failure."""
    client = _client()
    cfg = _config()
    if client is None or cfg is None:
        return None
    try:
        resp = client.get_object(Bucket=cfg["bucket_name"], Key=_key(asset_class_code, day))
        return pd.read_parquet(io.BytesIO(resp["Body"].read()))
    except Exception:
        return None


def write_day(asset_class_code: str, day: date, df: pd.DataFrame) -> None:
    """Best-effort write-through; failures are silent so caching is never load-bearing."""
    client = _client()
    cfg = _config()
    if client is None or cfg is None:
        return
    try:
        buf = io.BytesIO()
        df.to_parquet(buf, index=False)
        buf.seek(0)
        client.put_object(Bucket=cfg["bucket_name"], Key=_key(asset_class_code, day), Body=buf.getvalue())
    except Exception:
        pass
