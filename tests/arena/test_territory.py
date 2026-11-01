from __future__ import annotations

from openra_arena.executor.locations import NamedLocation
from openra_arena.executor.territory import CONTESTED, TerritoryTracker, control_scores, owner_from_scores

from .fixtures import building, make_obs, unit

LOC_A = NamedLocation("ore_0", "东北矿区", "ore", 50, 10, 5)
LOC_B = NamedLocation("center", "中央", "region", 32, 32, 6)


def test_scores_weight_buildings_and_skip_far_and_husks():
    actors = [building(1, "proc", 50, 11, "Multi1"), unit(2, "e1", 51, 10, "Multi0"), unit(3, "e1", 60, 10, "Multi0"),
              unit(4, "1tnk.husk", 50, 10, "Multi2")]
    assert control_scores(LOC_A, actors) == {"Multi1": 3, "Multi0": 1}


def test_owner_rules():
    assert owner_from_scores({}) is None
    assert owner_from_scores({"Multi0": 2, "Multi1": 1}) == "Multi0"
    assert owner_from_scores({"Multi0": 2, "Multi1": 2}) == CONTESTED


def test_tracker_reports_changes_once():
    t = TerritoryTracker([LOC_A, LOC_B])
    obs = {"Multi0": make_obs(units=[unit(1, "e1", 32, 32)]), "Multi1": make_obs()}
    ch = t.update(750, obs)
    assert [(c.key, c.old, c.new) for c in ch] == [("center", None, "Multi0")]
    assert t.update(1500, obs) == []
    assert t.counts() == {"Multi0": 1}
    obs["Multi1"] = make_obs(buildings=[building(9, "gun", 33, 33, "Multi1")])
    ch = t.update(2250, obs)
    assert [(c.name, c.old, c.new) for c in ch] == [("中央", "Multi0", "Multi1")]
    snap = t.snapshot(2250)
    assert snap == {"t": 2250, "owners": {"ore_0": None, "center": "Multi1"}}
