"""Match coordinator against an in-memory engine: personas, external join/fallback, takeover, end, ranking."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path

from openra_arena.config import ArenaConfig
from openra_arena.coordinator.artifacts import MatchArtifacts
from openra_arena.coordinator.match import NOT_READY, Match
from openra_arena.coordinator.personas import PERSONAS
from openra_arena.coordinator.players import PersonaPlayer
from tests.arena.fixtures import building, make_obs, ore_grid, unit

SPAWNS = {"Multi0": (8, 8), "Multi1": (56, 8), "Multi2": (8, 56), "Multi3": (56, 56)}
FAST = {"summary_interval_s": 0.05, "urgent_cooldown_s": 0.01, "takeover_after_s": 0.3, "wait_players_s": 0.3,
        "executor_interval_s": 0.02, "spatial_every": 3, "max_game_minutes": 10, "sample_interval_ticks": 250}


@dataclass(frozen=True)
class P:
    player: str
    is_external: bool
    win_state: str
    spawn: tuple[int, int]
    taken_over: bool = False


@dataclass(frozen=True)
class Snap:
    tick: int
    phase: str
    players: list[P]


class FakeEngine:
    """Ticks advance 50 per list_players call once started; `lose_at` maps player -> tick it loses."""

    def __init__(self, slots: list[str], builtin: tuple[str, ...] = (), lose_at: dict[str, int] | None = None):
        self.slots, self.builtin, self.lose_at = slots, builtin, lose_at or {}
        self.tick, self.started = 0, False
        self.grid = ore_grid(64, 64, [(14, 14, 2), (50, 14, 2), (14, 50, 2), (50, 50, 2), (32, 32, 3)])
        self.issued: list[tuple[str, list]] = []
        self.takeovers: list[tuple[str, bool]] = []
        self.ended: list[str] = []
        self.observe_calls: list[tuple[str, bool]] = []

    def state(self, p: str) -> str:
        return "lost" if self.tick >= self.lose_at.get(p, 10**9) else "none"

    async def list_players(self):
        if self.started:
            self.tick += 50
        return Snap(self.tick, "playing" if self.started else "waiting",
                    [P(s, s not in self.builtin, self.state(s), SPAWNS[s]) for s in self.slots])

    async def observe(self, player: str, include_spatial: bool = False) -> dict:
        assert player not in self.builtin, "built-in AI slots have no bridge"
        self.observe_calls.append((player, include_spatial))
        x, y = SPAWNS[player]
        enemies = [unit(900, "e1", 9, 9, owner="Multi3")] if player == "Multi0" and "Multi3" in self.builtin else []
        return make_obs(tick=self.tick, units=[unit(1, "e1", x + 1, y)], buildings=[building(2, "fact", x, y, owner=player)],
                        enemies=enemies, grid=self.grid if include_spatial else None, earned=self.tick)

    async def issue(self, player: str, commands: list[dict]) -> int:
        self.issued.append((player, commands))
        return len(commands)

    async def start_match(self):
        self.started = True

    async def end_match(self, reason: str):
        self.ended.append(reason)

    async def set_takeover(self, player: str, enabled: bool):
        self.takeovers.append((player, enabled))


def scripted(reply: dict | None):
    async def chat(cfg, messages):
        if reply is None:
            from openra_arena.coordinator.llm import LLMError
            raise LLMError("down")
        return reply
    return chat


def cfg(tmp_path: Path, slots: list[dict], **timing) -> ArenaConfig:
    return ArenaConfig.model_validate({"engine_dir": str(tmp_path), "slots": slots, "timing": {**FAST, **timing}})


async def until(pred, timeout_s: float = 10.0) -> None:
    async def poll():
        while not pred():
            await asyncio.sleep(0.02)
    await asyncio.wait_for(poll(), timeout_s)


def lines(art: MatchArtifacts, stream: str) -> list[dict]:
    return [json.loads(x) for x in (art.root / f"{stream}.jsonl").read_text(encoding="utf-8").splitlines()]


async def test_four_personas_play_until_elimination(tmp_path: Path):
    c = cfg(tmp_path, [{"slot": f"Multi{i}", "display": d, "persona": p} for i, (d, p) in
                       enumerate(zip(["红方", "蓝方", "绿方", "黄方"], ["rusher", "economist", "turtle", "raider"],
                                     strict=True))])
    eng = FakeEngine(c.display and list(c.display), lose_at={"Multi1": 400, "Multi2": 600, "Multi3": 800})
    art = MatchArtifacts(tmp_path / "m")
    reply = {"reason": "建电厂", "commands": [{"kind": "建造", "item": "powr"}]}
    m = Match(c, eng, art, make_persona=lambda s: PersonaPlayer(s.slot, s.display, PERSONAS[s.persona], c.llm,
                                                                 chat=scripted(reply)))
    meta = await asyncio.wait_for(m.run(), 20)
    art.close()
    assert meta["end_reason"] == "elimination" and meta["winner"] == "Multi0"
    assert [r["player"] for r in meta["ranking"]] == ["Multi0", "Multi3", "Multi2", "Multi1"]
    assert eng.ended == ["elimination"]
    decisions = lines(art, "decisions")
    assert {d["player"] for d in decisions} == {"Multi0", "Multi1", "Multi2", "Multi3"}
    assert all(d["source"] == "persona" and d["reason"] == "建电厂" for d in decisions)
    assert "已接受任务 #1" in decisions[0]["feedback"]
    samples = lines(art, "samples")
    assert {s["player"] for s in samples} == {"Multi0", "Multi1", "Multi2", "Multi3"}
    assert any(not include for _p, include in eng.observe_calls) and any(i for _p, i in eng.observe_calls)
    assert [e["player"] for e in lines(art, "coordinator") if e["event"] == "player_lost"] == ["Multi1", "Multi2",
                                                                                              "Multi3"]
    saved = json.loads(art.meta_path.read_text(encoding="utf-8"))
    assert saved["winner"] == "Multi0" and saved["map_size"] == [64, 64]
    assert {"key": "spawn_multi0", "name": "红方基地"}.items() <= saved["locations"][0].items()


async def test_external_call_before_setup_counts_as_ready(tmp_path: Path):
    c = cfg(tmp_path, [{"slot": "Multi0", "display": "红方", "kind": "external"},
                       {"slot": "Multi1", "display": "蓝方"}])
    m = Match(c, FakeEngine(["Multi0", "Multi1"]), MatchArtifacts(tmp_path / "m"))
    m.touch("Multi0")
    assert await m.situation("Multi0") == NOT_READY
    assert await m.orders("Multi0", [{"kind": "建造", "item": "powr"}], "早") == NOT_READY
    assert m.slots["Multi0"].joined
    m.art.close()


async def test_external_join_orders_and_shout_then_idle_takeover_and_release(tmp_path: Path):
    c = cfg(tmp_path, [{"slot": "Multi0", "display": "红方", "kind": "external"},
                       {"slot": "Multi1", "display": "蓝方", "persona": "balanced"}], max_game_minutes=2)
    eng = FakeEngine(["Multi0", "Multi1"])
    art = MatchArtifacts(tmp_path / "m")
    m = Match(c, eng, art, make_persona=lambda s: PersonaPlayer(s.slot, s.display, PERSONAS[s.persona], c.llm,
                                                                 chat=scripted({"reason": "等", "commands": []})))
    run = asyncio.create_task(m.run())
    await until(lambda: m.slots["Multi0"].executor is not None)
    m.touch("Multi0")
    text = await m.situation("Multi0")
    assert "你是红方" in text and "红方基地" in text
    fb = await m.orders("Multi0", [{"kind": "喊话", "text": "我先发育"}, {"kind": "飞行"}], "试试")
    assert fb.startswith("已接受任务 #1") and "被拒绝" in fb
    assert await m.shout("Multi0", "别打我") == "已喊话"
    assert [t for _t, _who, t in m.shouts] == ["我先发育", "别打我"]
    await until(lambda: ("Multi0", True) in eng.takeovers)
    assert m.slots["Multi0"].executor.paused
    m.touch("Multi0")
    await until(lambda: ("Multi0", False) in eng.takeovers)
    assert not m.slots["Multi0"].executor.paused
    meta = await asyncio.wait_for(run, 20)
    art.close()
    assert meta["end_reason"] == "time_limit" and meta["winner"] is None
    assert any(d["source"] == "external" and d["reason"] == "试试" for d in lines(art, "decisions"))
    assert "Multi0" in "".join(json.dumps(e) for e in lines(art, "coordinator") if e["event"] == "takeover")


async def test_no_show_falls_back_to_builtin_or_persona(tmp_path: Path):
    c = cfg(tmp_path, [{"slot": "Multi0", "display": "红方", "kind": "external", "fallback": "builtin"},
                       {"slot": "Multi1", "display": "蓝方", "kind": "external", "fallback": "persona",
                        "persona": "rusher"},
                       {"slot": "Multi3", "display": "黄方", "kind": "builtin"}],
            max_game_minutes=0.2)
    eng = FakeEngine(["Multi0", "Multi1", "Multi3"], builtin=("Multi3",))
    art = MatchArtifacts(tmp_path / "m")
    m = Match(c, eng, art, make_persona=lambda s: PersonaPlayer(s.slot, s.display, PERSONAS[s.persona], c.llm,
                                                                 chat=scripted({"reason": "冲", "commands": []})))
    meta = await asyncio.wait_for(m.run(), 20)
    art.close()
    assert eng.takeovers == [("Multi0", True)]
    assert {s["slot"]: s["driver"] for s in meta["slots"]} == {"Multi0": "builtin", "Multi1": "persona",
                                                                "Multi3": "builtin"}
    assert "已由内置 AI接管" in await m.situation("Multi0")
    assert all(p != "Multi3" for p, _ in eng.observe_calls)
    assert any(d["player"] == "Multi1" for d in lines(art, "decisions"))
    snaps = [t for t in lines(art, "territory") if t["kind"] == "snapshot"]
    assert snaps and snaps[-1]["owners"]["spawn_multi0"] == "Multi0"


async def test_llm_outage_triggers_takeover_and_engine_crash_ends_match(tmp_path: Path):
    c = cfg(tmp_path, [{"slot": "Multi0", "display": "红方"}, {"slot": "Multi1", "display": "蓝方"}])
    eng = FakeEngine(["Multi0", "Multi1"])
    art = MatchArtifacts(tmp_path / "m")
    alive = {"v": True}
    m = Match(c, eng, art, engine_alive=lambda: alive["v"],
              make_persona=lambda s: PersonaPlayer(s.slot, s.display, PERSONAS[s.persona], c.llm, chat=scripted(None)))
    run = asyncio.create_task(m.run())
    await until(lambda: len(eng.takeovers) >= 2)
    assert set(eng.takeovers) == {("Multi0", True), ("Multi1", True)}
    alive["v"] = False
    meta = await asyncio.wait_for(run, 20)
    art.close()
    assert meta["end_reason"] == "engine_crashed" and eng.ended == []
    assert any(d["source"] == "persona_error" for d in lines(art, "decisions"))
