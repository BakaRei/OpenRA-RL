"""Task 21: takeover state is visible in ListPlayers, logged as events, and blocks external commands."""

from __future__ import annotations

import asyncio

import pytest

from openra_arena.engine.events import read_events

pytestmark = pytest.mark.engine


def by_name(snap) -> dict:
    return {p.player: p for p in snap.players}


async def test_takeover_flag_events_and_command_block(arena_engine):
    _proc, client, spec = arena_engine
    assert (await client.start_match()).ok
    assert not any(p.taken_over for p in (await client.list_players()).players)

    on = await client.set_takeover("Multi2", True)
    assert on.ok, on.message
    again = await client.set_takeover("Multi2", True)
    assert again.ok and "already" in again.message
    assert by_name(await client.list_players())["Multi2"].taken_over is True
    assert by_name(await client.list_players())["Multi1"].taken_over is False

    assert await client.issue("Multi2", [{"action": "build", "item_type": "powr"}]) == 0
    await asyncio.sleep(1)
    rejected = [e for e in read_events(spec.event_log) if e["type"] == "command_rejected" and e["player"] == "Multi2"]
    assert [e["reason"] for e in rejected] == ["taken_over"]

    off = await client.set_takeover("Multi2", False)
    assert off.ok, off.message
    assert by_name(await client.list_players())["Multi2"].taken_over is False
    assert await client.issue("Multi2", [{"action": "build", "item_type": "powr"}]) == 1

    events = [(e["player"], e["enabled"]) for e in read_events(spec.event_log) if e["type"] == "takeover"]
    assert events == [("Multi2", True), ("Multi2", False)]
    bad = await client.set_takeover("Multi9", True)
    assert bad.ok is False and "Multi9" in bad.message


async def test_builtin_slot_cannot_be_toggled(mixed_engine):
    _proc, client, _spec = mixed_engine
    r = await client.set_takeover("Multi1", False)
    assert r.ok is False and "no arena bridge" in r.message
