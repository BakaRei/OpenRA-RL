from __future__ import annotations

from pathlib import Path

import pytest

from openra_arena.report.journey import bot_journey
from openra_arena.report.loader import load_match
from openra_arena.report.moments import key_moments
from tests.arena.report_data import write_match


@pytest.fixture
def data(tmp_path: Path):
    return load_match(write_match(tmp_path / "m"))


def test_key_moments(data):
    ms = key_moments(data)
    kinds = [(m.clock, m.kind) for m in ms]
    assert kinds == [("01:20", "first_contact"), ("01:24", "shout"), ("02:00", "big_battle"),
                     ("02:40", "takeover"), ("04:04", "base_destroyed"), ("04:08", "player_lost")]
    assert ms[0].title == "首次交火：红方击毁蓝方的 e1"
    assert ms[2].title == "绿方、黄方在中央爆发大战，损失 10 个单位/建筑"
    assert ms[4].title == "蓝方的建造厂被红方摧毁"


def test_journey_prefers_busy_decisions_near_moments(data):
    j = bot_journey(data, key_moments(data))
    assert [d["t"] for d in j["Multi0"]] == [250, 1900, 2600]
    assert j["Multi1"] == []


def test_other_building_losses_are_moments(data):
    data.events.append({
        "t": 4000, "type": "actor_killed", "actor_type": "powr", "owner": "Multi2",
        "is_building": True, "x": 10, "y": 90, "killer_owner": "Multi0",
    })
    lost = [m for m in key_moments(data) if m.kind == "building_lost"]
    assert len(lost) == 1 and lost[0].title == "绿方的建筑 powr被红方摧毁"
