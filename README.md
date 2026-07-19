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
- **Credit** — CDS index (CDX/iTraxx) vs. single-name split, most active names, spread curve by tenor
- **Rates** — notional by tenor bucket and currency, per-currency yield curve
- **FX** — most active currency pairs, spot vs. forward tenor mix, forward curve
- **Equities & Commodities** — most active underliers, tenor mix, level curve by tenor
- **CFTC Positioning** — net long/short by trader category and open interest, for both
  financial futures (rates/FX/equity index) and commodity futures (WTI, gold, corn, etc.),
  plus positioning-extreme flags (percentile + z-score crowding signals)
- **Central Bank Paths** — market-implied policy rate for the Fed (Treasury.gov curve +
  NY Fed EFFR, FRED backup, FOMC dot-plot overlay), the ECB (ECB Data Portal), the Bank of
  England (sterling OIS curve) and the Bank of Japan (Japan MOF JGB curve), with the implied
  rate at each upcoming meeting, a per-source status line, and a "show your work" validation
  panel. An optional **as-of compare** overlays the path as it was priced on an earlier date
  (from each source's own history) and shows how each meeting has repriced since. With a free
  **FRED API key**, an **own model** (Taylor-gap rule + momentum, tuned by sidebar sliders) is
  overlaid on the market path, and the model-vs-market **divergence** drives outright /
  cross-bank spread / FX **signals**. Five tabs: **Policy paths** (the interactive content),
  **Methodology** (the CB-dashboard brief's three-stage engine — raw instrument quotes →
  basis-adjusted → per-meeting path deconvolved on EFFECTIVE dates, with a `method` label on
  every number: Fed ZQ futures, ECB Eurex €STR CSV, BoE OIS forward windowing, curve-forward
  fallback everywhere), **Daily signals** (snapshot-driven: overnight repricing, divergence
  z-scores, signal board with flip flags, FX overlay, instrument mapping, refresh button),
  **Data sources**, and **Model rationale** (renders `docs/MODEL.md`). Central banks are
  registry-driven (`data/central_banks.py`) — adding one is a new fetcher plus a registry
  entry, no page changes
Most DTCC/CFTC pages also carry a **Trading signals** row (trend percentile, curve-shape
relative value, and flow vs. the window average) and a collapsible trade-level detail table.

## Architecture

```
app.py                    Home page (Streamlit's entrypoint)
pages/                    One file per page, auto-discovered by Streamlit
  1_Credit.py
  2_Rates.py
  3_FX.py
  4_Equities_and_Commodities.py
  5_CFTC_Positioning.py
  6_Central_Bank_Paths.py
config.py                 Tunables: lookback slider ranges, cache TTL
fed_path.py                Pure market-implied path math (short-end yields ->
                           implied forward rate path + interpolation), no
                           Streamlit/network so it's fully unit-tested; drives
                           the Central Bank Paths page
policy_model.py            Pure 'own model' — Taylor-gap + momentum -> hike/
                           hold/cut probabilities -> model path; unit-tested
docs/MODEL.md              The model's rationale, design choices vs
                           alternatives, and limitations — rendered in-app on
                           the Model rationale tab (single source of truth)
signals.py                 Pure model-vs-market divergence -> outright / spread
                           / FX signals; unit-tested
implied_engine.py          Pure three-stage implied-path engine (raw ->
                           basis-adjusted -> per-meeting path): Fed monthly-
                           average deconvolution on effective dates (with the
                           late-month next-month-proxy fallback), ECB quarterly
                           equal-step fit, BoE OIS forward windowing, and the
                           curve-forward fallback; unit-tested
ui.py                      Shared Streamlit widgets: sidebar date/lookback
                           controls, chart chrome + render, metric rows,
                           empty-state banners — every page uses these
                           instead of repeating the same boilerplate
analytics.py               Small pandas helpers shared across pages (e.g.
                           percentile-based outlier dropping for curves) —
                           not Streamlit-specific, not DTCC-specific
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
  central_banks.py         Registry of central banks for the policy-path
                           section — one CentralBankSpec per bank; adding a
                           bank never touches page code
  fred.py                  FRED series ingestion (keyless CSV) — EFFR, target
                           range, short-end Treasury yields
  us_rates.py              Composes the US inputs: FRED first, falling back
                           per-piece to Treasury.gov (curve) and the NY Fed
                           markets API (EFFR), with per-source status lines
  ecb.py                   ECB Data Portal ingestion (keyless CSV) — €STR,
                           deposit/MRO rates, euro-area yield curve
  boe.py                   Bank of England IADB ingestion (keyless CSV) —
                           Bank Rate + short gilt yields
  boj.py                   Bank of Japan curve from the Japan MOF JGB CSV
  cb_calendar.py           Best-effort scrape of central-bank meeting calendars
                           (FETCHERS dispatch), validated, with a maintained
                           fallback in constants.py
  macro.py                 FRED macro inputs for the own model (via fredapi,
                           needs a free key) — inflation, unemployment, NFCI
  meetings.py              Decision + EFFECTIVE dates per bank (Fed: next
                           business day; ECB: following Wednesday; BoE: same
                           day) — the deconvolution keys on effective dates
  cb_market.py             Raw quote fetchers: ZQ futures (yfinance), BoE OIS
                           forward zip, FX spots — network only, no math
  store.py                 SQLite snapshot store (var/snapshots.db, gitignored)
                           — paths/signals/fx history, divergence z-scores
  s3sync.py                Pull-on-start / push-after-refresh persistence for
                           the store (CB_S3_BUCKET env or [aws].snapshots_bucket)
  refresh.py               The daily job: fetch -> paths -> model -> signals ->
                           snapshot -> S3 push. CLI: python -m data.refresh
                           --fred-key KEY (cron weekdays ~07:30 UK); the app's
                           "Refresh & snapshot" button runs the same job
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
