"""Raw ingestion of DTCC Swap Data Repository (SDR) public dissemination data.

DTCC publishes real, trade-level OTC derivatives data free of charge under
Dodd-Frank Part 43/45 reporting rules: one cumulative CSV (zipped) per asset
class per calendar day, containing every publicly disseminated swap trade
(price/rate, notional, counterparty-anonymized) for that day.

This module owns fetching and lightly parsing that raw data — everything
below "genuinely new trade rows, DTCC's original column names, unconverted
strings". Cleaning/enrichment into analysis-ready columns lives in
normalize.py; keeping the two separate means a future paid source that
already provides clean data doesn't need to fake its way through this
module's parsing quirks — it can go straight to normalize().

Reference: https://www.dtcc.com/public-reporting
"""

from __future__ import annotations

import gc
import io
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

import pandas as pd
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.csv as pv
import requests

from .. import s3_cache
from ..constants import DTCC_BASE_URL, NEW_TRADE_ACTION_TYPES

COLUMNS = [
    "Action type",
    "Asset Class",
    "Execution Timestamp",
    "Effective Date",
    "Expiration Date",
    "Cleared",
    "Block trade election indicator",
    "Notional amount-Leg 1",
    "Notional amount-Leg 2",
    "Notional currency-Leg 1",
    "Notional currency-Leg 2",
    "Fixed rate-Leg 1",
    "Spread-Leg 1",
    "Price",
    "Exchange rate",
    "UPI Underlier Name",
]

_REQUEST_TIMEOUT = 30


def _slice_url(asset_class_code: str, day: date) -> str:
    return f"{DTCC_BASE_URL}/CFTC_CUMULATIVE_{asset_class_code}_{day:%Y_%m_%d}.zip"


def fetch_day(asset_class_code: str, day: date) -> pd.DataFrame:
    """Fetch and lightly parse one asset class's cumulative slice for one day.

    Returns an empty DataFrame (not an error) for weekends/holidays or any
    day DTCC has not published a file for, since that's an expected gap
    rather than a failure.

    Checks the optional S3 cache first (see s3_cache.py) — DTCC's daily
    files are immutable once published, so a cache hit skips the network
    fetch and the expensive parse entirely. Only a *definitive* result
    (DTCC actually responded, whether with data or an empty day) is written
    back; network errors are never cached, so a transient failure is
    retried on the next request rather than "confirmed empty" forever.
    """
    cached = s3_cache.read_day(asset_class_code, day)
    if cached is not None:
        return cached

    url = _slice_url(asset_class_code, day)
    try:
        resp = requests.get(url, timeout=_REQUEST_TIMEOUT)
    except requests.RequestException:
        return pd.DataFrame(columns=COLUMNS)

    if resp.status_code != 200 or not resp.content:
        return pd.DataFrame(columns=COLUMNS)

    # Some of these files are 100+ columns wide and 800k+ rows (equities
    # especially). Reading the whole thing into one pandas/Arrow table
    # before filtering peaks well past Streamlit Cloud's 1GB per-app memory
    # limit, even with column pruning. Streaming in batches and discarding
    # non-new-trade rows (corrections/cancellations/amendments, which
    # outnumber genuinely new trades and are never used downstream) as each
    # batch arrives keeps peak memory to roughly one batch at a time,
    # cutting it by 3-4x versus a bulk read.
    try:
        with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
            csv_name = next(n for n in zf.namelist() if n.lower().endswith(".csv"))
            with zf.open(csv_name) as f:
                # use_threads=False: this runs inside our own ThreadPoolExecutor
                # (concurrent across days/asset classes) — letting pyarrow's C++
                # reader spin up its own internal thread pool on top of that
                # caused a hard segfault under load during testing.
                reader = pv.open_csv(
                    f,
                    convert_options=pv.ConvertOptions(include_columns=COLUMNS),
                    read_options=pv.ReadOptions(block_size=8 * 1024 * 1024, use_threads=False),
                )
                kept_batches = []
                for batch in reader:
                    table = pa.Table.from_batches([batch])
                    mask = pc.is_in(table.column("Action type"), pa.array(NEW_TRADE_ACTION_TYPES))
                    kept_batches.append(table.filter(mask))
    except (zipfile.BadZipFile, StopIteration, ValueError, pa.ArrowInvalid):
        return pd.DataFrame(columns=COLUMNS)

    if not kept_batches:
        empty = pd.DataFrame(columns=COLUMNS + ["_trade_date"])
        s3_cache.write_day(asset_class_code, day, empty)
        return empty

    # self_destruct releases each Arrow column's buffer as soon as it's been
    # converted, instead of keeping the whole source table alive alongside
    # the new pandas frame — this alone roughly halved peak memory during
    # testing, and (unlike the default conversion) the result is actually
    # freed by `del` afterward rather than lingering in Arrow's pool for the
    # rest of the process's life.
    table = pa.concat_tables(kept_batches)
    del kept_batches
    df = table.to_pandas(split_blocks=True, self_destruct=True)
    del table
    for col in ("Asset Class", "Cleared", "Notional currency-Leg 1", "Notional currency-Leg 2", "Block trade election indicator"):
        if col in df.columns:
            df[col] = df[col].astype("category")

    df["_trade_date"] = day
    s3_cache.write_day(asset_class_code, day, df)
    return df


def fetch_recent(asset_class_code: str, end_day: date, lookback_days: int) -> pd.DataFrame:
    """Fetch and concatenate several days of a slice, skipping missing days.

    Days are fetched concurrently — this is pure I/O wait on independent
    HTTP requests, and lookback windows of a week or more make the naive
    serial version too slow for a good first-load experience.
    """
    days = [end_day - timedelta(days=i) for i in range(lookback_days)]
    with ThreadPoolExecutor(max_workers=min(4, len(days))) as pool:
        results = pool.map(lambda day: fetch_day(asset_class_code, day), days)
    frames = [df for df in results if not df.empty]
    if not frames:
        return pd.DataFrame(columns=COLUMNS + ["_trade_date"])
    combined = pd.concat(frames, ignore_index=True)
    # Drop references to the per-day frames and nudge the allocator to
    # return their memory promptly rather than holding it in reserve —
    # matters when running under a hard cgroup memory limit (Streamlit
    # Cloud), where "freed but not yet returned to the OS" still counts
    # against the cap.
    del frames, results
    gc.collect()
    return combined
