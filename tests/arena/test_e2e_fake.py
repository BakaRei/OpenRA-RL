"""Engine-free end-to-end: Match with 4 scripted personas -> match dir -> report.html."""

from __future__ import annotations

import asyncio
from pathlib import Path

from openra_arena.coordinator.artifacts import MatchArtifacts
from openra_arena.coordinator.match import Match
from openra_arena.coordinator.personas import PERSONAS
from openra_arena.coordinator.players import PersonaPlayer
from openra_arena.report.render import build_report
from tests.arena.test_match import FakeEngine, cfg, scripted


async def test_fake_match_produces_report(tmp_path: Path):
    c = cfg(tmp_path, [{"slot": f"Multi{i}", "display": d, "persona": p} for i, (d, p) in
                       enumerate(zip(["红方", "蓝方", "绿方", "黄方"], ["rusher", "economist", "turtle", "raider"],
                                     strict=True))], max_game_minutes=1)
    eng = FakeEngine(["Multi0", "Multi1", "Multi2", "Multi3"])
    art = MatchArtifacts(tmp_path / "m")
    reply = {"reason": "按计划发展", "commands": [{"kind": "喊话", "text": "大家好"}]}
    m = Match(c, eng, art, make_persona=lambda s: PersonaPlayer(s.slot, s.display, PERSONAS[s.persona], c.llm,
                                                                 chat=scripted(reply)))
    meta = await asyncio.wait_for(m.run(), 30)
    art.close()
    assert meta["end_reason"] == "time_limit"
    html = (await build_report(art.root, None)).read_text(encoding="utf-8")
    assert "红警 Bot 竞技场战报：时间到按分数" in html
    assert "喊话：“大家好”" in html and "按计划发展" in html
    assert html.count("class='frame'") == 0 and html.count('class="frame"') >= 2
