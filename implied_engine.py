"""Implied-path engine: raw (preliminary) → adjusted → per-meeting path.

Pure math (pandas/numpy only, no Streamlit, no network) so every stage is
unit-tested; fetchers live in data/cb_market.py. Ported from the CB-dashboard
brief and adapted to this app's registry (lowercase bank codes, Meeting
objects from data/meetings.py).

Every bank follows the same three-stage pipeline so the Methodology tab can
show each stage explicitly:

  STAGE 1  PRELIMINARY  raw quotes exactly as sourced (futures prices /
                        forward-curve points), no transformation.
  STAGE 2  ADJUSTED     (a) convert quotes to overnight-rate space,
                        (b) apply the index-vs-policy basis so the path is
                            expressed in POLICY-RATE terms,
                        (c) for monthly-average futures, deconvolve the
                            meeting month using the EFFECTIVE date.
  STAGE 3  PATH         implied post-meeting policy rate per meeting, the
                        step in bp, the 25bp move probability, and a
                        `method` label saying how each number was produced.

Basis logic: FF futures settle to EFFR, €STR futures to €STR, BoE OIS to
SONIA. Each index trades at a small, fairly stable spread to the policy
anchor (target midpoint / DFR / Bank Rate): policy = index − basis, where
basis = index − policy (typically a few bp, negative). Basis values are
user-editable in the UI — re-measure them, don't treat them as constants.
"""

from __future__ import annotations

import calendar
from datetime import date

import numpy as np
import pandas as pd

from config import STEP_BP
from data.meetings import Meeting


# ------------------------------------------------------------- shared ------
def _path_row(mt: Meeting, r_post: float, step_bp: float, method: str = "curve window") -> dict:
    if r_post is None or (isinstance(r_post, float) and np.isnan(r_post)):
        return {
            "decision": mt.decision, "effective": mt.effective,
            "implied_rate": np.nan, "step_bp": np.nan,
            "direction": "unidentified", "prob_25bp_move": np.nan,
            "method": "unidentified",
        }
    return {
        "decision": mt.decision, "effective": mt.effective,
        "implied_rate": round(float(r_post), 3), "step_bp": round(float(step_bp), 1),
        "direction": ("cut" if step_bp < -2 else "hike" if step_bp > 2 else "hold"),
        "prob_25bp_move": round(min(abs(step_bp) / STEP_BP, 1.0), 2),
        "method": method,
    }


def meeting_table(meetings: list[Meeting]) -> pd.DataFrame:
    """Conventions table: decision/effective dates, lag, deconvolution weights."""
    rows = []
    for mt in meetings:
        n_days = calendar.monthrange(mt.effective.year, mt.effective.month)[1]
        e = mt.effective.day
        rows.append(
            {
                "decision_date": mt.decision, "effective_date": mt.effective,
                "lag_days": (mt.effective - mt.decision).days,
                "days_in_month": n_days,
                "pre_weight": round((e - 1) / n_days, 3),
                "post_weight": round((n_days - e + 1) / n_days, 3),
                "note": mt.note,
            }
        )
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- FED ------
def adjust_ff(raw: pd.DataFrame, basis_bp: float) -> pd.DataFrame:
    """STAGE 2 (Fed): price → implied avg EFFR → policy-space rate."""
    adj = raw.copy()
    adj["implied_avg_effr"] = 100.0 - adj["raw_price"]
    adj["basis_bp"] = basis_bp
    adj["implied_avg_policy"] = adj["implied_avg_effr"] - basis_bp / 100.0
    return adj


