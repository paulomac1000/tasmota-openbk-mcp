"""
Unit tests for IoT MCP device control tools.

Tests power, brightness, restart, and WiFi config operations
with name resolution from the discovery cache.
"""

import json
from unittest.mock import MagicMock, patch

import pytest

from tools.iot_control import (
    _get_wifi_config,
    _restart_device,
    _set_brightness,
    _set_power,
    register_iot_control_tools,
)

pytestmark = pytest.mark.unit


class TestPowerControl:
    """Tests for power control operations."""

    def test_set_power_tasmota_on(self):
        with patch("tools.iot_discovery._resolve_ip", return_value="192.168.1.100"):
            with patch(
                "tools.iot_discovery._detect_device_type",
                return_value="tasmota",
            ):
                with patch("tools.iot_control.requests.get") as mock_get:
                    resp = MagicMock()
                    resp.status_code = 200
                    resp.json.return_value = {"POWER1": "ON"}
                    mock_get.return_value = resp
                    result = _set_power("192.168.1.100", "ON")
                    data = json.loads(result)
                    assert data["success"] is True
                    assert data["data"]["device_type"] == "tasmota"
                    assert data["data"]["actual_state"] == "ON"
                    assert data["data"]["resolved_from"] == "192.168.1.100"

    def test_set_power_tasmota_toggle(self):
        with patch("tools.iot_discovery._resolve_ip", return_value="192.168.1.100"):
            with patch(
                "tools.iot_discovery._detect_device_type",
                return_value="tasmota",
            ):
                with patch("tools.iot_control.requests.get") as mock_get:
                    resp = MagicMock()
                    resp.status_code = 200
                    resp.json.return_value = {"POWER1": "ON"}
                    mock_get.return_value = resp
                    result = _set_power("192.168.1.100", "TOGGLE")
                    data = json.loads(result)
                    assert data["success"] is True
                    assert data["data"]["requested_state"] == "TOGGLE"

    def test_set_power_openbk(self):
        with patch("tools.iot_discovery._resolve_ip", return_value="192.168.1.101"):
            with patch(
                "tools.iot_discovery._detect_device_type",
                return_value="openbk",
            ):
                with patch("tools.iot_control.requests.get") as mock_get:
                    resp = MagicMock()
                    resp.status_code = 200
                    mock_get.return_value = resp
                    result = _set_power("192.168.1.101", "ON")
                    data = json.loads(result)
                    assert data["success"] is True
                    assert data["data"]["device_type"] == "openbk"

    def test_set_power_by_name(self):
        with patch(
            "tools.iot_discovery._resolve_ip",
            return_value="192.168.1.100",
        ):
            with patch(
                "tools.iot_discovery._detect_device_type",
                return_value="tasmota",
            ):
                with patch("tools.iot_control.requests.get") as mock_get:
                    resp = MagicMock()
                    resp.status_code = 200
                    resp.json.return_value = {"POWER": "ON"}
                    mock_get.return_value = resp
                    result = _set_power("Light_Bathroom", "ON")
                    data = json.loads(result)
                    assert data["success"] is True
                    assert data["data"]["resolved_from"] == "Light_Bathroom"
                    assert data["data"]["ip"] == "192.168.1.100"

    def test_set_power_name_not_found(self):
        with patch("tools.iot_discovery._resolve_ip", return_value=None):
            with patch("tools.iot_discovery._get_cached_devices", return_value=[]):
                result = _set_power("UnknownDevice", "ON")
                data = json.loads(result)
                assert data["success"] is False
                assert "Could not resolve" in data["error"]["message"]

    def test_set_power_invalid_state(self):
        with patch(
            "tools.iot_discovery._resolve_ip",
            return_value="192.168.1.100",
        ):
            with patch(
                "tools.iot_discovery._detect_device_type",
                return_value="tasmota",
            ):
                result = _set_power("192.168.1.100", "INVALID")
                data = json.loads(result)
                assert data["success"] is False
                assert "Invalid state" in data["error"]["message"]

    def test_set_power_device_not_found(self):
        with patch(
            "tools.iot_discovery._resolve_ip",
            return_value="192.168.1.200",
        ):
            with patch(
                "tools.iot_discovery._detect_device_type",
                return_value=None,
            ):
                result = _set_power("192.168.1.200", "ON")
                data = json.loads(result)
                assert data["success"] is False


