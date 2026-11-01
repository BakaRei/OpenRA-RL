from __future__ import annotations

import grpc
import pytest

from openra_arena.engine.client import ArenaEngineClient
from openra_env.generated import rl_bridge_pb2 as pb


async def test_list_players_and_start_once(fake_engine):
    _fake, addr = fake_engine
    async with ArenaEngineClient(addr) as client:
        snap = await client.wait_ready(4, timeout_s=5)
        assert [p.player for p in snap.players] == ["Multi0", "Multi1", "Multi2", "Multi3"]
        assert snap.phase == "lobby_gate"
        assert snap.get("Multi1").spawn == (40, 40)
        assert (await client.start_match()).ok is True
        assert (await client.start_match()).ok is False


async def test_observe_adds_earned_and_drops_spatial(fake_engine):
    fake, addr = fake_engine
    fake.observations["Multi0"] = pb.GameObservation(
        tick=42, economy=pb.RlEconomy(cash=5000, earned=1200, spent=300), spatial_map=b"\x00" * 36, spatial_channels=9)
    async with ArenaEngineClient(addr) as client:
        obs = await client.observe("Multi0")
        assert obs["tick"] == 42
        assert obs["economy"]["earned"] == 1200 and obs["economy"]["spent"] == 300
        assert "spatial_map" not in obs
        full = await client.observe("Multi0", include_spatial=True)
        assert full["spatial_channels"] == 9 and full["spatial_map"]


async def test_issue_converts_dicts(fake_engine):
    fake, addr = fake_engine
    async with ArenaEngineClient(addr) as client:
        assert await client.issue("Multi2", [{"action": "move", "actor_id": 7, "target_x": 3, "target_y": 4}]) == 1
        assert await client.issue("Multi2", []) == 0
    player, cmds = fake.issued[0]
    assert player == "Multi2" and cmds[0].action == pb.MOVE and cmds[0].target_y == 4


async def test_observe_without_player_raises(fake_engine):
    _, addr = fake_engine
    async with ArenaEngineClient(addr) as client:
        with pytest.raises(grpc.aio.AioRpcError) as ei:
            await client.observe("")
        assert ei.value.code() == grpc.StatusCode.INVALID_ARGUMENT


async def test_wait_ready_times_out_without_server():
    async with ArenaEngineClient("127.0.0.1:1", timeout_s=0.2) as client:
        with pytest.raises(TimeoutError):
            await client.wait_ready(4, timeout_s=0.5, poll_s=0.1)
