"""
Layer 2 — AGGREGATION.

Pure functions over the tidy long table. No knowledge of Excel, Google Sheets,
or the dashboard. Every output is project-level: individual per-student metrics are
intentionally kept in `student_view.py` so this module stays focused on the
project/task picture.

KEY METHODOLOGY NOTE — weighted vs naive average time-per-signal:
    The naive figure (mean of the per-row "Time per Signal" column) over-weights
    low-signal days and is misleading. The honest figure is a WEIGHTED average:
        avg_time_per_signal = (total hours on signal-bearing rows / total signals) * 60
    We only count rows where signals were actually recorded, so days logged in
    hours-only (e.g. some Topology days) don't distort the per-signal efficiency.

METRIC NOTE — "days":
    "Person-Days"        = number of logged rows in the group (one student × one
                           date = one person-day). This is *effort*, not calendar time.
    "Active Days"        = number of DISTINCT calendar dates in the group. The whole
                           dataset only spans 46 distinct dates, so this is the honest
                           "how many days did work happen on" number.
    "Avg Hrs/Person-Day" = total hours / person-days (typical length of a logged day).

TOTAL ROWS:
    The summary tables can append a "Total" row (with_total=True). Totals are
    RECOMPUTED from the underlying rows, never summed from the displayed rows, so
    weighted time/signal, active days and avg hrs/person-day stay correct (you cannot
    simply add those columns up).
"""

from __future__ import annotations
import pandas as pd
from data_source import (
    COL_PROJECT, COL_TASK, COL_HOURS, COL_SIGNALS, COL_WEEK, COL_DATE,
)

# Granularity labels used by the UI radio and the breakdown functions.
GRAN_WEEKLY = "Weekly"
GRAN_BIWEEKLY = "Bi-weekly"
GRAN_MONTHLY = "Monthly"
GRANULARITIES = [GRAN_WEEKLY, GRAN_BIWEEKLY, GRAN_MONTHLY]


def _weighted_tps(g: pd.DataFrame) -> float:
    """Weighted average minutes-per-signal over rows that actually logged signals."""
    sig = g[COL_SIGNALS]
    mask = sig.notna() & (sig > 0)
    total_sig = sig[mask].sum()
    if total_sig == 0:
        return float("nan")
    total_hours_on_signal_rows = g.loc[mask, COL_HOURS].sum()
    return (total_hours_on_signal_rows / total_sig) * 60.0


def _active_days(g: pd.DataFrame) -> int:
    """Number of distinct calendar dates with logged work in the group."""
    return int(g[COL_DATE].dropna().dt.normalize().nunique())


# ---------------------------------------------------------------------------
# Total-row helper (shared by the summary tables)
# ---------------------------------------------------------------------------

def _summary_total_row(scope: pd.DataFrame, columns, label_col: str,
                       label: str = "Total") -> dict:
    """Build a correctly-computed 'Total' row matching `columns`. Every metric is
    recomputed from `scope` (the underlying rows), so the total is honest even for
    weighted time/signal, active days and avg hrs/person-day."""
    person_days = len(scope)
    hours = scope[COL_HOURS].sum()
    row = {c: "" for c in columns}   # label/empty by default; numerics overwritten below
    row[label_col] = label
    if "Total Hours" in columns:
        row["Total Hours"] = round(hours, 1)
    if "Total Signals" in columns:
        row["Total Signals"] = int(scope[COL_SIGNALS].dropna().sum())
    if "Avg Time/Signal (min)" in columns:
        row["Avg Time/Signal (min)"] = round(_weighted_tps(scope), 1)
    if "Person-Days" in columns:
        row["Person-Days"] = person_days
    if "Active Days" in columns:
        row["Active Days"] = _active_days(scope)
    if "Avg Hrs/Person-Day" in columns:
        row["Avg Hrs/Person-Day"] = round(hours / person_days, 1) if person_days else 0.0
    if "% of Hours" in columns:
        row["% of Hours"] = 100.0
    return row


def _append_total(out: pd.DataFrame, scope: pd.DataFrame, label_col: str) -> pd.DataFrame:
    if out.empty:
        return out
    total = _summary_total_row(scope, list(out.columns), label_col)
    return pd.concat([out, pd.DataFrame([total])], ignore_index=True)


# ---------------------------------------------------------------------------
# Period bucketing (drives the whole Time Breakdown tab)
# ---------------------------------------------------------------------------

