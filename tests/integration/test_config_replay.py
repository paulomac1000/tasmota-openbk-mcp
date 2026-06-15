"""Integration tests for config tools with recorded device response replay.

Uses HTTP mocking with recorded responses from real OpenBK (.115) and
Tasmota (.109) devices. All tests are offline-safe -- no real devices needed.
"""

import json
from unittest.mock import MagicMock, patch

import pytest

from tests.mock_data.mock_responses import (
    openbk_status0_response,
    tasmota_status0_response,
)
from tools.http_session import DeviceConnectionError


def _get_result(mcp_client, tool_name, **kwargs):
    """Call a tool via MCPWrapper and return parsed JSON dict."""
    result = mcp_client.call_tool(tool_name, **kwargs)
    return json.loads(result) if isinstance(result, str) else result


# ============================================================================
# TestOpenBKReplay -- 8 tests replaying OpenBK Status 0 JSON
# ============================================================================


@pytest.mark.integration
class TestOpenBKReplay:
    """Tests replaying recorded OpenBK Status 0 responses via HTTP mocking."""

    @staticmethod
    def _mock_openbk(mock_session_cls):
        """Set up mock session with recorded OpenBK Status 0 response."""
        mock_session = MagicMock()
        mock_session.get_json.return_value = openbk_status0_response()
        mock_session_cls.return_value = mock_session
        return mock_session

    def test_full_info_parses_version_mac(self, mcp_client):
        """Verify version and MAC are parsed from the recorded OpenBK response."""
        with (
            patch("tools.iot_discovery._detect_device_type", return_value="openbk"),
            patch("tools.iot_config._DeviceHttpSession") as mock_session_cls,
        ):
            self._mock_openbk(mock_session_cls)

            data = _get_result(mcp_client, "iot_get_full_info", identifier="192.0.2.101")
            assert data["success"] is True
            assert data["data"]["version"] == "OpenBK7231N_1.17.306"
            assert data["data"]["mac"] == "AA:BB:CC:DD:EE:11"
            assert data["data"]["device_type"] == "openbk"

    def test_full_info_parses_mqtt(self, mcp_client):
        """Verify MQTT host is parsed from the recorded OpenBK response."""
        with (
            patch("tools.iot_discovery._detect_device_type", return_value="openbk"),
            patch("tools.iot_config._DeviceHttpSession") as mock_session_cls,
        ):
            self._mock_openbk(mock_session_cls)

            data = _get_result(mcp_client, "iot_get_full_info", identifier="192.0.2.101")
            assert data["success"] is True
            assert data["data"]["mqtt_host"] == "192.0.2.100"

    def test_full_info_parses_wifi(self, mcp_client):
        """Verify WiFi SSID, RSSI and Signal are parsed from recorded response."""
        with (
            patch("tools.iot_discovery._detect_device_type", return_value="openbk"),
            patch("tools.iot_config._DeviceHttpSession") as mock_session_cls,
        ):
            self._mock_openbk(mock_session_cls)

            data = _get_result(mcp_client, "iot_get_full_info", identifier="192.0.2.101")
            assert data["success"] is True
            assert data["data"]["wifi_ssid"] == "Test_SSID"
            assert isinstance(data["data"]["wifi_rssi"], int)
            assert isinstance(data["data"]["wifi_signal"], int)

    def test_full_info_parses_flags(self, mcp_client):
        """Verify generic_flags parsed from SetOption[0] hex is an integer."""
        with (
            patch("tools.iot_discovery._detect_device_type", return_value="openbk"),
            patch("tools.iot_config._DeviceHttpSession") as mock_session_cls,
        ):
            self._mock_openbk(mock_session_cls)

            data = _get_result(mcp_client, "iot_get_full_info", identifier="192.0.2.101")
            assert data["success"] is True
            assert isinstance(data["data"]["flags"]["generic_flags"], int)

    def test_set_name_creates_correct_url(self, mcp_client):
        """Verify iot_set_name builds URL containing shortName param."""
        with (
            patch("tools.iot_discovery._detect_device_type", return_value="openbk"),
            patch("tools.iot_config._DeviceHttpSession") as mock_session_cls,
        ):
            mock_session = MagicMock()
            mock_session_cls.return_value = mock_session

            data = _get_result(
                mcp_client,
                "iot_set_name",
                identifier="192.0.2.101",
                short_name="TestDev",
            )
            assert data["success"] is True
            mock_session.get_form.assert_called_once()
            url_path = mock_session.get_form.call_args[0][0]
            assert "shortName" in url_path

    def test_set_flags_creates_correct_url(self, mcp_client):
        """Verify iot_set_flags builds URL containing flag and setFlags params."""
        with (
            patch("tools.iot_discovery._detect_device_type", return_value="openbk"),
            patch("tools.iot_config._DeviceHttpSession") as mock_session_cls,
        ):
            mock_session = MagicMock()
            mock_session_cls.return_value = mock_session

            data = _get_result(
                mcp_client,
                "iot_set_flags",
                identifier="192.0.2.101",
                flags=1,
            )
            assert data["success"] is True
            mock_session.get_form.assert_called_once()
            url_path = mock_session.get_form.call_args[0][0]
            assert "flag" in url_path
            assert "setFlags" in url_path

    def test_configure_mqtt_all_params(self, mcp_client):
        """Verify iot_configure_mqtt builds URL with all MQTT params."""
        with (
            patch("tools.iot_discovery._detect_device_type", return_value="openbk"),
            patch("tools.iot_config._DeviceHttpSession") as mock_session_cls,
        ):
            mock_session = MagicMock()
            mock_session_cls.return_value = mock_session

            data = _get_result(
                mcp_client,
                "iot_configure_mqtt",
                identifier="192.0.2.101",
                host="10.0.0.1",
                port=1884,
                client="test_client",
                group="test_group",
            )
            assert data["success"] is True
            mock_session.get_form.assert_called_once()
            url_path = mock_session.get_form.call_args[0][0]
            assert "host" in url_path
            assert "port" in url_path
            assert "client" in url_path
            assert "group" in url_path

    def test_get_full_info_empty_identifier(self, mcp_client):
        """Empty identifier -- expect INVALID_PARAM error."""
        data = _get_result(mcp_client, "iot_get_full_info", identifier="")
        assert data["success"] is False
        assert data["error"]["code"] == "INVALID_PARAM"


