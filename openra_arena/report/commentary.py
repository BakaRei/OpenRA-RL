"""Match commentary: LLM over verified facts, with a deterministic template fallback."""

from __future__ import annotations

import json
import os
import re
from collections.abc import Awaitable, Callable

from openra_arena.coordinator.llm import API_KEY_ENV, LLMError, chat_json
from openra_arena.report.loader import MatchData, clock
from openra_arena.report.moments import Moment
from openra_env.config import LLMConfig

_TIME = re.compile(r"\b\d{2}:\d{2}\b")
REASONS = {"elimination": "全歼", "time_limit": "时间到按分数", "engine_crashed": "引擎中断", "aborted": "中止"}


def build_facts(data: MatchData, moments: list[Moment]) -> dict:
    meta = data.meta
    return {
        "end_reason": REASONS.get(meta.get("end_reason", ""), meta.get("end_reason", "")),
        "duration": clock(meta.get("duration_ticks", 0)),
        "ranking": [{"rank": r["rank"], "name": data.name(r["player"]), "score": r["score"],
                     "alive": r["alive"]} for r in meta.get("ranking", [])],
        "moments": [{"time": m.clock, "what": m.title} for m in moments[:20]],
    }


def allowed_times(facts: dict) -> set[str]:
    return {m["time"] for m in facts["moments"]} | {facts["duration"], "00:00"}


def validate(paragraphs: list[str], facts: dict) -> bool:
    if not 2 <= len(paragraphs) <= 5 or not all(isinstance(p, str) and p.strip() for p in paragraphs):
        return False
    ok_times = allowed_times(facts)
    return all(t in ok_times for p in paragraphs for t in _TIME.findall(p))


def template_commentary(facts: dict) -> list[str]:
    rk = facts["ranking"]
    head = f"本局历时 {facts['duration']}，以{facts['end_reason']}结束。"
    if rk:
        head += f"{rk[0]['name']}拿下第一（{rk[0]['score']} 分）。"
    body = "；".join(f"{m['time']} {m['what']}" for m in facts["moments"][:6]) or "全场没有发生大规模交火"
    tail = "最终排名：" + "，".join(f"{r['rank']}. {r['name']}" for r in rk) + "。"
    return [head, f"关键进程：{body}。", tail]


PROMPT = """你是红警比赛解说。只能使用下面给出的事实，不许编造时间、选手或事件。
用 3 段中文写一篇 200 字左右的赛后解说，时间写成 mm:ss，只能引用事实里出现过的时间。
回复 JSON：{{"paragraphs": ["...", "...", "..."]}}
事实：{facts}"""


def llm_available(llm: LLMConfig | None) -> bool:
    """True when a key is configured. Commentary is omitted (template) otherwise."""
    if llm is None:
        return False
    return bool(llm.api_key or os.environ.get(API_KEY_ENV, ""))


async def make_commentary(
    facts: dict, llm: LLMConfig | None,
    chat: Callable[[LLMConfig, list[dict]], Awaitable[dict]] = chat_json,
) -> tuple[list[str], str]:
    """Returns (paragraphs, source) where source is 'llm' or 'template'.

    No API key (argument or XAI_API_KEY) skips the model entirely so the page still renders.
    """
    if not llm_available(llm):
        return template_commentary(facts), "template"
    assert llm is not None
    try:
        reply = await chat(llm, [{
            "role": "user",
            "content": PROMPT.format(facts=json.dumps(facts, ensure_ascii=False)),
        }])
    except LLMError:
        return template_commentary(facts), "template"
    paragraphs = reply.get("paragraphs") if isinstance(reply, dict) else None
    if isinstance(paragraphs, list) and validate(paragraphs, facts):
        return [str(p) for p in paragraphs], "llm"
    return template_commentary(facts), "template"
