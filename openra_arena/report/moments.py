"""Key moments mined from engine events and coordinator logs."""

from __future__ import annotations

from dataclasses import dataclass

from openra_arena.report.loader import MatchData, clock

BATTLE_WINDOW_TICKS = 750
BIG_BATTLE_KILLS = 8


@dataclass(frozen=True)
class Moment:
    t: int
    kind: str  # first_contact | big_battle | base_destroyed | building_lost | player_lost | shout | takeover | fallback
    title: str
    players: tuple[str, ...] = ()

    @property
    def clock(self) -> str:
        return clock(self.t)


def _pvp_kills(data: MatchData) -> list[dict]:
    players = set(data.players)
    return [e for e in data.events
            if e.get("type") == "actor_killed" and e.get("owner") in players
            and e.get("killer_owner") in players and e["owner"] != e["killer_owner"]]


def _nearest_name(data: MatchData, x: float, y: float) -> str:
    locs = data.meta.get("locations", [])
    if not locs:
        return "战场"
    return min(locs, key=lambda loc: (loc["x"] - x) ** 2 + (loc["y"] - y) ** 2)["name"]


def big_battles(data: MatchData) -> list[Moment]:
    buckets: dict[int, list[dict]] = {}
    for e in _pvp_kills(data):
        buckets.setdefault(e["t"] // BATTLE_WINDOW_TICKS, []).append(e)
    hot = sorted(b for b, es in buckets.items() if len(es) >= BIG_BATTLE_KILLS)
    merged: list[list[int]] = []
    for b in hot:
        if merged and b == merged[-1][-1] + 1:
            merged[-1].append(b)
        else:
            merged.append([b])
    out = []
    for run in merged:
        es = [e for b in run for e in buckets[b]]
        sides = tuple(sorted({e["owner"] for e in es} | {e["killer_owner"] for e in es}))
        where = _nearest_name(data, sum(e["x"] for e in es) / len(es), sum(e["y"] for e in es) / len(es))
        names = "、".join(data.name(p) for p in sides)
        out.append(Moment(es[0]["t"], "big_battle", f"{names}在{where}爆发大战，损失 {len(es)} 个单位/建筑", sides))
    return out


def _building_moments(data: MatchData) -> list[Moment]:
    players = set(data.players)
    moments: list[Moment] = []
    for e in data.events:
        if e.get("type") != "actor_killed" or e.get("owner") not in players:
            continue
        is_yard = e.get("actor_type") == "fact"
        if not is_yard and not e.get("is_building"):
            continue
        killer = e.get("killer_owner")
        by = f"被{data.name(killer)}" if killer in players else ""
        what = "建造厂" if is_yard else f"建筑 {e.get('actor_type', '')}"
        kind = "base_destroyed" if is_yard else "building_lost"
        involved = tuple(p for p in (e["owner"], killer) if p in players)
        moments.append(Moment(e["t"], kind, f"{data.name(e['owner'])}的{what}{by}摧毁", involved))
    return moments


def key_moments(data: MatchData) -> list[Moment]:
    moments: list[Moment] = []
    kills = sorted(_pvp_kills(data), key=lambda e: e["t"])
    if kills:
        k = kills[0]
        moments.append(Moment(
            k["t"], "first_contact",
            f"首次交火：{data.name(k['killer_owner'])}击毁{data.name(k['owner'])}的 {k['actor_type']}",
            (k["killer_owner"], k["owner"]),
        ))
    moments += big_battles(data)
    moments += _building_moments(data)
    lost_seen: set[str] = set()
    for src in (data.events, data.coordinator):
        for e in src:
            if (e.get("type") or e.get("event")) == "player_lost" and e.get("player") in data.players \
                    and e["player"] not in lost_seen:
                lost_seen.add(e["player"])
                moments.append(Moment(e["t"], "player_lost", f"{data.name(e['player'])}出局", (e["player"],)))
    for e in data.coordinator:
        ev, p = e.get("event"), e.get("player")
        if ev == "shout":
            moments.append(Moment(e["t"], "shout", f"{data.name(p)}喊话：“{e.get('text', '')}”", (p,)))
        elif ev == "takeover" and e.get("enabled"):
            moments.append(Moment(e["t"], "takeover", f"{data.name(p)}失联，内置 AI 接管", (p,)))
        elif ev == "fallback":
            who = "内置 AI" if e.get("driver") == "builtin" else "内置角色"
            moments.append(Moment(e["t"], "fallback", f"{data.name(p)}未就绪，由{who}代打", (p,)))
    return sorted(moments, key=lambda m: (m.t, m.kind))
