from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import implied_engine as eng
from config import FX_PAIRS
from data import refresh as refresh_job
from data import s3sync, store
from data.central_banks import CENTRAL_BANKS, get_spec
from data.meetings import CONVENTION_NOTES, meetings_for
from data.sources import get_boe_forward_curve, get_macro, get_meeting_dates, get_policy_inputs, get_zq_futures
from fed_path import implied_forward_path, implied_rate_at
from policy_model import model_path
from signals import build_signal_table, merge_paths, outright_signal
from ui import metric_row, render
from viz_theme import CATEGORICAL

st.set_page_config(page_title="Central Bank Paths — Derivatives Monitor", page_icon="📈", layout="wide")
st.title("Central bank policy paths (market-implied)")
st.caption(
    "Where the market expects each central bank's policy rate to go — an always-on curve-implied "
    "path per bank, a Methodology tab that rebuilds it from the preferred instrument (futures/OIS) "
    "in three explicit stages, an optional own model (free FRED key) with divergence signals, and "
    "a Daily signals tab fed by snapshot history. Sources and rationale on their own tabs."
)

_MODEL_DOC = Path(__file__).resolve().parent.parent / "docs" / "MODEL.md"

INSTRUMENTS = pd.DataFrame(
    [
        {"signal": "Fed outright", "futures": "ZQ / SR3 strip", "swap": "USD 1y/2y SOFR OIS", "note": "pay if model hawkish vs market"},
        {"signal": "ECB outright", "futures": "Eurex 3M €STR strip", "swap": "EUR 1y/2y €STR OIS", "note": "same convention"},
        {"signal": "BoE outright", "futures": "ICE 3M SONIA strip", "swap": "GBP 1y/2y SONIA OIS", "note": "same convention"},
        {"signal": "BoJ outright", "futures": "TONA futures (thin)", "swap": "JPY 1y/2y TONA OIS", "note": "same convention"},
        {"signal": "Cross-bank spread", "futures": "front-strip calendar packs", "swap": "2y cross-currency OIS spread", "note": "pay the wider leg"},
        {"signal": "FX", "futures": "CME FX futures", "swap": "spot/forward EURUSD, GBPUSD, EURGBP…", "note": "long the relatively-hawkish-mispriced ccy"},
    ]
)


def _maturity_label(years: float) -> str:
    return {1 / 12: "1M", 0.25: "3M", 0.5: "6M", 1.0: "1Y", 2.0: "2Y"}.get(years, f"{years:g}Y")


def _curve_as_of(history, target_date):
    """Nearest available curve on or before target_date: (actual_date, curve)."""
    eligible = [d for d in history if d <= target_date]
    if not eligible:
        return None, {}
    day = max(eligible)
    return day, history[day]


def _market_at_meetings(path, meetings, today):
    """Market-implied rate interpolated at each upcoming meeting within the curve."""
    if path.empty:
        return pd.DataFrame(columns=["meeting", "implied_rate"])
    last = today + timedelta(days=round(float(path["horizon_years"].max()) * 365))
    rows = []
    for meeting in sorted(meetings):
        if meeting < today or meeting > last:
            continue
        rate = implied_rate_at(path, (meeting - today).days / 365.0)
        if rate is not None:
            rows.append({"meeting": meeting, "implied_rate": rate})
    return pd.DataFrame(rows)


def _bank_divergence(bank_spec, key, a, b, inertia, today):
    """Mean model−market divergence (bp) over the next 3 meetings, or NaN."""
    bank_inputs = get_policy_inputs(bank_spec.code)
    if bank_inputs.anchor_rate is not None:
        bank_anchor = bank_inputs.anchor_rate
    elif bank_inputs.yields:
        bank_anchor = bank_inputs.yields[min(bank_inputs.yields)]
    else:
        return float("nan")
    if not bank_inputs.yields:
        return float("nan")
    path = implied_forward_path(bank_inputs.yields, anchor_rate=bank_anchor)
    scraped = [d for d in get_meeting_dates(bank_spec.calendar_code) if d >= today]
    market = _market_at_meetings(path, scraped or bank_spec.meeting_fallback, today)
    if market.empty:
        return float("nan")
    model = model_path(
        list(market["meeting"]), current_rate=bank_anchor, macro=get_macro(bank_spec.code, key),
        inflation_target=bank_spec.inflation_target, neutral=bank_spec.neutral_nominal, a=a, b=b, inertia=inertia,
    )
    merged = merge_paths(market, model)
    return float(merged.head(3)["divergence_bp"].mean()) if not merged.empty else float("nan")


