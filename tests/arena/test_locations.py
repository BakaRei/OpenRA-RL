from __future__ import annotations

from openra_arena.executor.locations import (
    build_named_locations,
    direction_name,
    find_location,
    nearest_location,
    ore_clusters,
)
from openra_arena.executor.spatial import CH_RESOURCE, SpatialGrid

from .fixtures import make_obs, ore_grid

SPAWNS = {"Multi0": (8, 8), "Multi1": (56, 8), "Multi2": (8, 56), "Multi3": (56, 56)}
DISPLAY = {"Multi0": "红方", "Multi1": "蓝方", "Multi2": "绿方", "Multi3": "黄方"}


def test_grid_roundtrip_from_obs():
    g = ore_grid(16, 8, [(3, 3, 1)])
    back = SpatialGrid.from_obs(make_obs(width=16, height=8, grid=g))
    assert (back.width, back.height, back.channels) == (16, 8, 9)
    assert back.at(3, 3, CH_RESOURCE) == 1.0 and back.at(10, 3, CH_RESOURCE) == 0.0
    assert back.at(-1, 0, CH_RESOURCE) == 0.0


def test_direction_names():
    assert direction_name(32, 32, 64, 64) == "中央"
    assert direction_name(50, 12, 64, 64) == "东北"
    assert direction_name(5, 32, 64, 64) == "西"
    assert direction_name(32, 60, 64, 64) == "南"


def test_ore_clusters_sorted_by_size():
    g = ore_grid(64, 64, [(10, 12, 2), (40, 30, 1)])
    clusters = ore_clusters(g)
    assert clusters[0][:2] == (10, 12) and clusters[0][2] == 25
    assert clusters[1][:2] == (40, 30)


def test_named_locations_are_stable_and_chinese():
    g = ore_grid(64, 64, [(12, 12, 2), (50, 14, 2), (44, 40, 1), (40, 46, 1)])
    locs = build_named_locations(g, SPAWNS, DISPLAY)
    names = [loc.name for loc in locs]
    assert names == [loc.name for loc in build_named_locations(g, SPAWNS, DISPLAY)]
    for n in ["红方基地", "蓝方基地", "绿方基地", "黄方基地", "红方矿区", "蓝方矿区", "中央", "北部", "南部", "东部", "西部"]:
        assert n in names, n
    assert "东南矿区" in names and "东南矿区二" in names
    assert len(set(names)) == len(names)
    assert len({loc.key for loc in locs}) == len(locs)


def test_find_and_nearest():
    g = ore_grid(64, 64, [(12, 12, 2)])
    locs = build_named_locations(g, SPAWNS, DISPLAY)
    assert find_location(locs, "红方基地").kind == "spawn"
    assert find_location(locs, "spawn_multi1").name == "蓝方基地"
    assert find_location(locs, "中央高地") is None
    assert find_location(locs, "红方矿").name == "红方矿区"
    assert nearest_location(locs, 31, 30).name == "中央"
