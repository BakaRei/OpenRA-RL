from __future__ import annotations

import asyncio
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

DEFAULT_SLOTS: tuple[str, ...] = ("Multi0", "Multi1", "Multi2", "Multi3")


@dataclass(frozen=True)
class EngineLaunchSpec:
    engine_dir: Path
    support_dir: Path
    map_file: str = "maelstrom.oramap"
    slots: tuple[str, ...] = DEFAULT_SLOTS
    bot_type: str = "arena-agent"
    grpc_port: int = 19999
    event_log: Path | None = None
    extra_args: tuple[str, ...] = ()
    slot_overrides: tuple[tuple[str, str], ...] = ()  # e.g. (("Multi1", "normal"),) puts built-in AI in that slot
    # rl-agent is not realtime unless Launch.Realtime is set. arena-agent already has Realtime in yaml.
    realtime: bool = False


def build_engine_command(spec: EngineLaunchSpec) -> list[str]:
    overrides = dict(spec.slot_overrides)
    bots = ",".join(f"{slot}:{overrides.get(slot, spec.bot_type)}" for slot in spec.slots)
    cmd = [
        "dotnet",
        str(spec.engine_dir / "bin" / "OpenRA.dll"),
        f"Engine.EngineDir={spec.engine_dir}",
        f"Engine.SupportDir={spec.support_dir}/",
        "Game.Mod=ra",
        f"Launch.Map={spec.map_file}",
        f"Launch.Bots={bots}",
        "Game.Platform=Null",
        "Server.RecordReplays=True",
    ]
    # The shipped rl-agent trait is not realtime by itself. Launch.Realtime forces the
    # shared clock, start gate, and FastAdvance refusal for every external bot.
    if spec.realtime or spec.bot_type == "rl-agent":
        cmd.append("Launch.Realtime=True")
    cmd.extend(spec.extra_args)
    return cmd


def build_engine_env(spec: EngineLaunchSpec, base: Mapping[str, str]) -> dict[str, str]:
    env = dict(base)
    env["RL_GRPC_PORT"] = str(spec.grpc_port)
    env["DOTNET_ROLL_FORWARD"] = "LatestMajor"
    if spec.event_log is not None:
        env["RL_EVENT_LOG"] = str(spec.event_log)
    return env


class EngineProcess:
    """Runs one headless OpenRA arena game as a subprocess."""

    def __init__(self, spec: EngineLaunchSpec) -> None:
        self.spec = spec
        self._proc: asyncio.subprocess.Process | None = None

    @property
    def returncode(self) -> int | None:
        return None if self._proc is None else self._proc.returncode

    async def start(self) -> None:
        self.spec.support_dir.mkdir(parents=True, exist_ok=True)
        log = (self.spec.support_dir / "engine.stdout.log").open("ab")
        self._proc = await asyncio.create_subprocess_exec(
            *build_engine_command(self.spec),
            cwd=str(self.spec.engine_dir),
            env=build_engine_env(self.spec, os.environ),
            stdout=log,
            stderr=asyncio.subprocess.STDOUT,
        )
        log.close()

    async def wait_port(self, timeout_s: float = 120.0) -> None:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout_s
        while loop.time() < deadline:
            if self.returncode is not None:
                raise RuntimeError(f"engine exited early with code {self.returncode}")
            try:
                _, writer = await asyncio.open_connection("127.0.0.1", self.spec.grpc_port)
                writer.close()
                await writer.wait_closed()
                return
            except OSError:
                await asyncio.sleep(0.5)
        raise TimeoutError(f"gRPC port {self.spec.grpc_port} not open after {timeout_s}s")

    async def wait_exit(self, timeout_s: float) -> int | None:
        if self._proc is None:
            return None
        try:
            return await asyncio.wait_for(self._proc.wait(), timeout_s)
        except TimeoutError:
            return None

    async def stop(self, timeout_s: float = 15.0) -> int:
        if self._proc is None:
            return 0
        if self._proc.returncode is None:
            self._proc.terminate()
            if await self.wait_exit(timeout_s) is None:
                self._proc.kill()
                await self._proc.wait()
        return self._proc.returncode or 0

    def find_replays(self) -> list[Path]:
        return sorted(self.spec.support_dir.glob("Replays/**/*.orarep"))