def _render_policy_path(
    path, anchor_rate, meeting_dates, meeting_source, *, meeting_label, yaxis_title, dot_plot=None, dot_label=None, compare_path=None, compare_label=None, model_df=None
):
    """The implied-path chart plus the per-meeting implied-rate table, shown
    inline. compare_path overlays a prior date's pricing; model_df overlays
    the own-model path and adds model/divergence columns."""
    today = date.today()
    path_dates = [today + pd.Timedelta(days=round(h * 365)) for h in path["horizon_years"]]
    last_date = path_dates[-1]
    model_lookup = dict(zip(model_df["meeting"], model_df["model_rate"])) if model_df is not None and not model_df.empty else {}

    fig = go.Figure()
    if model_lookup:
        fig.add_trace(
            go.Scatter(x=list(model_lookup), y=list(model_lookup.values()), mode="lines+markers",
                       line=dict(color=CATEGORICAL[2], width=2, dash="dash"), marker=dict(size=7), name="Own model")
        )
    if compare_path is not None:
        compare_dates = [today + pd.Timedelta(days=round(h * 365)) for h in compare_path["horizon_years"]]
        fig.add_trace(
            go.Scatter(x=compare_dates, y=compare_path["rate"], mode="lines",
                       line=dict(color=CATEGORICAL[3], width=2, dash="dot"), name=compare_label)
        )
    fig.add_trace(
        go.Scatter(x=path_dates, y=path["rate"], mode="lines+markers",
                   line=dict(color=CATEGORICAL[0], width=3), marker=dict(size=8), name="Market-implied path (now)")
    )
    if dot_plot:
        dots = [(date(y, 12, 31), r) for y, r in sorted(dot_plot.items()) if date(y, 12, 31) <= last_date]
        if dots:
            fig.add_trace(
                go.Scatter(x=[d for d, _ in dots], y=[r for _, r in dots], mode="markers",
                           marker=dict(color=CATEGORICAL[5], size=13, symbol="diamond"), name=dot_label)
            )
    fig.update_layout(yaxis_title=yaxis_title, legend_title=None, hovermode="x unified")
    render(fig)

    st.markdown(f"**Implied rate at each upcoming {meeting_label} meeting**")
    prior_rate = anchor_rate
    rows = []
    for meeting in sorted(meeting_dates):
        if meeting < today or meeting > last_date:
            continue
        horizon = (meeting - today).days / 365.0
        rate = implied_rate_at(path, horizon)
        if rate is None:
            continue
        row = {
            "Meeting": meeting.strftime("%d %b %Y"),
            "Implied rate (%)": round(rate, 3),
            "Cumulative vs now (bps)": round((rate - anchor_rate) * 100, 0),
            "Change since prior meeting (bps)": round((rate - prior_rate) * 100, 0),
        }
        if compare_path is not None:
            was = implied_rate_at(compare_path, horizon)
            if was is not None:
                row["Repriced since compare (bps)"] = round((rate - was) * 100, 0)
        if meeting in model_lookup:
            row["Model rate (%)"] = round(model_lookup[meeting], 3)
            row["Divergence (bps)"] = round((model_lookup[meeting] - rate) * 100, 0)
        rows.append(row)
        prior_rate = rate
    if rows:
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    else:
        st.caption(f"No upcoming {meeting_label} meetings fall within the curve's horizon.")
    st.caption(f"Meeting dates: {meeting_source}.")


def _render_validation_expander(raw_yields, anchor_rate, status):
    with st.expander("Raw inputs fetched (validation)"):
        st.markdown("**Live status:** " + " · ".join(status))
        if raw_yields:
            curve = pd.DataFrame(
                [{"Maturity": _maturity_label(y), "Market yield (%)": round(raw_yields[y], 3)} for y in sorted(raw_yields)]
            )
            st.dataframe(curve, use_container_width=True, hide_index=True)
            st.caption(
                f"Overnight anchor used: {anchor_rate:.2f}% (at horizon 0). Cross-check these "
                "against the origin links on the Data sources tab."
            )
        else:
            st.markdown("**Raw curve fetched:** none — see the Data sources tab for the exact source it's trying.")


