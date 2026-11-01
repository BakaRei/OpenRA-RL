from __future__ import annotations

from pathlib import Path

from openra_arena.engine.events import EventTail, read_events


def test_tail_reads_incrementally_and_keeps_partial_lines(tmp_path: Path):
    p = tmp_path / "events.jsonl"
    tail = EventTail(p)
    assert tail.read_new() == []
    p.write_bytes(b'{"t":1,"type":"match_started"}\n{"t":2,"type":"actor_')
    assert [e["type"] for e in tail.read_new()] == ["match_started"]
    with p.open("ab") as f:
        f.write('killed","owner":"Multi1","reason":"时间到"}\nnot json\n'.encode())
    evs = tail.read_new()
    assert len(evs) == 1 and evs[0]["type"] == "actor_killed" and evs[0]["reason"] == "时间到"
    assert len(read_events(p)) == 2
