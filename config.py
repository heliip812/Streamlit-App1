"""Central, non-Streamlit-specific tunables.

Keeping these here instead of scattered as magic numbers across pages means
adjusting a default or a cache lifetime is a one-line change in one place,
not a hunt through every page file.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class RangeConfig:
    min_value: int
    max_value: int
    default: int


# For the DTCC-backed pages, these drive ui.sidebar_date_range: `default` is
# how many business days the range picker starts pre-filled with, and
# `max_value` caps how many business days a manually widened range can span
# — the safety limit that keeps a wide window from reintroducing the memory
# issues seen before (min_value is unused here; date ranges have no natural
# floor besides "at least one day"). CFTC_WEEKS_LOOKBACK is unrelated — it
# still drives a plain slider in weeks, not a date range.
HOME_LOOKBACK = RangeConfig(min_value=3, max_value=21, default=3)
CREDIT_LOOKBACK = RangeConfig(min_value=3, max_value=30, default=7)
RATES_LOOKBACK = RangeConfig(min_value=3, max_value=30, default=7)
FX_LOOKBACK = RangeConfig(min_value=3, max_value=30, default=7)
EQUITIES_COMMODITIES_LOOKBACK = RangeConfig(min_value=3, max_value=21, default=3)
CFTC_WEEKS_LOOKBACK = RangeConfig(min_value=8, max_value=104, default=26)

CACHE_TTL_SECONDS = 3600

# --- Policy-model & signals tunables -----------------------------------------
# One standard policy move, in basis points; used to scale gaps into
# hike/hold/cut probabilities and to discretise the model's path.
STEP_BP = 25.0

# Divergence (model − market, bp) thresholds for the trading signals.
SIGNAL_THRESHOLD_BP = 10.0  # ignore divergences smaller than this
SIGNAL_STRONG_BP = 25.0  # one full step of mispricing → high conviction

# FX pair label for each unordered pair of central banks (by code). Used to
# name the FX leg of a cross-bank signal.
FX_PAIRS = {
    frozenset({"fed", "ecb"}): "EUR/USD",
    frozenset({"fed", "boe"}): "GBP/USD",
    frozenset({"fed", "boj"}): "USD/JPY",
    frozenset({"ecb", "boe"}): "EUR/GBP",
    frozenset({"ecb", "boj"}): "EUR/JPY",
    frozenset({"boe", "boj"}): "GBP/JPY",
}
