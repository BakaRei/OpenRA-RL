from __future__ import annotations

from openra_arena.executor.placement import FOOTPRINTS, MAX_PLACEMENT_ATTEMPTS, placement_candidates
from openra_arena.executor.spatial import CH_PASSABLE, SpatialGrid

from .fixtures import building, make_obs, unit

YARD = building(1, "fact", 20, 20)


def _cells(btype: str, x: int, y: int) -> set[tuple[int, int]]:
    w, h = FOOTPRINTS[btype]
    return {(x + dx, y + dy) for dx in range(w) for dy in range(h)}


def test_no_yard_or_water_building_gives_nothing():
    assert placement_candidates("powr", make_obs()) == []
    assert placement_candidates("syrd", make_obs(buildings=[YARD])) == []


def test_candidates_avoid_padded_footprints_and_sort_by_distance():
    obs = make_obs(buildings=[YARD, building(2, "powr", 25, 20)])
    cands = placement_candidates("powr", obs)
    assert len(cands) >= MAX_PLACEMENT_ATTEMPTS
    blocked = {(x + dx, y + dy) for x, y, t in [(20, 20, "fact"), (25, 20, "powr")]
               for dx in range(-1, FOOTPRINTS[t][0] + 1) for dy in range(-1, FOOTPRINTS[t][1] + 1)}
    for x, y in cands[:MAX_PLACEMENT_ATTEMPTS]:
        assert not (_cells("powr", x, y) & blocked)
    dists = [abs(x - 20) + abs(y - 20) for x, y in cands]
    assert dists == sorted(dists)
    assert cands[0] == (17, 20)


def test_impassable_cells_are_skipped():
    cells = {(x, y, CH_PASSABLE): 1.0 for x in range(64) for y in range(64)}
    for y in range(64):
        cells[(17, y, CH_PASSABLE)] = cells[(18, y, CH_PASSABLE)] = 0.0
    grid = SpatialGrid.from_cells(64, 64, cells)
    cands = placement_candidates("powr", make_obs(buildings=[YARD]), grid)
    assert all(not any(c[0] in (17, 18) for c in _cells("powr", x, y)) for x, y in cands)
    assert cands[0] == (20, 16)


def test_defense_faces_visible_enemy():
    obs = make_obs(buildings=[YARD], enemies=[unit(50, "3tnk", 40, 21, owner="Multi1")])
    assert placement_candidates("gun", obs)[0][0] > 23
