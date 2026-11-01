"""Spike S5 + Task 23: real MCP server over HTTP, two tokens -> two slots, bad token -> 401. No engine needed."""

from __future__ import annotations

import asyncio
import socket

import httpx
import pytest
import uvicorn
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from openra_arena.coordinator.mcp_connector import build_app, build_mcp_server, token_from_scope
from openra_arena.coordinator.tokens import SlotTokens


class RecordingGateway:
    def __init__(self) -> None:
        self.touched: list[str] = []
        self.orders_seen: list[tuple[str, list, str]] = []

    def touch(self, slot: str) -> None:
        self.touched.append(slot)

    async def situation(self, slot: str) -> str:
        return f"局势:{slot}"

    async def orders(self, slot: str, commands: list[dict], reason: str) -> str:
        self.orders_seen.append((slot, commands, reason))
        return f"已接受 {len(commands)} 条"

    async def shout(self, slot: str, text: str) -> str:
        return f"{slot} 喊话：{text}"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
async def server():
    tokens = SlotTokens.generate(["Multi0", "Multi1"])
    gw = RecordingGateway()
    port = _free_port()
    app = build_app(build_mcp_server(gw, tokens, port=port), tokens)
    srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", lifespan="on"))
    task = asyncio.create_task(srv.serve())
    while not srv.started:
        await asyncio.sleep(0.05)
    yield tokens, gw, port
    srv.should_exit = True
    await task


async def _call(url: str, tool: str, args: dict, headers: dict | None = None) -> str:
    async with streamablehttp_client(url, headers=headers) as (read, write, _), ClientSession(read, write) as s:
        await s.initialize()
        result = await s.call_tool(tool, args)
        return result.content[0].text


async def test_tokens_map_to_their_own_slots_in_parallel(server):
    tokens, gw, port = server
    url0 = tokens.connector_url("Multi0", "127.0.0.1", port)
    base = f"http://127.0.0.1:{port}/mcp"
    r0, r1 = await asyncio.gather(
        _call(url0, "get_situation", {}),
        _call(base, "get_situation", {}, headers={"Authorization": f"Bearer {tokens.token_for('Multi1')}"}),
    )
    assert (r0, r1) == ("局势:Multi0", "局势:Multi1")
    reply = await _call(url0, "issue_orders", {"commands": [{"kind": "建造", "item": "电厂"}], "reason": "补电"})
    assert reply == "已接受 1 条"
    assert gw.orders_seen == [("Multi0", [{"kind": "建造", "item": "电厂"}], "补电")]
    assert sorted(gw.touched) == ["Multi0", "Multi0", "Multi1"]


async def test_tool_list_is_ascii_and_has_three_tools(server):
    tokens, _gw, port = server
    url = tokens.connector_url("Multi0", "127.0.0.1", port)
    async with streamablehttp_client(url) as (read, write, _), ClientSession(read, write) as s:
        await s.initialize()
        names = sorted(t.name for t in (await s.list_tools()).tools)
    assert names == ["get_situation", "issue_orders", "shout"]


async def test_bad_token_gets_401(server):
    _tokens, gw, port = server
    async with httpx.AsyncClient() as c:
        r = await c.post(f"http://127.0.0.1:{port}/mcp?token=wrong", json={})
        r2 = await c.post(f"http://127.0.0.1:{port}/mcp", json={})
    assert r.status_code == 401 and r2.status_code == 401
    assert gw.touched == []


def test_token_from_scope():
    assert token_from_scope({"headers": [(b"authorization", b"Bearer abc")]}) == "abc"
    assert token_from_scope({"headers": [], "query_string": b"token=xyz&x=1"}) == "xyz"
    assert token_from_scope({"headers": []}) is None
