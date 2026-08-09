"""End-to-end MCP lifecycle through the official client over real stdio.

In-memory `Client(mcp)` tests are not accepted as transport evidence (see
README), so the server is exercised as an actual stdio subprocess here.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

mcp = pytest.importorskip("mcp", reason="official MCP client dependency is required")
from mcp import ClientSession, StdioServerParameters  # noqa: E402
from mcp.client.stdio import stdio_client  # noqa: E402

pytestmark = [pytest.mark.e2e, pytest.mark.asyncio]

ROOT = Path(__file__).resolve().parents[2]


def _env(tmp_path: Path) -> dict[str, str]:
    return {
        **os.environ,
        "PYTHONPATH": str(ROOT),
        "MCP_MOCK_MODE": "1",
        "MCP_TRANSPORT": "stdio",
        "ENABLE_WRITE_OPERATIONS": "1",
        "MCP_ARTIFACT_ROOT": str(tmp_path / "artifacts"),
    }


async def test_initialize_discover_call_and_restore(tmp_path: Path):
    params = StdioServerParameters(
        command=sys.executable,
        args=[str(ROOT / "server.py")],
        env=_env(tmp_path),
    )
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        tools = await session.list_tools()
        names = {tool.name for tool in tools.tools}
        assert names == {
            "mock_get_state",
            "mock_set_power",
            "mock_wait",
            "mock_capture_snapshot",
        }

        before = await session.call_tool("mock_get_state", {"identifier": "dev_mock_light"})
        assert before.isError is not True

        changed = await session.call_tool(
            "mock_set_power", {"identifier": "dev_mock_light", "power": True}
        )
        assert changed.isError is not True

        restored = await session.call_tool(
            "mock_set_power", {"identifier": "dev_mock_light", "power": False}
        )
        assert restored.isError is not True

        after = await session.call_tool("mock_get_state", {"identifier": "dev_mock_light"})
        assert after.isError is not True
