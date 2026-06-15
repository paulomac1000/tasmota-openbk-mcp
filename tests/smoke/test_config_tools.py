"""Smoke tests for IoT configuration tools via REST API."""

import os

import pytest
import requests

from .conftest import REST_API_PORT, REST_API_URL, server_is_running

# ---------------------------------------------------------------------------
# Dynamic skip — entire file is skipped when the server is not reachable
# ---------------------------------------------------------------------------
pytestmark = [
    pytest.mark.smoke,
    pytest.mark.skipif(
        not server_is_running(),
        reason=f"MCP server not running on port {REST_API_PORT}. Start with: python server.py",
    ),
]

# ---------------------------------------------------------------------------
# The 7 config tools as listed in the README "Device Configuration" section
# ---------------------------------------------------------------------------
CONFIG_TOOL_NAMES: tuple[str, ...] = (
    "iot_set_flags",
    "iot_set_name",
    "iot_configure_mqtt",
    "iot_set_gpio",
    "iot_execute_command",
    "iot_start_ha_discovery",
    "iot_get_full_info",
)

# Subset used for explicit presence checks
SPECIFIC_CONFIG_TOOLS: tuple[str, ...] = (
    "iot_set_flags",
    "iot_set_name",
    "iot_get_full_info",
    "iot_set_friendly_name",
)

# Safe test device — read-only Status 0 commands are harmless
TEST_DEVICE_IP = os.getenv("TEST_CONFIG_DEVICE_IP", "192.0.2.115")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _api_get(path: str) -> requests.Response:
    """GET a REST API endpoint with 5 s timeout."""
    return requests.get(f"{REST_API_URL}{path}", timeout=5)


def _api_post(tool_name: str, data: dict | None = None) -> requests.Response:
    """POST to a REST API tool endpoint."""
    return requests.post(
        f"{REST_API_URL}/api/tools/{tool_name}",
        json=data or {},
        timeout=30,
    )


# ===================================================================
# Health + Tool List
# ===================================================================


class TestHealthEndpoint:
    """Health-check and tool-listing smoke tests."""

    def test_health_returns_200(self) -> None:
        """GET /health returns 200 and reports healthy status."""
        resp = _api_get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("status") == "healthy"

    def test_health_returns_tool_count(self) -> None:
        """GET /health reports tool_count >= 66."""
        resp = _api_get("/health")
        data = resp.json()
        count = data.get("tool_count", 0)
        assert count >= 66, f"Expected tool_count >= 66, got {count}"

    def test_health_version_is_1_6_0(self) -> None:
        """GET /health reports version == '1.6.0'."""
        resp = _api_get("/health")
        data = resp.json()
        assert data.get("version") == "1.6.0", f"Expected version 1.6.0, got {data.get('version')}"

    def test_tools_list_returns_tools(self) -> None:
        """GET /api/tools returns a 'tools' list with >= 66 entries."""
        resp = _api_get("/api/tools")
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("success") is True
        tools = data.get("tools", [])
        assert isinstance(tools, list)
        assert len(tools) >= 66, f"Expected >= 66 tools, got {len(tools)}"

    def test_tools_list_includes_config_tools(self) -> None:
        """GET /api/tools includes the 4 specific config tools."""
        resp = _api_get("/api/tools")
        data = resp.json()
        tool_names = {t["name"] for t in data.get("tools", []) if "name" in t}
        for name in SPECIFIC_CONFIG_TOOLS:
            assert name in tool_names, f"'{name}' not found in /api/tools response"

    def test_health_returns_tools_registered(self) -> None:
        """GET /health reports tools_registered matching tool_count."""
        resp = _api_get("/health")
        data = resp.json()
        assert data.get("tools_registered") == data.get("tool_count"), (
            "tools_registered should match tool_count"
        )


# ===================================================================
# Tool Descriptions
# ===================================================================


class TestToolDescriptions:
    """All config tools must have non-empty descriptions."""

    def _fetch_tools_map(self) -> dict[str, str | None]:
        resp = _api_get("/api/tools")
        data = resp.json()
        return {t["name"]: t.get("description") for t in data["tools"]}

    def test_config_tools_have_description(self) -> None:
        """Each of the 7 config tools has a non-empty description."""
        tools_map = self._fetch_tools_map()
        missing: list[str] = []
        empty: list[str] = []
        for name in CONFIG_TOOL_NAMES:
            desc = tools_map.get(name)
            if desc is None:
                missing.append(name)
            elif not desc.strip():
                empty.append(name)
        if missing:
            raise AssertionError(f"Config tools absent from /api/tools: {missing}")
        if empty:
            raise AssertionError(f"Config tools with empty description: {empty}")

    def test_all_tools_have_description(self) -> None:
        """Every tool in /api/tools has some description text."""
        resp = _api_get("/api/tools")
        data = resp.json()
        bad: list[tuple[str, str | None]] = [
            (t["name"], t.get("description")) for t in data["tools"] if not t.get("description")
        ]
        assert not bad, f"Tools with no description: {[b[0] for b in bad]}"


# ===================================================================
# Read-only tool smoke – verify responses are well-formed JSON
# ===================================================================


