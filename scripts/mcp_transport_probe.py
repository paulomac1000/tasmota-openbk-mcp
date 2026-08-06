#!/usr/bin/env python3
"""Probe a real MCP transport through the official Python client."""

from __future__ import annotations

import argparse
import asyncio
import os

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamable_http_client


async def probe_stdio(command: str, args: list[str]) -> None:
    params = StdioServerParameters(command=command, args=args, env=os.environ.copy())
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            assert "mock_get_state" in {tool.name for tool in tools.tools}
            result = await session.call_tool(
                "mock_get_state", {"identifier": "dev_mock_light"}
            )
            assert result.isError is not True


async def probe_http(url: str, token: str | None) -> None:
    import httpx

    headers = {"Authorization": f"Bearer {token}"} if token else {}
    async with httpx.AsyncClient(headers=headers) as client:
        async with streamable_http_client(url, http_client=client) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
                assert "mock_get_state" in {tool.name for tool in tools.tools}
                result = await session.call_tool(
                    "mock_get_state", {"identifier": "dev_mock_light"}
                )
                assert result.isError is not True


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="transport", required=True)
    stdio = sub.add_parser("stdio")
    stdio.add_argument("command")
    stdio.add_argument("args", nargs=argparse.REMAINDER)
    http = sub.add_parser("http")
    http.add_argument("url")
    http.add_argument("--token")
    ns = parser.parse_args()
    if ns.transport == "stdio":
        asyncio.run(probe_stdio(ns.command, ns.args))
    else:
        asyncio.run(probe_http(ns.url, ns.token))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
