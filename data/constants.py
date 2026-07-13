"""Shared constants for market data ingestion."""

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
