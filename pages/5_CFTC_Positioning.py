import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from analytics import trend_signal
from config import CFTC_WEEKS_LOOKBACK
from data import cftc
from data.constants import CFTC_DISAGG_CONTRACTS, CFTC_TFF_CONTRACTS
from data.sources import get_cftc_positioning
from ui import empty_state, metric_row, render
from viz_theme import CATEGORICAL

st.set_page_config(page_title="CFTC Positioning — Derivatives Monitor", page_icon="📈", layout="wide")
st.title("CFTC positioning")
st.caption(
    "Weekly futures positioning by trader category, from the CFTC's free Commitments of "
    "Traders report. Updated Fridays, as of the prior Tuesday — this is positioning, not "
    "trade-level liquidity, and is the natural complement to the DTCC pages."
)

REPORTS = {"Financial futures (rates, FX, equity index)": "financial", "Commodity futures": "commodities"}
CONTRACTS = {"financial": CFTC_TFF_CONTRACTS, "commodities": CFTC_DISAGG_CONTRACTS}

with st.sidebar:
    report_label = st.radio("Report", list(REPORTS.keys()))
    report = REPORTS[report_label]
    contract = st.selectbox("Contract", CONTRACTS[report])
    weeks = st.slider(
        "Lookback (weeks)", CFTC_WEEKS_LOOKBACK.min_value, CFTC_WEEKS_LOOKBACK.max_value, CFTC_WEEKS_LOOKBACK.default
    )

if report == "commodities":
    st.caption(
        "Trader categories here differ from the financial-futures report: Producer/Merchant "
        "(commercial hedgers), Swap Dealer, Managed Money (speculative funds), and Other "
        "Reportables."
    )

df = get_cftc_positioning((contract,), weeks, report)

if df.empty:
    empty_state(
        "No positioning data returned for this contract/window. The CFTC public reporting "
        "API can occasionally be slow or rate-limit; try again in a moment, or pick a "
        "different contract.",
        kind="warning",
    )

categories = cftc.category_columns(report)
latest = df.iloc[-1]
metric_row(
    [("Open interest", f"{int(latest['open_interest_all']):,}" if pd.notna(latest["open_interest_all"]) else "N/A")]
    + [
        (f"{category} net", f"{int(latest[net_col]):,}" if pd.notna(latest[net_col]) else "N/A")
        for category, net_col in categories
    ]
)

st.subheader(f"Net positioning by trader category — {contract}")
fig = go.Figure()
for i, (category, net_col) in enumerate(categories):
    if df[net_col].isna().all():
        continue
    fig.add_trace(
        go.Scatter(
            x=df["report_date"],
            y=df[net_col],
            mode="lines",
            name=category,
            line=dict(color=CATEGORICAL[i], width=2),
        )
    )
fig.add_hline(y=0, line_width=1, line_color="rgba(128,128,128,0.4)")
fig.update_layout(yaxis_title="Net contracts (long − short)", legend_title=None, hovermode="x unified")
render(fig)

st.subheader("Open interest")
fig_oi = go.Figure(
    go.Scatter(
        x=df["report_date"],
        y=df["open_interest_all"],
        mode="lines",
        line=dict(color=CATEGORICAL[0], width=2),
        fill="tozeroy",
    )
)
fig_oi.update_layout(yaxis_title="Contracts")
render(fig_oi)

st.subheader("Positioning extremes")
st.caption(
    "Percentile rank of each category's current net position within the lookback window "
    "above — readings near the extremes (below ~10th or above ~90th percentile) are the "
    "classic contrarian crowding signal: positioning is stretched one way, raising the odds "
    "of a reversal if the fundamental driver behind it fades."
)
signal_cols = st.columns(len(categories))
for col, (category, net_col) in zip(signal_cols, categories):
    with col:
        st.markdown(f"**{category}**")
        signal = trend_signal(df.set_index("report_date")[net_col])
        if signal is None:
            st.write("Not enough data.")
            continue
        delta = f"{signal.change:+,.0f} vs prior week" if signal.change is not None else None
        st.metric("Net position", f"{signal.latest_value:,.0f}", delta)
        percentile_caption = f"{signal.percentile:.0f}th percentile of {signal.n_periods} weeks"
        if signal.percentile >= 90:
            st.caption(f"⚠️ Crowded long — {percentile_caption}")
        elif signal.percentile <= 10:
            st.caption(f"⚠️ Crowded short — {percentile_caption}")
        else:
            st.caption(percentile_caption)

with st.expander(f"Show weekly positioning detail — {contract}"):
    st.dataframe(
        df.sort_values("report_date", ascending=False)
        .rename(columns={"report_date": "Week", "open_interest_all": "Open interest", **{c: name for name, c in categories}})[
            ["Week", "Open interest"] + [name for name, _ in categories]
        ],
        use_container_width=True,
        hide_index=True,
    )
