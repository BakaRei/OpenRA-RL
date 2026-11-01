from __future__ import annotations

from pathlib import Path

import pytest

from openra_arena.report.charts import line_chart_svg, series, territory_frames, territory_svg
from openra_arena.report.loader import load_match
from tests.arena.report_data import write_match


@pytest.fixture
def data(tmp_path: Path):
    return load_match(write_match(tmp_path / "m"))


def test_charts_and_frames(data):
    svg = line_chart_svg("兵力价值", series(data, "army_value"), data.display)
    assert svg.count("<polyline") == 4 and "#d9363e" in svg and "红方" in svg
    assert "无数据" in line_chart_svg("空", {"Multi0": []}, {})
    frames = territory_frames(data)
    assert [f["t"] for f in frames] == [0, 750, 1500]
    fsvg = territory_svg(data, frames[-1])
    assert fsvg.count("<circle") == 5 and "中央：争夺中" in fsvg and "00:01" not in fsvg
