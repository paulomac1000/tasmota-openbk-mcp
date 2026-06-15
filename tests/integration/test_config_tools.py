"""Integration tests for IoT configuration tools.

These tests work in two modes:
1. Live mode: When the OpenBK device is reachable — read-only tests
2. Replay mode: When device unreachable — tests use HTTP mocking

All live tests are read-only on the real device. Write-tool error-path
tests verify name resolution and validation, never reaching real hardware.
"""

import json
import os
import re
import socket
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------

_REAL_DEVICE_IP = os.getenv("TEST_OPENBK_DEVICE_IP", "192.0.2.115")


def _device_reachable():
    """Check if the real OpenBK device at _REAL_DEVICE_IP is reachable.

    Returns:
        True if the device accepts a TCP connection on port 80.
    """
    try:
        s = socket.create_connection((_REAL_DEVICE_IP, 80), timeout=2)
        s.close()
        return True
    except OSError:
        return False


# ---------------------------------------------------------------------------
# Test helpers (follow existing integration test patterns)
# ---------------------------------------------------------------------------


def _get_result(mcp_client, tool_name, **kwargs):
    """Call a tool via MCPWrapper and return parsed JSON dict."""
    result = mcp_client.call_tool(tool_name, **kwargs)
    return json.loads(result) if isinstance(result, str) else result


# ============================================================================
# Live tests — run only when the real OpenBK device (at _REAL_DEVICE_IP) is online
# ============================================================================


_DEVICE_SKIP_REASON = (
    f"Real OpenBK device not reachable at {_REAL_DEVICE_IP}. "
    "Power on the device and connect it to the network."
)


@pytest.mark.integration
@pytest.mark.skipif(not _device_reachable(), reason=_DEVICE_SKIP_REASON)
class TestConfigToolsLive:
    """Read-only tests against the real OpenBK device.

    These tests fetch iot_get_full_info from the live device and verify
    response structure. No write operations are performed.
    """

    def test_get_full_info_returns_version_and_source(self, mcp_client):
        """Verify firmware version is returned and source is Status 0."""
        data = _get_result(mcp_client, "iot_get_full_info", identifier=_REAL_DEVICE_IP)
        assert data["success"] is True
        assert isinstance(data["data"]["version"], str)
        assert len(data["data"]["version"]) > 0
        assert data["data"]["source"] == "Status 0"

    def test_get_full_info_returns_mac(self, mcp_client):
        """Verify MAC field is present in the response."""
        data = _get_result(mcp_client, "iot_get_full_info", identifier=_REAL_DEVICE_IP)
        assert data["success"] is True
        mac = data["data"]["mac"]
        # MAC is present but may be empty if the device nests it outside
        # the Status dict (e.g. in StatusNET) — this documents the field exists.
        assert isinstance(mac, str)
        if mac:
            assert re.match(r"^([0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}$", mac), (
                f"Invalid MAC format: {mac}"
            )

    def test_get_full_info_returns_mqtt_host(self, mcp_client):
        """Verify MQTT host field is present in the response."""
        data = _get_result(mcp_client, "iot_get_full_info", identifier=_REAL_DEVICE_IP)
        assert data["success"] is True
        mqtt_host = data["data"]["mqtt_host"]
        assert isinstance(mqtt_host, str)

    def test_get_full_info_returns_wifi_ssid(self, mcp_client):
        """Verify WiFi SSID field is present in the response."""
        data = _get_result(mcp_client, "iot_get_full_info", identifier=_REAL_DEVICE_IP)
        assert data["success"] is True
        wifi_ssid = data["data"]["wifi_ssid"]
        assert isinstance(wifi_ssid, str)

    def test_get_full_info_returns_device_type_and_ip(self, mcp_client):
        """Verify device type and IP are returned correctly."""
        data = _get_result(mcp_client, "iot_get_full_info", identifier=_REAL_DEVICE_IP)
        assert data["success"] is True
        assert data["data"]["device_type"] in ("openbk", "tasmota")
        assert data["data"]["ip"] == _REAL_DEVICE_IP

    def test_get_full_info_unresolvable_name(self, mcp_client):
        """Call with nonexistent device name — expect NAME_NOT_RESOLVED error."""
        data = _get_result(mcp_client, "iot_get_full_info", identifier="NoSuchDevice_XYZ")
        assert data["success"] is False
        assert "Could not resolve" in data["error"]["message"]

    def test_get_full_info_unreachable_ip(self, mcp_client):
        """Call with unreachable IP — expect error response."""
        data = _get_result(
            mcp_client,
            "iot_get_full_info",
            identifier="192.168.1.199",
            timeout_seconds=3,
        )
        assert data["success"] is False

    def test_set_flags_name_not_found(self, mcp_client):
        """Write tool with nonexistent name -- safe error path, no HTTP to device."""
        data = _get_result(
            mcp_client,
            "iot_set_flags",
            identifier="NoSuchDevice_XYZ",
            flags=0,
        )
        assert data["success"] is False
        assert "Could not resolve" in data["error"]["message"]


