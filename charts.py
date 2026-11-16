"""Small SVG chart builders, rendered on the server in pure Python.

Every chart is an inline <svg> string that uses CSS custom properties for its
colours (so light/dark mode come from style.css), and carries `data-tip`
attributes that static/tooltip.js turns into hover tooltips.
"""
from __future__ import annotations

import math
from html import escape
from typing import Callable, Sequence

W, H = 640, 260
PAD_L, PAD_R, PAD_T, PAD_B = 52, 16, 18, 34


def _nice_ticks(lo: float, hi: float, count: int = 5) -> list[float]:
    if hi == lo:
        hi = lo + 1
    raw = (hi - lo) / count
    mag = 10 ** math.floor(math.log10(raw))
    step = min((m * mag for m in (1, 2, 2.5, 5, 10) if m * mag >= raw), default=mag * 10)
    start = math.floor(lo / step) * step
    end = math.ceil(hi / step - 1e-9) * step
    n = int(round((end - start) / step))
    return [round(start + i * step, 10) for i in range(n + 1)]


def _pace_ticks(lo: float, hi: float) -> list[float]:
    """Ticks on whole 15/30/60-second steps for pace (minutes)."""
    span = (hi - lo) * 60
    step = 15 if span <= 90 else 30 if span <= 200 else 60
    start = math.floor(lo * 60 / step) * step
    end = math.ceil(hi * 60 / step) * step
    return [s / 60 for s in range(int(start), int(end) + 1, step)]


def _svg_open(height: int, label: str, W: int = 640) -> str:
    return (
        f'<svg class="chart" viewBox="0 0 {W} {height}" role="img" '
        f'aria-label="{escape(label)}" preserveAspectRatio="xMidYMid meet">'
    )


def _x_labels(labels: Sequence[str], xs: Sequence[float], height: int, every: int = 1) -> str:
    out = []
    for i, (lab, x) in enumerate(zip(labels, xs)):
        if i % every:
            continue
        out.append(
            f'<text class="axis-label" x="{x:.1f}" y="{height - PAD_B + 18}" '
            f'text-anchor="middle">{escape(lab)}</text>'
        )
    return "".join(out)


def _y_grid(ticks, y_of, fmt, height, W: int = 640) -> str:
    out = []
    for t in ticks:
        y = y_of(t)
        if y < PAD_T - 1 or y > height - PAD_B + 1:
            continue
        out.append(f'<line class="grid" x1="{PAD_L}" x2="{W - PAD_R}" y1="{y:.1f}" y2="{y:.1f}"/>')
        out.append(
            f'<text class="axis-label" x="{PAD_L - 8}" y="{y + 4:.1f}" text-anchor="end">{escape(fmt(t))}</text>'
        )
    return "".join(out)


def _bar_path(x: float, y: float, w: float, h: float, r: float = 4) -> str:
    """Bar with rounded top corners, square at the baseline."""
    r = min(r, w / 2, h)
    return (
        f"M{x:.1f},{y + h:.1f} V{y + r:.1f} Q{x:.1f},{y:.1f} {x + r:.1f},{y:.1f} "
        f"H{x + w - r:.1f} Q{x + w:.1f},{y:.1f} {x + w:.1f},{y + r:.1f} V{y + h:.1f} Z"
    )


