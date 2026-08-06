from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from local_home_devices_mcp.config import load_settings
from local_home_devices_mcp.legacy_compat import install_legacy_safety

pytestmark = pytest.mark.unit


@pytest.fixture
def safe_iot_control(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MCP_TRANSPORT", "stdio")
    from tools import iot_control, iot_discovery

    original_power = iot_control._set_power
    original_brightness = iot_control._set_brightness
    original_resolve = iot_discovery._resolve_ip
    install_legacy_safety(load_settings())
    try:
        yield iot_control
    finally:
        iot_control._set_power = original_power
        iot_control._set_brightness = original_brightness
        iot_discovery._resolve_ip = original_resolve


def test_tuya_toggle_is_rejected_not_mapped_to_off(safe_iot_control):
    with (
        patch("tools.iot_discovery._resolve_ip", return_value="192.168.1.50"),
        patch("tools.iot_discovery._detect_device_type", return_value="tuya"),
        patch("tools.iot_tuya._tuya_set_value") as set_value,
    ):
        result = json.loads(safe_iot_control._set_power("lamp", "TOGGLE"))
    assert result["success"] is False
    assert result["error"]["code"] == "UNSUPPORTED_OPERATION"
    set_value.assert_not_called()


def test_tuya_brightness_uses_dedicated_dp(safe_iot_control):
    with (
        patch("tools.iot_discovery._resolve_ip", return_value="192.168.1.50"),
        patch("tools.iot_discovery._detect_device_type", return_value="tuya"),
        patch(
            "tools.iot_tuya._find_tuya_in_cache",
            return_value={"power_dp_id": "1", "brightness_dp_id": "22"},
        ),
        patch("tools.iot_tuya._tuya_set_value", return_value='{"success": true}') as set_value,
    ):
        safe_iot_control._set_brightness("lamp", 40)
    set_value.assert_called_once_with("lamp", "22", 40)


def test_tuya_brightness_fails_closed_without_mapping(safe_iot_control):
    with (
        patch("tools.iot_discovery._resolve_ip", return_value="192.168.1.50"),
        patch("tools.iot_discovery._detect_device_type", return_value="tuya"),
        patch("tools.iot_tuya._find_tuya_in_cache", return_value={"power_dp_id": "1"}),
        patch("tools.iot_tuya._tuya_set_value") as set_value,
    ):
        result = json.loads(safe_iot_control._set_brightness("lamp", 40))
    assert result["success"] is False
    assert result["error"]["code"] == "UNSUPPORTED_OPERATION"
    set_value.assert_not_called()
