"""
Unit tests for IoT MCP device information tools.
"""

import json
from unittest.mock import MagicMock, patch

import pytest

from tools.iot_devices import (
    _get_device_info,
    _get_device_power,
    _get_openbk_status,
    _get_tasmota_status,
    register_iot_device_tools,
)

pytestmark = pytest.mark.unit


class TestGetOpenBKStatus:
    """Tests for OpenBK status retrieval."""

    def test_get_openbk_status_success(self):
        """Should parse OpenBK HTML and extract status."""
        with patch("tools.iot_devices.requests.get") as mock_get:
            resp = MagicMock()
            resp.status_code = 200
            resp.text = """
            <html><head><title>My Light</title></head>
            <body>
            <h5>Channel 0 = 1.00, Channel 1 = 0.00</h5>
            <h5>Wifi RSSI: Good (-55dBm)</h5>
            <h5>Device MAC: 18:DE:50:34:F6:5F</h5>
            <h5>MQTT State: <span style="color:green">connected</span></h5>
            <h5>Reboot reason: 0 - Pwr</h5>
            version 1.17.273
            </body></html>
            """
            mock_get.return_value = resp

            status = _get_openbk_status("192.168.1.101")

            assert status["name"] == "My Light"
            assert status["rssi"] == -55
            assert status["mac"] == "18:DE:50:34:F6:5F"
            assert status["version"] == "1.17.273"
            assert status["mqtt_connected"] is True
            assert status["reboot_reason"]["code"] == 0
            assert len(status["channels"]) == 2

    def test_get_openbk_status_http_error(self):
        """Should return error on HTTP failure."""
        with patch("tools.iot_devices.requests.get") as mock_get:
            resp = MagicMock()
            resp.status_code = 404
            mock_get.return_value = resp

            status = _get_openbk_status("192.168.1.101")
            assert "error" in status
            assert "404" in status["error"]

    def test_get_openbk_status_timeout(self):
        """Should return error on timeout."""
        with patch(
            "tools.iot_devices.requests.get",
            side_effect=Exception("Connection timeout"),
        ):
            status = _get_openbk_status("192.168.1.101")
            assert "error" in status

    def test_get_openbk_status_uptime(self):
        """Should extract uptime from data-initial attribute."""
        with patch("tools.iot_devices.requests.get") as mock_get:
            resp = MagicMock()
            resp.status_code = 200
            resp.text = (
                '<html><head><title>Test</title></head><body data-initial="3600"></body></html>'
            )
            mock_get.return_value = resp
            status = _get_openbk_status("192.168.1.101")
            assert status["uptime_seconds"] == 3600


