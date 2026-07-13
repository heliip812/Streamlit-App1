"""DTCC Swap Data Repository ingestion: fetching (client.py) + cleaning (normalize.py).

Re-exported here so callers keep writing `from data import dtcc` /
`dtcc.get_recent_trades(...)` regardless of which submodule an implementation
detail lives in.
"""

from .client import fetch_day, fetch_recent
from .normalize import get_recent_trades, normalize

__all__ = ["fetch_day", "fetch_recent", "get_recent_trades", "normalize"]
