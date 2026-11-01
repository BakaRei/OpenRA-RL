from __future__ import annotations

import asyncio
from dataclasses import dataclass

import grpc

from openra_env.generated import rl_bridge_pb2 as pb
from openra_env.generated import rl_bridge_pb2_grpc as pbg
from openra_env.server.bridge_client import commands_to_proto, observation_to_dict


@dataclass(frozen=True)
class PlayerInfo:
    player: str
    faction: str
    team: int
    is_external: bool
    win_state: str
    spawn: tuple[int, int]
    taken_over: bool


@dataclass(frozen=True)
class MatchSnapshot:
    tick: int
    phase: str
    players: list[PlayerInfo]

    def get(self, name: str) -> PlayerInfo:
        for p in self.players:
            if p.player == name:
                return p
        raise KeyError(name)

    @property
    def alive(self) -> list[str]:
        return [p.player for p in self.players if p.win_state != "lost"]


@dataclass(frozen=True)
class ControlResult:
    ok: bool
    message: str
    tick: int


def obs_to_dict(obs: pb.GameObservation, include_spatial: bool) -> dict:
    d = observation_to_dict(obs)
    d["economy"]["earned"] = obs.economy.earned
    d["economy"]["spent"] = obs.economy.spent
    if not include_spatial:
        d.pop("spatial_map", None)
    return d


def _control(resp: pb.MatchControlResponse) -> ControlResult:
    return ControlResult(ok=resp.ok, message=resp.message, tick=resp.tick)


class ArenaEngineClient:
    """Async client for the arena RPCs of the patched engine."""

    def __init__(self, address: str, session_id: str = "", timeout_s: float = 10.0) -> None:
        self._channel = grpc.aio.insecure_channel(address)
        self._stub = pbg.RLBridgeStub(self._channel)
        self._session = session_id
        self._timeout = timeout_s

    async def __aenter__(self) -> ArenaEngineClient:  # noqa: PYI034 - keep 3.10-compatible return type
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.close()

    async def close(self) -> None:
        await self._channel.close()

    async def list_players(self) -> MatchSnapshot:
        r = await self._stub.ListPlayers(pb.ListPlayersRequest(session_id=self._session), timeout=self._timeout)
        players = [
            PlayerInfo(p.player, p.faction, p.team, p.is_external, p.win_state, (p.spawn_x, p.spawn_y), p.taken_over)
            for p in r.players
        ]
        return MatchSnapshot(tick=r.tick, phase=r.phase, players=players)

    async def wait_ready(self, expected_players: int, timeout_s: float = 120.0, poll_s: float = 1.0) -> MatchSnapshot:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout_s
        last: Exception | None = None
        while loop.time() < deadline:
            try:
                snap = await self.list_players()
                if sum(p.is_external for p in snap.players) >= expected_players:
                    return snap
            except grpc.aio.AioRpcError as e:
                last = e
            await asyncio.sleep(poll_s)
        raise TimeoutError(f"engine not ready with {expected_players} external players: {last}")

    async def observe(self, player: str, include_spatial: bool = False) -> dict:
        req = pb.ObserveRequest(session_id=self._session, player=player, include_spatial=include_spatial)
        obs = await self._stub.Observe(req, timeout=self._timeout)
        return obs_to_dict(obs, include_spatial)

    async def issue(self, player: str, commands: list[dict]) -> int:
        if not commands:
            return 0
        action = commands_to_proto(commands)
        req = pb.IssueCommandsRequest(session_id=self._session, player=player, commands=action.commands)
        return (await self._stub.IssueCommands(req, timeout=self._timeout)).queued

    async def start_match(self) -> ControlResult:
        return _control(await self._stub.StartMatch(pb.StartMatchRequest(session_id=self._session), timeout=self._timeout))

    async def end_match(self, reason: str) -> ControlResult:
        req = pb.EndMatchRequest(session_id=self._session, reason=reason)
        return _control(await self._stub.EndMatch(req, timeout=self._timeout))

    async def set_takeover(self, player: str, enabled: bool) -> ControlResult:
        req = pb.SetTakeoverRequest(session_id=self._session, player=player, enabled=enabled)
        return _control(await self._stub.SetTakeover(req, timeout=self._timeout))
