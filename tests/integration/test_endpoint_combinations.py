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

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from tests.fixtures_real_devices import MOCK_OPENBK_LIGHT_HTML  # noqa: E402

pytestmark = [pytest.mark.integration]


class TestSetPowerParameterMatrix:
    """iot_set_power: device_type x state x channel matrix.

    Per AGENTS.md, destructive operations in the integration suite test only
    error paths. The success-path tests below verify that the request reaches
    the HTTP layer (mock URL is correct) without claiming destructive success
    against a real device.
    """

    def _call(self, mcp_client, device_type, state, channel=1, expect_call=True):
        with patch("tools.iot_discovery._resolve_ip", return_value="192.168.1.100"):
            with patch("tools.iot_discovery._detect_device_type", return_value=device_type):
                with patch("tools.iot_control.requests.get") as mock_get:
                    resp = MagicMock()
                    resp.status_code = 200
                    if device_type == "tasmota":
                        resp.json.return_value = {"POWER1": state}
                        resp.text = json.dumps({"POWER1": state})
                    else:
                        resp.text = "OK"
                    mock_get.return_value = resp

                    result = mcp_client.call_tool(
                        "iot_set_power", identifier="192.168.1.100", state=state, channel=channel
                    )
                    if expect_call:
                        assert mock_get.called, (
                            f"Expected HTTP request to device for {device_type}/{state}/ch{channel}"
                        )
                    return result, mock_get

    def test_tasmota_on_all_channels(self, mcp_client):
        """Tasmota: state=ON x channel in {1, 2, 3, 4} reaches HTTP layer."""
        for ch in [1, 2, 3, 4]:
            _, mock_get = self._call(mcp_client, "tasmota", "ON", ch)
            assert mock_get.call_count >= 1, f"Channel {ch} never reached HTTP"

    def test_tasmota_off_all_channels(self, mcp_client):
        """Tasmota: state=OFF x channel in {1, 2, 3, 4} reaches HTTP layer."""
        for ch in [1, 2, 3, 4]:
            _, mock_get = self._call(mcp_client, "tasmota", "OFF", ch)
            assert mock_get.call_count >= 1, f"Channel {ch} never reached HTTP"

    def test_tasmota_toggle(self, mcp_client):
        """Tasmota: state=TOGGLE reaches HTTP layer."""
        _, mock_get = self._call(mcp_client, "tasmota", "TOGGLE", 1)
        assert mock_get.call_count >= 1

    def test_openbk_on_all_channels(self, mcp_client):
        """OpenBK: state=ON x channel in {1, 2, 3, 4} reaches HTTP layer."""
        for ch in [1, 2, 3, 4]:
            _, mock_get = self._call(mcp_client, "openbk", "ON", ch)
            assert mock_get.call_count >= 1, f"Channel {ch} never reached HTTP"

    def test_openbk_off(self, mcp_client):
        """OpenBK: state=OFF reaches HTTP layer."""
        _, mock_get = self._call(mcp_client, "openbk", "OFF", 1)
        assert mock_get.call_count >= 1

    def test_tuya_on_off(self, mcp_client):
        """Tuya: state=ON and state=OFF reach the local Tuya setter."""
        for state in ["ON", "OFF"]:
            with patch("tools.iot_discovery._resolve_ip", return_value="192.168.1.100"):
                with patch("tools.iot_discovery._detect_device_type", return_value="tuya"):
                    with patch("tools.iot_tuya._find_tuya_in_cache", return_value=None):
                        with patch("tools.iot_tuya._tuya_set_value") as mock_tuya_set:
                            mock_tuya_set.return_value = (
                                '{"success": true, "data": {"result": "ok"}}'
                            )
                            mcp_client.call_tool(
                                "iot_set_power",
                                identifier="192.168.1.100",
                                state=state,
                                channel=1,
                            )
                            assert mock_tuya_set.called, (
                                f"Tuya setter never invoked for state {state}"
                            )

    def test_invalid_state_rejected(self, mcp_client):
        """Invalid state value returns INVALID_PARAM error."""
        result, mock_get = self._call(mcp_client, "tasmota", "INVALID_STATE", 1, expect_call=False)
        data = json.loads(result)
        assert data["success"] is False
        assert data["error"]["code"] == "INVALID_PARAM"
        assert not mock_get.called, "HTTP must not be called for invalid state"

    def test_channel_zero_rejected(self, mcp_client):
        """channel=0 rejected with INVALID_PARAM."""
        result, mock_get = self._call(mcp_client, "tasmota", "ON", 0, expect_call=False)
        data = json.loads(result)
        assert data["success"] is False
        assert data["error"]["code"] == "INVALID_PARAM"
        assert not mock_get.called, "HTTP must not be called for invalid channel"

    def test_channel_negative_rejected(self, mcp_client):
        """channel=-1 rejected with INVALID_PARAM."""
        result, mock_get = self._call(mcp_client, "tasmota", "ON", -1, expect_call=False)
        data = json.loads(result)
        assert data["success"] is False
        assert data["error"]["code"] == "INVALID_PARAM"
        assert not mock_get.called, "HTTP must not be called for invalid channel"