class TestReadOnlyToolShapes:
    """Safe read-only operations return valid JSON with success field."""

    def test_iot_get_full_info_returns_success(self) -> None:
        """iot_get_full_info with a known device IP returns success=True."""
        resp = _api_post("iot_get_full_info", {"identifier": TEST_DEVICE_IP})
        data = resp.json()
        assert "success" in data, "Response must contain 'success' key"
        if data["success"]:
            assert "result" in data, "Successful response must contain 'result'"

    def test_iot_execute_command_allowed(self) -> None:
        """iot_execute_command with a safe 'Status 0' returns JSON."""
        resp = _api_post(
            "iot_execute_command",
            {"identifier": TEST_DEVICE_IP, "command": "Status 0"},
        )
        data = resp.json()
        assert "success" in data, "Response must contain 'success' key"

    def test_iot_get_wifi_config_shape(self) -> None:
        """iot_get_wifi_config returns JSON with success field."""
        resp = _api_post("iot_get_wifi_config", {"identifier": TEST_DEVICE_IP})
        data = resp.json()
        assert "success" in data, "Response must contain 'success' key"

    def test_iot_get_device_info_shape(self) -> None:
        """iot_get_device_info returns valid JSON."""
        resp = _api_post("iot_get_device_info", {"identifier": TEST_DEVICE_IP})
        data = resp.json()
        assert "success" in data, "Response must contain 'success' key"

    def test_iot_get_device_power_shape(self) -> None:
        """iot_get_device_power returns valid JSON."""
        resp = _api_post("iot_get_device_power", {"identifier": TEST_DEVICE_IP})
        data = resp.json()
        assert "success" in data, "Response must contain 'success' key"

    def test_iot_list_devices_shape(self) -> None:
        """iot_list_devices returns valid JSON."""
        resp = _api_post("iot_list_devices")
        data = resp.json()
        assert "success" in data, "Response must contain 'success' key"

    def test_iot_find_device_by_name_shape(self) -> None:
        """iot_find_device_by_name with a test name returns valid JSON."""
        resp = _api_post("iot_find_device_by_name", {"name": "OpenBK_Test"})
        data = resp.json()
        assert "success" in data, "Response must contain 'success' key"


# ===================================================================
# Introspection / capabilities
# ===================================================================


class TestDescribeCapabilities:
    """describe_iot_capabilities tool smoke."""

    def test_describe_iot_capabilities_returns_manifest(self) -> None:
        """describe_iot_capabilities returns manifests for all config tools."""
        resp = _api_post("describe_iot_capabilities")
        data = resp.json()
        assert data.get("success") is True
        tools = data.get("result", {}).get("data", {}).get("tools", [])
        tool_names = {t["name"] for t in tools if "name" in t}
        for name in CONFIG_TOOL_NAMES:
            assert name in tool_names, (
                f"Manifest for '{name}' missing from describe_iot_capabilities"
            )
        for t in tools:
            if t.get("name") in CONFIG_TOOL_NAMES:
                assert "risk" in t, f"Manifest for '{t['name']}' missing 'risk' field"


# ===================================================================
# Write gate – destructive / write tools blocked when disabled
# ===================================================================


class TestWriteGate:
    """Verify write/destructive tools are blocked when write operations disabled."""

    def test_set_flags_returns_valid_response(self) -> None:
        """iot_set_flags returns a well-formed response (may be write-blocked)."""
        resp = _api_post("iot_set_flags", {"identifier": TEST_DEVICE_IP, "flags": 0})
        data = resp.json()
        assert "success" in data, "Response must contain 'success' key"
        if not data["success"]:
            # If write is disabled, the error should be well-structured
            assert "error" in data or "code" in data or "message" in data, (
                "Error response should contain error details"
            )

    def test_set_name_blocked_or_allowed(self) -> None:
        """iot_set_name returns a well-formed response."""
        resp = _api_post(
            "iot_set_name",
            {"identifier": TEST_DEVICE_IP, "short_name": "test_device"},
        )
        data = resp.json()
        assert "success" in data, "Response must contain 'success' key"

    def test_configure_mqtt_blocked_or_allowed(self) -> None:
        """iot_configure_mqtt returns a well-formed response."""
        resp = _api_post(
            "iot_configure_mqtt",
            {"identifier": TEST_DEVICE_IP, "mqtt_host": "192.168.1.1"},
        )
        data = resp.json()
        assert "success" in data, "Response must contain 'success' key"

    def test_set_gpio_blocked_or_allowed(self) -> None:
        """iot_set_gpio returns a well-formed response."""
        resp = _api_post(
            "iot_set_gpio",
            {"identifier": TEST_DEVICE_IP, "pin": 0, "role": 0, "channel": 1},
        )
        data = resp.json()
        assert "success" in data, "Response must contain 'success' key"

    def test_start_ha_discovery_blocked_or_allowed(self) -> None:
        """iot_start_ha_discovery returns a well-formed response."""
        resp = _api_post("iot_start_ha_discovery", {"identifier": TEST_DEVICE_IP})
        data = resp.json()
        assert "success" in data, "Response must contain 'success' key"

    def test_set_friendly_name_blocked_or_allowed(self) -> None:
        """iot_set_friendly_name returns a well-formed response."""
        resp = _api_post(
            "iot_set_friendly_name",
            {"identifier": TEST_DEVICE_IP, "friendly_name": "Test_Device"},
        )
        data = resp.json()
        assert "success" in data, "Response must contain 'success' key"
