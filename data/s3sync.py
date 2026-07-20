"""S3 persistence for the snapshot store.

SQLite stays the working store (fast local queries); S3 holds the durable
copy. Pull on startup, push after each refresh — survives ephemeral disks
(Streamlit Cloud restarts) and lets a scheduled cron job be the single
writer while dashboard instances are read-only consumers.

Config, in priority order:
1. Environment (the brief's convention, works for the CLI cron job):
   CB_S3_BUCKET (required to enable), CB_S3_PREFIX (default cb-dashboard),
   credentials via the standard AWS chain (env keys / ~/.aws / IAM role).
2. This app's existing Streamlit [aws] secrets (so the deployed app needs no
   new configuration beyond a `snapshots_bucket` key there): bucket from
   `snapshots_bucket`, credentials from the same keys data/s3_cache.py uses.

Minimal IAM: Get/Put/HeadObject on the prefix. Suggested lifecycle rule:
expire backups/ after 90 days.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

DB_KEY = "snapshots.db"


def _secrets_cfg():
    try:
        import streamlit as st

        aws = st.secrets.get("aws")
        if aws and aws.get("snapshots_bucket"):
            return dict(aws)
    except Exception:
        pass
    return None


def _cfg() -> dict | None:
    bucket = os.environ.get("CB_S3_BUCKET")
    if bucket:
        return {"bucket": bucket, "prefix": os.environ.get("CB_S3_PREFIX", "cb-dashboard").strip("/")}
    secrets = _secrets_cfg()
    if secrets:
        return {
            "bucket": secrets["snapshots_bucket"],
            "prefix": secrets.get("snapshots_prefix", "cb-dashboard").strip("/"),
            # same key names the existing [aws] DTCC-cache secrets use
            "region": secrets.get("region_name") or secrets.get("region"),
            "access_key": secrets.get("access_key_id"),
            "secret_key": secrets.get("secret_access_key"),
        }
    return None


def enabled() -> bool:
    return _cfg() is not None


def _client(cfg: dict):
    import boto3

    if cfg.get("access_key"):
        return boto3.client(
            "s3",
            region_name=cfg.get("region"),
            aws_access_key_id=cfg["access_key"],
            aws_secret_access_key=cfg["secret_key"],
        )
    return boto3.client("s3")


def _key(cfg: dict) -> str:
    return f"{cfg['prefix']}/{DB_KEY}"


def remote_mtime() -> datetime | None:
    cfg = _cfg()
    if not cfg:
        return None
    try:
        head = _client(cfg).head_object(Bucket=cfg["bucket"], Key=_key(cfg))
        return head["LastModified"]
    except Exception:
        return None


def should_pull(local: Path) -> bool:
    """Pull when the S3 copy exists and is newer than (or replaces a missing)
    local file; 60s clock-skew tolerance."""
    rm = remote_mtime()
    if rm is None:
        return False
    if not local.exists():
        return True
    lm = datetime.fromtimestamp(local.stat().st_mtime, tz=timezone.utc)
    return (rm - lm).total_seconds() > 60


def pull_db(local: Path) -> bool:
    cfg = _cfg()
    if not cfg or not should_pull(local):
        return False
    local.parent.mkdir(parents=True, exist_ok=True)
    tmp = local.with_suffix(".db.tmp")
    try:
        _client(cfg).download_file(cfg["bucket"], _key(cfg), str(tmp))
        tmp.replace(local)  # atomic
        return True
    except Exception:
        tmp.unlink(missing_ok=True)
        return False


def push_db(local: Path) -> bool:
    cfg = _cfg()
    if not cfg or not local.exists():
        return False
    try:
        client = _client(cfg)
        client.upload_file(str(local), cfg["bucket"], _key(cfg))
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
        client.upload_file(str(local), cfg["bucket"], f"{cfg['prefix']}/backups/snapshots-{stamp}.db")
        return True
    except Exception:
        return False


def status() -> str:
    cfg = _cfg()
    if not cfg:
        return "S3 sync: disabled (set CB_S3_BUCKET or [aws].snapshots_bucket to enable)"
    rm = remote_mtime()
    tail = f"last remote write {rm:%Y-%m-%d %H:%M UTC}" if rm else "no remote copy yet"
    return f"S3 sync: s3://{cfg['bucket']}/{cfg['prefix']}/ · {tail}"