class TestPowerControlErrors:
    """Edge case and error path tests for power control."""

    def test_set_power_tasmota_http_error(self):
        with patch("tools.iot_discovery._resolve_ip", return_value="192.168.1.100"):
            with patch("tools.iot_discovery._detect_device_type", return_value="tasmota"):
                with patch("tools.iot_control.requests.get") as mock_get:
                    resp = MagicMock()
                    resp.status_code = 500
                    mock_get.return_value = resp
                    result = _set_power("192.168.1.100", "ON")
                    data = json.loads(result)
                    assert data["success"] is False
                    assert "HTTP 500" in data["error"]["message"]

    def test_set_power_openbk_toggle(self):
        with patch("tools.iot_discovery._resolve_ip", return_value="192.168.1.101"):
            with patch("tools.iot_discovery._detect_device_type", return_value="openbk"):
                with patch("tools.iot_control.requests.get") as mock_get:
                    resp = MagicMock()
                    resp.status_code = 200
                    mock_get.return_value = resp
                    result = _set_power("192.168.1.101", "TOGGLE")
                    data = json.loads(result)
                    assert data["success"] is True
                    assert data["data"]["requested_state"] == "TOGGLE"

    def test_set_power_openbk_http_error(self):
        with patch("tools.iot_discovery._resolve_ip", return_value="192.168.1.101"):
            with patch("tools.iot_discovery._detect_device_type", return_value="openbk"):
                with patch("tools.iot_control.requests.get") as mock_get:
                    resp = MagicMock()
                    resp.status_code = 403
                    mock_get.return_value = resp
                    result = _set_power("192.168.1.101", "ON")
                    data = json.loads(result)
                    assert data["success"] is False
                    assert "HTTP 403" in data["error"]["message"]

    def test_set_power_unsupported_device_type(self):
        with patch("tools.iot_discovery._resolve_ip", return_value="192.168.1.100"):
            with patch("tools.iot_discovery._detect_device_type", return_value="zigbee"):
                result = _set_power("192.168.1.100", "ON")
                data = json.loads(result)
                assert data["success"] is False
                assert "Unsupported device type" in data["error"]["message"]


class TestBrightnessControl:
    """Tests for brightness control."""

    def test_set_brightness_tasmota(self):
        with patch(
            "tools.iot_discovery._resolve_ip",
            return_value="192.168.1.100",
        ):
            with patch(
                "tools.iot_discovery._detect_device_type",
                return_value="tasmota",
            ):
                with patch("tools.iot_control.requests.get") as mock_get:
                    resp = MagicMock()
                    resp.status_code = 200
                    mock_get.return_value = resp
                    result = _set_brightness("192.168.1.100", 75)
                    data = json.loads(result)
                    assert data["success"] is True
                    assert data["data"]["brightness"] == 75

    def test_set_brightness_by_name(self):
        with patch(
            "tools.iot_discovery._resolve_ip",
            return_value="192.168.1.101",
        ):
            with patch(
                "tools.iot_discovery._detect_device_type",
                return_value="openbk",
            ):
                with patch("tools.iot_control.requests.get") as mock_get:
                    resp = MagicMock()
                    resp.status_code = 200
                    mock_get.return_value = resp
                    result = _set_brightness("Light_LivingRoom", 50)
                    data = json.loads(result)
                    assert data["success"] is True
                    assert data["data"]["resolved_from"] == "Light_LivingRoom"

    def test_set_brightness_rejected_high(self):
        with patch(
            "tools.iot_discovery._resolve_ip",
            return_value="192.168.1.101",
        ):
            with patch(
                "tools.iot_discovery._detect_device_type",
                return_value="openbk",
            ):
                with patch("tools.iot_control.requests.get") as mock_get:
                    resp = MagicMock()
                    resp.status_code = 200
                    mock_get.return_value = resp
                    result = _set_brightness("192.168.1.101", 150)
                    data = json.loads(result)
                    assert data["success"] is False
                    assert "0-100" in data["error"]["message"]

    def test_set_brightness_rejected_low(self):
        with patch(
            "tools.iot_discovery._resolve_ip",
            return_value="192.168.1.101",
        ):
            with patch(
                "tools.iot_discovery._detect_device_type",
                return_value="openbk",
            ):
                with patch("tools.iot_control.requests.get") as mock_get:
                    resp = MagicMock()
                    resp.status_code = 200
                    mock_get.return_value = resp
                    result = _set_brightness("192.168.1.101", -10)
                    data = json.loads(result)
                    assert data["success"] is False
                    assert "0-100" in data["error"]["message"]