# ============================================================================
# TestTasmotaReplay -- 8 tests replaying Tasmota Status 0 JSON
# ============================================================================


@pytest.mark.integration
class TestTasmotaReplay:
    """Tests replaying recorded Tasmota Status 0 responses via HTTP mocking."""

    @staticmethod
    def _mock_tasmota(mock_session_cls):
        """Set up mock session with recorded Tasmota Status 0 response."""
        mock_session = MagicMock()
        mock_session.get_json.return_value = tasmota_status0_response()
        mock_session_cls.return_value = mock_session
        return mock_session

    def test_full_info_parses_tasmota_version_mac(self, mcp_client):
        """Verify Tasmota version and MAC parsed from recorded response."""
        with (
            patch("tools.iot_discovery._detect_device_type", return_value="tasmota"),
            patch("tools.iot_config._DeviceHttpSession") as mock_session_cls,
        ):
            self._mock_tasmota(mock_session_cls)

            data = _get_result(mcp_client, "iot_get_full_info", identifier="192.0.2.100")
            assert data["success"] is True
            assert data["data"]["version"] == "12.5.0(tasmota)"
            assert data["data"]["mac"] == "AA:BB:CC:DD:EE:22"
            assert data["data"]["device_type"] == "tasmota"

    def test_tasmota_set_flags_single_bit(self, mcp_client):
        """Set flags=1 on Tasmota -- builds SetOption0 command."""
        with (
            patch("tools.iot_discovery._detect_device_type", return_value="tasmota"),
            patch("tools.iot_config._DeviceHttpSession") as mock_session_cls,
        ):
            mock_session = MagicMock()
            mock_session_cls.return_value = mock_session

            data = _get_result(
                mcp_client,
                "iot_set_flags",
                identifier="192.0.2.100",
                flags=1,
            )
            assert data["success"] is True
            assert data["data"]["device_type"] == "tasmota"
            mock_session.get_json.assert_called_once()
            url_path = mock_session.get_json.call_args[0][0]
            assert "SetOption0" in url_path

    def test_tasmota_set_flags_multi_bit(self, mcp_client):
        """Set flags=9 (bits 0+3) on Tasmota -- builds backlog command."""
        with (
            patch("tools.iot_discovery._detect_device_type", return_value="tasmota"),
            patch("tools.iot_config._DeviceHttpSession") as mock_session_cls,
        ):
            mock_session = MagicMock()
            mock_session_cls.return_value = mock_session

            data = _get_result(
                mcp_client,
                "iot_set_flags",
                identifier="192.0.2.100",
                flags=9,
            )
            assert data["success"] is True
            assert data["data"]["device_type"] == "tasmota"
            mock_session.get_json.assert_called_once()
            url_path = mock_session.get_json.call_args[0][0]
            assert "backlog" in url_path

    def test_tasmota_set_name(self, mcp_client):
        """Set short_name+full_name on Tasmota -- builds DeviceName+FriendlyName."""
        with (
            patch("tools.iot_discovery._detect_device_type", return_value="tasmota"),
            patch("tools.iot_config._DeviceHttpSession") as mock_session_cls,
        ):
            mock_session = MagicMock()
            mock_session_cls.return_value = mock_session

            data = _get_result(
                mcp_client,
                "iot_set_name",
                identifier="192.0.2.100",
                short_name="TDev",
                full_name="Test_Device",
            )
            assert data["success"] is True
            mock_session.get_form.assert_called_once()
            url_path = mock_session.get_form.call_args[0][0]
            assert "DeviceName" in url_path
            assert "FriendlyName1" in url_path

    def test_tasmota_set_friendly_name(self, mcp_client):
        """Set friendly_name on Tasmota -- builds FriendlyName1 command."""
        with (
            patch("tools.iot_discovery._detect_device_type", return_value="tasmota"),
            patch("tools.iot_config._DeviceHttpSession") as mock_session_cls,
        ):
            mock_session = MagicMock()
            mock_session_cls.return_value = mock_session

            data = _get_result(
                mcp_client,
                "iot_set_friendly_name",
                identifier="192.0.2.100",
                friendly_name="My Device",
            )
            assert data["success"] is True
            mock_session.get_form.assert_called_once()
            url_path = mock_session.get_form.call_args[0][0]
            assert "FriendlyName1" in url_path

    def test_tasmota_configure_mqtt(self, mcp_client):
        """Configure MQTT on Tasmota -- builds MqttHost+MqttPort commands."""
        with (
            patch("tools.iot_discovery._detect_device_type", return_value="tasmota"),
            patch("tools.iot_config._DeviceHttpSession") as mock_session_cls,
        ):
            mock_session = MagicMock()
            mock_session_cls.return_value = mock_session

            data = _get_result(
                mcp_client,
                "iot_configure_mqtt",
                identifier="192.0.2.100",
                host="10.0.0.1",
                port=1884,
            )
            assert data["success"] is True
            mock_session.get_form.assert_called_once()
            url_path = mock_session.get_form.call_args[0][0]
            assert "MqttHost" in url_path
            assert "MqttPort" in url_path

    def test_tasmota_start_ha_discovery(self, mcp_client):
        """Start HA discovery on Tasmota -- builds SetOption19 command."""
        with (
            patch("tools.iot_discovery._detect_device_type", return_value="tasmota"),
            patch("tools.iot_config._DeviceHttpSession") as mock_session_cls,
        ):
            mock_session = MagicMock()
            mock_session_cls.return_value = mock_session

            data = _get_result(
                mcp_client,
                "iot_start_ha_discovery",
                identifier="192.0.2.100",
            )
            assert data["success"] is True
            mock_session.get_form.assert_called_once()
            url_path = mock_session.get_form.call_args[0][0]
            assert "SetOption19" in url_path

    def test_tasmota_startup_command(self, mcp_client):
        """Set startup command on Tasmota -- builds Rule1 with the command."""
        with (
            patch("tools.iot_discovery._detect_device_type", return_value="tasmota"),
            patch("tools.iot_config._DeviceHttpSession") as mock_session_cls,
        ):
            mock_session = MagicMock()
            mock_session_cls.return_value = mock_session

            data = _get_result(
                mcp_client,
                "iot_set_startup_command",
                identifier="192.0.2.100",
                command="Power1 ON",
            )
            assert data["success"] is True
            mock_session.get_form.assert_called_once()
            url_path = mock_session.get_form.call_args[0][0]
            assert "Rule1" in url_path


