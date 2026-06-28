"""
Layer 3 — PRESENTATION (Streamlit).

Project-level overview dashboard. Five tabs:
  1. Overview        — KPIs (+ sparklines), hours by project, share of effort,
                       Phase 3 vs Phase 4 spotlight.
  2. Time Breakdown  — weekly / bi-weekly / monthly toggle drives stacked area,
                       100%-stacked effort drift, small-multiples, heatmap, cumulative.
  3. Tasks & Efficiency — project-wise + task-wise + project→task tables (each with a
                       Total row) and learning-curve charts (respects cross-filter).
  4. Team            — per-student view (student_view.py).
  5. Data Quality    — flags table.

Charts use Plotly for zoom/pan/hover + legend isolate, plus a Plotly click
selection on the project bar that CROSS-FILTERS the task/efficiency views.

Theme: Miovision-inspired green / navy / teal (see .streamlit/config.toml).

Run:  streamlit run app.py
Swap data source later: replace load_long_table() with a Google Sheets loader
that returns the same columns — nothing below changes.
"""

from __future__ import annotations
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st

from data_source import load_long_table, load_reference, COL_PROJECT, COL_TASK, COL_WEEK, COL_HOURS, COL_SIGNALS
import aggregations as agg
import student_view as sv
from data_quality import quality_flags

st.set_page_config(page_title="Project Hours Overview", layout="wide", page_icon="📊")

# Miovision-inspired palette keyed to project so a project is the SAME colour everywhere.
# Brand cues: bright green accent, deep navy, teal. Tune these hex values to the exact
# corporate values if you have the brand guide.
MIO_GREEN = "#1FA85C"
MIO_TEAL = "#0E8A8A"
MIO_NAVY = "#15426B"
MIO_AMBER = "#F39C12"
PALETTE = [MIO_GREEN, MIO_TEAL, MIO_NAVY, MIO_AMBER, "#7B5BA6", "#C0392B", "#16A085"]
PLOTLY_TEMPLATE = "plotly_white"

st.markdown(f"""
<style>
  /* Wider canvas: fills more of the screen so there's less blank space left/right.
     Change 95% to a fixed px (e.g. 1500px) if you prefer a capped width. */
  .block-container {{padding-top: 1.3rem; padding-left: 2.2rem; padding-right: 2.2rem; max-width: 95%;}}
  h1, h2, h3 {{letter-spacing: -0.4px;}}
  [data-testid="stMetricValue"] {{font-size: 1.55rem; font-weight: 700; color: {MIO_NAVY};}}
  [data-testid="stMetricLabel"] {{opacity: 0.8;}}
  /* Header bar */
  .hero {{
     background: linear-gradient(110deg, #10212B 0%, #0E5A66 55%, {MIO_GREEN} 100%);
     padding: 1.1rem 1.4rem; border-radius: 14px; color: #fff; margin-bottom: 1.1rem;
     box-shadow: 0 6px 22px rgba(16,33,43,0.22);
  }}
  .hero h1 {{margin: 0; font-size: 1.7rem; font-weight: 800; color:#fff;}}
  .hero p {{margin: 0.25rem 0 0 0; opacity: 0.93; font-size: 0.92rem;}}
  .callout {{
     background: #ecfdf3; border: 1px solid #abe5c4; border-left: 5px solid {MIO_GREEN};
     padding: 0.8rem 1rem; border-radius: 10px; font-size: 0.92rem; margin-top: 0.4rem;
  }}
  .stTabs [data-baseweb="tab"] {{font-weight: 600;}}
  .stTabs [aria-selected="true"] {{color: {MIO_GREEN};}}
</style>
""", unsafe_allow_html=True)


@st.cache_data(show_spinner=False)
def get_data(file_bytes: bytes | None, path: str):
    src = file_bytes if file_bytes is not None else path
    df = load_long_table(src)
    ref = load_reference(src)
    return df, ref


def project_color_map(projects) -> dict:
    """Stable project -> colour map (sorted so colours don't shuffle when filtering)."""
    return {p: PALETTE[i % len(PALETTE)] for i, p in enumerate(sorted(projects))}


def fmt_tps(v) -> str:
    return f"{v:.1f} min/sig" if pd.notna(v) else "no signal data"


