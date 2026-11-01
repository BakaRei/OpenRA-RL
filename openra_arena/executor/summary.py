"""Chinese situation summary for one player, filtered by that player's fog of war."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from openra_arena.executor.locations import NamedLocation, nearest_location
from openra_arena.executor.spatial import CH_VISIBILITY, SpatialGrid
from openra_arena.executor.tasks import Task
from openra_arena.executor.territory import CONTESTED

TICKS_PER_SECOND = 25
MAX_SUMMARY_CHARS = 1200
MAX_AVAILABLE = 15


def game_time(tick: int) -> str:
    seconds = max(0, tick) // TICKS_PER_SECOND
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


@dataclass
class SummaryInput:
    player: str
    display: dict[str, str]
    obs: dict
    grid: SpatialGrid | None
    locations: list[NamedLocation]
    owners: dict[str, str | None]
    tasks: list[Task]
    events: list[str] = field(default_factory=list)
    shouts: list[tuple[int, str, str]] = field(default_factory=list)


def _counts(items: list[dict], limit: int = 8) -> str:
    c = Counter(i["type"] for i in items)
    parts = [t if n == 1 else f"{t}×{n}" for t, n in sorted(c.items(), key=lambda kv: (-kv[1], kv[0]))]
    if len(parts) > limit:
        parts = parts[:limit] + ["…"]
    return "、".join(parts) if parts else "无"


def _owner_label(inp: SummaryInput, loc: NamedLocation) -> str:
    owner = inp.owners.get(loc.key)
    visible = inp.grid is None or inp.grid.at(loc.x, loc.y, CH_VISIBILITY) >= 1.0
    if owner != inp.player and not visible:
        return "迷雾未知"
    if owner is None:
        return "无人"
    if owner == CONTESTED:
        return "争夺中"
    if owner == inp.player:
        return "我方"
    return inp.display.get(owner, owner)


def _task_line(t: Task) -> str:
    c = t.command
    what = c.item or c.target or (f"#{c.task_id}" if c.task_id else "") or (c.text or "")[:10]
    note = f"，{t.note}" if t.note else ""
    return f"#{t.id} {c.kind} {what}：{t.status.value}{note}"


def render_summary(inp: SummaryInput) -> str:
    obs = inp.obs
    eco = obs.get("economy", {})
    tick = obs.get("tick", 0)
    me = inp.display.get(inp.player, inp.player)
    lines = [
        f"【时间】{game_time(tick)}（第 {tick} 帧）你是{me}",
        (f"【经济】资金 {eco.get('cash', 0)}，电力 {eco.get('power_provided', 0)}/{eco.get('power_drained', 0)}，"
         f"矿车 {eco.get('harvester_count', 0)}"),
        (f"【我方兵力】单位 {len(obs.get('units', []))}：{_counts(obs.get('units', []))}；"
         f"建筑 {len(obs.get('buildings', []))}：{_counts(obs.get('buildings', []))}"),
        "【地点】" + "；".join(f"{loc.name}：{_owner_label(inp, loc)}" for loc in inp.locations),
    ]
    enemies = obs.get("visible_enemies", []) + obs.get("visible_enemy_buildings", [])
    if enemies and inp.locations:
        groups: dict[tuple[str, str], list[dict]] = {}
        for e in enemies:
            where = nearest_location(inp.locations, e["cell_x"], e["cell_y"]).name
            groups.setdefault((inp.display.get(e["owner"], e["owner"]), where), []).append(e)
        parts = [f"{who}在{where}附近：{_counts(es, 4)}" for (who, where), es in sorted(groups.items())[:6]]
        lines.append("【视野内敌人】" + "；".join(parts))
    else:
        lines.append("【视野内敌人】无")
    if inp.events:
        lines.append("【最近事件】" + "；".join(inp.events[-5:]))
    tasks = [_task_line(t) for t in inp.tasks[:8]]
    lines.append("【任务】" + ("；".join(tasks) if tasks else "无"))
    if inp.shouts:
        lines.append("【喊话】" + "；".join(f"{game_time(t)} {who}：“{text}”" for t, who, text in inp.shouts[-3:]))
    avail = obs.get("available_production", [])
    shown = avail[:MAX_AVAILABLE] + (["…"] if len(avail) > MAX_AVAILABLE else [])
    lines.append("【可生产】" + ("、".join(shown) if shown else "无"))
    text = "\n".join(lines)
    if len(text) > MAX_SUMMARY_CHARS:
        text = text[: MAX_SUMMARY_CHARS - 1] + "…"
    return text
