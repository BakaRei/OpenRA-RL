from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import pytest

from openra_arena.executor.executor import PlayerExecutor
from openra_arena.executor.locations import build_named_locations
from openra_arena.executor.spatial import SpatialGrid

pytestmark = pytest.mark.engine

DISPLAY = {"Multi0": "红方", "Multi1": "蓝方", "Multi2": "绿方", "Multi3": "黄方"}
DATA = Path(__file__).parents[1] / "data"


async def _run_until(ex: PlayerExecutor, pred, timeout_s: float, interval_s: float = 2.0) -> dict:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_s
    while loop.time() < deadline:
        obs = await ex.refresh()
        if pred(obs):
            return obs
        await ex.step()
        await asyncio.sleep(interval_s)
    tasks = [(t.id, t.command.kind, t.status.value, t.note) for t in ex.book.recent()]
    raise AssertionError(f"condition not met in {timeout_s}s; tasks={tasks}")


async def test_executor_expands_and_builds_power(arena_engine):
    _proc, client, _spec = arena_engine
    snap = await client.list_players()
    spawns = {p.player: p.spawn for p in snap.players}
    first = await client.observe("Multi0", include_spatial=True)
    grid = SpatialGrid.from_obs(first)
    locs = build_named_locations(grid, spawns, DISPLAY)
    assert sum(1 for loc in locs if loc.kind == "ore") >= 4, [loc.name for loc in locs]

    if os.environ.get("ARENA_RECORD") == "1":
        DATA.mkdir(parents=True, exist_ok=True)
        (DATA / "obs_multi0_start.json").write_text(
            json.dumps({**first, "arena_spawns": {k: list(v) for k, v in spawns.items()}}, ensure_ascii=False),
            encoding="utf-8")

    assert (await client.start_match()).ok
    ex = PlayerExecutor("Multi0", DISPLAY, client, locs, spawns)
    await ex.refresh()
    r = ex.submit([{"kind": "扩张", "target": "红方基地"}])
    assert r.errors == []
    await _run_until(ex, lambda o: any(b["type"] == "fact" for b in o["buildings"]), 60)
    await _run_until(ex, lambda o: ex.book.get(1).status.value == "完成", 20)

    r = ex.submit([{"kind": "建造", "item": "电厂"}])
    assert r.errors == []
    await _run_until(ex, lambda o: any(b["type"] == "powr" for b in o["buildings"]), 90)
    text = ex.summary({})
    assert "【我方兵力】" in text and "powr" in text


class _Recording:
    """Forwards observe/issue and keeps the low-level commands the executor sent."""

    def __init__(self, inner) -> None:
        self.inner = inner
        self.issued: list[tuple[str, list[dict]]] = []

    async def observe(self, player: str, include_spatial: bool = False) -> dict:
        return await self.inner.observe(player, include_spatial=include_spatial)

    async def issue(self, player: str, commands: list[dict]) -> int:
        self.issued.append((player, list(commands)))
        return await self.inner.issue(player, commands)


def _actions(rec: _Recording, player: str) -> list[str]:
    return [c["action"] for who, cmds in rec.issued if who == player for c in cmds]


async def test_four_rl_agents_summary_and_orders(rl_agent_engine):
    """Four rl-agent slots: a summary each, then build and attack through the executor."""
    _proc, client, spec = rl_agent_engine
    assert spec.bot_type == "rl-agent" and spec.realtime is True
    snap = await client.list_players()
    assert [p.player for p in snap.players] == ["Multi0", "Multi1", "Multi2", "Multi3"]
    assert all(p.is_external for p in snap.players)
    assert snap.phase == "lobby_gate"
    spawns = {p.player: p.spawn for p in snap.players}
    assert len(set(spawns.values())) == 4

    observations = {name: await client.observe(name, include_spatial=True) for name in spawns}
    grid = SpatialGrid.from_obs(observations["Multi0"])
    locs = build_named_locations(grid, spawns, DISPLAY)
    assert sum(1 for loc in locs if loc.kind == "ore") >= 4

    if os.environ.get("ARENA_RECORD") == "1":
        DATA.mkdir(parents=True, exist_ok=True)
        (DATA / "obs_multi0_start.json").write_text(
            json.dumps({**observations["Multi0"], "arena_spawns": {k: list(v) for k, v in spawns.items()}},
                       ensure_ascii=False),
            encoding="utf-8")

    for name, obs in observations.items():
        ex = PlayerExecutor(name, DISPLAY, client, locs, spawns)
        ex.obs, ex.grid = obs, SpatialGrid.from_obs(obs)
        text = ex.summary({})
        assert f"你是{DISPLAY[name]}" in text
        assert "【我方兵力】" in text and "【地点】" in text
        assert len(text) <= 1200

    assert (await client.start_match()).ok
    rec = _Recording(client)
    ex = PlayerExecutor("Multi0", DISPLAY, rec, locs, spawns)
    await ex.refresh()

    # No combat units yet: the attack is accepted and the failure reason is visible on the task.
    early = ex.submit([{"kind": "进攻", "target": "蓝方基地", "count": 1}])
    assert early.errors == []
    await ex.step()
    early_task = ex.book.get(early.accepted[0])
    assert early_task is not None and early_task.status.value == "失败"
    assert "没有空闲的作战单位" in early_task.note

    expand = ex.submit([{"kind": "扩张", "target": "红方基地"}])
    assert expand.errors == []
    await _run_until(ex, lambda o: any(b["type"] == "fact" for b in o["buildings"]), 90)
    await _run_until(ex, lambda o: ex.book.get(expand.accepted[0]).status.value == "完成", 30)
    assert "deploy" in _actions(rec, "Multi0")

    build = ex.submit([{"kind": "建造", "item": "电厂"}])
    assert build.errors == []
    await _run_until(ex, lambda o: "build" in _actions(rec, "Multi0") or any(
        b["type"] == "powr" for b in o["buildings"]), 30)
    assert "build" in _actions(rec, "Multi0")
    await _run_until(ex, lambda o: any(b["type"] == "powr" for b in o["buildings"]), 120)
    await _run_until(ex, lambda o: ex.book.get(build.accepted[0]).status.value == "完成", 30)
    assert "powr" in ex.summary({})

    # Barracks, then one rifle squad, then a real attack-move.
    await _run_until(ex, lambda o: any(x in o.get("available_production", []) for x in ("tent", "barr")), 40)
    tents = ex.submit([{"kind": "建造", "item": "兵营"}])
    assert tents.errors == []
    await _run_until(ex, lambda o: any(b["type"] in ("tent", "barr") for b in o["buildings"]), 150)
    await _run_until(ex, lambda o: "e1" in o.get("available_production", []), 40)
    rifles = ex.submit([{"kind": "建造", "item": "步兵", "count": 1}])
    assert rifles.errors == []
    await _run_until(ex, lambda o: any(u["type"] == "e1" for u in o["units"]), 90)
    attack = ex.submit([{"kind": "进攻", "target": "蓝方基地", "count": 1}])
    assert attack.errors == []
    await _run_until(
        ex,
        lambda o: any(c.get("action") == "attack_move" for _p, cmds in rec.issued for c in cmds),
        30,
    )
    assert any(c.get("action") == "attack_move" for _p, cmds in rec.issued for c in cmds)