class TestGetTasmotaStatus:
    """Tests for Tasmota status retrieval."""

    def test_get_tasmota_status_success(self):
        """Should parse Tasmota JSON and extract status."""
        with patch("tools.iot_devices.requests.get") as mock_get:

            def mock_response(url, **kwargs):
                resp = MagicMock()
                resp.status_code = 200
                if "Status%200" in url:
                    resp.json.return_value = {
                        "Status": {
                            "FriendlyName": ["TestDevice"],
                            "DeviceName": "TestDevice",
                            "Topic": "device_test",
                            "Power": 1,
                            "Version": "12.5.0",
                            "Module": 0,
                            "SaveData": 1,
                            "PowerOnState": 3,
                        }
                    }
                elif "Status%205" in url:
                    resp.json.return_value = {
                        "StatusSTS": {
                            "Wifi": {
                                "RSSI": -65,
                                "SSId": "MyNetwork",
                                "Mac": "AA:BB:CC:DD:EE:FF",
                                "IPAddress": "192.168.1.100",
                                "Mode": "11n",
                            }
                        }
                    }
                elif "Power" in url and "%20" not in url:
                    resp.json.return_value = {"POWER": "ON"}
                return resp

            mock_get.side_effect = mock_response

            status = _get_tasmota_status("192.168.1.100")

            assert status["name"] == "TestDevice"
            assert status["power_state"] == 1
            assert status["current_power"] == "ON"
            assert status["version"] == "12.5.0"
            assert status["rssi"] == -65
            assert status["mac"] == "AA:BB:CC:DD:EE:FF"

    def test_get_tasmota_status_no_wifi(self):
        """Should handle missing WiFi data gracefully."""
        with patch("tools.iot_devices.requests.get") as mock_get:

            def mock_response(url, **kwargs):
                resp = MagicMock()
                if "Status%200" in url:
                    resp.status_code = 200
                    resp.json.return_value = {
                        "Status": {
                            "FriendlyName": ["TestDevice"],
                            "Version": "12.5.0",
                        }
                    }
                else:
                    resp.status_code = 404
                return resp

            mock_get.side_effect = mock_response

            status = _get_tasmota_status("192.168.1.100")
            assert status["name"] == "TestDevice"
            assert status["rssi"] is None

    def test_get_tasmota_status_http_error(self):
        """Should return error on non-200 Status response."""
        with patch("tools.iot_devices.requests.get") as mock_get:
            resp = MagicMock()
            resp.status_code = 500
            mock_get.return_value = resp
            status = _get_tasmota_status("192.168.1.100")
            assert status == {"error": "HTTP 500"}

    def test_get_tasmota_status_wifi_exception(self):
        """Should handle WiFi request exception gracefully."""
        with patch("tools.iot_devices.requests.get") as mock_get:

            def mock_response(url, **kwargs):
                resp = MagicMock()
                if "Status%200" in url:
                    resp.status_code = 200
                    resp.json.return_value = {
                        "Status": {
                            "FriendlyName": ["TestDevice"],
                            "Version": "12.5.0",
                        }
                    }
                elif "Status%205" in url:
                    raise Exception("WiFi timeout")
                else:
                    resp.status_code = 404
                return resp

            mock_get.side_effect = mock_response

            status = _get_tasmota_status("192.168.1.100")
            assert status["name"] == "TestDevice"
            assert status["rssi"] is None

    def test_get_tasmota_status_power_exception(self):
        """Should handle Power request exception gracefully."""
        with patch("tools.iot_devices.requests.get") as mock_get:

            def mock_response(url, **kwargs):
                resp = MagicMock()
                if "Status%200" in url:
                    resp.status_code = 200
                    resp.json.return_value = {
                        "Status": {
                            "FriendlyName": ["TestDevice"],
                            "Version": "12.5.0",
                        }
                    }
                elif "Power" in url and "%20" not in url:
                    raise Exception("Power timeout")
                else:
                    resp.status_code = 404
                return resp

            mock_get.side_effect = mock_response

            status = _get_tasmota_status("192.168.1.100")
            assert status["name"] == "TestDevice"
            assert status["current_power"] is None

    def test_get_tasmota_status_outer_exception(self):
        """Should catch outer exception from primary request."""
        with patch(
            "tools.iot_devices.requests.get",
            side_effect=Exception("Connection refused"),
        ):
            status = _get_tasmota_status("192.168.1.100")
            assert status == {"error": "Connection refused"}


class TestGetDeviceInfo:
    """Tests for device info tool."""

    def test_get_device_info_by_ip(self):
        """Should resolve IP directly and return info."""
        with patch("tools.iot_discovery._resolve_ip", return_value="192.168.1.100"):
            with patch(
                "tools.iot_discovery._detect_device_type",
                return_value="tasmota",
            ):
                with patch("tools.iot_devices._get_tasmota_status") as mock_status:
                    mock_status.return_value = {
                        "name": "TestDevice",
                        "power_state": 0,
                    }
                    result = _get_device_info("192.168.1.100")
                    data = json.loads(result)
                    assert data["success"] is True
                    assert data["data"]["ip_address"] == "192.168.1.100"

    def test_get_device_info_name_not_found(self):
        """Should suggest discovery when name not in cache."""
        with patch("tools.iot_discovery._resolve_ip", return_value=None):
            with patch("tools.iot_discovery._get_cached_devices", return_value=[]):
                result = _get_device_info("UnknownDevice")
                data = json.loads(result)
                assert data["success"] is False
                assert "Could not resolve" in data["error"]["message"]

    def test_get_device_info_openbk(self):
        """Should route to OpenBK status for openbk devices."""
        with patch("tools.iot_discovery._resolve_ip", return_value="192.168.1.101"):
            with patch(
                "tools.iot_discovery._detect_device_type",
                return_value="openbk",
            ):
                with patch("tools.iot_devices._get_openbk_status") as mock_status:
                    mock_status.return_value = {
                        "name": "OpenBK_Test",
                        "channels": [],
                    }
                    result = _get_device_info("192.168.1.101")
                    data = json.loads(result)
                    assert data["success"] is True
                    assert data["data"]["device_type"] == "openbk"

    def test_get_device_info_device_not_found_at_ip(self):
        """Should error when no device detected at IP."""
        with patch("tools.iot_discovery._resolve_ip", return_value="192.168.1.200"):
            with patch("tools.iot_discovery._detect_device_type", return_value=None):
                result = _get_device_info("192.168.1.200")
                data = json.loads(result)
                assert data["success"] is False
                assert "No IoT device found" in data["error"]["message"]

    def test_get_device_info_unknown_type(self):
        """Should error for unsupported device type."""
        with patch("tools.iot_discovery._resolve_ip", return_value="192.168.1.100"):
            with patch(
                "tools.iot_discovery._detect_device_type",
                return_value="esphome",
            ):
                result = _get_device_info("192.168.1.100")
                data = json.loads(result)
                assert data["success"] is False
                assert "Unknown device type" in data["error"]["message"]

    def test_get_device_info_status_error_propagation(self):
        """Should propagate error from status function."""
        with patch("tools.iot_discovery._resolve_ip", return_value="192.168.1.100"):
            with patch(
                "tools.iot_discovery._detect_device_type",
                return_value="tasmota",
            ):
                with patch("tools.iot_devices._get_tasmota_status") as mock_status:
                    mock_status.return_value = {"error": "Device unreachable"}
                    result = _get_device_info("192.168.1.100")
                    data = json.loads(result)
                    assert data["success"] is False
                    assert "Device unreachable" in data["error"]["message"]