def add_period(df: pd.DataFrame, granularity: str = GRAN_WEEKLY) -> pd.DataFrame:
    """
    Return a copy of df with two helper columns:
        period       — human label for the bucket (e.g. "KW 19", "KW 19–20", "May 2026")
        period_order — sortable integer/period key so charts stay in chronological order

    Weekly    : one bucket per ISO calendar week (KW).
    Bi-weekly : consecutive week pairs (19–20, 21–22, ...). Keyed off the FIRST week.
    Monthly   : one bucket per calendar month. The logic is fully general; it simply
                produces fewer buckets while the sheet covers a short span, and fills
                out automatically as more weeks are logged.
    """
    d = df.copy()
    if granularity == GRAN_WEEKLY:
        d = d.dropna(subset=[COL_WEEK])
        d["period_order"] = d[COL_WEEK].astype(int)
        d["period"] = "KW " + d["period_order"].astype(str)
    elif granularity == GRAN_BIWEEKLY:
        d = d.dropna(subset=[COL_WEEK])
        wk = d[COL_WEEK].astype(int)
        # Pair weeks: 19&20 -> start 19, 21&22 -> start 21, ...
        start = wk - ((wk - wk.min()) % 2)
        d["period_order"] = start
        d["period"] = "KW " + start.astype(str) + "–" + (start + 1).astype(str)
    elif granularity == GRAN_MONTHLY:
        d = d.dropna(subset=[COL_DATE])
        per = d[COL_DATE].dt.to_period("M")
        d["period_order"] = per.apply(lambda p: p.ordinal)
        d["period"] = d[COL_DATE].dt.strftime("%b %Y")
    else:
        raise ValueError(f"Unknown granularity: {granularity}")
    return d


def _period_label_order(d: pd.DataFrame) -> list[str]:
    """Chronological list of unique period labels for categorical chart axes."""
    return (
        d[["period", "period_order"]]
        .drop_duplicates()
        .sort_values("period_order")["period"]
        .tolist()
    )


# ---------------------------------------------------------------------------
# Project / task summaries
# ---------------------------------------------------------------------------

def project_summary(df: pd.DataFrame, with_total: bool = False) -> pd.DataFrame:
    """Per project: hours, signals, weighted time/signal, person-days, active days,
    avg hrs/person-day, % of all hours. Optionally append a recomputed Total row."""
    rows = []
    grand_hours = df[COL_HOURS].sum()
    for proj, g in df.groupby(COL_PROJECT):
        person_days = len(g)
        hours = g[COL_HOURS].sum()
        rows.append({
            "Project": proj,
            "Total Hours": round(hours, 1),
            "Total Signals": int(g[COL_SIGNALS].dropna().sum()),
            "Avg Time/Signal (min)": round(_weighted_tps(g), 1),
            "Person-Days": person_days,
            "Active Days": _active_days(g),
            "Avg Hrs/Person-Day": round(hours / person_days, 1) if person_days else 0.0,
            "% of Hours": round(100 * hours / grand_hours, 1) if grand_hours else 0,
        })
    out = pd.DataFrame(rows).sort_values("Total Hours", ascending=False, ignore_index=True)
    return _append_total(out, df, "Project") if with_total else out


def task_summary(df: pd.DataFrame, project: str | None = None,
                 with_total: bool = False) -> pd.DataFrame:
    """Same metrics broken down to Project -> Task. Optionally filter to one project
    and/or append a recomputed Total row."""
    d = df if project is None else df[df[COL_PROJECT] == project]
    rows = []
    for (proj, task), g in d.groupby([COL_PROJECT, COL_TASK]):
        person_days = len(g)
        hours = g[COL_HOURS].sum()
        rows.append({
            "Project": proj,
            "Task": task,
            "Total Hours": round(hours, 1),
            "Total Signals": int(g[COL_SIGNALS].dropna().sum()),
            "Avg Time/Signal (min)": round(_weighted_tps(g), 1),
            "Person-Days": person_days,
            "Active Days": _active_days(g),
            "Avg Hrs/Person-Day": round(hours / person_days, 1) if person_days else 0.0,
        })
    out = pd.DataFrame(rows).sort_values(
        ["Project", "Total Hours"], ascending=[True, False], ignore_index=True
    )
    return _append_total(out, d, "Project") if with_total else out


