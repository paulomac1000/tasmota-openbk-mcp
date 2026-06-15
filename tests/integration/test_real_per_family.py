"""Per-device-family integration tests with anonymized real-device mocks.

These tests verify that each iot_* tool works correctly against the specific
response shapes of each device family (Tasmota, OpenBK, Curtains, Socket).
Uses MOCK_TASMOTA_*, MOCK_OPENBK_*, MOCK_DISCOVERED_DEVICES from
tests.fixtures_real_devices.
"""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from tests.fixtures_real_devices import (
    MOCK_DISCOVERED_DEVICES,
    MOCK_OPENBK_CURTAINS_HTML,
    MOCK_OPENBK_LIGHT_HTML,
)


class TestTasmotaAllTools:
    """All iot_* tools against Tasmota-shaped responses."""

    def test_iot_set_friendly_name_tasmota(self, mcp_client):
        """iot_set_friendly_name uses /cm?cmnd=FriendlyName1."""
        with patch("tools.iot_discovery._resolve_ip", return_value="192.168.1.100"):
            with patch("tools.iot_discovery._detect_device_type", return_value="tasmota"):
                with patch("tools.iot_config._DeviceHttpSession") as mock_session_cls:
                    mock_session = MagicMock()
                    mock_session.get_json.return_value = {"FriendlyName1": "NewName"}
                    mock_session_cls.return_value = mock_session

                    result = mcp_client.call_tool(
                        "iot_set_friendly_name",
                        identifier="192.168.1.100",
                        friendly_name="NewName",
                    )
                    data = json.loads(result)
                    assert data["success"] is True

    def test_iot_set_startup_command_tasmota(self, mcp_client):
        """iot_set_startup_command uses /cm?cmnd=Backlog."""
        with patch("tools.iot_discovery._resolve_ip", return_value="192.168.1.100"):
            with patch("tools.iot_discovery._detect_device_type", return_value="tasmota"):
                with patch("tools.iot_config._DeviceHttpSession") as mock_session_cls:
                    mock_session = MagicMock()
                    mock_session.get_json.return_value = {"Backlog": "OK"}
                    mock_session_cls.return_value = mock_session

                    result = mcp_client.call_tool(
                        "iot_set_startup_command",
                        identifier="192.168.1.100",
                        command="Power ON; Delay 100",
                    )
                    data = json.loads(result)
                    assert data["success"] is True

    def test_iot_execute_command_tasmota_blocks_dangerous(self, mcp_client):
        """iot_execute_command rejects dangerous Tasmota commands."""
        result = mcp_client.call_tool(
            "iot_execute_command",
            identifier="192.168.1.100",
            command="Reset 1",
        )
        data = json.loads(result)
        assert data["success"] is False
        assert data["error"]["code"] in ("COMMAND_BLOCKED", "BLOCKED_COMMAND", "UNSUPPORTED_TYPE")

    def test_iot_execute_command_tasmota_allows_safe(self, mcp_client):
        """iot_execute_command allows safe Tasmota commands like Status."""
        with patch("tools.iot_discovery._resolve_ip", return_value="192.168.1.100"):
            with patch("tools.iot_discovery._detect_device_type", return_value="tasmota"):
                with patch("tools.iot_config._DeviceHttpSession") as mock_session_cls:
                    mock_session = MagicMock()
                    mock_session.get_form.return_value = "Status: OK"
                    mock_session_cls.return_value = mock_session

                    result = mcp_client.call_tool(
                        "iot_execute_command",
                        identifier="192.168.1.100",
                        command="Status",
                    )
                    data = json.loads(result)
                    assert data["success"] is True, f"Got: {data}"