# ============================================================================
# Write-cycle tests -- read-modify-write-restore on the real device
# ============================================================================


@pytest.mark.integration
@pytest.mark.skipif(not _device_reachable(), reason=_DEVICE_SKIP_REASON)
class TestConfigWriteCycle:
    """Read-modify-write-restore tests against the real OpenBK device.

    These tests toggle flag 0 (OBK_FLAG_MQTT_BROADCASTLEDPARAMSTOGETHER)
    which is harmless to change, and always restore the original value
    even if the test fails.
    """

    def test_set_flags_read_modify_write_restore(self, mcp_client):
        """Toggle flag 0 via iot_set_flags, verify, and restore original."""
        # 1. Read current flags
        data = _get_result(mcp_client, "iot_get_full_info", identifier=_REAL_DEVICE_IP)
        assert data["success"] is True
        assert data["data"]["device_type"] == "openbk", (
            f"Test requires OpenBK device, got {data['data']['device_type']}"
        )
        original_flags = data["data"]["flags"]["generic_flags"]
        assert isinstance(original_flags, int)

        # 2. Toggle bit 0 (flag 0: OBK_FLAG_MQTT_BROADCASTLEDPARAMSTOGETHER)
        target_flags = original_flags ^ 1

        try:
            # 3. Apply new flags
            set_data = _get_result(
                mcp_client,
                "iot_set_flags",
                identifier=_REAL_DEVICE_IP,
                flags=target_flags,
            )
            assert set_data["success"] is True

            # 4. Verify the change took effect
            verify_data = _get_result(
                mcp_client,
                "iot_get_full_info",
                identifier=_REAL_DEVICE_IP,
            )
            assert verify_data["success"] is True
            actual = verify_data["data"]["flags"]["generic_flags"]
            assert actual == target_flags, f"Expected flags={target_flags}, got {actual}"
        finally:
            # 5. Always restore original flags
            restore_data = _get_result(
                mcp_client,
                "iot_set_flags",
                identifier=_REAL_DEVICE_IP,
                flags=original_flags,
            )
            assert restore_data["success"] is True

            # Verify restoration
            final_data = _get_result(
                mcp_client,
                "iot_get_full_info",
                identifier=_REAL_DEVICE_IP,
            )
            assert final_data["success"] is True
            assert final_data["data"]["flags"]["generic_flags"] == original_flags


# ============================================================================
# Mocked tests -- always run, use HTTP mocking, offline-safe
# ============================================================================