def _render_engine_path(path_df, anchor_rate, yaxis_title, bank_code):
    """STAGE 3 renderer: hv-step chart + table with the method column + CSV."""
    if path_df is None or path_df.empty:
        st.info("Path appears once Stage-1 raw data is loaded above.")
        return
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(x=path_df["decision"], y=path_df["implied_rate"], mode="lines+markers",
                   name="Implied post-meeting rate", line=dict(color=CATEGORICAL[0], width=3), line_shape="hv")
    )
    fig.add_hline(y=anchor_rate, line_dash="dot", annotation_text="current policy anchor")
    fig.update_layout(yaxis_title=yaxis_title, legend_title=None)
    render(fig)
    st.dataframe(path_df, use_container_width=True, hide_index=True)
    st.download_button(
        "Download path CSV", path_df.to_csv(index=False).encode(), file_name=f"{bank_code}_implied_path.csv"
    )
    st.caption(
        "The `method` column says how each number was produced — same-month deconvolution is the "
        "cleanest; next-month proxy and curve forwards deserve a wider error bar."
    )


# ------------------------- shared state (used by several tabs) --------------
bank_label = st.radio("Central bank", [s.label for s in CENTRAL_BANKS], horizontal=True)
spec = get_spec(bank_label)
inputs = get_policy_inputs(spec.code)
scraped_meetings = get_meeting_dates(spec.calendar_code)

today = date.today()
scraped_upcoming = [d for d in scraped_meetings if d >= today]
meetings = scraped_upcoming or [d for d in spec.meeting_fallback if d >= today]
meeting_source = (
    "live from the official calendar" if scraped_upcoming else f"maintained fallback list (verify against {spec.calendar_hint})"
)
mtg_objs = meetings_for(spec.code, scraped_meetings, today)

# A failed fetch must not sit in the cache for its full TTL looking permanent —
# clear so the next interaction retries.
if not inputs.yields:
    get_policy_inputs.clear()
if not scraped_upcoming:
    get_meeting_dates.clear()

# Anchor from real data only: live overnight rate, else shortest curve yield.
if inputs.anchor_rate is not None:
    anchor_default = inputs.anchor_rate
    anchor_metric_label = spec.anchor_metric_label
elif inputs.yields:
    shortest = min(inputs.yields)
    anchor_default = inputs.yields[shortest]
    anchor_metric_label = f"Front rate ({_maturity_label(shortest)} yield)"
else:
    anchor_default = 0.0
    anchor_metric_label = spec.anchor_metric_label

with st.sidebar:
    anchor = st.number_input(
        spec.anchor_label, min_value=-1.0, max_value=10.0, value=float(anchor_default), step=0.01, format="%.2f",
        key=f"{spec.code}_anchor",
        help="Anchors the front of the implied path. Defaults to the live overnight rate, "
        "or the shortest real curve yield when no overnight feed exists; override if needed.",
    )
    compare_on = st.checkbox(
        "Compare to a previous date", key=f"{spec.code}_compare_on",
        help="Overlay the implied path as it was priced on an earlier date to see how expectations shifted.",
    )
    compare_date = None
    if compare_on:
        earliest = min(inputs.history) if inputs.history else today - timedelta(days=30)
        compare_date = st.date_input(
            "As-of date", value=max(earliest, today - timedelta(days=7)), min_value=earliest, max_value=today,
            key=f"{spec.code}_compare_date",
        )

    st.divider()
    st.markdown("**Own model (optional)**")
    # st.secrets raises (not just returns empty) when no secrets.toml exists
    # at all — the default state; same guard as data/s3_cache.py.
    try:
        _fred_default = str(st.secrets.get("fred_api_key", ""))
    except Exception:
        _fred_default = ""
    fred_key = st.text_input(
        "FRED API key", type="password", key="fred_key",
        value=_fred_default,
        help="Free at fred.stlouisfed.org (Account → API Keys); prefer setting `fred_api_key` in "
        "Streamlit secrets. Activates the Taylor-gap model overlay, the divergence signals, and "
        "model columns in snapshots. Market paths work without it.",
    )
    model_a = st.slider("Inflation-gap weight (a)", 0.0, 1.5, 0.5, 0.05, key="model_a")
    model_b = st.slider("Employment-gap weight (b)", 0.0, 1.5, 0.5, 0.05, key="model_b")
    model_inertia = st.slider("Policy inertia (gap closed per meeting)", 0.05, 0.6, 0.25, 0.05, key="model_inertia")

