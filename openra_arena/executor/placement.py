"""Building placement candidates, ported from OpenRA-RL's OpenRAEnvironment._find_placement_candidates."""

from __future__ import annotations

from openra_arena.executor.spatial import CH_PASSABLE, SpatialGrid

FOOTPRINTS: dict[str, tuple[int, int]] = {
    "fact": (3, 4), "proc": (3, 4),
    "powr": (2, 3), "apwr": (3, 3),
    "barr": (2, 3), "tent": (2, 3),
    "weap": (3, 3), "fix": (3, 3), "stek": (3, 3),
    "dome": (2, 3), "hpad": (2, 3), "afld": (3, 2),
    "iron": (2, 2), "pdox": (2, 2),
    "mslo": (2, 1), "sam": (2, 1),
    "spen": (3, 3), "syrd": (3, 3), "atek": (2, 3),
    "gun": (1, 1), "ftur": (1, 1), "tsla": (1, 1),
    "agun": (1, 1), "pbox": (1, 1), "hbox": (1, 1), "gap": (1, 1),
}
WATER_BUILDINGS = frozenset({"spen", "syrd"})
DEFENSE_BUILDINGS = frozenset({"gun", "ftur", "tsla", "agun", "pbox", "hbox", "sam", "gap"})
MAX_PLACEMENT_ATTEMPTS = 20


def is_building_type(item: str) -> bool:
    return item in FOOTPRINTS


def _occupied(buildings: list[dict]) -> set[tuple[int, int]]:
    cells: set[tuple[int, int]] = set()
    for b in buildings:
        fw, fh = FOOTPRINTS.get(b["type"], (2, 2))
        for dx in range(-1, fw + 1):
            for dy in range(-1, fh + 1):
                cells.add((b["cell_x"] + dx, b["cell_y"] + dy))
    return cells


def placement_candidates(btype: str, obs: dict, grid: SpatialGrid | None = None,
                         max_radius: int = 15) -> list[tuple[int, int]]:
    if btype in WATER_BUILDINGS:
        return []
    own = obs.get("buildings", [])
    yard = next((b for b in own if b["type"] == "fact"), None)
    if yard is None:
        return []
    cx, cy = yard["cell_x"], yard["cell_y"]
    bw, bh = FOOTPRINTS.get(btype, (2, 2))
    occupied = _occupied(own + obs.get("visible_enemy_buildings", []))
    map_w = obs.get("map_info", {}).get("width", 128)
    map_h = obs.get("map_info", {}).get("height", 128)

    ex = ey = 0.0
    defense = btype in DEFENSE_BUILDINGS
    if defense:
        enemies = obs.get("visible_enemies", []) + obs.get("visible_enemy_buildings", [])
        if enemies:
            ex = sum(e["cell_x"] for e in enemies) / len(enemies) - cx
            ey = sum(e["cell_y"] for e in enemies) / len(enemies) - cy
        else:
            ex, ey = map_w / 2 - cx, map_h / 2 - cy
        mag = max(abs(ex), abs(ey), 1.0)
        ex, ey = ex / mag, ey / mag

    scored: list[tuple[tuple, tuple[int, int]]] = []
    for dx in range(-max_radius, max_radius + 1):
        for dy in range(-max_radius, max_radius + 1):
            dist = abs(dx) + abs(dy)
            if dist < 2 or dist > max_radius:
                continue
            px, py = cx + dx, cy + dy
            if px < 0 or py < 0 or px + bw > map_w or py + bh > map_h:
                continue
            cells = [(px + ox, py + oy) for ox in range(bw) for oy in range(bh)]
            if any(c in occupied for c in cells):
                continue
            if grid is not None and any(grid.at(x, y, CH_PASSABLE) <= 0 for x, y in cells):
                continue
            if defense:
                key = (-(dx * ex + dy * ey), abs(dist - 5), dy, dx)
            else:
                key = (dist, dy, dx)
            scored.append((key, (px, py)))
    scored.sort()
    return [p for _, p in scored]
