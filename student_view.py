"""
Layer 2c — STUDENT VIEW.

Kept SEPARATE from aggregations.py on purpose: all per-student / per-individual
logic lives here and is surfaced only in the "Team" tab. Keeping it out of
aggregations.py means the project-level module never accidentally mixes in
individual metrics.

Same tidy long table in, same weighted methodology for time-per-signal. Nothing here
changes any project-level number.
"""

from __future__ import annotations
import pandas as pd
from data_source import (
    COL_STUDENT, COL_PROJECT, COL_HOURS, COL_SIGNALS, COL_WEEK, COL_DATE, COL_TASK,
)


def _weighted_tps(g: pd.DataFrame) -> float:
    """Weighted minutes-per-signal over rows that actually logged signals.
    Identical methodology to aggregations._weighted_tps (kept local so this module
    is self-contained and the project-level module has no student dependency)."""
    sig = g[COL_SIGNALS]
    mask = sig.notna() & (sig > 0)
    total_sig = sig[mask].sum()
    if total_sig == 0:
        return float("nan")
    return (g.loc[mask, COL_HOURS].sum() / total_sig) * 60.0


def _active_days(g: pd.DataFrame) -> int:
    return int(g[COL_DATE].dropna().dt.normalize().nunique())


def _most_worked_task(g: pd.DataFrame) -> str:
    """Task the student logged the most HOURS on."""
    if g.empty:
        return "—"
    by_task = g.groupby(COL_TASK)[COL_HOURS].sum()
    if by_task.empty:
        return "—"
    return by_task.idxmax()


def student_summary(df: pd.DataFrame) -> pd.DataFrame:
    """One row per student: total hours, signals, weighted time/signal, person-days,
    active days, avg hrs/person-day, top project and most-worked task."""
    rows = []
    for student, g in df.groupby(COL_STUDENT):
        person_days = len(g)
        hours = g[COL_HOURS].sum()
        top_project = (
            g.groupby(COL_PROJECT)[COL_HOURS].sum().idxmax() if not g.empty else "—"
        )
        rows.append({
            "Student": student,
            "Total Hours": round(hours, 1),
            "Total Signals": int(g[COL_SIGNALS].dropna().sum()),
            "Weighted Time/Signal (min)": round(_weighted_tps(g), 1),
            "Person-Days": person_days,
            "Active Days": _active_days(g),
            "Avg Hrs/Person-Day": round(hours / person_days, 1) if person_days else 0.0,
            "Top Project": top_project,
            "Most-Worked Task": _most_worked_task(g),
        })
    return pd.DataFrame(rows).sort_values("Total Hours", ascending=False, ignore_index=True)


def student_hours_ranking(df: pd.DataFrame) -> pd.DataFrame:
    """Two-column (Student, Total Hours) frame sorted descending — feeds the ranked bar."""
    out = (
        df.groupby(COL_STUDENT)[COL_HOURS].sum().round(1)
        .reset_index()
        .rename(columns={COL_HOURS: "Total Hours", COL_STUDENT: "Student"})
        .sort_values("Total Hours", ascending=False, ignore_index=True)
    )
    return out


def student_project_split(df: pd.DataFrame, student: str) -> pd.DataFrame:
    """Hours and signals by project for ONE student (drilldown)."""
    g = df[df[COL_STUDENT] == student]
    rows = []
    for proj, gp in g.groupby(COL_PROJECT):
        rows.append({
            "Project": proj,
            "Total Hours": round(gp[COL_HOURS].sum(), 1),
            "Total Signals": int(gp[COL_SIGNALS].dropna().sum()),
            "Weighted Time/Signal (min)": round(_weighted_tps(gp), 1),
        })
    return pd.DataFrame(rows).sort_values("Total Hours", ascending=False, ignore_index=True)


def student_weekly_trend(df: pd.DataFrame, student: str) -> pd.DataFrame:
    """Hours per KW week for ONE student (drilldown line). Columns: week, Hours."""
    g = df[(df[COL_STUDENT] == student)].dropna(subset=[COL_WEEK])
    out = (
        g.groupby(COL_WEEK)[COL_HOURS].sum().round(1)
        .reset_index()
        .rename(columns={COL_WEEK: "week", COL_HOURS: "Hours"})
        .sort_values("week")
    )
    out["week"] = out["week"].astype(int)
    return out


def student_project_matrix(df: pd.DataFrame) -> pd.DataFrame:
    """Wide student × project hours matrix for the heatmap (index = student)."""
    pivot = df.pivot_table(
        index=COL_STUDENT, columns=COL_PROJECT, values=COL_HOURS,
        aggfunc="sum", fill_value=0.0,
    )
    # Order students by total hours so the heatmap reads top-down.
    order = pivot.sum(axis=1).sort_values(ascending=False).index
    return pivot.reindex(order)


if __name__ == "__main__":
    from data_source import load_long_table
    df = load_long_table("data.xlsx")
    print("=== STUDENT SUMMARY ===")
    print(student_summary(df).to_string(index=False))
    print("\n=== HOURS RANKING ===")
    print(student_hours_ranking(df).to_string(index=False))
    top = student_hours_ranking(df).iloc[0]["Student"]
    print(f"\n=== DRILLDOWN: {top} — project split ===")
    print(student_project_split(df, top).to_string(index=False))
