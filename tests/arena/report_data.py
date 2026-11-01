"""Writes a small but complete synthetic match directory for report tests."""

from __future__ import annotations

import json
from pathlib import Path

PLAYERS = ["Multi0", "Multi1", "Multi2", "Multi3"]
DISPLAY = {"Multi0": "红方", "Multi1": "蓝方", "Multi2": "绿方", "Multi3": "黄方"}
LOCATIONS = [
    {"key": "spawn_multi0", "name": "红方基地", "kind": "spawn", "x": 10, "y": 10, "radius": 8},
    {"key": "spawn_multi1", "name": "蓝方基地", "kind": "spawn", "x": 90, "y": 10, "radius": 8},
    {"key": "spawn_multi2", "name": "绿方基地", "kind": "spawn", "x": 10, "y": 90, "radius": 8},
    {"key": "spawn_multi3", "name": "黄方基地", "kind": "spawn", "x": 90, "y": 90, "radius": 8},
    {"key": "center", "name": "中央", "kind": "region", "x": 50, "y": 50, "radius": 12},
]


def _w(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")


def kill(t: int, victim: str, killer: str | None, actor_type: str = "e1", x: int = 50, y: int = 50) -> dict:
    return {"t": t, "type": "actor_killed", "actor_id": t, "actor_type": actor_type, "owner": victim,
            "is_building": actor_type == "fact", "cost": 100, "x": x, "y": y, "killer_id": 1,
            "killer_type": "2tnk" if killer else None, "killer_owner": killer}


def write_match(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "replays").mkdir(exist_ok=True)
    (root / "replays" / "arena.orarep").write_bytes(b"x")
    meta = {
        "match_id": "20261101-200000", "map": "maelstrom.oramap", "end_reason": "elimination", "winner": "Multi0",
        "duration_ticks": 9000, "display": DISPLAY,
        "slots": [{"slot": p, "kind": "persona", "persona": "rusher", "driver": "persona", "observed": True}
                  for p in PLAYERS],
        "ranking": [{"player": p, "rank": i + 1, "score": 100.0 - i, "territory": 3 - min(i, 3), "army_value": 1000,
                     "earned": 5000, "alive": i == 0, "eliminated_tick": None if i == 0 else 9000 - i * 1000}
                    for i, p in enumerate(PLAYERS)],
        "map_size": [100, 100], "locations": LOCATIONS,
    }
    (root / "match.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    events = [{"t": 0, "type": "match_started"}, kill(1500, "Multi1", None, "e1")]  # neutral/self kill: not contact
    events += [kill(2000, "Multi1", "Multi0", "e1", 80, 15)]
    events += [kill(3000 + i * 50, "Multi2" if i % 2 else "Multi3", "Multi3" if i % 2 else "Multi2", "1tnk")
               for i in range(10)]
    events += [kill(6100, "Multi1", "Multi0", "fact", 90, 10), {"t": 6200, "type": "player_lost", "player": "Multi1"}]
    _w(root / "events.jsonl", events)
    _w(root / "samples.jsonl", [{"t": t, "player": p, "observed": True, "army_value": t // 10 * (i + 1),
                                 "earned": t, "territory": i % 3} for t in (0, 750, 1500) for i, p in enumerate(PLAYERS)])
    snaps = [{"kind": "snapshot", "t": t, "owners": {"spawn_multi0": "Multi0", "spawn_multi1": "Multi1",
                                                       "spawn_multi2": "Multi2", "spawn_multi3": "Multi3",
                                                       "center": None if t < 1500 else "contested"}}
             for t in (0, 250, 750, 1500)]
    _w(root / "territory.jsonl", [*snaps, {"kind": "change", "t": 1500, "key": "center", "name": "中央", "old": None,
                                           "new": "contested"}])
    _w(root / "decisions.jsonl", [
        {"t": 250, "player": "Multi0", "source": "persona", "commands": [{"kind": "建造", "item": "weap"}],
         "reason": "先造战车工厂准备出坦克", "feedback": "已接受任务 #1"},
        {"t": 1900, "player": "Multi0", "source": "persona", "commands": [{"kind": "进攻", "target": "蓝方"}] * 2,
         "reason": "蓝方最弱，<b>全军压上</b>", "feedback": "已接受任务 #2、#3"},
        {"t": 2500, "player": "Multi0", "source": "persona", "commands": [], "reason": "", "feedback": ""},
        {"t": 2600, "player": "Multi0", "source": "persona", "commands": [], "reason": "观望", "feedback": ""},
        {"t": 300, "player": "Multi1", "source": "persona_error", "commands": [], "reason": "大模型调用失败",
         "feedback": ""},
    ])
    _w(root / "coordinator.jsonl", [
        {"t": 0, "event": "player_joined", "player": "Multi0", "driver": "persona"},
        {"t": 2100, "event": "shout", "player": "Multi0", "text": "蓝方先走一步"},
        {"t": 4000, "event": "takeover", "player": "Multi2", "enabled": True, "permanent": False},
        {"t": 4500, "event": "takeover", "player": "Multi2", "enabled": False, "permanent": False},
        {"t": 6200, "event": "player_lost", "player": "Multi1"},
    ])
    return root