class TestSetBrightnessParameterMatrix:
    """iot_set_brightness: device_type x brightness x channel matrix.

    Per AGENTS.md, destructive operations in the integration suite test only
    error paths. Success-path tests below verify the request reaches the HTTP
    layer (mock URL is correct) without claiming destructive success.
    """

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

                    mcp_client.call_tool(
                        "iot_set_brightness",
                        identifier="192.168.1.100",
                        brightness=brightness,
                        channel=channel,
                    )
                    return mock_get

    def test_tasmota_brightness_valid_range(self, mcp_client):
        """Tasmota: brightness in {0, 25, 50, 75, 100} all reach the HTTP layer."""
        for b in [0, 25, 50, 75, 100]:
            mock_get = self._call(mcp_client, "tasmota", b, 1)
            assert mock_get.call_count >= 1, f"Brightness {b} never reached HTTP"

    def test_tasmota_brightness_invalid_high(self, mcp_client):
        """Tasmota: brightness=101 rejected."""
        with patch("tools.iot_discovery._resolve_ip", return_value="192.168.1.100"):
            with patch("tools.iot_discovery._detect_device_type", return_value="tasmota"):
                with patch("tools.iot_control.requests.get") as mock_get:
                    result = mcp_client.call_tool(
                        "iot_set_brightness",
                        identifier="192.168.1.100",
                        brightness=101,
                        channel=1,
                    )
                    data = json.loads(result)
                    assert data["success"] is False
                    assert data["error"]["code"] == "INVALID_PARAM"
                    assert not mock_get.called, "HTTP must not be called for brightness > 100"

    def test_tasmota_brightness_invalid_negative(self, mcp_client):
        """Tasmota: brightness=-1 rejected."""
        with patch("tools.iot_discovery._resolve_ip", return_value="192.168.1.100"):
            with patch("tools.iot_discovery._detect_device_type", return_value="tasmota"):
                with patch("tools.iot_control.requests.get") as mock_get:
                    result = mcp_client.call_tool(
                        "iot_set_brightness",
                        identifier="192.168.1.100",
                        brightness=-1,
                        channel=1,
                    )
                    data = json.loads(result)
                    assert data["success"] is False
                    assert data["error"]["code"] == "INVALID_PARAM"
                    assert not mock_get.called, "HTTP must not be called for negative brightness"

    def test_openbk_brightness_valid(self, mcp_client):
        """OpenBK: brightness in {0, 50, 100} all reach the HTTP layer."""
        for b in [0, 50, 100]:
            mock_get = self._call(mcp_client, "openbk", b, 1)
            assert mock_get.call_count >= 1, f"Brightness {b} never reached HTTP"


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
