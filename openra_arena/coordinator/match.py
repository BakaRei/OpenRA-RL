"""One arena match: slot drivers, executor loop, persona loops, takeover watchdog, end check, ranking."""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Protocol

from openra_arena.config import ArenaConfig, SlotConfig
from openra_arena.coordinator.artifacts import MatchArtifacts
from openra_arena.coordinator.personas import PERSONAS
from openra_arena.coordinator.players import Decision, PersonaPlayer
from openra_arena.coordinator.scoring import PlayerScoreInput, end_condition, rank_players
from openra_arena.executor.commands import MAX_SHOUT
from openra_arena.executor.executor import PlayerExecutor
from openra_arena.executor.locations import build_named_locations
from openra_arena.executor.spatial import SpatialGrid
from openra_arena.executor.territory import TerritoryTracker

WATCHDOG_PERIOD_S = 1.0
PERSONA_POLL_S = 0.2
NOT_READY = "比赛还在准备（引擎加载地图中），你已登记就绪，请过几秒再看局势。"


class MatchEngine(Protocol):
    async def list_players(self): ...  # -> MatchSnapshot (Task 7)

    async def observe(self, player: str, include_spatial: bool = False) -> dict: ...

    async def issue(self, player: str, commands: list[dict]) -> int: ...

    async def start_match(self): ...  # -> ControlResult

    async def end_match(self, reason: str): ...

    async def set_takeover(self, player: str, enabled: bool): ...


@dataclass
class SlotState:
    cfg: SlotConfig
    executor: PlayerExecutor | None = None
    persona: PersonaPlayer | None = None
    driver: str = "persona"  # persona | external | builtin
    joined: bool = False
    last_active: float = 0.0
    taken_over: bool = False
    permanent: bool = False
    feedback: str = ""
    eliminated_tick: int | None = None