class TestGetDevicePower:
    """Tests for power state query."""

    def test_get_device_power_tasmota(self):
        """Should query Tasmota power state."""
        with patch("tools.iot_discovery._resolve_ip", return_value="192.168.1.100"):
            with patch(
                "tools.iot_discovery._detect_device_type",
                return_value="tasmota",
            ):
                with patch("tools.iot_devices.requests.get") as mock_get:
                    resp = MagicMock()
                    resp.status_code = 200
                    resp.json.return_value = {"POWER": "ON"}
                    mock_get.return_value = resp

                    result = _get_device_power("192.168.1.100")
                    data = json.loads(result)
                    assert data["success"] is True
                    assert data["data"]["state"] == "ON"

    def test_get_device_power_openbk(self):
        """Should query OpenBK power state."""
        with patch("tools.iot_discovery._resolve_ip", return_value="192.168.1.101"):
            with patch(
                "tools.iot_discovery._detect_device_type",
                return_value="openbk",
            ):
                with patch("tools.iot_devices._get_openbk_status") as mock_status:
                    mock_status.return_value = {
                        "channels": [
                            {"channel": 0, "value": 1.0},
                        ]
                    }
                    result = _get_device_power("192.168.1.101")
                    data = json.loads(result)
                    assert data["success"] is True
                    assert data["data"]["state"] == "ON"
                    assert data["data"]["value"] == 1.0

    def test_get_device_power_name_not_resolved(self):
        """Should suggest discovery when name not in cache."""
        with patch("tools.iot_discovery._resolve_ip", return_value=None):
            with patch("tools.iot_discovery._get_cached_devices", return_value=[]):
                result = _get_device_power("UnknownDevice")
                data = json.loads(result)
                assert data["success"] is False
                assert "Could not resolve" in data["error"]["message"]

    def test_get_device_power_tasmota_exception(self):
        """Should handle Tasmota power request exception."""
        with patch("tools.iot_discovery._resolve_ip", return_value="192.168.1.100"):
            with patch(
                "tools.iot_discovery._detect_device_type",
                return_value="tasmota",
            ):
                with patch(
                    "tools.iot_devices.requests.get",
                    side_effect=Exception("Timeout"),
                ):
                    result = _get_device_power("192.168.1.100")
                    data = json.loads(result)
                    assert data["success"] is False
                    assert "Timeout" in data["error"]["message"]

    def test_get_device_power_unknown_type(self):
        """Should error for unsupported device type."""
        with patch("tools.iot_discovery._resolve_ip", return_value="192.168.1.100"):
            with patch(
                "tools.iot_discovery._detect_device_type",
                return_value="zigbee",
            ):
                result = _get_device_power("192.168.1.100")
                data = json.loads(result)
                assert data["success"] is False
                assert "Device not found or unsupported" in data["error"]["message"]


