"""Data loading and aggregation for the running dashboards.

Reads the running log CSV (the same columns as the "Running Log" sheet) and
builds the weekly / monthly summaries and plain-language insights.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

DATA_FILE = Path(__file__).parent / "data" / "running_log.csv"

INTERVAL_LEVELS = [
    "2 min walk – 1 min run",
    "1 min walk – 2 min run",
    "1 min walk – 3 min run",
    "1 min walk – 5 min run",
    "Only run",
]
SPLIT_COLS = [f"Km {i} Pace" for i in range(1, 11)]


# --------------------------------------------------------------------------- #
# Parsing helpers
# --------------------------------------------------------------------------- #
def parse_pace(value) -> float | None:
    """'9:10' -> 9.1667 minutes. Also accepts '0:09:10' and plain numbers."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    text = str(value).strip()
    if not text:
        return None
    parts = text.split(":")
    try:
        if len(parts) == 3:  # h:mm:ss
            h, m, s = (float(p) for p in parts)
            return h * 60 + m + s / 60
        if len(parts) == 2:  # m:ss
            m, s = (float(p) for p in parts)
            return m + s / 60
        return float(text)
    except ValueError:
        return None


def fmt_pace(minutes: float | None) -> str:
    """9.1667 -> '9:10'."""
    if minutes is None or pd.isna(minutes):
        return "–"
    total = round(minutes * 60)
    return f"{total // 60}:{total % 60:02d}"


def fmt_duration(minutes: float) -> str:
    """135 -> '2h 15m'."""
    minutes = int(round(minutes))
    h, m = divmod(minutes, 60)
    return f"{h}h {m:02d}m" if h else f"{m}m"


# --------------------------------------------------------------------------- #
# Loading
# --------------------------------------------------------------------------- #
def load_runs(path: Path = DATA_FILE) -> pd.DataFrame:
    df = pd.read_csv(path, dtype=str, keep_default_na=False)
    df["Date"] = pd.to_datetime(df["Date"])
    num_cols = [
        "Duration (min)", "Distance (km)", "Avg HR (bpm)", "Max HR (bpm)",
        "Effort (1-10)", "Elevation Gain (m)", "Calories (kcal)",
    ]
    for col in num_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    for col in SPLIT_COLS:
        df[col] = df[col].map(parse_pace)

    # Average pace: always recomputed from duration / distance so it stays right.
    df["pace"] = df["Duration (min)"] / df["Distance (km)"]

    splits = df[SPLIT_COLS].astype(float)
    df["variation_sec"] = (splits.std(axis=1, ddof=1) * 60).round()
    df["level"] = df["Interval Type"].map(
        {name: i for i, name in enumerate(INTERVAL_LEVELS)}
    )
    df["week_start"] = (df["Date"] - pd.to_timedelta(df["Date"].dt.weekday, unit="D")).dt.normalize()
    df["month"] = df["Date"].dt.to_period("M")
    df["day_key"] = df["Date"].dt.strftime("%Y-%m-%d")
    return df.sort_values("Date").reset_index(drop=True)


# --------------------------------------------------------------------------- #
# Aggregation
# --------------------------------------------------------------------------- #
def _summarise(group: pd.DataFrame) -> dict:
    km = group["Distance (km)"].sum()
    minutes = group["Duration (min)"].sum()
    return {
        "runs": len(group),
        "km": km,
        "minutes": minutes,
        "pace": minutes / km if km else None,
        "avg_hr": group["Avg HR (bpm)"].mean(),
        "max_hr": group["Max HR (bpm)"].max(),
        "calories": group["Calories (kcal)"].sum(),
        "elevation": group["Elevation Gain (m)"].sum(),
        "variation": group["variation_sec"].mean(),
        "top_level": int(group["level"].max()),
        "longest": group["Distance (km)"].max(),
    }


def weekly_table(df: pd.DataFrame) -> pd.DataFrame:
    """One row per calendar week (Mon–Sun), including weeks with no runs."""
    rows = {ws: _summarise(g) for ws, g in df.groupby("week_start")}
    all_weeks = pd.date_range(df["week_start"].min(), df["week_start"].max(), freq="7D")
    empty = {"runs": 0, "km": 0.0, "minutes": 0.0, "pace": None, "avg_hr": None,
             "max_hr": None, "calories": 0, "elevation": 0, "variation": None,
             "top_level": None, "longest": 0.0}
    out = pd.DataFrame([{"week_start": w, **rows.get(w, empty)} for w in all_weeks])
    return out