class TestBrightnessControlErrors:
    """Edge case and error path tests for brightness control."""

    def test_set_brightness_name_not_resolved(self):
        with patch("tools.iot_discovery._resolve_ip", return_value=None):
            with patch("tools.iot_discovery._get_cached_devices", return_value=[]):
                result = _set_brightness("UnknownDevice", 50)
                data = json.loads(result)
                assert data["success"] is False
                assert "Could not resolve" in data["error"]["message"]

    def test_set_brightness_device_not_found(self):
        with patch("tools.iot_discovery._resolve_ip", return_value="192.168.1.200"):
            with patch("tools.iot_discovery._detect_device_type", return_value=None):
                result = _set_brightness("192.168.1.200", 50)
                data = json.loads(result)
                assert data["success"] is False
                assert "No IoT device found" in data["error"]["message"]

    def test_set_brightness_unsupported_type(self):
        with patch("tools.iot_discovery._resolve_ip", return_value="192.168.1.100"):
            with patch("tools.iot_discovery._detect_device_type", return_value="esphome"):
                result = _set_brightness("192.168.1.100", 50)
                data = json.loads(result)
                assert data["success"] is False
                assert "Unsupported device type" in data["error"]["message"]

    def test_set_brightness_tasmota_http_error(self):
        with patch("tools.iot_discovery._resolve_ip", return_value="192.168.1.100"):
            with patch("tools.iot_discovery._detect_device_type", return_value="tasmota"):
                with patch("tools.iot_control.requests.get") as mock_get:
                    resp = MagicMock()
                    resp.status_code = 500
                    mock_get.return_value = resp
                    result = _set_brightness("192.168.1.100", 80)
                    data = json.loads(result)
                    assert data["success"] is False


class TestRestart:
    """Tests for device restart."""

    def test_restart_tasmota(self):
        with patch(
            "tools.iot_discovery._resolve_ip",
            return_value="192.168.1.100",
        ):
            with patch(
                "tools.iot_discovery._detect_device_type",
                return_value="tasmota",
            ):
                with patch("tools.iot_control.requests.get") as mock_get:
                    resp = MagicMock()
                    resp.status_code = 200
                    mock_get.return_value = resp
                    result = _restart_device("192.168.1.100")
                    data = json.loads(result)
                    assert data["success"] is True
                    assert "Restart command sent" in data["data"]["message"]

    def test_restart_openbk(self):
        with patch(
            "tools.iot_discovery._resolve_ip",
            return_value="192.168.1.101",
        ):
            with patch(
                "tools.iot_discovery._detect_device_type",
                return_value="openbk",
            ):
                with patch("tools.iot_control.requests.get") as mock_get:
                    resp = MagicMock()
                    resp.status_code = 200
                    mock_get.return_value = resp
                    result = _restart_device("192.168.1.101")
                    data = json.loads(result)
                    assert data["success"] is True
                    assert data["data"]["device_type"] == "openbk"

    def test_restart_by_name(self):
        with patch(
            "tools.iot_discovery._resolve_ip",
            return_value="192.168.1.100",
        ):
            with patch(
                "tools.iot_discovery._detect_device_type",
                return_value="tasmota",
            ):
                with patch("tools.iot_control.requests.get") as mock_get:
                    resp = MagicMock()
                    resp.status_code = 200
                    mock_get.return_value = resp
                    result = _restart_device("Curtains_LivingRoom")
                    data = json.loads(result)
                    assert data["success"] is True
                    assert data["data"]["resolved_from"] == "Curtains_LivingRoom"


