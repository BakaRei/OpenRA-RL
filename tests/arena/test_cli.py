from __future__ import annotations

import io
from pathlib import Path

import pytest

from openra_arena.cli import load_or_create_tokens, main, print_connectors
from openra_arena.config import ArenaConfig

YAML = """engine_dir: /e
mcp_port: 9001
slots:
  - {slot: Multi0, display: 红方, kind: external}
  - {slot: Multi1, display: 蓝方}
  - {slot: Multi2, display: 绿方, kind: external}
"""


def test_tokens_command_writes_file_and_prints_urls(tmp_path: Path, capsys):
    cfg_path = tmp_path / "arena.yaml"
    cfg_path.write_text(YAML, encoding="utf-8")
    assert main(["tokens", "--config", str(cfg_path), "--out", str(tmp_path / "t.json")]) == 0
    out = capsys.readouterr().out.splitlines()
    assert len(out) == 2
    assert out[0].startswith("红方（Multi0）连接器地址：http://127.0.0.1:9001/mcp?token=")
    assert out[1].startswith("绿方（Multi2）")


def test_load_or_create_tokens_reuses_and_validates(tmp_path: Path):
    cfg = ArenaConfig.model_validate({"engine_dir": "/e", "slots": [
        {"slot": "Multi0", "display": "红方", "kind": "external"}, {"slot": "Multi1", "display": "蓝方"}]})
    path = tmp_path / "t.json"
    first = load_or_create_tokens(cfg, path)
    again = load_or_create_tokens(cfg, path)
    assert first.slots == ["Multi0"] and again.token_for("Multi0") == first.token_for("Multi0")
    buf = io.StringIO()
    print_connectors(cfg, again, buf)
    assert "mcp?token=" + first.token_for("Multi0") in buf.getvalue()
    cfg2 = ArenaConfig.model_validate({"engine_dir": "/e", "slots": [
        {"slot": "Multi0", "display": "红方", "kind": "external"},
        {"slot": "Multi1", "display": "蓝方", "kind": "external"}]})
    with pytest.raises(SystemExit):
        load_or_create_tokens(cfg2, path)


def test_example_config_loads():
    from openra_arena.config import load_arena_config

    cfg = load_arena_config(Path(__file__).resolve().parents[2] / "configs" / "arena.example.yaml")
    assert [s.kind for s in cfg.slots] == ["external", "persona", "persona", "persona"]
    assert cfg.timing.max_game_ticks == 45000 and cfg.slot_overrides == ()
    assert cfg.mcp_host == "127.0.0.1" and cfg.map_file == "maelstrom.oramap"
    assert cfg.llm.base_url == "https://api.x.ai/v1" and cfg.llm.model == "grok-4.7" and not cfg.llm.api_key
