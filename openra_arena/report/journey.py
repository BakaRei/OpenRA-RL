"""Bot 心路历程: the few decisions per player that best explain how its game went."""

from __future__ import annotations

from openra_arena.report.loader import MatchData
from openra_arena.report.moments import Moment

NEAR_MOMENT_TICKS = 750


def decision_score(d: dict, moments: list[Moment]) -> float:
    score = float(min(len(d.get("commands") or []), 5))
    if len(d.get("reason") or "") >= 8:
        score += 1
    if any(d["player"] in m.players and 0 <= m.t - d["t"] <= NEAR_MOMENT_TICKS for m in moments):
        score += 3
    return score


def bot_journey(data: MatchData, moments: list[Moment], per_player: int = 3) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for p in data.players:
        ds = [d for d in data.decisions
              if d.get("player") == p and d.get("source") in ("persona", "external")
              and (d.get("commands") or d.get("reason"))]
        best = sorted(ds, key=lambda d: (-decision_score(d, moments), d["t"]))[:per_player]
        out[p] = sorted(best, key=lambda d: d["t"])
    return out
