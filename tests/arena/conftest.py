from __future__ import annotations

import grpc
import pytest

from openra_env.generated import rl_bridge_pb2 as pb
from openra_env.generated import rl_bridge_pb2_grpc as pbg


class FakeBridge(pbg.RLBridgeServicer):
    """In-process stand-in for the arena engine's gRPC surface."""

    def __init__(self) -> None:
        self.started = False
        self.issued: list[tuple[str, list[pb.Command]]] = []
        self.observations: dict[str, pb.GameObservation] = {}
        self.takeovers: list[tuple[str, bool]] = []
        self.ended: str | None = None
        self.win_states: dict[str, str] = {f"Multi{i}": "undefined" for i in range(4)}
        self.tick = 0

    async def ListPlayers(self, request, context):
        players = [
            pb.PlayerSlot(player=name, faction="soviet", team=0, is_external=True, win_state=state,
                          spawn_x=10 + 30 * i, spawn_y=10 + 30 * (i % 2))
            for i, (name, state) in enumerate(sorted(self.win_states.items()))
        ]
        phase = "playing" if self.started else "lobby_gate"
        return pb.ListPlayersResponse(players=players, tick=self.tick, phase=phase)

    async def Observe(self, request, context):
        if not request.player:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, "player required")
        obs = pb.GameObservation()
        obs.CopyFrom(self.observations.get(request.player, pb.GameObservation(tick=self.tick)))
        if not request.include_spatial:
            obs.ClearField("spatial_map")
        return obs

    async def IssueCommands(self, request, context):
        self.issued.append((request.player, list(request.commands)))
        return pb.IssueCommandsResponse(queued=len(request.commands), tick=self.tick)

    async def StartMatch(self, request, context):
        ok = not self.started
        self.started = True
        return pb.MatchControlResponse(ok=ok, message="started" if ok else "cannot start: phase is playing")

    async def EndMatch(self, request, context):
        self.ended = request.reason
        return pb.MatchControlResponse(ok=True, message="ending", tick=self.tick)

    async def SetTakeover(self, request, context):
        self.takeovers.append((request.player, request.enabled))
        return pb.MatchControlResponse(ok=True, message="ok", tick=self.tick)


@pytest.fixture
async def fake_engine():
    server = grpc.aio.server()
    fake = FakeBridge()
    pbg.add_RLBridgeServicer_to_server(fake, server)
    port = server.add_insecure_port("127.0.0.1:0")
    await server.start()
    yield fake, f"127.0.0.1:{port}"
    await server.stop(None)