# How the weighted time-per-signal is computed — reused as a help string / caption.
WEIGHTED_HELP = ("Weighted figure: total hours on signal-bearing rows ÷ total signals × 60. "
                 "It is NOT the average of the per-row 'Time per Signal' column "
                 "(that would over-weight low-signal days).")

# ===========================================================================
# Sidebar — data source + filters + granularity
# ===========================================================================
st.sidebar.header("Data source")
uploaded = st.sidebar.file_uploader("Working Hours Tracker (.xlsx)", type=["xlsx"])
file_bytes = uploaded.getvalue() if uploaded else None

try:
    df, reference = get_data(file_bytes, "data.xlsx")
except Exception as e:
    st.error(f"Could not read the tracker: {e}")
    st.stop()

if df.empty:
    st.warning("No logged rows found in the tracker.")
    st.stop()

# Colour map built from the FULL dataset so colours are stable under filtering.
CMAP = project_color_map(df[COL_PROJECT].unique())

st.sidebar.header("Filters")
all_projects = sorted(df[COL_PROJECT].unique())
sel_projects = st.sidebar.multiselect("Projects", all_projects, default=all_projects)
weeks = sorted([int(w) for w in df[COL_WEEK].dropna().unique()])
if weeks:
    wmin, wmax = st.sidebar.select_slider(
        "Calendar week (KW) range", options=weeks, value=(weeks[0], weeks[-1])
    )
else:
    wmin, wmax = None, None

st.sidebar.header("Time granularity")
granularity = st.sidebar.radio(
    "Bucket size (drives the Time Breakdown tab)",
    agg.GRANULARITIES, index=0,
    help="Weekly, Bi-weekly and Monthly all use the same logic. Monthly currently shows "
         "fewer buckets simply because the sheet covers a short span — it fills out "
         "automatically as more weeks are logged.",
)
split_by_label = st.sidebar.radio("Split breakdowns by", ["Project", "Task"], index=0)
SPLIT = COL_PROJECT if split_by_label == "Project" else COL_TASK

mask = df[COL_PROJECT].isin(sel_projects)
if wmin is not None:
    mask &= df[COL_WEEK].between(wmin, wmax)
fdf = df[mask].copy()

if fdf.empty:
    st.warning("No rows match the current filters. Widen the project or week selection.")
    st.stop()

# Cross-filter state (set by clicking a project bar on the Overview tab).
if "sel_proj" not in st.session_state:
    st.session_state.sel_proj = None
# Drop a stale cross-filter if that project is no longer in the sidebar selection.
if st.session_state.sel_proj and st.session_state.sel_proj not in sel_projects:
    st.session_state.sel_proj = None


# ---- small helpers for charts -------------------------------------------------
def make_sparkline(x, y, color: str) -> go.Figure:
    """Tiny inline trend chart shown under a KPI number."""
    fig = go.Figure(go.Scatter(
        x=list(x), y=list(y), mode="lines", line=dict(color=color, width=2),
        fill="tozeroy", fillcolor="rgba(31,168,92,0.10)",
        hovertemplate="%{x}: %{y}<extra></extra>",
    ))
    fig.update_layout(
        height=58, margin=dict(l=0, r=0, t=4, b=0),
        xaxis=dict(visible=False), yaxis=dict(visible=False),
        showlegend=False, template=PLOTLY_TEMPLATE,
        plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
    )
    return fig


def weekly_overall_series(d: pd.DataFrame) -> pd.DataFrame:
    """Per-week overall hours, signals and weighted min/signal for KPI sparklines."""
    rows = []
    for wk, g in d.dropna(subset=[COL_WEEK]).groupby(COL_WEEK):
        rows.append({
            "week": f"KW {int(wk)}",
            "hours": round(g[COL_HOURS].sum(), 1),
            "signals": int(g[COL_SIGNALS].dropna().sum()),
            "tps": round(agg._weighted_tps(g), 1),
        })
    return pd.DataFrame(rows)


def full_grid(d: pd.DataFrame, gran: str, by: str) -> pd.DataFrame:
    """Complete period × group grid (zero-filled) with hours, share and cumulative —
    so stacked/area/cumulative charts never misalign on empty buckets."""
    grid = agg.cumulative_hours(d, gran, by)  # period, by, hours, period_order, cumulative_hours
    if grid.empty:
        return grid
    totals = grid.groupby("period")["hours"].transform("sum")
    grid = grid.copy()
    grid["share"] = (100 * grid["hours"] / totals).round(1).fillna(0.0)
    return grid


