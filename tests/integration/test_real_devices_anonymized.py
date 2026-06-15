"""Integration tests using real anonymized device responses.

These tests mock the HTTP layer with REAL device response shapes (anonymized)
captured from the actual home network. They verify that the tool's parsing
logic correctly handles realistic response structures without depending on
actual network devices.

Test data is sourced from:
- Tasmota 12.5.0 (192.168.0.109, captured 2026-06-15)
- OpenBK 1.17.306 (192.168.0.115 Light_Bedroom, captured 2026-06-15)
- OpenBK Curtains (192.168.0.105, captured 2026-06-15)
- OpenBK Socket (192.168.0.225, captured 2026-06-15)

All IPs/MACs are anonymized per the strategy in
.omo/plans/v1.6.0-real-integration.md
"""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from tests.fixtures_real_devices import (
    MOCK_DISCOVERED_DEVICES,
    MOCK_OPENBK_CURTAINS_HTML,
    MOCK_OPENBK_LIGHT_API_INFO,
    MOCK_OPENBK_LIGHT_HTML,
    MOCK_TASMOTA_BASIC_STATUS_0,
    MOCK_TASMOTA_CURTAINS_STATUS_0,
)


class TestTasmotaAnonymizedResponses:
    """Test iot_* tools against Tasmota-shaped responses captured from real device."""

    def _call_tool(self, mcp_client, tool_name, **kwargs):
        result = mcp_client.call_tool(tool_name, **kwargs)
        return json.loads(result) if isinstance(result, str) else result

    def test_iot_get_device_info_tasmota(self, mcp_client):
        """Get device info using real Tasmota response shape."""
        with patch("tools.iot_discovery._resolve_ip", return_value="192.168.1.100"):
            with patch("tools.iot_discovery._detect_device_type", return_value="tasmota"):
                with patch("tools.iot_control.requests.get") as mock_get:
                    resp = MagicMock()
                    resp.status_code = 200
                    resp.json.return_value = MOCK_TASMOTA_BASIC_STATUS_0
                    resp.text = json.dumps(MOCK_TASMOTA_BASIC_STATUS_0)
                    mock_get.return_value = resp

                    result = self._call_tool(
                        mcp_client, "iot_get_device_info", identifier="192.168.1.100"
                    )

        assert result["success"] is True
        data = result.get("data", {})
        assert data.get("device_type") == "tasmota"
        assert data.get("info", {}).get("name") == "Tasmota"
        assert data.get("ip_address") == "192.168.1.100"

    def test_iot_get_full_info_tasmota(self, mcp_client):
        """Get full info (MAC, version, flags, MQTT, WiFi) from real Tasmota Status 0."""
        with patch("tools.iot_discovery._resolve_ip", return_value="192.168.1.100"):
            with patch("tools.iot_discovery._detect_device_type", return_value="tasmota"):
                with patch("tools.iot_config._DeviceHttpSession") as mock_session_cls:
                    mock_session = MagicMock()
                    mock_session.get_json.return_value = MOCK_TASMOTA_BASIC_STATUS_0
                    mock_session_cls.return_value = mock_session

                    result = self._call_tool(
                        mcp_client, "iot_get_full_info", identifier="192.168.1.100"
                    )

        assert result["success"] is True, f"Expected success, got {result}"

    def test_iot_set_power_tasmota(self, mcp_client):
        """Test power control with real Tasmota /cm?cmnd= response."""
        with patch("tools.iot_discovery._resolve_ip", return_value="192.168.1.100"):
            with patch("tools.iot_discovery._detect_device_type", return_value="tasmota"):
                with patch("tools.iot_control.requests.get") as mock_get:
                    resp = MagicMock()
                    resp.status_code = 200
                    resp.json.return_value = {"POWER1": "ON"}
                    mock_get.return_value = resp

                    result = self._call_tool(
                        mcp_client,
                        "iot_set_power",
                        identifier="192.168.1.100",
                        state="ON",
                        channel=1,
                    )

        assert result["success"] is True
        data = result.get("data", {})
        assert data.get("device_type") == "tasmota"
        assert data.get("requested_state") == "ON"

    def test_iot_set_brightness_tasmota(self, mcp_client):
        """Test brightness control with real Tasmota /cm?cmnd=Channel response."""
        with patch("tools.iot_discovery._resolve_ip", return_value="192.168.1.100"):
            with patch("tools.iot_discovery._detect_device_type", return_value="tasmota"):
                with patch("tools.iot_control.requests.get") as mock_get:
                    resp = MagicMock()
                    resp.status_code = 200
                    resp.json.return_value = {"POWER1": "ON", "Dimmer": 50}
                    mock_get.return_value = resp

                    result = self._call_tool(
                        mcp_client,
                        "iot_set_brightness",
                        identifier="192.168.1.100",
                        brightness=50,
                        channel=1,
                    )

        assert result["success"] is True
        data = result.get("data", {})
        assert data.get("device_type") == "tasmota"

    def test_iot_get_device_power_tasmota(self, mcp_client):
        """Test power state query with real Tasmota /cm?cmnd=Power response."""
        with patch("tools.iot_discovery._resolve_ip", return_value="192.168.1.100"):
            with patch("tools.iot_discovery._detect_device_type", return_value="tasmota"):
                with patch("tools.iot_devices.requests.get") as mock_get:
                    resp = MagicMock()
                    resp.status_code = 200
                    resp.json.return_value = {"POWER": "ON"}
                    mock_get.return_value = resp

                    result = self._call_tool(
                        mcp_client,
                        "iot_get_device_power",
                        identifier="192.168.1.100",
                    )

        assert result["success"] is True

    def test_iot_get_wifi_config_tasmota(self, mcp_client):
        """Test WiFi config query with real Tasmota /cm?cmnd=Status%205 response."""
        with patch("tools.iot_discovery._resolve_ip", return_value="192.168.1.100"):
            with patch("tools.iot_discovery._detect_device_type", return_value="tasmota"):
                with patch("tools.iot_control.requests.get") as mock_get:
                    resp = MagicMock()
                    resp.status_code = 200
                    resp.json.return_value = MOCK_TASMOTA_BASIC_STATUS_0["StatusNET"]
                    mock_get.return_value = resp

                    result = self._call_tool(
                        mcp_client,
                        "iot_get_wifi_config",
                        identifier="192.168.1.100",
                    )

        assert result["success"] is True

    def test_iot_discover_devices_tasmota_curtains(self, mcp_client):
        """Tasmota curtains (Tasmota API on OpenBK device) full info."""
        with patch("tools.iot_discovery._resolve_ip", return_value="192.168.1.101"):
            with patch("tools.iot_discovery._detect_device_type", return_value="tasmota"):
                with patch("tools.iot_config._DeviceHttpSession") as mock_session_cls:
                    mock_session = MagicMock()
                    mock_session.get_json.return_value = MOCK_TASMOTA_CURTAINS_STATUS_0
                    mock_session_cls.return_value = mock_session

                    result = self._call_tool(
                        mcp_client,
                        "iot_get_full_info",
                        identifier="192.168.1.101",
                    )

        assert result["success"] is True, f"Expected success, got {result}"


