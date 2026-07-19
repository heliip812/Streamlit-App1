"""SQLite snapshot store — the memory that makes the signals page dynamic.

Every refresh writes today's implied path, model path, divergences, signals
and FX spots. History enables day-over-day repricing, divergence z-scores,
signal-flip detection, and eventually backtests of the signal rules.

The DB lives in var/snapshots.db (this repo's data/ directory is a code
package, so the brief's data/snapshots.db relocates; var/ is gitignored).
CB_SNAPSHOT_DB overrides the path (used by tests). An S3 pull runs lazily on
first connection per process (see data/s3sync.py) so ephemeral disks —
Streamlit Cloud restarts included — start with the accumulated history.
Single-writer rule: only the refresh job (button or cron) writes; page reads
are passive.
"""

from __future__ import annotations

import os
import sqlite3
from datetime import date
from pathlib import Path

import pandas as pd

_pulled = False


def db_path() -> Path:
    env = os.environ.get("CB_SNAPSHOT_DB")
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[1] / "var" / "snapshots.db"


def _maybe_pull() -> None:
    global _pulled
    if _pulled:
        return
    _pulled = True
    try:
        from . import s3sync

        if s3sync.enabled():
            s3sync.pull_db(db_path())
    except Exception:
        pass


def _conn() -> sqlite3.Connection:
    _maybe_pull()
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(path)
    c.execute(
        """CREATE TABLE IF NOT EXISTS paths (
        asof TEXT, bank TEXT, decision TEXT,
        implied_rate REAL, model_rate REAL, divergence_bp REAL,
        step_bp REAL, method TEXT,
        PRIMARY KEY (asof, bank, decision))"""
    )
    c.execute(
        """CREATE TABLE IF NOT EXISTS signals (
        asof TEXT, name TEXT, signal TEXT, value_bp REAL, conviction INT,
        PRIMARY KEY (asof, name))"""
    )
    c.execute("""CREATE TABLE IF NOT EXISTS fx (asof TEXT, pair TEXT, spot REAL, PRIMARY KEY (asof, pair))""")
    return c


def save_paths(asof: date, bank: str, df: pd.DataFrame) -> None:
    if df is None or df.empty:
        return
    with _conn() as c:
        for _, r in df.iterrows():
            c.execute(
                "INSERT OR REPLACE INTO paths VALUES (?,?,?,?,?,?,?,?)",
                (
                    str(asof), bank, str(r.get("decision")),
                    _num(r.get("implied_rate")), _num(r.get("model_rate")),
                    _num(r.get("divergence_bp")), _num(r.get("step_bp")),
                    r.get("method", ""),
                ),
            )


def _num(x):
    return None if x is None or (isinstance(x, float) and pd.isna(x)) else float(x)


def save_signal(asof: date, name: str, signal: str, value_bp: float, conviction: int) -> None:
    with _conn() as c:
        c.execute("INSERT OR REPLACE INTO signals VALUES (?,?,?,?,?)", (str(asof), name, signal, _num(value_bp), int(conviction)))


def save_fx(asof: date, pair: str, spot: float) -> None:
    with _conn() as c:
        c.execute("INSERT OR REPLACE INTO fx VALUES (?,?,?)", (str(asof), pair, float(spot)))


def load_paths(bank: str | None = None) -> pd.DataFrame:
    with _conn() as c:
        q = "SELECT * FROM paths" + (" WHERE bank=?" if bank else "")
        df = pd.read_sql(q, c, params=(bank,) if bank else None)
    for col in ("asof", "decision"):
        if col in df:
            df[col] = pd.to_datetime(df[col])
    return df


def load_signals() -> pd.DataFrame:
    with _conn() as c:
        df = pd.read_sql("SELECT * FROM signals", c)
    if "asof" in df:
        df["asof"] = pd.to_datetime(df["asof"])
    return df


def load_fx() -> pd.DataFrame:
    with _conn() as c:
        df = pd.read_sql("SELECT * FROM fx", c)
    if "asof" in df:
        df["asof"] = pd.to_datetime(df["asof"])
    return df


def divergence_history(bank: str, horizon_meetings: int = 3) -> pd.Series:
    """Daily mean divergence over the front N meetings, for z-scoring."""
    df = load_paths(bank).dropna(subset=["divergence_bp"])
    if df.empty:
        return pd.Series(dtype=float)
    df = df.sort_values(["asof", "decision"])
    return df.groupby("asof").apply(lambda g: g.head(horizon_meetings)["divergence_bp"].mean(), include_groups=False)


def zscore(series: pd.Series, window: int = 60, min_obs: int = 15) -> float | None:
    """Latest value's z vs its own rolling window; None until enough history
    (the UI shows 'n/a' rather than a meaningless early z)."""
    s = series.dropna()
    if len(s) < min_obs:
        return None
    tail = s.tail(window)
    sd = tail.std()
    return float((s.iloc[-1] - tail.mean()) / sd) if sd and sd > 0 else None
