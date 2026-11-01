"""Turns one high-level Task into low-level CommandModel dicts, one executor step at a time."""

from __future__ import annotations

from dataclasses import dataclass, field

from openra_arena.executor.commands import resolve_item
from openra_arena.executor.locations import NamedLocation, find_location
from openra_arena.executor.placement import MAX_PLACEMENT_ATTEMPTS, is_building_type, placement_candidates
from openra_arena.executor.spatial import SpatialGrid
from openra_arena.executor.tasks import Task, TaskBook, TaskStatus

NON_COMBAT = frozenset({"harv", "mcv", "e6", "truk", "mnly", "spy", "medi", "mech", "thf"})
FAST_TYPES = ("jeep", "1tnk", "apc", "ftrk", "dog")
ARRIVE_RADIUS = 6
CHASE_RADIUS = 10
DEFEND_RADIUS = 5
EXPAND_OFFSETS = [(0, 0), (3, 0), (-3, 0), (0, 3), (0, -3), (3, 3)]
MAX_PRODUCTION_WAIT_STEPS = 3
MAX_MCV_WAIT_STEPS = 60
HARASS_RETREAT_HP = 50


@dataclass
class PlanContext:
    player: str
    tick: int
    obs: dict
    grid: SpatialGrid | None
    locations: list[NamedLocation]
    spawns: dict[str, tuple[int, int]]
    display: dict[str, str]
    book: TaskBook
    last_seen_enemy: dict[str, tuple[int, int]] = field(default_factory=dict)


def dist2(ax: int, ay: int, bx: int, by: int) -> int:
    return (ax - bx) ** 2 + (ay - by) ** 2


def base_point(ctx: PlanContext) -> tuple[int, int]:
    yard = next((b for b in ctx.obs.get("buildings", []) if b["type"] == "fact"), None)
    if yard is not None:
        return yard["cell_x"], yard["cell_y"]
    return ctx.spawns[ctx.player]


def resolve_player(ctx: PlanContext, text: str | None) -> str | None:
    t = (text or "").strip()
    for p, name in ctx.display.items():
        if t in (p, name, f"{name}基地") or t.lower() == p.lower():
            return p
    return None


def resolve_target(ctx: PlanContext, text: str | None) -> tuple[int, int, str] | None:
    player = resolve_player(ctx, text)
    if player is not None and not (text or "").endswith("基地"):
        x, y = ctx.last_seen_enemy.get(player, ctx.spawns[player])
        return x, y, ctx.display[player]
    loc = find_location(ctx.locations, text or "")
    if loc is not None:
        return loc.x, loc.y, loc.name
    return None


def combat_units(obs: dict) -> list[dict]:
    return [u for u in obs.get("units", [])
            if u.get("can_attack") and u["type"] not in NON_COMBAT and not u.get("is_building")]


def task_units(task: Task, obs: dict) -> list[dict]:
    return sorted((u for u in obs.get("units", []) if u["actor_id"] in task.units), key=lambda u: u["actor_id"])


def free_combat_units(ctx: PlanContext, near: tuple[int, int], unit_type: str | None = None,
                      idle_only: bool = False) -> list[dict]:
    units = [u for u in combat_units(ctx.obs) if ctx.book.owner_of(u["actor_id"]) is None]
    if unit_type:
        units = [u for u in units if u["type"] == unit_type]
    if idle_only:
        units = [u for u in units if u["is_idle"]]
    return sorted(units, key=lambda u: (not u["is_idle"], dist2(u["cell_x"], u["cell_y"], *near), u["actor_id"]))


def _fail(ctx: PlanContext, task: Task, note: str) -> list[dict]:
    ctx.book.finish(task, TaskStatus.FAILED, note, ctx.tick)
    return []


def _done(ctx: PlanContext, task: Task, note: str) -> None:
    ctx.book.finish(task, TaskStatus.DONE, note, ctx.tick)


def _attack_move(u: dict, x: int, y: int) -> dict:
    return {"action": "attack_move", "actor_id": u["actor_id"], "target_x": x, "target_y": y}


def _move(u: dict, x: int, y: int) -> dict:
    return {"action": "move", "actor_id": u["actor_id"], "target_x": x, "target_y": y}