# ============================================================================
# TestErrorReplay -- 4 tests for error paths
# ============================================================================


@pytest.mark.integration
class TestErrorReplay:
    """Tests that verify error handling paths with mocked failures."""

    def test_device_timeout(self, mcp_client):
        """Mock a connection timeout and verify DEVICE_ERROR response."""
        with (
            patch("tools.iot_discovery._detect_device_type", return_value="openbk"),
            patch("tools.iot_config._DeviceHttpSession") as mock_session_cls,
        ):
            mock_session = MagicMock()
            mock_session.get_json.side_effect = DeviceConnectionError("Connection timed out")
            mock_session_cls.return_value = mock_session

            data = _get_result(
                mcp_client,
                "iot_get_full_info",
                identifier="192.0.2.101",
            )
            assert data["success"] is False
            assert "error" in data

    def test_device_http_500(self, mcp_client):
        """Mock an HTTP 500 error and verify error response."""
        with (
            patch("tools.iot_discovery._detect_device_type", return_value="openbk"),
            patch("tools.iot_config._DeviceHttpSession") as mock_session_cls,
        ):
            mock_session = MagicMock()
            mock_session.get_form.side_effect = DeviceConnectionError("HTTP 500: Server Error")
            mock_session_cls.return_value = mock_session

            data = _get_result(
                mcp_client,
                "iot_set_flags",
                identifier="192.0.2.101",
                flags=0,
            )
            assert data["success"] is False

    def test_name_not_resolved(self, mcp_client):
        """Unresolvable device name -- expect NAME_NOT_RESOLVED error."""
        with patch("tools.iot_discovery._resolve_ip", return_value=None):
            data = _get_result(
                mcp_client,
                "iot_get_full_info",
                identifier="UnknownDevice",
            )
            assert data["success"] is False
            assert data["error"]["code"] == "NAME_NOT_RESOLVED"

    def test_device_not_found(self, mcp_client):
        """Device type undetected -- expect DEVICE_NOT_FOUND error."""
        with patch("tools.iot_discovery._detect_device_type", return_value=None):
            data = _get_result(
                mcp_client,
                "iot_get_full_info",
                identifier="192.0.2.200",
            )
            assert data["success"] is False
            assert data["error"]["code"] == "DEVICE_NOT_FOUND"