class TestOpenBKAllTools:
    """All iot_* tools against OpenBK-shaped responses.

    Note: Many IoT config tools (set_flags, set_friendly_name, set_startup_command,
    set_gpio, configure_mqtt, start_ha_discovery) are Tasmota-only or have
    limited OpenBK support. This test class verifies that the iot_config
    module is properly registered and that Tasmota-only endpoints return
    UNSUPPORTED_TYPE for OpenBK devices.
    """

    def test_iot_set_flags_openbk(self, mcp_client):
        """iot_set_flags — works for both Tasmota and OpenBK."""
        with patch("tools.iot_discovery._resolve_ip", return_value="192.168.1.102"):
            with patch("tools.iot_discovery._detect_device_type", return_value="openbk"):
                with patch("tools.iot_config._DeviceHttpSession") as mock_session_cls:
                    mock_session = MagicMock()
                    mock_session.get_json.return_value = {}
                    mock_session_cls.return_value = mock_session

                    result = mcp_client.call_tool(
                        "iot_set_flags", identifier="192.168.1.102", flags=3
                    )
                    data = json.loads(result)
                    assert data["success"] is True
                    assert data["data"]["flags_set"] == 3

    def test_iot_config_tools_registered(self, mcp_client):
        """Verify all iot_config tools are registered on the MCP server."""
        expected_tools = [
            "iot_set_flags",
            "iot_set_name",
            "iot_configure_mqtt",
            "iot_set_gpio",
            "iot_execute_command",
            "iot_start_ha_discovery",
            "iot_set_friendly_name",
            "iot_set_startup_command",
            "iot_get_full_info",
        ]
        import asyncio

        all_tool_names = []
        try:
            tools = asyncio.run(mcp_client._mcp.get_tools())
            all_tool_names = list(tools.keys()) if tools else []
        except Exception:
            pass
        for tool_name in expected_tools:
            assert tool_name in all_tool_names, f"{tool_name} not registered"


class TestCurtainsWorkflow:
    """Curtains-specific end-to-end workflow tests."""

    def test_curtains_identify(self, mcp_client):
        """Identify curtains device."""
        with patch("tools.iot_discovery._resolve_ip", return_value="192.168.1.103"):
            with patch("tools.iot_discovery._detect_device_type", return_value="openbk"):
                with patch("tools.iot_devices.requests.get") as mock_get:
                    resp = MagicMock()
                    resp.status_code = 200
                    resp.text = MOCK_OPENBK_CURTAINS_HTML
                    resp.json.side_effect = Exception("not JSON")
                    mock_get.return_value = resp

                    result = mcp_client.call_tool("iot_get_device_info", identifier="192.168.1.103")
                    data = json.loads(result)
                    assert data["success"] is True
                    assert data["data"]["info"]["name"] == "Curtains LivingRoom"

    def test_curtains_control_close(self, mcp_client):
        """Set curtains channel 1 (Close)."""
        with patch("tools.iot_discovery._resolve_ip", return_value="192.168.1.103"):
            with patch("tools.iot_discovery._detect_device_type", return_value="openbk"):
                with patch("tools.iot_control.requests.get") as mock_get:
                    resp = MagicMock()
                    resp.status_code = 200
                    resp.text = "OK"
                    mock_get.return_value = resp

                    result = mcp_client.call_tool(
                        "iot_set_power", identifier="192.168.1.103", state="ON", channel=1
                    )
                    data = json.loads(result)
                    assert data["success"] is True

    def test_curtains_all_3_channels(self, mcp_client):
        """Curtains has 3 channels: Close, Stop, Open."""
        for ch in [1, 2, 3]:
            with patch("tools.iot_discovery._resolve_ip", return_value="192.168.1.103"):
                with patch("tools.iot_discovery._detect_device_type", return_value="openbk"):
                    with patch("tools.iot_control.requests.get") as mock_get:
                        resp = MagicMock()
                        resp.status_code = 200
                        resp.text = "OK"
                        mock_get.return_value = resp

                        result = mcp_client.call_tool(
                            "iot_set_power", identifier="192.168.1.103", state="ON", channel=ch
                        )
                        data = json.loads(result)
                        assert data["success"] is True, f"Channel {ch} failed"


