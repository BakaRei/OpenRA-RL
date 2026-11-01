from __future__ import annotations

from openra_arena.executor.commands import ArenaCommand
from openra_arena.executor.locations import NamedLocation
from openra_arena.executor.spatial import CH_VISIBILITY, SpatialGrid
from openra_arena.executor.summary import MAX_SUMMARY_CHARS, SummaryInput, game_time, render_summary
from openra_arena.executor.tasks import TaskBook, TaskStatus

from .fixtures import building, make_obs, unit

DISPLAY = {"Multi0": "红方", "Multi1": "蓝方"}
LOCS = [NamedLocation("spawn_multi0", "红方基地", "spawn", 10, 10, 8),
        NamedLocation("spawn_multi1", "蓝方基地", "spawn", 50, 50, 8),
        NamedLocation("center", "中央", "region", 32, 32, 6)]


def _grid(visible: list[tuple[int, int]]) -> SpatialGrid:
    return SpatialGrid.from_cells(64, 64, {(x, y, CH_VISIBILITY): 1.0 for x, y in visible})


def test_game_time():
    assert game_time(0) == "00:00" and game_time(12500) == "08:20"


def test_summary_sections_and_fog():
    book = TaskBook()
    t = book.add(ArenaCommand("进攻", target="蓝方基地"), 0)
    t.note = "3 个单位前往蓝方基地"
    b = book.add(ArenaCommand("建造", item="powr", count=1), 0)
    book.finish(b, TaskStatus.DONE, "已建成 1 座 powr", 50)
    obs = make_obs(tick=12500, cash=3200, units=[unit(1, "3tnk", 10, 10), unit(2, "3tnk", 11, 10)],
                   buildings=[building(3, "fact", 9, 9)], enemies=[unit(9, "e1", 31, 32, owner="Multi1")],
                   available=["powr", "e1"])
    inp = SummaryInput("Multi0", DISPLAY, obs, _grid([(10, 10), (32, 32)]), LOCS,
                       {"spawn_multi0": "Multi0", "spawn_multi1": "Multi1", "center": "contested"},
                       book.recent(), events=["07:50 我方 powr 被摧毁"], shouts=[(12000, "蓝方", "投降吧")])
    text = render_summary(inp)
    assert "【时间】08:20（第 12500 帧）你是红方" in text
    assert "资金 3200" in text and "3tnk×2" in text
    assert "红方基地：我方；蓝方基地：迷雾未知；中央：争夺中" in text
    assert "蓝方在中央附近：e1" in text
    assert "#1 进攻 蓝方基地：进行中，3 个单位前往蓝方基地" in text
    assert "#2 建造 powr：完成，已建成 1 座 powr" in text
    assert "08:00 蓝方：“投降吧”" in text and "【可生产】powr、e1" in text


def test_summary_is_bounded():
    units = [unit(i, f"type{i}", i % 64, 0) for i in range(300)]
    obs = make_obs(units=units, available=[f"item{i}" for i in range(80)])
    locs = [NamedLocation(f"ore_{i}", f"东北矿区{i}", "ore", i, i, 4) for i in range(40)]
    text = render_summary(SummaryInput("Multi0", DISPLAY, obs, None, locs, {}, []))
    assert len(text) <= MAX_SUMMARY_CHARS