def path_from_monthly_avg(adj: pd.DataFrame, current_policy: float, meetings: list[Meeting]) -> pd.DataFrame:
    """STAGE 3 (Fed): deconvolve meeting months on the EFFECTIVE date.

    avg = r_pre·(e−1)/N + r_post·(N−e+1)/N, solved for r_post with r_pre
    carried contract to contract. Meeting-free months re-anchor r_pre (which
    self-corrects small basis drift). When the post-effective window is <10%
    of the month the same-month solve is ill-conditioned — fall back to the
    next meeting-free month's contract, which embeds the new rate fully, and
    label the method accordingly.
    """
    if adj.empty:
        return pd.DataFrame()
    adj = adj.sort_values("contract_month").reset_index(drop=True)

    def month_meetings(y: int, m: int) -> list[Meeting]:
        return [mt for mt in meetings if mt.effective.year == y and mt.effective.month == m]

    r_run, out = current_policy, []
    rows = list(adj.iterrows())
    for i, (_, row) in enumerate(rows):
        y, m = map(int, str(row["contract_month"]).split("-"))
        n_days = calendar.monthrange(y, m)[1]
        month_mtgs = month_meetings(y, m)
        avg = row["implied_avg_policy"]
        if not month_mtgs:
            r_run = avg
            continue
        mt = month_mtgs[0]
        e = mt.effective.day
        w_pre, w_post = (e - 1) / n_days, (n_days - e + 1) / n_days
        if w_post >= 0.10:
            r_post = (avg - r_run * w_pre) / w_post
            out.append(_path_row(mt, r_post, (r_post - r_run) * 100.0, method="same-month deconvolution"))
        else:
            r_post = np.nan
            for _, nxt in rows[i + 1:]:
                ny, nm = map(int, str(nxt["contract_month"]).split("-"))
                if not month_meetings(ny, nm):
                    r_post = nxt["implied_avg_policy"]
                    break
            if np.isnan(r_post):
                out.append(_path_row(mt, np.nan, np.nan))
                continue
            out.append(_path_row(mt, r_post, (r_post - r_run) * 100.0, method="next-month proxy"))
        r_run = r_post
    return pd.DataFrame(out)


# ------------------------------------------------------- ECB (3M €STR) -----
def parse_estr_futures_csv(buf) -> pd.DataFrame | None:
    """STAGE 1 (ECB): Eurex settlement CSV with columns contract,price where
    contract is the delivery month 'YYYY-MM'. Returns None on any parse
    failure so the page shows the expected format instead of crashing."""
    try:
        df = pd.read_csv(buf).rename(columns=str.lower)
        df = df[["contract", "price"]].dropna()
        df["contract_month"] = df["contract"].astype(str).str.strip()
        df["raw_price"] = df["price"].astype(float)
        return df[["contract_month", "raw_price"]]
    except Exception:
        return None


def adjust_estr(raw: pd.DataFrame, basis_bp: float) -> pd.DataFrame:
    """STAGE 2 (ECB): price → implied 3M-compounded €STR → policy space.

    A 3M €STR future covers a quarter; its rate is treated as the average
    policy-space rate over that quarter (compounding drag <1bp at these
    levels, noted on the page).
    """
    adj = raw.copy()
    adj["implied_estr_3m"] = 100.0 - adj["raw_price"]
    adj["basis_bp"] = basis_bp
    adj["implied_avg_policy"] = adj["implied_estr_3m"] - basis_bp / 100.0
    return adj