# --------------------------------------------------------------------------- #
def bar_chart(
    labels: Sequence[str],
    values: Sequence[float],
    *,
    label: str,
    fmt: Callable[[float], str] = lambda v: f"{v:g}",
    tips: Sequence[str] | None = None,
    highlight: int | None = None,
    links: Sequence[str | None] | None = None,
    height: int = H,
    width: int = W,
    label_every: int = 1,
    value_labels: bool = False,
) -> str:
    W = width
    n = len(values)
    plot_w = W - PAD_L - PAD_R
    plot_h = height - PAD_T - PAD_B
    vmax = max([v for v in values if v] + [1])
    ticks = _nice_ticks(0, vmax)
    top = ticks[-1]
    y_of = lambda v: PAD_T + plot_h * (1 - v / top)
    slot = plot_w / n
    bw = max(4.0, min(42.0, slot - 2 - slot * 0.25))
    xs = [PAD_L + slot * (i + 0.5) for i in range(n)]

    parts = [_svg_open(height, label, W), _y_grid(ticks, y_of, fmt, height, W)]
    for i, v in enumerate(values):
        v = v or 0
        x = xs[i] - bw / 2
        y = y_of(v)
        h = PAD_T + plot_h - y
        cls = "bar"
        if highlight is not None:
            cls += " bar-hi" if i == highlight else " bar-dim"
        tip = escape(tips[i] if tips else f"{labels[i]}: {fmt(v)}")
        mark = f'<path class="{cls}" d="{_bar_path(x, y, bw, h)}"/>' if h > 0.5 else ""
        # Hit target is the whole column, larger than the mark.
        hit = (
            f'<rect class="hit" x="{xs[i] - slot / 2:.1f}" y="{PAD_T}" width="{slot:.1f}" '
            f'height="{plot_h}" data-tip="{tip}"/>'
        )
        if links and links[i]:
            parts.append(f'<a href="{escape(links[i])}">{mark}{hit}</a>')
        else:
            parts.append(mark + hit)
        if value_labels and v:
            parts.append(
                f'<text class="value-label" x="{xs[i]:.1f}" y="{y - 6:.1f}" text-anchor="middle">{escape(fmt(v))}</text>'
            )
    parts.append(f'<line class="baseline" x1="{PAD_L}" x2="{W - PAD_R}" y1="{PAD_T + plot_h}" y2="{PAD_T + plot_h}"/>')
    parts.append(_x_labels(labels, xs, height, label_every))
    parts.append("</svg>")
    return "".join(parts)


# --------------------------------------------------------------------------- #
def line_chart(
    labels: Sequence[str],
    series: Sequence[dict],
    *,
    label: str,
    pace_axis: bool = False,
    fmt: Callable[[float], str] = lambda v: f"{v:g}",
    ref: tuple[float, str] | None = None,
    highlight: int | None = None,
    height: int = H,
    width: int = W,
    label_every: int = 1,
    y_note: str | None = None,
    links: Sequence[str | None] | None = None,
    value_labels: bool = False,
) -> str:
    """series: [{"name", "values": [float|None], "color": css var, "tips": [...]}].

    pace_axis=True inverts the y-axis so faster (smaller) paces sit higher.
    """
    W = width
    n = len(labels)
    plot_w = W - PAD_L - PAD_R
    plot_h = height - PAD_T - PAD_B
    vals = [v for s in series for v in s["values"] if v is not None]
    if ref:
        vals.append(ref[0])
    lo, hi = min(vals), max(vals)
    if pace_axis:
        ticks = _pace_ticks(lo, hi)
    else:
        pad = (hi - lo) * 0.1 or 1
        ticks = _nice_ticks(lo - pad, hi + pad)
    t_lo, t_hi = ticks[0], ticks[-1]

    def y_of(v):
        frac = (v - t_lo) / (t_hi - t_lo)
        return PAD_T + plot_h * frac if pace_axis else PAD_T + plot_h * (1 - frac)

    slot = plot_w / max(n, 1)
    xs = [PAD_L + slot * (i + 0.5) for i in range(n)]
    parts = [_svg_open(height, label, W), _y_grid(ticks, y_of, fmt, height, W)]

    if highlight is not None:
        parts.append(
            f'<rect class="hi-band" x="{xs[highlight] - slot / 2:.1f}" y="{PAD_T}" '
            f'width="{slot:.1f}" height="{plot_h}"/>'
        )
    if ref:
        y = y_of(ref[0])
        parts.append(f'<line class="ref-line" x1="{PAD_L}" x2="{W - PAD_R}" y1="{y:.1f}" y2="{y:.1f}"/>')
        parts.append(
            f'<text class="ref-label" x="{W - PAD_R - 4}" y="{y - 6:.1f}" text-anchor="end">{escape(ref[1])}</text>'
        )

    for s in series:
        color = s["color"]
        pts = [(xs[i], y_of(v)) for i, v in enumerate(s["values"]) if v is not None]
        # break the line at gaps
        segs, cur = [], []
        for i, v in enumerate(s["values"]):
            if v is None:
                if cur:
                    segs.append(cur)
                cur = []
            else:
                cur.append((xs[i], y_of(v)))
        if cur:
            segs.append(cur)
        for seg in segs:
            d = " ".join(f"{'M' if j == 0 else 'L'}{x:.1f},{y:.1f}" for j, (x, y) in enumerate(seg))
            parts.append(f'<path class="line" d="{d}" style="stroke:{color}"/>')
        for i, v in enumerate(s["values"]):
            if v is None:
                continue
            x, y = xs[i], y_of(v)
            big = highlight == i
            parts.append(
                f'<circle class="dot{" dot-hi" if big else ""}" cx="{x:.1f}" cy="{y:.1f}" '
                f'r="{6 if big else 4}" style="fill:{color}"/>'
            )
            if value_labels:
                parts.append(
                    f'<text class="value-label" x="{x:.1f}" y="{y - 10:.1f}" text-anchor="middle">{escape(fmt(v))}</text>'
                )
            tip = escape(s.get("tips", [None] * n)[i] or f"{labels[i]}: {fmt(v)}")
            hit = f'<circle class="hit" cx="{x:.1f}" cy="{y:.1f}" r="13" data-tip="{tip}"/>'
            if links and links[i]:
                parts.append(f'<a href="{escape(links[i])}">{hit}</a>')
            else:
                parts.append(hit)
        if s.get("end_label") and pts:
            x, y = pts[-1]
            parts.append(f'<text class="series-label" x="{x + 8:.1f}" y="{y + 4:.1f}">{escape(s["name"])}</text>')

    parts.append(_x_labels(labels, xs, height, label_every))
    if y_note:
        parts.append(f'<text class="axis-note" x="{PAD_L}" y="11">{escape(y_note)}</text>')
    parts.append("</svg>")
    return "".join(parts)


