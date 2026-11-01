"""End conditions and the time-limit score: territory x100 + army_value x0.01 + earned x0.005."""

from __future__ import annotations

from dataclasses import dataclass

from openra_arena.config import ScoringConfig


@dataclass(frozen=True)
class PlayerScoreInput:
    player: str
    territory: int
    army_value: int
    earned: int
    alive: bool
    eliminated_tick: int | None = None


@dataclass(frozen=True)
class RankedPlayer:
    player: str
    rank: int
    score: float
    territory: int
    army_value: int
    earned: int
    alive: bool
    eliminated_tick: int | None


def score_player(p: PlayerScoreInput, cfg: ScoringConfig) -> float:
    raw = p.territory * cfg.territory_weight + p.army_value * cfg.army_weight + p.earned * cfg.income_weight
    return round(raw, 2)


def rank_players(players: list[PlayerScoreInput], cfg: ScoringConfig, winner: str | None = None) -> list[RankedPlayer]:
    def key(p: PlayerScoreInput) -> tuple:
        if p.player == winner:
            return (0, 0.0, p.player)
        if p.alive:
            return (1, -score_player(p, cfg), p.player)
        return (2, -(p.eliminated_tick or 0), p.player)

    ordered = sorted(players, key=key)
    return [
        RankedPlayer(
            p.player, i + 1, score_player(p, cfg), p.territory, p.army_value, p.earned, p.alive, p.eliminated_tick,
        )
        for i, p in enumerate(ordered)
    ]


def end_condition(alive: list[str], tick: int, max_ticks: int) -> tuple[str, str | None] | None:
    """Returns (reason, winner) when the match should end, else None."""
    if len(alive) <= 1:
        return "elimination", (alive[0] if alive else None)
    if tick >= max_ticks:
        return "time_limit", None
    return None
