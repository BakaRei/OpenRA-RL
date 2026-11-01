from __future__ import annotations

import os
import random
from pathlib import Path

import pytest

from openra_arena.engine.client import ArenaEngineClient
from openra_arena.engine.launcher import EngineLaunchSpec, EngineProcess

ENGINE_DIR = os.environ.get("ARENA_ENGINE_DIR", "")


def pytest_collection_modifyitems(config, items):
    if ENGINE_DIR:
        return
    skip = pytest.mark.skip(reason="ARENA_ENGINE_DIR not set")
    for item in items:
        if "engine" in item.keywords:
            item.add_marker(skip)


def _link_ra_content(support: Path) -> None:
    """Headless RA needs the mix files under SupportDir/Content/ra/v2.

    The launcher itself does not install content. Tests symlink a local install
    (ARENA_RA_CONTENT, or ~/.config/openra/Content/ra/v2) when it is present.
    """
    src = Path(os.environ.get("ARENA_RA_CONTENT", Path.home() / ".config/openra/Content/ra/v2"))
    if not src.is_dir():
        return
    dest = support / "Content" / "ra" / "v2"
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not dest.exists():
        dest.symlink_to(src, target_is_directory=True)


async def launch_engine(tmp_path: Path, slot_overrides: tuple[tuple[str, str], ...] = (),
                        bot_type: str | None = None, realtime: bool | None = None):
    _link_ra_content(tmp_path / "support")
    port = random.randint(20000, 29000)
    kwargs = {}
    if bot_type is not None:
        kwargs["bot_type"] = bot_type
    if realtime is not None:
        kwargs["realtime"] = realtime
    spec = EngineLaunchSpec(
        engine_dir=Path(ENGINE_DIR), support_dir=tmp_path / "support", grpc_port=port,
        event_log=tmp_path / "events.jsonl", map_file=os.environ.get("ARENA_MAP", "maelstrom.oramap"),
        slot_overrides=slot_overrides,
        **kwargs,
    )
    proc = EngineProcess(spec)
    await proc.start()
    await proc.wait_port(timeout_s=180)
    client = ArenaEngineClient(f"127.0.0.1:{port}", timeout_s=15)
    await client.wait_ready(len(spec.slots) - len(slot_overrides), timeout_s=180)
    return proc, client, spec


@pytest.fixture
async def arena_engine(tmp_path: Path):
    proc, client, spec = await launch_engine(tmp_path)
    yield proc, client, spec
    await client.close()
    await proc.stop()


@pytest.fixture
async def mixed_engine(tmp_path: Path):
    """Multi0 external, Multi1..3 built-in normal AI (spec: '1 external + 3 built-in AI')."""
    proc, client, spec = await launch_engine(
        tmp_path, (("Multi1", "normal"), ("Multi2", "normal"), ("Multi3", "normal")))
    yield proc, client, spec
    await client.close()
    await proc.stop()


@pytest.fixture
async def rl_agent_engine(tmp_path: Path):
    """Four rl-agent slots with Launch.Realtime, matching the bot-arena-m1 engine contract."""
    proc, client, spec = await launch_engine(tmp_path, bot_type="rl-agent", realtime=True)
    yield proc, client, spec
    await client.close()
    await proc.stop()