class TestOpenBKAnonymizedResponses:
    """Test iot_* tools against OpenBK-shaped responses captured from real device."""

    def _call_tool(self, mcp_client, tool_name, **kwargs):
        result = mcp_client.call_tool(tool_name, **kwargs)
        return json.loads(result) if isinstance(result, str) else result

    def test_iot_get_device_info_openbk_light(self, mcp_client):
        """Get device info using real OpenBK /api/info + /index state."""
        with patch("tools.iot_discovery._resolve_ip", return_value="192.168.1.102"):
            with patch("tools.iot_discovery._detect_device_type", return_value="openbk"):
                with patch("tools.iot_devices.requests.get") as mock_get:

                    def side_effect(url, **kwargs):
                        resp = MagicMock()
                        resp.status_code = 200
                        if "api/info" in url:
                            resp.json.return_value = MOCK_OPENBK_LIGHT_API_INFO
                            resp.text = json.dumps(MOCK_OPENBK_LIGHT_API_INFO)
                        else:
                            # /index returns HTML — must be parseable as text
                            resp.text = MOCK_OPENBK_LIGHT_HTML
                            resp.json.side_effect = Exception("not JSON")
                        return resp

                    mock_get.side_effect = side_effect

                    result = self._call_tool(
                        mcp_client,
                        "iot_get_device_info",
                        identifier="192.168.1.102",
                    )

        assert result["success"] is True, f"Expected success, got {result}"
        data = result.get("data", {})
        assert data.get("device_type") == "openbk"
        info = data.get("info", {})
        # OpenBK name comes from HTML <title> tag via regex
        assert info.get("name") == "Light_Bedroom", (
            f"Got name: {info.get('name')}, full info: {info}"
        )

    def test_iot_set_power_openbk(self, mcp_client):
        """Test OpenBK /index?set=1&val=1 power control."""
        with patch("tools.iot_discovery._resolve_ip", return_value="192.168.1.102"):
            with patch("tools.iot_discovery._detect_device_type", return_value="openbk"):
                with patch("tools.iot_control.requests.get") as mock_get:
                    resp = MagicMock()
                    resp.status_code = 200
                    mock_get.return_value = resp

                    result = self._call_tool(
                        mcp_client,
                        "iot_set_power",
                        identifier="192.168.1.102",
                        state="ON",
                        channel=1,
                    )

        assert result["success"] is True
        data = result.get("data", {})
        assert data.get("device_type") == "openbk"

    def test_iot_get_full_info_openbk(self, mcp_client):
        """Test OpenBK full info with real api/info + index state."""
        with patch("tools.iot_discovery._resolve_ip", return_value="192.168.1.102"):
            with patch("tools.iot_discovery._detect_device_type", return_value="openbk"):
                with patch("tools.iot_config._DeviceHttpSession") as mock_session_cls:
                    mock_session = MagicMock()
                    # OpenBK full_info does api/info first, then status 0 (tasmota compat)
                    mock_session.get_json.side_effect = [
                        MOCK_OPENBK_LIGHT_API_INFO,
                        MOCK_TASMOTA_BASIC_STATUS_0,  # t-string
                    ]
                    mock_session_cls.return_value = mock_session

                    result = self._call_tool(
                        mcp_client,
                        "iot_get_full_info",
                        identifier="192.168.1.102",
                    )

        assert result["success"] is True, f"Expected success, got {result}"

    def test_iot_set_brightness_openbk(self, mcp_client):
        """Test OpenBK brightness via /index?set=1&val=N."""
        with patch("tools.iot_discovery._resolve_ip", return_value="192.168.1.102"):
            with patch("tools.iot_discovery._detect_device_type", return_value="openbk"):
                with patch("tools.iot_control.requests.get") as mock_get:
                    resp = MagicMock()
                    resp.status_code = 200
                    mock_get.return_value = resp

                    result = self._call_tool(
                        mcp_client,
                        "iot_set_brightness",
                        identifier="192.168.1.102",
                        brightness=50,
                        channel=1,
                    )

        assert result["success"] is True

    def test_iot_restart_device_openbk(self, mcp_client):
        """Test OpenBK /index?restart=1 restart."""
        with patch("tools.iot_discovery._resolve_ip", return_value="192.168.1.102"):
            with patch("tools.iot_discovery._detect_device_type", return_value="openbk"):
                with patch("tools.iot_control.requests.get") as mock_get:
                    resp = MagicMock()
                    resp.status_code = 200
                    mock_get.return_value = resp

                    result = self._call_tool(
                        mcp_client,
                        "iot_restart_device",
                        identifier="192.168.1.102",
                    )

        assert result["success"] is True

    def test_iot_get_wifi_config_openbk(self, mcp_client):
        """Test OpenBK WiFi info extraction from /index page."""
        with patch("tools.iot_discovery._resolve_ip", return_value="192.168.1.102"):
            with patch("tools.iot_discovery._detect_device_type", return_value="openbk"):
                with patch("tools.iot_control.requests.get") as mock_get:
                    resp = MagicMock()
                    resp.status_code = 200
                    resp.text = MOCK_OPENBK_LIGHT_HTML
                    resp.json.side_effect = Exception("not JSON")
                    mock_get.return_value = resp

                    result = self._call_tool(
                        mcp_client,
                        "iot_get_wifi_config",
                        identifier="192.168.1.102",
                    )

        assert result["success"] is True, f"Expected success, got {result}"