def period_order(grid: pd.DataFrame) -> list[str]:
    return grid.sort_values("period_order")["period"].drop_duplicates().tolist()


def color_args(by: str):
    """Use the stable colour map only when splitting by project (tasks get a sequence)."""
    if by == COL_PROJECT:
        return dict(color_discrete_map=CMAP)
    return dict(color_discrete_sequence=px.colors.qualitative.Safe)


# ===========================================================================
# Header
# ===========================================================================
st.markdown(
    '<div class="hero"><h1>📊 Project Hours — General Overview</h1>'
    f'<p>Project- and task-level performance across the team · KW {wmin}–{wmax}.</p></div>',
    unsafe_allow_html=True,
)

tab_overview, tab_time, tab_tasks, tab_team, tab_quality = st.tabs(
    ["📈 Overview", "🗓️ Time Breakdown", "🧩 Tasks & Efficiency",
     "👥 Team", "🔎 Data Quality"]
)

# ===========================================================================
# TAB 1 — OVERVIEW
# ===========================================================================
with tab_overview:
    k = agg.headline_numbers(fdf)
    wk_series = weekly_overall_series(fdf)

    cols = st.columns(5)
    cols[0].metric("Total hours", f"{k['total_hours']:.0f}",
                   help="Sum of Duration (Hrs) across every logged row in the current filter.")
    cols[1].metric("Total signals", f"{k['total_signals']:,}",
                   help="Sum of signals recorded (signal-bearing rows only).")
    cols[2].metric("Avg time / signal", f"{k['weighted_tps']:.1f} min", help=WEIGHTED_HELP)
    cols[3].metric("Person-Days", f"{k['person_days']:,}",
                   help="One logged row = one person on one day. Counts effort "
                        "(student × date), NOT calendar days.")
    cols[4].metric("Active Days", f"{k['active_days']}",
                   help="Number of DISTINCT calendar dates that have any logged work "
                        "(the dataset spans 46 distinct dates in total).")
    if not wk_series.empty:
        cfg = {"displayModeBar": False}
        cols[0].plotly_chart(make_sparkline(wk_series["week"], wk_series["hours"], MIO_GREEN),
                             use_container_width=True, config=cfg, key="sp_hours")
        cols[1].plotly_chart(make_sparkline(wk_series["week"], wk_series["signals"], MIO_TEAL),
                             use_container_width=True, config=cfg, key="sp_sig")
        cols[2].plotly_chart(make_sparkline(wk_series["week"], wk_series["tps"], MIO_NAVY),
                             use_container_width=True, config=cfg, key="sp_tps")
        pd_wk = fdf.dropna(subset=[COL_WEEK]).groupby(COL_WEEK).size()
        ad_wk = fdf.dropna(subset=[COL_WEEK]).groupby(COL_WEEK)["date"].apply(
            lambda s: s.dt.normalize().nunique())
        cols[3].plotly_chart(make_sparkline([f"KW {int(w)}" for w in pd_wk.index], pd_wk.values, MIO_AMBER),
                             use_container_width=True, config=cfg, key="sp_pd")
        cols[4].plotly_chart(make_sparkline([f"KW {int(w)}" for w in ad_wk.index], ad_wk.values, "#7B5BA6"),
                             use_container_width=True, config=cfg, key="sp_ad")
    st.caption("Hover the ⓘ on any KPI for its definition. Sparklines show the per-week trend.")

    st.divider()
    psum = agg.project_summary(fdf)

    left, right = st.columns([1.25, 1])
    with left:
        st.subheader("Hours by project")
        st.caption("Click a bar to cross-filter the Tasks & Efficiency tab. Click again or use Clear to reset.")
        bar = px.bar(
            psum, x="Total Hours", y="Project", orientation="h",
            color="Project", **color_args(COL_PROJECT), text="Total Hours",
            custom_data=["Total Signals", "Avg Time/Signal (min)", "Person-Days",
                         "Active Days", "% of Hours"],
        )
        bar.update_traces(
            marker=dict(cornerradius=6, line=dict(width=0)),
            texttemplate="%{text:.0f} h", textposition="outside", cliponaxis=False,
            hovertemplate=("<b>%{y}</b><br>Hours: %{x}<br>Signals: %{customdata[0]:,}<br>"
                           "Weighted: %{customdata[1]} min/sig<br>Person-Days: %{customdata[2]}<br>"
                           "Active Days: %{customdata[3]}<br>Share: %{customdata[4]}%<extra></extra>"),
        )
        bar.update_layout(
            template=PLOTLY_TEMPLATE, height=300, showlegend=False,
            margin=dict(l=4, r=40, t=8, b=4), yaxis=dict(title=None, categoryorder="total ascending"),
            xaxis=dict(title="Hours"),
        )
        event = st.plotly_chart(bar, use_container_width=True, on_select="rerun",
                                key="proj_bar", config={"displayModeBar": False})
        pts = (event.get("selection") or {}).get("points", []) if event else []
        if pts:
            clicked = pts[0].get("y") or pts[0].get("label")
            if clicked:
                st.session_state.sel_proj = clicked
        if st.session_state.sel_proj:
            cc1, cc2 = st.columns([3, 1])
            cc1.info(f"Cross-filter active: **{st.session_state.sel_proj}** "
                     "→ applied to Tasks & Efficiency.")
            if cc2.button("Clear", use_container_width=True):
                st.session_state.sel_proj = None
                st.rerun()
    with right:
        st.subheader("Share of total effort")
        donut = px.pie(
            psum, names="Project", values="Total Hours", hole=0.55,
            color="Project", **color_args(COL_PROJECT),
        )
        donut.update_traces(
            textposition="inside", texttemplate="%{percent}",
            hovertemplate="<b>%{label}</b><br>%{value} hrs<br>%{percent}<extra></extra>",
        )
        donut.update_layout(template=PLOTLY_TEMPLATE, height=300,
                            margin=dict(l=4, r=4, t=8, b=4),
                            legend=dict(orientation="h", y=-0.12))
        st.plotly_chart(donut, use_container_width=True, config={"displayModeBar": False})

    st.dataframe(
        psum, use_container_width=True, hide_index=True,
        column_config={
            "Total Hours": st.column_config.NumberColumn(format="%.1f"),
            "Total Signals": st.column_config.NumberColumn(format="%d"),
            "Avg Time/Signal (min)": st.column_config.NumberColumn(
                "Avg Time/Signal (min)", help=WEIGHTED_HELP, format="%.1f"),
            "% of Hours": st.column_config.ProgressColumn(
                "% of Hours", format="%.1f%%", min_value=0,
                max_value=float(psum["% of Hours"].max()) if not psum.empty else 100),
        },
    )
    st.caption("ℹ️ **Avg Time/Signal** is a *weighted* figure: total hours on signal-bearing "
               "rows ÷ total signals × 60 — not an average of the per-row column.")

    st.divider()
    # ---- Phase 3 vs Phase 4 spotlight + comparison panel ----
    st.subheader("TPfC — Phase 3 vs Phase 4")
    comp = agg.phase_comparison(fdf)
    if comp.empty:
        st.info("No TPfC phase rows in the current filter.")
    else:
        mcols = st.columns(len(comp))
        for col, (_, r) in zip(mcols, comp.iterrows()):
            col.metric(r["Phase"], f"{r['Total Hours']:.0f} hrs",
                       fmt_tps(r["Weighted Time/Signal (min)"]), delta_color="off")
        p1, p2 = st.columns([1.1, 1])
        with p1:
            metrics = ["Total Hours", "Total Signals", "Weighted Time/Signal (min)"]
            melt = comp.melt(id_vars="Phase", value_vars=metrics,
                             var_name="Metric", value_name="Value")
            gcmp = px.bar(melt, x="Metric", y="Value", color="Phase", barmode="group",
                          color_discrete_sequence=[MIO_NAVY, MIO_GREEN], text="Value")
            gcmp.update_traces(textposition="outside", cliponaxis=False)
            gcmp.update_layout(template=PLOTLY_TEMPLATE, height=320,
                               margin=dict(l=4, r=4, t=30, b=4),
                               yaxis_title=None, xaxis_title=None,
                               legend=dict(orientation="h", y=1.12))
            st.plotly_chart(gcmp, use_container_width=True, config={"displayModeBar": False})
        with p2:
            st.dataframe(comp.set_index("Phase").T, use_container_width=True)
        note = agg.phase_ramp_note(comp)
        if note:
            st.markdown(f'<div class="callout">⏳ {note}</div>', unsafe_allow_html=True)

