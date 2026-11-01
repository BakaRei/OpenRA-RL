"""Per-player command executor: high-level orders in, low-level engine commands out."""

from __future__ import annotations

from collections import Counter, deque
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from openra_arena.executor.commands import parse_commands
from openra_arena.executor.locations import NamedLocation
from openra_arena.executor.planner import PlanContext, base_point, dist2, step_task
from openra_arena.executor.spatial import SpatialGrid
from openra_arena.executor.summary import SummaryInput, game_time, render_summary
from openra_arena.executor.tasks import TaskBook

BASE_ALERT_RADIUS = 15
ALERT_COOLDOWN_TICKS = 750
URGENT_UNIT_LOSS = 3


class EngineLike(Protocol):
    async def observe(self, player: str, include_spatial: bool = False) -> dict: ...

    async def issue(self, player: str, commands: list[dict]) -> int: ...


@dataclass(frozen=True)
class SubmitResult:
    accepted: list[int]
    errors: list[str]

    def feedback(self) -> str:
        parts = []
        if self.accepted:
            parts.append("已接受任务 " + "、".join(f"#{i}" for i in self.accepted))
        if self.errors:
            parts.append("被拒绝：" + "；".join(self.errors))
        return "。".join(parts) if parts else "没有收到指令"


class PlayerExecutor:
    def __init__(self, player: str, display: dict[str, str], client: EngineLike, locations: list[NamedLocation],
                 spawns: dict[str, tuple[int, int]], on_shout: Callable[[str, str], None] | None = None) -> None:
        self.player = player
        self.display = display
        self.client = client
        self.locations = locations
        self.spawns = spawns
        self.on_shout = on_shout
        self.book = TaskBook()
        self.obs: dict | None = None
        self.grid: SpatialGrid | None = None
        self.events: deque[str] = deque(maxlen=10)
        self.last_seen_enemy: dict[str, tuple[int, int]] = {}
        self.paused = False
        self._urgent: list[str] = []
        self._last_alert = -10**9

    @property
    def tick(self) -> int:
        return 0 if self.obs is None else self.obs.get("tick", 0)

    def note(self, text: str, urgent: bool = False) -> None:
        line = f"{game_time(self.tick)} {text}"
        self.events.append(line)
        if urgent:
            self._urgent.append(line)

    def pop_urgent(self) -> list[str]:
        out, self._urgent = self._urgent, []
        return out

    async def refresh(self, include_spatial: bool = True) -> dict:
        obs = await self.client.observe(self.player, include_spatial=include_spatial)
        grid = SpatialGrid.from_obs(obs) if obs.get("spatial_map") else None
        prev = self.obs
        self.obs, self.grid = obs, grid or self.grid
        if prev is not None:
            self._diff(prev, obs)
        for b in obs.get("visible_enemy_buildings", []):
            self.last_seen_enemy[b["owner"]] = (b["cell_x"], b["cell_y"])
        return obs

    def submit(self, raw: list) -> SubmitResult:
        commands, errors = parse_commands(raw)
        accepted = []
        for c in commands:
            if c.kind == "喊话" and self.on_shout is not None:
                self.on_shout(self.player, c.text or "")
            accepted.append(self.book.add(c, self.tick).id)
        return SubmitResult(accepted, errors)

    def context(self) -> PlanContext:
        assert self.obs is not None
        return PlanContext(self.player, self.tick, self.obs, self.grid, self.locations, self.spawns, self.display,
                           self.book, self.last_seen_enemy)

    async def step(self) -> int:
        if self.obs is None or self.paused:
            return 0
        alive = {u["actor_id"] for u in self.obs.get("units", [])} | {b["actor_id"] for b in self.obs.get("buildings", [])}
        self.book.prune_dead(alive)
        ctx = self.context()
        out: list[dict] = []
        for task in self.book.active():
            out.extend(step_task(task, ctx))
        if out:
            await self.client.issue(self.player, out)
        return len(out)

    def summary(self, owners: dict[str, str | None], shouts: list[tuple[int, str, str]] | None = None) -> str:
        assert self.obs is not None
        return render_summary(SummaryInput(self.player, self.display, self.obs, self.grid, self.locations, owners,
                                           self.book.recent(), list(self.events), list(shouts or [])))

    def _diff(self, prev: dict, cur: dict) -> None:
        cur_b = {b["actor_id"] for b in cur.get("buildings", [])}
        for b in prev.get("buildings", []):
            if b["actor_id"] not in cur_b:
                self.note(f"我方 {b['type']} 被摧毁", urgent=True)
        new_yard = any(b["type"] == "fact" for b in cur.get("buildings", [])
                       if b["actor_id"] not in {p["actor_id"] for p in prev.get("buildings", [])})
        cur_u = {u["actor_id"] for u in cur.get("units", [])}
        lost = [u for u in prev.get("units", []) if u["actor_id"] not in cur_u and not (u["type"] == "mcv" and new_yard)]
        if lost:
            kinds = "、".join(f"{t}×{n}" if n > 1 else t for t, n in sorted(Counter(u["type"] for u in lost).items()))
            self.note(f"损失 {len(lost)} 个单位：{kinds}", urgent=len(lost) >= URGENT_UNIT_LOSS)
        bx, by = base_point(self.context())
        near = [e for e in cur.get("visible_enemies", []) if dist2(e["cell_x"], e["cell_y"], bx, by) <= BASE_ALERT_RADIUS ** 2]
        if near and self.tick - self._last_alert >= ALERT_COOLDOWN_TICKS:
            self._last_alert = self.tick
            self.note(f"基地附近发现 {len(near)} 个敌方单位", urgent=True)