class TestGetDeviceInfoTuyaErrors:
    """Tests for Tuya integration path in device info retrieval."""

    def test_get_device_info_tuya_success(self):
        """Should return info when Tuya status query succeeds."""
        with patch("tools.iot_discovery._resolve_ip", return_value="192.168.1.100"):
            with patch(
                "tools.iot_discovery._detect_device_type",
                return_value="tuya",
            ):
                with patch("tools.iot_devices._get_openbk_status"):
                    with patch("tools.iot_devices._get_tasmota_status"):
                        with patch("tools.iot_tuya._tuya_status") as mock_tuya:
                            mock_tuya.return_value = json.dumps(
                                {
                                    "success": True,
                                    "data": {
                                        "name": "Tuya_Device",
                                        "device_id": "abc123",
                                        "transport": "local",
                                        "dps": {"1": True},
                                        "dps_spec": {},
                                    },
                                }
                            )
                            result = _get_device_info("192.168.1.100")
                            data = json.loads(result)
                            assert data["success"] is True
                            assert data["data"]["device_type"] == "tuya"
                            assert data["data"]["info"]["name"] == "Tuya_Device"

    def test_get_device_info_tuya_status_error(self):
        """Should propagate error when Tuya status returns failure."""
        with patch("tools.iot_discovery._resolve_ip", return_value="192.168.1.100"):
            with patch(
                "tools.iot_discovery._detect_device_type",
                return_value="tuya",
            ):
                with patch("tools.iot_devices._get_openbk_status"):
                    with patch("tools.iot_devices._get_tasmota_status"):
                        with patch("tools.iot_tuya._tuya_status") as mock_tuya:
                            mock_tuya.return_value = json.dumps(
                                {"success": False, "error": "Device offline"}
                            )
                            result = _get_device_info("192.168.1.100")
                            data = json.loads(result)
                            assert data["success"] is False
                            assert "Device offline" in data["error"]["message"]

    def test_get_device_info_tuya_exception(self):
        """Should handle exception from Tuya status query."""
        with patch("tools.iot_discovery._resolve_ip", return_value="192.168.1.100"):
            with patch(
                "tools.iot_discovery._detect_device_type",
                return_value="tuya",
            ):
                with patch("tools.iot_devices._get_openbk_status"):
                    with patch("tools.iot_devices._get_tasmota_status"):
                        with patch(
                            "tools.iot_tuya._tuya_status",
                            side_effect=Exception("Tuya unreachable"),
                        ):
                            result = _get_device_info("192.168.1.100")
                            data = json.loads(result)
                            assert data["success"] is False
                            assert "Tuya status query failed" in data["error"]["message"]


class TestGetDeviceInfoOpenHASPErrors:
    """Tests for OpenHASP integration path in device info retrieval."""

    def test_get_device_info_openhasp_success(self):
        """Should return info when OpenHASP status query succeeds."""
        with patch("tools.iot_discovery._resolve_ip", return_value="192.168.1.100"):
            with patch(
                "tools.iot_discovery._detect_device_type",
                return_value="openhasp",
            ):
                with patch("tools.iot_devices._get_openbk_status"):
                    with patch("tools.iot_devices._get_tasmota_status"):
                        with patch("tools.iot_openhasp._openhasp_status") as mock_hasp:
                            mock_hasp.return_value = json.dumps(
                                {
                                    "success": True,
                                    "data": {
                                        "name": "HASP_Test",
                                        "version": "0.7.9",
                                        "tft_driver": "ILI9341",
                                        "objects_count": 15,
                                        "bckl": 255,
                                        "rssi": -50,
                                        "mac": "AA:BB:CC:DD:EE:FF",
                                    },
                                }
                            )
                            result = _get_device_info("192.168.1.100")
                            data = json.loads(result)
                            assert data["success"] is True
                            assert data["data"]["device_type"] == "openhasp"
                            assert data["data"]["info"]["name"] == "HASP_Test"

    def test_get_device_info_openhasp_status_error(self):
        """Should propagate error when OpenHASP status returns failure."""
        with patch("tools.iot_discovery._resolve_ip", return_value="192.168.1.100"):
            with patch(
                "tools.iot_discovery._detect_device_type",
                return_value="openhasp",
            ):
                with patch("tools.iot_devices._get_openbk_status"):
                    with patch("tools.iot_devices._get_tasmota_status"):
                        with patch("tools.iot_openhasp._openhasp_status") as mock_hasp:
                            mock_hasp.return_value = json.dumps(
                                {"success": False, "error": "Connection refused"}
                            )
                            result = _get_device_info("192.168.1.100")
                            data = json.loads(result)
                            assert data["success"] is False
                            assert "Connection refused" in data["error"]["message"]

    def test_get_device_info_openhasp_exception(self):
        """Should handle exception from OpenHASP status query gracefully."""
        with patch("tools.iot_discovery._resolve_ip", return_value="192.168.1.100"):
            with patch(
                "tools.iot_discovery._detect_device_type",
                return_value="openhasp",
            ):
                with patch("tools.iot_devices._get_openbk_status"):
                    with patch("tools.iot_devices._get_tasmota_status"):
                        with patch(
                            "tools.iot_openhasp._openhasp_status",
                            side_effect=Exception("HASP timeout"),
                        ):
                            result = _get_device_info("192.168.1.100")
                            data = json.loads(result)
                            assert data["success"] is False
                            assert "error" in data


