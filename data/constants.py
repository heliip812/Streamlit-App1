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

# CME delayed quotes for 30-Day Fed Funds futures ("ZQ", product id 305) —
# the same contracts that feed CME's FedWatch tool. Keyless and public but
# delayed; like the CFTC host it's unreachable from the build sandbox (open
# on Streamlit Cloud), so the fetch is defensively coded and unit-tested
# against mocked responses rather than live calls.
CME_QUOTES_URL = "https://www.cmegroup.com/CmeWS/mvc/Quotes/Future/305/G"

# --- Editable Fed assumptions -------------------------------------------------
# These three are NOT market-derived and can't be inferred for a future date;
# they anchor the market-implied math and must be kept current by hand. The
# Fed Path page surfaces the rate as a sidebar input (defaulting here) so the
# viewer sets ground truth; the meeting dates and dot plot are edited here.

# Current effective fed funds rate (EFFR), in percent. VERIFY against the NY
# Fed / FRED (series EFFR) and update after any move. Anchors the front of the
# implied path — using EFFR rather than the range midpoint keeps the first
# computed change honest.
CURRENT_EFFR_DEFAULT = 4.33

# 2026 FOMC decision dates (the second/announcement day of each meeting).
# VERIFY against federalreserve.gov/monetarypolicy/fomccalendars.htm — the
# path only depends on meetings still ahead of the current date.
FOMC_MEETING_DATES_2026 = [
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
