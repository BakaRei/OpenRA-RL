from __future__ import annotations

import stat
from pathlib import Path

from openra_arena.config import ArenaConfig
from openra_arena.coordinator.invitations import write_invitations
from openra_arena.coordinator.tokens import SlotTokens


def test_write_invitations_one_private_file_per_external_slot(tmp_path: Path):
    cfg = ArenaConfig.model_validate({"engine_dir": "/e", "mcp_port": 9001, "slots": [
        {"slot": "Multi0", "display": "红方", "kind": "external", "fallback": "persona"},
        {"slot": "Multi1", "display": "蓝方"},
        {"slot": "Multi2", "display": "绿方", "kind": "external", "fallback": "builtin"}]})
    tokens = SlotTokens.generate(["Multi0", "Multi2"])
    paths = write_invitations(cfg, tokens, "m1", tmp_path / "inv")
    assert sorted(paths) == ["Multi0", "Multi2"]
    red = paths["Multi0"].read_text(encoding="utf-8")
    assert f"http://127.0.0.1:9001/mcp?token={tokens.token_for('Multi0')}" in red
    assert "红方（槽位 Multi0）" in red and "m1" in red and "maelstrom.oramap" in red
    assert "120 秒内" in red and "内置模型选手代打" in red
    green = paths["Multi2"].read_text(encoding="utf-8")
    assert tokens.token_for("Multi0") not in green and "内置 AI代打" in green
    assert stat.S_IMODE(paths["Multi0"].stat().st_mode) == 0o600
