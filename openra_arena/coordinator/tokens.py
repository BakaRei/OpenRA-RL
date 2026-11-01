"""Per-slot connector tokens: one secret per external slot, so a bot can only ever control its own slot."""

from __future__ import annotations

import hmac
import json
import os
import secrets
from pathlib import Path


class SlotTokens:
    def __init__(self, tokens: dict[str, str]) -> None:
        self._tokens = dict(tokens)

    @classmethod
    def generate(cls, slots: list[str]) -> SlotTokens:
        return cls({s: secrets.token_urlsafe(24) for s in slots})

    @classmethod
    def load(cls, path: Path) -> SlotTokens:
        return cls(json.loads(path.read_text(encoding="utf-8")))

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(self._tokens, f, indent=2)
        os.chmod(path, 0o600)

    @property
    def slots(self) -> list[str]:
        return list(self._tokens)

    def token_for(self, slot: str) -> str:
        return self._tokens[slot]

    def slot_for(self, token: str | None) -> str | None:
        if not token:
            return None
        for slot, expected in self._tokens.items():
            if hmac.compare_digest(expected.encode(), token.encode()):
                return slot
        return None

    def connector_url(self, slot: str, host: str, port: int) -> str:
        return f"http://{host}:{port}/mcp?token={self.token_for(slot)}"