class TestRestartErrors:
    """Edge case and error path tests for device restart."""

    def test_restart_name_not_resolved(self):
        with patch("tools.iot_discovery._resolve_ip", return_value=None):
            with patch("tools.iot_discovery._get_cached_devices", return_value=[]):
                result = _restart_device("UnknownDevice")
                data = json.loads(result)
                assert data["success"] is False
                assert "Could not resolve" in data["error"]["message"]

    def test_restart_tasmota_http_error(self):
        with patch("tools.iot_discovery._resolve_ip", return_value="192.168.1.100"):
            with patch("tools.iot_discovery._detect_device_type", return_value="tasmota"):
                with patch("tools.iot_control.requests.get") as mock_get:
                    resp = MagicMock()
                    resp.status_code = 500
                    mock_get.return_value = resp
                    result = _restart_device("192.168.1.100")
                    data = json.loads(result)
                    assert data["success"] is False
                    assert "Device not found" in data["error"]["message"]

    def test_restart_unsupported_type(self):
        with patch("tools.iot_discovery._resolve_ip", return_value="192.168.1.100"):
            with patch("tools.iot_discovery._detect_device_type", return_value="wiz"):
                result = _restart_device("192.168.1.100")
                data = json.loads(result)
                assert data["success"] is False
                assert "Device not found" in data["error"]["message"]