def monthly_table(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for month, g in df.groupby("month"):
        s = _summarise(g)
        days_in_month = month.days_in_month
        s["runs_per_week"] = s["runs"] / (days_in_month / 7)
        for i, name in enumerate(INTERVAL_LEVELS):
            s[f"level_{i}"] = int((g["level"] == i).sum())
        rows.append({"month": month, **s})
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- #
# Deltas & insights
# --------------------------------------------------------------------------- #
@dataclass
class Delta:
    text: str      # e.g. "+3.2 km vs last week"
    tone: str      # "good" | "bad" | "flat"


def delta(cur, prev, *, unit="", lower_is_better=False, fmt=None, label="") -> Delta | None:
    if cur is None or prev is None or pd.isna(cur) or pd.isna(prev):
        return None
    diff = cur - prev
    if abs(diff) < 1e-9:
        return Delta(f"same as {label}", "flat")
    better = diff < 0 if lower_is_better else diff > 0
    if fmt:
        shown = fmt(abs(diff))
    else:
        shown = f"{abs(diff):,.1f}".rstrip("0").rstrip(".")
    sign = "+" if diff > 0 else "−"
    if lower_is_better and fmt is fmt_pace:
        word = "faster" if diff < 0 else "slower"
        return Delta(f"{shown} /km {word} than {label}", "good" if better else "bad")
    return Delta(f"{sign}{shown}{unit} vs {label}", "good" if better else "bad")


def week_insights(cur: dict, prev: dict | None, runs: pd.DataFrame) -> list[str]:
    tips = []
    if prev and prev["runs"]:
        if cur["runs"] < prev["runs"]:
            tips.append(f"Fewer runs than last week ({cur['runs']} vs {prev['runs']}).")
        elif cur["runs"] > prev["runs"]:
            tips.append(f"More runs than last week ({cur['runs']} vs {prev['runs']}).")
        if cur["pace"] and prev["pace"]:
            d = cur["pace"] - prev["pace"]
            if abs(d) >= 5 / 60:
                word = "faster" if d < 0 else "slower"
                tips.append(f"Average pace was {fmt_pace(abs(d))} /km {word} than last week.")
            else:
                tips.append("Average pace held steady compared with last week.")
        if cur["top_level"] is not None and prev["top_level"] is not None:
            if cur["top_level"] > prev["top_level"]:
                tips.append(f"Moved up to “{INTERVAL_LEVELS[cur['top_level']]}”.")
            elif cur["top_level"] < prev["top_level"]:
                tips.append(f"Dropped back to “{INTERVAL_LEVELS[cur['top_level']]}”.")
    if cur["runs"] and cur["runs"] < 3:
        tips.append("Below the 3–4 runs-a-week target; expect pace to slip.")
    if len(runs):
        best = runs.loc[runs["pace"].idxmin()]
        tips.append(
            f"Fastest run: {best['Date']:%a %d %b} at {fmt_pace(best['pace'])} /km "
            f"over {best['Distance (km)']:.1f} km."
        )
        steady = runs.loc[runs["variation_sec"].idxmin()]
        tips.append(
            f"Most even pacing: {steady['Date']:%a %d %b} "
            f"(±{steady['variation_sec']:.0f} s per km)."
        )
    return tips


def run_insights(run: pd.Series, week_runs: pd.DataFrame) -> list[str]:
    splits = [s for s in run[SPLIT_COLS].tolist() if s is not None and not pd.isna(s)]
    tips = []
    if splits:
        fastest = min(range(len(splits)), key=lambda i: splits[i])
        slowest = max(range(len(splits)), key=lambda i: splits[i])
        tips.append(f"Fastest km: Km {fastest + 1} at {fmt_pace(splits[fastest])} /km.")
        tips.append(f"Slowest km: Km {slowest + 1} at {fmt_pace(splits[slowest])} /km.")
        half = len(splits) // 2
        first, second = sum(splits[:half]) / half, sum(splits[-half:]) / half
        gap = second - first
        if gap < -3 / 60:
            tips.append(f"Negative split: second half was {fmt_pace(-gap)} /km faster than the first.")
        elif gap > 3 / 60:
            tips.append(f"Positive split: second half was {fmt_pace(gap)} /km slower than the first (fatigue).")
        else:
            tips.append("Even split: both halves ran at almost the same pace.")
        spread = max(splits) - min(splits)
        tips.append(f"Spread between fastest and slowest km: {fmt_pace(spread)}.")
    if len(week_runs) > 1:
        wk = week_runs["Duration (min)"].sum() / week_runs["Distance (km)"].sum()
        d = run["pace"] - wk
        word = "faster" if d < 0 else "slower"
        tips.append(f"{fmt_pace(abs(d))} /km {word} than this week's average.")
    if run.get("Notes"):
        tips.append(f"Note: {run['Notes']}")
    return tips


def month_insights(cur: dict, prev: dict | None, weeks: pd.DataFrame) -> list[str]:
    tips = []
    if prev:
        if cur["runs"] < prev["runs"] - 2:
            tips.append(
                f"Runs dropped from {prev['runs']} to {cur['runs']}, about "
                f"{cur['runs_per_week']:.1f} a week."
            )
        elif cur["runs"] > prev["runs"] + 2:
            tips.append(f"Runs rose from {prev['runs']} to {cur['runs']}.")
        d = cur["pace"] - prev["pace"]
        word = "faster" if d < 0 else "slower"
        tips.append(f"Average pace {fmt_pace(cur['pace'])} /km, {fmt_pace(abs(d))} {word} than last month.")
        if cur["variation"] and prev["variation"]:
            if cur["variation"] < prev["variation"] - 1:
                tips.append("Pacing was more even than last month.")
            elif cur["variation"] > prev["variation"] + 1:
                tips.append("Pacing was less even than last month.")
        if cur["top_level"] > prev["top_level"]:
            tips.append(f"Reached “{INTERVAL_LEVELS[cur['top_level']]}” for the first time this block.")
        elif cur["top_level"] < prev["top_level"]:
            tips.append(f"Highest interval level fell to “{INTERVAL_LEVELS[cur['top_level']]}”.")
    if cur["runs_per_week"] < 3:
        tips.append("Under 3 runs a week on average: the main reason progress slipped.")
    if len(weeks):
        bw = weeks.loc[weeks["km"].idxmax()]
        tips.append(f"Biggest week: {bw['week_start']:%d %b} with {bw['km']:.1f} km over {bw['runs']} runs.")
    tips.append(f"Longest run: {cur['longest']:.1f} km.")
    return tips
