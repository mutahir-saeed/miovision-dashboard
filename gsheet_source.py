"""
FUTURE SWAP — Google Sheets data source (stub).

This shows how to point the dashboard at Google Sheets later WITHOUT touching
aggregations.py, data_quality.py, or app.py. The only contract you must honour:
return a DataFrame with the exact same columns as data_source.load_long_table().

Setup (when you're ready):
  1. pip install gspread google-auth
  2. Create a Google Cloud service account, enable the Sheets API, download its
     JSON key, and SHARE the spreadsheet with the service-account email.
  3. Fill in SPREADSHEET_KEY below and call load_long_table_from_gsheet().
  4. In app.py, swap:
         from data_source import load_long_table
     for:
         from gsheet_source import load_long_table_from_gsheet as load_long_table
"""

from __future__ import annotations
import pandas as pd

from data_source import (
    COL_STUDENT, COL_PROJECT, COL_TASK, COL_HOURS, COL_SIGNALS,
    COL_WEEK, COL_DATE, COL_NOTES, UNSPECIFIED_TASK, REFERENCE_SHEET,
)

SPREADSHEET_KEY = "PUT_YOUR_SHEET_ID_HERE"
SERVICE_ACCOUNT_JSON = "service_account.json"


def load_long_table_from_gsheet() -> pd.DataFrame:
    import gspread
    gc = gspread.service_account(filename=SERVICE_ACCOUNT_JSON)
    sh = gc.open_by_key(SPREADSHEET_KEY)

    records = []
    for ws in sh.worksheets():
        if ws.title == REFERENCE_SHEET:
            continue
        rows = ws.get_all_records()  # uses row 1 as headers, like the Excel version
        for row in rows:
            # Header keys mirror the Excel columns; map them the same way.
            proj = (row.get("Project") or "").strip() or None
            hours = _num(row.get("Duration (Hrs)"))
            signals = _num(row.get("# of Signals") or row.get("No. of Signals"))
            if hours is None and signals is None:
                continue
            records.append({
                COL_STUDENT: ws.title,
                COL_PROJECT: proj or UNSPECIFIED_TASK,
                COL_TASK: (row.get("Task") or "").strip() or UNSPECIFIED_TASK,
                COL_HOURS: hours or 0.0,
                COL_SIGNALS: signals,
                COL_WEEK: _num(row.get("KW")),
                COL_DATE: pd.to_datetime(row.get("Date"), errors="coerce"),
                COL_NOTES: (row.get("Notes") or "").strip() or None,
            })
    df = pd.DataFrame.from_records(records)
    if not df.empty:
        df[COL_WEEK] = df[COL_WEEK].astype("Int64")
    return df


def _num(v):
    if v in (None, ""):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None