base_curve_path = implied_forward_path(inputs.yields, anchor_rate=anchor) if inputs.yields else pd.DataFrame()

tab_paths, tab_method, tab_signals, tab_sources, tab_model = st.tabs(
    ["Policy paths", "Methodology", "Daily signals", "Data sources", "Model rationale"]
)


# ----------------------------- Policy paths tab -----------------------------
with tab_paths:
    st.caption(
        "Data sources — " + " · ".join(inputs.status)
        + f" · Meetings: {'official calendar' if scraped_upcoming else 'fallback list'}"
        + " · full listing on the Data sources tab"
    )

    compare_path = compare_label = None
    if compare_on and compare_date:
        if inputs.history:
            as_of, curve = _curve_as_of(inputs.history, compare_date)
            if curve:
                compare_path = implied_forward_path(curve, anchor_rate=anchor)
                compare_label = f"As priced on {as_of.strftime('%d %b %Y')}"
        if compare_path is None:
            st.caption("No stored curve is available on or before that date to compare against.")

    if not inputs.yields:
        st.info(
            f"The {spec.label} yield-curve feed isn't available right now — the source status "
            "above says which feeds failed, and it will retry on the next interaction. The Data "
            "sources tab lists (and links) the exact source it's trying."
        )
    else:
        year_end_rate = implied_rate_at(base_curve_path, (date(today.year, 12, 31) - today).days / 365.0)
        metric_row(
            [
                (anchor_metric_label, f"{anchor:.2f}%"),
                *inputs.metrics,
                (
                    f"Implied by end-{today.year}",
                    f"{year_end_rate:.2f}%" if year_end_rate is not None else "N/A",
                    f"{(year_end_rate - anchor) * 100:+.0f} bps" if year_end_rate is not None else None,
                ),
            ]
        )
        market_df = _market_at_meetings(base_curve_path, meetings, today)
        model_df = merged = None
        if fred_key and not market_df.empty:
            model_df = model_path(
                list(market_df["meeting"]), current_rate=anchor, macro=get_macro(spec.code, fred_key),
                inflation_target=spec.inflation_target, neutral=spec.neutral_nominal,
                a=model_a, b=model_b, inertia=model_inertia,
            )
            merged = merge_paths(market_df, model_df)

        _render_policy_path(
            base_curve_path, anchor, meetings, meeting_source,
            meeting_label=spec.meeting_label, yaxis_title=spec.yaxis_title,
            dot_plot=spec.dot_plot, dot_label=spec.dot_label,
            compare_path=compare_path, compare_label=compare_label, model_df=model_df,
        )
        if compare_label:
            st.caption(
                "Dotted line: the implied path as priced on the selected date, using that day's "
                "curve anchored at the current overnight rate."
            )
        if merged is not None and not merged.empty:
            sig = outright_signal(merged)
            badge = {0: "⚪", 1: "🟡", 2: "🔴"}[sig["conviction"]]
            st.markdown(f"#### {badge} Outright signal — {sig['signal']}")
            st.caption(
                f"Own model vs market: {sig['divergence_bp']:+.0f} bp average divergence over the next 3 "
                f"meetings (model r* = {model_df['r_star'].iloc[0]:.2f}%). See the Model rationale tab."
            )

    _render_validation_expander(inputs.yields, anchor, inputs.status)

    if fred_key:
        st.divider()
        st.subheader("Cross-market signals — model vs market")
        divergences = {s.code: _bank_divergence(s, fred_key, model_a, model_b, model_inertia, today) for s in CENTRAL_BANKS}
        valid = {k: v for k, v in divergences.items() if not pd.isna(v)}
        if len(valid) >= 2:
            table = build_signal_table(valid)
            table["conviction"] = table["conviction"].map({0: "—", 1: "Medium", 2: "High"})
            st.dataframe(
                table.rename(columns={"type": "Type", "pair": "Pair", "signal": "Signal", "rel_divergence_bp": "Rel. divergence (bp)", "conviction": "Conviction"}),
                use_container_width=True, hide_index=True,
            )
        else:
            st.info("Need at least two banks with both a live curve and macro data for cross-market signals.")
        st.caption(
            "Signals are model-minus-market divergences — a research scaffold, not investment "
            "advice (see the Model rationale tab for limitations)."
        )


