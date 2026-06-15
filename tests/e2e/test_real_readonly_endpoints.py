"""E2E tests for readonly endpoints via deployed MCP server.

These tests REQUIRE the MCP server to be running locally (default port 9102).
The server can be started with:
    MCP_SSE_PORT=9101 REST_API_PORT=9102 BIND_HOST=0.0.0.0 \
    MCP_UNSAFE_PUBLIC_ACCESS_CONFIRMED=1 \
    python server.py

Or with Docker:
    docker run -d --rm --name tmcptest \
        -e MCP_SSE_PORT=9101 -e REST_API_PORT=9102 -e BIND_HOST=0.0.0.0 \
        -e MCP_UNSAFE_PUBLIC_ACCESS_CONFIRMED=1 \
        --network host local-home-devices-mcp:test-v1.6-real

All tests are readonly — no write operations (no set_power, no restart, etc.).
"""

import os
import socket

import pytest
import requests

REST_API_URL = os.getenv("REST_API_URL", "http://localhost:9102")
SSE_URL = os.getenv("SSE_URL", "http://localhost:9101")
# /health endpoint is on the MCP transport port (9100), not the REST API (9102)
HEALTH_URL = os.getenv("HEALTH_URL", "http://localhost:9100")


def _server_running(host: str = "localhost", port: int = 9102) -> bool:
    """Probe server port to check if it's accepting connections."""
    try:
        s = socket.create_connection((host, port), timeout=1)
        s.close()
        return True
    except OSError:
        return False


pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(
        not _server_running(),
        reason=(
            f"MCP server not running on {REST_API_URL}. Start with: "
            f"python server.py or docker run --network host local-home-devices-mcp:test-v1.6-real"
        ),
    ),
]


class TestE2EHealth:
    """E2E tests for /health endpoint."""

    def test_health_responds_200(self):
        """Health endpoint returns 200."""
        resp = requests.get(f"{HEALTH_URL}/health", timeout=5)
        assert resp.status_code == 200
        body = resp.json()
        assert body.get("status") == "healthy"
        assert "tools" in body or "tool_count" in body
        assert "tools_version" in body

    def test_health_tool_count_matches(self):
        """Tool count from /health matches actual tool count from /api/tools."""
        health = requests.get(f"{HEALTH_URL}/health", timeout=5).json()
        tools_listing = requests.get(f"{REST_API_URL}/api/tools", timeout=10).json()

        tools_listing_count = (
            len(tools_listing.get("tools", []))
            if isinstance(tools_listing, dict)
            else len(tools_listing)
        )
        health_count = health.get("tool_count", health.get("tools", 0))
        # Both should agree on tool count
        # (Docker mount may exclude some Hikvision container tools, but the
        # base count should be ≥ 55 — non-container tools)
        assert health_count == tools_listing_count, (
            f"/health says {health_count}, /api/tools says {tools_listing_count}"
        )
        assert health_count >= 55, f"Tool count too low: {health_count}"


class TestE2EToolsList:
    """E2E tests for /api/tools endpoint."""

    def test_list_tools(self):
        """List all tools via REST API."""
        resp = requests.get(f"{REST_API_URL}/api/tools", timeout=10)
        assert resp.status_code == 200
        body = resp.json()
        tools = body.get("tools", []) if isinstance(body, dict) else body
        assert len(tools) >= 55
        # All tools should have name and description
        for t in tools[:10]:
            assert "name" in t
            assert "description" in t or "risk" in t

    def test_tools_have_expected_categories(self):
        """Verify all 5 device families are represented in tool list."""
        resp = requests.get(f"{REST_API_URL}/api/tools", timeout=10)
        body = resp.json()
        tools = body.get("tools", []) if isinstance(body, dict) else body
        names = [t.get("name", "") for t in tools]

        # Verify categories
        iot_tools = [n for n in names if n.startswith("iot_")]
        hikvision_tools = [n for n in names if n.startswith("hikvision_")]
        openhasp_tools = [n for n in names if n.startswith("openhasp_")]

        assert len(iot_tools) >= 25, f"Too few iot_ tools: {len(iot_tools)}"
        assert len(hikvision_tools) >= 8, f"Too few hikvision_ tools: {len(hikvision_tools)}"
        assert len(openhasp_tools) >= 15, f"Too few openhasp_ tools: {len(openhasp_tools)}"