class Match:
    def __init__(self, cfg: ArenaConfig, engine: MatchEngine, artifacts: MatchArtifacts,
                 make_persona: Callable[[SlotConfig], PersonaPlayer] | None = None,
                 engine_alive: Callable[[], bool] = lambda: True,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.cfg = cfg
        self.engine = engine
        self.art = artifacts
        self.make_persona = make_persona or (lambda s: PersonaPlayer(s.slot, s.display, PERSONAS[s.persona], cfg.llm))
        self.engine_alive = engine_alive
        self.clock = clock
        self.display = cfg.display
        self.slots: dict[str, SlotState] = {s.slot: SlotState(s, driver=s.kind) for s in cfg.slots}
        self.shouts: list[tuple[int, str, str]] = []
        self.tracker: TerritoryTracker | None = None
        self.tick = 0
        self.started = False
        self.done = asyncio.Event()
        self.end: tuple[str, str | None] | None = None
        self.started_at = ""
        self.map_size = (0, 0)

    async def setup(self) -> None:
        snap = await self.engine.list_players()
        spawns = {p.player: p.spawn for p in snap.players if p.player in self.slots}
        first = next(s for s in self.slots.values() if s.cfg.kind != "builtin")
        obs = await self.engine.observe(first.cfg.slot, include_spatial=True)
        grid = SpatialGrid.from_obs(obs)
        self.map_size = (grid.width, grid.height)
        locations = build_named_locations(grid, spawns, self.display)
        self.tracker = TerritoryTracker(locations)
        now = self.clock()
        for name, st in self.slots.items():
            st.last_active = now
            if st.cfg.kind == "builtin":
                st.permanent = True
                self._log("player_joined", name, driver="builtin")
                continue
            st.executor = PlayerExecutor(name, self.display, self.engine, locations, spawns, on_shout=self._on_shout)
            await st.executor.refresh(include_spatial=True)
            if st.cfg.kind == "persona":
                st.persona = self.make_persona(st.cfg)
                st.joined = True
                self._log("player_joined", name, driver="persona", persona=st.cfg.persona)

    def _external(self, slot: str) -> SlotState:
        st = self.slots.get(slot)
        if st is None or st.cfg.kind != "external":
            raise PermissionError(f"{slot} 不是外部 bot 槽位")
        return st

    def touch(self, slot: str) -> None:
        st = self._external(slot)
        st.last_active = self.clock()
        if not st.joined and st.driver == "external":
            st.joined = True
            self._log("player_joined", slot, driver="external")

    async def situation(self, slot: str) -> str:
        st = self._external(slot)
        if st.driver != "external":
            return self._lost_slot_text(st)
        if st.executor is None:
            return NOT_READY
        if st.executor.obs is None:
            await st.executor.refresh()
        return st.executor.summary(self._owners(), self.shouts)

    async def orders(self, slot: str, commands: list[dict], reason: str) -> str:
        st = self._external(slot)
        if st.driver != "external":
            return self._lost_slot_text(st)
        if st.executor is None:
            return NOT_READY
        res = st.executor.submit(commands)
        st.feedback = res.feedback()
        self._decision(slot, "external", commands, reason, st.feedback)
        return st.feedback

    async def shout(self, slot: str, text: str) -> str:
        st = self._external(slot)
        if st.driver != "external":
            return self._lost_slot_text(st)
        self._on_shout(slot, text)
        return "已喊话"

    def _lost_slot_text(self, st: SlotState) -> str:
        who = "内置 AI" if st.driver == "builtin" else f"角色「{PERSONAS[st.cfg.persona].title}」"
        return f"你没有在开局前就绪，本局 {self.display[st.cfg.slot]} 已由{who}接管。"

    async def wait_for_players(self) -> None:
        deadline = self.clock() + self.cfg.timing.wait_players_s
        pending = [s for s in self.slots.values() if s.cfg.kind == "external"]
        while any(not s.joined for s in pending) and self.clock() < deadline:
            await asyncio.sleep(PERSONA_POLL_S)
        for st in pending:
            if st.joined:
                continue
            if st.cfg.fallback == "persona":
                st.driver = "persona"
                st.persona = self.make_persona(st.cfg)
                st.joined = True
            else:
                st.driver = "builtin"
                st.permanent = True
                await self._set_takeover(st, True)
            self._log("fallback", st.cfg.slot, driver=st.driver)

    async def run(self) -> dict:
        self.started_at = datetime.now().isoformat(timespec="seconds")
        await self.setup()
        await self.wait_for_players()
        await self.engine.start_match()
        self.started = True
        now = self.clock()
        for st in self.slots.values():
            st.last_active = now
        loops = [self._executor_loop(), self._watchdog_loop()]
        loops += [self._persona_loop(st) for st in self.slots.values() if st.driver == "persona"]
        tasks = [asyncio.create_task(c) for c in loops]
        await self.done.wait()
        for t in tasks:
            t.cancel()
        for t in tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await t
        return await self.finish()

    async def finish(self) -> dict:
        reason, winner = self.end or ("aborted", None)
        if reason != "engine_crashed":
            with contextlib.suppress(Exception):
                await self.engine.end_match(reason)
        counts = self.tracker.counts() if self.tracker else {}
        inputs = []
        for name, st in self.slots.items():
            obs = (st.executor.obs if st.executor else None) or {}
            inputs.append(PlayerScoreInput(
                name, counts.get(name, 0), obs.get("military", {}).get("army_value", 0),
                obs.get("economy", {}).get("earned", 0), st.eliminated_tick is None, st.eliminated_tick,
            ))
        ranking = rank_players(inputs, self.cfg.scoring, winner)
        meta = {
            "match_id": self.art.root.name,
            "map": self.cfg.map_file,
            "started_at": self.started_at,
            "ended_at": datetime.now().isoformat(timespec="seconds"),
            "end_reason": reason,
            "winner": winner,
            "duration_ticks": self.tick,
            "display": self.display,
            "slots": [
                {"slot": n, "kind": st.cfg.kind, "persona": st.cfg.persona, "driver": st.driver,
                 "observed": st.executor is not None}
                for n, st in self.slots.items()
            ],
            "ranking": [asdict(r) for r in ranking],
            "scoring": self.cfg.scoring.model_dump(),
            "map_size": list(self.map_size),
            "locations": [asdict(loc) for loc in (self.tracker.locations if self.tracker else [])],
        }
        self.art.write_meta(meta)
        return meta

    async def _executor_loop(self) -> None:
        n = 0
        last_sample = -10**9
        timing = self.cfg.timing
        while not self.done.is_set():
            n += 1
            if not self.engine_alive():
                self._finish_with("engine_crashed", None)
                return
            for st in self.slots.values():
                if st.executor is not None and st.eliminated_tick is None:
                    await st.executor.refresh(include_spatial=n % timing.spatial_every == 0)
                    self.tick = max(self.tick, st.executor.tick)
            for st in self.slots.values():
                if st.executor is not None and st.eliminated_tick is None:
                    await st.executor.step()
            self._update_territory()
            if self.tick - last_sample >= timing.sample_interval_ticks:
                last_sample = self.tick
                self._sample()
            await self._check_end()
            await asyncio.sleep(timing.executor_interval_s)

    async def _check_end(self) -> None:
        snap = await self.engine.list_players()
        self.tick = max(self.tick, snap.tick)
        alive = []
        for p in snap.players:
            st = self.slots.get(p.player)
            if st is None:
                continue
            if p.win_state == "lost" and st.eliminated_tick is None:
                st.eliminated_tick = self.tick
                self._log("player_lost", p.player)
            if st.eliminated_tick is None:
                alive.append(p.player)
        result = end_condition(alive, self.tick, self.cfg.timing.max_game_ticks)
        if result is not None:
            self._finish_with(*result)

    async def _persona_loop(self, st: SlotState) -> None:
        timing = self.cfg.timing
        assert st.executor is not None and st.persona is not None
        last = -10**9
        pending_urgent = False
        while not self.done.is_set():
            now = self.clock()
            pending_urgent = bool(st.executor.pop_urgent()) or pending_urgent
            due = now - last >= timing.summary_interval_s
            urgent = pending_urgent and now - last >= timing.urgent_cooldown_s
            if st.eliminated_tick is None and (due or urgent):
                last, pending_urgent = now, False
                summary = st.executor.summary(self._owners(), self.shouts)
                d: Decision = await st.persona.decide(summary, st.feedback)
                if d.ok:
                    res = st.executor.submit(d.commands)
                    st.feedback = res.feedback()
                    st.last_active = self.clock()
                else:
                    st.feedback = ""
                self._decision(st.cfg.slot, "persona" if d.ok else "persona_error", d.commands, d.reason, st.feedback)
            await asyncio.sleep(PERSONA_POLL_S)

    async def _watchdog_loop(self) -> None:
        limit = self.cfg.timing.takeover_after_s
        while not self.done.is_set():
            now = self.clock()
            for st in self.slots.values():
                if st.permanent or st.executor is None or st.eliminated_tick is not None:
                    continue
                idle = now - st.last_active
                if not st.taken_over and idle >= limit:
                    await self._set_takeover(st, True)
                elif st.taken_over and idle < limit:
                    await self._set_takeover(st, False)
            await asyncio.sleep(min(WATCHDOG_PERIOD_S, limit / 4))

    async def _set_takeover(self, st: SlotState, enabled: bool) -> None:
        await self.engine.set_takeover(st.cfg.slot, enabled)
        st.taken_over = enabled
        if st.executor is not None:
            st.executor.paused = enabled
        self._log("takeover", st.cfg.slot, enabled=enabled, permanent=st.permanent)

    def _finish_with(self, reason: str, winner: str | None) -> None:
        if self.end is None:
            self.end = (reason, winner)
            self._log("match_end", None, reason=reason, winner=winner)
        self.done.set()

    def _owners(self) -> dict[str, str | None]:
        return dict(self.tracker.owners) if self.tracker else {}

    def _on_shout(self, slot: str, text: str) -> None:
        text = text[:MAX_SHOUT]
        self.shouts.append((self.tick, self.display[slot], text))
        self._log("shout", slot, text=text)

    def _update_territory(self) -> None:
        assert self.tracker is not None
        observed = {n: st.executor.obs for n, st in self.slots.items() if st.executor and st.executor.obs}
        seen: dict[str, dict[int, dict]] = {n: {} for n in self.slots if n not in observed}
        for obs in observed.values():
            for e in obs.get("visible_enemies", []):
                if e["owner"] in seen:
                    seen[e["owner"]][e["actor_id"]] = e
            for b in obs.get("visible_enemy_buildings", []):
                if b["owner"] in seen:
                    seen[b["owner"]][b["actor_id"]] = {**b, "is_building": True}
        synthetic = {n: {"units": list(a.values()), "buildings": []} for n, a in seen.items()}
        for ch in self.tracker.update(self.tick, {**observed, **synthetic}):
            self.art.append("territory", {
                "t": ch.tick, "kind": "change", "key": ch.key, "name": ch.name, "old": ch.old, "new": ch.new,
            })

    def _sample(self) -> None:
        assert self.tracker is not None
        counts = self.tracker.counts()
        self.art.append("territory", {"kind": "snapshot", **self.tracker.snapshot(self.tick)})
        for name, st in self.slots.items():
            obs = (st.executor.obs if st.executor else None) or {}
            eco, mil = obs.get("economy", {}), obs.get("military", {})
            self.art.append("samples", {
                "t": self.tick, "player": name, "observed": bool(obs), "cash": eco.get("cash", 0),
                "earned": eco.get("earned", 0), "spent": eco.get("spent", 0),
                "army_value": mil.get("army_value", 0), "units": len(obs.get("units", [])),
                "buildings": len(obs.get("buildings", [])), "kills_cost": mil.get("kills_cost", 0),
                "deaths_cost": mil.get("deaths_cost", 0), "territory": counts.get(name, 0),
                "taken_over": st.taken_over, "alive": st.eliminated_tick is None,
            })

    def _decision(self, slot: str, source: str, commands: list, reason: str, feedback: str) -> None:
        self.art.append("decisions", {
            "t": self.tick, "player": slot, "source": source, "commands": commands,
            "reason": reason, "feedback": feedback,
        })

    def _log(self, event: str, slot: str | None, **fields) -> None:
        self.art.append("coordinator", {"t": self.tick, "event": event, "player": slot, **fields})
