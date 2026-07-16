"""Central-bank registry for the market-implied policy-path section.

Every central bank the Rates page can show is one CentralBankSpec entry in
CENTRAL_BANKS, and the page renders whatever the registry contains — so
adding a bank (BoE, BoJ, SNB, ...) never touches page code. To add one:

1. Write a fetcher module under data/ that returns this normalised shape
   (see _fed_inputs/_ecb_inputs for adapters over existing modules):
   anchor rate, extra metric tiles, a {maturity_years: yield} curve, and
   per-piece source-status lines.
2. (Optional) Add a meeting-calendar scraper to cb_calendar.FETCHERS under a
   new code, with a fallback date list in constants.py.
3. Append a CentralBankSpec below.

PolicyInputs is deliberately plain (floats, dicts, strings) so it pickles
cleanly through st.cache_data.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Callable

from . import boe, boj, ecb, us_rates
from .constants import (
    BOE_MEETING_DATES_FALLBACK,
    BOJ_MEETING_DATES_FALLBACK,
    CURRENT_BANK_RATE_DEFAULT,
    CURRENT_BOJ_RATE_DEFAULT,
    CURRENT_EFFR_DEFAULT,
    CURRENT_ESTR_DEFAULT,
    ECB_MEETING_DATES_FALLBACK,
    FOMC_MEETING_DATES_FALLBACK,
    SEP_AS_OF,
    SEP_DOT_PLOT_MEDIAN,
)


@dataclass
class PolicyInputs:
    anchor_rate: float | None  # overnight rate anchoring the path's front
    yields: dict[float, float]  # maturity in years -> yield (%); empty = curve unavailable
    metrics: list[tuple[str, str]]  # extra (label, formatted value) metric tiles
    status: list[str]  # per-piece "which source supplied this" diagnostic lines


@dataclass(frozen=True)
class CentralBankSpec:
    code: str  # stable id used for cache keys and calendar dispatch
    label: str  # radio-button label
    anchor_label: str  # sidebar override input label
    anchor_metric_label: str  # metric-tile label for the anchor
    anchor_fallback: float  # last-resort anchor if every live source fails
    fetch: Callable[[], PolicyInputs]
    calendar_code: str  # key into cb_calendar.FETCHERS
    calendar_hint: str  # where to verify the fallback meeting list
    meeting_fallback: list[date]
    meeting_label: str  # e.g. "FOMC"
    yaxis_title: str
    # (label, url) references shown in the "Data source & method" panel so the
    # numbers can be validated against the raw source.
    sources: list[tuple[str, str]] = field(default_factory=list)
    dot_plot: dict[int, float] | None = field(default=None)  # year -> projected rate
    dot_label: str | None = field(default=None)


def _fed_inputs() -> PolicyInputs:
    raw = us_rates.fetch_policy_inputs()
    metrics = []
    if raw["target_range"] is not None:
        lower, upper = raw["target_range"]
        metrics.append(("Target range", f"{lower:.2f}–{upper:.2f}%"))
    return PolicyInputs(raw["anchor"], raw["yields"], metrics, raw["status"])


def _ecb_inputs() -> PolicyInputs:
    raw = ecb.fetch_ecb_policy_inputs()
    yields = raw.get("yields", {})
    estr, dfr, mro = raw.get("estr"), raw.get("dfr"), raw.get("mro")
    anchor = estr if estr is not None else dfr
    metrics = []
    if dfr is not None and mro is not None:
        metrics.append(("Deposit facility / MRO", f"{dfr:.2f}% / {mro:.2f}%"))
    status = [
        "Curve: ECB Data Portal" if yields else "Curve: unavailable (ECB Data Portal failed)",
        "€STR: ECB Data Portal"
        if estr is not None
        else ("€STR: unavailable — using deposit rate" if dfr is not None else "€STR: unavailable — using the manual anchor"),
    ]
    return PolicyInputs(anchor, yields, metrics, status)


def _boe_inputs() -> PolicyInputs:
    raw = boe.fetch_boe_policy_inputs()
    return PolicyInputs(raw.get("bank_rate"), raw.get("yields", {}), [], raw["status"])


def _boj_inputs() -> PolicyInputs:
    raw = boj.fetch_boj_policy_inputs()
    # The BoJ has no clean live overnight feed, so the anchor is always the
    # sidebar/fallback value; the page's number_input supplies it.
    status = raw["status"] + ["Policy rate: manual anchor (no live BoJ feed)"]
    return PolicyInputs(None, raw.get("yields", {}), [], status)


CENTRAL_BANKS: list[CentralBankSpec] = [
    CentralBankSpec(
        code="fed",
        label="Federal Reserve",
        anchor_label="Current effective fed funds rate (EFFR), %",
        anchor_metric_label="Current EFFR",
        anchor_fallback=CURRENT_EFFR_DEFAULT,
        fetch=_fed_inputs,
        calendar_code="fomc",
        calendar_hint="federalreserve.gov",
        meeting_fallback=FOMC_MEETING_DATES_FALLBACK,
        meeting_label="FOMC",
        yaxis_title="Fed funds rate (%)",
        sources=[
            (
                "Curve — U.S. Treasury daily par yield curve",
                "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/TextView?type=daily_treasury_yield_curve",
            ),
            ("Overnight anchor — NY Fed Effective Federal Funds Rate", "https://www.newyorkfed.org/markets/reference-rates/effr"),
            ("Backup — FRED (DGS* / DFF / DFEDTAR*)", "https://fred.stlouisfed.org/graph/?id=DGS3MO"),
        ],
        dot_plot=SEP_DOT_PLOT_MEDIAN,
        dot_label=f"Dot plot median — {SEP_AS_OF}",
    ),
    CentralBankSpec(
        code="ecb",
        label="ECB",
        anchor_label="Current €STR (euro overnight rate), %",
        anchor_metric_label="€STR (overnight)",
        anchor_fallback=CURRENT_ESTR_DEFAULT,
        fetch=_ecb_inputs,
        calendar_code="ecb",
        calendar_hint="ecb.europa.eu",
        meeting_fallback=ECB_MEETING_DATES_FALLBACK,
        meeting_label="ECB Governing Council",
        yaxis_title="ECB policy rate (%)",
        sources=[
            ("Curve — ECB Data Portal, euro-area AAA yield curve (YC)", "https://data.ecb.europa.eu/data/datasets/YC"),
            (
                "€STR & key rates — ECB Data Portal (EST / FM)",
                "https://www.ecb.europa.eu/stats/financial_markets_and_interest_rates/euro_short-term_rate/html/index.en.html",
            ),
        ],
    ),
    CentralBankSpec(
        code="boe",
        label="Bank of England",
        anchor_label="Current UK Bank Rate, %",
        anchor_metric_label="Bank Rate",
        anchor_fallback=CURRENT_BANK_RATE_DEFAULT,
        fetch=_boe_inputs,
        calendar_code="boe",  # no scraper yet -> fallback list is used
        calendar_hint="bankofengland.co.uk",
        meeting_fallback=BOE_MEETING_DATES_FALLBACK,
        meeting_label="MPC",
        yaxis_title="UK Bank Rate (%)",
        sources=[
            ("Curve — Bank of England sterling OIS yield curve (Excel)", "https://www.bankofengland.co.uk/statistics/yield-curves"),
            ("Bank Rate — BoE Interactive Database (IADB)", "https://www.bankofengland.co.uk/boeapps/database/"),
        ],
    ),
    CentralBankSpec(
        code="boj",
        label="Bank of Japan",
        anchor_label="Current BoJ policy rate, %",
        anchor_metric_label="Policy rate",
        anchor_fallback=CURRENT_BOJ_RATE_DEFAULT,
        fetch=_boj_inputs,
        calendar_code="boj",  # no scraper yet -> fallback list is used
        calendar_hint="boj.or.jp",
        meeting_fallback=BOJ_MEETING_DATES_FALLBACK,
        meeting_label="MPM",
        yaxis_title="BoJ policy rate (%)",
        sources=[
            ("Curve — Japan MOF, JGB interest rates (daily CSV)", "https://www.mof.go.jp/english/policy/jgbs/reference/interest_rate/index.htm"),
            ("Policy rate — Bank of Japan", "https://www.boj.or.jp/en/statistics/boj/other/mci/index.htm"),
        ],
    ),
]


def get_spec(label_or_code: str) -> CentralBankSpec:
    return next(s for s in CENTRAL_BANKS if label_or_code in (s.code, s.label))


def fetch_inputs(code: str) -> PolicyInputs:
    return get_spec(code).fetch()
