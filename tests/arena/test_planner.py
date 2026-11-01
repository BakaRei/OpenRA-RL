from __future__ import annotations

from openra_arena.executor.commands import ArenaCommand
from openra_arena.executor.locations import NamedLocation
from openra_arena.executor.planner import PlanContext, resolve_target, step_task
from openra_arena.executor.tasks import TaskBook, TaskStatus

from .fixtures import building, make_obs, unit

SPAWNS = {"Multi0": (10, 10), "Multi1": (50, 50)}
DISPLAY = {"Multi0": "红方", "Multi1": "蓝方"}
LOCS = [
    NamedLocation("spawn_multi0", "红方基地", "spawn", 10, 10, 8),
    NamedLocation("spawn_multi1", "蓝方基地", "spawn", 50, 50, 8),
    NamedLocation("ore_0", "中央矿区", "ore", 30, 30, 5),
    NamedLocation("ore_1", "蓝方矿区", "ore", 46, 52, 5),
]
YARD = building(1, "fact", 20, 20)


def ctx(obs: dict, book: TaskBook, tick: int = 100, seen=None) -> PlanContext:
    return PlanContext("Multi0", tick, obs, None, LOCS, SPAWNS, DISPLAY, book, dict(seen or {}))


def queue(item: str, progress: float) -> dict:
    return {"queue_type": "Building", "item": item, "progress": progress, "remaining_ticks": 0,
            "remaining_cost": 0, "paused": False}


def test_resolve_target_prefers_last_seen_for_players():
    book = TaskBook()
    assert resolve_target(ctx(make_obs(), book), "蓝方基地") == (50, 50, "蓝方基地")
    assert resolve_target(ctx(make_obs(), book, seen={"Multi1": (44, 40)}), "蓝方") == (44, 40, "蓝方")
    assert resolve_target(ctx(make_obs(), book), "月球") is None


def test_build_unknown_item_fails():
    book = TaskBook()
    t = book.add(ArenaCommand("建造", item="雷达", count=1), 0)
    assert step_task(t, ctx(make_obs(available=["powr"]), book)) == []
    assert t.status == TaskStatus.FAILED and "当前无法建造 雷达" in t.note


def test_build_structure_lifecycle_with_placement_retry():
    book = TaskBook()
    t = book.add(ArenaCommand("建造", item="电厂", count=1), 0)
    avail = ["powr", "e1"]
    assert step_task(t, ctx(make_obs(buildings=[YARD], available=avail), book)) == [
        {"action": "build", "item_type": "powr"}]
    assert step_task(t, ctx(make_obs(buildings=[YARD], available=avail, production=[queue("powr", 0.4)]), book)) == []
    ready = make_obs(buildings=[YARD], available=avail, production=[queue("powr", 1.0)])
    assert step_task(t, ctx(ready, book)) == [
        {"action": "place_building", "item_type": "powr", "target_x": 17, "target_y": 20}]
    assert step_task(t, ctx(ready, book)) == [
        {"action": "place_building", "item_type": "powr", "target_x": 20, "target_y": 16}]
    done = make_obs(buildings=[YARD, building(2, "powr", 20, 16)], available=avail)
    assert step_task(t, ctx(done, book)) == []
    assert t.status == TaskStatus.DONE and t.note == "已建成 1 座 powr"


def test_build_gives_up_after_placement_attempts():
    book = TaskBook()
    t = book.add(ArenaCommand("建造", item="powr", count=1), 0)
    ready = make_obs(buildings=[YARD], available=["powr"], production=[queue("powr", 1.0)])
    t.data.update(item="powr", remaining=0, attempt=20, pending=False, wait=0)
    assert step_task(t, ctx(ready, book)) == [{"action": "cancel_production", "item_type": "powr"}]
    assert t.status == TaskStatus.FAILED and "找不到可以摆放" in t.note


def test_build_fails_when_production_never_starts():
    book = TaskBook()
    t = book.add(ArenaCommand("建造", item="powr", count=1), 0)
    obs = make_obs(buildings=[YARD], available=["powr"])
    assert len(step_task(t, ctx(obs, book))) == 1
    for _ in range(3):
        step_task(t, ctx(obs, book))
    assert t.status == TaskStatus.FAILED and "生产没有开始" in t.note


def test_train_units_then_done():
    book = TaskBook()
    t = book.add(ArenaCommand("建造", item="步兵", count=3), 0)
    obs = make_obs(available=["e1"])
    assert step_task(t, ctx(obs, book)) == [{"action": "train", "item_type": "e1"}] * 3
    assert step_task(t, ctx(make_obs(available=["e1"], production=[queue("e1", 0.2)]), book)) == []
    assert step_task(t, ctx(obs, book)) == [] and t.status == TaskStatus.DONE


def test_attack_selects_combat_units_and_finishes_on_arrival():
    book = TaskBook()
    army = [unit(i, "e1", 12, 12) for i in (1, 2, 3, 4)] + [unit(9, "harv", 12, 12)]
    t = book.add(ArenaCommand("进攻", target="蓝方基地", count=3), 0)
    cmds = step_task(t, ctx(make_obs(units=army), book))
    assert cmds == [{"action": "attack_move", "actor_id": i, "target_x": 50, "target_y": 50} for i in (1, 2, 3)]
    assert t.units == {1, 2, 3}
    moving = [unit(i, "e1", 30, 30, idle=False) for i in (1, 2, 3)]
    assert step_task(t, ctx(make_obs(units=moving), book)) == []
    there = [unit(i, "e1", 50, 50) for i in (1, 2, 3)]
    assert step_task(t, ctx(make_obs(units=there), book)) == []
    assert t.status == TaskStatus.DONE and t.note.startswith("已抵达蓝方基地")