def path_from_quarterly_avg(adj: pd.DataFrame, current_policy: float, meetings: list[Meeting]) -> pd.DataFrame:
    """STAGE 3 (ECB): fit a meeting-step function to quarterly averages.

    A 3M contract cannot separately identify two meetings in one quarter, so
    the fit assumes equal steps per meeting within the quarter — the
    identification constraint, documented on the page.
    """
    if adj.empty:
        return pd.DataFrame()
    adj = adj.sort_values("contract_month").reset_index(drop=True)
    r_run, out = current_policy, []
    for _, row in adj.iterrows():
        y, m = map(int, str(row["contract_month"]).split("-"))
        q_start = date(y, m, 1)
        q_end = date(y + (m + 2) // 12, (m + 2) % 12 + 1, 1)
        n_days = (q_end - q_start).days
        mtgs = [mt for mt in meetings if q_start <= mt.effective < q_end]
        avg = row["implied_avg_policy"]
        if not mtgs:
            r_run = avg
            continue
        seg_bounds = [q_start] + [mt.effective for mt in mtgs] + [q_end]
        seg_days = np.diff([d.toordinal() for d in seg_bounds])
        k = len(mtgs)
        w = seg_days / n_days
        j = np.arange(0, k + 1)
        step = (avg - r_run) / float(np.dot(w, j)) if np.dot(w, j) > 0 else 0.0
        for i, mt in enumerate(mtgs, start=1):
            out.append(_path_row(mt, r_run + step * i, step * 100.0, method="quarterly equal-step fit"))
        r_run = r_run + step * k
    return pd.DataFrame(out)


# ------------------------------------------------------------- BOE ---------
def adjust_boe(raw: pd.DataFrame, basis_bp: float) -> pd.DataFrame:
    """STAGE 2 (BoE): SONIA-forward space → Bank Rate space."""
    adj = raw.copy()
    adj["basis_bp"] = basis_bp
    adj["fwd_policy"] = adj["fwd_rate"] - basis_bp / 100.0
    return adj


def path_from_forward_curve(adj: pd.DataFrame, current_policy: float, meetings: list[Meeting], asof: date | None = None) -> pd.DataFrame:
    """STAGE 3 (BoE): average instantaneous forwards between effective dates,
    converting the smooth fitted curve back into the step function policy
    actually follows (20-point interpolation per window)."""
    if adj.empty:
        return pd.DataFrame()
    asof = asof or date.today()
    ordered = adj.sort_values("horizon_years")
    hz = ordered["horizon_years"].values.astype(float)
    fw = ordered["fwd_policy"].values.astype(float)

    def window_avg(d0: date, d1: date) -> float:
        t0, t1 = (d0 - asof).days / 365.25, (d1 - asof).days / 365.25
        t0, t1 = max(t0, hz.min()), min(max(t1, t0 + 1e-4), hz.max())
        ts = np.linspace(t0, t1, 20)
        return float(np.interp(ts, hz, fw).mean())

    out, r_prev = [], current_policy
    bounds = [m.effective for m in meetings]
    for i, mt in enumerate(meetings):
        d0 = mt.effective
        d1 = bounds[i + 1] if i + 1 < len(bounds) else d0.replace(
            year=d0.year + (d0.month + 1) // 12, month=(d0.month % 12) + 1
        )
        if (d1 - asof).days / 365.25 > hz.max():
            break
        r_post = window_avg(d0, d1)
        out.append(_path_row(mt, r_post, (r_post - r_prev) * 100.0, method="OIS forward windowing"))
        r_prev = r_post
    return pd.DataFrame(out)


# --------------------------------------------------- curve fallback --------
def path_from_yield_curve(curve_path: pd.DataFrame, current_policy: float, meetings: list[Meeting], asof: date, source_label: str = "curve forward (proxy)") -> pd.DataFrame:
    """Fallback STAGE 3 for any bank: read the app's government/OIS-curve
    implied forward path (fed_path.implied_forward_path output) at each
    effective date. Always available when the curve feeds are — the baseline
    the preferred instruments degrade to."""
    from fed_path import implied_rate_at

    if curve_path is None or curve_path.empty:
        return pd.DataFrame()
    last_h = float(curve_path["horizon_years"].max())
    out, r_prev = [], current_policy
    for mt in meetings:
        h = (mt.effective - asof).days / 365.0
        if h < 0 or h > last_h:
            continue
        r_post = implied_rate_at(curve_path, h)
        if r_post is None:
            continue
        out.append(_path_row(mt, r_post, (r_post - r_prev) * 100.0, method=source_label))
        r_prev = r_post
    return pd.DataFrame(out)