class TestGetDevicePowerTasmotaErrors:
    """Tests for Tasmota power error paths."""

    def test_get_device_power_tasmota_http_500(self):
        """Should return error when Tasmota returns HTTP 500."""
        with patch("tools.iot_discovery._resolve_ip", return_value="192.168.1.100"):
            with patch(
                "tools.iot_discovery._detect_device_type",
                return_value="tasmota",
            ):
                with patch("tools.iot_devices.requests.get") as mock_get:
                    resp = MagicMock()
                    resp.status_code = 500
                    mock_get.return_value = resp
                    result = _get_device_power("192.168.1.100")
                    data = json.loads(result)
                    assert data["success"] is False
                    assert "Device not found or unsupported" in data["error"]["message"]

    def test_get_device_power_tasmota_invalid_json(self):
        """Should handle non-JSON response from Tasmota device."""
        with patch("tools.iot_discovery._resolve_ip", return_value="192.168.1.100"):
            with patch(
                "tools.iot_discovery._detect_device_type",
                return_value="tasmota",
            ):
                with patch("tools.iot_devices.requests.get") as mock_get:
                    resp = MagicMock()
                    resp.status_code = 200
                    resp.json.side_effect = json.JSONDecodeError("Expecting value", "doc", 0)
                    mock_get.return_value = resp
                    result = _get_device_power("192.168.1.100")
                    data = json.loads(result)
                    assert data["success"] is False
                    assert "Expecting value" in data["error"]["message"]

    def test_get_device_power_tasmota_connection_error(self):
        """Should handle ConnectionError when device unreachable."""
        with patch("tools.iot_discovery._resolve_ip", return_value="192.168.1.100"):
            with patch(
                "tools.iot_discovery._detect_device_type",
                return_value="tasmota",
            ):
                with patch(
                    "tools.iot_devices.requests.get",
                    side_effect=Exception("Connection refused"),
                ):
                    result = _get_device_power("192.168.1.100")
                    data = json.loads(result)
                    assert data["success"] is False
                    assert "Connection refused" in data["error"]["message"]

    def test_get_device_power_tasmota_multi_channel(self):
        """Should use POWER2 key for channel 2 on Tasmota."""
        with patch("tools.iot_discovery._resolve_ip", return_value="192.168.1.100"):
            with patch(
                "tools.iot_discovery._detect_device_type",
                return_value="tasmota",
            ):
                with patch("tools.iot_devices.requests.get") as mock_get:
                    resp = MagicMock()
                    resp.status_code = 200
                    resp.json.return_value = {"POWER2": "ON", "POWER": "OFF"}
                    mock_get.return_value = resp
                    result = _get_device_power("192.168.1.100", channel=2)
                    data = json.loads(result)
                    assert data["success"] is True
                    assert data["data"]["state"] == "ON"
                    assert data["data"]["channel"] == 2


class TestGetDevicePowerOpenBKErrors:
    """Tests for OpenBK power error paths."""

    def test_get_device_power_openbk_no_channels(self):
        """Should return OFF when OpenBK has no channels defined."""
        with patch("tools.iot_discovery._resolve_ip", return_value="192.168.1.101"):
            with patch(
                "tools.iot_discovery._detect_device_type",
                return_value="openbk",
            ):
                with patch("tools.iot_devices._get_openbk_status") as mock_status:
                    mock_status.return_value = {"channels": []}
                    result = _get_device_power("192.168.1.101")
                    data = json.loads(result)
                    assert data["success"] is True
                    assert data["data"]["state"] == "OFF"
                    assert data["data"]["value"] == 0

    def test_get_device_power_openbk_channel_3(self):
        """Should look up channel index 2 for channel 3 on OpenBK."""
        with patch("tools.iot_discovery._resolve_ip", return_value="192.168.1.101"):
            with patch(
                "tools.iot_discovery._detect_device_type",
                return_value="openbk",
            ):
                with patch("tools.iot_devices._get_openbk_status") as mock_status:
                    mock_status.return_value = {
                        "channels": [
                            {"channel": 0, "value": 0.0},
                            {"channel": 1, "value": 0.0},
                            {"channel": 2, "value": 1.0},
                        ]
                    }
                    result = _get_device_power("192.168.1.101", channel=3)
                    data = json.loads(result)
                    assert data["success"] is True
                    assert data["data"]["state"] == "ON"
                    assert data["data"]["value"] == 1.0

    def test_get_device_power_openbk_channel_not_found(self):
        """Should return OFF when channel index not in available channels."""
        with patch("tools.iot_discovery._resolve_ip", return_value="192.168.1.101"):
            with patch(
                "tools.iot_discovery._detect_device_type",
                return_value="openbk",
            ):
                with patch("tools.iot_devices._get_openbk_status") as mock_status:
                    mock_status.return_value = {"channels": [{"channel": 0, "value": 0.0}]}
                    result = _get_device_power("192.168.1.101", channel=3)
                    data = json.loads(result)
                    assert data["success"] is True
                    assert data["data"]["state"] == "OFF"


