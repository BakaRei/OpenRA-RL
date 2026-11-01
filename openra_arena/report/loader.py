"""Reads a match directory written by MatchArtifacts + the engine event log."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from openra_arena.executor.summary import TICKS_PER_SECOND, game_time

SLOT_COLORS = {"Multi0": "#d9363e", "Multi1": "#2f6fd6", "Multi2": "#2e9e4f", "Multi3": "#d4a017"}


def _jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


@dataclass
class MatchData:
    root: Path
    meta: dict
    events: list[dict] = field(default_factory=list)
    samples: list[dict] = field(default_factory=list)
    territory: list[dict] = field(default_factory=list)
    decisions: list[dict] = field(default_factory=list)
    coordinator: list[dict] = field(default_factory=list)

    @property
    def display(self) -> dict[str, str]:
        return self.meta.get("display", {})

    @property
    def players(self) -> list[str]:
        return [s["slot"] for s in self.meta.get("slots", [])]

    def name(self, player: str | None) -> str:
        return self.display.get(player or "", player or "无人")

    @property
    def replays(self) -> list[Path]:
        return sorted((self.root / "replays").glob("*.orarep"))


def load_match(root: Path) -> MatchData:
    meta_path = root / "match.json"
    if not meta_path.exists():
        raise FileNotFoundError(f"{root} 不是对局目录（缺 match.json）")
    return MatchData(
        root=root,
        meta=json.loads(meta_path.read_text(encoding="utf-8")),
        events=_jsonl(root / "events.jsonl"),
        samples=_jsonl(root / "samples.jsonl"),
        territory=_jsonl(root / "territory.jsonl"),
        decisions=_jsonl(root / "decisions.jsonl"),
        coordinator=_jsonl(root / "coordinator.jsonl"),
    )


def clock(tick: int) -> str:
    return game_time(tick)


__all__ = ["SLOT_COLORS", "TICKS_PER_SECOND", "MatchData", "clock", "load_match"]
