"""Official-client MCP lifecycle test through a real stdio subprocess.

README: "Client(mcp) in-memory tests are not accepted as transport evidence."
The server is therefore launched as an actual subprocess and driven with the
official MCP client over stdio.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

mcp = pytest.importorskip("mcp", reason="official MCP client dependency is required")
from mcp import ClientSession, StdioServerParameters  # noqa: E402
from mcp.client.stdio import stdio_client  # noqa: E402

from local_home_devices_mcp.composition import build_server  # noqa: E402
from local_home_devices_mcp.config import load_settings  # noqa: E402

pytestmark = pytest.mark.integration

ROOT = Path(__file__).resolve().parents[2]

MOCK_TOOLS = {
    "mock_get_state",
    "mock_set_power",
    "mock_wait",
    "mock_capture_snapshot",
}


def _env(tmp_path: Path) -> dict[str, str]:
    return {
        **os.environ,
        "PYTHONPATH": str(ROOT),
        "MCP_MOCK_MODE": "1",
        "MCP_TRANSPORT": "stdio",
        "ENABLE_WRITE_OPERATIONS": "1",
        "MCP_ARTIFACT_ROOT": str(tmp_path / "artifacts"),
    }


@pytest.mark.asyncio
async def test_official_client_initialize_list_and_call(tmp_path: Path):
    params = StdioServerParameters(
        command=sys.executable,
        args=[str(ROOT / "server.py")],
        env=_env(tmp_path),
    )
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        tools = await session.list_tools()
        names = {tool.name for tool in tools.tools}
        assert names == MOCK_TOOLS

        templates_result = await session.list_resource_templates()
        templates = getattr(templates_result, "resourceTemplates", templates_result) or []
        template_uris = {
            str(getattr(template, "uriTemplate", getattr(template, "uri_template", "")))
            for template in templates
        }
        assert "artifact://{artifact_id}" in template_uris

        result = await session.call_tool("mock_get_state", {"identifier": "dev_mock_light"})
        assert result.isError is not True
        changed = await session.call_tool(
            "mock_set_power", {"identifier": "dev_mock_light", "power": True}
        )
        assert changed.isError is not True


def test_in_memory_gate_governs_mock_catalog(monkeypatch) -> None:
    """Keep a cheap in-memory contract check without claiming transport evidence."""
    monkeypatch.setenv("MCP_MOCK_MODE", "1")
    monkeypatch.setenv("MCP_TRANSPORT", "stdio")
    monkeypatch.setenv("ENABLE_WRITE_OPERATIONS", "1")
    mcp_server, gate = build_server(load_settings())
    assert "artifact_read" in gate.catalog
    assert MOCK_TOOLS.issubset(gate.catalog)
    assert mcp_server is not None
