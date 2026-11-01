from __future__ import annotations

import os
from pathlib import Path

import pytest

from openra_env.generated import rl_bridge_pb2 as pb
from openra_env.generated import rl_bridge_pb2_grpc as pbg


def test_new_rpcs_exist_on_stub():
    for name in ("ListPlayers", "Observe", "IssueCommands", "StartMatch", "EndMatch", "SetTakeover"):
        assert hasattr(pbg.RLBridgeStub, "__init__")
        assert name in pb.DESCRIPTOR.services_by_name["RLBridge"].methods_by_name


def test_player_routing_fields():
    assert pb.StateRequest(session_id="s", player="Multi0").player == "Multi0"
    assert pb.FastAdvanceRequest(player="Multi1").player == "Multi1"
    req = pb.IssueCommandsRequest(player="Multi2", commands=[pb.Command(action=pb.MOVE, actor_id=5)])
    assert req.commands[0].actor_id == 5
    assert pb.ObserveRequest(player="Multi3", include_spatial=True).include_spatial is True


def test_economy_and_patrol_numbers():
    assert pb.RlEconomy.DESCRIPTOR.fields_by_name["earned"].number == 7
    assert pb.RlEconomy.DESCRIPTOR.fields_by_name["spent"].number == 8
    assert pb.PATROL == 22
    assert pb.PlayerSlot.DESCRIPTOR.fields_by_name["taken_over"].number == 8


def test_engine_and_python_proto_identical():
    """Compare against the engine checkout. Default is this repo's OpenRA submodule.

    The plan hardcoded /workspace/work/arena-engine. This repo keeps the engine as a
    submodule, so that path is only used when ARENA_ENGINE_DIR points at it.
    """
    root = Path(__file__).resolve().parents[2]
    engine = Path(os.environ["ARENA_ENGINE_DIR"]) if os.environ.get("ARENA_ENGINE_DIR") else root / "OpenRA"
    proto = engine / "OpenRA.Mods.Common/Traits/Player/Protos/rl_bridge.proto"
    if not proto.is_file():
        pytest.skip(f"engine proto not checked out at {proto}")
    py = root / "proto/rl_bridge.proto"
    assert proto.read_bytes() == py.read_bytes()