# ----------------------------- Methodology tab ------------------------------
with tab_method:
    st.subheader(f"{spec.label} — instrument-based path, stage by stage")
    st.caption(
        "The brief's three-stage pipeline: raw quotes exactly as sourced → adjusted into "
        "policy-rate space (index basis) → deconvolved per-meeting path keyed on EFFECTIVE "
        "dates. The Policy paths tab's curve forwards remain the always-on baseline; this tab "
        "rebuilds the path from the preferred instrument and labels every number's method."
    )

    st.markdown("### 1 · Meeting dates & effective-date convention")
    st.markdown(f"**Convention ({spec.label}):** {CONVENTION_NOTES.get(spec.code, '')}")
    if mtg_objs:
        st.dataframe(eng.meeting_table(mtg_objs), use_container_width=True, hide_index=True)
        st.caption(
            "pre/post weights = share of the effective-date month at the old vs new rate — the "
            "deconvolution weights. 'tentative' rows: verify when official calendars update "
            "(maintenance: extend each December)."
        )

    st.markdown("### 2 · Preliminary (raw) data")
    basis_default = spec.basis_bp_default
    raw = adj = engine_path = None
    if spec.code == "fed":
        st.markdown(
            "CME 30-Day Fed Funds futures (ZQ) via Yahoo (`ZQ<M><YY>.CBT`) — settles to the "
            "monthly average **EFFR**, the policy target itself. Quotes are delayed and can be "
            "stale in deferred months (check `quote_date`); verify against CME settlements "
            "before acting."
        )
        load = st.checkbox("Load live ZQ quotes (slow, ~15s)", key="load_zq")
        if load:
            n_months = st.slider("Contract months to fetch", 6, 18, 14, key="zq_months")
            raw = get_zq_futures(n_months)
            if raw.empty:
                get_zq_futures.clear()
                st.warning("No ZQ quotes returned (Yahoo unreachable or blocked). The curve-forward fallback below still works.")
    elif spec.code == "ecb":
        st.markdown(
            "Eurex 3M €STR futures **daily settlements** (free CSV from eurex.com) — €STR tracks "
            "the deposit facility rate directly. Upload `contract,price` rows where contract is "
            "the delivery month `YYYY-MM` (e.g. `2026-09,98.15`). Quarterly granularity is "
            "handled by the equal-step fit below."
        )
        up = st.file_uploader("Eurex €STR settlements CSV (contract,price)", type="csv", key="ecb_csv")
        if up is not None:
            raw = eng.parse_estr_futures_csv(up)
            if raw is None:
                st.warning("Couldn't parse that CSV — expected columns `contract,price` with contract as `YYYY-MM`.")
    elif spec.code == "boe":
        st.markdown(
            "The Bank of England's **daily OIS instantaneous-forward curve** (auto-downloaded "
            "from the latest-yield-curve zip) — institutional-grade OIS on SONIA, one business "
            "day's lag. The smooth Svensson-fitted curve biases imminent-meeting steps a few bp "
            "toward zero."
        )
        load = st.checkbox("Load the OIS forward curve", key="load_boe_fwd")
        if load:
            raw = get_boe_forward_curve()
            if raw.empty:
                get_boe_forward_curve.clear()
                st.warning("Couldn't fetch/parse the BoE forward sheet. The curve-forward fallback below still works.")
    else:
        st.info(
            "The engine brief doesn't cover the BoJ (no free futures/OIS feed). The path below "
            "uses the JGB curve-forward fallback."
        )
    if raw is not None and not getattr(raw, "empty", True):
        st.dataframe(raw, use_container_width=True, hide_index=True)

    st.markdown("### 3 · Adjusted data")
    basis_bp = st.number_input(
        f"{spec.index_label or 'index'} − policy basis (bp)", value=float(basis_default), step=0.5,
        key=f"{spec.code}_basis",
        help="The overnight index the instrument settles to trades a few bp off the policy "
        "anchor. policy = index − basis. Drifts with money-market conditions — re-measure "
        "periodically rather than hardcoding.",
    )
    st.caption(
        f"Adjustments: (1) price → rate (100 − price) where applicable; (2) subtract the "
        f"{spec.index_label or 'index'}−policy basis ({basis_bp:+.1f}bp) so the path reads in "
        "policy terms; (3) NOT adjusted: term premium in deferred contracts — the path is "
        "expectations + term premium, which is why signals weight the front 3 meetings."
    )
    if raw is not None and not getattr(raw, "empty", True):
        if spec.code == "fed":
            adj = eng.adjust_ff(raw, basis_bp)
        elif spec.code == "ecb":
            adj = eng.adjust_estr(raw, basis_bp)
        elif spec.code == "boe":
            adj = eng.adjust_boe(raw, basis_bp)
        if adj is not None:
            st.dataframe(adj, use_container_width=True, hide_index=True)

    st.markdown("### 4 · Market-implied policy path")
    if adj is not None and not adj.empty and mtg_objs:
        if spec.code == "fed":
            engine_path = eng.path_from_monthly_avg(adj, anchor, mtg_objs)
        elif spec.code == "ecb":
            engine_path = eng.path_from_quarterly_avg(adj, anchor, mtg_objs)
        elif spec.code == "boe":
            engine_path = eng.path_from_forward_curve(adj, anchor, mtg_objs, today)
    if (engine_path is None or engine_path.empty) and not base_curve_path.empty and mtg_objs:
        engine_path = eng.path_from_yield_curve(base_curve_path, anchor, mtg_objs, today, source_label="curve forward (proxy)")
        st.caption("Showing the curve-forward fallback — load Stage-1 data above for the instrument-based path.")
    _render_engine_path(engine_path, anchor, spec.yaxis_title, spec.code)
    if spec.code == "ecb" and engine_path is not None and not engine_path.empty:
        st.session_state["ecb_engine_path"] = engine_path

    with st.expander("Known limitations (read before acting)"):
        st.markdown(
            "1. Yahoo ZQ quotes are delayed/stale in deferred months — verify against CME settlements.\n"
            "2. The ECB fit smears multi-meeting quarters (equal-step identification constraint); "
            "true meeting-level precision needs meeting-dated OIS (paid) or liquid 1M €STR futures.\n"
            "3. The BoE curve is Svensson-smoothed: imminent-meeting steps bias a few bp toward zero.\n"
            "4. Basis spreads drift with money-market conditions — re-measure, don't hardcode.\n"
            "5. Divergence-fading assumes the model anchors and the market converges; sometimes the "
            "model is wrong. Stretched readings are candidates, not orders — backtest against "
            "accumulated snapshots before sizing.\n"
            "6. Meeting calendars need manual extension each December; 2027 dates are tentative."
        )