def task_rollup(df: pd.DataFrame, project: str | None = None,
                with_total: bool = False) -> pd.DataFrame:
    """
    Per TASK, collapsed across projects (a pure task-level view). Same metric columns
    as task_summary minus Project, plus a "% of Hours" share column. Optionally
    restrict to one project and/or append a recomputed Total row.
    Useful when the same task label can appear under more than one project.
    """
    d = df if project is None else df[df[COL_PROJECT] == project]
    grand_hours = d[COL_HOURS].sum()
    rows = []
    for task, g in d.groupby(COL_TASK):
        person_days = len(g)
        hours = g[COL_HOURS].sum()
        rows.append({
            "Task": task,
            "Total Hours": round(hours, 1),
            "Total Signals": int(g[COL_SIGNALS].dropna().sum()),
            "Avg Time/Signal (min)": round(_weighted_tps(g), 1),
            "Person-Days": person_days,
            "Active Days": _active_days(g),
            "Avg Hrs/Person-Day": round(hours / person_days, 1) if person_days else 0.0,
            "% of Hours": round(100 * hours / grand_hours, 1) if grand_hours else 0,
        })
    out = pd.DataFrame(rows).sort_values("Total Hours", ascending=False, ignore_index=True)
    return _append_total(out, d, "Task") if with_total else out


# ---------------------------------------------------------------------------
# Time breakdowns at chosen granularity (project OR task)
# ---------------------------------------------------------------------------

def time_breakdown(df: pd.DataFrame, granularity: str = GRAN_WEEKLY,
                   by: str = COL_PROJECT) -> pd.DataFrame:
    """
    Tidy long table of hours per period per group, plus signals & weighted tps for
    rich tooltips. Columns: period, period_order, <by>, hours, signals, weighted_tps.
    Pivot in the UI as needed (stacked area / heatmap / facets all consume this).
    """
    d = add_period(df, granularity)
    if d.empty:
        return pd.DataFrame(columns=["period", "period_order", by, "hours", "signals", "weighted_tps"])
    rows = []
    for (period, order, grp), g in d.groupby(["period", "period_order", by]):
        rows.append({
            "period": period,
            "period_order": order,
            by: grp,
            "hours": round(g[COL_HOURS].sum(), 1),
            "signals": int(g[COL_SIGNALS].dropna().sum()),
            "weighted_tps": round(_weighted_tps(g), 1),
        })
    out = pd.DataFrame(rows).sort_values(["period_order", by], ignore_index=True)
    return out


def share_of_effort(df: pd.DataFrame, granularity: str = GRAN_WEEKLY,
                    by: str = COL_PROJECT) -> pd.DataFrame:
    """Same as time_breakdown but with a `share` column = % of that period's hours.
    Feeds the 100%-stacked 'effort drift' chart."""
    tb = time_breakdown(df, granularity, by)
    if tb.empty:
        tb["share"] = []
        return tb
    totals = tb.groupby("period")["hours"].transform("sum")
    tb = tb.copy()
    tb["share"] = (100 * tb["hours"] / totals).round(1).fillna(0.0)
    return tb


def cumulative_hours(df: pd.DataFrame, granularity: str = GRAN_WEEKLY,
                     by: str = COL_PROJECT) -> pd.DataFrame:
    """Running total of hours per group across periods. Columns add `cumulative_hours`.
    Every group is reindexed across ALL periods so lines don't break on empty buckets."""
    tb = time_breakdown(df, granularity, by)
    if tb.empty:
        tb["cumulative_hours"] = []
        return tb
    order_map = tb[["period", "period_order"]].drop_duplicates()
    periods = order_map.sort_values("period_order")["period"].tolist()
    groups = sorted(tb[by].unique())
    full_idx = pd.MultiIndex.from_product([periods, groups], names=["period", by])
    grid = (
        tb.set_index(["period", by])["hours"]
        .reindex(full_idx, fill_value=0.0)
        .reset_index()
    )
    grid = grid.merge(order_map, on="period", how="left")
    grid = grid.sort_values(["period_order", by])
    grid["cumulative_hours"] = grid.groupby(by)["hours"].cumsum().round(1)
    return grid.reset_index(drop=True)


def heatmap_data(df: pd.DataFrame, granularity: str = GRAN_WEEKLY,
                 by: str = COL_PROJECT) -> pd.DataFrame:
    """Wide period × group matrix of hours for a heatmap (index = group, cols = periods)."""
    tb = time_breakdown(df, granularity, by)
    if tb.empty:
        return pd.DataFrame()
    periods = _period_label_order(tb)
    pivot = tb.pivot_table(index=by, columns="period", values="hours",
                           aggfunc="sum", fill_value=0.0)
    return pivot.reindex(columns=periods, fill_value=0.0)


# ---------------------------------------------------------------------------
# Legacy weekly views (kept; UI still uses them for the learning curve)
# ---------------------------------------------------------------------------