class TestGetDevicePowerTuyaErrors:
    """Tests for Tuya power integration paths."""

    def test_get_device_power_tuya_success_bool_dp(self):
        """Should return ON when Tuya DP 1 is True (bool)."""
        with patch("tools.iot_discovery._resolve_ip", return_value="192.168.1.100"):
            with patch(
                "tools.iot_discovery._detect_device_type",
                return_value="tuya",
            ):
                with patch("tools.iot_tuya._tuya_status") as mock_tuya:
                    mock_tuya.return_value = json.dumps(
                        {
                            "success": True,
                            "data": {"dps": {"1": True}},
                        }
                    )
                    result = _get_device_power("192.168.1.100")
                    data = json.loads(result)
                    assert data["success"] is True
                    assert data["data"]["state"] == "ON"
                    assert data["data"]["device_type"] == "tuya"

    def test_get_device_power_tuya_success_str_dp(self):
        """Should return ON when Tuya DP 1 is 'on' (string)."""
        with patch("tools.iot_discovery._resolve_ip", return_value="192.168.1.100"):
            with patch(
                "tools.iot_discovery._detect_device_type",
                return_value="tuya",
            ):
                with patch("tools.iot_tuya._tuya_status") as mock_tuya:
                    mock_tuya.return_value = json.dumps(
                        {
                            "success": True,
                            "data": {"dps": {"1": "on"}},
                        }
                    )
                    result = _get_device_power("192.168.1.100")
                    data = json.loads(result)
                    assert data["success"] is True
                    assert data["data"]["state"] == "ON"

    def test_get_device_power_tuya_status_error(self):
        """Should propagate Tuya status error directly."""
        with patch("tools.iot_discovery._resolve_ip", return_value="192.168.1.100"):
            with patch(
                "tools.iot_discovery._detect_device_type",
                return_value="tuya",
            ):
                with patch("tools.iot_tuya._tuya_status") as mock_tuya:
                    mock_tuya.return_value = json.dumps({"success": False, "error": "No local key"})
                    result = _get_device_power("192.168.1.100")
                    data = json.loads(result)
                    assert data["success"] is False
                    assert "No local key" in data["error"]

    def test_get_device_power_tuya_success_int_dp(self):
        """Should return ON when Tuya DP 1 is numeric 1 (int)."""
        with patch("tools.iot_discovery._resolve_ip", return_value="192.168.1.100"):
            with patch(
                "tools.iot_discovery._detect_device_type",
                return_value="tuya",
            ):
                with patch("tools.iot_tuya._tuya_status") as mock_tuya:
                    mock_tuya.return_value = json.dumps(
                        {
                            "success": True,
                            "data": {"dps": {"1": 1}},
                        }
                    )
                    result = _get_device_power("192.168.1.100")
                    data = json.loads(result)
                    assert data["success"] is True
                    assert data["data"]["state"] == "ON"

    def test_get_device_power_tuya_exception(self):
        """Should handle exception from Tuya status query."""
        with patch("tools.iot_discovery._resolve_ip", return_value="192.168.1.100"):
            with patch(
                "tools.iot_discovery._detect_device_type",
                return_value="tuya",
            ):
                with patch(
                    "tools.iot_tuya._tuya_status",
                    side_effect=Exception("Tuya connection lost"),
                ):
                    result = _get_device_power("192.168.1.100")
                    data = json.loads(result)
                    assert data["success"] is False
                    assert "Tuya connection lost" in data["error"]["message"]