# ----------------------------- Daily signals tab ----------------------------
with tab_signals:
    st.subheader("Daily trading signals")
    st.caption(s3sync.status())
    ref_col, note_col = st.columns([1, 3])
    with ref_col:
        if st.button("Refresh & snapshot now"):
            with st.spinner("Running the full refresh (fetch → paths → signals → snapshot)..."):
                extra = {}
                ecb_path = st.session_state.get("ecb_engine_path")
                if ecb_path is not None and not getattr(ecb_path, "empty", True):
                    extra["ecb"] = ecb_path
                refresh_job.run(
                    fred_key or None, extra_market_paths=extra,
                    model_params={"a": model_a, "b": model_b, "inertia": model_inertia},
                )
            st.cache_data.clear()
            st.success("Snapshot saved.")
            st.rerun()
    with note_col:
        st.caption(
            "Same job as `python -m data.refresh --fred-key KEY` (schedule weekdays ~07:30 UK, "
            "after the BoE curve publishes). Single-writer rule: prefer the scheduled job; this "
            "button is for ad-hoc runs."
        )

    paths_hist = store.load_paths()
    if paths_hist.empty:
        st.info(
            "No snapshots yet. Run a refresh (button above, or the CLI) — history builds daily; "
            "z-scores need ~15 sessions."
        )
        st.dataframe(INSTRUMENTS, use_container_width=True, hide_index=True)
    else:
        bank_codes = [s.code for s in CENTRAL_BANKS]
        labels = {s.code: s.label for s in CENTRAL_BANKS}
        asofs = sorted(paths_hist["asof"].unique())
        latest, prev = asofs[-1], (asofs[-2] if len(asofs) > 1 else None)
        st.caption(
            f"Latest snapshot: {pd.Timestamp(latest).date()}"
            + (f" · previous: {pd.Timestamp(prev).date()}" if prev is not None else "")
        )

        st.markdown("### 1 · Overnight repricing (market path Δ)")
        cols = st.columns(len(bank_codes))
        for col, code in zip(cols, bank_codes):
            with col:
                b = paths_hist[paths_hist["bank"] == code].sort_values("decision")
                cur = b[b["asof"] == latest].set_index("decision")["implied_rate"].dropna()
                if cur.empty:
                    st.metric(labels[code], "no data")
                    continue
                if prev is not None:
                    old = b[b["asof"] == prev].set_index("decision")["implied_rate"]
                    delta = ((cur - old) * 100).dropna()
                    front = delta.iloc[0] if len(delta) else float("nan")
                    st.metric(
                        f"{labels[code]} front meeting", f"{cur.iloc[0]:.2f}%",
                        f"{front:+.1f}bp vs prev" if not pd.isna(front) else None, delta_color="inverse",
                    )
                    if len(delta):
                        fig = go.Figure(go.Bar(x=delta.index, y=delta.values, marker_color=CATEGORICAL[0]))
                        fig.update_layout(height=180, yaxis_title="Δ bp", margin=dict(t=10, b=10))
                        st.plotly_chart(fig, use_container_width=True)
                else:
                    st.metric(f"{labels[code]} front meeting", f"{cur.iloc[0]:.2f}%")

        st.markdown("### 2 · Model-vs-market divergence (front 3 meetings)")
        fig = go.Figure()
        zrows = []
        for i, code in enumerate(bank_codes):
            h = store.divergence_history(code)
            if h.empty:
                continue
            fig.add_trace(go.Scatter(x=h.index, y=h.values, name=labels[code], mode="lines+markers",
                                     line=dict(color=CATEGORICAL[i % len(CATEGORICAL)])))
            z = store.zscore(h)
            zrows.append(
                {
                    "bank": labels[code], "divergence_bp": round(h.iloc[-1], 1),
                    "zscore_60d": round(z, 2) if z is not None else "n/a (<15 obs)",
                    "stretched": "YES" if z is not None and abs(z) > 1.5 else "",
                }
            )
        fig.add_hrect(y0=-10, y1=10, fillcolor="gray", opacity=0.15, line_width=0)
        fig.update_layout(height=340, yaxis_title="model − market (bp)", legend=dict(orientation="h"))
        st.plotly_chart(fig, use_container_width=True)
        if zrows:
            st.dataframe(pd.DataFrame(zrows), use_container_width=True, hide_index=True)
        st.caption(
            "Grey band = ±10bp neutral zone. The z-score flags whether today's divergence is "
            "stretched vs its own 60d history — fade stretched readings with care: divergence "
            "can mean the model is wrong."
        )

        st.markdown("### 3 · Signal board")
        sigs = store.load_signals()
        if not sigs.empty:
            latest_s = sigs[sigs["asof"] == sigs["asof"].max()].copy()
            if prev is not None:
                prev_s = sigs[sigs["asof"] == prev][["name", "signal"]]
                latest_s = latest_s.merge(prev_s, on="name", how="left", suffixes=("", "_prev"))
                latest_s["flip"] = (
                    (latest_s["signal"].ne(latest_s["signal_prev"]) & latest_s["signal_prev"].notna())
                    .map({True: "⚑ FLIPPED", False: ""})
                )
            show = [c for c in ["name", "signal", "value_bp", "conviction", "flip"] if c in latest_s]
            st.dataframe(latest_s[show].sort_values("conviction", ascending=False), use_container_width=True, hide_index=True)

        st.markdown("### 4 · FX spots vs relative divergence")
        fx = store.load_fx()
        if fx.empty:
            st.caption("No FX history yet — spots are captured by each refresh.")
        else:
            fx_names = {
                f"{a}_{b}_fx": FX_PAIRS.get(frozenset({a, b}))
                for i, a in enumerate(bank_codes)
                for b in bank_codes[i + 1:]
                if FX_PAIRS.get(frozenset({a, b}))
            }
            available = [(n, p) for n, p in fx_names.items() if p in set(fx["pair"])]
            if available:
                fx_tabs = st.tabs([p for _, p in available])
                for t, (sig_name, pair) in zip(fx_tabs, available):
                    with t:
                        f = fx[fx["pair"] == pair].sort_values("asof")
                        s = sigs[sigs["name"] == sig_name].sort_values("asof") if not sigs.empty else pd.DataFrame()
                        fig = go.Figure()
                        fig.add_trace(go.Scatter(x=f["asof"], y=f["spot"], name="spot", line=dict(color=CATEGORICAL[0])))
                        if not s.empty:
                            fig.add_trace(go.Scatter(x=s["asof"], y=s["value_bp"], name="rel divergence (bp)",
                                                     yaxis="y2", line=dict(color=CATEGORICAL[2])))
                        fig.update_layout(height=300, yaxis2=dict(overlaying="y", side="right", title="bp"))
                        st.plotly_chart(fig, use_container_width=True)

        st.markdown("### 5 · Instrument mapping")
        st.dataframe(INSTRUMENTS, use_container_width=True, hide_index=True)
        st.caption(
            "Divergence horizons are the front 3 meetings, so the cleanest expressions are the "
            "front futures strip or 1y–2y OIS; longer tenors dilute the signal with term premium."
        )


