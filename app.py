"""Running dashboards website (Flask).

    python app.py          -> http://127.0.0.1:5000

Pages
    /weekly    weekly insights; ?week=YYYY-MM-DD (Monday) and ?day=YYYY-MM-DD
    /monthly   monthly insights; ?month=YYYY-MM
"""
from __future__ import annotations

import pandas as pd
from flask import Flask, redirect, render_template, request, url_for
from markupsafe import Markup

import analytics as an
import charts

app = Flask(__name__)

LEVEL_COLORS = [f"var(--series-{i})" for i in range(1, 6)]
LEVEL_SHORT = ["2w/1r", "1w/2r", "1w/3r", "1w/5r", "Run"]


def get_data():
    """Reload the CSV on every request so edits to the file show up on refresh."""
    df = an.load_runs()
    return df, an.weekly_table(df), an.monthly_table(df)


def kpi(label, value, d: an.Delta | None = None, sub: str | None = None):
    return {"label": label, "value": value, "delta": d, "sub": sub}


@app.template_filter("pace")
def _pace(v):
    return an.fmt_pace(v)


@app.route("/")
def index():
    return redirect(url_for("weekly"))


# --------------------------------------------------------------------------- #
# Weekly dashboard
# --------------------------------------------------------------------------- #
@app.route("/weekly")
def weekly():
    df, weeks, _ = get_data()
    week_starts = list(weeks["week_start"])

    sel = request.args.get("week")
    try:
        sel_ws = pd.Timestamp(sel) if sel else week_starts[-1]
        idx = week_starts.index(sel_ws)
    except (ValueError, KeyError):
        idx, sel_ws = len(week_starts) - 1, week_starts[-1]

    cur = weeks.iloc[idx].to_dict()
    prev = weeks.iloc[idx - 1].to_dict() if idx > 0 else None
    week_runs = df[df["week_start"] == sel_ws]
    week_key = sel_ws.strftime("%Y-%m-%d")
    day = request.args.get("day")
    if day not in set(week_runs["day_key"]):
        day = None

    # ---- filter options ---------------------------------------------------
    week_options = [
        {"value": w.strftime("%Y-%m-%d"),
         "label": f"Week of {w:%d %b} (W{w.isocalendar().week}) · {int(r)} run{'s' if r != 1 else ''}"}
        for w, r in zip(weeks["week_start"], weeks["runs"])
    ]
    day_chips = [{"key": None, "label": "All days", "active": day is None}] + [
        {"key": r["day_key"], "label": f"{r['Date']:%a %d}", "active": r["day_key"] == day}
        for _, r in week_runs.iterrows()
    ]
    nav = {
        "prev": week_starts[idx - 1].strftime("%Y-%m-%d") if idx > 0 else None,
        "next": week_starts[idx + 1].strftime("%Y-%m-%d") if idx < len(week_starts) - 1 else None,
    }
    ctx = dict(page="weekly", week_key=week_key, week_options=week_options,
               day_chips=day_chips, nav=nav, day=day, week_start=sel_ws,
               week_end=sel_ws + pd.Timedelta(days=6))

    if day:
        return render_template("weekly.html", **ctx, **_day_view(week_runs, day))

    # ---- KPIs -------------------------------------------------------------
    lbl = "last week"
    p = prev or {}
    kpis = [
        kpi("Runs", f"{cur['runs']}", an.delta(cur["runs"], p.get("runs"), label=lbl), "target 3–4"),
        kpi("Distance", f"{cur['km']:.1f} km", an.delta(cur["km"], p.get("km"), unit=" km", label=lbl)),
        kpi("Time", an.fmt_duration(cur["minutes"]), None),
        kpi("Avg pace", f"{an.fmt_pace(cur['pace'])} /km",
            an.delta(cur["pace"], p.get("pace"), lower_is_better=True, fmt=an.fmt_pace, label=lbl)),
        kpi("Avg heart rate", f"{cur['avg_hr']:.0f} bpm" if cur["runs"] else "–", None,
            f"max {cur['max_hr']:.0f}" if cur["runs"] else None),
        kpi("Calories", f"{cur['calories']:,.0f}", an.delta(cur["calories"], p.get("calories"), label=lbl)),
        kpi("Elevation", f"{cur['elevation']:,.0f} m", None),
        kpi("Pace variation", f"±{cur['variation']:.0f} s" if cur["runs"] else "–",
            an.delta(cur["variation"], p.get("variation"), unit=" s", lower_is_better=True, label=lbl),
            "lower = more even"),
    ]

    # ---- Charts -----------------------------------------------------------
    days = [sel_ws + pd.Timedelta(days=i) for i in range(7)]
    by_day = {r["day_key"]: r for _, r in week_runs.iterrows()}
    km_by_day, tips, links = [], [], []
    for d in days:
        r = by_day.get(d.strftime("%Y-%m-%d"))
        km_by_day.append(r["Distance (km)"] if r is not None else 0)
        tips.append(
            f"{d:%a %d %b}: {r['Distance (km)']:.1f} km · {an.fmt_pace(r['pace'])} /km · {r['Interval Type']} — click for km splits"
            if r is not None else f"{d:%a %d %b}: rest day"
        )
        links.append(url_for("weekly", week=week_key, day=d.strftime("%Y-%m-%d")) if r is not None else None)
    chart_days = charts.bar_chart(
        [f"{d:%a}" for d in days], km_by_day, label="Distance per day this week",
        fmt=lambda v: f"{v:g}", tips=tips, links=links, value_labels=True, height=145, width=520)

    # all runs this week overlaid: per-km pace lines
    split_series = []
    for i, (_, r) in enumerate(week_runs.iterrows()):
        vals = [None if pd.isna(v) else v for v in r[an.SPLIT_COLS]]
        split_series.append({
            "name": f"{r['Date']:%a}", "values": vals,
            "color": f"var(--series-{i + 1})", "end_label": True,
            "tips": [f"{r['Date']:%a} · Km {k + 1}: {an.fmt_pace(v)} /km" if v else None for k, v in enumerate(vals)],
        })
    chart_splits = charts.line_chart(
        [f"Km {i}" for i in range(1, 11)], split_series, label="Per-km pace of each run this week",
        pace_axis=True, fmt=an.fmt_pace, y_note="min/km · faster ↑", height=145, width=520,
    ) if split_series else None
    legend_splits = [{"name": f"{r['Date']:%a %d %b} · {r['Distance (km)']:.1f} km", "color": f"var(--series-{i + 1})"}
                     for i, (_, r) in enumerate(week_runs.iterrows())]

    # trend across all weeks
    wl = [f"{w:%d %b}" for w in weeks["week_start"]]
    wlinks = [url_for("weekly", week=w.strftime("%Y-%m-%d")) for w in weeks["week_start"]]
    chart_trend_pace = charts.line_chart(
        wl, [{"name": "Avg pace", "values": [None if pd.isna(v) else v for v in weeks["pace"]],
              "color": "var(--series-1)",
              "tips": [f"Week of {w:%d %b}: {an.fmt_pace(v)} /km" if not pd.isna(v) else None
                       for w, v in zip(weeks["week_start"], weeks["pace"])]}],
        label="Average pace by week", pace_axis=True, fmt=an.fmt_pace, highlight=idx,
        label_every=3, y_note="min/km · faster ↑", height=145, width=520, links=wlinks)
    chart_trend_runs = charts.bar_chart(
        wl, list(weeks["runs"]), label="Runs per week", highlight=idx, label_every=3, height=145, width=520,
        tips=[f"Week of {w:%d %b}: {r} runs · {k:.1f} km" for w, r, k in
              zip(weeks["week_start"], weeks["runs"], weeks["km"])],
        links=wlinks)

    table = [{
        "date": r["Date"], "day_key": r["day_key"], "type": r["Interval Type"], "level": int(r["level"]),
        "km": r["Distance (km)"], "dur": r["Duration (min)"], "pace": r["pace"],
        "hr": r["Avg HR (bpm)"], "maxhr": r["Max HR (bpm)"], "cal": r["Calories (kcal)"],
        "elev": r["Elevation Gain (m)"], "var": r["variation_sec"], "notes": r["Notes"],
    } for _, r in week_runs.iterrows()]

    return render_template(
        "weekly.html", **ctx, kpis=kpis,
        insights=an.week_insights(cur, prev, week_runs) if cur["runs"] else ["No runs logged this week."],
        chart_days=Markup(chart_days),
        chart_splits=Markup(chart_splits) if chart_splits else None, legend_splits=legend_splits,
        chart_trend_pace=Markup(chart_trend_pace), chart_trend_runs=Markup(chart_trend_runs),
        table=table, level_colors=LEVEL_COLORS,
    )


