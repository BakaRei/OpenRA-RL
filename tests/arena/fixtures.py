from __future__ import annotations

import base64

from openra_arena.executor.spatial import CH_RESOURCE, CH_VISIBILITY, SpatialGrid


def unit(actor_id: int, type: str, x: int, y: int, owner: str = "Multi0", idle: bool = True, hp: int = 100,
         can_attack: bool = True) -> dict:
    return {"actor_id": actor_id, "type": type, "cell_x": x, "cell_y": y, "owner": owner, "is_idle": idle,
            "hp_percent": hp, "can_attack": can_attack, "is_building": False, "current_activity": ""}


def building(actor_id: int, type: str, x: int, y: int, owner: str = "Multi0") -> dict:
    return {"actor_id": actor_id, "type": type, "cell_x": x, "cell_y": y, "owner": owner, "hp_percent": 100,
            "is_producing": False, "producing_item": "", "can_produce": []}


def ore_grid(width: int, height: int, blobs: list[tuple[int, int, int]], visible: float = 1.0) -> SpatialGrid:
    cells: dict[tuple[int, int, int], float] = {}
    for x in range(width):
        for y in range(height):
            cells[(x, y, CH_VISIBILITY)] = visible
    for cx, cy, r in blobs:
        for x in range(cx - r, cx + r + 1):
            for y in range(cy - r, cy + r + 1):
                if 0 <= x < width and 0 <= y < height:
                    cells[(x, y, CH_RESOURCE)] = 1.0
    return SpatialGrid.from_cells(width, height, cells)


def encode_grid(grid: SpatialGrid) -> tuple[str, int]:
    return base64.b64encode(grid.data.tobytes()).decode("ascii"), grid.channels


def make_obs(tick: int = 0, cash: int = 5000, units=(), buildings=(), enemies=(), enemy_buildings=(), production=(),
             available=(), width: int = 64, height: int = 64, grid: SpatialGrid | None = None,
             power=(100, 50), earned: int = 0) -> dict:
    obs = {
        "tick": tick,
        "economy": {"cash": cash, "ore": 0, "power_provided": power[0], "power_drained": power[1],
                    "resource_capacity": 0, "harvester_count": sum(1 for u in units if u["type"] == "harv"),
                    "earned": earned, "spent": 0},
        "military": {"army_value": 0, "units_killed": 0, "units_lost": 0, "buildings_killed": 0,
                     "buildings_lost": 0, "kills_cost": 0, "deaths_cost": 0},
        "units": list(units), "buildings": list(buildings),
        "visible_enemies": list(enemies), "visible_enemy_buildings": list(enemy_buildings),
        "production": list(production), "available_production": list(available),
        "map_info": {"width": width, "height": height, "map_name": "test"},
    }
    if grid is not None:
        obs["spatial_map"], obs["spatial_channels"] = encode_grid(grid)
    return obs
