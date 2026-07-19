from datetime import date, timedelta

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from data.central_banks import CENTRAL_BANKS, get_spec
from data.sources import get_macro, get_meeting_dates, get_policy_inputs
from fed_path import implied_forward_path, implied_rate_at
from policy_model import model_path
from signals import build_signal_table, merge_paths, outright_signal
from ui import metric_row, render
from viz_theme import CATEGORICAL

st.set_page_config(page_title="Central Bank Paths — Derivatives Monitor", page_icon="📈", layout="wide")
st.title("Central bank policy paths (market-implied)")
st.caption(
    "Where the market expects each central bank's policy rate to go, implied by its short-end "
    "government (or OIS) curve — free, keyless sources with independent fallbacks. Add a free "
    "FRED API key in the sidebar to overlay an **own model** (a Taylor-gap rule you tune with "
    "sliders) and turn the model-vs-market divergence into outright, cross-bank spread, and FX "
    "signals. A curve-implied proxy, not a live policy-expectations curve; the model is a "
    "research scaffold, not a forecast."
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


def _derive_anchor(inputs):
    """The overnight anchor from real data: live rate, else shortest curve yield."""
    if inputs.anchor_rate is not None:
        return inputs.anchor_rate
    if inputs.yields:
        return inputs.yields[min(inputs.yields)]
    return None


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


def _bank_divergence(spec, fred_key, a, b, inertia, today):
    """Mean model−market divergence (bp) over the next 3 meetings, or NaN."""
    inputs = get_policy_inputs(spec.code)
    anchor = _derive_anchor(inputs)
    if not inputs.yields or anchor is None:
        return float("nan")
    path = implied_forward_path(inputs.yields, anchor_rate=anchor)
    scraped = [d for d in get_meeting_dates(spec.calendar_code) if d >= today]
    meetings = scraped or spec.meeting_fallback
    market = _market_at_meetings(path, meetings, today)
    if market.empty:
        return float("nan")
    macro = get_macro(spec.code, fred_key)
    model = model_path(
        list(market["meeting"]), current_rate=anchor, macro=macro,
        inflation_target=spec.inflation_target, neutral=spec.neutral_nominal, a=a, b=b, inertia=inertia,
    )
    merged = merge_paths(market, model)
    return float(merged.head(3)["divergence_bp"].mean()) if not merged.empty else float("nan")


def _render_policy_path(
    path, anchor_rate, meeting_dates, meeting_source, *, meeting_label, yaxis_title, dot_plot=None, dot_label=None, compare_path=None, compare_label=None, model_df=None
):
    """The implied-path chart plus the per-meeting implied-rate table, shown
    inline (not collapsed) so the meeting-by-meeting detail is visible, not
    just the year-end figure. When `compare_path` is given, a prior date's
    implied path is overlaid and the table gains a repricing column. When
    `model_df` is given, the own-model path is overlaid (dashed) and the table
    gains model-rate and divergence columns."""
    today = date.today()
    path_dates = [today + pd.Timedelta(days=round(h * 365)) for h in path["horizon_years"]]
    last_date = path_dates[-1]
    model_lookup = dict(zip(model_df["meeting"], model_df["model_rate"])) if model_df is not None and not model_df.empty else {}

    fig = go.Figure()
    if model_lookup:
        fig.add_trace(
            go.Scatter(
                x=list(model_lookup),
                y=list(model_lookup.values()),
                mode="lines+markers",
                line=dict(color=CATEGORICAL[2], width=2, dash="dash"),
                marker=dict(size=7),
                name="Own model",
            )
        )
    if compare_path is not None:
        compare_dates = [today + pd.Timedelta(days=round(h * 365)) for h in compare_path["horizon_years"]]
        fig.add_trace(
            go.Scatter(
                x=compare_dates,
                y=compare_path["rate"],
                mode="lines",
                line=dict(color=CATEGORICAL[3], width=2, dash="dot"),
                name=compare_label,
            )
        )
    fig.add_trace(
        go.Scatter(
            x=path_dates,
            y=path["rate"],
            mode="lines+markers",
            line=dict(color=CATEGORICAL[0], width=3),
            marker=dict(size=8),
            name="Market-implied path (now)",
        )
    )
    if dot_plot:
        dots = [(date(y, 12, 31), r) for y, r in sorted(dot_plot.items()) if date(y, 12, 31) <= last_date]
        if dots:
            fig.add_trace(
                go.Scatter(
                    x=[d for d, _ in dots],
                    y=[r for _, r in dots],
                    mode="markers",
                    marker=dict(color=CATEGORICAL[5], size=13, symbol="diamond"),
                    name=dot_label,
                )
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


def _render_sources_panel(spec, raw_yields, anchor_rate, status):
    """A collapsible 'show your work' panel for validation: the exact raw
    sources (tap to check them), the actual yields fetched, and the formula
    that turns them into the implied path. Shown for every bank — including
    ones with no data, so an empty curve is diagnosable from the source link."""
    with st.expander("Data source & how it's derived (for validation)"):
        st.markdown("**Live status:** " + " · ".join(status))

        st.markdown("**Raw sources** (tap to verify the numbers against the origin):")
        for label, url in spec.sources:
            st.markdown(f"- [{label}]({url})")

        if raw_yields:
            st.markdown("**Raw curve fetched** (the exact inputs to the calculation):")
            curve = pd.DataFrame(
                [{"Maturity": _maturity_label(y), "Market yield (%)": round(raw_yields[y], 3)} for y in sorted(raw_yields)]
            )
            st.dataframe(curve, use_container_width=True, hide_index=True)
            st.caption(f"Overnight anchor used: {anchor_rate:.2f}% (at horizon 0).")
        else:
            st.markdown("**Raw curve fetched:** none — the curve source above returned no usable data.")

        st.markdown(
            "**Method.** A yield to maturity *t* is (roughly) the market's expected *average* "
            "overnight rate over the next *t* years, so the implied **forward** rate between two "
            "maturities is the expected average over that future window:\n\n"
            "```\nforward(a, b) = (yield_b × b − yield_a × a) / (b − a)\n```\n\n"
            "Chaining these forwards across the maturities above, anchored at horizon 0 to the "
            "overnight rate, traces the implied path; the meeting table reads that path at each "
            "meeting date (interpolated). It is a curve-implied **proxy**: it carries a little "
            "term premium and safe-haven/collateral richness, so it reads marginally more dovish "
            "than a pure OIS/futures measure — right on direction and rough magnitude, not "
            "basis-point-exact, and not a discrete hike/cut probability model."
        )


bank_label = st.radio("Central bank", [spec.label for spec in CENTRAL_BANKS], horizontal=True)
spec = get_spec(bank_label)
inputs = get_policy_inputs(spec.code)
scraped_meetings = get_meeting_dates(spec.calendar_code)

today = date.today()
# Use scraped dates only if they actually contain upcoming meetings — a scrape
# that returns only past meetings (seen with the ECB calendar) would otherwise
# leave the table empty instead of falling back to the maintained list.
scraped_upcoming = [d for d in scraped_meetings if d >= today]
meetings = scraped_upcoming or spec.meeting_fallback
meeting_source = (
    "live from the official calendar"
    if scraped_upcoming
    else f"maintained fallback list (verify against {spec.calendar_hint})"
)

# A failed fetch must not sit in the cache for its full TTL looking permanent
# (one bad FRED call used to pin "unavailable" for an hour on the deployed
# app) — clear so the next interaction retries.
if not inputs.yields:
    get_policy_inputs.clear()
if not scraped_upcoming:
    get_meeting_dates.clear()

st.caption(
    "Data sources — "
    + " · ".join(inputs.status)
    + f" · Meetings: {'official calendar' if scraped_upcoming else 'fallback list'}"
)

# Anchor the path at real data only: the live overnight rate when a feed
# provides it, otherwise the shortest real curve yield (e.g. BoJ, which has no
# free overnight feed). No hardcoded rate is ever used.
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
        spec.anchor_label,
        min_value=-1.0,
        max_value=10.0,
        value=float(anchor_default),
        step=0.01,
        format="%.2f",
        key=f"{spec.code}_anchor",
        help="Anchors the front of the implied path. Defaults to the live overnight rate, "
        "or the shortest real curve yield when no overnight feed exists; override if needed.",
    )
    compare_on = st.checkbox(
        "Compare to a previous date",
        key=f"{spec.code}_compare_on",
        help="Overlay the implied path as it was priced on an earlier date to see how expectations shifted.",
    )
    compare_date = None
    if compare_on:
        earliest = min(inputs.history) if inputs.history else today - timedelta(days=30)
        compare_date = st.date_input(
            "As-of date",
            value=max(earliest, today - timedelta(days=7)),
            min_value=earliest,
            max_value=today,
            key=f"{spec.code}_compare_date",
        )

    st.divider()
    st.markdown("**Own model (optional)**")
    fred_key = st.text_input(
        "FRED API key",
        type="password",
        key="fred_key",
        help="Free at fred.stlouisfed.org (Account → API Keys). Activates the Taylor-gap "
        "model overlay and the cross-market signals. Market paths work without it.",
    )
    model_a = st.slider("Inflation-gap weight (a)", 0.0, 1.5, 0.5, 0.05, key="model_a")
    model_b = st.slider("Employment-gap weight (b)", 0.0, 1.5, 0.5, 0.05, key="model_b")
    model_inertia = st.slider("Policy inertia (gap closed per meeting)", 0.05, 0.6, 0.25, 0.05, key="model_inertia")

# Build the comparison path from the curve as it stood on (or just before) the
# chosen date. It's anchored at the current overnight rate for simplicity — the
# repricing story lives in the curve, and the overnight rate barely moves
# between meetings.
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
        "above says which feeds failed, and it will retry on the next interaction. Open the "
        "panel below to see (and tap) the exact source it's trying."
    )