# ===========================================================================
# TAB 2 — TIME BREAKDOWN  (driven by granularity + split toggle)
# ===========================================================================
with tab_time:
    st.subheader(f"Time breakdown — {granularity}, by {split_by_label.lower()}")
    st.caption("Use the sidebar to change granularity (Weekly / Bi-weekly / Monthly) "
               "and whether to split by project or task. All charts below update together.")

    grid = full_grid(fdf, granularity, SPLIT)
    if grid.empty:
        st.info("Not enough dated rows for this granularity.")
    else:
        porder = period_order(grid)

        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**a) Hours per period (stacked)**")
            area = px.area(grid, x="period", y="hours", color=SPLIT,
                           category_orders={"period": porder}, **color_args(SPLIT),
                           custom_data=["share"])
            area.update_traces(hovertemplate="%{x}<br>%{fullData.name}: %{y} hrs "
                                             "(%{customdata[0]}%)<extra></extra>")
            area.update_layout(template=PLOTLY_TEMPLATE, height=330,
                               margin=dict(l=4, r=4, t=8, b=4), xaxis_title=None,
                               yaxis_title="Hours", legend=dict(title=None))
            st.plotly_chart(area, use_container_width=True, config={"displayModeBar": False})
        with c2:
            st.markdown("**b) Share-of-effort drift (100%)**")
            area100 = px.area(grid, x="period", y="share", color=SPLIT,
                              category_orders={"period": porder}, **color_args(SPLIT),
                              groupnorm="percent", custom_data=["hours"])
            area100.update_traces(hovertemplate="%{x}<br>%{fullData.name}: %{y:.1f}% "
                                                "(%{customdata[0]} hrs)<extra></extra>")
            area100.update_layout(template=PLOTLY_TEMPLATE, height=330,
                                  margin=dict(l=4, r=4, t=8, b=4), xaxis_title=None,
                                  yaxis_title="Share of hours (%)", legend=dict(title=None))
            st.plotly_chart(area100, use_container_width=True, config={"displayModeBar": False})

        st.markdown(f"**c) Small multiples — each {split_by_label.lower()}'s hours trend**")
        facet = px.line(grid, x="period", y="hours", color=SPLIT, facet_col=SPLIT,
                        facet_col_wrap=3, markers=True, category_orders={"period": porder},
                        **color_args(SPLIT))
        facet.update_yaxes(matches=None, showticklabels=True)  # each mini-chart scales to itself
        facet.for_each_annotation(lambda a: a.update(text=a.text.split("=")[-1]))
        facet.update_layout(template=PLOTLY_TEMPLATE, showlegend=False,
                            height=120 * (1 + (grid[SPLIT].nunique() - 1) // 3) + 60,
                            margin=dict(l=4, r=4, t=30, b=4))
        facet.update_xaxes(title=None)
        st.plotly_chart(facet, use_container_width=True, config={"displayModeBar": False})

        c3, c4 = st.columns([1.15, 1])
        with c3:
            st.markdown("**d) Heatmap — periods × " + split_by_label.lower() + " (hours)**")
            hm = agg.heatmap_data(fdf, granularity, SPLIT)
            if not hm.empty:
                heat = px.imshow(hm, text_auto=".0f", aspect="auto",
                                 color_continuous_scale="Greens",
                                 labels=dict(color="Hours"))
                heat.update_layout(template=PLOTLY_TEMPLATE, height=max(260, 40 * len(hm) + 120),
                                   margin=dict(l=4, r=4, t=8, b=4),
                                   xaxis_title=None, yaxis_title=None)
                heat.update_xaxes(side="bottom")
                st.plotly_chart(heat, use_container_width=True, config={"displayModeBar": False})
        with c4:
            st.markdown("**e) Cumulative hours (running total)**")
            cum = px.line(grid, x="period", y="cumulative_hours", color=SPLIT, markers=True,
                          category_orders={"period": porder}, **color_args(SPLIT))
            cum.update_traces(hovertemplate="%{x}<br>%{fullData.name}: %{y} hrs cumulative<extra></extra>")
            cum.update_layout(template=PLOTLY_TEMPLATE, height=max(260, 40 * len(hm) + 120) if not hm.empty else 320,
                              margin=dict(l=4, r=4, t=8, b=4), xaxis_title=None,
                              yaxis_title="Cumulative hours", legend=dict(title=None))
            st.plotly_chart(cum, use_container_width=True, config={"displayModeBar": False})

# ===========================================================================
# TAB 3 — TASKS & EFFICIENCY  (respects the Overview cross-filter)
# ===========================================================================
with tab_tasks:
    focus = st.session_state.sel_proj
    if focus:
        st.info(f"Showing **{focus}** (cross-filtered from the Overview bar). "
                "Clear the selection on the Overview tab to see all projects.")
    colp = st.columns([2, 1])
    proj_options = ["All"] + sorted(fdf[COL_PROJECT].unique())
    default_idx = proj_options.index(focus) if focus in proj_options else 0
    proj_pick = colp[0].selectbox("Focus project", proj_options, index=default_idx)
    effective_proj = None if proj_pick == "All" else proj_pick
    eff_df = fdf if effective_proj is None else fdf[fdf[COL_PROJECT] == effective_proj]
    st.caption("Each table ends with a **Total** row computed from the underlying rows "
               "(weighted time/signal and active days are recomputed, not summed).")

    _tps_cfg = {
        "Total Hours": st.column_config.NumberColumn(format="%.1f"),
        "Total Signals": st.column_config.NumberColumn(format="%d"),
        "Avg Time/Signal (min)": st.column_config.NumberColumn(
            "Avg Time/Signal (min)", help=WEIGHTED_HELP, format="%.1f"),
    }
    _pct_cfg = {**_tps_cfg,
                "% of Hours": st.column_config.NumberColumn("% of Hours", format="%.1f%%")}

    # 1) Project-wise
    st.subheader("Project-wise summary")
    st.dataframe(agg.project_summary(eff_df, with_total=True), use_container_width=True,
                 hide_index=True, column_config=_pct_cfg)

    # 2) Task-wise (task collapsed across projects)
    st.subheader("Task-wise summary")
    st.caption("Tasks aggregated on their own (collapsed across projects).")
    st.dataframe(agg.task_rollup(fdf, effective_proj, with_total=True),
                 use_container_width=True, hide_index=True, column_config=_pct_cfg)

    # 3) Project → Task breakdown (the original table)
    st.subheader("Project → Task breakdown")
    st.dataframe(agg.task_summary(fdf, effective_proj, with_total=True),
                 use_container_width=True, hide_index=True, column_config=_tps_cfg)

    st.divider()
    m1, m2 = st.columns(2)
    with m1:
        st.subheader("Weekly hours (momentum)")
        wt = agg.weekly_trend(eff_df).reset_index().melt(
            COL_WEEK, var_name="Project", value_name="Hours")
        wt["KW"] = "KW " + wt[COL_WEEK].astype(int).astype(str)
        line = px.line(wt, x="KW", y="Hours", color="Project", markers=True, **color_args(COL_PROJECT))
        line.update_layout(template=PLOTLY_TEMPLATE, height=320, xaxis_title=None,
                           margin=dict(l=4, r=4, t=8, b=4), legend=dict(title=None))
        st.plotly_chart(line, use_container_width=True, config={"displayModeBar": False})
    with m2:
        st.subheader("Learning curve (min / signal)")
        we = agg.weekly_efficiency(eff_df).reset_index().rename(columns={"index": COL_WEEK})
        we = we.melt(COL_WEEK, var_name="Project", value_name="Min/Signal").dropna()
        if not we.empty:
            we["KW"] = "KW " + we[COL_WEEK].astype(int).astype(str)
            eline = px.line(we, x="KW", y="Min/Signal", color="Project", markers=True,
                            **color_args(COL_PROJECT))
            eline.update_layout(template=PLOTLY_TEMPLATE, height=320, xaxis_title=None,
                               margin=dict(l=4, r=4, t=8, b=4), legend=dict(title=None))
            st.plotly_chart(eline, use_container_width=True, config={"displayModeBar": False})
            st.caption("Downward slope = team getting faster per signal.")
        else:
            st.info("No signal-bearing rows for this selection.")

# ===========================================================================
# TAB 4 — TEAM
# ===========================================================================
with tab_team:
    ssum = sv.student_summary(fdf)
    st.subheader("Per-student summary")
    st.caption("Hours, signals and activity per person. Click a column header to sort.")
    st.dataframe(
        ssum, use_container_width=True, hide_index=True,
        column_config={
            "Total Hours": st.column_config.NumberColumn(format="%.1f"),
            "Weighted Time/Signal (min)": st.column_config.NumberColumn(
                "Weighted Time/Signal (min)", help=WEIGHTED_HELP, format="%.1f"),
        },
    )

    c1, c2 = st.columns([1, 1])
    with c1:
        st.subheader("Hours per student (ranked)")
        rank = sv.student_hours_ranking(fdf)
        rbar = px.bar(rank, x="Total Hours", y="Student", orientation="h",
                      color="Total Hours", color_continuous_scale="Greens", text="Total Hours")
        rbar.update_traces(marker=dict(cornerradius=4), texttemplate="%{text:.0f}",
                           textposition="outside", cliponaxis=False,
                           hovertemplate="<b>%{y}</b><br>%{x} hrs<extra></extra>")
        rbar.update_layout(template=PLOTLY_TEMPLATE, height=460, coloraxis_showscale=False,
                           yaxis=dict(categoryorder="total ascending", title=None),
                           xaxis_title="Hours", margin=dict(l=4, r=30, t=8, b=4))
        st.plotly_chart(rbar, use_container_width=True, config={"displayModeBar": False})
    with c2:
        st.subheader("Student × project heatmap")
        mtx = sv.student_project_matrix(fdf)
        if not mtx.empty:
            sheat = px.imshow(mtx, text_auto=".0f", aspect="auto",
                              color_continuous_scale="Tealgrn", labels=dict(color="Hours"))
            sheat.update_layout(template=PLOTLY_TEMPLATE, height=460,
                                margin=dict(l=4, r=4, t=8, b=4),
                                xaxis_title=None, yaxis_title=None)
            st.plotly_chart(sheat, use_container_width=True, config={"displayModeBar": False})

    st.divider()
    st.subheader("Individual drilldown")
    who = st.selectbox("Student", sorted(fdf["student"].unique()))
    d1, d2 = st.columns([1, 1.2])
    with d1:
        split = sv.student_project_split(fdf, who)
        sd = px.pie(split, names="Project", values="Total Hours", hole=0.5,
                    color="Project", **color_args(COL_PROJECT))
        sd.update_traces(textposition="inside", texttemplate="%{percent}",
                         hovertemplate="<b>%{label}</b><br>%{value} hrs<extra></extra>")
        sd.update_layout(template=PLOTLY_TEMPLATE, height=300,
                         margin=dict(l=4, r=4, t=30, b=4), title=f"{who} — project split",
                         legend=dict(orientation="h", y=-0.1))
        st.plotly_chart(sd, use_container_width=True, config={"displayModeBar": False})
    with d2:
        wtr = sv.student_weekly_trend(fdf, who)
        wtr["KW"] = "KW " + wtr["week"].astype(str)
        sl = px.area(wtr, x="KW", y="Hours", markers=True,
                     color_discrete_sequence=[MIO_TEAL])
        sl.update_layout(template=PLOTLY_TEMPLATE, height=300, xaxis_title=None,
                         margin=dict(l=4, r=4, t=30, b=4), title=f"{who} — weekly hours")
        st.plotly_chart(sl, use_container_width=True, config={"displayModeBar": False})

# ===========================================================================
# TAB 5 — DATA QUALITY
# ===========================================================================
with tab_quality:
    st.subheader("Data-quality flags")
    st.caption("Run on the FULL dataset (not the sidebar filter) so nothing hides. "
               "These rows can silently distort project totals.")
    flags = quality_flags(df, reference)
    if flags.empty:
        st.success("No data-quality issues detected.")
    else:
        st.metric("Flagged rows", len(flags))
        st.dataframe(flags, use_container_width=True, hide_index=True)