def _enemies_near(obs: dict, x: int, y: int, radius: int) -> list[dict]:
    seen = obs.get("visible_enemies", []) + obs.get("visible_enemy_buildings", [])
    return [e for e in seen if dist2(e["cell_x"], e["cell_y"], x, y) <= radius * radius]


def step_build(task: Task, ctx: PlanContext) -> list[dict]:
    cmd, d = task.command, task.data
    if "item" not in d:
        item = resolve_item(cmd.item or "", ctx.obs.get("available_production", []))
        if item is None:
            return _fail(ctx, task, f"当前无法建造 {cmd.item}（缺少前置建筑或工厂）")
        d.update(item=item, remaining=cmd.count, attempt=0, pending=False, wait=0)
    item = d["item"]
    queue = [p for p in ctx.obs.get("production", []) if p["item"] == item]
    if queue:
        d["pending"], d["wait"] = False, 0
    elif d["pending"]:
        d["wait"] += 1
        if d["wait"] >= MAX_PRODUCTION_WAIT_STEPS:
            return _fail(ctx, task, f"{item} 的生产没有开始（队列被占用或资金不足）")
        return []

    if not is_building_type(item):
        if d["remaining"] > 0:
            n, d["remaining"], d["pending"] = d["remaining"], 0, True
            return [{"action": "train", "item_type": item} for _ in range(n)]
        if not queue:
            _done(ctx, task, f"已生产 {cmd.count} 个 {item}")
        return []

    ready = [p for p in queue if p.get("progress", 0) >= 0.99]
    if ready:
        cands = placement_candidates(item, ctx.obs, ctx.grid)
        if d["attempt"] >= min(len(cands), MAX_PLACEMENT_ATTEMPTS):
            ctx.book.finish(task, TaskStatus.FAILED, f"找不到可以摆放 {item} 的位置", ctx.tick)
            return [{"action": "cancel_production", "item_type": item}]
        x, y = cands[d["attempt"]]
        d["attempt"] += 1
        return [{"action": "place_building", "item_type": item, "target_x": x, "target_y": y}]
    if queue:
        return []
    if d["remaining"] == 0:
        _done(ctx, task, f"已建成 {cmd.count} 座 {item}")
        return []
    d["remaining"] -= 1
    d.update(attempt=0, pending=True, wait=0)
    return [{"action": "build", "item_type": item}]


def step_attack(task: Task, ctx: PlanContext) -> list[dict]:
    cmd, d = task.command, task.data
    if "target" not in d:
        target = resolve_target(ctx, cmd.target)
        if target is None:
            return _fail(ctx, task, f"找不到目标 {cmd.target}")
        x, y, label = target
        free = free_combat_units(ctx, (x, y), cmd.unit_type)
        pick = free if cmd.count == 0 else free[:cmd.count]
        if not pick:
            suffix = f"（{cmd.unit_type}）" if cmd.unit_type else ""
            return _fail(ctx, task, f"没有空闲的作战单位{suffix}")
        d.update(target=(x, y), label=label)
        ctx.book.assign(task, [u["actor_id"] for u in pick])
        task.note = f"{len(pick)} 个单位前往{label}"
        return [_attack_move(u, x, y) for u in pick]

    units = task_units(task, ctx.obs)
    if not units:
        return _fail(ctx, task, "进攻部队已全部阵亡")
    tx, ty = d["target"]
    near = _enemies_near(ctx.obs, tx, ty, CHASE_RADIUS)
    arrived = all(dist2(u["cell_x"], u["cell_y"], tx, ty) <= ARRIVE_RADIUS ** 2 for u in units)
    if arrived and not near and all(u["is_idle"] for u in units):
        _done(ctx, task, f"已抵达{d['label']}，附近没有发现敌人")
        return []
    out = []
    for u in units:
        if not u["is_idle"]:
            continue
        if near:
            e = min(near, key=lambda e: dist2(e["cell_x"], e["cell_y"], u["cell_x"], u["cell_y"]))
            out.append(_attack_move(u, e["cell_x"], e["cell_y"]))
        elif dist2(u["cell_x"], u["cell_y"], tx, ty) > ARRIVE_RADIUS ** 2:
            out.append(_attack_move(u, tx, ty))
    task.note = f"{len(units)} 个单位在{d['label']}方向作战"
    return out