def weekly_trend(df: pd.DataFrame, by: str = COL_PROJECT) -> pd.DataFrame:
    """Hours per ISO week (KW) pivoted by project (or task) — for momentum charts."""
    d = df.dropna(subset=[COL_WEEK])
    pivot = d.pivot_table(
        index=COL_WEEK, columns=by, values=COL_HOURS, aggfunc="sum", fill_value=0
    ).sort_index()
    return pivot


def weekly_efficiency(df: pd.DataFrame, by: str = COL_PROJECT) -> pd.DataFrame:
    """Weighted time-per-signal per week per group — the team 'learning curve'."""
    d = df.dropna(subset=[COL_WEEK])
    out = {}
    for key, g in d.groupby(by):
        per_week = {}
        for wk, gw in g.groupby(COL_WEEK):
            per_week[int(wk)] = _weighted_tps(gw)
        out[key] = pd.Series(per_week)
    return pd.DataFrame(out).sort_index()


# ---------------------------------------------------------------------------
# Phase 3 vs Phase 4 comparison (computed, never hardcoded)
# ---------------------------------------------------------------------------

def phase_comparison(df: pd.DataFrame) -> pd.DataFrame:
    """
    Compare TPfC Phase 3 and Phase 4 side by side across hours, signals, weighted
    time/signal, person-days and active days. Matches any task containing the phase
    name (handles a stray Phase 3 logged under the Topology project too).
    Returns one row per phase found, in phase order.
    """
    rows = []
    for label, needle in [("TPfC Phase 3", "phase 3"), ("TPfC Phase 4", "phase 4")]:
        g = df[df[COL_TASK].str.lower().str.contains(needle, na=False)]
        if g.empty:
            continue
        person_days = len(g)
        hours = g[COL_HOURS].sum()
        rows.append({
            "Phase": label,
            "Total Hours": round(hours, 1),
            "Total Signals": int(g[COL_SIGNALS].dropna().sum()),
            "Weighted Time/Signal (min)": round(_weighted_tps(g), 1),
            "Person-Days": person_days,
            "Active Days": _active_days(g),
            "Avg Hrs/Person-Day": round(hours / person_days, 1) if person_days else 0.0,
        })
    return pd.DataFrame(rows)


def phase_ramp_note(comp: pd.DataFrame) -> str | None:
    """
    Build a data-driven callout about Phase 4 ramp-up. Returns None if we can't
    compare (e.g. one phase missing or has no signals). Nothing is hardcoded — the
    direction of the message is decided from the actual weighted figures.
    """
    if comp.empty or len(comp) < 2:
        return None
    try:
        p3 = comp.loc[comp["Phase"] == "TPfC Phase 3"].iloc[0]
        p4 = comp.loc[comp["Phase"] == "TPfC Phase 4"].iloc[0]
    except IndexError:
        return None
    t3, t4 = p3["Weighted Time/Signal (min)"], p4["Weighted Time/Signal (min)"]
    if pd.isna(t3) or pd.isna(t4):
        return None
    if t4 > t3:
        mult = t4 / t3 if t3 else float("nan")
        return (
            f"Phase 4 is still ramping: at {t4:.1f} min/signal it is "
            f"{mult:.1f}× slower than Phase 3 ({t3:.1f} min/signal), on only "
            f"{p4['Total Hours']:.0f} hrs vs {p3['Total Hours']:.0f}. "
            "Early-phase effort per signal is expected to fall as the team builds familiarity."
        )
    return (
        f"Phase 4 is already at {t4:.1f} min/signal vs Phase 3's {t3:.1f} — "
        "tracking at or below the mature phase."
    )


def headline_numbers(df: pd.DataFrame) -> dict:
    """Top-line KPIs for the dashboard header."""
    return {
        "total_hours": round(df[COL_HOURS].sum(), 1),
        "total_signals": int(df[COL_SIGNALS].dropna().sum()),
        "projects": df[COL_PROJECT].nunique(),
        "weighted_tps": round(_weighted_tps(df), 1),
        "weeks_covered": int(df[COL_WEEK].dropna().nunique()),
        "active_days": _active_days(df),
        "person_days": len(df),
    }


if __name__ == "__main__":
    from data_source import load_long_table
    df = load_long_table("data.xlsx")
    print("=== PROJECT SUMMARY (with total) ===")
    print(project_summary(df, with_total=True).to_string(index=False))
    print("\n=== TASK ROLLUP (with total, % of hours) ===")
    print(task_rollup(df, with_total=True).to_string(index=False))
    print("\n=== TASK SUMMARY (with total) ===")
    print(task_summary(df, with_total=True).to_string(index=False))
