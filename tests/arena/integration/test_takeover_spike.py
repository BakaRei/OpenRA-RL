"""Spike S4: built-in AI takeover of an arena-agent player via SetTakeover, and handing control back."""

from __future__ import annotations

import asyncio

import pytest

from openra_arena.engine.events import read_events
from openra_arena.executor.executor import PlayerExecutor
from openra_arena.executor.locations import build_named_locations
from openra_arena.executor.spatial import SpatialGrid

pytestmark = pytest.mark.engine

DISPLAY = {"Multi0": "红方", "Multi1": "蓝方", "Multi2": "绿方", "Multi3": "黄方"}


def placed(path, player: str, after_tick: int = -1) -> list[dict]:
    return [e for e in read_events(path)
            if e["type"] == "building_placed" and e["owner"] == player and e["t"] > after_tick]


async def wait_for(pred, timeout_s: float, interval_s: float = 2.0):
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_s
    while loop.time() < deadline:
        value = await pred()
        if value:
            return value
        await asyncio.sleep(interval_s)
    return None


async def test_takeover_builds_without_commands_and_releases(arena_engine):
    _proc, client, spec = arena_engine
    snap = await client.list_players()
    spawns = {p.player: p.spawn for p in snap.players}
    grid = SpatialGrid.from_obs(await client.observe("Multi0", include_spatial=True))
    assert (await client.start_match()).ok
    ex = PlayerExecutor("Multi0", DISPLAY, client, build_named_locations(grid, spawns, DISPLAY), spawns)
    await ex.refresh()
    ex.submit([{"kind": "扩张", "target": "红方基地"}])

    async def has_fact():
        obs = await ex.refresh()
        await ex.step()
        return any(b["type"] == "fact" for b in obs["buildings"])

    assert await wait_for(has_fact, 60), "MCV never deployed"

    # (a) takeover on: within 90 s at least one new building appears with no external commands.
    on = await client.set_takeover("Multi0", True)
    assert on.ok, on.message

    async def ai_built():
        return placed(spec.event_log, "Multi0", on.tick)

    assert await wait_for(ai_built, 90), "built-in AI placed nothing while in control"

    # (b) takeover off: after a 20 s grace period the building count stays flat for 60 s.
    off = await client.set_takeover("Multi0", False)
    assert off.ok, off.message
    await asyncio.sleep(20)
    before = len((await client.observe("Multi0"))["buildings"])
    await asyncio.sleep(60)
    assert len((await client.observe("Multi0"))["buildings"]) == before, "AI kept building after release"

    # (c) external commands work again.
    assert await client.issue("Multi0", [{"action": "build", "item_type": "powr"}]) == 1