def _day_view(week_runs: pd.DataFrame, day: str) -> dict:
    run = week_runs[week_runs["day_key"] == day].iloc[0]
    splits = [None if pd.isna(v) else v for v in run[an.SPLIT_COLS]]
    n = sum(v is not None for v in splits)
    labels = [f"Km {i}" for i in range(1, n + 1)]
    vals = splits[:n]
    fastest, slowest = min(vals), max(vals)
    tips = []
    for i, v in enumerate(vals):
        diff = (v - run["pace"]) * 60
        tag = " · fastest" if v == fastest else " · slowest" if v == slowest else ""
        tips.append(f"Km {i + 1}: {an.fmt_pace(v)} /km ({diff:+.0f} s vs avg){tag}")
    chart = charts.line_chart(
        labels, [{"name": "Pace", "values": vals, "color": "var(--series-1)", "tips": tips}],
        label=f"Pace per km on {run['Date']:%A %d %B}", pace_axis=True, fmt=an.fmt_pace,
        ref=(run["pace"], f"avg {an.fmt_pace(run['pace'])}"), y_note="min/km · faster ↑", height=320, width=680,
        value_labels=True)

    # deviation from average, per km (seconds) — a bar per km
    dev = [round((v - run["pace"]) * 60) for v in vals]
    kpis = [
        kpi("Distance", f"{run['Distance (km)']:.1f} km"),
        kpi("Duration", an.fmt_duration(run["Duration (min)"])),
        kpi("Avg pace", f"{an.fmt_pace(run['pace'])} /km"),
        kpi("Pace variation", f"±{run['variation_sec']:.0f} s", None, "lower = more even"),
        kpi("Avg / max HR", f"{run['Avg HR (bpm)']:.0f} / {run['Max HR (bpm)']:.0f}", None, "bpm"),
        kpi("Calories", f"{run['Calories (kcal)']:,.0f}"),
        kpi("Elevation", f"{run['Elevation Gain (m)']:.0f} m"),
        kpi("Effort", f"{run['Effort (1-10)']:.0f}/10"),
    ]
    split_rows = [{"km": i + 1, "pace": v, "dev": d, "fast": v == fastest, "slow": v == slowest}
                  for i, (v, d) in enumerate(zip(vals, dev))]
    return dict(kpis=kpis, run=run, chart_run=Markup(chart), split_rows=split_rows,
                insights=an.run_insights(run, week_runs),
                level_color=LEVEL_COLORS[int(run["level"])])


