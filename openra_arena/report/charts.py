"""Dependency-free inline SVG: per-player line charts and territory map frames."""

from __future__ import annotations

from html import escape

from openra_arena.report.loader import SLOT_COLORS, MatchData, clock

CONTESTED_COLOR = "#999999"
EMPTY_COLOR = "#e8e8e8"


def series(data: MatchData, metric: str) -> dict[str, list[tuple[int, float]]]:
    out: dict[str, list[tuple[int, float]]] = {p: [] for p in data.players}
    for s in data.samples:
        if s.get("player") in out and s.get("observed", True):
            out[s["player"]].append((s["t"], float(s.get(metric, 0))))
    return out


def line_chart_svg(title: str, lines: dict[str, list[tuple[int, float]]], names: dict[str, str],
                   width: int = 640, height: int = 240) -> str:
    pad_l, pad_r, pad_t, pad_b = 56, 16, 52, 32
    points = [pt for pts in lines.values() for pt in pts]
    if not points:
        return (f'<svg class="chart" width="{width}" height="60">'
                f'<text x="8" y="30">{escape(title)}：无数据</text></svg>')
    t_max = max(t for t, _ in points) or 1
    v_max = max(v for _, v in points) or 1.0
    w, h = width - pad_l - pad_r, height - pad_t - pad_b

    def xy(t: int, v: float) -> str:
        return f"{pad_l + t / t_max * w:.1f},{pad_t + h - v / v_max * h:.1f}"

    parts = [f'<svg class="chart" viewBox="0 0 {width} {height}" width="{width}" height="{height}">',
             f'<text x="{pad_l}" y="18" font-weight="bold">{escape(title)}</text>',
             f'<line x1="{pad_l}" y1="{pad_t + h}" x2="{pad_l + w}" y2="{pad_t + h}" stroke="#888"/>',
             f'<text x="4" y="{pad_t + 10}" font-size="11">{v_max:.0f}</text>',
             f'<text x="{pad_l + w - 40}" y="{height - 6}" font-size="11">{clock(t_max)}</text>']
    for i, (player, pts) in enumerate(lines.items()):
        if not pts:
            continue
        color = SLOT_COLORS.get(player, "#333")
        path = " ".join(xy(t, v) for t, v in sorted(pts))
        parts.append(f'<polyline fill="none" stroke="{color}" stroke-width="2" points="{path}"/>')
        parts.append(
            f'<text x="{pad_l + i * 72}" y="36" fill="{color}" font-size="12">'
            f'{escape(names.get(player, player))}</text>')
    parts.append("</svg>")
    return "".join(parts)


def territory_frames(data: MatchData, every_ticks: int = 750) -> list[dict]:
    frames: list[dict] = []
    next_t = 0
    for rec in data.territory:
        if rec.get("kind") != "snapshot":
            continue
        if rec["t"] >= next_t:
            frames.append({"t": rec["t"], "owners": rec["owners"]})
            next_t = rec["t"] + every_ticks
    return frames


def owner_color(owner: str | None) -> str:
    if owner is None:
        return EMPTY_COLOR
    if owner == "contested":
        return CONTESTED_COLOR
    return SLOT_COLORS.get(owner, "#333")


def _owner_label(data: MatchData, owner: str | None) -> str:
    if owner is None:
        return "无人"
    if owner == "contested":
        return "争夺中"
    return data.name(owner)


def territory_svg(data: MatchData, frame: dict, size: int = 180) -> str:
    mw, mh = (data.meta.get("map_size") or [1, 1])
    scale = size / max(mw, mh, 1)
    parts = [f'<svg class="frame" viewBox="0 0 {size} {size}" width="{size}" height="{size}">',
             f'<rect width="{size}" height="{size}" fill="#fafafa" stroke="#ccc"/>']
    for loc in data.meta.get("locations", []):
        owner = frame["owners"].get(loc["key"])
        label = f"{loc['name']}：{_owner_label(data, owner)}"
        radius = max(3.0, loc["radius"] * scale)
        parts.append(
            f'<circle cx="{loc["x"] * scale:.1f}" cy="{loc["y"] * scale:.1f}" '
            f'r="{radius:.1f}" fill="{owner_color(owner)}" fill-opacity="0.8">'
            f"<title>{escape(label)}</title></circle>")
    parts.append(f'<text x="4" y="{size - 4}" font-size="11">{clock(frame["t"])}</text></svg>')
    return "".join(parts)
