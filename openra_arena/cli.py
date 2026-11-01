"""openra-arena command line: `run` a match, print connector `tokens`, render a `report`."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from openra_arena.config import ArenaConfig, default_llm, load_arena_config
from openra_arena.coordinator.tokens import SlotTokens


def external_slots(cfg: ArenaConfig) -> list[str]:
    return [s.slot for s in cfg.slots if s.kind == "external"]


def load_or_create_tokens(cfg: ArenaConfig, path: Path | None) -> SlotTokens:
    if path is not None and path.exists():
        tokens = SlotTokens.load(path)
        missing = set(external_slots(cfg)) - set(tokens.slots)
        if missing:
            raise SystemExit(f"令牌文件缺少槽位：{sorted(missing)}")
        return tokens
    tokens = SlotTokens.generate(external_slots(cfg))
    if path is not None:
        tokens.save(path)
    return tokens


def print_connectors(cfg: ArenaConfig, tokens: SlotTokens, out=None) -> None:
    out = out or sys.stdout
    for slot in external_slots(cfg):
        url = tokens.connector_url(slot, cfg.mcp_host, cfg.mcp_port)
        print(f"{cfg.slot(slot).display}（{slot}）连接器地址：{url}", file=out)


async def run_match(cfg: ArenaConfig, tokens: SlotTokens, make_persona=None) -> dict:
    import uvicorn

    from openra_arena.coordinator.artifacts import MatchArtifacts, new_match_id
    from openra_arena.coordinator.invitations import write_invitations
    from openra_arena.coordinator.match import Match
    from openra_arena.coordinator.mcp_connector import build_app, build_mcp_server
    from openra_arena.engine.client import ArenaEngineClient
    from openra_arena.engine.launcher import EngineLaunchSpec, EngineProcess

    art = MatchArtifacts.create(cfg.output_root, new_match_id())
    spec = EngineLaunchSpec(
        engine_dir=cfg.engine_dir, support_dir=art.root / "support", map_file=cfg.map_file,
        slots=tuple(s.slot for s in cfg.slots), grpc_port=cfg.grpc_port,
        event_log=art.events_path, slot_overrides=cfg.slot_overrides,
    )
    proc = EngineProcess(spec)
    await proc.start()
    server = None
    client = None
    serve_task = None
    try:
        # The connector comes up before the engine finishes loading, so invited bots can connect early
        # (calls before setup get NOT_READY but already count as "joined").
        client = ArenaEngineClient(f"127.0.0.1:{cfg.grpc_port}", timeout_s=15)
        match = Match(cfg, client, art, make_persona=make_persona, engine_alive=lambda: proc.returncode is None)
        if external_slots(cfg):
            app = build_app(build_mcp_server(match, tokens, cfg.mcp_host, cfg.mcp_port), tokens)
            server = uvicorn.Server(uvicorn.Config(app, host=cfg.mcp_host, port=cfg.mcp_port, log_level="warning"))
            serve_task = asyncio.create_task(server.serve())
            print_connectors(cfg, tokens)
            inv = write_invitations(cfg, tokens, art.root.name, cfg.output_root / "invitations")
            print(f"邀请文件（交给裁判 Bot 转发）：{', '.join(str(p) for p in inv.values())}", flush=True)
        print(f"对局目录：{art.root}", flush=True)
        await proc.wait_port(timeout_s=180)
        await client.wait_ready(len(spec.slots) - len(spec.slot_overrides), timeout_s=180)
        meta = await match.run()
    finally:
        if client is not None:
            await client.close()
        if server is not None:
            server.should_exit = True
            if serve_task is not None:
                await serve_task
        await proc.stop()
        art.copy_replays(proc.find_replays())
        art.close()
    return meta


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="openra-arena")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="跑一局")
    r.add_argument("--config", type=Path, required=True)
    r.add_argument("--tokens", type=Path, default=None, help="令牌文件；不存在则生成并保存")
    t = sub.add_parser("tokens", help="生成外部槽位令牌并打印连接器地址")
    t.add_argument("--config", type=Path, required=True)
    t.add_argument("--out", type=Path, required=True)
    rp = sub.add_parser("report", help="为一个对局目录生成 report.html")
    rp.add_argument("match_dir", type=Path)
    rp.add_argument("--config", type=Path, default=None, help="读取其中的 llm 配置")
    rp.add_argument("--no-llm", action="store_true", help="只用模板解说")
    args = ap.parse_args(argv)

    if args.cmd == "report":
        from openra_arena.report.render import build_report

        llm = None if args.no_llm else (load_arena_config(args.config).llm if args.config else default_llm())
        print(f"战报：{asyncio.run(build_report(args.match_dir, llm))}")
        return 0
    cfg = load_arena_config(args.config)
    if args.cmd == "tokens":
        tokens = SlotTokens.generate(external_slots(cfg))
        tokens.save(args.out)
        print_connectors(cfg, tokens)
        return 0
    meta = asyncio.run(run_match(cfg, load_or_create_tokens(cfg, args.tokens)))
    ranking = "，".join(f"{r['rank']}. {cfg.display[r['player']]}（{r['score']}）" for r in meta["ranking"])
    print(f"结束：{meta['end_reason']}；排名：{ranking}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
