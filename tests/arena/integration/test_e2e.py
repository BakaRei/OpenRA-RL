"""M5 end-to-end: `run_match` (engine + coordinator + MCP off) with 4 scripted personas, then the battle report.

Set ARENA_E2E_LLM=1 (and XAI_API_KEY) to use real LLM personas and LLM commentary instead.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from openra_arena.cli import run_match
from openra_arena.config import ArenaConfig
from openra_arena.coordinator.personas import PERSONAS
from openra_arena.coordinator.players import PersonaPlayer
from openra_arena.coordinator.tokens import SlotTokens
from openra_arena.engine.launcher import EngineProcess
from openra_arena.report.render import build_report
from tests.arena.integration.conftest import ENGINE_DIR, _link_ra_content
from tests.arena.integration.test_m3_match import scripted_opening

pytestmark = pytest.mark.engine
REAL_LLM = os.environ.get("ARENA_E2E_LLM") == "1"


async def test_full_match_then_report(tmp_path: Path, monkeypatch):
    # run_match points SupportDir at the match folder. The engine only sees RA mixes there.
    orig_start = EngineProcess.start

    async def start_with_content(self):
        _link_ra_content(self.spec.support_dir)
        await orig_start(self)

    monkeypatch.setattr(EngineProcess, "start", start_with_content)
    cfg = ArenaConfig.model_validate({
        "engine_dir": ENGINE_DIR, "output_root": str(tmp_path / "matches"),
        "map_file": os.environ.get("ARENA_MAP", "maelstrom.oramap"), "grpc_port": 23999,
        "slots": [{"slot": f"Multi{i}", "display": d, "persona": p} for i, (d, p) in enumerate(
            zip(["红方", "蓝方", "绿方", "黄方"], ["rusher", "economist", "turtle", "raider"], strict=True))],
        "timing": {"max_game_minutes": int(os.environ.get("ARENA_E2E_MINUTES", "5")), "summary_interval_s": 10},
    })
    make = None if REAL_LLM else (lambda s: PersonaPlayer(s.slot, s.display, PERSONAS[s.persona], cfg.llm,
                                                          chat=scripted_opening(s.display)))
    meta = await run_match(cfg, SlotTokens({}), make_persona=make)
    assert meta["end_reason"] in ("time_limit", "elimination")
    root = next((tmp_path / "matches").iterdir())
    assert {p.name for p in root.iterdir()} >= {"match.json", "events.jsonl", "samples.jsonl", "territory.jsonl",
                                               "decisions.jsonl", "coordinator.jsonl", "replays"}
    assert list((root / "replays").glob("*.orarep")), "replay not copied"
    html = (await build_report(root, cfg.llm if REAL_LLM else None)).read_text(encoding="utf-8")
    assert "红警 Bot 竞技场战报" in html and html.count("<svg") >= 3
    assert all(cfg.display[p] in html for p in cfg.display)