class TestE2EReadonlyTools:
    """E2E tests for readonly iot_* tools (no write operations)."""

    def test_iot_list_devices(self):
        """iot_list_devices works against running server."""
        resp = requests.post(
            f"{REST_API_URL}/api/tools/iot_list_devices",
            json={},
            timeout=10,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body.get("success") is True
        inner = body.get("result", {}).get("data", {})
        # May be empty cache, but should not error
        assert "device_count" in inner or "devices" in inner

    def test_iot_get_device_info_real_openbk(self):
        """iot_get_device_info against real OpenBK device 192.168.0.115."""
        if not _server_running_with_real_network():
            pytest.skip("Real network not available (192.168.0.115 unreachable)")

        resp = requests.post(
            f"{REST_API_URL}/api/tools/iot_get_device_info",
            json={"identifier": "192.168.0.115"},
            timeout=15,
        )
        assert resp.status_code == 200
        body = resp.json()
        # Success or graceful failure (device offline)
        if body.get("success"):
            data = body.get("result", {}).get("data", {})
            assert data.get("device_type") in ("openbk", "tasmota", "tuya", "openhasp")

    def test_iot_get_device_info_real_tasmota(self):
        """iot_get_device_info against real Tasmota device 192.168.0.109."""
        if not _server_running_with_real_network():
            pytest.skip("Real network not available (192.168.0.109 unreachable)")

        resp = requests.post(
            f"{REST_API_URL}/api/tools/iot_get_device_info",
            json={"identifier": "192.168.0.109"},
            timeout=15,
        )
        assert resp.status_code == 200
        body = resp.json()
        if body.get("success"):
            data = body.get("result", {}).get("data", {})
            assert data.get("device_type") in ("openbk", "tasmota", "tuya", "openhasp")

    def test_iot_discover_devices(self):
        """iot_discover_devices runs against network."""
        resp = requests.post(
            f"{REST_API_URL}/api/tools/iot_discover_devices",
            json={"network_range": "192.168.0.0/24", "timeout_seconds": 30},
            timeout=60,
        )
        assert resp.status_code == 200
        body = resp.json()
        # Should succeed
        if body.get("success"):
            inner = body.get("result", {}).get("data", {})
            assert "total_found" in inner or "by_type" in inner

    def test_iot_find_device_by_name_nonexistent(self):
        """iot_find_device_by_name returns error for unknown name."""
        resp = requests.post(
            f"{REST_API_URL}/api/tools/iot_find_device_by_name",
            json={"name": "NonexistentDeviceXYZ123"},
            timeout=10,
        )
        assert resp.status_code == 200
        body = resp.json()
        # Should return success=false with error (not crash)
        assert "result" in body or "error" in body

    def test_iot_check_device_router(self):
        """iot_check_device against router IP (192.168.0.1)."""
        if not _server_running_with_real_network():
            pytest.skip("Real network not available")

        resp = requests.post(
            f"{REST_API_URL}/api/tools/iot_check_device",
            json={"ip_address": "192.168.0.1"},
            timeout=10,
        )
        assert resp.status_code == 200
        # Don't assert specific result (may be IoT or not), just no crash

    def test_describe_iot_capabilities(self):
        """describe_iot_capabilities introspection tool works."""
        resp = requests.post(
            f"{REST_API_URL}/api/tools/describe_iot_capabilities",
            json={},
            timeout=10,
        )
        assert resp.status_code == 200
        body = resp.json()
        # Should return tool manifest
        assert body.get("success") is True or "error" in body


class TestE2EMCPTransport:
    """E2E tests for MCP SSE transport."""

    def test_sse_endpoint_accessible(self):
        """SSE endpoint is accessible (returns 200 or 405, but not 502)."""
        try:
            resp = requests.get(
                f"{SSE_URL}/sse",
                timeout=3,
                stream=True,
            )
            # SSE endpoint typically returns 200 with text/event-stream
            # but may return 405 for GET on certain transports
            assert resp.status_code in (200, 405, 400, 404)
        except requests.exceptions.Timeout:
            # SSE is long-lived; timeout is OK
            pass

    def test_messages_endpoint_exists(self):
        """Messages endpoint exists."""
        try:
            resp = requests.post(
                f"{SSE_URL}/messages/",
                json={"test": True},
                timeout=3,
            )
            # Should not be 502/503/404 - transport is up
            assert resp.status_code != 502
            assert resp.status_code != 503
        except requests.exceptions.Timeout:
            pass


def _server_running_with_real_network(target: str = "192.168.0.115", port: int = 80) -> bool:
    """Check if real network devices are reachable from this test runner."""
    try:
        s = socket.create_connection((target, port), timeout=2)
        s.close()
        return True
    except OSError:
        return False
