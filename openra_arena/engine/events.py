from __future__ import annotations

import json
from pathlib import Path


class EventTail:
    """Incrementally reads complete JSON lines appended to a file."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._offset = 0
        self._partial = b""

    def read_new(self) -> list[dict]:
        if not self.path.exists():
            return []
        with self.path.open("rb") as f:
            f.seek(self._offset)
            chunk = f.read()
        self._offset += len(chunk)
        parts = (self._partial + chunk).split(b"\n")
        self._partial = parts.pop()
        events: list[dict] = []
        for raw in parts:
            line = raw.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line.decode("utf-8")))
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue
        return events


def read_events(path: Path) -> list[dict]:
    return EventTail(path).read_new()
