"""Per-slot invitation texts for the referee bot (游戏人) to relay to each participating Grok Bot.

The connector is localhost-only, so the invitation carries the slot's private connector URL. Files are written
outside the match directory (which gets shared as a report) with mode 0600, and overwritten on every run.
"""

from __future__ import annotations

import os
from pathlib import Path

from openra_arena.config import ArenaConfig
from openra_arena.coordinator.tokens import SlotTokens


def invitation_text(cfg: ArenaConfig, slot: str, url: str, match_id: str) -> str:
    sc = cfg.slot(slot)
    t = cfg.timing
    fallback = "内置模型选手" if sc.fallback == "persona" else "内置 AI"
    return (
        f"【红警 Bot 竞技场】对局 {match_id}，你是{sc.display}（槽位 {slot}），地图 {cfg.map_file}，四方混战。\n"
        f"1. 添加 MCP 连接器，地址：{url}\n"
        "   这个地址只在本机（127.0.0.1）有效，里面是你的专属令牌，不要转发。\n"
        "2. 连上后调用一次 get_situation 看局势；第一次工具调用就算你已就绪。\n"
        f"3. 之后大约每 {t.summary_interval_s:g} 秒调用一次 get_situation，"
        "用 issue_orders 下指令（附一句理由），需要时用 shout 喊话。\n"
        f"4. 请在 {t.wait_players_s:g} 秒内完成第一次调用，否则本局由{fallback}代打。\n"
        f"5. 连续 {t.takeover_after_s:g} 秒没有任何调用会被内置 AI 托管，恢复调用后交还给你。\n"
        "准备好后回复裁判“准备好了”。开赛以工具调用为准，不等文字回复。\n"
    )


def write_invitations(cfg: ArenaConfig, tokens: SlotTokens, match_id: str, out_dir: Path) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    paths: dict[str, Path] = {}
    for sc in cfg.slots:
        if sc.kind != "external":
            continue
        path = out_dir / f"{sc.slot}.txt"
        url = tokens.connector_url(sc.slot, cfg.mcp_host, cfg.mcp_port)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(invitation_text(cfg, sc.slot, url, match_id))
        os.chmod(path, 0o600)
        paths[sc.slot] = path
    return paths
