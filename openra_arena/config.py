"""Arena match configuration (YAML -> pydantic)."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator

from openra_env.config import LLMConfig

SLOT_NAMES = ("Multi0", "Multi1", "Multi2", "Multi3")

# Persona players and commentary default to xAI Grok (OpenAI-compatible). The key is read from $XAI_API_KEY
# at call time (coordinator/llm.py) and is never written to config files.
XAI_BASE_URL = "https://api.x.ai/v1"
XAI_DEFAULT_MODEL = "grok-4.7"


def default_llm(**overrides) -> LLMConfig:
    """LLMConfig with arena defaults: xAI endpoint, no OpenRouter headers, short replies, low reasoning effort."""
    base = {
        "base_url": XAI_BASE_URL,
        "model": XAI_DEFAULT_MODEL,
        "max_tokens": 800,
        "max_retries": 2,
        "retry_backoff_s": 3,
        "reasoning_effort": "low",
        "extra_headers": {},
    }
    return LLMConfig(**{**base, **overrides})


class SlotConfig(BaseModel):
    slot: str
    display: str
    kind: Literal["persona", "external", "builtin"] = "persona"
    persona: str = "balanced"
    fallback: Literal["persona", "builtin"] = "builtin"


class TimingConfig(BaseModel):
    summary_interval_s: float = 15.0
    urgent_cooldown_s: float = 3.0
    takeover_after_s: float = 60.0
    wait_players_s: float = 120.0
    executor_interval_s: float = 1.0
    spatial_every: int = 5
    max_game_minutes: float = 30.0
    sample_interval_ticks: int = 750
    ticks_per_second: int = 25

    @property
    def max_game_ticks(self) -> int:
        return int(self.max_game_minutes * 60 * self.ticks_per_second)


class ScoringConfig(BaseModel):
    territory_weight: float = 100.0
    army_weight: float = 0.01
    income_weight: float = 0.005


class ArenaConfig(BaseModel):
    engine_dir: Path
    output_root: Path = Path("matches")
    map_file: str = "maelstrom.oramap"
    grpc_port: int = 19999
    mcp_host: str = "127.0.0.1"
    mcp_port: int = 8765
    slots: list[SlotConfig]
    timing: TimingConfig = Field(default_factory=TimingConfig)
    scoring: ScoringConfig = Field(default_factory=ScoringConfig)
    llm: LLMConfig = Field(default_factory=default_llm)

    @field_validator("llm", mode="before")
    @classmethod
    def _llm_defaults(cls, v):
        # A partial `llm:` block overrides the arena defaults, not openra_env's OpenRouter defaults.
        return default_llm(**v) if isinstance(v, dict) else v

    @model_validator(mode="after")
    def _check_slots(self) -> ArenaConfig:
        names = [s.slot for s in self.slots]
        if not 2 <= len(names) <= 4:
            raise ValueError("slots 需要 2 到 4 个")
        if len(set(names)) != len(names) or any(n not in SLOT_NAMES for n in names):
            raise ValueError(f"slot 必须是 {SLOT_NAMES} 中互不重复的值")
        displays = [s.display for s in self.slots]
        if len(set(displays)) != len(displays):
            raise ValueError("display 不能重复")
        return self

    def slot(self, name: str) -> SlotConfig:
        return next(s for s in self.slots if s.slot == name)

    @property
    def display(self) -> dict[str, str]:
        return {s.slot: s.display for s in self.slots}

    @property
    def slot_overrides(self) -> tuple[tuple[str, str], ...]:
        return tuple((s.slot, "normal") for s in self.slots if s.kind == "builtin")


def load_arena_config(path: str | Path) -> ArenaConfig:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    return ArenaConfig.model_validate(data)
