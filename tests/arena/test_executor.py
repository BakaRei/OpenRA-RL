from __future__ import annotations

import json
from pathlib import Path

import pytest

from openra_arena.executor.executor import PlayerExecutor
from openra_arena.executor.locations import NamedLocation, build_named_locations
from openra_arena.executor.spatial import SpatialGrid
from openra_arena.executor.tasks import TaskStatus

from .fixtures import building, make_obs, unit

DISPLAY = {"Multi0": "红方", "Multi1": "蓝方"}
SPAWNS = {"Multi0": (10, 10), "Multi1": (50, 50)}
LOCS = [NamedLocation("spawn_multi0", "红方基地", "spawn", 10, 10, 8),
        NamedLocation("spawn_multi1", "蓝方基地", "spawn", 50, 50, 8)]
RECORDED = Path(__file__).parent / "data" / "obs_multi0_start.json"


class FakeClient:
    def __init__(self, frames: list[dict]) -> None:
        self.frames = frames
        self.issued: list[tuple[str, list[dict]]] = []

    async def observe(self, player: str, include_spatial: bool = False) -> dict:
        return self.frames.pop(0) if len(self.frames) > 1 else self.frames[0]

    async def issue(self, player: str, commands: list[dict]) -> int:
        self.issued.append((player, commands))
        return len(commands)


def make_executor(frames: list[dict], shouts: list | None = None) -> tuple[PlayerExecutor, FakeClient]:
    client = FakeClient(frames)
    sink = shouts if shouts is not None else []
    ex = PlayerExecutor("Multi0", DISPLAY, client, LOCS, SPAWNS, on_shout=lambda p, t: sink.append((p, t)))
    return ex, client


async def test_submit_feedback_and_shout():
    shouts: list = []
    ex, _ = make_executor([make_obs()], shouts)
    await ex.refresh()
    r = ex.submit([{"kind": "建造", "item": "e1"}, {"kind": "飞"}, {"kind": "喊话", "text": "来战"}])
    assert r.accepted == [1, 2] and r.errors == ["第 2 条：未知指令 飞"]
    assert r.feedback() == "已接受任务 #1、#2。被拒绝：第 2 条：未知指令 飞"
    assert shouts == [("Multi0", "来战")]


async def test_step_issues_low_level_commands_and_respects_pause():
    ex, client = make_executor([make_obs(available=["e1"])])
    await ex.refresh()
    ex.submit([{"kind": "建造", "item": "e1", "count": 2}])
    ex.paused = True
    assert await ex.step() == 0
    ex.paused = False
    assert await ex.step() == 2
    assert client.issued == [("Multi0", [{"action": "train", "item_type": "e1"}] * 2)]


async def test_diff_reports_losses_and_base_alert_once():
    yard, powr = building(1, "fact", 10, 10), building(2, "powr", 13, 10)
    army = [unit(i, "e1", 12, 12) for i in range(10, 14)]
    enemy = unit(90, "3tnk", 14, 14, owner="Multi1")
    frames = [make_obs(tick=0, buildings=[yard, powr], units=army),
              make_obs(tick=250, buildings=[yard], units=army[:1], enemies=[enemy]),
              make_obs(tick=500, buildings=[yard], units=army[:1], enemies=[enemy])]
    ex, _ = make_executor(frames)
    for _ in range(3):
        await ex.refresh()
    urgent = ex.pop_urgent()
    assert urgent == ["00:10 我方 powr 被摧毁", "00:10 损失 3 个单位：e1×3", "00:10 基地附近发现 1 个敌方单位"]
    assert ex.pop_urgent() == []
    summary = ex.summary({"spawn_multi0": "Multi0"})
    assert "【最近事件】00:10 我方 powr 被摧毁" in summary


async def test_task_finishes_through_executor_loop():
    frames = [make_obs(units=[unit(1, "e1", 12, 12)]), make_obs(units=[unit(1, "e1", 50, 50)])]
    ex, client = make_executor(frames)
    await ex.refresh()
    ex.submit([{"kind": "进攻", "target": "蓝方基地"}])
    await ex.step()
    await ex.refresh()
    await ex.step()
    assert ex.book.get(1).status == TaskStatus.DONE
    assert client.issued[0][1][0]["action"] == "attack_move"


@pytest.mark.skipif(not RECORDED.exists(), reason="recorded observation not captured yet (Task 16 Step 5)")
async def test_recorded_real_observation_builds_locations_and_summary():
    obs = json.loads(RECORDED.read_text(encoding="utf-8"))
    grid = SpatialGrid.from_obs(obs)
    spawns = {"Multi0": tuple(obs["arena_spawns"]["Multi0"]), "Multi1": tuple(obs["arena_spawns"]["Multi1"]),
              "Multi2": tuple(obs["arena_spawns"]["Multi2"]), "Multi3": tuple(obs["arena_spawns"]["Multi3"])}
    display = {"Multi0": "红方", "Multi1": "蓝方", "Multi2": "绿方", "Multi3": "黄方"}
    locs = build_named_locations(grid, spawns, display)
    assert sum(1 for loc in locs if loc.kind == "ore") >= 4
    ex, _ = make_executor([obs])
    ex.locations, ex.spawns, ex.display = locs, spawns, display
    await ex.refresh()
    text = ex.summary({})
    assert "红方基地：" in text and len(text) <= 1200
    assert any(u["type"] == "mcv" for u in obs["units"])