else:
    path = implied_forward_path(inputs.yields, anchor_rate=anchor)
    year_end_rate = implied_rate_at(path, (date(today.year, 12, 31) - today).days / 365.0)
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
    # Own-model overlay (Taylor-gap + momentum) when a FRED key is provided.
    market_df = _market_at_meetings(path, meetings, today)
    model_df = merged = None
    if fred_key and not market_df.empty:
        macro = get_macro(spec.code, fred_key)
        model_df = model_path(
            list(market_df["meeting"]), current_rate=anchor, macro=macro,
            inflation_target=spec.inflation_target, neutral=spec.neutral_nominal,
            a=model_a, b=model_b, inertia=model_inertia,
        )
        merged = merge_paths(market_df, model_df)

    _render_policy_path(
        path,
        anchor,
        meetings,
        meeting_source,
        meeting_label=spec.meeting_label,
        yaxis_title=spec.yaxis_title,
        dot_plot=spec.dot_plot,
        dot_label=spec.dot_label,
        compare_path=compare_path,
        compare_label=compare_label,
        model_df=model_df,
    )
    if compare_label:
        st.caption(
            "Dotted line: the implied path as priced on the selected date, using that day's "
            "curve anchored at the current overnight rate. The repricing column shows how each "
            "meeting's implied rate has moved since then."
        )
    if merged is not None and not merged.empty:
        sig = outright_signal(merged)
        badge = {0: "⚪", 1: "🟡", 2: "🔴"}[sig["conviction"]]
        st.markdown(f"#### {badge} Outright signal — {sig['signal']}")
        st.caption(
            f"Own model vs market: {sig['divergence_bp']:+.0f} bp average divergence over the next 3 "
            f"meetings (model r* = {model_df['r_star'].iloc[0]:.2f}%). Dashed green line is the model path."
        )

_render_sources_panel(spec, inputs.yields, anchor, inputs.status)

# --- Cross-market signals (needs the model, i.e. a FRED key, for 2+ banks) ---
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
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("Need at least two banks with both a live curve and macro data for cross-market signals.")
    st.caption(
        "Signals are model-minus-market divergences — a research scaffold, not investment advice. "
        "Euro-area/UK/Japan macro series are best-effort (headline CPI / OECD unemployment); verify "
        "before relying on their signals. Validate everything against primary sources."
    )