class TestGetDevicePowerOpenHASP:
    """Tests for OpenHASP power state via Telnet."""

    def test_get_device_power_openhasp_success(self):
        """Should return ON when Telnet backlight query succeeds."""
        with patch("tools.iot_discovery._resolve_ip", return_value="192.168.1.100"):
            with patch(
                "tools.iot_discovery._detect_device_type",
                return_value="openhasp",
            ):
                with patch("tools.openhasp.telnet.OpenHASPTelnet") as mock_tn_cls:
                    mock_tn = MagicMock()
                    mock_tn.connect.return_value = True
                    mock_tn.backlight_query.return_value = {
                        "state": "on",
                        "brightness": 255,
                    }
                    mock_tn_cls.return_value = mock_tn
                    result = _get_device_power("192.168.1.100")
                    data = json.loads(result)
                    assert data["success"] is True
                    assert data["data"]["state"] == "ON"
                    assert data["data"]["device_type"] == "openhasp"
                    mock_tn.disconnect.assert_called_once()

    def test_get_device_power_openhasp_connection_fail(self):
        """Should return error when Telnet connection fails."""
        with patch("tools.iot_discovery._resolve_ip", return_value="192.168.1.100"):
            with patch(
                "tools.iot_discovery._detect_device_type",
                return_value="openhasp",
            ):
                with patch("tools.openhasp.telnet.OpenHASPTelnet") as mock_tn_cls:
                    mock_tn = MagicMock()
                    mock_tn.connect.return_value = False
                    mock_tn_cls.return_value = mock_tn
                    result = _get_device_power("192.168.1.100")
                    data = json.loads(result)
                    assert data["success"] is False
                    assert "Telnet connection failed" in data["error"]["message"]

    def test_get_device_power_openhasp_exception(self):
        """Should handle exception from Telnet operations."""
        with patch("tools.iot_discovery._resolve_ip", return_value="192.168.1.100"):
            with patch(
                "tools.iot_discovery._detect_device_type",
                return_value="openhasp",
            ):
                with patch(
                    "tools.openhasp.telnet.OpenHASPTelnet",
                    side_effect=Exception("Telnet timeout"),
                ):
                    result = _get_device_power("192.168.1.100")
                    data = json.loads(result)
                    assert data["success"] is False
                    assert "Telnet timeout" in data["error"]["message"]


class TestGetOpenBKStatusEdgeCases:
    """Tests for OpenBK status edge cases and error handling."""

    def test_get_openbk_status_connection_error(self):
        """Should return error on requests.ConnectionError."""
        with patch(
            "tools.iot_devices.requests.get",
            side_effect=Exception("Connection refused"),
        ):
            status = _get_openbk_status("192.168.1.101")
            assert "error" in status
            assert "Connection refused" in status["error"]

    def test_get_openbk_status_minimal_html(self):
        """Should handle minimal HTML without optional fields."""
        with patch("tools.iot_devices.requests.get") as mock_get:

            def mock_response(url, **kwargs):
                resp = MagicMock()
                resp.status_code = 200
                if "index" in url:
                    resp.text = "<html><head><title>Minimal</title></head><body></body></html>"
                elif "Status%200" in url:
                    resp.json.side_effect = ValueError("not json")
                return resp

            mock_get.side_effect = mock_response
            status = _get_openbk_status("192.168.1.101")
            assert status["name"] == "Minimal"
            assert status["channels"] == []
            assert status["rssi"] is None
            assert status["mac"] is None
            assert status["version"] is None
            assert status["mqtt_connected"] is False
            assert status["reboot_reason"] is None

    def test_get_openbk_status_with_status_zero_enrichment(self):
        """Should enrich status with WiFi/network data from Status 0 JSON."""
        with patch("tools.iot_devices.requests.get") as mock_get:

            def mock_response(url, **kwargs):
                resp = MagicMock()
                resp.status_code = 200
                if "index" in url:
                    resp.text = "<html><head><title>Test</title></head><body></body></html>"
                elif "Status%200" in url:
                    resp.json.return_value = {
                        "StatusSTS": {
                            "Wifi": {
                                "SSId": "HomeWiFi",
                                "RSSI": -50,
                                "Signal": -50,
                            }
                        },
                        "StatusNET": {
                            "Mac": "AA:BB:CC:DD:EE:FF",
                            "IPAddress": "192.168.1.200",
                            "Gateway": "192.168.1.1",
                            "Hostname": "test-device",
                            "DNSServer1": "192.168.1.1",
                        },
                    }
                return resp

            mock_get.side_effect = mock_response
            status = _get_openbk_status("192.168.1.101")
            assert status["ssid"] == "HomeWiFi"
            assert status["rssi"] == -50
            assert status["signal"] == -50
            assert status["mac"] == "AA:BB:CC:DD:EE:FF"
            assert status["ip"] == "192.168.1.200"
            assert status["gateway"] == "192.168.1.1"
            assert status["hostname"] == "test-device"
            assert status["dns"] == "192.168.1.1"