class TestCurtainsDeviceEndToEnd:
    """End-to-end test for curtain control workflow with real device data."""

    def _call_tool(self, mcp_client, tool_name, **kwargs):
        result = mcp_client.call_tool(tool_name, **kwargs)
        return json.loads(result) if isinstance(result, str) else result

    def test_curtains_full_workflow(self, mcp_client):
        """Test full curtain control: identify -> query state -> control -> verify."""
        from tools.iot_control import _set_power
        from tools.iot_devices import _get_device_info

        # Step 1: Identify device
        with patch("tools.iot_discovery._resolve_ip", return_value="192.168.1.103"):
            with patch("tools.iot_discovery._detect_device_type", return_value="openbk"):
                with patch("tools.iot_devices.requests.get") as mock_get:
                    resp = MagicMock()
                    resp.status_code = 200
                    resp.text = MOCK_OPENBK_CURTAINS_HTML
                    resp.json.side_effect = Exception("not JSON")
                    mock_get.return_value = resp

                    info_result = _get_device_info("192.168.1.103")
                    info_data = json.loads(info_result)
                    assert info_data["success"] is True, f"Got: {info_data}"
                    # Curtains HTML has <title>Curtains LivingRoom</title>
                    assert info_data["data"]["info"]["name"] == "Curtains LivingRoom"

        # Step 2: Control curtains
        with patch("tools.iot_discovery._resolve_ip", return_value="192.168.1.103"):
            with patch("tools.iot_discovery._detect_device_type", return_value="openbk"):
                with patch("tools.iot_control.requests.get") as mock_get:
                    resp = MagicMock()
                    resp.status_code = 200
                    mock_get.return_value = resp

                    power_result = _set_power("192.168.1.103", "ON", channel=1)
                    power_data = json.loads(power_result)
                    assert power_data["success"] is True

    def test_socket_device_info(self, mcp_client):
        """Test socket (relay) device identification with real /index HTML."""
        with patch("tools.iot_discovery._resolve_ip", return_value="192.168.1.104"):
            with patch("tools.iot_discovery._detect_device_type", return_value="openbk"):
                with patch("tools.iot_devices.requests.get") as mock_get:
                    resp = MagicMock()
                    resp.status_code = 200
                    # Socket uses standard OpenBK HTML structure
                    resp.text = MOCK_OPENBK_LIGHT_HTML.replace("Light_Bedroom", "Socket_Kitchen")
                    resp.json.side_effect = Exception("not JSON")
                    mock_get.return_value = resp

                    from tools.iot_devices import _get_device_info

                    info_result = _get_device_info("192.168.1.104")
                    info_data = json.loads(info_result)
                    # OpenBK info is parsed from HTML; "Socket_Kitchen" is from <title>
                    assert info_data["success"] is True, f"Got: {info_data}"
                    assert info_data["data"]["info"]["name"] == "Socket_Kitchen"


