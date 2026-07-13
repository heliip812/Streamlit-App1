# Derivatives Market Monitor

[![Open in Streamlit](https://static.streamlit.io/badges/streamlit_badge_black_white.svg)](https://app-app1-yje7wiztq2gzp4qxktfb2h.streamlit.app/)

Trade-level liquidity and positioning across credit, rates, FX, equity and commodity
derivatives, sourced entirely from free public regulatory data:

- **[DTCC Swap Data Repository](https://www.dtcc.com/public-reporting)** — real trade
  prints (price/rate, notional, timestamp) disclosed under Dodd-Frank Part 43/45, no auth
- **[CFTC Commitments of Traders](https://www.cftc.gov/MarketReports/CommitmentsofTraders/index.htm)**
  — weekly futures positioning by trader category

Official CDX/iTraxx index levels require a licensed Markit/ICE data feed and are **not**
included — figures here are derived from actual reported trades, not composite fixings.

**Live app:** https://app-app1-yje7wiztq2gzp4qxktfb2h.streamlit.app/

## Pages

- **Home** — cross-asset overview (latest-day notional/trades, multi-day trend)
- **Credit** — CDS index (CDX/iTraxx) vs. single-name split, most active names
- **Rates** — notional by tenor bucket and currency, fixed-rate levels
- **FX** — most active currency pairs, daily volume
- **Equities & Commodities** — most active underliers, daily volume
- **CFTC Positioning** — net long/short by trader category, open interest

## Architecture

```
app.py                    Home page (Streamlit's entrypoint)
pages/                    One file per page, auto-discovered by Streamlit
  1_Credit.py
  2_Rates.py
  3_FX.py
  4_Equities_and_Commodities.py
  5_CFTC_Positioning.py
config.py                 Tunables: lookback slider ranges, cache TTL
ui.py                      Shared Streamlit widgets: sidebar date/lookback
                           controls, chart chrome + render, metric rows,
                           empty-state banners — every page uses these
                           instead of repeating the same boilerplate
viz_theme.py               The categorical/status color palette, shared
                           across all charts so a series always gets the
                           same color regardless of which page draws it
data/
  sources.py               The only module pages import data through —
                           adds st.cache_data and is the seam where a
                           future paid feed (Markit/ICE/Bloomberg) would
                           plug in alongside the free ones
  constants.py             Asset class codes, index-name patterns, CFTC
                           resource IDs/contract lists
  dtcc/
    client.py              Fetching + parsing raw DTCC files (HTTP, zip,
                           streaming CSV parse) — no analytics, just "get
                           the rows out of the file"
    normalize.py            Cleaning raw rows into analysis-ready columns
                           (notional/currency handling, tenor, index
                           detection) — knows nothing about HTTP or files
  cftc.py                  CFTC Commitments of Traders ingestion
  s3_cache.py               Optional persistent cache (see below);
                           every function is a no-op if AWS isn't configured
```

**Adding a new data source** (e.g. a paid Markit feed): add a module under `data/`
that exposes a `get_recent_trades(asset_class_code, end_day, lookback_days) -> DataFrame`
returning the same normalized columns `dtcc/normalize.py` produces (see its docstring),
then add a cached wrapper in `data/sources.py`. Pages never need to change.

**Adding a new page**: add a file to `pages/`, pull data through `data/sources.py`, and
build its sidebar/charts with the helpers in `ui.py` — that's usually the entire diff.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
```

## Run locally

```bash
streamlit run app.py
```

## Lint & test

```bash
ruff check .
pytest
```

## Optional: S3 data cache

The app works with zero setup, fetching directly from DTCC on every load. Configuring an
S3 bucket adds a persistent cache of already-parsed days (DTCC's daily files are
immutable once published), so repeat loads of the same date — including from other users
or after the app restarts — skip re-downloading and re-parsing entirely. This is what
makes it practical to widen the lookback range: the first pull of a new day is the only
expensive one.

**1. Create an S3 bucket** (AWS Console -> S3 -> Create bucket). Any region; keep "Block
all public access" on — nothing here needs to be public.

**2. Create an IAM policy** scoped to just that bucket (replace `your-bucket-name`):

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["s3:GetObject", "s3:PutObject"],
      "Resource": "arn:aws:s3:::your-bucket-name/*"
    }
  ]
}
```

**3. Create an IAM user** (IAM -> Users -> Create user) with no console access, attach the
policy above, then generate an access key (Security credentials -> Access keys ->
"Application running outside AWS").

**4. Add the credentials as secrets** — locally, copy `.streamlit/secrets.toml.example` to
`.streamlit/secrets.toml` (gitignored) and fill in the values; on Streamlit Community
Cloud, paste the same content into your app's **Settings -> Secrets** instead. Never
commit real credentials.

**5. Reboot the app** (Streamlit Cloud picks up new secrets on restart). That's it —
`data/s3_cache.py` detects the `[aws]` section automatically; nothing else to configure.

## Deploy

This app is deployed on [Streamlit Community Cloud](https://share.streamlit.io) from the `main`
branch, pointed at `app.py`. Configuration lives in `.streamlit/config.toml`. Every push to `main`
auto-redeploys the live app above.

To deploy your own copy: [![Deploy on Streamlit](https://static.streamlit.io/badges/streamlit_badge_black_white.svg)](https://share.streamlit.io/deploy?repository=heliip812/Streamlit-App1&branch=main&mainModule=app.py)
