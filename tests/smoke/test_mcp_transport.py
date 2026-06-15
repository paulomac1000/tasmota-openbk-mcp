"""Smoke tests for Streamable HTTP /mcp endpoint (JSON-RPC)."""

import pytest
import requests

from .conftest import REST_API_URL, server_is_running

pytestmark = [
    pytest.mark.smoke,
    pytest.mark.skipif(
        not server_is_running(),
        reason="MCP server not running",
    ),
]


class TestMcpTransport:
    """Smoke tests for the /mcp Streamable HTTP transport."""

    def test_mcp_tools_list(self):
        """POST /mcp tools/list should return tool list."""
        payload = {"jsonrpc": "2.0", "method": "tools/list", "id": 1}
        resp = requests.post(f"{REST_API_URL}/mcp", json=payload, timeout=5)
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("jsonrpc") == "2.0"
        assert "result" in data
        assert "tools" in data["result"]
        assert len(data["result"]["tools"]) > 0

    def test_mcp_tools_call(self):
        """POST /mcp tools/call iot_list_devices should return result."""
        payload = {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {
                "name": "iot_list_devices",
                "arguments": {},
            },
            "id": 2,
        }
        resp = requests.post(f"{REST_API_URL}/mcp", json=payload, timeout=10)
        assert resp.status_code == 200
        data = resp.json()
        assert "result" in data

    def test_mcp_delete_session(self):
        """DELETE /mcp should terminate session."""
        resp = requests.delete(f"{REST_API_URL}/mcp", timeout=5)
        assert resp.status_code in (200, 204)

    def test_mcp_get(self):
        """GET /mcp should return SSE stream info."""
        resp = requests.get(f"{REST_API_URL}/mcp", timeout=5)
        assert resp.status_code == 200
        data = resp.json()
        assert "result" in data
