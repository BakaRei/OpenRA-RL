from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass

from openra_arena.executor.spatial import CH_RESOURCE, SpatialGrid

_SECTORS = ["东", "东南", "南", "西南", "西", "西北", "北", "东北"]
_ORDINALS = ["", "二", "三", "四", "五", "六", "七", "八"]
SPAWN_ORE_RADIUS = 14
MAX_ORE_LOCATIONS = 8


@dataclass(frozen=True)
class NamedLocation:
    key: str
    name: str
    kind: str
    x: int
    y: int
    radius: int


def direction_name(x: int, y: int, width: int, height: int) -> str:
    dx, dy = x - width / 2, y - height / 2
    if abs(dx) < width / 6 and abs(dy) < height / 6:
        return "中央"
    angle = math.degrees(math.atan2(dy, dx)) % 360  # 0 = east, 90 = south (y grows downward)
    return _SECTORS[int(((angle + 22.5) % 360) // 45)]


def ore_clusters(grid: SpatialGrid, min_cells: int = 6) -> list[tuple[int, int, int]]:
    seen: set[tuple[int, int]] = set()
    out: list[tuple[int, int, int]] = []
    for y in range(grid.height):
        for x in range(grid.width):
            if (x, y) in seen or grid.at(x, y, CH_RESOURCE) <= 0:
                continue
            cells = []
            queue = deque([(x, y)])
            seen.add((x, y))
            while queue:
                cx, cy = queue.popleft()
                cells.append((cx, cy))
                for nx in (cx - 1, cx, cx + 1):
                    for ny in (cy - 1, cy, cy + 1):
                        if (nx, ny) not in seen and grid.at(nx, ny, CH_RESOURCE) > 0:
                            seen.add((nx, ny))
                            queue.append((nx, ny))
            if len(cells) >= min_cells:
                mx = round(sum(c[0] for c in cells) / len(cells))
                my = round(sum(c[1] for c in cells) / len(cells))
                out.append((mx, my, len(cells)))
    out.sort(key=lambda c: (-c[2], c[1], c[0]))
    return out


def _dist2(ax: int, ay: int, bx: int, by: int) -> int:
    return (ax - bx) ** 2 + (ay - by) ** 2


def build_named_locations(grid: SpatialGrid, spawns: dict[str, tuple[int, int]],
                          display: dict[str, str]) -> list[NamedLocation]:
    w, h = grid.width, grid.height
    region_r = max(4, min(w, h) // 8)
    locs: list[NamedLocation] = []
    for player in sorted(spawns):
        sx, sy = spawns[player]
        locs.append(NamedLocation(f"spawn_{player.lower()}", f"{display[player]}基地", "spawn", sx, sy, 8))

    used_names: dict[str, int] = {}
    for ore_index, (cx, cy, size) in enumerate(ore_clusters(grid)[:MAX_ORE_LOCATIONS]):
        near = [p for p in sorted(spawns) if _dist2(cx, cy, *spawns[p]) <= SPAWN_ORE_RADIUS ** 2]
        if near:
            owner = min(near, key=lambda p: _dist2(cx, cy, *spawns[p]))
            base = f"{display[owner]}矿区"
        else:
            base = f"{direction_name(cx, cy, w, h)}矿区"
        n = used_names.get(base, 0)
        used_names[base] = n + 1
        name = base + _ORDINALS[min(n, len(_ORDINALS) - 1)]
        radius = max(4, int(math.sqrt(size)) + 2)
        locs.append(NamedLocation(f"ore_{ore_index}", name, "ore", cx, cy, radius))

    regions = [("center", "中央", w // 2, h // 2), ("north", "北部", w // 2, h // 6), ("south", "南部", w // 2, h - h // 6),
               ("east", "东部", w - w // 6, h // 2), ("west", "西部", w // 6, h // 2)]
    for key, name, x, y in regions:
        locs.append(NamedLocation(key, name, "region", x, y, region_r))
    return locs


def nearest_location(locs: list[NamedLocation], x: int, y: int) -> NamedLocation:
    return min(locs, key=lambda loc: (_dist2(x, y, loc.x, loc.y), loc.key))


def find_location(locs: list[NamedLocation], text: str) -> NamedLocation | None:
    t = (text or "").strip()
    if not t:
        return None
    for loc in locs:
        if t == loc.name or t.lower() == loc.key:
            return loc
    matches = [loc for loc in locs if t in loc.name]
    return matches[0] if len(matches) == 1 else None
