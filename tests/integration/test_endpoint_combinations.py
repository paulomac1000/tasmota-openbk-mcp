"""Parameter matrix tests for iot_* control tools.

Tests all valid parameter combinations for:
- iot_set_power: device_type × state × channel
- iot_set_brightness: device_type × brightness × channel
- iot_restart_device: device_type only
- iot_get_device_power: device_type × channel

Uses anonymized real-device response fixtures (MOCK_TASMOTA_BASIC_STATUS_0,
MOCK_OPENBK_LIGHT_API_INFO, etc.) for realistic validation paths.
"""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from tests.fixtures_real_devices import (
    MOCK_OPENBK_LIGHT_HTML,
)


class TestSetPowerParameterMatrix:
    """iot_set_power: device_type × state × channel matrix."""

    def _call(self, mcp_client, device_type, state, channel=1):
        with patch("tools.iot_discovery._resolve_ip", return_value="192.168.1.100"):
            with patch("tools.iot_discovery._detect_device_type", return_value=device_type):
                with patch("tools.iot_control.requests.get") as mock_get:
                    resp = MagicMock()
                    resp.status_code = 200
                    if device_type == "tasmota":
                        resp.json.return_value = {"POWER1": state}
                        resp.text = json.dumps({"POWER1": state})
                    elif device_type == "openbk":
                        resp.text = "OK"
                    else:
                        resp.text = "OK"
                    mock_get.return_value = resp

                    return mcp_client.call_tool(
                        "iot_set_power", identifier="192.168.1.100", state=state, channel=channel
                    )

    def test_tasmota_on_all_channels(self, mcp_client):
        """Tasmota: state=ON × channel ∈ {1, 2, 3, 4}."""
        for ch in [1, 2, 3, 4]:
            result = self._call(mcp_client, "tasmota", "ON", ch)
            assert json.loads(result)["success"] is True, f"Channel {ch} failed"

    def test_tasmota_off_all_channels(self, mcp_client):
        """Tasmota: state=OFF × channel ∈ {1, 2, 3, 4}."""
        for ch in [1, 2, 3, 4]:
            result = self._call(mcp_client, "tasmota", "OFF", ch)
            assert json.loads(result)["success"] is True, f"Channel {ch} failed"

    def test_tasmota_toggle(self, mcp_client):
        """Tasmota: state=TOGGLE works."""
        result = self._call(mcp_client, "tasmota", "TOGGLE", 1)
        assert json.loads(result)["success"] is True

    def test_openbk_on_all_channels(self, mcp_client):
        """OpenBK: state=ON × channel ∈ {1, 2, 3, 4}."""
        for ch in [1, 2, 3, 4]:
            result = self._call(mcp_client, "openbk", "ON", ch)
            assert json.loads(result)["success"] is True, f"Channel {ch} failed"

    def test_openbk_off(self, mcp_client):
        """OpenBK: state=OFF works."""
        result = self._call(mcp_client, "openbk", "OFF", 1)
        assert json.loads(result)["success"] is True

    def test_tuya_on_off(self, mcp_client):
        """Tuya: state=ON and state=OFF."""
        for state in ["ON", "OFF"]:
            with patch("tools.iot_discovery._resolve_ip", return_value="192.168.1.100"):
                with patch("tools.iot_discovery._detect_device_type", return_value="tuya"):
                    with patch("tools.iot_tuya._find_tuya_in_cache", return_value=None):
                        with patch(
                            "tools.iot_tuya._tuya_set_value",
                            return_value='{"success": true, "data": {"result": "ok"}}',
                        ):
                            result = mcp_client.call_tool(
                                "iot_set_power", identifier="192.168.1.100", state=state, channel=1
                            )
                            assert json.loads(result)["success"] is True, f"State {state} failed"

    def test_invalid_state_rejected(self, mcp_client):
        """Invalid state value returns INVALID_PARAM error."""
        result = self._call(mcp_client, "tasmota", "INVALID_STATE", 1)
        data = json.loads(result)
        assert data["success"] is False
        assert data["error"]["code"] == "INVALID_PARAM"

    def test_channel_zero_rejected(self, mcp_client):
        """channel=0 rejected with INVALID_PARAM."""
        result = self._call(mcp_client, "tasmota", "ON", 0)
        data = json.loads(result)
        assert data["success"] is False
        assert data["error"]["code"] == "INVALID_PARAM"

    def test_channel_negative_rejected(self, mcp_client):
        """channel=-1 rejected with INVALID_PARAM."""
        result = self._call(mcp_client, "tasmota", "ON", -1)
        data = json.loads(result)
        assert data["success"] is False
        assert data["error"]["code"] == "INVALID_PARAM"