class TestWifiConfig:
    """Tests for WiFi configuration retrieval."""

    def test_get_wifi_tasmota(self):
        with patch(
            "tools.iot_discovery._resolve_ip",
            return_value="192.168.1.100",
        ):
            with patch(
                "tools.iot_discovery._detect_device_type",
                return_value="tasmota",
            ):
                with patch("tools.iot_control.requests.get") as mock_get:
                    resp = MagicMock()
                    resp.status_code = 200
                    resp.json.return_value = {
                        "StatusSTS": {
                            "Wifi": {
                                "SSId": "MyNetwork",
                                "RSSI": -60,
                                "Signal": -60,
                                "Mac": "AA:BB:CC:DD:EE:FF",
                                "IPAddress": "192.168.1.100",
                                "Gateway": "192.168.1.1",
                                "Mode": "11n",
                            }
                        }
                    }
                    mock_get.return_value = resp
                    result = _get_wifi_config("192.168.1.100")
                    data = json.loads(result)
                    assert data["success"] is True
                    assert data["data"]["wifi"]["ssid"] == "MyNetwork"
                    assert data["data"]["wifi"]["rssi"] == -60
                    assert data["data"]["wifi"]["mac"] == "AA:BB:CC:DD:EE:FF"

    def test_get_wifi_openbk(self):
        with patch(
            "tools.iot_discovery._resolve_ip",
            return_value="192.168.1.101",
        ):
            with patch(
                "tools.iot_discovery._detect_device_type",
                return_value="openbk",
            ):
                mock_status = {
                    "name": "My Light",
                    "ssid": "MyWiFi",
                    "rssi": -55,
                    "signal": -55,
                    "mac": "18:DE:50:34:F6:5F",
                    "ip": "192.168.1.101",
                    "gateway": "192.168.1.1",
                    "hostname": "my-light",
                    "dns": "192.168.1.1",
                }
                with patch(
                    "tools.iot_devices._get_openbk_status",
                    return_value=mock_status,
                ):
                    result = _get_wifi_config("192.168.1.101")
                    data = json.loads(result)
                    assert data["success"] is True
                    assert data["data"]["wifi"]["ssid"] == "MyWiFi"
                    assert data["data"]["wifi"]["rssi"] == -55
                    assert data["data"]["wifi"]["signal"] == -55
                    assert data["data"]["wifi"]["mac"] == "18:DE:50:34:F6:5F"
                    assert data["data"]["wifi"]["ip"] == "192.168.1.101"
                    assert data["data"]["wifi"]["gateway"] == "192.168.1.1"
                    assert data["data"]["wifi"]["hostname"] == "my-light"
                    assert data["data"]["wifi"]["dns"] == "192.168.1.1"

    def test_get_wifi_openbk_returns_all_fields(self):
        with patch(
            "tools.iot_discovery._resolve_ip",
            return_value="192.168.1.101",
        ):
            with patch(
                "tools.iot_discovery._detect_device_type",
                return_value="openbk",
            ):
                mock_status = {
                    "name": "OpenBK Test Device",
                    "ssid": "Test_SSID",
                    "rssi": 62,
                    "signal": -69,
                    "mac": "AA:BB:CC:DD:EE:11",
                    "ip": "192.168.1.101",
                    "gateway": "192.168.1.1",
                    "hostname": "openbk-test",
                    "dns": "192.168.1.1",
                }
                with patch(
                    "tools.iot_devices._get_openbk_status",
                    return_value=mock_status,
                ):
                    result = _get_wifi_config("192.168.1.101")
                    data = json.loads(result)
                    assert data["success"] is True
                    assert data["data"]["device_type"] == "openbk"
                    assert data["data"]["wifi"]["ssid"] == "Test_SSID"
                    assert data["data"]["wifi"]["rssi"] == 62
                    assert data["data"]["wifi"]["signal"] == -69
                    assert data["data"]["wifi"]["mac"] == "AA:BB:CC:DD:EE:11"
                    assert data["data"]["wifi"]["ip"] == "192.168.1.101"
                    assert data["data"]["wifi"]["gateway"] == "192.168.1.1"
                    assert data["data"]["wifi"]["hostname"] == "openbk-test"
                    assert data["data"]["wifi"]["dns"] == "192.168.1.1"

    def test_get_wifi_openbk_status_five_fallback(self):
        """Status 0 returned 404, so only HTML-scraped fields available."""
        with patch(
            "tools.iot_discovery._resolve_ip",
            return_value="192.168.1.101",
        ):
            with patch(
                "tools.iot_discovery._detect_device_type",
                return_value="openbk",
            ):
                mock_status = {
                    "name": "OpenBK Test Device",
                    "channels": [],
                    "rssi": -65,
                    "mac": "00:11:22:33:44:55",
                    "ip": None,
                    "gateway": None,
                    "hostname": None,
                    "dns": None,
                    "ssid": None,
                    "signal": None,
                    "signal_quality": "Good",
                    "version": "1.17.0",
                    "uptime_seconds": 3600,
                    "mqtt_connected": True,
                    "reboot_reason": None,
                }
                with patch(
                    "tools.iot_devices._get_openbk_status",
                    return_value=mock_status,
                ):
                    result = _get_wifi_config("192.168.1.101")
                    data = json.loads(result)
                    assert data["success"] is True
                    assert data["data"]["device_type"] == "openbk"
                    assert data["data"]["wifi"]["ssid"] is None
                    assert data["data"]["wifi"]["rssi"] == -65
                    assert data["data"]["wifi"]["signal"] is None
                    assert data["data"]["wifi"]["mac"] == "00:11:22:33:44:55"
                    assert data["data"]["wifi"]["ip"] is None
                    assert data["data"]["wifi"]["gateway"] is None
                    assert data["data"]["wifi"]["hostname"] is None
                    assert data["data"]["wifi"]["dns"] is None

    def test_get_wifi_by_name(self):
        with patch(
            "tools.iot_discovery._resolve_ip",
            return_value="192.168.1.100",
        ):
            with patch(
                "tools.iot_discovery._detect_device_type",
                return_value="tasmota",
            ):
                with patch("tools.iot_control.requests.get") as mock_get:
                    resp = MagicMock()
                    resp.status_code = 200
                    resp.json.return_value = {
                        "StatusSTS": {"Wifi": {"SSId": "HomeWiFi", "RSSI": -70}}
                    }
                    mock_get.return_value = resp
                    result = _get_wifi_config("Light_Bathroom")
                    data = json.loads(result)
                    assert data["success"] is True
                    assert data["data"]["resolved_from"] == "Light_Bathroom"