# --------------------------------------------------------------------------- #
# Monthly dashboard
# --------------------------------------------------------------------------- #
@app.route("/monthly")
def monthly():
    df, weeks, months = get_data()
    keys = [str(m) for m in months["month"]]
    sel = request.args.get("month")
    idx = keys.index(sel) if sel in keys else len(keys) - 1
    cur = months.iloc[idx].to_dict()
    prev = months.iloc[idx - 1].to_dict() if idx > 0 else None
    period = months.iloc[idx]["month"]
    mruns = df[df["month"] == period]
    mweeks = weeks[(weeks["week_start"] + pd.Timedelta(days=3)).dt.to_period("M") == period]

    lbl = "last month"
    p = prev or {}
    kpis = [
        kpi("Runs", f"{cur['runs']}", an.delta(cur["runs"], p.get("runs"), label=lbl),
            f"{cur['runs_per_week']:.1f} per week"),
        kpi("Distance", f"{cur['km']:.1f} km", an.delta(cur["km"], p.get("km"), unit=" km", label=lbl)),
        kpi("Time", an.fmt_duration(cur["minutes"])),
        kpi("Avg pace", f"{an.fmt_pace(cur['pace'])} /km",
            an.delta(cur["pace"], p.get("pace"), lower_is_better=True, fmt=an.fmt_pace, label=lbl)),
        kpi("Avg heart rate", f"{cur['avg_hr']:.0f} bpm", None, f"max {cur['max_hr']:.0f}"),
        kpi("Calories", f"{cur['calories']:,.0f}", an.delta(cur["calories"], p.get("calories"), label=lbl)),
        kpi("Elevation", f"{cur['elevation']:,.0f} m", an.delta(cur["elevation"], p.get("elevation"), unit=" m", label=lbl)),
        kpi("Pace variation", f"±{cur['variation']:.0f} s",
            an.delta(cur["variation"], p.get("variation"), unit=" s", lower_is_better=True, label=lbl),
            "lower = more even"),
    ]

    ml = [m.strftime("%b") for m in months["month"]]
    mlinks = [url_for("monthly", month=k) for k in keys]
    chart_runs = charts.bar_chart(
        ml, list(months["runs"]), label="Runs per month", highlight=idx, value_labels=True, height=170, width=420,
        tips=[f"{m.strftime('%B')}: {r} runs ({w:.1f}/week)" for m, r, w in
              zip(months["month"], months["runs"], months["runs_per_week"])], links=mlinks)
    chart_km = charts.bar_chart(
        ml, list(months["km"]), label="Distance per month", highlight=idx, value_labels=True, height=170, width=420,
        fmt=lambda v: f"{v:.0f}", tips=[f"{m.strftime('%B')}: {k:.1f} km" for m, k in zip(months["month"], months["km"])],
        links=mlinks)
    chart_pace = charts.line_chart(
        ml, [{"name": "Avg pace", "values": list(months["pace"]), "color": "var(--series-1)",
              "tips": [f"{m.strftime('%B')}: {an.fmt_pace(v)} /km" for m, v in zip(months["month"], months["pace"])]}],
        label="Average pace by month", pace_axis=True, fmt=an.fmt_pace, highlight=idx,
        y_note="min/km · faster ↑", height=170, width=420, links=mlinks)
    chart_var = charts.line_chart(
        ml, [{"name": "Variation", "values": list(months["variation"]), "color": "var(--series-2)",
              "tips": [f"{m.strftime('%B')}: ±{v:.1f} s per km" for m, v in zip(months["month"], months["variation"])]}],
        label="Pace variation by month", fmt=lambda v: f"{v:.0f} s", highlight=idx,
        y_note="seconds · lower = more even", height=170, width=420, links=mlinks)
    matrix = [[int(r[f"level_{i}"]) for i in range(5)] for _, r in months.iterrows()]
    chart_mix = charts.stacked_bar_chart(
        ml, an.INTERVAL_LEVELS, matrix, LEVEL_COLORS, label="Interval type mix by month",
        highlight=idx, height=170, width=420)

    # weeks inside the month
    wl = [f"{w:%d %b}" for w in mweeks["week_start"]]
    chart_weeks = charts.bar_chart(
        wl, list(mweeks["km"]), label="Distance per week this month", value_labels=True, height=170, width=420,
        fmt=lambda v: f"{v:.1f}",
        tips=[f"Week of {w:%d %b}: {r} runs · {k:.1f} km · {an.fmt_pace(pc)} /km" for w, r, k, pc in
              zip(mweeks["week_start"], mweeks["runs"], mweeks["km"], mweeks["pace"])],
        links=[url_for("weekly", week=w.strftime("%Y-%m-%d")) for w in mweeks["week_start"]])

    # every run in the month: avg pace, coloured by interval level
    run_labels = [f"{d:%d}" for d in mruns["Date"]]
    chart_month_runs = charts.line_chart(
        run_labels, [{"name": "Run pace", "values": list(mruns["pace"]), "color": "var(--series-1)",
                      "tips": [f"{r['Date']:%a %d %b}: {an.fmt_pace(r['pace'])} /km · {r['Distance (km)']:.1f} km · {r['Interval Type']}"
                               for _, r in mruns.iterrows()]}],
        label="Pace of every run this month", pace_axis=True, fmt=an.fmt_pace,
        ref=(cur["pace"], f"month avg {an.fmt_pace(cur['pace'])}"), y_note="min/km · faster ↑",
        height=170, width=420, label_every=1 if len(mruns) <= 16 else 2,
        links=[url_for("weekly", week=r["week_start"].strftime("%Y-%m-%d"), day=r["day_key"]) for _, r in mruns.iterrows()])

    week_rows = [{"ws": w, "key": w.strftime("%Y-%m-%d"), "runs": r, "km": k, "pace": pc, "hr": hr, "var": v}
                 for w, r, k, pc, hr, v in zip(mweeks["week_start"], mweeks["runs"], mweeks["km"],
                                                mweeks["pace"], mweeks["avg_hr"], mweeks["variation"])]
    return render_template(
        "monthly.html", page="monthly", month_key=keys[idx], period=period,
        month_options=[{"value": k, "label": f"{m.strftime('%B %Y')} · {r} runs"} for k, m, r in
                       zip(keys, months["month"], months["runs"])],
        nav={"prev": keys[idx - 1] if idx > 0 else None, "next": keys[idx + 1] if idx < len(keys) - 1 else None},
        kpis=kpis, insights=an.month_insights(cur, prev, mweeks),
        chart_runs=Markup(chart_runs), chart_km=Markup(chart_km), chart_pace=Markup(chart_pace),
        chart_var=Markup(chart_var), chart_mix=Markup(chart_mix), chart_weeks=Markup(chart_weeks),
        chart_month_runs=Markup(chart_month_runs), week_rows=week_rows,
        levels=list(zip(an.INTERVAL_LEVELS, LEVEL_COLORS)),
    )


if __name__ == "__main__":
    app.run(debug=True)
