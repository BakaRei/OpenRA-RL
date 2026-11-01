"""Short engine smoke: lobby gate, StartMatch, scripted think cycles, one takeover and release, time-limit scores.

The chat function is scripted. No XAI_API_KEY and no network calls.
"""

from __future__ import annotations

import asyncio
import json
import time

import pytest

from openra_arena.config import ArenaConfig
from openra_arena.coordinator.artifacts import MatchArtifacts
from openra_arena.coordinator.llm import LLMError
from openra_arena.coordinator.match import Match
from openra_arena.coordinator.personas import PERSONAS
from openra_arena.coordinator.players import PersonaPlayer

pytestmark = pytest.mark.engine

DISPLAYS = ["红方", "蓝方", "绿方", "黄方"]
PERSONA_NAMES = ["rusher", "economist", "turtle", "raider"]


def _cfg(tmp_path) -> ArenaConfig:
    slots = [
        {"slot": f"Multi{i}", "display": DISPLAYS[i], "persona": PERSONA_NAMES[i]}
        for i in range(4)
    ]
    return ArenaConfig.model_validate({
        "engine_dir": str(tmp_path),
        "slots": slots,
        "timing": {
            "summary_interval_s": 3,
            "urgent_cooldown_s": 1,
            "takeover_after_s": 8,
            "wait_players_s": 1,
            "executor_interval_s": 0.5,
            "max_game_minutes": 1,
            "sample_interval_ticks": 250,
        },
    })


def _factory(cfg: ArenaConfig):
    origin: dict[str, float | None] = {"t": None}

    def make(slot):
        async def chat(_llm, _messages):
            if origin["t"] is None:
                origin["t"] = time.monotonic()
            # Multi3 stays silent long enough for the watchdog, then answers again.
            if slot.slot == "Multi3" and time.monotonic() - origin["t"] < 12:
                raise LLMError("silent")
            return {
                "reason": f"{slot.display}先展开基地",
                "commands": [{"kind": "扩张", "target": f"{slot.display}基地"}],
            }

        return PersonaPlayer(slot.slot, slot.display, PERSONAS[slot.persona], cfg.llm, chat=chat)

    return make


async def test_scripted_gate_think_takeover_release_and_time_limit(arena_engine, tmp_path):
    _proc, client, _spec = arena_engine
    before = await client.list_players()
    assert before.phase == "lobby_gate"
    assert [p.player for p in before.players] == ["Multi0", "Multi1", "Multi2", "Multi3"]

    cfg = _cfg(tmp_path)
    art = MatchArtifacts(tmp_path / "m")
    meta = await asyncio.wait_for(Match(cfg, client, art, make_persona=_factory(cfg)).run(), 180)
    art.close()

    assert meta["end_reason"] == "time_limit" and meta["winner"] is None
    assert meta["duration_ticks"] >= cfg.timing.max_game_ticks
    assert len(meta["ranking"]) == 4
    assert all(isinstance(r["score"], (int, float)) for r in meta["ranking"])

    decisions = [json.loads(x) for x in (art.root / "decisions.jsonl").read_text(encoding="utf-8").splitlines()]
    by_player: dict[str, list[str]] = {}
    for d in decisions:
        by_player.setdefault(d["player"], []).append(d["source"])
        assert "reason" in d
    for name in ("Multi0", "Multi1", "Multi2"):
        assert by_player.get(name, []).count("persona") >= 3, by_player
    assert "persona_error" in by_player.get("Multi3", [])
    assert "persona" in by_player.get("Multi3", [])

    takeover = [e for e in _lines(art, "coordinator") if e["event"] == "takeover" and e["player"] == "Multi3"]
    assert [e["enabled"] for e in takeover] == [True, False], takeover


def _lines(art: MatchArtifacts, stream: str) -> list[dict]:
    return [json.loads(x) for x in (art.root / f"{stream}.jsonl").read_text(encoding="utf-8").splitlines()]