def test_attack_chases_visible_enemies_and_fails_when_wiped():
    book = TaskBook()
    t = book.add(ArenaCommand("进攻", target="蓝方基地"), 0)
    step_task(t, ctx(make_obs(units=[unit(1, "3tnk", 12, 12)]), book))
    enemy = unit(70, "e1", 55, 50, owner="Multi1")
    obs = make_obs(units=[unit(1, "3tnk", 50, 50)], enemies=[enemy])
    assert step_task(t, ctx(obs, book)) == [{"action": "attack_move", "actor_id": 1, "target_x": 55, "target_y": 50}]
    assert step_task(t, ctx(make_obs(), book)) == []
    assert t.status == TaskStatus.FAILED and t.note == "进攻部队已全部阵亡"


def test_attack_without_free_units_fails():
    book = TaskBook()
    t = book.add(ArenaCommand("进攻", target="中央矿区", unit_type="3tnk"), 0)
    step_task(t, ctx(make_obs(units=[unit(1, "e1", 1, 1)]), book))
    assert t.status == TaskStatus.FAILED and t.note == "没有空闲的作战单位（3tnk）"


def test_defend_keeps_count_and_returns_strays():
    book = TaskBook()
    t = book.add(ArenaCommand("防守", target="中央矿区", count=2), 0)
    units = [unit(1, "e1", 30, 31), unit(2, "e1", 10, 10), unit(3, "e1", 11, 10)]
    cmds = step_task(t, ctx(make_obs(units=units), book))
    assert t.units == {1, 3}
    assert cmds == [{"action": "attack_move", "actor_id": 3, "target_x": 30, "target_y": 30}]
    assert t.status == TaskStatus.ACTIVE and t.note == "驻守中央矿区：2/2"


def test_expand_moves_deploys_and_confirms():
    book = TaskBook()
    t = book.add(ArenaCommand("扩张", target="中央矿区"), 0)
    assert step_task(t, ctx(make_obs(units=[unit(7, "mcv", 10, 12, can_attack=False)]), book)) == [
        {"action": "move", "actor_id": 7, "target_x": 30, "target_y": 30}]
    assert step_task(t, ctx(make_obs(units=[unit(7, "mcv", 30, 31, can_attack=False)]), book)) == [
        {"action": "deploy", "actor_id": 7}]
    assert step_task(t, ctx(make_obs(buildings=[building(8, "fact", 29, 29)]), book)) == []
    assert t.status == TaskStatus.DONE and t.note == "已在中央矿区展开基地"


def test_expand_orders_mcv_or_fails():
    book = TaskBook()
    t = book.add(ArenaCommand("扩张", target="中央矿区"), 0)
    assert step_task(t, ctx(make_obs(available=["mcv"]), book)) == [{"action": "train", "item_type": "mcv"}]
    t2 = book.add(ArenaCommand("扩张", target="中央矿区"), 0)
    step_task(t2, ctx(make_obs(), book))
    assert t2.status == TaskStatus.FAILED and "无法生产" in t2.note


def test_harass_prefers_fast_units_hits_harvesters_and_retreats_hurt():
    book = TaskBook()
    t = book.add(ArenaCommand("骚扰", target="蓝方", count=2), 0)
    units = [unit(5, "e1", 12, 12), unit(6, "jeep", 14, 14), unit(7, "e1", 11, 11)]
    cmds = step_task(t, ctx(make_obs(units=units), book))
    assert t.units == {6, 7}
    assert cmds == [{"action": "attack_move", "actor_id": 6, "target_x": 46, "target_y": 52},
                    {"action": "attack_move", "actor_id": 7, "target_x": 46, "target_y": 52}]
    harv = unit(80, "harv", 47, 52, owner="Multi1")
    obs = make_obs(units=[unit(6, "jeep", 45, 50, hp=30), unit(7, "e1", 44, 50)], enemies=[harv])
    cmds = step_task(t, ctx(obs, book))
    assert cmds == [{"action": "move", "actor_id": 6, "target_x": 10, "target_y": 10},
                    {"action": "attack", "actor_id": 7, "target_actor_id": 80}]
    assert t.units == {7}


def test_retreat_cancels_attacks_and_moves_home():
    book = TaskBook()
    attack = book.add(ArenaCommand("进攻", target="蓝方基地"), 0)
    step_task(attack, ctx(make_obs(units=[unit(1, "e1", 12, 12)]), book))
    retreat = book.add(ArenaCommand("撤退"), 0)
    cmds = step_task(retreat, ctx(make_obs(buildings=[YARD], units=[unit(1, "e1", 40, 40)]), book))
    assert cmds == [{"action": "move", "actor_id": 1, "target_x": 20, "target_y": 20}]
    assert attack.status == TaskStatus.CANCELLED and retreat.status == TaskStatus.DONE


def test_cancel_and_shout():
    book = TaskBook()
    d = book.add(ArenaCommand("防守", target="中央矿区", count=1), 0)
    step_task(d, ctx(make_obs(units=[unit(1, "e1", 30, 30)]), book))
    c = book.add(ArenaCommand("取消", task_id=d.id), 0)
    assert step_task(c, ctx(make_obs(), book)) == [{"action": "stop", "actor_id": 1}]
    assert d.status == TaskStatus.CANCELLED and c.note == "已取消任务 #1"
    bad = book.add(ArenaCommand("取消", task_id=99), 0)
    step_task(bad, ctx(make_obs(), book))
    assert bad.status == TaskStatus.FAILED
    s = book.add(ArenaCommand("喊话", text="你好"), 0)
    assert step_task(s, ctx(make_obs(), book)) == [] and s.status == TaskStatus.DONE
