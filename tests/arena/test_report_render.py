from __future__ import annotations

from pathlib import Path

import pytest

from openra_arena.cli import main
from openra_arena.report.loader import load_match
from openra_arena.report.render import build_report
from tests.arena.report_data import write_match


@pytest.fixture
def data(tmp_path: Path):
    return load_match(write_match(tmp_path / "m"))


async def test_build_report_writes_escaped_single_file(data):
    path = await build_report(data.root, None)
    html = path.read_text(encoding="utf-8")
    assert path.name == "report.html"
    assert "红警 Bot 竞技场战报：红方获胜" in html and "模板解说" in html
    assert "&lt;b&gt;全军压上&lt;/b&gt;" in html and "<b>全军压上</b>" not in html
    assert html.count("<svg") == 3 + 3 and "href='replays/arena.orarep'" in html
    assert "<script" not in html and "http" not in html


def test_report_cli_no_llm(data, capsys):
    assert main(["report", str(data.root), "--no-llm"]) == 0
    assert capsys.readouterr().out.strip().endswith("report.html")


async def test_crashed_match_is_flagged(data):
    import json

    meta = json.loads((data.root / "match.json").read_text(encoding="utf-8"))
    meta.update(end_reason="engine_crashed", winner=None)
    (data.root / "match.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    html = (await build_report(data.root, None)).read_text(encoding="utf-8")
    assert "对局异常终止" in html and "红警 Bot 竞技场战报：引擎中断" in html
