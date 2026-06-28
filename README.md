# Project Hours — General Overview Dashboard

A project-level dashboard over the **Working Hours Tracker** (19 student tabs +
Reference). It shows how many hours went into each project and phase (e.g. TPfC
Phase 3 vs Phase 4) and the average time per signal per task. Individual per-student
numbers exist in their own **Team** tab so the main view stays project- and
task-focused.

## Architecture (why it's easy to adapt)

Separated layers. Only the first knows where the data lives:

| Layer | File | Job |
|-------|------|-----|
| 1. Ingestion | `data_source.py` | Read all 19 tabs → one tidy "long" table. Maps columns by header *name* (handles `# of Signals` vs `No. of Signals`). |
| 1b. Future source | `gsheet_source.py` | Drop-in Google Sheets loader (stub). Returns the same columns. |
| 2. Aggregation | `aggregations.py` | Pure pandas, project/task level: totals, weighted time/signal, period breakdowns, phase comparison. No Excel/UI knowledge. |
| 2b. Data quality | `data_quality.py` | Flags blank tasks & misclassifications before they distort totals. |
| 2c. Student view | `student_view.py` | Per-student metrics, kept out of `aggregations.py` so the project-level logic stays clean. |
| 3. Presentation | `app.py` | Streamlit dashboard (Plotly charts, 5 tabs). |

**To switch to Google Sheets later:** fill in `gsheet_source.py`, then in `app.py`
change `from data_source import load_long_table` to
`from gsheet_source import load_long_table_from_gsheet as load_long_table`.
The long-table schema (`student, project, task, hours, signals, week, date, notes`)
is unchanged, so `gsheet_source.py` stays a drop-in match — nothing else changes.

## Run it

```bash
pip install -r requirements.txt
streamlit run app.py
```

Put `Working_Hours_Tracker.xlsx` next to `app.py` as `data.xlsx`, or upload any
tracker from the sidebar.

## The five tabs

1. **Overview** — headline KPIs (each with an ⓘ tooltip explaining the metric) and a
   per-week **sparkline** behind every number, hours by project (bars labelled with
   the hour value; click one to cross-filter), share-of-effort donut, and the
   **TPfC Phase 3 vs Phase 4** spotlight + side-by-side comparison panel.
2. **Time Breakdown** — a sidebar **granularity** radio (Weekly / Bi-weekly / Monthly)
   and a **split-by** toggle (Project / Task) drive five linked charts: stacked-area
   hours, 100%-stacked share-of-effort drift, small-multiple line charts, a
   period × group **heatmap**, and cumulative running-total hours. All three
   granularities use the same logic; Monthly simply shows fewer buckets while the
   sheet covers a short span and fills out as more weeks are logged.
3. **Tasks & Efficiency** — three tables (project-wise summary, task-wise summary, and
   the project → task breakdown) plus weekly momentum and the **learning-curve**
   (weighted min/signal per week). Respects the Overview cross-filter.
4. **Team** — per-student view: a sortable summary table, ranked hours bar,
   student × project heatmap, and a per-student drilldown.
5. **Data Quality** — rows with likely entry problems (blank tasks, tasks logged under
   the wrong project, unusually long days), run on the *full* dataset.

## Interactivity & theme

Charts are **Plotly**: hover for rich tooltips (hours, signals, person-days, weighted
min/signal), drag to zoom/pan, click a legend entry to isolate a series. Clicking a
bar in **Hours by project** sets a cross-filter that flows into the Tasks & Efficiency
tab; a **Clear** button resets it. The colour theme (green / navy / teal) is
Miovision-inspired and centralised in `.streamlit/config.toml` plus the `PALETTE`
constant in `app.py`. The page uses a wide layout (`max-width: 95%`) to minimise blank
side margins — change that one value in `app.py` if you prefer a capped width.

## Metric note — Person-Days vs Active Days

"Logged Days" used to count **rows**, which is actually **person-days** (one student ×
one date), not calendar days — the dataset only spans **46 distinct dates**. It is now
split into honest metrics:

- **Person-Days** — number of logged rows (a measure of *effort*).
- **Active Days** — number of **distinct calendar dates** with work in the group.
- **Avg Hrs/Person-Day** — total hours ÷ person-days (typical length of a logged day).

These appear in the project and task tables and in the headline KPIs (with tooltips).

## Methodology note — average time per signal

The dashboard uses a **weighted** average: `total hours on signal-bearing rows /
total signals × 60`. This is the honest figure. The naive alternative (averaging the
per-row "Time per Signal" column) over-weights low-signal days and misleads. Days
logged in hours only (no signal count) are excluded from the per-signal figure but
still count toward total hours. The Phase 3 vs Phase 4 ramp callout is **computed from
the data**, never hardcoded, so it stays correct as `data.xlsx` updates.