def step_defend(task: Task, ctx: PlanContext) -> list[dict]:
    cmd, d = task.command, task.data
    if "target" not in d:
        target = resolve_target(ctx, cmd.target)
        if target is None:
            return _fail(ctx, task, f"找不到地点 {cmd.target}")
        d.update(target=target[:2], label=target[2])
    tx, ty = d["target"]
    units = task_units(task, ctx.obs)
    deficit = cmd.count - len(units)
    if deficit > 0:
        extra = free_combat_units(ctx, (tx, ty), cmd.unit_type, idle_only=True)[:deficit]
        ctx.book.assign(task, [u["actor_id"] for u in extra])
        units = task_units(task, ctx.obs)
    near = _enemies_near(ctx.obs, tx, ty, CHASE_RADIUS)
    out = []
    for u in units:
        if not u["is_idle"]:
            continue
        if near:
            e = min(near, key=lambda e: dist2(e["cell_x"], e["cell_y"], u["cell_x"], u["cell_y"]))
            out.append(_attack_move(u, e["cell_x"], e["cell_y"]))
        elif dist2(u["cell_x"], u["cell_y"], tx, ty) > DEFEND_RADIUS ** 2:
            out.append(_attack_move(u, tx, ty))
    task.note = f"驻守{d['label']}：{len(units)}/{cmd.count}"
    return out


def step_expand(task: Task, ctx: PlanContext) -> list[dict]:
    cmd, d = task.command, task.data
    if "target" not in d:
        loc = find_location(ctx.locations, cmd.target or "")
        if loc is None:
            return _fail(ctx, task, f"找不到地点 {cmd.target}")
        d.update(target=(loc.x, loc.y), label=loc.name, tries=0, mcv=None, ordered=False, waited=0)
    tx, ty = d["target"]
    units = {u["actor_id"]: u for u in ctx.obs.get("units", [])}
    if d["mcv"] is not None and d["mcv"] not in units:
        yards = [b for b in ctx.obs.get("buildings", []) if b["type"] == "fact"
                 and dist2(b["cell_x"], b["cell_y"], tx, ty) <= 8 ** 2]
        if yards:
            _done(ctx, task, f"已在{d['label']}展开基地")
            return []
        return _fail(ctx, task, "基地车在途中损失")
    if d["mcv"] is None:
        mcvs = [u for u in units.values() if u["type"] == "mcv" and ctx.book.owner_of(u["actor_id"]) is None]
        if mcvs:
            mcv = min(mcvs, key=lambda u: (dist2(u["cell_x"], u["cell_y"], tx, ty), u["actor_id"]))
            d["mcv"] = mcv["actor_id"]
            ctx.book.assign(task, [mcv["actor_id"]])
        elif not d["ordered"]:
            if "mcv" not in ctx.obs.get("available_production", []):
                return _fail(ctx, task, "没有空闲基地车，也无法生产（需要战车工厂）")
            d["ordered"] = True
            task.note = "等待基地车出厂"
            return [{"action": "train", "item_type": "mcv"}]
        else:
            d["waited"] += 1
            if d["waited"] >= MAX_MCV_WAIT_STEPS:
                return _fail(ctx, task, "等待基地车超时")
            return []
    mcv = units[d["mcv"]]
    ox, oy = EXPAND_OFFSETS[min(d["tries"], len(EXPAND_OFFSETS) - 1)]
    sx, sy = tx + ox, ty + oy
    if dist2(mcv["cell_x"], mcv["cell_y"], sx, sy) > 2 ** 2:
        if mcv["is_idle"]:
            task.note = f"基地车前往{d['label']}"
            return [_move(mcv, sx, sy)]
        return []
    if not mcv["is_idle"]:
        return []
    if d["tries"] >= len(EXPAND_OFFSETS):
        return _fail(ctx, task, f"无法在{d['label']}展开")
    d["tries"] += 1
    task.note = f"尝试在{d['label']}展开（第 {d['tries']} 次）"
    return [{"action": "deploy", "actor_id": mcv["actor_id"]}]


