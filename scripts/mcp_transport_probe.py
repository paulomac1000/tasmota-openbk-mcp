#!/usr/bin/env python3
"""Probe an exact MCP artifact through the official Python client."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from contextlib import suppress
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamable_http_client


def _tool_names(result: Any) -> set[str]:
    return {tool.name for tool in result.tools}


def _structured_mapping(result: Any) -> dict[str, Any]:
    for attribute in ("structuredContent", "structured_content"):
        value = getattr(result, attribute, None)
        if isinstance(value, dict):
            return value
    for item in getattr(result, "content", []) or []:
        text = getattr(item, "text", None)
        if not isinstance(text, str):
            continue
        try:
            value = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    raise AssertionError("tool result did not contain structured mapping content")


async def _assert_controlled_failure(session: ClientSession) -> None:
    try:
        result = await session.call_tool("definitely_unknown_tool", {})
    except Exception:
        return
    assert result.isError is True


async def _assert_timeout_and_cancellation(session: ClientSession) -> None:
    timeout = await session.call_tool(
        "mock_wait",
        {"identifier": "dev_mock_light", "delay_seconds": 1.0},
    )
    assert timeout.isError is True

    pending = asyncio.create_task(
        session.call_tool(
            "mock_wait",
            {"identifier": "dev_mock_light", "delay_seconds": 0.2},
        )
    )
    await asyncio.sleep(0.02)
    pending.cancel()
    with suppress(asyncio.CancelledError):
        await pending

    state = await session.call_tool(
        "mock_get_state",
        {"identifier": "dev_mock_light"},
    )
    assert state.isError is not True


async def _assert_artifact_resource(session: ClientSession) -> None:
    snapshot = await session.call_tool(
        "mock_capture_snapshot",
        {"identifier": "dev_mock_light"},
    )
    assert snapshot.isError is not True
    artifact_id = str(_structured_mapping(snapshot)["artifact_id"])
    resource = await session.read_resource(f"artifact://{artifact_id}")
    assert resource.contents


async def _common_read_probe(session: ClientSession) -> set[str]:
    await session.initialize()
    tools = await session.list_tools()
    names = _tool_names(tools)
    assert {"mock_get_state", "mock_wait"} <= names
    result = await session.call_tool(
        "mock_get_state",
        {"identifier": "dev_mock_light"},
    )
    assert result.isError is not True
    await _assert_controlled_failure(session)
    await _assert_timeout_and_cancellation(session)
    return names


async def probe_stdio(command: str, args: list[str]) -> None:
    params = StdioServerParameters(command=command, args=args, env=os.environ.copy())
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            names = await _common_read_probe(session)
            assert {"mock_set_power", "mock_capture_snapshot"} <= names
            write_result = await session.call_tool(
                "mock_set_power",
                {"identifier": "dev_mock_light", "power": True},
            )
            assert write_result.isError is not True
            await _assert_artifact_resource(session)


async def probe_http(url: str, token: str | None) -> None:
    import httpx

    headers = {"Authorization": f"Bearer {token}"} if token else {}
    async with httpx.AsyncClient(headers=headers) as client:
        async with streamable_http_client(url, http_client=client) as (read, write, _):
            async with ClientSession(read, write) as session:
                names = await _common_read_probe(session)
                assert "mock_set_power" not in names
                assert "mock_capture_snapshot" not in names
                denied = await session.call_tool(
                    "mock_set_power",
                    {"identifier": "dev_mock_light", "power": True},
                )
                assert denied.isError is True


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
