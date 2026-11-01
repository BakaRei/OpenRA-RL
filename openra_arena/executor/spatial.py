from __future__ import annotations

import base64
from array import array
from dataclasses import dataclass

(CH_TERRAIN, CH_HEIGHT, CH_RESOURCE, CH_PASSABLE, CH_VISIBILITY,
 CH_OWN_BUILDINGS, CH_OWN_UNITS, CH_ENEMY_BUILDINGS, CH_ENEMY_UNITS) = range(9)


@dataclass(frozen=True)
class SpatialGrid:
    """Float32 H×W×C channels-last tensor from ObservationSerializer.SerializeSpatialMap."""

    width: int
    height: int
    channels: int
    data: array

    @classmethod
    def from_obs(cls, obs: dict) -> SpatialGrid:
        raw = base64.b64decode(obs.get("spatial_map", ""))
        w, h = obs["map_info"]["width"], obs["map_info"]["height"]
        c = obs.get("spatial_channels", 0)
        data = array("f")
        data.frombytes(raw)
        if c <= 0 or len(data) != w * h * c:
            raise ValueError(f"spatial map size {len(data)} != {w}x{h}x{c}")
        return cls(w, h, c, data)

    @classmethod
    def from_cells(cls, width: int, height: int, cells: dict[tuple[int, int, int], float], channels: int = 9) -> SpatialGrid:
        data = array("f", [0.0]) * (width * height * channels)
        for (x, y, ch), v in cells.items():
            data[(y * width + x) * channels + ch] = v
        return cls(width, height, channels, data)

    def at(self, x: int, y: int, ch: int) -> float:
        if not (0 <= x < self.width and 0 <= y < self.height and 0 <= ch < self.channels):
            return 0.0
        return self.data[(y * self.width + x) * self.channels + ch]