class TestWifiConfigErrors:
    """Edge case and error path tests for WiFi config."""

    def test_get_wifi_name_not_resolved(self):
        with patch("tools.iot_discovery._resolve_ip", return_value=None):
            with patch("tools.iot_discovery._get_cached_devices", return_value=[]):
                result = _get_wifi_config("UnknownDevice")
                data = json.loads(result)
                assert data["success"] is False
                assert "Could not resolve" in data["error"]["message"]

    def test_get_wifi_tasmota_http_error(self):
        with patch("tools.iot_discovery._resolve_ip", return_value="192.168.1.100"):
            with patch("tools.iot_discovery._detect_device_type", return_value="tasmota"):
                with patch("tools.iot_control.requests.get") as mock_get:
                    resp = MagicMock()
                    resp.status_code = 503
                    mock_get.return_value = resp
                    result = _get_wifi_config("192.168.1.100")
                    data = json.loads(result)
                    assert data["success"] is False
                    assert "Device not found" in data["error"]["message"]

    def test_get_wifi_unsupported_type(self):
        with patch("tools.iot_discovery._resolve_ip", return_value="192.168.1.100"):
            with patch("tools.iot_discovery._detect_device_type", return_value="matter"):
                result = _get_wifi_config("192.168.1.100")
                data = json.loads(result)
                assert data["success"] is False
                assert "Device not found" in data["error"]["message"]

    def test_get_wifi_openbk_device_unreachable(self):
        with patch(
            "tools.iot_discovery._resolve_ip",
            return_value="192.168.1.101",
        ):
            with patch(
                "tools.iot_discovery._detect_device_type",
                return_value=None,
            ):
                result = _get_wifi_config("192.168.1.101")
                data = json.loads(result)
                assert data["success"] is False
                assert "Device not found" in data["error"]["message"]


