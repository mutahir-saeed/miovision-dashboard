"""
Layer 2b — DATA QUALITY.

Surfaces rows that will silently distort project totals so the dashboard can flag
them instead of hiding them. Pure logic over the tidy long table.
"""

from __future__ import annotations
import pandas as pd
from data_source import (
    COL_STUDENT, COL_PROJECT, COL_TASK, COL_HOURS, COL_SIGNALS, COL_DATE,
    UNSPECIFIED_TASK,
)


def quality_flags(df: pd.DataFrame, reference: dict) -> pd.DataFrame:
    """Return rows with likely data-entry problems, with a human-readable reason."""
    valid = reference["projects"]  # project -> [allowed tasks]
    issues = []

    for i, row in df.iterrows():
        reasons = []
        proj, task = row[COL_PROJECT], row[COL_TASK]

        if task == UNSPECIFIED_TASK:
            reasons.append("Task is blank")
        elif proj in valid and valid[proj] and task not in valid[proj] and task != UNSPECIFIED_TASK:
            reasons.append(f"Task '{task}' not listed under project '{proj}' (possible misclassification)")

        if (row[COL_HOURS] or 0) > 0 and (pd.isna(row[COL_SIGNALS]) or row[COL_SIGNALS] == 0):
            # Not always an error (some tasks are not signal-based) — informational only.
            pass

        if (row[COL_HOURS] or 0) > 16:
            reasons.append(f"Unusually long day: {row[COL_HOURS]} hrs")

        if reasons:
            issues.append({
                "Student": row[COL_STUDENT],
                "Date": row[COL_DATE].date() if pd.notna(row[COL_DATE]) else None,
                "Project": proj,
                "Task": task,
                "Hours": row[COL_HOURS],
                "Issue": "; ".join(reasons),
            })

    return pd.DataFrame(issues)