class TestGetTasmotaStatusEdgeCases:
    """Tests for Tasmota status edge cases."""

    def test_get_tasmota_status_wifi_http_404(self):
        """Should handle WiFi endpoint returning non-200."""
        with patch("tools.iot_devices.requests.get") as mock_get:

            def mock_response(url, **kwargs):
                resp = MagicMock()
                if "Status%200" in url:
                    resp.status_code = 200
                    resp.json.return_value = {
                        "Status": {
                            "FriendlyName": ["TestDevice"],
                            "Version": "12.5.0",
                        }
                    }
                elif "Status%205" in url:
                    resp.status_code = 404
                elif "Power" in url and "%20" not in url:
                    resp.status_code = 200
                    resp.json.return_value = {"POWER": "ON"}
                return resp

            mock_get.side_effect = mock_response
            status = _get_tasmota_status("192.168.1.100")
            assert status["name"] == "TestDevice"
            assert status["rssi"] is None

    def test_get_tasmota_status_power_http_500(self):
        """Should handle Power endpoint returning non-200."""
        with patch("tools.iot_devices.requests.get") as mock_get:

            def mock_response(url, **kwargs):
                resp = MagicMock()
                if "Status%200" in url:
                    resp.status_code = 200
                    resp.json.return_value = {
                        "Status": {
                            "FriendlyName": ["TestDevice"],
                            "Version": "12.5.0",
                        }
                    }
                elif "Status%205" in url:
                    resp.status_code = 200
                    resp.json.return_value = {
                        "StatusSTS": {
                            "Wifi": {
                                "RSSI": -65,
                                "SSId": "MyNetwork",
                            }
                        }
                    }
                elif "Power" in url and "%20" not in url:
                    resp.status_code = 500
                return resp

            mock_get.side_effect = mock_response
            status = _get_tasmota_status("192.168.1.100")
            assert status["name"] == "TestDevice"
            assert status["rssi"] == -65
            assert status["current_power"] is None

    def test_get_tasmota_status_missing_friendly_name(self):
        """Should handle missing FriendlyName in Status JSON."""
        with patch("tools.iot_devices.requests.get") as mock_get:
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = {"Status": {"Version": "12.5.0"}}
            mock_get.return_value = resp
            status = _get_tasmota_status("192.168.1.100")
            assert status["name"] == "Unknown"

    def test_get_tasmota_status_timeout(self):
        """Should handle requests.Timeout as an exception."""
        with patch(
            "tools.iot_devices.requests.get",
            side_effect=Exception("Connection timed out"),
        ):
            status = _get_tasmota_status("192.168.1.100")
            assert status == {"error": "Connection timed out"}


class TestGetDeviceInfoValidation:
    """Tests for input validation in device info."""

    def test_get_device_info_invalid_identifier_empty(self):
        """Should return error for empty identifier."""
        from tools.validators import ValidationError

        with patch(
            "tools.iot_devices.validate_required_string",
            side_effect=ValidationError("identifier must not be empty"),
        ):
            result = _get_device_info("")
            data = json.loads(result)
            assert data["success"] is False
            assert "INVALID_PARAM" in data["error"]["code"]


class TestDeviceRegistrationWrappers:
    """Tests for MCP tool registration wrappers."""

    def test_registration_creates_two_tools(self, mock_mcp):
        register_iot_device_tools(mock_mcp)
        assert "iot_get_device_info" in mock_mcp._tools
        assert "iot_get_device_power" in mock_mcp._tools

    def test_iot_get_device_info_wrapper(self, mock_mcp):
        register_iot_device_tools(mock_mcp)
        fn = mock_mcp.get_tool("iot_get_device_info")
        with patch("tools.iot_discovery._resolve_ip", return_value="192.168.1.100"):
            with patch(
                "tools.iot_discovery._detect_device_type",
                return_value="tasmota",
            ):
                with patch("tools.iot_devices._get_tasmota_status") as mock_status:
                    mock_status.return_value = {"name": "TestDevice", "power_state": 0}
                    result = fn("192.168.1.100")
                    data = json.loads(result)
                    assert data["success"] is True

    def test_iot_get_device_power_wrapper(self, mock_mcp):
        register_iot_device_tools(mock_mcp)
        fn = mock_mcp.get_tool("iot_get_device_power")
        with patch("tools.iot_discovery._resolve_ip", return_value="192.168.1.100"):
            with patch(
                "tools.iot_discovery._detect_device_type",
                return_value="tasmota",
            ):
                with patch("tools.iot_devices.requests.get") as mock_get:
                    resp = MagicMock()
                    resp.status_code = 200
                    resp.json.return_value = {"POWER": "ON"}
                    mock_get.return_value = resp
                    result = fn("192.168.1.100")
                    data = json.loads(result)
                    assert data["success"] is True