# --------------------------------------------------------------------------- #
def stacked_bar_chart(
    labels: Sequence[str],
    categories: Sequence[str],
    matrix: Sequence[Sequence[int]],
    colors: Sequence[str],
    *,
    label: str,
    highlight: int | None = None,
    height: int = H,
    width: int = W,
) -> str:
    """matrix[i][c] = count of category c in column i."""
    W = width
    n = len(labels)
    plot_w = W - PAD_L - PAD_R
    plot_h = height - PAD_T - PAD_B
    totals = [sum(col) for col in matrix]
    ticks = _nice_ticks(0, max(totals + [1]))
    top = ticks[-1]
    y_of = lambda v: PAD_T + plot_h * (1 - v / top)
    slot = plot_w / n
    bw = max(8.0, min(56.0, slot * 0.6))
    xs = [PAD_L + slot * (i + 0.5) for i in range(n)]
    parts = [_svg_open(height, label, W), _y_grid(ticks, y_of, lambda v: f"{v:g}", height, W)]
    gap = 2  # surface gap between stacked segments
    for i, col in enumerate(matrix):
        acc = 0
        dim = highlight is not None and i != highlight
        nonzero = [c for c, v in enumerate(col) if v]
        for c, v in enumerate(col):
            if not v:
                continue
            y_top, y_bot = y_of(acc + v), y_of(acc)
            h = y_bot - y_top - (gap if c != nonzero[0] else 0)
            x = xs[i] - bw / 2
            is_top = c == nonzero[-1]
            d = _bar_path(x, y_top, bw, h) if is_top else f"M{x:.1f},{y_top:.1f} h{bw:.1f} v{h:.1f} h{-bw:.1f} Z"
            tip = escape(f"{labels[i]} · {categories[c]}: {v} run{'s' if v != 1 else ''}")
            parts.append(
                f'<path class="seg{" bar-dim" if dim else ""}" d="{d}" style="fill:{colors[c]}" data-tip="{tip}"/>'
            )
            acc += v
        parts.append(
            f'<text class="value-label" x="{xs[i]:.1f}" y="{y_of(totals[i]) - 6:.1f}" text-anchor="middle">{totals[i]}</text>'
        )
    parts.append(f'<line class="baseline" x1="{PAD_L}" x2="{W - PAD_R}" y1="{PAD_T + plot_h}" y2="{PAD_T + plot_h}"/>')
    parts.append(_x_labels(labels, xs, height))
    parts.append("</svg>")
    return "".join(parts)
