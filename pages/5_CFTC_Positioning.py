import pandas as pd
import plotly.graph_objects as go
import streamlit as st

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
