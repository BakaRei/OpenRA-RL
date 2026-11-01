from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from openra_arena.coordinator.artifacts import MatchArtifacts, new_match_id


def test_streams_meta_and_replays(tmp_path: Path):
    art = MatchArtifacts.create(tmp_path, new_match_id(datetime(2026, 11, 1, 20, 5, 9)))
    assert art.root == tmp_path / "20261101-200509"
    art.append("decisions", {"t": 10, "player": "Multi0", "reason": "先发展经济"})
    art.append("decisions", {"t": 20, "player": "Multi1", "reason": "进攻"})
    art.write_meta({"result": {"winner": None}})
    rep = tmp_path / "x.orarep"
    rep.write_bytes(b"replay")
    copied = art.copy_replays([rep])
    art.close()
    lines = (art.root / "decisions.jsonl").read_text(encoding="utf-8").splitlines()
    assert [json.loads(x)["t"] for x in lines] == [10, 20]
    assert "先发展经济" in lines[0]
    assert json.loads(art.meta_path.read_text(encoding="utf-8")) == {"result": {"winner": None}}
    assert copied[0].read_bytes() == b"replay"
    assert art.events_path == art.root / "events.jsonl"
    assert {p.name for p in art.root.iterdir()} >= {"samples.jsonl", "territory.jsonl", "coordinator.jsonl", "replays"}
