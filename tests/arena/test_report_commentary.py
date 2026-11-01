from __future__ import annotations

from pathlib import Path

import pytest

from openra_arena.report.commentary import build_facts, make_commentary, template_commentary, validate
from openra_arena.report.loader import load_match
from openra_arena.report.moments import key_moments
from openra_env.config import LLMConfig
from tests.arena.report_data import write_match


@pytest.fixture
def data(tmp_path: Path):
    return load_match(write_match(tmp_path / "m"))


def test_commentary_validation_and_fallback(data):
    facts = build_facts(data, key_moments(data))
    assert facts["ranking"][0]["name"] == "红方" and facts["duration"] == "06:00"
    good = ["01:20 红方率先开火。", "02:00 绿黄大战。", "06:00 红方收官。"]
    assert validate(good, facts)
    assert not validate(["03:33 编造的时间。", "第二段"], facts)
    assert not validate(["只有一段"], facts)
    t = template_commentary(facts)
    assert t[0].startswith("本局历时 06:00，以全歼结束。红方拿下第一") and "4. 黄方" in t[2]


async def test_make_commentary_uses_llm_only_when_valid(data):
    facts = build_facts(data, key_moments(data))
    cfg = LLMConfig(api_key="k")

    async def good(c, m):
        return {"paragraphs": ["01:20 开打。", "06:00 结束。"]}

    async def bad(c, m):
        return {"paragraphs": ["07:77 胡说。", "x"]}

    assert await make_commentary(facts, cfg, chat=good) == (["01:20 开打。", "06:00 结束。"], "llm")
    assert (await make_commentary(facts, cfg, chat=bad))[1] == "template"
    assert (await make_commentary(facts, None))[1] == "template"


async def test_missing_key_skips_the_model(data, monkeypatch):
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    facts = build_facts(data, key_moments(data))

    async def boom(_cfg, _messages):
        raise AssertionError("没有密钥时不应调用大模型")

    paragraphs, source = await make_commentary(facts, LLMConfig(api_key=""), chat=boom)
    assert source == "template" and paragraphs[0].startswith("本局历时 06:00")
