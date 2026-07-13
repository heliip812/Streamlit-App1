"""Shared chart color palette, applied consistently across all pages.

Categorical hues are assigned in a fixed order (never cycled/re-ranked) so
the same series always gets the same color across charts. Pass
theme="streamlit" to st.plotly_chart so gridlines/background/font adapt to
the active light/dark mode; only trace colors below are hardcoded.
"""

CATEGORICAL = [
    "#2a78d6",  # 1 blue
    "#1baf7a",  # 2 aqua
    "#eda100",  # 3 yellow
    "#008300",  # 4 green
    "#4a3aa7",  # 5 violet
    "#e34948",  # 6 red
    "#e87ba4",  # 7 magenta
    "#eb6834",  # 8 orange
]

STATUS = {
    "good": "#0ca30c",
    "warning": "#fab219",
    "serious": "#ec835a",
    "critical": "#d03b3b",
}

SEQUENTIAL_BLUE = ["#cde2fb", "#9ec5f4", "#5598e7", "#2a78d6", "#184f95", "#0d366b"]


def color_for(index: int) -> str:
    return CATEGORICAL[index % len(CATEGORICAL)]
