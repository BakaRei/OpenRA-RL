from __future__ import annotations

import json

import httpx
import pytest

from openra_arena.config import default_llm
from openra_arena.coordinator.llm import LLMError, chat_json, chat_url, extract_json
from openra_arena.coordinator.personas import PERSONAS, system_prompt
from openra_arena.coordinator.players import PersonaPlayer
from openra_env.config import LLMConfig

CFG = LLMConfig(base_url="http://llm.test/v1/chat/completions", api_key="k", model="m", max_retries=1,
                retry_backoff_s=0)


def test_extract_json_handles_fences_and_prose():
    assert extract_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert extract_json('好的：{"reason": "x", "commands": []} 完毕') == {"reason": "x", "commands": []}
    with pytest.raises(LLMError):
        extract_json("没有 JSON")


async def test_chat_json_posts_openai_format_and_retries():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(json.loads(request.content))
        assert request.headers["Authorization"] == "Bearer k"
        if len(calls) == 1:
            return httpx.Response(500)
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"ok": true}'}}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        assert await chat_json(CFG, [{"role": "user", "content": "hi"}], client) == {"ok": True}
    assert calls[1]["model"] == "m" and calls[1]["messages"][0]["content"] == "hi"


async def test_chat_json_gives_up_after_retries():
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(503))) as client:
        with pytest.raises(LLMError):
            await chat_json(CFG, [], client)


async def test_chat_json_defaults_to_xai(monkeypatch):
    monkeypatch.setenv("XAI_API_KEY", "xai-test")
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"ok": 1}'}}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        assert await chat_json(default_llm(), [], client) == {"ok": 1}
    req = seen[0]
    assert str(req.url) == "https://api.x.ai/v1/chat/completions"
    assert req.headers["Authorization"] == "Bearer xai-test" and "HTTP-Referer" not in req.headers
    body = json.loads(req.content)
    assert body["model"] == "grok-4.7" and body["reasoning_effort"] == "low"
    assert chat_url("http://llm.test/v1/chat/completions") == "http://llm.test/v1/chat/completions"


def test_personas_render_prompt():
    assert set(PERSONAS) == {"rusher", "economist", "turtle", "raider", "balanced"}
    text = system_prompt(PERSONAS["rusher"], "红方")
    assert "你是红方" in text and "激进坦克流" in text and '"kind":"扩张"' in text


async def test_persona_player_decides_and_keeps_short_history():
    seen: list[list[dict]] = []

    async def fake_chat(cfg, messages):
        seen.append(messages)
        return {"reason": "先补电", "commands": [{"kind": "建造", "item": "电厂"}] * 7}

    p = PersonaPlayer("Multi0", "红方", PERSONAS["economist"], CFG, chat=fake_chat, history_turns=1)
    d = await p.decide("【时间】00:10", "")
    assert d.ok and d.reason == "先补电" and len(d.commands) == 5
    await p.decide("【时间】00:25", "已接受任务 #1")
    assert seen[1][-1]["content"].endswith("【上一轮反馈】已接受任务 #1")
    assert len(p.history) == 2


async def test_persona_player_reports_llm_failure():
    async def broken(cfg, messages):
        raise LLMError("大模型调用失败：timeout")

    d = await PersonaPlayer("Multi0", "红方", PERSONAS["rusher"], CFG, chat=broken).decide("s", "")
    assert not d.ok and d.commands == [] and "timeout" in d.reason