class TestRegistrationWrappers:
    """Tests for MCP tool registration wrappers and exception handlers."""

    def test_registration_creates_four_tools(self, mock_mcp):
        register_iot_control_tools(mock_mcp)
        assert "iot_set_power" in mock_mcp._tools
        assert "iot_set_brightness" in mock_mcp._tools
        assert "iot_restart_device" in mock_mcp._tools
        assert "iot_get_wifi_config" in mock_mcp._tools

    def test_iot_set_power_wrapper(self, mock_mcp):
        register_iot_control_tools(mock_mcp)
        fn = mock_mcp.get_tool("iot_set_power")
        with patch("tools.iot_discovery._resolve_ip", return_value="192.168.1.100"):
            with patch("tools.iot_discovery._detect_device_type", return_value="tasmota"):
                with patch("tools.iot_control.requests.get") as mock_get:
                    resp = MagicMock()
                    resp.status_code = 200
                    resp.json.return_value = {"POWER1": "ON"}
                    mock_get.return_value = resp
                    result = fn("192.168.1.100", "ON")
                    data = json.loads(result)
                    assert data["success"] is True

    def test_iot_set_brightness_wrapper(self, mock_mcp):
        register_iot_control_tools(mock_mcp)
        fn = mock_mcp.get_tool("iot_set_brightness")
        with patch("tools.iot_discovery._resolve_ip", return_value="192.168.1.100"):
            with patch("tools.iot_discovery._detect_device_type", return_value="tasmota"):
                with patch("tools.iot_control.requests.get") as mock_get:
                    resp = MagicMock()
                    resp.status_code = 200
                    mock_get.return_value = resp
                    result = fn("192.168.1.100", 50)
                    data = json.loads(result)
                    assert data["success"] is True

    def test_iot_restart_device_wrapper(self, mock_mcp):
        register_iot_control_tools(mock_mcp)
        fn = mock_mcp.get_tool("iot_restart_device")
        with patch("tools.iot_discovery._resolve_ip", return_value="192.168.1.100"):
            with patch("tools.iot_discovery._detect_device_type", return_value="tasmota"):
                with patch("tools.iot_control.requests.get") as mock_get:
                    resp = MagicMock()
                    resp.status_code = 200
                    mock_get.return_value = resp
                    result = fn("192.168.1.100")
                    data = json.loads(result)
                    assert data["success"] is True

    def test_iot_get_wifi_config_wrapper(self, mock_mcp):
        register_iot_control_tools(mock_mcp)
        fn = mock_mcp.get_tool("iot_get_wifi_config")
        with patch("tools.iot_discovery._resolve_ip", return_value="192.168.1.100"):
            with patch("tools.iot_discovery._detect_device_type", return_value="tasmota"):
                with patch("tools.iot_control.requests.get") as mock_get:
                    resp = MagicMock()
                    resp.status_code = 200
                    resp.json.return_value = {
                        "StatusSTS": {
                            "Wifi": {
                                "SSId": "TestNet",
                                "RSSI": -80,
                                "Signal": -80,
                                "Mac": "00:00:00:00:00:00",
                                "IPAddress": "192.168.1.100",
                                "Gateway": "192.168.1.1",
                                "Mode": "11g",
                            }
                        }
                    }
                    mock_get.return_value = resp
                    result = fn("192.168.1.100")
                    data = json.loads(result)
                    assert data["success"] is True

    def test_set_power_wrapper_exception_handler(self, mock_mcp):
        register_iot_control_tools(mock_mcp)
        fn = mock_mcp.get_tool("iot_set_power")
        with patch("tools.iot_control._set_power", side_effect=RuntimeError("boom")):
            result = fn("192.168.1.100", "ON")
            data = json.loads(result)
            assert data["success"] is False
            assert "boom" in data["error"]["message"]

    def test_set_brightness_wrapper_exception_handler(self, mock_mcp):
        register_iot_control_tools(mock_mcp)
        fn = mock_mcp.get_tool("iot_set_brightness")
        with patch("tools.iot_control._set_brightness", side_effect=ValueError("bad")):
            result = fn("192.168.1.100", 50)
            data = json.loads(result)
            assert data["success"] is False
            assert "bad" in data["error"]["message"]

    def test_restart_wrapper_exception_handler(self, mock_mcp):
        register_iot_control_tools(mock_mcp)
        fn = mock_mcp.get_tool("iot_restart_device")
        with patch("tools.iot_control._restart_device", side_effect=OSError("io")):
            result = fn("192.168.1.100")
            data = json.loads(result)
            assert data["success"] is False
            assert "io" in data["error"]["message"]

    def test_get_wifi_wrapper_exception_handler(self, mock_mcp):
        register_iot_control_tools(mock_mcp)
        fn = mock_mcp.get_tool("iot_get_wifi_config")
        with patch("tools.iot_control._get_wifi_config", side_effect=Exception("fail")):
            result = fn("192.168.1.100")
            data = json.loads(result)
            assert data["success"] is False
            assert "fail" in data["error"]["message"]