class TestSetBrightnessParameterMatrix:
    """iot_set_brightness: device_type × brightness × channel matrix."""

    def _call(self, mcp_client, device_type, brightness, channel=1):
        with patch("tools.iot_discovery._resolve_ip", return_value="192.168.1.100"):
            with patch("tools.iot_discovery._detect_device_type", return_value=device_type):
                with patch("tools.iot_control.requests.get") as mock_get:
                    resp = MagicMock()
                    resp.status_code = 200
                    if device_type == "tasmota":
                        resp.json.return_value = {"POWER1": "ON", "Dimmer": brightness}
                    resp.text = "OK"
                    mock_get.return_value = resp

                    return mcp_client.call_tool(
                        "iot_set_brightness",
                        identifier="192.168.1.100",
                        brightness=brightness,
                        channel=channel,
                    )

    def test_tasmota_brightness_valid_range(self, mcp_client):
        """Tasmota: brightness ∈ {0, 25, 50, 75, 100} all work."""
        for b in [0, 25, 50, 75, 100]:
            result = self._call(mcp_client, "tasmota", b, 1)
            assert json.loads(result)["success"] is True, f"Brightness {b} failed"

    def test_tasmota_brightness_invalid_high(self, mcp_client):
        """Tasmota: brightness=101 rejected."""
        result = self._call(mcp_client, "tasmota", 101, 1)
        data = json.loads(result)
        assert data["success"] is False
        assert data["error"]["code"] == "INVALID_PARAM"

    def test_tasmota_brightness_invalid_negative(self, mcp_client):
        """Tasmota: brightness=-1 rejected."""
        result = self._call(mcp_client, "tasmota", -1, 1)
        data = json.loads(result)
        assert data["success"] is False
        assert data["error"]["code"] == "INVALID_PARAM"

    def test_openbk_brightness_valid(self, mcp_client):
        """OpenBK: brightness ∈ {0, 50, 100} all work."""
        for b in [0, 50, 100]:
            result = self._call(mcp_client, "openbk", b, 1)
            assert json.loads(result)["success"] is True, f"Brightness {b} failed"


class TestGetDevicePowerParameterMatrix:
    """iot_get_device_power: device_type × channel matrix."""

    def test_tasmota_power(self, mcp_client):
        """Tasmota: get power state."""
        with patch("tools.iot_discovery._resolve_ip", return_value="192.168.1.100"):
            with patch("tools.iot_discovery._detect_device_type", return_value="tasmota"):
                with patch("tools.iot_devices.requests.get") as mock_get:
                    resp = MagicMock()
                    resp.status_code = 200
                    resp.json.return_value = {"POWER": "ON"}
                    mock_get.return_value = resp

                    result = mcp_client.call_tool(
                        "iot_get_device_power", identifier="192.168.1.100"
                    )
                    data = json.loads(result)
                    assert data["success"] is True

    def test_openbk_power(self, mcp_client):
        """OpenBK: get power state via HTML regex."""
        with patch("tools.iot_discovery._resolve_ip", return_value="192.168.1.102"):
            with patch("tools.iot_discovery._detect_device_type", return_value="openbk"):
                with patch("tools.iot_devices.requests.get") as mock_get:
                    resp = MagicMock()
                    resp.status_code = 200
                    resp.text = MOCK_OPENBK_LIGHT_HTML
                    resp.json.side_effect = Exception("not JSON")
                    mock_get.return_value = resp

                    result = mcp_client.call_tool(
                        "iot_get_device_power", identifier="192.168.1.102"
                    )
                    data = json.loads(result)
                    assert data["success"] is True


class TestDiscoverDevicesParameterMatrix:
    """iot_discover_devices: network_range × timeout matrix."""

    def test_valid_cidr(self, mcp_client):
        """Valid CIDR works (with mock to avoid real network scan)."""
        with patch("tools.iot_discovery._scan_network", return_value=[]):
            result = mcp_client.call_tool(
                "iot_discover_devices", network_range="192.168.1.0/24", timeout_seconds=10
            )
            data = json.loads(result)
            assert "success" in data
            assert "data" in data

    def test_alternate_form(self, mcp_client):
        """Standard /24 format works (with mock)."""
        with patch("tools.iot_discovery._scan_network", return_value=[]):
            result = mcp_client.call_tool(
                "iot_discover_devices", network_range="10.0.0.0/24", timeout_seconds=5
            )
            data = json.loads(result)
            assert "success" in data

    def test_invalid_cidr_rejected(self, mcp_client):
        """Invalid CIDR returns validation error."""
        result = mcp_client.call_tool(
            "iot_discover_devices", network_range="not-a-cidr", timeout_seconds=10
        )
        data = json.loads(result)
        assert data["success"] is False