# ----------------------------- Data sources tab -----------------------------
with tab_sources:
    st.subheader("Live data sources by central bank")
    st.caption(
        "Every number on the Policy paths tab comes from one of the sources below — all free "
        "and keyless (the optional FRED macro model needs a free key). Tap any link to check "
        "the raw numbers against the origin; the per-bank 'Raw inputs fetched' expander shows "
        "exactly what was pulled on this load."
    )
    for s in CENTRAL_BANKS:
        st.markdown(f"#### {s.label}")
        if s.instrument_note:
            st.markdown(f"- {s.instrument_note}")
        for label, url in s.sources:
            st.markdown(f"- [{label}]({url})")
        st.markdown(
            f"- Meeting dates — scraped best-effort from the official calendar ({s.calendar_hint}); "
            "a maintained fallback list in `data/constants.py` is used when the scrape fails. "
            "Effective-date conventions per bank are on the Methodology tab"
        )
        if s.dot_plot:
            st.markdown(f"- Projection overlay — {s.dot_label}, hand-entered from the official release (federalreserve.gov)")
        if s.macro_series:
            codes = ", ".join(f"`{code}`" for code in s.macro_series.values())
            st.markdown(f"- Own-model macro (FRED, optional key): {codes}")

    st.markdown("---")
    st.markdown(
        "**How the baseline market-implied path is derived.** A yield to maturity *t* is "
        "(roughly) the market's expected *average* overnight rate over the next *t* years, so "
        "the implied **forward** rate between two maturities is the expected average over that "
        "future window:\n\n"
        "```\nforward(a, b) = (yield_b × b − yield_a × a) / (b − a)\n```\n\n"
        "Chaining these forwards, anchored at horizon 0 to the overnight rate, traces the "
        "implied path. It is a curve-implied **proxy** (term premium + safe-haven richness read "
        "marginally dovish vs pure OIS/futures). The Methodology tab rebuilds the path from the "
        "preferred instrument per bank with per-meeting deconvolution and a `method` label on "
        "every number."
    )
    st.caption(
        "Macro-series caveat: US codes (core PCE, UNRATE, NFCI) are first-rate; euro-area/UK/"
        "Japan currently use best-effort codes (headline CPI, OECD unemployment) — treat their "
        "model signals as indicative until upgraded."
    )


# ----------------------------- Model rationale tab --------------------------
with tab_model:
    if _MODEL_DOC.exists():
        st.markdown(_MODEL_DOC.read_text())
    else:
        st.info("Model documentation (docs/MODEL.md) not found in this deployment.")
