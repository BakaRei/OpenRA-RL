"""Cheap checks the M2 PR left unverified on bot-arena-m1: tick rate, rejected commands, replays, mixed slots."""

from __future__ import annotations

import asyncio

import grpc
import pytest

from openra_arena.engine.events import read_events

pytestmark = pytest.mark.engine


async def test_realtime_tick_rate_rejected_command_and_replay(arena_engine):
    proc, client, spec = arena_engine
    snap = await client.list_players()
    assert snap.phase == "lobby_gate"
    assert all(p.is_external for p in snap.players)
    assert (await client.start_match()).ok

    t0 = (await client.observe("Multi0"))["tick"]
    await asyncio.sleep(4)
    t1 = (await client.observe("Multi0"))["tick"]
    rate = (t1 - t0) / 4
    print(f"realtime tick rate {rate:.2f}/s ({t0} -> {t1})")
    assert 15 <= rate <= 40, f"tick rate {rate:.1f}/s (tick {t0} -> {t1})"

    queued = await client.issue("Multi0", [{"action": "fast_advance", "ticks": 50}])
    assert queued == 0
    await asyncio.sleep(0.5)
    rejected = [e for e in read_events(spec.event_log) if e.get("type") == "command_rejected" and e.get("player") == "Multi0"]
    assert rejected and rejected[0]["reason"] == "unsupported_action", rejected

    assert (await client.end_match("probe")).ok
    replays = []
    for _ in range(30):
        replays = proc.find_replays()
        if replays:
            break
        await asyncio.sleep(0.5)
    assert replays, "no .orarep written"
    blob = replays[0].read_bytes()
    assert len(blob) > 64
    # Metadata footer names the mod and the map by content hash, not by filename.
    assert b"Mod: ra" in blob and b"\n\tMap:" in blob
    assert b"Slot: Multi0" in blob and b"Bot: arena-agent" in blob


async def test_one_external_three_builtin_slots(mixed_engine):
    _proc, client, _spec = mixed_engine
    snap = await client.list_players()
    by = {p.player: p for p in snap.players}
    assert by["Multi0"].is_external is True
    assert by["Multi1"].is_external is False
    assert by["Multi2"].is_external is False
    assert by["Multi3"].is_external is False
    assert len({p.spawn for p in snap.players}) == 4
    # OpenRA uses team 0 for "no shared team": the four players are not allied (FFA).
    assert [p.team for p in snap.players] == [0, 0, 0, 0]
    assert (await client.start_match()).ok
    obs = await client.observe("Multi0")
    assert "economy" in obs and "tick" in obs
    with pytest.raises(grpc.aio.AioRpcError) as exc:
        await client.observe("Multi1")
    assert exc.value.code() == grpc.StatusCode.NOT_FOUND