class TestWriteGuardDisabled:
    """Write guard: tools must return WRITE_DISABLED when ENABLE_WRITE_OPERATIONS=0."""

    def test_set_power_rejected_when_write_disabled(self, mock_mcp, monkeypatch):
        monkeypatch.setattr("tools.constants.ENABLE_WRITE_OPERATIONS", False)
        register_iot_control_tools(mock_mcp)
        fn = mock_mcp.get_tool("iot_set_power")
        with patch("tools.iot_discovery._resolve_ip", return_value="192.168.1.100"):
            with patch("tools.iot_discovery._detect_device_type", return_value="tasmota"):
                with patch("tools.iot_control.requests.get") as mock_get:
                    resp = MagicMock()
                    resp.status_code = 200
                    mock_get.return_value = resp
                    result = fn("192.168.1.100", "ON")
                    data = json.loads(result)
                    assert data["success"] is False
                    assert data["error"]["code"] == "WRITE_DISABLED"
                    mock_get.assert_not_called()

    def test_set_brightness_rejected_when_write_disabled(self, mock_mcp, monkeypatch):
        monkeypatch.setattr("tools.constants.ENABLE_WRITE_OPERATIONS", False)
        register_iot_control_tools(mock_mcp)
        fn = mock_mcp.get_tool("iot_set_brightness")
        with patch("tools.iot_discovery._resolve_ip", return_value="192.168.1.100"):
            with patch("tools.iot_discovery._detect_device_type", return_value="tasmota"):
                with patch("tools.iot_control.requests.get") as mock_get:
                    resp = MagicMock()
                    resp.status_code = 200
                    mock_get.return_value = resp
                    result = fn("192.168.1.100", 50)
                    data = json.loads(result)
                    assert data["success"] is False
                    assert data["error"]["code"] == "WRITE_DISABLED"
                    mock_get.assert_not_called()

    def test_restart_rejected_when_write_disabled(self, mock_mcp, monkeypatch):
        monkeypatch.setattr("tools.constants.ENABLE_WRITE_OPERATIONS", False)
        register_iot_control_tools(mock_mcp)
        fn = mock_mcp.get_tool("iot_restart_device")
        with patch("tools.iot_discovery._resolve_ip", return_value="192.168.1.100"):
            with patch("tools.iot_discovery._detect_device_type", return_value="tasmota"):
                with patch("tools.iot_control.requests.get") as mock_get:
                    resp = MagicMock()
                    resp.status_code = 200
                    mock_get.return_value = resp
                    result = fn("192.168.1.100")
                    data = json.loads(result)
                    assert data["success"] is False
                    assert data["error"]["code"] == "WRITE_DISABLED"


class TestTuyaDispatch:
    def test_set_power_tuya(self):
        from tools.iot_control import _set_power

        with (
            patch("tools.iot_discovery._resolve_ip", return_value="192.168.1.150"),
            patch("tools.iot_discovery._detect_device_type", return_value="tuya"),
            patch("tools.iot_tuya._tuya_set_value", return_value='{"success": true}'),
            patch("tools.validators.validate_power_state", return_value="ON"),
        ):
            result = _set_power("test_device", "ON")
            assert '"success": true' in result

    def test_restart_device_tuya_unsupported(self):
        from tools.iot_control import _restart_device

        with (
            patch("tools.iot_control._resolve_or_fail", return_value="192.168.1.150"),
            patch("tools.iot_discovery._detect_device_type", return_value="tuya"),
        ):
            result = _restart_device("test_device")
            assert "UNSUPPORTED_OPERATION" in result


class TestOpenHASPDispatch:
    def test_set_power_openhasp(self):
        from tools.iot_control import _set_power

        with (
            patch("tools.iot_discovery._resolve_ip", return_value="192.168.0.239"),
            patch("tools.iot_discovery._detect_device_type", return_value="openhasp"),
            patch("tools.validators.validate_power_state", return_value="ON"),
            patch("tools.openhasp.telnet.OpenHASPTelnet") as mock_tn_cls,
        ):
            mock_tn = MagicMock()
            mock_tn.connect.return_value = True
            mock_tn_cls.return_value = mock_tn
            result = _set_power("192.168.0.239", "ON")
            assert '"success": true' in result

    def test_restart_device_openhasp(self):
        from tools.iot_control import _restart_device

        with (
            patch("tools.iot_control._resolve_or_fail", return_value="192.168.0.239"),
            patch("tools.iot_discovery._detect_device_type", return_value="openhasp"),
            patch("tools.openhasp.telnet.OpenHASPTelnet") as mock_tn_cls,
        ):
            mock_tn = MagicMock()
            mock_tn.connect.return_value = True
            mock_tn_cls.return_value = mock_tn
            result = _restart_device("192.168.0.239")
            assert '"success": true' in result
