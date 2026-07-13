import plotly.graph_objects as go
import streamlit as st

from config import CFTC_WEEKS_LOOKBACK
from data.constants import CFTC_TFF_CONTRACTS
from data.sources import get_cftc_positioning
from ui import empty_state, metric_row, render
from viz_theme import CATEGORICAL

st.set_page_config(page_title="CFTC Positioning — Derivatives Monitor", page_icon="📈", layout="wide")
st.title("CFTC positioning (Traders in Financial Futures)")
st.caption(
    "Weekly futures positioning by trader category, from the CFTC's free Commitments of "
    "Traders report. Updated Fridays, as of the prior Tuesday — this is positioning, not "
    "trade-level liquidity, and is the natural complement to the DTCC pages."
)

with st.sidebar:
    contract = st.selectbox("Contract", CFTC_TFF_CONTRACTS)
    weeks = st.slider(
        "Lookback (weeks)", CFTC_WEEKS_LOOKBACK.min_value, CFTC_WEEKS_LOOKBACK.max_value, CFTC_WEEKS_LOOKBACK.default
    )

df = get_cftc_positioning((contract,), weeks)

if df.empty:
    empty_state(
        "No positioning data returned for this contract/window. The CFTC public reporting "
        "API can occasionally be slow or rate-limit; try again in a moment, or pick a "
        "different contract.",
        kind="warning",
    )

latest = df.iloc[-1]
metric_row(
    [
        ("Open interest", f"{int(latest['open_interest_all']):,}"),
        ("Dealer net", f"{int(latest['dealer_net']):,}"),
        ("Asset manager net", f"{int(latest['asset_mgr_net']):,}"),
        ("Leveraged funds net", f"{int(latest['lev_money_net']):,}"),
    ]
)

st.subheader(f"Net positioning by trader category — {contract}")
fig = go.Figure()
for i, (col, name) in enumerate(
    [
        ("dealer_net", "Dealer"),
        ("asset_mgr_net", "Asset manager"),
        ("lev_money_net", "Leveraged funds"),
        ("other_net", "Other reportables"),
    ]
):
    fig.add_trace(
        go.Scatter(
            x=df["report_date"],
            y=df[col],
            mode="lines",
            name=name,
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
