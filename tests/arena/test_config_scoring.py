from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from openra_arena.config import ArenaConfig, ScoringConfig, load_arena_config
from openra_arena.coordinator.scoring import PlayerScoreInput, end_condition, rank_players, score_player

YAML = """
engine_dir: /e
slots:
  - {slot: Multi0, display: 红方, kind: external, fallback: persona, persona: rusher}
  - {slot: Multi1, display: 蓝方, persona: economist}
  - {slot: Multi2, display: 绿方, kind: builtin}
timing: {max_game_minutes: 2}
llm: {model: test/model}
"""


def test_load_config_and_derived_fields(tmp_path: Path):
    p = tmp_path / "arena.yaml"
    p.write_text(YAML, encoding="utf-8")
    cfg = load_arena_config(p)
    assert cfg.display == {"Multi0": "红方", "Multi1": "蓝方", "Multi2": "绿方"}
    assert cfg.slot_overrides == (("Multi2", "normal"),)
    assert cfg.timing.max_game_ticks == 3000
    assert cfg.llm.model == "test/model" and cfg.scoring.territory_weight == 100
    assert cfg.llm.base_url == "https://api.x.ai/v1" and cfg.llm.extra_headers == {}


@pytest.mark.parametrize("slots", [
    [{"slot": "Multi0", "display": "红方"}],
    [{"slot": "Multi0", "display": "红方"}, {"slot": "Multi0", "display": "蓝方"}],
    [{"slot": "Multi0", "display": "红方"}, {"slot": "Multi9", "display": "蓝方"}],
    [{"slot": "Multi0", "display": "红方"}, {"slot": "Multi1", "display": "红方"}],
])
def test_invalid_slots_rejected(slots):
    with pytest.raises(ValidationError):
        ArenaConfig.model_validate({"engine_dir": "/e", "slots": slots})


def test_score_formula_matches_spec():
    p = PlayerScoreInput("Multi0", territory=3, army_value=12000, earned=20000, alive=True)
    assert score_player(p, ScoringConfig()) == 300 + 120 + 100


def test_rank_winner_then_alive_by_score_then_survival_time():
    cfg = ScoringConfig()
    players = [
        PlayerScoreInput("Multi0", 0, 0, 0, alive=False, eliminated_tick=9000),
        PlayerScoreInput("Multi1", 1, 100, 0, alive=True),
        PlayerScoreInput("Multi2", 5, 9000, 9000, alive=True),
        PlayerScoreInput("Multi3", 0, 0, 0, alive=False, eliminated_tick=12000),
    ]
    ranked = rank_players(players, cfg)
    assert [r.player for r in ranked] == ["Multi2", "Multi1", "Multi3", "Multi0"]
    assert [r.rank for r in ranked] == [1, 2, 3, 4]
    assert rank_players(players, cfg, winner="Multi1")[0].player == "Multi1"


def test_end_condition():
    assert end_condition(["Multi0", "Multi1"], 100, 45000) is None
    assert end_condition(["Multi1"], 100, 45000) == ("elimination", "Multi1")
    assert end_condition([], 100, 45000) == ("elimination", None)
    assert end_condition(["Multi0", "Multi1"], 45000, 45000) == ("time_limit", None)
