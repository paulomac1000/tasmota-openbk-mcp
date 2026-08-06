from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

pytestmark = [pytest.mark.integration, pytest.mark.transport]

mcp = pytest.importorskip("mcp", reason="official MCP client dependency is required")
from mcp import ClientSession, StdioServerParameters  # noqa: E402
from mcp.client.stdio import stdio_client  # noqa: E402
from mcp.client.streamable_http import streamable_http_client  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]


def _env(tmp_path: Path, *, transport: str) -> dict[str, str]:
    return {
        **os.environ,
        "PYTHONPATH": str(ROOT),
        "MCP_TRANSPORT": transport,
        "MCP_MOCK_MODE": "1",
        "ENABLE_WRITE_OPERATIONS": "1",
        "MCP_ARTIFACT_ROOT": str(tmp_path / "artifacts"),
    }


@pytest.mark.asyncio
async def test_stdio_subprocess_full_lifecycle(tmp_path: Path):
    params = StdioServerParameters(
        command=sys.executable,
        args=[str(ROOT / "server.py")],
        env=_env(tmp_path, transport="stdio"),
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            names = {tool.name for tool in tools.tools}
            assert {"mock_get_state", "mock_set_power", "mock_capture_snapshot"} <= names
            result = await session.call_tool(
                "mock_set_power", {"identifier": "dev_mock_light", "power": True}
            )
            assert result.isError is not True
            state = await session.call_tool("mock_get_state", {"identifier": "Mock Light"})
            assert state.isError is not True


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_http(url: str, process: subprocess.Popen[bytes]) -> None:
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"HTTP MCP server exited with {process.returncode}")
        try:
            if httpx.get(url, timeout=0.3).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.1)
    raise TimeoutError("HTTP MCP server did not become healthy")


@pytest.mark.asyncio
async def test_streamable_http_real_server_and_auth_boundaries(tmp_path: Path):
    port = _free_port()
    token = "r" * 32
    env = _env(tmp_path, transport="http")
    env.update({"MCP_PORT": str(port), "MCP_AUTH_READ_TOKEN": token})
    process = subprocess.Popen(
        [sys.executable, str(ROOT / "server.py")],
        cwd=ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        _wait_http(f"http://127.0.0.1:{port}/health", process)
        async with httpx.AsyncClient(headers={"Authorization": f"Bearer {token}"}) as client:
            async with streamable_http_client(
                f"http://127.0.0.1:{port}/mcp", http_client=client
            ) as (read, write, _):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    tools = await session.list_tools()
                    assert "mock_get_state" in {tool.name for tool in tools.tools}
                    result = await session.call_tool(
                        "mock_get_state", {"identifier": "dev_mock_light"}
                    )
                    assert result.isError is not True
                    denied = await session.call_tool(
                        "mock_set_power", {"identifier": "dev_mock_light", "power": True}
                    )
                    assert denied.isError is True

        async with httpx.AsyncClient(headers={"Authorization": "Bearer invalid"}) as bad_client:
            with pytest.raises(Exception):
                async with streamable_http_client(
                    f"http://127.0.0.1:{port}/mcp", http_client=bad_client
                ) as (read, write, _):
                    async with ClientSession(read, write) as session:
                        await session.initialize()
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
