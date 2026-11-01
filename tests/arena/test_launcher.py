from __future__ import annotations

from pathlib import Path

from openra_arena.engine.launcher import EngineLaunchSpec, build_engine_command, build_engine_env


def test_command_has_four_arena_slots_and_replays(tmp_path: Path):
    spec = EngineLaunchSpec(engine_dir=Path("/e"), support_dir=tmp_path, map_file="maelstrom.oramap")
    cmd = build_engine_command(spec)
    assert cmd[:2] == ["dotnet", "/e/bin/OpenRA.dll"]
    assert "Launch.Bots=Multi0:arena-agent,Multi1:arena-agent,Multi2:arena-agent,Multi3:arena-agent" in cmd
    assert "Launch.Map=maelstrom.oramap" in cmd
    assert "Server.RecordReplays=True" in cmd
    assert "Game.Platform=Null" in cmd
    assert f"Engine.SupportDir={tmp_path}/" in cmd
    assert "Launch.Realtime=True" not in cmd


def test_slot_overrides_mix_builtin_ai(tmp_path: Path):
    spec = EngineLaunchSpec(engine_dir=Path("/e"), support_dir=tmp_path,
                            slot_overrides=(("Multi1", "normal"), ("Multi2", "normal"), ("Multi3", "normal")))
    assert "Launch.Bots=Multi0:arena-agent,Multi1:normal,Multi2:normal,Multi3:normal" in build_engine_command(spec)


def test_env_sets_port_and_event_log(tmp_path: Path):
    spec = EngineLaunchSpec(engine_dir=Path("/e"), support_dir=tmp_path, grpc_port=20001, event_log=tmp_path / "ev.jsonl")
    env = build_engine_env(spec, {"PATH": "/bin"})
    assert env["RL_GRPC_PORT"] == "20001"
    assert env["RL_EVENT_LOG"] == str(tmp_path / "ev.jsonl")
    assert env["DOTNET_ROLL_FORWARD"] == "LatestMajor"
    assert env["PATH"] == "/bin"


def test_rl_agent_enables_launch_realtime(tmp_path: Path):
    spec = EngineLaunchSpec(engine_dir=Path("/e"), support_dir=tmp_path, bot_type="rl-agent")
    cmd = build_engine_command(spec)
    assert "Launch.Bots=Multi0:rl-agent,Multi1:rl-agent,Multi2:rl-agent,Multi3:rl-agent" in cmd
    assert "Launch.Realtime=True" in cmd
