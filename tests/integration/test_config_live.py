"""Live device integration tests for config tools.

Tests run against real OpenBK and Tasmota devices
when they are reachable. All tests are read-only — no state changes.
"""

import json
import os
import re
import socket

import pytest

OPENBK_IP = os.getenv("TEST_OPENBK_DEVICE_IP", "192.0.2.115")
TASMOTA_IP = os.getenv("TEST_TASMOTA_DEVICE_IP", "192.0.2.109")

# Both devices are detected as "tasmota" by _detect_device_type()
# due to the /cm compatibility layer on OpenBK. The actual device
# type is derived from version strings in the Status 0 response.

MAC_RE = re.compile(r"^([0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}$")


def _device_reachable(ip: str, port: int = 80) -> bool:
    """Check if a device is reachable via TCP connect."""
    try:
        s = socket.create_connection((ip, port), timeout=2)
        s.close()
        return True
    except OSError:
        return False


openbk_skip = pytest.mark.skipif(
    not _device_reachable(OPENBK_IP),
    reason=f"OpenBK device not reachable at {OPENBK_IP}",
)

tasmota_skip = pytest.mark.skipif(
    not _device_reachable(TASMOTA_IP),
    reason=f"Tasmota device not reachable at {TASMOTA_IP}",
)


def _call(mcp_client, tool_name, **kwargs):
    """Call a tool and return the parsed JSON result dict."""
    result = mcp_client.call_tool(tool_name, **kwargs)
    return json.loads(result) if isinstance(result, str) else result


def _get_data(mcp_client, tool_name, **kwargs):
    """Call a tool and return the 'data' portion of the response."""
    return _call(mcp_client, tool_name, **kwargs).get("data", {})


class TestOpenBKLive:
    """Read-only tests against the live OpenBK device at OPENBK_IP."""

    @openbk_skip
    def test_get_full_info_returns_device_info(self, mcp_client):
        """iot_get_full_info returns version, MAC, and recognizable metadata."""
        data = _call(mcp_client, "iot_get_full_info", identifier=OPENBK_IP)

        assert data.get("success") is True, f"Expected success, got: {data}"
        info = data.get("data", {})

        # Both devices detected as "tasmota" via _detect_device_type
        assert info.get("device_type") in ("tasmota", "openbk"), (
            f"Unexpected device_type: {info.get('device_type')}"
        )

        assert info.get("version"), f"Missing version in: {info}"
        version_str = str(info.get("version", "")).lower()
        assert any(tok in version_str for tok in ("openbk", "1.17", "bk7231", "obk")), (
            f"Version does not appear to be OpenBK: {version_str}"
        )

        mac = str(info.get("mac", ""))
        assert mac, f"Missing MAC in: {info}"
        assert MAC_RE.match(mac), f"MAC format invalid: {mac}"

    @openbk_skip
    def test_execute_command_status_returns_info(self, mcp_client):
        """iot_execute_command 'Status 0' returns device status for OpenBK."""
        data = _call(mcp_client, "iot_execute_command", identifier=OPENBK_IP, command="Status 0")

        assert data.get("success") is True, f"Expected success, got: {data}"
        resp = data.get("data", {})
        assert resp.get("response"), f"Empty response: {resp}"
        response_text = str(resp.get("response", ""))

        # Status 0 returns the full device status JSON
        assert "Status" in response_text, (
            f"Response does not contain Status block: {response_text[:200]}"
        )

    @openbk_skip
    def test_get_wifi_config_returns_data(self, mcp_client):
        """iot_get_wifi_config returns WiFi info structure for OpenBK."""
        data = _call(mcp_client, "iot_get_wifi_config", identifier=OPENBK_IP)

        assert data.get("success") is True, f"Expected success, got: {data}"
        info = data.get("data", {})

        # Response must have a recognizable structure
        assert "wifi" in info or "device_type" in info, (
            f"Response missing expected fields: {list(info.keys())}"
        )

        # Device type reported by detection layer
        assert info.get("device_type") in ("tasmota", "openbk"), (
            f"Unexpected device_type: {info.get('device_type')}"
        )

        # wifi sub-dict should be present for Tasmota-path response
        if "wifi" in info:
            wifi = info["wifi"]
            # At minimum, the SSID field exists (may be None/empty)
            assert "ssid" in wifi, f"Missing ssid in wifi block: {list(wifi.keys())}"


class TestTasmotaLive:
    """Read-only tests against the live Tasmota device at TASMOTA_IP."""

    @tasmota_skip
    def test_get_full_info_returns_device_info(self, mcp_client):
        """iot_get_full_info returns version, MAC, and device_type=tasmota."""
        data = _call(mcp_client, "iot_get_full_info", identifier=TASMOTA_IP)

        assert data.get("success") is True, f"Expected success, got: {data}"
        info = data.get("data", {})

        assert info.get("device_type") == "tasmota", (
            f"Expected tasmota, got: {info.get('device_type')}"
        )

        assert info.get("version"), f"Missing version in: {info}"
        version_str = str(info.get("version", "")).lower()
        assert "12.5" in version_str or "tasmota" in version_str, (
            f"Version does not appear to be Tasmota 12.5: {version_str}"
        )

        mac = str(info.get("mac", ""))
        assert mac, f"Missing MAC in: {info}"
        assert MAC_RE.match(mac), f"MAC format invalid: {mac}"

    @tasmota_skip
    def test_execute_command_status_fwr(self, mcp_client):
        """iot_execute_command 'Status 2' returns StatusFWR for Tasmota."""
        data = _call(mcp_client, "iot_execute_command", identifier=TASMOTA_IP, command="Status 2")

        assert data.get("success") is True, f"Expected success, got: {data}"
        resp = data.get("data", {})
        assert resp.get("response"), f"Empty response: {resp}"
        response_text = str(resp.get("response", ""))

        # Status 2 returns StatusFWR with firmware version info
        assert "StatusFWR" in response_text, (
            f"Response does not contain StatusFWR: {response_text[:200]}"
        )
