"""M3 against the real engine: scripted personas (no LLM key needed), short games, ranking and artifacts."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from openra_arena.config import ArenaConfig
from openra_arena.coordinator.artifacts import MatchArtifacts
from openra_arena.coordinator.match import Match
from openra_arena.coordinator.personas import PERSONAS
from openra_arena.coordinator.players import PersonaPlayer
from openra_arena.engine.events import read_events

pytestmark = pytest.mark.engine


def opening(display: str) -> list[dict]:
    return [
        {"reason": "先展开基地车", "commands": [{"kind": "扩张", "target": f"{display}基地"}]},
        {"reason": "补电", "commands": [{"kind": "建造", "item": "电厂"}]},
        {"reason": "要钱", "commands": [{"kind": "建造", "item": "矿场"}]},
        {"reason": "出兵", "commands": [{"kind": "建造", "item": "兵营"}, {"kind": "建造", "item": "步兵", "count": 5}]},
    ]


def scripted_opening(display: str):
    turns = iter(opening(display))

    async def chat(cfg, messages):
        return next(turns, {"reason": "攒兵", "commands": [{"kind": "建造", "item": "步兵", "count": 2}]})

    return chat


def arena_cfg(tmp_path: Path, slots: list[dict], minutes: int) -> ArenaConfig:
    return ArenaConfig.model_validate({
        "engine_dir": str(tmp_path), "slots": slots,
        "timing": {"summary_interval_s": 10, "takeover_after_s": 45, "wait_players_s": 5, "max_game_minutes": minutes},
    })


def persona_factory(cfg: ArenaConfig):
    return lambda s: PersonaPlayer(s.slot, s.display, PERSONAS[s.persona], cfg.llm, chat=scripted_opening(s.display))


async def test_four_scripted_personas_reach_time_limit(arena_engine, tmp_path: Path):
    _proc, client, spec = arena_engine
    cfg = arena_cfg(tmp_path, [{"slot": f"Multi{i}", "display": d, "persona": p} for i, (d, p) in enumerate(
        zip(["红方", "蓝方", "绿方", "黄方"], ["rusher", "economist", "turtle", "raider"], strict=True))], minutes=3)
    art = MatchArtifacts(tmp_path / "m")
    meta = await asyncio.wait_for(Match(cfg, client, art, make_persona=persona_factory(cfg)).run(), 400)
    art.close()
    assert meta["end_reason"] == "time_limit" and len(meta["ranking"]) == 4
    placed = {e["owner"] for e in read_events(spec.event_log) if e["type"] == "building_placed"}
    assert placed == {"Multi0", "Multi1", "Multi2", "Multi3"}, placed
    decisions = [json.loads(x) for x in (art.root / "decisions.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len({d["player"] for d in decisions if d["source"] == "persona"}) == 4
    assert all(r["territory"] >= 1 for r in meta["ranking"]), meta["ranking"]


async def test_one_persona_three_builtin(mixed_engine, tmp_path: Path):
    _proc, client, _spec = mixed_engine
    cfg = arena_cfg(tmp_path, [{"slot": "Multi0", "display": "红方", "persona": "turtle"},
                               *[{"slot": f"Multi{i}", "display": d, "kind": "builtin"}
                                 for i, d in ((1, "蓝方"), (2, "绿方"), (3, "黄方"))]], minutes=2)
    art = MatchArtifacts(tmp_path / "m")
    meta = await asyncio.wait_for(Match(cfg, client, art, make_persona=persona_factory(cfg)).run(), 300)
    art.close()
    assert meta["end_reason"] == "time_limit"
    observed = {s["slot"]: s["observed"] for s in meta["slots"]}
    assert observed == {"Multi0": True, "Multi1": False, "Multi2": False, "Multi3": False}
