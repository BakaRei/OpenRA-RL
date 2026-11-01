from __future__ import annotations

import json
from pathlib import Path

from openra_arena.coordinator.tokens import SlotTokens


def test_tokens_roundtrip_with_private_file(tmp_path: Path):
    tokens = SlotTokens.generate(["Multi0", "Multi2"])
    assert tokens.slots == ["Multi0", "Multi2"] and tokens.token_for("Multi0") != tokens.token_for("Multi2")
    path = tmp_path / "tokens.json"
    tokens.save(path)
    assert path.stat().st_mode & 0o777 == 0o600
    again = SlotTokens.load(path)
    assert again.slot_for(tokens.token_for("Multi2")) == "Multi2"
    assert again.slot_for("nope") is None and again.slot_for(None) is None
    assert json.loads(path.read_text())["Multi0"] == tokens.token_for("Multi0")


def test_connector_url():
    t = SlotTokens({"Multi1": "abc"})
    assert t.connector_url("Multi1", "1.2.3.4", 8765) == "http://1.2.3.4:8765/mcp?token=abc"
