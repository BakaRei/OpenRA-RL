"""Minimal OpenAI-compatible chat client that returns a JSON object."""

from __future__ import annotations

import asyncio
import json
import os
import re

import httpx

from openra_env.config import LLMConfig

API_KEY_ENV = "XAI_API_KEY"
_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.DOTALL)


class LLMError(RuntimeError):
    pass


def extract_json(text: str) -> dict:
    s = _FENCE.sub("", text.strip())
    start, end = s.find("{"), s.rfind("}")
    if start < 0 or end <= start:
        raise LLMError(f"回复里没有 JSON 对象：{text[:80]}")
    try:
        value = json.loads(s[start:end + 1])
    except json.JSONDecodeError as e:
        raise LLMError(f"JSON 解析失败：{e}") from None
    if not isinstance(value, dict):
        raise LLMError("JSON 顶层必须是对象")
    return value


def chat_url(base_url: str) -> str:
    """Accepts an API root (https://api.x.ai/v1) or a full .../chat/completions URL."""
    url = base_url.rstrip("/")
    return url if url.endswith("/chat/completions") else url + "/chat/completions"


async def chat_json(cfg: LLMConfig, messages: list[dict], client: httpx.AsyncClient | None = None) -> dict:
    key = cfg.api_key or os.environ.get(API_KEY_ENV, "")
    headers = {"Content-Type": "application/json", **cfg.extra_headers}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    body: dict = {"model": cfg.model, "messages": messages, "max_tokens": cfg.max_tokens}
    if cfg.temperature is not None:
        body["temperature"] = cfg.temperature
    if cfg.reasoning_effort:
        body["reasoning_effort"] = cfg.reasoning_effort
    own = client is None
    http = client or httpx.AsyncClient(timeout=cfg.request_timeout_s)
    last: Exception | None = None
    try:
        for attempt in range(cfg.max_retries + 1):
            try:
                resp = await http.post(chat_url(cfg.base_url), json=body, headers=headers)
                resp.raise_for_status()
                return extract_json(resp.json()["choices"][0]["message"]["content"] or "")
            except (httpx.HTTPError, KeyError, IndexError, LLMError) as e:
                last = e
                if attempt < cfg.max_retries:
                    await asyncio.sleep(cfg.retry_backoff_s * (attempt + 1))
        raise LLMError(f"大模型调用失败：{last}")
    finally:
        if own:
            await http.aclose()
