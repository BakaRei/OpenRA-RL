from __future__ import annotations

from pathlib import Path

import pytest

from openra_arena.report.loader import load_match
from tests.arena.report_data import write_match


@pytest.fixture
def data(tmp_path: Path):
    return load_match(write_match(tmp_path / "m"))


def test_loader_reads_all_streams(data, tmp_path: Path):
    assert data.players == ["Multi0", "Multi1", "Multi2", "Multi3"]
    assert len(data.events) == 15 and len(data.samples) == 12 and len(data.decisions) == 5
    assert data.name("Multi2") == "绿方" and data.name(None) == "无人"
    assert [r.name for r in data.replays] == ["arena.orarep"]
    with pytest.raises(FileNotFoundError):
        load_match(tmp_path / "nope")
