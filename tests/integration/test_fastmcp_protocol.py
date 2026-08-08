"""Official-client MCP lifecycle test; runs when the pinned FastMCP dependency is installed."""

from __future__ import annotations

import pytest

fastmcp = pytest.importorskip("fastmcp")
from fastmcp import Client  # noqa: E402

from local_home_devices_mcp.composition import build_server
from local_home_devices_mcp.config import load_settings

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def test_official_client_initialize_list_and_call(monkeypatch):
    monkeypatch.setenv("MCP_MOCK_MODE", "1")
    monkeypatch.setenv("MCP_TRANSPORT", "stdio")
    monkeypatch.setenv("ENABLE_WRITE_OPERATIONS", "1")
    mcp, gate = build_server(load_settings())
    async with Client(mcp) as client:
        tools = await client.list_tools()
        names = {tool.name for tool in tools}
        assert names == {"mock_get_state", "mock_set_power"}

        templates = await client.list_resource_templates()
        template_uris = {
            str(getattr(template, "uriTemplate", getattr(template, "uri_template", "")))
            for template in templates
        }
        assert "artifact://{artifact_id}" in template_uris
        assert "artifact_read" in gate.catalog

        result = await client.call_tool("mock_get_state", {"identifier": "dev_mock_light"})
        assert result.data["power"] is False
        changed = await client.call_tool(
            "mock_set_power", {"identifier": "dev_mock_light", "power": True}
        )
        assert changed.data["power"] is True
