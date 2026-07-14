from datetime import date

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from data.constants import (
    CURRENT_EFFR_DEFAULT,
    FOMC_MEETING_DATES_2026,
    SEP_AS_OF,
    SEP_DOT_PLOT_MEDIAN,
)
from data.sources import get_fed_funds_futures
from fed_path import meeting_expectations, step_probabilities
from ui import empty_state, metric_row, render
from viz_theme import CATEGORICAL

st.set_page_config(page_title="Fed Path — Derivatives Monitor", page_icon="📈", layout="wide")
st.title("Market-implied Fed path")
st.caption(
    "The policy-rate path priced into CME 30-Day Fed Funds futures (the same contracts "
    "behind CME's FedWatch), with per-meeting hike/cut/hold probabilities. Delayed, "
    "free data — an approximation of a live curve, not a live curve, and the only page "
    "that depends on CME rather than DTCC/CFTC."
)

with st.sidebar:
    current_effr = st.number_input(
        "Current effective fed funds rate (EFFR), %",
        min_value=0.0,
        max_value=10.0,
        value=float(CURRENT_EFFR_DEFAULT),
        step=0.01,
        format="%.2f",
        help=(
            "Anchors the front of the implied path. Set this to the current EFFR "
            "(NY Fed / FRED series EFFR); the default is a placeholder."
        ),
    )

futures = get_fed_funds_futures()

if futures.empty:
    empty_state(
        "Couldn't load Fed Funds futures from CME right now. The endpoint is delayed and "
        "occasionally blocks automated requests — try again in a moment. (This is expected "
        "when running outside Streamlit Cloud, where the CME host may be unreachable.)",
        kind="warning",
    )

today = date.today()
expectations = meeting_expectations(
    futures, FOMC_MEETING_DATES_2026, current_rate=current_effr, as_of=today
)

if not expectations:
    empty_state(
        "Loaded the futures strip, but none of the configured FOMC meeting dates fall "
        "within it (or all are in the past). Check FOMC_MEETING_DATES_2026 in "
        "data/constants.py against the published FOMC calendar."
    )

next_meeting = expectations[0]
next_probs = step_probabilities(next_meeting.change)
most_likely_move, most_likely_prob = max(next_probs, key=lambda o: o[1])
final_rate = expectations[-1].rate_after

metric_row(
    [
        ("Next meeting", next_meeting.meeting_date.strftime("%d %b %Y")),
        (
            "Priced for next meeting",
            f"{most_likely_move * 100:+.0f} bps" if most_likely_move else "No change",
            f"{most_likely_prob * 100:.0f}% likely",
        ),
        ("Implied cuts to year-end", f"{(final_rate - current_effr) * 100:+.0f} bps"),
    ]
)

st.subheader("Implied policy-rate path")
path = pd.DataFrame(
    {"date": [today] + [e.meeting_date for e in expectations], "rate": [current_effr] + [e.rate_after for e in expectations]}
)
fig = go.Figure()
fig.add_trace(
    go.Scatter(
        x=path["date"],
        y=path["rate"],
        mode="lines+markers",
        line=dict(color=CATEGORICAL[0], width=3, shape="hv"),
        marker=dict(size=8),
        name="Market-implied (futures)",
    )
)
# Only overlay dot-plot medians for years the market path actually reaches,
# so a multi-year dot plot doesn't stretch the x-axis past the (shorter)
# futures curve and crush the path into a corner.
last_year = expectations[-1].meeting_date.year
dots = [(date(year, 12, 31), rate) for year, rate in sorted(SEP_DOT_PLOT_MEDIAN.items()) if year <= last_year]
if dots:
    fig.add_trace(
        go.Scatter(
            x=[d for d, _ in dots],
            y=[r for _, r in dots],
            mode="markers",
            marker=dict(color=CATEGORICAL[5], size=13, symbol="diamond"),
            name=f"Dot plot median — {SEP_AS_OF}",
        )
    )
fig.update_layout(yaxis_title="Fed funds rate (%)", legend_title=None, hovermode="x unified")
render(fig)

st.subheader("Per-meeting expectations")
st.caption(
    "Each meeting's expected move is split across the two adjacent 25bp outcomes that "
    "bracket it — the standard FedWatch simplification, so 'most likely move' is the "
    "higher-probability of those two, not a full distribution over every possible step."
)
rows = []
for exp in expectations:
    move, prob = max(step_probabilities(exp.change), key=lambda o: o[1])
    rows.append(
        {
            "Meeting": exp.meeting_date.strftime("%d %b %Y"),
            "Implied rate after (%)": round(exp.rate_after, 3),
            "Expected change (bps)": round(exp.change * 100, 1),
            "Most likely move": "No change" if move == 0 else f"{move * 100:+.0f} bps",
            "Probability": f"{prob * 100:.0f}%",
        }
    )
st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

st.subheader(f"Next meeting outcome probabilities — {next_meeting.meeting_date.strftime('%d %b %Y')}")
prob_df = pd.DataFrame(
    {
        "Outcome": ["No change" if move == 0 else f"{move * 100:+.0f} bps" for move, _ in next_probs],
        "Probability (%)": [round(prob * 100, 1) for _, prob in next_probs],
    }
)
fig_prob = px.bar(
    prob_df,
    x="Outcome",
    y="Probability (%)",
    color_discrete_sequence=[CATEGORICAL[2]],
    labels={"Outcome": "", "Probability (%)": "Probability (%)"},
)
render(fig_prob)

with st.expander("Show futures strip"):
    strip = futures.copy()
    strip["implied_rate"] = (100.0 - strip["price"]).round(3)
    strip["contract_month"] = strip["contract_month"].dt.strftime("%b %Y")
    st.dataframe(
        strip.rename(
            columns={"contract_month": "Contract", "price": "Price", "implied_rate": "Implied avg rate (%)"}
        ),
        use_container_width=True,
        hide_index=True,
    )

st.caption(
    "Method: a 30-Day Fed Funds future settles to 100 − the average daily EFFR for its "
    "month, so `100 − price` is the market's expected average EFFR; splitting each "
    "meeting month into its pre- and post-decision days recovers the implied rate each "
    "meeting is priced to leave in place. Assumes one decision per contract month and "
    "uses the EFFR anchor set in the sidebar. Meeting dates and the dot-plot overlay are "
    "hand-maintained in data/constants.py — verify them against federalreserve.gov and "
    "update after each meeting/SEP release."
)
