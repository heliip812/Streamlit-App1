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


HOME_LOOKBACK = RangeConfig(min_value=3, max_value=21, default=3)
CREDIT_LOOKBACK = RangeConfig(min_value=3, max_value=30, default=7)
RATES_LOOKBACK = RangeConfig(min_value=3, max_value=30, default=7)
FX_LOOKBACK = RangeConfig(min_value=3, max_value=30, default=7)
EQUITIES_COMMODITIES_LOOKBACK = RangeConfig(min_value=3, max_value=21, default=3)
CFTC_WEEKS_LOOKBACK = RangeConfig(min_value=8, max_value=104, default=26)

CACHE_TTL_SECONDS = 3600
