from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from openra_arena.executor.locations import NamedLocation

CONTESTED = "contested"
BUILDING_WEIGHT = 3
UNIT_WEIGHT = 1


def control_scores(loc: NamedLocation, actors: list[dict]) -> dict[str, int]:
    scores: Counter[str] = Counter()
    r2 = loc.radius * loc.radius
    for a in actors:
        if a["type"].endswith(".husk"):
            continue
        if (a["cell_x"] - loc.x) ** 2 + (a["cell_y"] - loc.y) ** 2 > r2:
            continue
        scores[a["owner"]] += BUILDING_WEIGHT if a.get("is_building") or "can_produce" in a else UNIT_WEIGHT
    return dict(scores)


def owner_from_scores(scores: dict[str, int]) -> str | None:
    ranked = sorted(scores.items(), key=lambda kv: -kv[1])
    if not ranked or ranked[0][1] <= 0:
        return None
    if len(ranked) > 1 and ranked[1][1] == ranked[0][1]:
        return CONTESTED
    return ranked[0][0]


@dataclass(frozen=True)
class TerritoryChange:
    tick: int
    key: str
    name: str
    old: str | None
    new: str | None


class TerritoryTracker:
    def __init__(self, locations: list[NamedLocation]) -> None:
        self.locations = locations
        self.owners: dict[str, str | None] = {loc.key: None for loc in locations}

    def update(self, tick: int, obs_by_player: dict[str, dict]) -> list[TerritoryChange]:
        actors: list[dict] = []
        for obs in obs_by_player.values():
            actors.extend(obs.get("units", []))
            actors.extend(obs.get("buildings", []))
        changes = []
        for loc in self.locations:
            new = owner_from_scores(control_scores(loc, actors))
            old = self.owners[loc.key]
            if new != old:
                self.owners[loc.key] = new
                changes.append(TerritoryChange(tick, loc.key, loc.name, old, new))
        return changes

    def counts(self) -> dict[str, int]:
        c = Counter(o for o in self.owners.values() if o and o != CONTESTED)
        return dict(c)

    def snapshot(self, tick: int) -> dict:
        return {"t": tick, "owners": dict(self.owners)}