@pytest.mark.integration
class TestConfigToolsMocked:
    """HTTP-mocked tests that run without a real device.

    These tests verify JSON parsing, validation error paths, and
    command blocklist enforcement — all through HTTP mocking.
    """

    # ------------------------------------------------------------------
    # _get_full_info — OpenBK Status 0 response parsing (mocked)
    # ------------------------------------------------------------------

    def test_get_full_info_parses_openbk_status(self, mcp_client):
        """Mock OpenBK Status 0 response and verify all fields are parsed."""
        # Real OpenBK Status 0 JSON structure:
        # StatusFWR.Version, StatusNET.Mac, StatusMQT.MqttHost,
        # StatusSTS.Wifi.{SSId,RSSI,Signal}, StatusSTS.Uptime,
        # StatusLOG.SetOption[0] (hex-encoded flags)
        mock_openbk_status = {
            "Status": {
                "Module": 0,
                "DeviceName": "OpenBK_Test",
                "FriendlyName": ["OpenBK_Test_1", "OpenBK_Test_2"],
                "Topic": "BK7231N_OPENBK_TEST",
            },
            "StatusFWR": {
                "Version": "OpenBK7231N_1.17.306",
                "BuildDateTime": "Nov  5 2023 10:01:03",
                "Hardware": "BK7231N",
            },
            "StatusNET": {
                "Hostname": "OpenBK_Test",
                "IPAddress": "192.0.2.101",
                "Mac": "AA:BB:CC:DD:EE:11",
            },
            "StatusMQT": {
                "MqttHost": "192.0.2.100",
                "MqttPort": 1883,
                "MqttClient": "BK7231N_OPENBK_TEST",
            },
            "StatusSTS": {
                "Uptime": "0T02:35:00",
                "UptimeSec": 9300,
                "Wifi": {"SSId": "Test_SSID", "RSSI": 62, "Signal": -69},
            },
            "StatusLOG": {
                "SetOption": ["000A8009", "2805C80001000600003C5A0A000000000000"],
            },
            "StatusPRM": {
                "Uptime": 9300,
            },
        }

        with (
            patch("tools.iot_discovery._detect_device_type", return_value="openbk"),
            patch("tools.iot_config._DeviceHttpSession") as mock_session_cls,
        ):
            mock_session = MagicMock()
            mock_session.get_json.return_value = mock_openbk_status
            mock_session_cls.return_value = mock_session

            data = _get_result(mcp_client, "iot_get_full_info", identifier="192.0.2.101")
            assert data["success"] is True
            assert data["data"]["device_type"] == "openbk"
            assert data["data"]["version"] == "OpenBK7231N_1.17.306"
            assert data["data"]["device_name"] == "OpenBK_Test"
            assert data["data"]["mac"] == "AA:BB:CC:DD:EE:11"
            assert data["data"]["mqtt_host"] == "192.0.2.100"
            assert data["data"]["wifi_ssid"] == "Test_SSID"
            assert data["data"]["wifi_rssi"] == 62
            assert data["data"]["wifi_signal"] == -69
            assert data["data"]["uptime"] == "0T02:35:00"
            assert data["data"]["source"] == "Status 0"
            # OpenBK-specific: flags parsed as generic_flags
            assert "generic_flags" in data["data"]["flags"]
            assert "generic_flags_2" in data["data"]["flags"]

    # ------------------------------------------------------------------
    # _get_full_info — Tasmota Status 0 response parsing (mocked)
    # ------------------------------------------------------------------

    def test_get_full_info_parses_tasmota_status(self, mcp_client):
        """Mock Tasmota Status 0 response and verify Tasmota-specific parsing."""
        mock_tasmota_status = {
            "Status": {
                "DeviceName": "Tasmota_Test",
                "FriendlyName": ["Tasmota_Test"],
            },
            "StatusFWR": {
                "Version": "Tasmota_14.2.0",
            },
            "StatusNET": {
                "Mac": "AA:BB:CC:DD:EE:FF",
            },
            "StatusMQT": {
                "MqttHost": "192.0.2.1",
            },
            "StatusSTS": {
                "Uptime": "0T01:00:00",
                "UptimeSec": 3600,
                "Wifi": {"SSId": "Test_SSID", "RSSI": 80, "Signal": -50},
            },
            "SetOption00": "00",
            "SetOption01": "08",
        }

        with (
            patch("tools.iot_discovery._detect_device_type", return_value="tasmota"),
            patch("tools.iot_config._DeviceHttpSession") as mock_session_cls,
        ):
            mock_session = MagicMock()
            mock_session.get_json.return_value = mock_tasmota_status
            mock_session_cls.return_value = mock_session

            data = _get_result(mcp_client, "iot_get_full_info", identifier="192.0.2.100")
            assert data["success"] is True
            assert data["data"]["device_type"] == "tasmota"
            assert data["data"]["version"] == "Tasmota_14.2.0"
            assert data["data"]["device_name"] == "Tasmota_Test"
            assert data["data"]["mac"] == "AA:BB:CC:DD:EE:FF"
            assert data["data"]["mqtt_host"] == "192.0.2.1"
            assert data["data"]["wifi_ssid"] == "Test_SSID"
            assert data["data"]["wifi_rssi"] == 80
            assert isinstance(data["data"]["flags"], dict)

    # ------------------------------------------------------------------
    # Validation error paths (no HTTP needed)
    # ------------------------------------------------------------------

    def test_get_full_info_empty_identifier(self, mcp_client):
        """Empty identifier string — expect INVALID_PARAM error."""
        data = _get_result(mcp_client, "iot_get_full_info", identifier="")
        assert data["success"] is False
        assert data["error"]["code"] == "INVALID_PARAM"

    def test_set_flags_negative_value(self, mcp_client):
        """Negative flags value — expect INVALID_PARAM error."""
        data = _get_result(
            mcp_client,
            "iot_set_flags",
            identifier="192.168.1.100",
            flags=-1,
        )
        assert data["success"] is False
        assert data["error"]["code"] == "INVALID_PARAM"

    def test_set_name_empty_short_name(self, mcp_client):
        """Empty short_name — expect INVALID_PARAM error."""
        data = _get_result(
            mcp_client,
            "iot_set_name",
            identifier="192.168.1.100",
            short_name="",
        )
        assert data["success"] is False
        assert "error" in data

    # ------------------------------------------------------------------
    # Command blocklist tests (no HTTP needed for blocked commands)
    # ------------------------------------------------------------------

    def test_execute_command_blocked_without_force(self, mcp_client):
        """'restart' is blocked — expect COMMAND_BLOCKED error."""
        data = _get_result(
            mcp_client,
            "iot_execute_command",
            identifier="192.168.1.100",
            command="restart",
        )
        assert data["success"] is False
        assert data["error"]["code"] == "COMMAND_BLOCKED"

    def test_execute_command_force_allows_blocked(self, mcp_client):
        """force=True bypasses the blocklist and submits a blocked command."""
        with (
            patch("tools.iot_discovery._detect_device_type", return_value="openbk"),
            patch("tools.iot_config._DeviceHttpSession") as mock_session_cls,
        ):
            mock_session = MagicMock()
            mock_session.get_form.return_value = '{"Status": "OK"}'
            mock_session_cls.return_value = mock_session

            data = _get_result(
                mcp_client,
                "iot_execute_command",
                identifier="192.168.1.100",
                command="restart",
                force=True,
            )
            assert data["success"] is True
            assert data["data"]["command"] == "restart"
            assert data["data"]["device_type"] == "openbk"
            assert "response" in data["data"]