# ============================================================================
# TestWriteGateReplay -- 3 tests for write-gate behavior
# ============================================================================


@pytest.mark.integration
class TestWriteGateReplay:
    """Tests verifying write-gate enforcement and read-tool safety."""

    def test_write_tool_rejected_when_disabled(self, mcp_client, monkeypatch):
        """Write tool returns WRITE_DISABLED when ENABLE_WRITE_OPERATIONS=False."""
        monkeypatch.setattr("tools.constants.ENABLE_WRITE_OPERATIONS", False)

        with (
            patch("tools.iot_discovery._detect_device_type", return_value="openbk"),
            patch("tools.iot_config._DeviceHttpSession") as mock_session_cls,
        ):
            mock_session = MagicMock()
            mock_session_cls.return_value = mock_session

            data = _get_result(
                mcp_client,
                "iot_set_flags",
                identifier="192.0.2.101",
                flags=1,
            )
            assert data["success"] is False
            assert data["error"]["code"] == "WRITE_DISABLED"
            # Verify HTTP was never called -- the gate blocked before reaching
            # the internal function.
            mock_session.get_form.assert_not_called()
            mock_session.get_json.assert_not_called()

    def test_read_tool_works_when_writes_disabled(self, mcp_client, monkeypatch):
        """Read tool succeeds even when write operations are disabled."""
        monkeypatch.setattr("tools.constants.ENABLE_WRITE_OPERATIONS", False)

        with (
            patch("tools.iot_discovery._detect_device_type", return_value="openbk"),
            patch("tools.iot_config._DeviceHttpSession") as mock_session_cls,
        ):
            mock_session = MagicMock()
            mock_session.get_json.return_value = openbk_status0_response()
            mock_session_cls.return_value = mock_session

            data = _get_result(
                mcp_client,
                "iot_get_full_info",
                identifier="192.0.2.101",
            )
            assert data["success"] is True

    def test_execute_command_blocked(self, mcp_client):
        """Blocked command 'reset' returns COMMAND_BLOCKED without HTTP call."""
        with (
            patch("tools.iot_discovery._detect_device_type", return_value="openbk"),
            patch("tools.iot_config._DeviceHttpSession") as mock_session_cls,
        ):
            mock_session = MagicMock()
            mock_session_cls.return_value = mock_session

            data = _get_result(
                mcp_client,
                "iot_execute_command",
                identifier="192.0.2.101",
                command="reset",
            )
            assert data["success"] is False
            assert data["error"]["code"] == "COMMAND_BLOCKED"
            # Blocklist check happens before any HTTP request.
            mock_session.get_form.assert_not_called()
