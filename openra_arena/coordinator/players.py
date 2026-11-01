"""Player implementations behind the unified slot interface: summary in, commands (+ reason) out."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from openra_arena.coordinator.llm import LLMError, chat_json
from openra_arena.coordinator.personas import Persona, system_prompt
from openra_env.config import LLMConfig

MAX_COMMANDS_PER_TURN = 5
ChatFn = Callable[[LLMConfig, list[dict]], Awaitable[dict]]


@dataclass(frozen=True)
class Decision:
    commands: list
    reason: str
    ok: bool = True


@dataclass
class PersonaPlayer:
    slot: str
    display: str
    persona: Persona
    llm: LLMConfig
    chat: ChatFn = chat_json
    history_turns: int = 4
    history: list[dict] = field(default_factory=list)
    kind: str = "persona"

    async def decide(self, summary: str, feedback: str) -> Decision:
        user = summary if not feedback else f"{summary}\n【上一轮反馈】{feedback}"
        messages = [
            {"role": "system", "content": system_prompt(self.persona, self.display)},
            *self.history,
            {"role": "user", "content": user},
        ]
        try:
            reply = await self.chat(self.llm, messages)
        except LLMError as e:
            return Decision([], str(e), ok=False)
        commands = reply.get("commands", [])
        if not isinstance(commands, list):
            commands = []
        decision = Decision(commands[:MAX_COMMANDS_PER_TURN], str(reply.get("reason", ""))[:200])
        self.history += [
            {"role": "user", "content": user},
            {"role": "assistant", "content": json.dumps(
                {"reason": decision.reason, "commands": decision.commands}, ensure_ascii=False)},
        ]
        self.history = self.history[-2 * self.history_turns:]
        return decision