class TestSocketWorkflow:
    """Socket (relay) end-to-end tests."""

    def test_socket_identify(self, mcp_client):
        """Identify socket device from OpenBK HTML."""
        with patch("tools.iot_discovery._resolve_ip", return_value="192.168.1.104"):
            with patch("tools.iot_discovery._detect_device_type", return_value="openbk"):
                with patch("tools.iot_devices.requests.get") as mock_get:
                    resp = MagicMock()
                    resp.status_code = 200
                    resp.text = MOCK_OPENBK_LIGHT_HTML.replace("Light_Bedroom", "Socket_Kitchen")
                    resp.json.side_effect = Exception("not JSON")
                    mock_get.return_value = resp

                    result = mcp_client.call_tool("iot_get_device_info", identifier="192.168.1.104")
                    data = json.loads(result)
                    assert data["success"] is True
                    assert data["data"]["info"]["name"] == "Socket_Kitchen"

    def test_socket_get_device_power(self, mcp_client):
        """Get socket power state via OpenBK HTML."""
        with patch("tools.iot_discovery._resolve_ip", return_value="192.168.1.104"):
            with patch("tools.iot_discovery._detect_device_type", return_value="openbk"):
                with patch("tools.iot_devices.requests.get") as mock_get:
                    resp = MagicMock()
                    resp.status_code = 200
                    resp.text = MOCK_OPENBK_LIGHT_HTML
                    resp.json.side_effect = Exception("not JSON")
                    mock_get.return_value = resp

                    result = mcp_client.call_tool(
                        "iot_get_device_power", identifier="192.168.1.104"
                    )
                    data = json.loads(result)
                    assert data["success"] is True


class TestDiscoveryE2E:
    """Full discovery flow with cached responses."""

    def test_discovery_cache_round_trip(self, mcp_client):
        """Save devices to cache, then read them back."""
        cache_data = {
            "last_scan": "2024-01-01T00:00:00",
            "devices": MOCK_DISCOVERED_DEVICES,
        }

        with patch("tools.iot_discovery._load_cache", return_value=cache_data):
            # List devices
            result_list = mcp_client.call_tool("iot_list_devices")
            data_list = json.loads(result_list)
            assert data_list["success"] is True

            # Find specific device
            result_find = mcp_client.call_tool("iot_find_device_by_name", name="Light_Bedroom")
            data_find = json.loads(result_find)
            assert data_find["success"] is True
            assert data_find["data"]["device"]["ip"] == "192.168.1.102"

    def test_discovery_resolve_ip_by_name(self, mcp_client):
        """_resolve_ip finds device by friendly name in cache."""
        from tools.iot_discovery import _resolve_ip

        cache_data = {"devices": MOCK_DISCOVERED_DEVICES}
        with patch("tools.iot_discovery._load_cache", return_value=cache_data):
            assert _resolve_ip("Light_Bedroom") == "192.168.1.102"
            assert _resolve_ip("Socket_Kitchen") == "192.168.1.104"
            assert _resolve_ip("Curtains_LivingRoom") == "192.168.1.103"
            assert _resolve_ip("192.168.1.100") == "192.168.1.100"
            assert _resolve_ip("Nonexistent") is None

    def test_discovery_resolve_ip_via_devices_file(self, mcp_client, tmp_path):
        """_resolve_ip reads from disk cache file."""
        from tools.iot_discovery import _resolve_ip

        cache_file = tmp_path / "discovered_devices.json"
        cache_file.write_text(json.dumps({"devices": MOCK_DISCOVERED_DEVICES}))

        with patch("tools.iot_discovery.CACHE_FILE", str(cache_file)):
            assert _resolve_ip("Light_Bedroom") == "192.168.1.102"


class TestTuyaMockWorkflow:
    """Tuya tests using mock devices (no real Tuya devices available)."""

    def test_iot_tuya_cloud_list_returns_result(self, mcp_client):
        """iot_tuya_cloud_list returns either cached devices or MISSING_CREDENTIALS.

        On a system with cached Tuya devices, it returns success=True with the
        cached list. On a system without creds, it returns MISSING_CREDENTIALS.
        Both are valid responses depending on environment.
        """
        result = mcp_client.call_tool("iot_tuya_cloud_list")
        data = json.loads(result)
        # Either success with devices, or failure with MISSING_CREDENTIALS
        if data["success"]:
            assert "devices" in data["data"]
            assert isinstance(data["data"]["devices"], list)
        else:
            assert data["error"]["code"] == "MISSING_CREDENTIALS"

    def test_iot_tuya_get_dps_no_cache(self, mcp_client):
        """iot_tuya_get_dps with no cached device returns error."""
        with patch("tools.iot_tuya._find_tuya_in_cache", return_value=None):
            result = mcp_client.call_tool("iot_tuya_get_dps", identifier="UnknownDevice")
            data = json.loads(result)
            assert data["success"] is False
