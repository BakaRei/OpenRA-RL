"""MCP connector for external bots (e.g. Grok Bot). The token picks the slot; tools never take a player argument.

Pinned to mcp>=1.10,<2 (FastMCP import path, streamable HTTP, stateless_http).
Listens on 127.0.0.1 by default: competing Grok Bots share this machine.
"""

from __future__ import annotations

from typing import Any, Protocol
from urllib.parse import parse_qs

from mcp.server.fastmcp import Context, FastMCP

from openra_arena.coordinator.tokens import SlotTokens


class ArenaGateway(Protocol):
    def touch(self, slot: str) -> None: ...

    async def situation(self, slot: str) -> str: ...

    async def orders(self, slot: str, commands: list[dict], reason: str) -> str: ...

    async def shout(self, slot: str, text: str) -> str: ...


def token_from_scope(scope: dict) -> str | None:
    for name, value in scope.get("headers", []):
        if name == b"authorization":
            text = value.decode("latin-1")
            if text.lower().startswith("bearer "):
                return text[7:].strip()
    query = parse_qs(scope.get("query_string", b"").decode("latin-1"))
    return query.get("token", [None])[0]


def _slot(ctx: Context, tokens: SlotTokens) -> str:
    request = ctx.request_context.request
    slot = tokens.slot_for(token_from_scope(request.scope)) if request is not None else None
    if slot is None:
        raise PermissionError("无效的连接令牌")
    return slot


def build_mcp_server(gateway: ArenaGateway, tokens: SlotTokens, host: str = "127.0.0.1", port: int = 8765) -> FastMCP:
    mcp = FastMCP("openra-arena", host=host, port=port, stateless_http=True, json_response=True)

    @mcp.tool()
    async def get_situation(ctx: Context) -> str:
        """看局势：返回你这一方的局势摘要（时间、经济、兵力、敌情、任务、最近事件、地点名）。第一次调用即表示你已就绪。"""
        slot = _slot(ctx, tokens)
        gateway.touch(slot)
        return await gateway.situation(slot)

    @mcp.tool()
    async def issue_orders(commands: list[dict[str, Any]], reason: str, ctx: Context) -> str:
        """下指令：commands 是指令列表（kind 取 建造/进攻/防守/扩张/骚扰/撤退/喊话/取消），reason 写一句理由。返回接受/拒绝反馈。"""
        slot = _slot(ctx, tokens)
        gateway.touch(slot)
        return await gateway.orders(slot, commands, reason)

    @mcp.tool()
    async def shout(text: str, ctx: Context) -> str:
        """喊话：向所有选手公开说一句话（最多 60 字），不改变任何规则。"""
        slot = _slot(ctx, tokens)
        gateway.touch(slot)
        return await gateway.shout(slot, text)

    return mcp


def build_app(mcp: FastMCP, tokens: SlotTokens):
    """ASGI app: rejects requests without a valid slot token with 401 before they reach MCP."""
    inner = mcp.streamable_http_app()

    async def app(scope, receive, send):
        if scope["type"] == "http" and tokens.slot_for(token_from_scope(scope)) is None:
            await send({
                "type": "http.response.start",
                "status": 401,
                "headers": [(b"content-type", b"text/plain; charset=utf-8")],
            })
            await send({"type": "http.response.body", "body": "无效的连接令牌".encode()})
            return
        await inner(scope, receive, send)

    return app