def step_harass(task: Task, ctx: PlanContext) -> list[dict]:
    cmd, d = task.command, task.data
    if "victim" not in d:
        victim = resolve_player(ctx, cmd.target)
        if victim is None or victim == ctx.player:
            return _fail(ctx, task, f"找不到骚扰对象 {cmd.target}")
        home = base_point(ctx)
        free = free_combat_units(ctx, home, cmd.unit_type)
        fast = [u for u in free if u["type"] in FAST_TYPES]
        pick = (fast + [u for u in free if u["type"] not in FAST_TYPES])[:cmd.count]
        if not pick:
            return _fail(ctx, task, "没有空闲的作战单位")
        ores = [loc for loc in ctx.locations if loc.kind == "ore"]
        vx, vy = ctx.spawns[victim]
        goal = min(ores, key=lambda o: dist2(o.x, o.y, vx, vy)) if ores else None
        d.update(victim=victim, home=home, goal=(goal.x, goal.y) if goal else (vx, vy))
        ctx.book.assign(task, [u["actor_id"] for u in pick])
    units = task_units(task, ctx.obs)
    hx, hy = d["home"]
    hurt = [u for u in units if u["hp_percent"] < HARASS_RETREAT_HP]
    out = [_move(u, hx, hy) for u in hurt]
    ctx.book.release(task, [u["actor_id"] for u in hurt])
    units = [u for u in units if u["hp_percent"] >= HARASS_RETREAT_HP]
    if not units:
        _done(ctx, task, "骚扰小队已撤回或阵亡")
        return out
    harvs = [e for e in ctx.obs.get("visible_enemies", []) if e["owner"] == d["victim"] and e["type"] == "harv"]
    gx, gy = d["goal"]
    for u in units:
        if harvs:
            h = min(harvs, key=lambda e: dist2(e["cell_x"], e["cell_y"], u["cell_x"], u["cell_y"]))
            if u["is_idle"] or d.get("hunting") != h["actor_id"]:
                out.append({"action": "attack", "actor_id": u["actor_id"], "target_actor_id": h["actor_id"]})
        elif u["is_idle"] and dist2(u["cell_x"], u["cell_y"], gx, gy) > ARRIVE_RADIUS ** 2:
            out.append(_attack_move(u, gx, gy))
    d["hunting"] = harvs[0]["actor_id"] if harvs else None
    task.note = f"{len(units)} 个单位骚扰{ctx.display[d['victim']]}"
    return out


def step_retreat(task: Task, ctx: PlanContext) -> list[dict]:
    cmd = task.command
    if cmd.task_id is not None:
        target = ctx.book.get(cmd.task_id)
        if target is None or target.status != TaskStatus.ACTIVE:
            return _fail(ctx, task, f"任务 #{cmd.task_id} 不存在或已结束")
        targets = [target]
    else:
        targets = [t for t in ctx.book.active() if t.command.kind in ("进攻", "骚扰") and t.id != task.id]
    hx, hy = base_point(ctx)
    freed: list[int] = []
    for t in targets:
        freed += ctx.book.cancel(t.id, ctx.tick)
    _done(ctx, task, f"已撤回 {len(freed)} 个单位")
    return [{"action": "move", "actor_id": a, "target_x": hx, "target_y": hy} for a in freed]


def step_cancel(task: Task, ctx: PlanContext) -> list[dict]:
    target = ctx.book.get(task.command.task_id or 0)
    if target is None or target.status != TaskStatus.ACTIVE or target.id == task.id:
        return _fail(ctx, task, f"任务 #{task.command.task_id} 不存在或已结束")
    freed = ctx.book.cancel(target.id, ctx.tick)
    _done(ctx, task, f"已取消任务 #{target.id}")
    return [{"action": "stop", "actor_id": a} for a in freed]


def step_shout(task: Task, ctx: PlanContext) -> list[dict]:
    _done(ctx, task, "已广播")
    return []


STEPS = {"建造": step_build, "进攻": step_attack, "防守": step_defend, "扩张": step_expand, "骚扰": step_harass,
         "撤退": step_retreat, "取消": step_cancel, "喊话": step_shout}


def step_task(task: Task, ctx: PlanContext) -> list[dict]:
    if task.status != TaskStatus.ACTIVE:
        return []
    return STEPS[task.command.kind](task, ctx)