class TestDiscoveryWithAnonymizedData:
    """Test discovery using anonymized device list as if from cache."""

    def test_list_cached_devices(self, mcp_client):
        """List devices from mocked cache."""
        from unittest.mock import patch

        cache_data = {
            "last_scan": "2024-01-01T00:00:00",
            "devices": MOCK_DISCOVERED_DEVICES,
        }

        with patch("tools.iot_discovery._load_cache", return_value=cache_data):
            result = mcp_client.call_tool("iot_list_devices")
            data = json.loads(result) if isinstance(result, str) else result
            assert data["success"] is True
            inner = data.get("data", {})
            assert inner.get("device_count") == 5
            devices = inner.get("devices", [])
            assert len(devices) == 5

    def test_find_device_by_name_light_bedroom(self, mcp_client):
        """Find device by name in anonymized cache."""
        cache_data = {"devices": MOCK_DISCOVERED_DEVICES}

        with patch("tools.iot_discovery._load_cache", return_value=cache_data):
            from tools.iot_discovery import _find_device_by_identifier

            result = _find_device_by_identifier("Light_Bedroom")
            assert result is not None
            assert result.get("ip") == "192.168.1.102"
            assert result.get("device_type") == "openbk"

    def test_find_device_by_ip(self, mcp_client):
        """Find device by IP in anonymized cache."""
        cache_data = {"devices": MOCK_DISCOVERED_DEVICES}

        with patch("tools.iot_discovery._load_cache", return_value=cache_data):
            from tools.iot_discovery import _find_device_by_identifier

            result = _find_device_by_identifier("192.168.1.101")
            assert result is not None
            assert result.get("name") == "Curtains_Test"

    def test_resolve_ip(self, mcp_client):
        """Test _resolve_ip function with cache lookup."""
        cache_data = {"devices": MOCK_DISCOVERED_DEVICES}

        with patch("tools.iot_discovery._load_cache", return_value=cache_data):
            from tools.iot_discovery import _resolve_ip

            # By name
            assert _resolve_ip("Light_Bedroom") == "192.168.1.102"
            assert _resolve_ip("Socket_Kitchen") == "192.168.1.104"

            # By IP (should pass through)
            assert _resolve_ip("192.168.1.100") == "192.168.1.100"

            # Unknown name
            assert _resolve_ip("NonexistentDevice") is None
