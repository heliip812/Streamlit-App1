"""Shared constants for market data ingestion."""

from datetime import date

# DTCC SDR (Swap Data Repository) public dissemination asset class codes.
# https://kgc0418-tdw-data-0.s3.amazonaws.com/cftc/eod/CFTC_CUMULATIVE_<CODE>_<YYYY>_<MM>_<DD>.zip
DTCC_ASSET_CLASSES = {
    "CREDITS": "Credit",
    "RATES": "Rates",
    "FOREX": "FX",
    "EQUITIES": "Equities",
    "COMMODITIES": "Commodities",
}

DTCC_BASE_URL = "https://kgc0418-tdw-data-0.s3.amazonaws.com/cftc/eod"

# Patterns identifying CDS index trades (vs. single-name CDS) via the
# "UPI Underlier Name" / UPI underlier fields in DTCC credit data.
CDS_INDEX_PATTERNS = ("CDX", "ITRAXX", "ITX", "MARKIT", "IDX", "INDEX")

# Action types that represent a genuinely new trade (as opposed to a
# correction, cancellation or amendment of a previously reported one).
NEW_TRADE_ACTION_TYPES = ("NEWT",)

# CFTC public reporting (Socrata) — Traders in Financial Futures, futures-only.
CFTC_TFF_RESOURCE_ID = "gpe5-46if"
CFTC_BASE_URL = "https://publicreporting.cftc.gov/resource"

# A representative slice of financial-futures contracts covering rates, FX
# and equity index products, for the positioning page.
CFTC_TFF_CONTRACTS = [
    "10-YEAR U.S. TREASURY NOTES",
    "2-YEAR U.S. TREASURY NOTES",
    "5-YEAR U.S. TREASURY NOTES",
    "ULTRA U.S. TREASURY BONDS",
    "SOFR-3M",
    "EURO FX",
    "JAPANESE YEN",
    "BRITISH POUND STERLING",
    "E-MINI S&P 500",
    "NASDAQ-100 CONSOLIDATED",
]

# CFTC public reporting (Socrata) — Disaggregated report, futures-only.
# Covers physical commodities, which the TFF report above does not.
CFTC_DISAGG_RESOURCE_ID = "72hh-3qpy"

CFTC_DISAGG_CONTRACTS = [
    "WTI",
    "NATURAL GAS",
    "GOLD",
    "SILVER",
    "COPPER",
    "CORN",
    "SOYBEAN",
    "WHEAT",
]

# FRED (St. Louis Fed) — the free, keyless CSV endpoint that backs the Fed
# path section. FRED is built for programmatic access and doesn't bot-block
# (unlike CME's quotes endpoint), which is why the path is derived from the
# Treasury curve it publishes rather than fed-funds futures. Like every other
# external host it's unreachable from the build sandbox's allowlist proxy, so
# the fetch is defensively coded and unit-tested against mocked CSV responses;
# it works from Streamlit Cloud's open network.
FRED_CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv"

# Live anchors pulled from FRED so the current policy stance isn't hardcoded:
# the effective fed funds rate and the target range bounds.
FRED_EFFR_SERIES = "DFF"
FRED_TARGET_UPPER_SERIES = "DFEDTARU"
FRED_TARGET_LOWER_SERIES = "DFEDTARL"

# Short-end constant-maturity Treasury yields (series id -> maturity in years),
# ascending — the market prices these off the expected policy path, so their
# implied forwards are a market-implied Fed-path proxy. Front-end term premium
# is small but nonzero and T-bills trade slightly rich, so this reads a touch
# more dovish than a pure OIS/futures measure would; captioned as such.
FRED_YIELD_SERIES = {
    "DGS1MO": 1 / 12,
    "DGS3MO": 0.25,
    "DGS6MO": 0.5,
    "DGS1": 1.0,
    "DGS2": 2.0,
}

# --- Editable Fed assumptions -------------------------------------------------
# Fallback anchor if FRED's EFFR series is momentarily unavailable; the live
# FRED value is preferred and the Rates sidebar lets the viewer override it.
CURRENT_EFFR_DEFAULT = 4.33

# FOMC decision dates are fetched from the Fed's public calendar page at
# runtime (see data/cb_calendar.py); this list is the FALLBACK used when that
# best-effort scrape fails. VERIFY against
# federalreserve.gov/monetarypolicy/fomccalendars.htm and keep roughly current.
FOMC_CALENDAR_URL = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"
FOMC_MEETING_DATES_FALLBACK = [
    date(2026, 1, 28),
    date(2026, 3, 18),
    date(2026, 4, 29),
    date(2026, 6, 17),
    date(2026, 7, 29),
    date(2026, 9, 16),
    date(2026, 10, 28),
    date(2026, 12, 9),
]

# Latest FOMC Summary of Economic Projections (SEP) dot-plot MEDIAN year-end
# federal funds rate, in percent. Placeholder values — UPDATE from the newest
# SEP (released quarterly) and change SEP_AS_OF so the overlay is labelled
# honestly. Shown only as a dated reference against the market-implied path.
SEP_DOT_PLOT_MEDIAN = {2026: 3.875, 2027: 3.375, 2028: 3.125}
SEP_AS_OF = "June 2026 SEP (placeholder — update from the latest release)"

# --- ECB (European Central Bank) ---------------------------------------------
# The ECB Data Portal — free, keyless, well-structured; the euro-area
# counterpart to FRED. Each series is one small CSV request:
#   {ECB_DATA_URL}/{dataflow}/{key}?lastNObservations=1&format=csvdata
ECB_DATA_URL = "https://data-api.ecb.europa.eu/service/data"

# Live policy anchors: the deposit facility rate (the effective policy floor in
# the current regime), the main refinancing rate, and the €STR overnight
# benchmark used to anchor the front of the implied path.
ECB_DFR_KEY = "FM/B.U2.EUR.4F.KR.DFR.LEV"
ECB_MRO_KEY = "FM/B.U2.EUR.4F.KR.MRR_FR.LEV"
ECB_ESTR_KEY = "EST/B.EU000A2X2A25.WT"

# Euro-area AAA government spot yield curve (maturity in years -> series key),
# the ECB's published curve used the same way FRED's Treasury yields are for
# the Fed. AAA/Bund collateral trades rich (safe haven), so this reads even a
# touch more dovish than the US proxy; captioned accordingly.
ECB_YIELD_KEYS = {
    0.25: "YC/B.U2.EUR.4F.G_N_A.SV_C_YM.SR_3M",
    0.5: "YC/B.U2.EUR.4F.G_N_A.SV_C_YM.SR_6M",
    1.0: "YC/B.U2.EUR.4F.G_N_A.SV_C_YM.SR_1Y",
    2.0: "YC/B.U2.EUR.4F.G_N_A.SV_C_YM.SR_2Y",
}

# Fallback euro overnight rate (€STR, %) if the live series is unavailable.
CURRENT_ESTR_DEFAULT = 1.90

# ECB Governing Council monetary-policy meeting dates are scraped best-effort
# from the ECB calendar page (data/cb_calendar.py); this is the FALLBACK.
# VERIFY against ecb.europa.eu and keep roughly current.
ECB_CALENDAR_URL = "https://www.ecb.europa.eu/press/calendars/mgcgc/html/index.en.html"
ECB_MEETING_DATES_FALLBACK = [
    date(2026, 2, 5),
    date(2026, 3, 19),
    date(2026, 4, 30),
    date(2026, 6, 4),
    date(2026, 7, 23),
    date(2026, 9, 10),
    date(2026, 10, 29),
    date(2026, 12, 17),
]
