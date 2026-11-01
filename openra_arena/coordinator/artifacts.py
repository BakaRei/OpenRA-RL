"""Match directory layout and append-only JSONL writers. The report layer only reads this directory."""

from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path

STREAMS = ("samples", "territory", "decisions", "coordinator")


def new_match_id(now: datetime | None = None) -> str:
    return (now or datetime.now()).strftime("%Y%m%d-%H%M%S")


class MatchArtifacts:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "replays").mkdir(exist_ok=True)
        self._files = {name: (self.root / f"{name}.jsonl").open("a", encoding="utf-8") for name in STREAMS}

    @classmethod
    def create(cls, output_root: Path, match_id: str) -> MatchArtifacts:
        return cls(output_root / match_id)

    @property
    def events_path(self) -> Path:
        return self.root / "events.jsonl"

    @property
    def meta_path(self) -> Path:
        return self.root / "match.json"

    def append(self, stream: str, record: dict) -> None:
        f = self._files[stream]
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
        f.flush()

    def write_meta(self, meta: dict) -> None:
        tmp = self.meta_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.meta_path)

    def copy_replays(self, replays: list[Path]) -> list[Path]:
        out = []
        for r in replays:
            dest = self.root / "replays" / r.name
            shutil.copy2(r, dest)
            out.append(dest)
        return out

    def close(self) -> None:
        for f in self._files.values():
            f.close()
