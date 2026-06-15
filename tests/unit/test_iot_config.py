"""
Unit tests for tools/iot_config.py — IoT device configuration tools.

Tests flag setting, device naming, MQTT configuration, GPIO pin assignment,
command execution with blocklist, HA discovery triggering, and full info retrieval.
"""

import json
from unittest.mock import MagicMock, patch

import pytest

from tools.iot_config import (
    _configure_mqtt,
    _execute_command,
    _get_full_info,
    _set_flags,
    _set_friendly_name,
    _set_gpio,
    _set_name,
    _set_startup_command,
    _start_ha_discovery,
    register_iot_config_tools,
)

pytestmark = pytest.mark.unit

# ---------------------------------------------------------------------------
# _set_flags / iot_set_flags
# ---------------------------------------------------------------------------


class TestSetFlags:
    """Tests for _set_flags / iot_set_flags — flag bitfield configuration."""

    def test_flags_openbk_success(self):
        """Set flags on an OpenBK device — flags=0x4004044 (bits 2,6,10,26)."""
        with patch("tools.iot_config._resolve_or_fail", return_value="192.168.1.101"):
            with patch("tools.iot_discovery._detect_device_type", return_value="openbk"):
                with patch("tools.iot_config._DeviceHttpSession") as mock_session_cls:
                    mock_session = MagicMock()
                    mock_session_cls.return_value = mock_session

                    result = _set_flags("192.168.1.101", 0x4004044)
                    data = json.loads(result)

                    assert data["success"] is True
                    assert data["data"]["flags_set"] == 0x4004044
                    assert data["data"]["device_type"] == "openbk"
                    assert data["data"]["ip"] == "192.168.1.101"

    def test_flags_openbk_url_build(self):
        """Verify URL contains correct flag parameters for set bits."""
        with patch("tools.iot_config._resolve_or_fail", return_value="192.168.1.101"):
            with patch("tools.iot_discovery._detect_device_type", return_value="openbk"):
                with patch("tools.iot_config._DeviceHttpSession") as mock_session_cls:
                    mock_session = MagicMock()
                    mock_session_cls.return_value = mock_session

                    _set_flags("192.168.1.101", 134218820)  # bits 2,6,10,27
                    call_path = mock_session.get_form.call_args[0][0]
                    assert "flag2=1" in call_path
                    assert "flag6=1" in call_path
                    assert "flag10=1" in call_path
                    assert "flag27=1" in call_path
                    assert "setFlags=1" in call_path

    def test_flags_zero_success(self):
        """Setting flags=0 — no bits set, still succeeds."""
        with patch("tools.iot_config._resolve_or_fail", return_value="192.168.1.101"):
            with patch("tools.iot_discovery._detect_device_type", return_value="openbk"):
                with patch("tools.iot_config._DeviceHttpSession") as mock_session_cls:
                    mock_session = MagicMock()
                    mock_session_cls.return_value = mock_session

                    result = _set_flags("192.168.1.101", 0)
                    data = json.loads(result)

                    assert data["success"] is True
                    assert data["data"]["flags_set"] == 0
                    # URL still has setFlags=1 even with zero flags
                    call_path = mock_session.get_form.call_args[0][0]
                    assert "setFlags=1" in call_path

    def test_flags_tasmota_single_bit(self):
        """Tasmota sets single SetOption via get_json for bit 0-31."""
        with patch("tools.iot_config._resolve_or_fail", return_value="192.168.1.100"):
            with patch("tools.iot_discovery._detect_device_type", return_value="tasmota"):
                with patch("tools.iot_config._DeviceHttpSession") as mock_session_cls:
                    mock_session = MagicMock()
                    mock_session.get_json.return_value = {}
                    mock_session_cls.return_value = mock_session

                    result = _set_flags("192.168.1.100", 8)  # bit 3
                    data = json.loads(result)

                    assert data["success"] is True
                    assert data["data"]["device_type"] == "tasmota"
                    mock_session.get_json.assert_called_once()

    def test_flags_name_not_resolved(self):
        """Identifier cannot be resolved — NAME_NOT_RESOLVED error."""
        with patch("tools.iot_config._resolve_or_fail", return_value=None):
            result = _set_flags("UnknownDevice", 0)
            data = json.loads(result)
            assert data["success"] is False
            assert data["error"]["code"] == "NAME_NOT_RESOLVED"

    def test_flags_device_not_found(self):
        """IP resolves but no device detected — DEVICE_NOT_FOUND error."""
        with patch("tools.iot_config._resolve_or_fail", return_value="192.168.1.200"):
            with patch("tools.iot_discovery._detect_device_type", return_value=None):
                result = _set_flags("192.168.1.200", 1)
                data = json.loads(result)
                assert data["success"] is False
                assert data["error"]["code"] == "DEVICE_NOT_FOUND"

    def test_flags_negative_rejected(self):
        """Negative flags value causes INVALID_PARAM validation error."""
        with patch("tools.iot_config._resolve_or_fail", return_value="192.168.1.101"):
            result = _set_flags("192.168.1.101", -1)
            data = json.loads(result)
            assert data["success"] is False
            assert data["error"]["code"] == "INVALID_PARAM"

    def test_flags_device_connection_error(self):
        """DeviceConnectionError during HTTP call — DEVICE_ERROR response."""
        from tools.http_session import DeviceConnectionError

        with patch("tools.iot_config._resolve_or_fail", return_value="192.168.1.101"):
            with patch("tools.iot_discovery._detect_device_type", return_value="openbk"):
                with patch("tools.iot_config._DeviceHttpSession") as mock_session_cls:
                    mock_session = MagicMock()
                    mock_session.get_form.side_effect = DeviceConnectionError("Connection failed")
                    mock_session_cls.return_value = mock_session

                    result = _set_flags("192.168.1.101", 7)
                    data = json.loads(result)
                    assert data["success"] is False
                    assert data["error"]["code"] == "DEVICE_ERROR"


# ---------------------------------------------------------------------------
# _set_name / iot_set_name
# ---------------------------------------------------------------------------


class TestSetName:
    """Tests for _set_name / iot_set_name — device naming."""

    def test_set_name_openbk_success(self):
        """Set name on an OpenBK device with valid short_name."""
        with patch("tools.iot_config._resolve_or_fail", return_value="192.168.1.101"):
            with patch("tools.iot_discovery._detect_device_type", return_value="openbk"):
                with patch("tools.iot_config._DeviceHttpSession") as mock_session_cls:
                    mock_session = MagicMock()
                    mock_session_cls.return_value = mock_session

                    result = _set_name("192.168.1.101", "OpenBK_Test")
                    data = json.loads(result)

                    assert data["success"] is True
                    assert data["data"]["short_name"] == "OpenBK_Test"
                    assert data["data"]["device_type"] == "openbk"

    def test_set_name_with_full_name(self):
        """Both short_name and full_name provided — both included in response."""
        with patch("tools.iot_config._resolve_or_fail", return_value="192.168.1.101"):
            with patch("tools.iot_discovery._detect_device_type", return_value="openbk"):
                with patch("tools.iot_config._DeviceHttpSession") as mock_session_cls:
                    mock_session = MagicMock()
                    mock_session_cls.return_value = mock_session

                    result = _set_name("192.168.1.101", "Kitchen", full_name="Kitchen_Light")
                    data = json.loads(result)

                    assert data["success"] is True
                    assert data["data"]["short_name"] == "Kitchen"
                    assert data["data"]["full_name"] == "Kitchen_Light"

    def test_set_name_invalid_chars(self):
        """Name with invalid characters — INVALID_PARAM error."""
        with patch("tools.iot_config._resolve_or_fail", return_value="192.168.1.101"):
            result = _set_name("192.168.1.101", "Bad Name!")
            data = json.loads(result)
            assert data["success"] is False
            assert data["error"]["code"] == "INVALID_PARAM"

    def test_set_name_empty_rejected(self):
        """Empty short_name — INVALID_PARAM error."""
        with patch("tools.iot_config._resolve_or_fail", return_value="192.168.1.101"):
            result = _set_name("192.168.1.101", "")
            data = json.loads(result)
            assert data["success"] is False
            assert data["error"]["code"] == "INVALID_PARAM"

    def test_set_name_name_not_resolved(self):
        """Unknown identifier — NAME_NOT_RESOLVED."""
        with patch("tools.iot_config._resolve_or_fail", return_value=None):
            result = _set_name("UnknownDevice", "Test")
            data = json.loads(result)
            assert data["success"] is False
            assert data["error"]["code"] == "NAME_NOT_RESOLVED"

    def test_set_name_tasmota_unsupported(self):
        """Tasmota does not support set_name via HTTP — UNSUPPORTED_TYPE."""
        from tools.http_session import DeviceConnectionError

        with patch("tools.iot_config._resolve_or_fail", return_value="192.168.1.100"):
            with patch("tools.iot_discovery._detect_device_type", return_value="tasmota"):
                with patch("tools.iot_config._DeviceHttpSession") as mock_session_cls:
                    mock_session = MagicMock()
                    mock_session.get_form.side_effect = DeviceConnectionError(
                        "[UNSUPPORTED_TYPE] set_name is not supported via HTTP GET on Tasmota"
                    )
                    mock_session_cls.return_value = mock_session

                    result = _set_name("192.168.1.100", "Tasmota_Name")
                    data = json.loads(result)
                    assert data["success"] is False
                    assert data["error"]["code"] == "UNSUPPORTED_TYPE"

    def test_set_name_device_not_found(self):
        """Device type unknown — DEVICE_NOT_FOUND."""
        with patch("tools.iot_config._resolve_or_fail", return_value="192.168.1.200"):
            with patch("tools.iot_discovery._detect_device_type", return_value=None):
                result = _set_name("192.168.1.200", "Test")
                data = json.loads(result)
                assert data["success"] is False
                assert data["error"]["code"] == "DEVICE_NOT_FOUND"

    def test_set_name_device_connection_error(self):
        """Generic connection error — DEVICE_ERROR."""
        from tools.http_session import DeviceConnectionError

        with patch("tools.iot_config._resolve_or_fail", return_value="192.168.1.101"):
            with patch("tools.iot_discovery._detect_device_type", return_value="openbk"):
                with patch("tools.iot_config._DeviceHttpSession") as mock_session_cls:
                    mock_session = MagicMock()
                    mock_session.get_form.side_effect = DeviceConnectionError("Timed out")
                    mock_session_cls.return_value = mock_session

                    result = _set_name("192.168.1.101", "Test")
                    data = json.loads(result)
                    assert data["success"] is False
                    assert data["error"]["code"] == "DEVICE_ERROR"


# ---------------------------------------------------------------------------
# _configure_mqtt / iot_configure_mqtt
# ---------------------------------------------------------------------------


class TestConfigureMQTT:
    """Tests for _configure_mqtt / iot_configure_mqtt — MQTT broker settings."""

    def test_configure_mqtt_all_params(self):
        """All MQTT parameters provided — all applied and reflected in response."""
        with patch("tools.iot_config._resolve_or_fail", return_value="192.168.1.101"):
            with patch("tools.iot_discovery._detect_device_type", return_value="openbk"):
                with patch("tools.iot_config._DeviceHttpSession") as mock_session_cls:
                    mock_session = MagicMock()
                    mock_session_cls.return_value = mock_session

                    result = _configure_mqtt(
                        "192.168.1.101",
                        host="192.168.1.50",
                        port=1883,
                        client="openbk_test",
                        group="living_room",
                        user="mqtt_user",
                        password="secret123",
                    )
                    data = json.loads(result)

                    assert data["success"] is True
                    assert data["data"]["device_type"] == "openbk"
                    assert data["data"]["host"] == "192.168.1.50"
                    assert data["data"]["port"] == 1883
                    assert "host" in data["data"]["applied"]
                    assert "port" in data["data"]["applied"]
                    assert "client" in data["data"]["applied"]
                    assert "group" in data["data"]["applied"]
                    assert "user" in data["data"]["applied"]
                    assert "password" in data["data"]["applied"]

    def test_configure_mqtt_minimal_params(self):
        """Only identifier provided — port defaults to 1883 and is always applied."""
        with patch("tools.iot_config._resolve_or_fail", return_value="192.168.1.101"):
            with patch("tools.iot_discovery._detect_device_type", return_value="openbk"):
                with patch("tools.iot_config._DeviceHttpSession") as mock_session_cls:
                    mock_session = MagicMock()
                    mock_session_cls.return_value = mock_session

                    result = _configure_mqtt("192.168.1.101")
                    data = json.loads(result)

                    assert data["success"] is True
                    assert data["data"]["port"] == 1883
                    assert "port" in data["data"]["applied"]

    def test_configure_mqtt_host_only(self):
        """Only host parameter — host and port in applied list (port always defaults)."""
        with patch("tools.iot_config._resolve_or_fail", return_value="192.168.1.101"):
            with patch("tools.iot_discovery._detect_device_type", return_value="openbk"):
                with patch("tools.iot_config._DeviceHttpSession") as mock_session_cls:
                    mock_session = MagicMock()
                    mock_session_cls.return_value = mock_session

                    result = _configure_mqtt("192.168.1.101", host="192.168.1.200")
                    data = json.loads(result)

                    assert data["success"] is True
                    assert data["data"]["host"] == "192.168.1.200"
                    assert "host" in data["data"]["applied"]
                    assert "port" in data["data"]["applied"]

    def test_configure_mqtt_port_invalid(self):
        """Port outside valid range — INVALID_PARAM."""
        with patch("tools.iot_config._resolve_or_fail", return_value="192.168.1.101"):
            result = _configure_mqtt("192.168.1.101", port=70000)
            data = json.loads(result)
            assert data["success"] is False
            assert data["error"]["code"] == "INVALID_PARAM"

    def test_configure_mqtt_port_zero(self):
        """Port 0 — INVALID_PARAM (below range)."""
        with patch("tools.iot_config._resolve_or_fail", return_value="192.168.1.101"):
            result = _configure_mqtt("192.168.1.101", port=0)
            data = json.loads(result)
            assert data["success"] is False
            assert data["error"]["code"] == "INVALID_PARAM"

    def test_configure_mqtt_name_not_resolved(self):
        """Unknown device name — NAME_NOT_RESOLVED."""
        with patch("tools.iot_config._resolve_or_fail", return_value=None):
            result = _configure_mqtt("UnknownDevice")
            data = json.loads(result)
            assert data["success"] is False
            assert data["error"]["code"] == "NAME_NOT_RESOLVED"

    def test_configure_mqtt_tasmota_unsupported(self):
        """Tasmota does not support MQTT config via HTTP — UNSUPPORTED_TYPE."""
        from tools.http_session import DeviceConnectionError

        with patch("tools.iot_config._resolve_or_fail", return_value="192.168.1.100"):
            with patch("tools.iot_discovery._detect_device_type", return_value="tasmota"):
                with patch("tools.iot_config._DeviceHttpSession") as mock_session_cls:
                    mock_session = MagicMock()
                    mock_session.get_form.side_effect = DeviceConnectionError(
                        "[UNSUPPORTED_TYPE] configure_mqtt is not supported via HTTP GET on Tasmota"
                    )
                    mock_session_cls.return_value = mock_session

                    result = _configure_mqtt("192.168.1.100", host="192.168.1.1")
                    data = json.loads(result)
                    assert data["success"] is False
                    assert data["error"]["code"] == "UNSUPPORTED_TYPE"

    def test_configure_mqtt_device_not_found(self):
        """No IoT device detected — DEVICE_NOT_FOUND."""
        with patch("tools.iot_config._resolve_or_fail", return_value="192.168.1.200"):
            with patch("tools.iot_discovery._detect_device_type", return_value=None):
                result = _configure_mqtt("192.168.1.200")
                data = json.loads(result)
                assert data["success"] is False
                assert data["error"]["code"] == "DEVICE_NOT_FOUND"

    def test_configure_mqtt_device_connection_error(self):
        """Generic connection failure — DEVICE_ERROR."""
        from tools.http_session import DeviceConnectionError

        with patch("tools.iot_config._resolve_or_fail", return_value="192.168.1.101"):
            with patch("tools.iot_discovery._detect_device_type", return_value="openbk"):
                with patch("tools.iot_config._DeviceHttpSession") as mock_session_cls:
                    mock_session = MagicMock()
                    mock_session.get_form.side_effect = DeviceConnectionError("No route to host")
                    mock_session_cls.return_value = mock_session

                    result = _configure_mqtt("192.168.1.101")
                    data = json.loads(result)
                    assert data["success"] is False
                    assert data["error"]["code"] == "DEVICE_ERROR"


# ---------------------------------------------------------------------------
# _set_gpio / iot_set_gpio
# ---------------------------------------------------------------------------


class TestSetGPIO:
    """Tests for _set_gpio / iot_set_gpio — GPIO pin assignment."""

    def test_set_gpio_openbk_success(self):
        """Configure GPIO pin on OpenBK — relay role on pin 12, channel 1."""
        with patch("tools.iot_config._resolve_or_fail", return_value="192.168.1.101"):
            with patch("tools.iot_discovery._detect_device_type", return_value="openbk"):
                with patch("tools.iot_config._DeviceHttpSession") as mock_session_cls:
                    mock_session = MagicMock()
                    mock_session_cls.return_value = mock_session

                    result = _set_gpio("192.168.1.101", pin=12, role="Relay")
                    data = json.loads(result)

                    assert data["success"] is True
                    assert data["data"]["pin"] == 12
                    assert data["data"]["role"] == "Relay"
                    assert data["data"]["channel"] == 1
                    assert data["data"]["device_type"] == "openbk"

    def test_set_gpio_custom_channel(self):
        """GPIO with explicit channel value."""
        with patch("tools.iot_config._resolve_or_fail", return_value="192.168.1.101"):
            with patch("tools.iot_discovery._detect_device_type", return_value="openbk"):
                with patch("tools.iot_config._DeviceHttpSession") as mock_session_cls:
                    mock_session = MagicMock()
                    mock_session_cls.return_value = mock_session

                    result = _set_gpio("192.168.1.101", pin=20, role="LED", channel=3)
                    data = json.loads(result)

                    assert data["success"] is True
                    assert data["data"]["pin"] == 20
                    assert data["data"]["role"] == "LED"
                    assert data["data"]["channel"] == 3

    def test_set_gpio_invalid_pin_high(self):
        """Pin 64 — INVALID_PARAM (outside 0-63)."""
        with patch("tools.iot_config._resolve_or_fail", return_value="192.168.1.101"):
            result = _set_gpio("192.168.1.101", pin=64, role="Relay")
            data = json.loads(result)
            assert data["success"] is False
            assert data["error"]["code"] == "INVALID_PARAM"

    def test_set_gpio_invalid_pin_negative(self):
        """Pin -1 — INVALID_PARAM."""
        with patch("tools.iot_config._resolve_or_fail", return_value="192.168.1.101"):
            result = _set_gpio("192.168.1.101", pin=-1, role="Relay")
            data = json.loads(result)
            assert data["success"] is False
            assert data["error"]["code"] == "INVALID_PARAM"

    def test_set_gpio_invalid_channel(self):
        """Channel 64 — INVALID_PARAM."""
        with patch("tools.iot_config._resolve_or_fail", return_value="192.168.1.101"):
            result = _set_gpio("192.168.1.101", pin=1, role="Relay", channel=64)
            data = json.loads(result)
            assert data["success"] is False
            assert data["error"]["code"] == "INVALID_PARAM"

    def test_set_gpio_tasmota_unsupported(self):
        """Tasmota — UNSUPPORTED_TYPE."""
        from tools.http_session import DeviceConnectionError

        with patch("tools.iot_config._resolve_or_fail", return_value="192.168.1.100"):
            with patch("tools.iot_discovery._detect_device_type", return_value="tasmota"):
                with patch("tools.iot_config._DeviceHttpSession") as mock_session_cls:
                    mock_session = MagicMock()
                    mock_session.get_form.side_effect = DeviceConnectionError(
                        "[UNSUPPORTED_TYPE] set_gpio is not supported via HTTP GET on Tasmota"
                    )
                    mock_session_cls.return_value = mock_session

                    result = _set_gpio("192.168.1.100", pin=12, role="Relay")
                    data = json.loads(result)
                    assert data["success"] is False
                    assert data["error"]["code"] == "UNSUPPORTED_TYPE"

    def test_set_gpio_name_not_resolved(self):
        """Unknown identifier — NAME_NOT_RESOLVED."""
        with patch("tools.iot_config._resolve_or_fail", return_value=None):
            result = _set_gpio("UnknownDevice", pin=0, role="Relay")
            data = json.loads(result)
            assert data["success"] is False
            assert data["error"]["code"] == "NAME_NOT_RESOLVED"

    def test_set_gpio_device_connection_error(self):
        """Generic connection error — DEVICE_ERROR."""
        from tools.http_session import DeviceConnectionError

        with patch("tools.iot_config._resolve_or_fail", return_value="192.168.1.101"):
            with patch("tools.iot_discovery._detect_device_type", return_value="openbk"):
                with patch("tools.iot_config._DeviceHttpSession") as mock_session_cls:
                    mock_session = MagicMock()
                    mock_session.get_form.side_effect = DeviceConnectionError("Refused")
                    mock_session_cls.return_value = mock_session

                    result = _set_gpio("192.168.1.101", pin=1, role="Btn")
                    data = json.loads(result)
                    assert data["success"] is False
                    assert data["error"]["code"] == "DEVICE_ERROR"


# ---------------------------------------------------------------------------
# _execute_command / iot_execute_command
# ---------------------------------------------------------------------------


class TestExecuteCommand:
    """Tests for _execute_command / iot_execute_command — raw command pass-through."""

    def test_execute_command_allowed(self):
        """Allowed command 'Status 0' — succeeds."""
        with patch("tools.iot_config._resolve_or_fail", return_value="192.168.1.101"):
            with patch("tools.iot_discovery._detect_device_type", return_value="openbk"):
                with patch("tools.iot_config._DeviceHttpSession") as mock_session_cls:
                    mock_session = MagicMock()
                    mock_session.get_form.return_value = "OK"
                    mock_session_cls.return_value = mock_session

                    result = _execute_command("192.168.1.101", "Status 0")
                    data = json.loads(result)

                    assert data["success"] is True
                    assert data["data"]["command"] == "Status 0"
                    assert data["data"]["response"] == "OK"

    def test_execute_command_blocked_no_force(self):
        """Blocked command 'restart' without force — COMMAND_BLOCKED."""
        with patch("tools.iot_config._resolve_or_fail", return_value="192.168.1.101"):
            with patch("tools.iot_discovery._detect_device_type", return_value="openbk"):
                result = _execute_command("192.168.1.101", "restart 1")
                data = json.loads(result)
                assert data["success"] is False
                assert data["error"]["code"] == "COMMAND_BLOCKED"

    def test_execute_command_blocked_with_force(self):
        """Blocked command with force=True — bypasses blocklist."""
        with patch("tools.iot_config._resolve_or_fail", return_value="192.168.1.101"):
            with patch("tools.iot_discovery._detect_device_type", return_value="openbk"):
                with patch("tools.iot_config._DeviceHttpSession") as mock_session_cls:
                    mock_session = MagicMock()
                    mock_session.get_form.return_value = "Device restarting..."
                    mock_session_cls.return_value = mock_session

                    result = _execute_command("192.168.1.101", "restart 1", force=True)
                    data = json.loads(result)

                    assert data["success"] is True
                    assert data["data"]["command"] == "restart 1"

    def test_execute_command_blocked_case_insensitive(self):
        """'Restart' (capitalized) — still blocked, case-insensitive check."""
        with patch("tools.iot_config._resolve_or_fail", return_value="192.168.1.101"):
            with patch("tools.iot_discovery._detect_device_type", return_value="openbk"):
                result = _execute_command("192.168.1.101", "Restart 1")
                data = json.loads(result)
                assert data["success"] is False
                assert data["error"]["code"] == "COMMAND_BLOCKED"

    def test_execute_command_blocked_format(self):
        """'Format' — blocked without force."""
        with patch("tools.iot_config._resolve_or_fail", return_value="192.168.1.101"):
            with patch("tools.iot_discovery._detect_device_type", return_value="openbk"):
                result = _execute_command("192.168.1.101", "Format")
                data = json.loads(result)
                assert data["success"] is False
                assert data["error"]["code"] == "COMMAND_BLOCKED"

    def test_execute_command_blocked_otaurl(self):
        """'OtaUrl' — blocked without force."""
        with patch("tools.iot_config._resolve_or_fail", return_value="192.168.1.101"):
            with patch("tools.iot_discovery._detect_device_type", return_value="openbk"):
                result = _execute_command("192.168.1.101", "OtaUrl http://example.com")
                data = json.loads(result)
                assert data["success"] is False
                assert data["error"]["code"] == "COMMAND_BLOCKED"

    def test_execute_command_blocked_flash(self):
        """'flash' — blocked without force."""
        with patch("tools.iot_config._resolve_or_fail", return_value="192.168.1.101"):
            with patch("tools.iot_discovery._detect_device_type", return_value="openbk"):
                result = _execute_command("192.168.1.101", "flash 1")
                data = json.loads(result)
                assert data["success"] is False
                assert data["error"]["code"] == "COMMAND_BLOCKED"

    def test_execute_command_blocked_backlog(self):
        """'backlog' with destructive sub-commands — blocked without force."""
        with patch("tools.iot_config._resolve_or_fail", return_value="192.168.1.101"):
            with patch("tools.iot_discovery._detect_device_type", return_value="openbk"):
                result = _execute_command("192.168.1.101", "backlog format 1")
                data = json.loads(result)
                assert data["success"] is False
                assert data["error"]["code"] == "COMMAND_BLOCKED"
                assert "destructive sub-commands" in data["error"]["message"]

    def test_execute_command_safe_backlog_allowed(self):
        """'backlog' with safe sub-commands (e.g. 'Power1 ON') — allowed."""
        with patch("tools.iot_config._resolve_or_fail", return_value="192.168.1.101"):
            with patch("tools.iot_discovery._detect_device_type", return_value="openbk"):
                with patch("tools.iot_config._DeviceHttpSession") as mock_session_cls:
                    mock_session = MagicMock()
                    mock_session.get_form.return_value = "OK"
                    mock_session_cls.return_value = mock_session

                    result = _execute_command("192.168.1.101", "backlog Power1 ON")
                    data = json.loads(result)
                    assert data["success"] is True

    def test_execute_command_backlog_with_reset_blocked(self):
        """'backlog reset 1' — contains destructive sub-command, blocked."""
        with patch("tools.iot_config._resolve_or_fail", return_value="192.168.1.101"):
            with patch("tools.iot_discovery._detect_device_type", return_value="openbk"):
                result = _execute_command("192.168.1.101", "backlog reset 1")
                data = json.loads(result)
                assert data["success"] is False
                assert data["error"]["code"] == "COMMAND_BLOCKED"

    def test_execute_command_all_blocked_force_bypass(self):
        """All 6 blocked commands passed with force=True — all succeed."""
        blocked = ["Format", "reset", "restart", "OtaUrl", "flash", "backlog"]
        for cmd in blocked:
            with patch("tools.iot_config._resolve_or_fail", return_value="192.168.1.101"):
                with patch("tools.iot_discovery._detect_device_type", return_value="openbk"):
                    with patch("tools.iot_config._DeviceHttpSession") as mock_session_cls:
                        mock_session = MagicMock()
                        mock_session.get_form.return_value = "OK"
                        mock_session_cls.return_value = mock_session

                        result = _execute_command("192.168.1.101", f"{cmd} X", force=True)
                        data = json.loads(result)
                        assert data["success"] is True, (
                            f"Blocked command '{cmd}' should pass with force=True"
                        )

    def test_execute_command_name_not_resolved(self):
        """Unknown identifier — NAME_NOT_RESOLVED."""
        with patch("tools.iot_config._resolve_or_fail", return_value=None):
            result = _execute_command("UnknownDevice", "Power1 ON")
            data = json.loads(result)
            assert data["success"] is False
            assert data["error"]["code"] == "NAME_NOT_RESOLVED"

    def test_execute_command_empty_command(self):
        """Empty command — INVALID_PARAM."""
        result = _execute_command("192.168.1.101", "")
        data = json.loads(result)
        assert data["success"] is False
        assert data["error"]["code"] == "INVALID_PARAM"

    def test_execute_command_device_not_found(self):
        """No IoT device — DEVICE_NOT_FOUND."""
        with patch("tools.iot_config._resolve_or_fail", return_value="192.168.1.200"):
            with patch("tools.iot_discovery._detect_device_type", return_value=None):
                result = _execute_command("192.168.1.200", "Power1 ON")
                data = json.loads(result)
                assert data["success"] is False
                assert data["error"]["code"] == "DEVICE_NOT_FOUND"

    def test_execute_command_tasmota_success(self):
        """Execute command on Tasmota device — succeeds via get_json."""
        with patch("tools.iot_config._resolve_or_fail", return_value="192.168.1.100"):
            with patch("tools.iot_discovery._detect_device_type", return_value="tasmota"):
                with patch("tools.iot_config._DeviceHttpSession") as mock_session_cls:
                    mock_session = MagicMock()
                    mock_session.get_form.return_value = '{"POWER":"ON"}'
                    mock_session_cls.return_value = mock_session

                    result = _execute_command("192.168.1.100", "Status 0")
                    data = json.loads(result)

                    assert data["success"] is True
                    assert data["data"]["device_type"] == "tasmota"
                    assert data["data"]["response"] == '{"POWER":"ON"}'

    def test_execute_command_response_truncated(self):
        """Response longer than 500 chars — truncated to 500."""
        with patch("tools.iot_config._resolve_or_fail", return_value="192.168.1.101"):
            with patch("tools.iot_discovery._detect_device_type", return_value="openbk"):
                with patch("tools.iot_config._DeviceHttpSession") as mock_session_cls:
                    mock_session = MagicMock()
                    long_response = "X" * 600
                    mock_session.get_form.return_value = long_response
                    mock_session_cls.return_value = mock_session

                    result = _execute_command("192.168.1.101", "Status 0")
                    data = json.loads(result)

                    assert data["success"] is True
                    assert len(data["data"]["response"]) == 500

    def test_execute_command_device_connection_error(self):
        """Device unreachable — DEVICE_ERROR."""
        from tools.http_session import DeviceConnectionError

        with patch("tools.iot_config._resolve_or_fail", return_value="192.168.1.101"):
            with patch("tools.iot_discovery._detect_device_type", return_value="openbk"):
                with patch("tools.iot_config._DeviceHttpSession") as mock_session_cls:
                    mock_session = MagicMock()
                    mock_session.get_form.side_effect = DeviceConnectionError("Timed out")
                    mock_session_cls.return_value = mock_session

                    result = _execute_command("192.168.1.101", "Power1 ON")
                    data = json.loads(result)
                    assert data["success"] is False
                    assert data["error"]["code"] == "DEVICE_ERROR"


# ---------------------------------------------------------------------------
# Command blocklist coverage (per-command edge cases)
# ---------------------------------------------------------------------------


class TestCommandBlocklist:
    """Per-command coverage of the _BLOCKED_COMMANDS set."""

    def test_blocked_reset(self):
        with patch("tools.iot_config._resolve_or_fail", return_value="192.168.1.101"):
            with patch("tools.iot_discovery._detect_device_type", return_value="openbk"):
                result = _execute_command("192.168.1.101", "reset 5")
                data = json.loads(result)
                assert data["error"]["code"] == "COMMAND_BLOCKED"

    def test_blocked_format_with_extra_args(self):
        with patch("tools.iot_config._resolve_or_fail", return_value="192.168.1.101"):
            with patch("tools.iot_discovery._detect_device_type", return_value="openbk"):
                result = _execute_command("192.168.1.101", "Format ALL")
                data = json.loads(result)
                assert data["error"]["code"] == "COMMAND_BLOCKED"

    def test_allowed_power_command(self):
        """'Power1 ON' — not blocked, succeeds."""
        with patch("tools.iot_config._resolve_or_fail", return_value="192.168.1.101"):
            with patch("tools.iot_discovery._detect_device_type", return_value="openbk"):
                with patch("tools.iot_config._DeviceHttpSession") as mock_session_cls:
                    mock_session = MagicMock()
                    mock_session.get_form.return_value = "OK"
                    mock_session_cls.return_value = mock_session

                    result = _execute_command("192.168.1.101", "Power1 ON")
                    data = json.loads(result)
                    assert data["success"] is True

    def test_allowed_status_command(self):
        """'Status 0' — not blocked, succeeds."""
        with patch("tools.iot_config._resolve_or_fail", return_value="192.168.1.101"):
            with patch("tools.iot_discovery._detect_device_type", return_value="openbk"):
                with patch("tools.iot_config._DeviceHttpSession") as mock_session_cls:
                    mock_session = MagicMock()
                    mock_session.get_form.return_value = "OK"
                    mock_session_cls.return_value = mock_session

                    result = _execute_command("192.168.1.101", "Status 0")
                    data = json.loads(result)
                    assert data["success"] is True

    def test_blocklist_not_triggered_by_substring(self):
        """'restarting' — NOT blocked (only exact first-word match)."""
        with patch("tools.iot_config._resolve_or_fail", return_value="192.168.1.101"):
            with patch("tools.iot_discovery._detect_device_type", return_value="openbk"):
                with patch("tools.iot_config._DeviceHttpSession") as mock_session_cls:
                    mock_session = MagicMock()
                    mock_session.get_form.return_value = "OK"
                    mock_session_cls.return_value = mock_session

                    result = _execute_command("192.168.1.101", "restarting service")
                    data = json.loads(result)
                    assert data["success"] is True

    def test_blocklist_whitespace_only(self):
        """Whitespace-only command — rejected by validate_required_string."""
        with patch("tools.iot_config._resolve_or_fail", return_value="192.168.1.101"):
            result = _execute_command("192.168.1.101", "   ")
            data = json.loads(result)
            assert data["success"] is False
            assert data["error"]["code"] == "INVALID_PARAM"


# ---------------------------------------------------------------------------
# Flag bitfield conversion tests
# ---------------------------------------------------------------------------


class TestFlagBitfieldConversion:
    """Tests for flag bitfield to URL parameter conversion."""

    def test_single_bit_low(self):
        """Flag 0 — 'flag0=1&setFlags=1'."""
        with patch("tools.iot_config._resolve_or_fail", return_value="192.168.1.101"):
            with patch("tools.iot_discovery._detect_device_type", return_value="openbk"):
                with patch("tools.iot_config._DeviceHttpSession") as mock_session_cls:
                    mock_session = MagicMock()
                    mock_session_cls.return_value = mock_session

                    _set_flags("192.168.1.101", 1)
                    call_path = mock_session.get_form.call_args[0][0]
                    assert "flag0=1" in call_path
                    assert "flag1=1" not in call_path

    def test_multiple_bits_url_order(self):
        """Bits 5 and 10 — both appear in URL."""
        with patch("tools.iot_config._resolve_or_fail", return_value="192.168.1.101"):
            with patch("tools.iot_discovery._detect_device_type", return_value="openbk"):
                with patch("tools.iot_config._DeviceHttpSession") as mock_session_cls:
                    mock_session = MagicMock()
                    mock_session_cls.return_value = mock_session

                    flags = (1 << 5) | (1 << 10)
                    _set_flags("192.168.1.101", flags)
                    call_path = mock_session.get_form.call_args[0][0]
                    assert "flag5=1" in call_path
                    assert "flag10=1" in call_path

    def test_max_bit_63(self):
        """Flag 63 — highest supported bit."""
        with patch("tools.iot_config._resolve_or_fail", return_value="192.168.1.101"):
            with patch("tools.iot_discovery._detect_device_type", return_value="openbk"):
                with patch("tools.iot_config._DeviceHttpSession") as mock_session_cls:
                    mock_session = MagicMock()
                    mock_session_cls.return_value = mock_session

                    _set_flags("192.168.1.101", 1 << 63)
                    call_path = mock_session.get_form.call_args[0][0]
                    assert "flag63=1" in call_path

    def test_tasmota_first_bit_only(self):
        """Tasmota with bits 0 and 3 set — only first found bit (0) is sent."""
        with patch("tools.iot_config._resolve_or_fail", return_value="192.168.1.100"):
            with patch("tools.iot_discovery._detect_device_type", return_value="tasmota"):
                with patch("tools.iot_config._DeviceHttpSession") as mock_session_cls:
                    mock_session = MagicMock()
                    mock_session.get_json.return_value = {}
                    mock_session_cls.return_value = mock_session

                    flags = (1 << 0) | (1 << 3)  # bits 0 and 3
                    result = _set_flags("192.168.1.100", flags)
                    data = json.loads(result)

                    assert data["success"] is True
                    # Only SetOption0 should be called
                    call_path = mock_session.get_json.call_args[0][0]
                    assert "SetOption0" in call_path


# ---------------------------------------------------------------------------
# _start_ha_discovery / iot_start_ha_discovery
# ---------------------------------------------------------------------------


class TestStartHADiscovery:
    """Tests for _start_ha_discovery / iot_start_ha_discovery — HA discovery trigger."""

    def test_start_ha_discovery_default_prefix(self):
        """Default prefix 'homeassistant' — succeeds on OpenBK."""
        with patch("tools.iot_config._resolve_or_fail", return_value="192.168.1.101"):
            with patch("tools.iot_discovery._detect_device_type", return_value="openbk"):
                with patch("tools.iot_config._DeviceHttpSession") as mock_session_cls:
                    mock_session = MagicMock()
                    mock_session_cls.return_value = mock_session

                    result = _start_ha_discovery("192.168.1.101")
                    data = json.loads(result)

                    assert data["success"] is True
                    assert data["data"]["prefix"] == "homeassistant"
                    assert data["data"]["message"] == "HA discovery triggered"
                    assert data["data"]["device_type"] == "openbk"

    def test_start_ha_discovery_custom_prefix(self):
        """Custom prefix 'hassio' — reflected in response."""
        with patch("tools.iot_config._resolve_or_fail", return_value="192.168.1.101"):
            with patch("tools.iot_discovery._detect_device_type", return_value="openbk"):
                with patch("tools.iot_config._DeviceHttpSession") as mock_session_cls:
                    mock_session = MagicMock()
                    mock_session_cls.return_value = mock_session

                    result = _start_ha_discovery("192.168.1.101", prefix="hassio")
                    data = json.loads(result)

                    assert data["success"] is True
                    assert data["data"]["prefix"] == "hassio"

    def test_start_ha_discovery_name_not_resolved(self):
        """Unknown device — NAME_NOT_RESOLVED."""
        with patch("tools.iot_config._resolve_or_fail", return_value=None):
            result = _start_ha_discovery("UnknownDevice")
            data = json.loads(result)
            assert data["success"] is False
            assert data["error"]["code"] == "NAME_NOT_RESOLVED"

    def test_start_ha_discovery_device_not_found(self):
        """No device detected — DEVICE_NOT_FOUND."""
        with patch("tools.iot_config._resolve_or_fail", return_value="192.168.1.200"):
            with patch("tools.iot_discovery._detect_device_type", return_value=None):
                result = _start_ha_discovery("192.168.1.200")
                data = json.loads(result)
                assert data["success"] is False
                assert data["error"]["code"] == "DEVICE_NOT_FOUND"

    def test_start_ha_discovery_tasmota_unsupported(self):
        """Tasmota — UNSUPPORTED_TYPE."""
        from tools.http_session import DeviceConnectionError

        with patch("tools.iot_config._resolve_or_fail", return_value="192.168.1.100"):
            with patch("tools.iot_discovery._detect_device_type", return_value="tasmota"):
                with patch("tools.iot_config._DeviceHttpSession") as mock_session_cls:
                    mock_session = MagicMock()
                    mock_session.get_form.side_effect = DeviceConnectionError(
                        "[UNSUPPORTED_TYPE] start_ha_discovery "
                        "is not supported via HTTP GET on Tasmota"
                    )
                    mock_session_cls.return_value = mock_session

                    result = _start_ha_discovery("192.168.1.100")
                    data = json.loads(result)
                    assert data["success"] is False
                    assert data["error"]["code"] == "UNSUPPORTED_TYPE"

    def test_start_ha_discovery_device_connection_error(self):
        """Unreachable device — DEVICE_ERROR."""
        from tools.http_session import DeviceConnectionError

        with patch("tools.iot_config._resolve_or_fail", return_value="192.168.1.101"):
            with patch("tools.iot_discovery._detect_device_type", return_value="openbk"):
                with patch("tools.iot_config._DeviceHttpSession") as mock_session_cls:
                    mock_session = MagicMock()
                    mock_session.get_form.side_effect = DeviceConnectionError("Timeout")
                    mock_session_cls.return_value = mock_session

                    result = _start_ha_discovery("192.168.1.101")
                    data = json.loads(result)
                    assert data["success"] is False
                    assert data["error"]["code"] == "DEVICE_ERROR"


# ---------------------------------------------------------------------------
# _set_startup_command / iot_set_startup_command
# ---------------------------------------------------------------------------


class TestSetStartupCommand:
    """Tests for _set_startup_command / iot_set_startup_command — startup command."""

    def test_set_startup_command_openbk_success(self):
        """Set startup command on OpenBK — succeeds via get_form."""
        with patch("tools.iot_config._resolve_or_fail", return_value="192.168.1.101"):
            with patch("tools.iot_discovery._detect_device_type", return_value="openbk"):
                with patch("tools.iot_config._DeviceHttpSession") as mock_session_cls:
                    mock_session = MagicMock()
                    mock_session_cls.return_value = mock_session

                    result = _set_startup_command(
                        "192.168.1.101",
                        "SetPinRole 6 1; SetPinChannel 6 1",
                    )
                    data = json.loads(result)

                    assert data["success"] is True
                    assert data["data"]["device_type"] == "openbk"
                    assert "SetPinRole" in data["data"]["command"]
                    assert data["data"]["ip"] == "192.168.1.101"

    def test_set_startup_command_empty_identifier(self):
        """Empty identifier — INVALID_PARAM."""
        result = _set_startup_command("", "cmd")
        data = json.loads(result)
        assert data["success"] is False
        assert data["error"]["code"] == "INVALID_PARAM"

    def test_set_startup_command_empty_command(self):
        """Empty command — INVALID_PARAM."""
        result = _set_startup_command("192.168.1.101", "")
        data = json.loads(result)
        assert data["success"] is False
        assert data["error"]["code"] == "INVALID_PARAM"

    def test_set_startup_command_name_not_resolved(self):
        """Unknown device — NAME_NOT_RESOLVED."""
        with patch("tools.iot_config._resolve_or_fail", return_value=None):
            result = _set_startup_command("UnknownDevice", "cmd")
            data = json.loads(result)
            assert data["success"] is False
            assert data["error"]["code"] == "NAME_NOT_RESOLVED"

    def test_set_startup_command_device_not_found(self):
        """No IoT device — DEVICE_NOT_FOUND."""
        with patch("tools.iot_config._resolve_or_fail", return_value="192.168.1.200"):
            with patch("tools.iot_discovery._detect_device_type", return_value=None):
                result = _set_startup_command("192.168.1.200", "cmd")
                data = json.loads(result)
                assert data["success"] is False
                assert data["error"]["code"] == "DEVICE_NOT_FOUND"

    def test_set_startup_command_tasmota_success(self):
        """Tasmota — Rule1 URL is built and command is executed successfully."""
        with patch("tools.iot_config._resolve_or_fail", return_value="192.168.1.100"):
            with patch("tools.iot_discovery._detect_device_type", return_value="tasmota"):
                with patch("tools.iot_config._DeviceHttpSession") as mock_session_cls:
                    mock_session = MagicMock()
                    mock_session.get_form.return_value = "OK"
                    mock_session_cls.return_value = mock_session

                    result = _set_startup_command("192.168.1.100", "cmd")
                    data = json.loads(result)
                    assert data["success"] is True
                    assert data["data"]["device_type"] == "tasmota"
                    assert data["data"]["command"] == "cmd"

    def test_set_startup_command_device_connection_error(self):
        """Device unreachable — DEVICE_ERROR."""
        from tools.http_session import DeviceConnectionError

        with patch("tools.iot_config._resolve_or_fail", return_value="192.168.1.101"):
            with patch("tools.iot_discovery._detect_device_type", return_value="openbk"):
                with patch("tools.iot_config._DeviceHttpSession") as mock_session_cls:
                    mock_session = MagicMock()
                    mock_session.get_form.side_effect = DeviceConnectionError("Timeout")
                    mock_session_cls.return_value = mock_session

                    result = _set_startup_command("192.168.1.101", "cmd")
                    data = json.loads(result)
                    assert data["success"] is False
                    assert data["error"]["code"] == "DEVICE_ERROR"


# ---------------------------------------------------------------------------
# _set_friendly_name / iot_set_friendly_name
# ---------------------------------------------------------------------------


class TestFriendlyName:
    """Tests for _set_friendly_name / iot_set_friendly_name — device friendly name."""

    def test_set_friendly_name_tasmota_success(self):
        """Set friendly name on Tasmota device — FriendlyName1 in URL."""
        with patch("tools.iot_config._resolve_or_fail", return_value="192.168.1.100"):
            with patch("tools.iot_discovery._detect_device_type", return_value="tasmota"):
                with patch("tools.iot_config._DeviceHttpSession") as mock_session_cls:
                    mock_session = MagicMock()
                    mock_session.get_form.return_value = "OK"
                    mock_session_cls.return_value = mock_session

                    result = _set_friendly_name("192.168.1.100", "Bathroom_Mirror")
                    data = json.loads(result)

                    assert data["success"] is True
                    assert data["data"]["friendly_name"] == "Bathroom_Mirror"
                    assert data["data"]["device_type"] == "tasmota"
                    assert data["data"]["ip"] == "192.168.1.100"
                    call_url = mock_session.get_form.call_args[0][0]
                    assert "FriendlyName1" in call_url
                    assert "Bathroom_Mirror" in call_url

    def test_set_friendly_name_openbk_unsupported(self):
        """OpenBK does not support friendly name via HTTP — UNSUPPORTED_TYPE."""
        from tools.http_session import DeviceConnectionError

        with patch("tools.iot_config._resolve_or_fail", return_value="192.168.1.101"):
            with patch("tools.iot_discovery._detect_device_type", return_value="openbk"):
                with patch("tools.iot_config._DeviceHttpSession") as mock_session_cls:
                    mock_session = MagicMock()
                    mock_session.get_form.side_effect = DeviceConnectionError(
                        "[UNSUPPORTED_TYPE] set_friendly_name "
                        "is not supported via HTTP GET on OpenBK"
                    )
                    mock_session_cls.return_value = mock_session

                    result = _set_friendly_name("192.168.1.101", "Test")
                    data = json.loads(result)
                    assert data["success"] is False
                    assert data["error"]["code"] == "UNSUPPORTED_TYPE"

    def test_set_friendly_name_invalid(self):
        """Empty friendly_name — INVALID_PARAM error."""
        result = _set_friendly_name("192.168.1.100", "")
        data = json.loads(result)
        assert data["success"] is False
        assert data["error"]["code"] == "INVALID_PARAM"

    def test_set_friendly_name_not_found(self):
        """Unknown identifier — NAME_NOT_RESOLVED."""
        with patch("tools.iot_config._resolve_or_fail", return_value=None):
            result = _set_friendly_name("UnknownDevice", "Test")
            data = json.loads(result)
            assert data["success"] is False
            assert data["error"]["code"] == "NAME_NOT_RESOLVED"

    def test_set_friendly_name_wrapper_write_gate(self, mock_mcp, monkeypatch):
        """iot_set_friendly_name returns WRITE_DISABLED when writes are off."""
        monkeypatch.setattr("tools.constants.ENABLE_WRITE_OPERATIONS", False)
        register_iot_config_tools(mock_mcp)
        fn = mock_mcp.get_tool("iot_set_friendly_name")
        with patch("tools.iot_config._resolve_or_fail", return_value="192.168.1.100"):
            with patch("tools.iot_discovery._detect_device_type", return_value="tasmota"):
                with patch("tools.iot_config._DeviceHttpSession") as mock_session_cls:
                    mock_session = MagicMock()
                    mock_session_cls.return_value = mock_session
                    result = fn("192.168.1.100", "Bathroom_Mirror")
                    data = json.loads(result)
                    assert data["success"] is False
                    assert data["error"]["code"] == "WRITE_DISABLED"


# ---------------------------------------------------------------------------
# _get_full_info / iot_get_full_info
# ---------------------------------------------------------------------------


class TestGetFullInfo:
    """Tests for _get_full_info / iot_get_full_info — comprehensive device info."""

    def test_get_full_info_openbk_success(self):
        """OpenBK returns full Status JSON with all fields parsed."""
        with patch("tools.iot_config._resolve_or_fail", return_value="192.168.1.101"):
            with patch("tools.iot_discovery._detect_device_type", return_value="openbk"):
                with patch("tools.iot_config._DeviceHttpSession") as mock_session_cls:
                    mock_session = MagicMock()
                    mock_session.get_json.return_value = {
                        "Status": {
                            "DeviceName": "OpenBK_Test",
                        },
                        "StatusFWR": {"Version": "1.17.0"},
                        "StatusNET": {"Mac": "AA:BB:CC:DD:EE:FF"},
                        "StatusMQT": {"MqttHost": "192.168.1.10"},
                        "StatusSTS": {
                            "Wifi": {"SSId": "HomeWiFi", "RSSI": "55", "Signal": "-40"},
                            "Uptime": "123456",
                        },
                        "StatusLOG": {"SetOption": ["808000", "0"]},
                    }
                    mock_session_cls.return_value = mock_session

                    result = _get_full_info("192.168.1.101")
                    data = json.loads(result)

                    assert data["success"] is True
                    assert data["data"]["device_type"] == "openbk"
                    assert data["data"]["version"] == "1.17.0"
                    assert data["data"]["mac"] == "AA:BB:CC:DD:EE:FF"
                    assert data["data"]["mqtt_host"] == "192.168.1.10"
                    assert data["data"]["wifi_ssid"] == "HomeWiFi"
                    assert data["data"]["wifi_rssi"] == "55"
                    assert data["data"]["wifi_signal"] == "-40"
                    assert data["data"]["uptime"] == "123456"
                    assert data["data"]["device_name"] == "OpenBK_Test"
                    assert data["data"]["flags"]["generic_flags"] == 8421376
                    assert data["data"]["flags"]["generic_flags_2"] == 0
                    assert data["data"]["source"] == "Status 0"

    def test_get_full_info_tasmota_success(self):
        """Tasmota returns Status JSON with SetOption flags."""
        with patch("tools.iot_config._resolve_or_fail", return_value="192.168.1.100"):
            with patch("tools.iot_discovery._detect_device_type", return_value="tasmota"):
                with patch("tools.iot_config._DeviceHttpSession") as mock_session_cls:
                    mock_session = MagicMock()
                    mock_session.get_json.return_value = {
                        "Status": {
                            "DeviceName": "Tasmota_Test",
                        },
                        "StatusFWR": {"Version": "14.0.0(tasmota)"},
                        "StatusNET": {"Mac": "FF:EE:DD:CC:BB:AA"},
                        "StatusSTS": {
                            "Wifi": {"SSId": "MyNetwork", "RSSI": "85", "Signal": "-45"},
                            "Uptime": "3600",
                        },
                        "SetOption0": "1",
                        "SetOption19": "1",
                    }
                    mock_session_cls.return_value = mock_session

                    result = _get_full_info("192.168.1.100")
                    data = json.loads(result)

                    assert data["success"] is True
                    assert data["data"]["device_type"] == "tasmota"
                    assert data["data"]["version"] == "14.0.0(tasmota)"
                    assert data["data"]["mac"] == "FF:EE:DD:CC:BB:AA"
                    assert data["data"]["wifi_ssid"] == "MyNetwork"
                    assert "SetOption0" in data["data"]["flags"]["set_options"]
                    assert "SetOption19" in data["data"]["flags"]["set_options"]

    def test_get_full_info_version_fallback(self):
        """Version field 'PRG' — OpenBK fallback path."""
        with patch("tools.iot_config._resolve_or_fail", return_value="192.168.1.101"):
            with patch("tools.iot_discovery._detect_device_type", return_value="openbk"):
                with patch("tools.iot_config._DeviceHttpSession") as mock_session_cls:
                    mock_session = MagicMock()
                    mock_session.get_json.return_value = {
                        "Status": {"DeviceName": "Test"},
                        "StatusFWR": {"PRG": "2.0.0"},
                        "StatusMQT": {},
                        "StatusSTS": {"Wifi": {}},
                    }
                    mock_session_cls.return_value = mock_session

                    result = _get_full_info("192.168.1.101")
                    data = json.loads(result)

                    assert data["success"] is True
                    assert data["data"]["version"] == "2.0.0"

    def test_get_full_info_minimal_status(self):
        """Device returns minimal Status — all defaults filled."""
        with patch("tools.iot_config._resolve_or_fail", return_value="192.168.1.101"):
            with patch("tools.iot_discovery._detect_device_type", return_value="openbk"):
                with patch("tools.iot_config._DeviceHttpSession") as mock_session_cls:
                    mock_session = MagicMock()
                    mock_session.get_json.return_value = {"Status": {}}
                    mock_session_cls.return_value = mock_session

                    result = _get_full_info("192.168.1.101")
                    data = json.loads(result)

                    assert data["success"] is True
                    assert data["data"]["version"] == "Unknown"
                    assert data["data"]["mac"] == ""
                    assert data["data"]["mqtt_host"] == ""
                    assert data["data"]["wifi_ssid"] == ""

    def test_get_full_info_device_name_from_top_level(self):
        """DeviceName at top level instead of inside Status."""
        with patch("tools.iot_config._resolve_or_fail", return_value="192.168.1.101"):
            with patch("tools.iot_discovery._detect_device_type", return_value="openbk"):
                with patch("tools.iot_config._DeviceHttpSession") as mock_session_cls:
                    mock_session = MagicMock()
                    mock_session.get_json.return_value = {
                        "DeviceName": "TopLevelName",
                        "Status": {
                            "MQTT": {},
                            "Wifi": {},
                        },
                    }
                    mock_session_cls.return_value = mock_session

                    result = _get_full_info("192.168.1.101")
                    data = json.loads(result)

                    assert data["success"] is True
                    assert data["data"]["device_name"] == "TopLevelName"

    def test_get_full_info_name_not_resolved(self):
        """Unknown identifier — NAME_NOT_RESOLVED."""
        with patch("tools.iot_config._resolve_or_fail", return_value=None):
            result = _get_full_info("UnknownDevice")
            data = json.loads(result)
            assert data["success"] is False
            assert data["error"]["code"] == "NAME_NOT_RESOLVED"

    def test_get_full_info_device_not_found(self):
        """No IoT device — DEVICE_NOT_FOUND."""
        with patch("tools.iot_config._resolve_or_fail", return_value="192.168.1.200"):
            with patch("tools.iot_discovery._detect_device_type", return_value=None):
                result = _get_full_info("192.168.1.200")
                data = json.loads(result)
                assert data["success"] is False
                assert data["error"]["code"] == "DEVICE_NOT_FOUND"

    def test_get_full_info_device_connection_error(self):
        """Device unreachable — DEVICE_ERROR."""
        from tools.http_session import DeviceConnectionError

        with patch("tools.iot_config._resolve_or_fail", return_value="192.168.1.101"):
            with patch("tools.iot_discovery._detect_device_type", return_value="openbk"):
                with patch("tools.iot_config._DeviceHttpSession") as mock_session_cls:
                    mock_session = MagicMock()
                    mock_session.get_json.side_effect = DeviceConnectionError("Timeout")
                    mock_session_cls.return_value = mock_session

                    result = _get_full_info("192.168.1.101")
                    data = json.loads(result)
                    assert data["success"] is False
                    assert data["error"]["code"] == "DEVICE_ERROR"


# ---------------------------------------------------------------------------
# Registration wrappers
# ---------------------------------------------------------------------------


class TestRegistrationWrappers:
    """Tests for MCP tool registration and wrapper exception handlers."""

    def test_registration_creates_nine_tools(self, mock_mcp):
        """register_iot_config_tools registers exactly 9 tools."""
        register_iot_config_tools(mock_mcp)
        assert "iot_set_flags" in mock_mcp._tools
        assert "iot_set_name" in mock_mcp._tools
        assert "iot_configure_mqtt" in mock_mcp._tools
        assert "iot_set_gpio" in mock_mcp._tools
        assert "iot_execute_command" in mock_mcp._tools
        assert "iot_start_ha_discovery" in mock_mcp._tools
        assert "iot_set_startup_command" in mock_mcp._tools
        assert "iot_set_friendly_name" in mock_mcp._tools
        assert "iot_get_full_info" in mock_mcp._tools
        assert len(mock_mcp._tools) == 9

    def test_iot_set_flags_wrapper(self, mock_mcp):
        """iot_set_flags wrapper delegates to _set_flags and succeeds."""
        register_iot_config_tools(mock_mcp)
        fn = mock_mcp.get_tool("iot_set_flags")
        with patch("tools.iot_config._resolve_or_fail", return_value="192.168.1.101"):
            with patch("tools.iot_discovery._detect_device_type", return_value="openbk"):
                with patch("tools.iot_config._DeviceHttpSession") as mock_session_cls:
                    mock_session = MagicMock()
                    mock_session_cls.return_value = mock_session
                    result = fn("192.168.1.101", 5)
                    data = json.loads(result)
                    assert data["success"] is True

    def test_iot_set_name_wrapper(self, mock_mcp):
        """iot_set_name wrapper delegates to _set_name and succeeds."""
        register_iot_config_tools(mock_mcp)
        fn = mock_mcp.get_tool("iot_set_name")
        with patch("tools.iot_config._resolve_or_fail", return_value="192.168.1.101"):
            with patch("tools.iot_discovery._detect_device_type", return_value="openbk"):
                with patch("tools.iot_config._DeviceHttpSession") as mock_session_cls:
                    mock_session = MagicMock()
                    mock_session_cls.return_value = mock_session
                    result = fn("192.168.1.101", "OpenBK_Test")
                    data = json.loads(result)
                    assert data["success"] is True

    def test_iot_configure_mqtt_wrapper(self, mock_mcp):
        """iot_configure_mqtt wrapper succeeds."""
        register_iot_config_tools(mock_mcp)
        fn = mock_mcp.get_tool("iot_configure_mqtt")
        with patch("tools.iot_config._resolve_or_fail", return_value="192.168.1.101"):
            with patch("tools.iot_discovery._detect_device_type", return_value="openbk"):
                with patch("tools.iot_config._DeviceHttpSession") as mock_session_cls:
                    mock_session = MagicMock()
                    mock_session_cls.return_value = mock_session
                    result = fn("192.168.1.101")
                    data = json.loads(result)
                    assert data["success"] is True

    def test_iot_set_gpio_wrapper(self, mock_mcp):
        """iot_set_gpio wrapper succeeds."""
        register_iot_config_tools(mock_mcp)
        fn = mock_mcp.get_tool("iot_set_gpio")
        with patch("tools.iot_config._resolve_or_fail", return_value="192.168.1.101"):
            with patch("tools.iot_discovery._detect_device_type", return_value="openbk"):
                with patch("tools.iot_config._DeviceHttpSession") as mock_session_cls:
                    mock_session = MagicMock()
                    mock_session_cls.return_value = mock_session
                    result = fn("192.168.1.101", pin=1, role="Relay")
                    data = json.loads(result)
                    assert data["success"] is True

    def test_iot_execute_command_wrapper(self, mock_mcp):
        """iot_execute_command wrapper succeeds."""
        register_iot_config_tools(mock_mcp)
        fn = mock_mcp.get_tool("iot_execute_command")
        with patch("tools.iot_config._resolve_or_fail", return_value="192.168.1.101"):
            with patch("tools.iot_discovery._detect_device_type", return_value="openbk"):
                with patch("tools.iot_config._DeviceHttpSession") as mock_session_cls:
                    mock_session = MagicMock()
                    mock_session.get_form.return_value = "OK"
                    mock_session_cls.return_value = mock_session
                    result = fn("192.168.1.101", "Power1 ON")
                    data = json.loads(result)
                    assert data["success"] is True

    def test_iot_start_ha_discovery_wrapper(self, mock_mcp):
        """iot_start_ha_discovery wrapper succeeds."""
        register_iot_config_tools(mock_mcp)
        fn = mock_mcp.get_tool("iot_start_ha_discovery")
        with patch("tools.iot_config._resolve_or_fail", return_value="192.168.1.101"):
            with patch("tools.iot_discovery._detect_device_type", return_value="openbk"):
                with patch("tools.iot_config._DeviceHttpSession") as mock_session_cls:
                    mock_session = MagicMock()
                    mock_session_cls.return_value = mock_session
                    result = fn("192.168.1.101")
                    data = json.loads(result)
                    assert data["success"] is True

    def test_iot_set_startup_command_wrapper(self, mock_mcp):
        """iot_set_startup_command wrapper succeeds."""
        register_iot_config_tools(mock_mcp)
        fn = mock_mcp.get_tool("iot_set_startup_command")
        with patch("tools.iot_config._resolve_or_fail", return_value="192.168.1.101"):
            with patch("tools.iot_discovery._detect_device_type", return_value="openbk"):
                with patch("tools.iot_config._DeviceHttpSession") as mock_session_cls:
                    mock_session = MagicMock()
                    mock_session_cls.return_value = mock_session
                    result = fn("192.168.1.101", "SetPinRole 6 1")
                    data = json.loads(result)
                    assert data["success"] is True

    def test_iot_get_full_info_wrapper(self, mock_mcp):
        """iot_get_full_info wrapper succeeds."""
        register_iot_config_tools(mock_mcp)
        fn = mock_mcp.get_tool("iot_get_full_info")
        with patch("tools.iot_config._resolve_or_fail", return_value="192.168.1.101"):
            with patch("tools.iot_discovery._detect_device_type", return_value="openbk"):
                with patch("tools.iot_config._DeviceHttpSession") as mock_session_cls:
                    mock_session = MagicMock()
                    mock_session.get_json.return_value = {
                        "Status": {"DeviceName": "Test"},
                    }
                    mock_session_cls.return_value = mock_session
                    result = fn("192.168.1.101")
                    data = json.loads(result)
                    assert data["success"] is True

    def test_set_flags_wrapper_exception_handler(self, mock_mcp):
        """iot_set_flags handles RuntimeError from internal function."""
        register_iot_config_tools(mock_mcp)
        fn = mock_mcp.get_tool("iot_set_flags")
        with patch("tools.iot_config._set_flags", side_effect=RuntimeError("unexpected")):
            result = fn("192.168.1.101", 0)
            data = json.loads(result)
            assert data["success"] is False
            assert "unexpected" in data["error"]["message"]

    def test_set_name_wrapper_exception_handler(self, mock_mcp):
        """iot_set_name handles Exception from internal function."""
        register_iot_config_tools(mock_mcp)
        fn = mock_mcp.get_tool("iot_set_name")
        with patch("tools.iot_config._set_name", side_effect=ValueError("bad name")):
            result = fn("192.168.1.101", "Test")
            data = json.loads(result)
            assert data["success"] is False
            assert "bad name" in data["error"]["message"]

    def test_configure_mqtt_wrapper_exception_handler(self, mock_mcp):
        """iot_configure_mqtt handles Exception from internal function."""
        register_iot_config_tools(mock_mcp)
        fn = mock_mcp.get_tool("iot_configure_mqtt")
        with patch("tools.iot_config._configure_mqtt", side_effect=OSError("disk full")):
            result = fn("192.168.1.101")
            data = json.loads(result)
            assert data["success"] is False
            assert "disk full" in data["error"]["message"]

    def test_set_gpio_wrapper_exception_handler(self, mock_mcp):
        """iot_set_gpio handles Exception from internal function."""
        register_iot_config_tools(mock_mcp)
        fn = mock_mcp.get_tool("iot_set_gpio")
        with patch("tools.iot_config._set_gpio", side_effect=Exception("boom")):
            result = fn("192.168.1.101", pin=1, role="Relay")
            data = json.loads(result)
            assert data["success"] is False
            assert "boom" in data["error"]["message"]

    def test_execute_command_wrapper_exception_handler(self, mock_mcp):
        """iot_execute_command handles Exception from internal function."""
        register_iot_config_tools(mock_mcp)
        fn = mock_mcp.get_tool("iot_execute_command")
        with patch("tools.iot_config._execute_command", side_effect=RuntimeError("crash")):
            result = fn("192.168.1.101", "Status 0")
            data = json.loads(result)
            assert data["success"] is False
            assert "crash" in data["error"]["message"]

    def test_start_ha_discovery_wrapper_exception_handler(self, mock_mcp):
        """iot_start_ha_discovery handles Exception from internal function."""
        register_iot_config_tools(mock_mcp)
        fn = mock_mcp.get_tool("iot_start_ha_discovery")
        with patch("tools.iot_config._start_ha_discovery", side_effect=Exception("fail")):
            result = fn("192.168.1.101")
            data = json.loads(result)
            assert data["success"] is False
            assert "fail" in data["error"]["message"]

    def test_set_startup_command_wrapper_exception_handler(self, mock_mcp):
        """iot_set_startup_command handles Exception from internal function."""
        register_iot_config_tools(mock_mcp)
        fn = mock_mcp.get_tool("iot_set_startup_command")
        with patch("tools.iot_config._set_startup_command", side_effect=RuntimeError("boom")):
            result = fn("192.168.1.101", "cmd")
            data = json.loads(result)
            assert data["success"] is False
            assert "boom" in data["error"]["message"]

    def test_get_full_info_wrapper_exception_handler(self, mock_mcp):
        """iot_get_full_info handles Exception from internal function."""
        register_iot_config_tools(mock_mcp)
        fn = mock_mcp.get_tool("iot_get_full_info")
        with patch("tools.iot_config._get_full_info", side_effect=ConnectionError("no connection")):
            result = fn("192.168.1.101")
            data = json.loads(result)
            assert data["success"] is False
            assert "no connection" in data["error"]["message"]


# ---------------------------------------------------------------------------
# Write guard (ENABLE_WRITE_OPERATIONS = False)
# ---------------------------------------------------------------------------


class TestWriteGuardDisabled:
    """Write guard: tools must return WRITE_DISABLED when writes disabled."""

    def test_set_flags_rejected_when_write_disabled(self, mock_mcp, monkeypatch):
        """iot_set_flags returns WRITE_DISABLED when writes are off."""
        monkeypatch.setattr("tools.constants.ENABLE_WRITE_OPERATIONS", False)
        register_iot_config_tools(mock_mcp)
        fn = mock_mcp.get_tool("iot_set_flags")
        with patch("tools.iot_config._resolve_or_fail", return_value="192.168.1.101"):
            with patch("tools.iot_discovery._detect_device_type", return_value="openbk"):
                with patch("tools.iot_config._DeviceHttpSession") as mock_session_cls:
                    mock_session = MagicMock()
                    mock_session_cls.return_value = mock_session
                    result = fn("192.168.1.101", 0)
                    data = json.loads(result)
                    assert data["success"] is False
                    assert data["error"]["code"] == "WRITE_DISABLED"

    def test_set_name_rejected_when_write_disabled(self, mock_mcp, monkeypatch):
        """iot_set_name returns WRITE_DISABLED when writes are off."""
        monkeypatch.setattr("tools.constants.ENABLE_WRITE_OPERATIONS", False)
        register_iot_config_tools(mock_mcp)
        fn = mock_mcp.get_tool("iot_set_name")
        with patch("tools.iot_config._resolve_or_fail", return_value="192.168.1.101"):
            with patch("tools.iot_discovery._detect_device_type", return_value="openbk"):
                with patch("tools.iot_config._DeviceHttpSession") as mock_session_cls:
                    mock_session = MagicMock()
                    mock_session_cls.return_value = mock_session
                    result = fn("192.168.1.101", "Test")
                    data = json.loads(result)
                    assert data["success"] is False
                    assert data["error"]["code"] == "WRITE_DISABLED"

    def test_configure_mqtt_rejected_when_write_disabled(self, mock_mcp, monkeypatch):
        """iot_configure_mqtt returns WRITE_DISABLED when writes are off."""
        monkeypatch.setattr("tools.constants.ENABLE_WRITE_OPERATIONS", False)
        register_iot_config_tools(mock_mcp)
        fn = mock_mcp.get_tool("iot_configure_mqtt")
        with patch("tools.iot_config._resolve_or_fail", return_value="192.168.1.101"):
            with patch("tools.iot_discovery._detect_device_type", return_value="openbk"):
                with patch("tools.iot_config._DeviceHttpSession") as mock_session_cls:
                    mock_session = MagicMock()
                    mock_session_cls.return_value = mock_session
                    result = fn("192.168.1.101")
                    data = json.loads(result)
                    assert data["success"] is False
                    assert data["error"]["code"] == "WRITE_DISABLED"

    def test_set_gpio_rejected_when_write_disabled(self, mock_mcp, monkeypatch):
        """iot_set_gpio returns WRITE_DISABLED when writes are off."""
        monkeypatch.setattr("tools.constants.ENABLE_WRITE_OPERATIONS", False)
        register_iot_config_tools(mock_mcp)
        fn = mock_mcp.get_tool("iot_set_gpio")
        with patch("tools.iot_config._resolve_or_fail", return_value="192.168.1.101"):
            with patch("tools.iot_discovery._detect_device_type", return_value="openbk"):
                with patch("tools.iot_config._DeviceHttpSession") as mock_session_cls:
                    mock_session = MagicMock()
                    mock_session_cls.return_value = mock_session
                    result = fn("192.168.1.101", pin=1, role="Relay")
                    data = json.loads(result)
                    assert data["success"] is False
                    assert data["error"]["code"] == "WRITE_DISABLED"

    def test_execute_command_rejected_when_write_disabled(self, mock_mcp, monkeypatch):
        """iot_execute_command returns WRITE_DISABLED when writes are off."""
        monkeypatch.setattr("tools.constants.ENABLE_WRITE_OPERATIONS", False)
        register_iot_config_tools(mock_mcp)
        fn = mock_mcp.get_tool("iot_execute_command")
        with patch("tools.iot_config._resolve_or_fail", return_value="192.168.1.101"):
            with patch("tools.iot_discovery._detect_device_type", return_value="openbk"):
                with patch("tools.iot_config._DeviceHttpSession") as mock_session_cls:
                    mock_session = MagicMock()
                    mock_session_cls.return_value = mock_session
                    result = fn("192.168.1.101", "Status 0")
                    data = json.loads(result)
                    assert data["success"] is False
                    assert data["error"]["code"] == "WRITE_DISABLED"

    def test_start_ha_discovery_rejected_when_write_disabled(self, mock_mcp, monkeypatch):
        """iot_start_ha_discovery returns WRITE_DISABLED when writes are off."""
        monkeypatch.setattr("tools.constants.ENABLE_WRITE_OPERATIONS", False)
        register_iot_config_tools(mock_mcp)
        fn = mock_mcp.get_tool("iot_start_ha_discovery")
        with patch("tools.iot_config._resolve_or_fail", return_value="192.168.1.101"):
            with patch("tools.iot_discovery._detect_device_type", return_value="openbk"):
                with patch("tools.iot_config._DeviceHttpSession") as mock_session_cls:
                    mock_session = MagicMock()
                    mock_session_cls.return_value = mock_session
                    result = fn("192.168.1.101")
                    data = json.loads(result)
                    assert data["success"] is False
                    assert data["error"]["code"] == "WRITE_DISABLED"

    def test_set_startup_command_rejected_when_write_disabled(self, mock_mcp, monkeypatch):
        """iot_set_startup_command returns WRITE_DISABLED when writes are off."""
        monkeypatch.setattr("tools.constants.ENABLE_WRITE_OPERATIONS", False)
        register_iot_config_tools(mock_mcp)
        fn = mock_mcp.get_tool("iot_set_startup_command")
        with patch("tools.iot_config._resolve_or_fail", return_value="192.168.1.101"):
            with patch("tools.iot_discovery._detect_device_type", return_value="openbk"):
                with patch("tools.iot_config._DeviceHttpSession") as mock_session_cls:
                    mock_session = MagicMock()
                    mock_session_cls.return_value = mock_session
                    result = fn("192.168.1.101", "cmd")
                    data = json.loads(result)
                    assert data["success"] is False
                    assert data["error"]["code"] == "WRITE_DISABLED"

    def test_get_full_info_read_no_write_gate(self, mock_mcp, monkeypatch):
        """iot_get_full_info (READ) succeeds even when writes are disabled."""
        monkeypatch.setattr("tools.constants.ENABLE_WRITE_OPERATIONS", False)
        register_iot_config_tools(mock_mcp)
        fn = mock_mcp.get_tool("iot_get_full_info")
        with patch("tools.iot_config._resolve_or_fail", return_value="192.168.1.101"):
            with patch("tools.iot_discovery._detect_device_type", return_value="openbk"):
                with patch("tools.iot_config._DeviceHttpSession") as mock_session_cls:
                    mock_session = MagicMock()
                    mock_session.get_json.return_value = {
                        "Status": {"DeviceName": "Test"},
                    }
                    mock_session_cls.return_value = mock_session
                    result = fn("192.168.1.101")
                    data = json.loads(result)
                    assert data["success"] is True


# ---------------------------------------------------------------------------
# Unsupported device type errors
# ---------------------------------------------------------------------------


class TestUnsupportedTypeErrors:
    """Tests for UNSUPPORTED_TYPE error paths across all tools."""

    def test_set_flags_unsupported_type(self):
        """_set_flags with unknown device type — handles UNSUPPORTED_TYPE."""
        from tools.http_session import DeviceConnectionError

        with patch("tools.iot_config._resolve_or_fail", return_value="192.168.1.150"):
            with patch("tools.iot_discovery._detect_device_type", return_value="esphome"):
                with patch("tools.iot_config._DeviceHttpSession") as mock_session_cls:
                    mock_session = MagicMock()
                    mock_session.get_json.side_effect = DeviceConnectionError(
                        "[UNSUPPORTED_TYPE] Unknown device type: esphome"
                    )
                    mock_session_cls.return_value = mock_session

                    result = _set_flags("192.168.1.150", 1)
                    data = json.loads(result)
                    assert data["success"] is False
                    assert data["error"]["code"] == "UNSUPPORTED_TYPE"

    def test_execute_command_unsupported_device_type(self):
        """_execute_command on unsupported device — UNSUPPORTED_TYPE."""
        from tools.http_session import DeviceConnectionError

        with patch("tools.iot_config._resolve_or_fail", return_value="192.168.1.150"):
            with patch("tools.iot_discovery._detect_device_type", return_value="zigbee"):
                with patch("tools.iot_config._DeviceHttpSession") as mock_session_cls:
                    mock_session = MagicMock()
                    mock_session.get_form.side_effect = DeviceConnectionError(
                        "[UNSUPPORTED_TYPE] Unknown device type: zigbee"
                    )
                    mock_session_cls.return_value = mock_session

                    result = _execute_command("192.168.1.150", "Status 0")
                    data = json.loads(result)
                    assert data["success"] is False
                    assert data["error"]["code"] == "UNSUPPORTED_TYPE"

    def test_get_full_info_unsupported_type(self):
        """_get_full_info with unsupported device — UNSUPPORTED_TYPE."""
        from tools.http_session import DeviceConnectionError

        with patch("tools.iot_config._resolve_or_fail", return_value="192.168.1.150"):
            with patch("tools.iot_discovery._detect_device_type", return_value="matter"):
                with patch("tools.iot_config._DeviceHttpSession") as mock_session_cls:
                    mock_session = MagicMock()
                    mock_session.get_json.side_effect = DeviceConnectionError(
                        "[UNSUPPORTED_TYPE] get_full_info is not supported for matter"
                    )
                    mock_session_cls.return_value = mock_session

                    result = _get_full_info("192.168.1.150")
                    data = json.loads(result)
                    assert data["success"] is False
                    assert data["error"]["code"] == "UNSUPPORTED_TYPE"

    def test_set_gpio_unsupported_device_type(self):
        """_set_gpio with unsupported device — UNSUPPORTED_TYPE."""
        from tools.http_session import DeviceConnectionError

        with patch("tools.iot_config._resolve_or_fail", return_value="192.168.1.150"):
            with patch("tools.iot_discovery._detect_device_type", return_value="wiz"):
                with patch("tools.iot_config._DeviceHttpSession") as mock_session_cls:
                    mock_session = MagicMock()
                    mock_session.get_form.side_effect = DeviceConnectionError(
                        "[UNSUPPORTED_TYPE] Unknown device type: wiz"
                    )
                    mock_session_cls.return_value = mock_session

                    result = _set_gpio("192.168.1.150", pin=1, role="Relay")
                    data = json.loads(result)
                    assert data["success"] is False
                    assert data["error"]["code"] == "UNSUPPORTED_TYPE"


# ---------------------------------------------------------------------------
# Validation edge cases
# ---------------------------------------------------------------------------


class TestValidationEdgeCases:
    """Validation edge cases across tools."""

    def test_set_flags_bool_rejected(self):
        """bool True — rejected as non-integer flags value."""
        result = _set_flags("192.168.1.101", True)  # type: ignore[arg-type]
        data = json.loads(result)
        assert data["success"] is False
        assert data["error"]["code"] == "INVALID_PARAM"

    def test_set_flags_empty_identifier(self):
        """Empty string identifier — INVALID_PARAM."""
        result = _set_flags("", 0)
        data = json.loads(result)
        assert data["success"] is False
        assert data["error"]["code"] == "INVALID_PARAM"

    def test_execute_command_space_only_validates_then_fails(self):
        """Space-only command — rejected by validate_required_string as empty."""
        result = _execute_command("192.168.1.101", "   ")
        data = json.loads(result)
        assert data["success"] is False
        assert data["error"]["code"] == "INVALID_PARAM"

    def test_get_full_info_wifi_as_string(self):
        """Wifi field is string instead of dict — graceful fallback."""
        with patch("tools.iot_config._resolve_or_fail", return_value="192.168.1.101"):
            with patch("tools.iot_discovery._detect_device_type", return_value="openbk"):
                with patch("tools.iot_config._DeviceHttpSession") as mock_session_cls:
                    mock_session = MagicMock()
                    mock_session.get_json.return_value = {
                        "Status": {
                            "Wifi": "connected",
                            "MQTT": "connected",
                        }
                    }
                    mock_session_cls.return_value = mock_session

                    result = _get_full_info("192.168.1.101")
                    data = json.loads(result)

                    assert data["success"] is True
                    assert data["data"]["wifi_ssid"] == ""
                    assert data["data"]["wifi_rssi"] == ""

    def test_get_full_info_mqtt_as_string(self):
        """MQTT field is string — graceful fallback to empty host."""
        with patch("tools.iot_config._resolve_or_fail", return_value="192.168.1.101"):
            with patch("tools.iot_discovery._detect_device_type", return_value="openbk"):
                with patch("tools.iot_config._DeviceHttpSession") as mock_session_cls:
                    mock_session = MagicMock()
                    mock_session.get_json.return_value = {
                        "Status": {
                            "MQTT": "disconnected",
                            "Wifi": {},
                        }
                    }
                    mock_session_cls.return_value = mock_session

                    result = _get_full_info("192.168.1.101")
                    data = json.loads(result)

                    assert data["success"] is True
                    assert data["data"]["mqtt_host"] == ""


# ---------------------------------------------------------------------------
# INVALID_PARAM dispatched by _build_url
# ---------------------------------------------------------------------------


class TestConfigEdgeCases:
    """Edge case and error path tests covering timeouts, HTTP errors,
    non-JSON responses, overflow, special characters, and blocklist
    boundary conditions.
    """

    # -----------------------------------------------------------------------
    # Timeout / HTTP error / non-JSON
    # -----------------------------------------------------------------------

    def test_device_timeout_returns_timeout_error(self):
        """get_json raises DeviceConnectionError('Connection timed out') — DEVICE_ERROR."""
        from tools.http_session import DeviceConnectionError

        with patch("tools.iot_config._resolve_or_fail", return_value="192.168.1.101"):
            with patch("tools.iot_discovery._detect_device_type", return_value="openbk"):
                with patch("tools.iot_config._DeviceHttpSession") as mock_session_cls:
                    mock_session = MagicMock()
                    mock_session.get_json.side_effect = DeviceConnectionError(
                        "Connection timed out"
                    )
                    mock_session_cls.return_value = mock_session

                    result = _get_full_info("192.168.1.101")
                    data = json.loads(result)

                    assert data["success"] is False
                    assert data["error"]["code"] == "DEVICE_ERROR"
                    assert "Connection timed out" in data["error"]["message"]

    def test_device_http_500_returns_error(self):
        """get_form raises DeviceConnectionError('HTTP 500: ...') — DEVICE_ERROR."""
        from tools.http_session import DeviceConnectionError

        with patch("tools.iot_config._resolve_or_fail", return_value="192.168.1.101"):
            with patch("tools.iot_discovery._detect_device_type", return_value="openbk"):
                with patch("tools.iot_config._DeviceHttpSession") as mock_session_cls:
                    mock_session = MagicMock()
                    mock_session.get_form.side_effect = DeviceConnectionError(
                        "HTTP 500: Internal Server Error"
                    )
                    mock_session_cls.return_value = mock_session

                    result = _set_name("192.168.1.101", "Test")
                    data = json.loads(result)

                    assert data["success"] is False
                    assert data["error"]["code"] == "DEVICE_ERROR"
                    assert "HTTP 500" in data["error"]["message"]

    def test_device_returns_non_json(self):
        """get_json raises DeviceConnectionError for a non-JSON response — DEVICE_ERROR."""
        from tools.http_session import DeviceConnectionError

        with patch("tools.iot_config._resolve_or_fail", return_value="192.168.1.101"):
            with patch("tools.iot_discovery._detect_device_type", return_value="openbk"):
                with patch("tools.iot_config._DeviceHttpSession") as mock_session_cls:
                    mock_session = MagicMock()
                    mock_session.get_json.side_effect = DeviceConnectionError(
                        "Failed to parse JSON: Expecting value: line 1 column 1 (char 0)"
                    )
                    mock_session_cls.return_value = mock_session

                    result = _get_full_info("192.168.1.101")
                    data = json.loads(result)

                    assert data["success"] is False
                    assert data["error"]["code"] == "DEVICE_ERROR"
                    assert "JSON" in data["error"]["message"]

    def test_empty_json_response(self):
        """get_json returns {} — _get_full_info still succeeds with defaults."""
        with patch("tools.iot_config._resolve_or_fail", return_value="192.168.1.101"):
            with patch("tools.iot_discovery._detect_device_type", return_value="openbk"):
                with patch("tools.iot_config._DeviceHttpSession") as mock_session_cls:
                    mock_session = MagicMock()
                    mock_session.get_json.return_value = {}
                    mock_session_cls.return_value = mock_session

                    result = _get_full_info("192.168.1.101")
                    data = json.loads(result)

                    assert data["success"] is True
                    assert data["data"]["version"] == "Unknown"
                    assert data["data"]["mac"] == ""
                    assert data["data"]["mqtt_host"] == ""
                    assert data["data"]["wifi_ssid"] == ""
                    assert data["data"]["wifi_rssi"] == ""
                    assert data["data"]["wifi_signal"] == ""
                    assert data["data"]["device_name"] == ""

    # -----------------------------------------------------------------------
    # Special characters / name validation
    # -----------------------------------------------------------------------

    def test_url_encoding_special_chars_in_name(self):
        """Names with spaces and special chars rejected by validate_name_pattern."""
        with patch("tools.iot_config._resolve_or_fail", return_value="192.168.1.101"):
            result = _set_name("192.168.1.101", "Bad Name!")
            data = json.loads(result)
            assert data["success"] is False
            assert data["error"]["code"] == "INVALID_PARAM"
            assert "invalid characters" in data["error"]["message"]

    def test_set_name_valid_with_underscores(self):
        """Underscores and digits are allowed in device names — success."""
        with patch("tools.iot_config._resolve_or_fail", return_value="192.168.1.101"):
            with patch("tools.iot_discovery._detect_device_type", return_value="openbk"):
                with patch("tools.iot_config._DeviceHttpSession") as mock_session_cls:
                    mock_session = MagicMock()
                    mock_session_cls.return_value = mock_session

                    result = _set_name("192.168.1.101", "Test_Device_123")
                    data = json.loads(result)

                    assert data["success"] is True
                    assert data["data"]["short_name"] == "Test_Device_123"
                    assert data["data"]["device_type"] == "openbk"

    # -----------------------------------------------------------------------
    # Flag bitfield overflow / negative
    # -----------------------------------------------------------------------

    def test_flag_bitfield_max_value(self):
        """flags=2^64-1 (all 64 bits set) — OpenBK success with all flagN=1 params."""
        with patch("tools.iot_config._resolve_or_fail", return_value="192.168.1.101"):
            with patch("tools.iot_discovery._detect_device_type", return_value="openbk"):
                with patch("tools.iot_config._DeviceHttpSession") as mock_session_cls:
                    mock_session = MagicMock()
                    mock_session_cls.return_value = mock_session

                    max_flags = 2**64 - 1
                    result = _set_flags("192.168.1.101", max_flags)
                    data = json.loads(result)

                    assert data["success"] is True
                    assert data["data"]["flags_set"] == max_flags
                    assert data["data"]["device_type"] == "openbk"
                    assert data["data"]["ip"] == "192.168.1.101"

                    # Verify all 64 flagN=1 parameters are in the URL
                    call_path = mock_session.get_form.call_args[0][0]
                    for bit in range(64):
                        assert f"flag{bit}=1" in call_path

    def test_flag_bitfield_negative_validation(self):
        """flags=-1 — validate_flags_value rejects negative, INVALID_PARAM."""
        with patch("tools.iot_config._resolve_or_fail", return_value="192.168.1.101"):
            result = _set_flags("192.168.1.101", -1)
            data = json.loads(result)
            assert data["success"] is False
            assert data["error"]["code"] == "INVALID_PARAM"

    # -----------------------------------------------------------------------
    # Command blocklist boundary conditions
    # -----------------------------------------------------------------------

    def test_command_blocklist_not_backlog(self):
        """'Power1 ON' is not in blocklist — succeeds."""
        with patch("tools.iot_config._resolve_or_fail", return_value="192.168.1.100"):
            with patch("tools.iot_discovery._detect_device_type", return_value="tasmota"):
                with patch("tools.iot_config._DeviceHttpSession") as mock_session_cls:
                    mock_session = MagicMock()
                    mock_session.get_form.return_value = '{"POWER":"ON"}'
                    mock_session_cls.return_value = mock_session

                    result = _execute_command("192.168.1.100", "Power1 ON")
                    data = json.loads(result)

                    assert data["success"] is True
                    assert data["data"]["command"] == "Power1 ON"
                    assert data["data"]["device_type"] == "tasmota"

    def test_command_blocklist_backlog_with_format(self):
        """'backlog format 1; Power1 ON' has destructive sub-command — COMMAND_BLOCKED."""
        with patch("tools.iot_config._resolve_or_fail", return_value="192.168.1.100"):
            with patch("tools.iot_discovery._detect_device_type", return_value="tasmota"):
                result = _execute_command("192.168.1.100", "backlog format 1; Power1 ON")
                data = json.loads(result)
                assert data["success"] is False
                assert data["error"]["code"] == "COMMAND_BLOCKED"
                assert "destructive sub-commands" in data["error"]["message"]


class TestInvalidParamFromBuildUrl:
    """Tests for [INVALID_PARAM] errors raised by _build_url."""

    def test_set_flags_invalid_param_via_build_url(self):
        """_build_url raises [INVALID_PARAM] — caught and returned."""
        from tools.http_session import DeviceConnectionError

        with patch("tools.iot_config._resolve_or_fail", return_value="192.168.1.101"):
            with patch("tools.iot_discovery._detect_device_type", return_value="openbk"):
                with patch("tools.iot_config._DeviceHttpSession") as mock_session_cls:
                    mock_session = MagicMock()
                    mock_session.get_form.side_effect = DeviceConnectionError(
                        "[INVALID_PARAM] flags must be a non-negative integer bitfield"
                    )
                    mock_session_cls.return_value = mock_session

                    result = _set_flags("192.168.1.101", 1)
                    data = json.loads(result)
                    assert data["success"] is False
                    assert data["error"]["code"] == "INVALID_PARAM"


# ---------------------------------------------------------------------------
# Tasmota config tool URL construction tests
# ---------------------------------------------------------------------------


class TestTasmotaConfigTools:
    """Tests for Tasmota-specific config URL construction and behavior."""

    def test_set_name_tasmota_backlog(self):
        """Both names on Tasmota — backlog URL with DeviceName and FriendlyName1."""
        with (
            patch("tools.iot_config._resolve_or_fail", return_value="192.168.1.100"),
            patch("tools.iot_discovery._detect_device_type", return_value="tasmota"),
            patch("tools.iot_config._DeviceHttpSession") as mock_session_cls,
        ):
            mock_session = MagicMock()
            mock_session_cls.return_value = mock_session

            result = _set_name("192.168.1.100", "Short", full_name="Full_Name")
            data = json.loads(result)

            assert data["success"] is True
            assert data["data"]["device_type"] == "tasmota"
            assert data["data"]["short_name"] == "Short"
            assert data["data"]["full_name"] == "Full_Name"

            call_url = mock_session.get_form.call_args[0][0]
            assert "backlog" in call_url
            assert "DeviceName" in call_url
            assert "FriendlyName1" in call_url

    def test_set_name_tasmota_short_only(self):
        """Only short_name on Tasmota — URL contains DeviceName but NOT FriendlyName1 or backlog."""
        with (
            patch("tools.iot_config._resolve_or_fail", return_value="192.168.1.100"),
            patch("tools.iot_discovery._detect_device_type", return_value="tasmota"),
            patch("tools.iot_config._DeviceHttpSession") as mock_session_cls,
        ):
            mock_session = MagicMock()
            mock_session_cls.return_value = mock_session

            result = _set_name("192.168.1.100", "Short")
            data = json.loads(result)

            assert data["success"] is True
            call_url = mock_session.get_form.call_args[0][0]
            assert "DeviceName" in call_url
            assert "FriendlyName1" not in call_url
            assert "backlog" not in call_url

    def test_set_flags_tasmota_single_bit(self):
        """Single bit 0 on Tasmota — URL has SetOption0 but NOT backlog."""
        with (
            patch("tools.iot_config._resolve_or_fail", return_value="192.168.1.100"),
            patch("tools.iot_discovery._detect_device_type", return_value="tasmota"),
            patch("tools.iot_config._DeviceHttpSession") as mock_session_cls,
        ):
            mock_session = MagicMock()
            mock_session.get_json.return_value = {}
            mock_session_cls.return_value = mock_session

            result = _set_flags("192.168.1.100", 1)
            data = json.loads(result)

            assert data["success"] is True
            assert data["data"]["device_type"] == "tasmota"
            call_url = mock_session.get_json.call_args[0][0]
            assert "SetOption0" in call_url
            assert "backlog" not in call_url

    def test_set_flags_tasmota_multi_bit(self):
        """Bits 0 and 3 on Tasmota — URL uses backlog with SetOption0 and SetOption3."""
        with (
            patch("tools.iot_config._resolve_or_fail", return_value="192.168.1.100"),
            patch("tools.iot_discovery._detect_device_type", return_value="tasmota"),
            patch("tools.iot_config._DeviceHttpSession") as mock_session_cls,
        ):
            mock_session = MagicMock()
            mock_session.get_json.return_value = {}
            mock_session_cls.return_value = mock_session

            result = _set_flags("192.168.1.100", 9)
            data = json.loads(result)

            assert data["success"] is True
            call_url = mock_session.get_json.call_args[0][0]
            assert "backlog" in call_url
            assert "SetOption0" in call_url
            assert "SetOption3" in call_url

    def test_set_flags_tasmota_high_bit(self):
        """Bit 31 on Tasmota — URL uses SetOption31, no backlog."""
        with (
            patch("tools.iot_config._resolve_or_fail", return_value="192.168.1.100"),
            patch("tools.iot_discovery._detect_device_type", return_value="tasmota"),
            patch("tools.iot_config._DeviceHttpSession") as mock_session_cls,
        ):
            mock_session = MagicMock()
            mock_session.get_json.return_value = {}
            mock_session_cls.return_value = mock_session

            result = _set_flags("192.168.1.100", 1 << 31)
            data = json.loads(result)

            assert data["success"] is True
            call_url = mock_session.get_json.call_args[0][0]
            assert "SetOption31" in call_url

    def test_set_flags_tasmota_bit_32_error(self):
        """Bit 32 outside Tasmota 32-bit range — no commands to send, INVALID_PARAM."""
        with (
            patch("tools.iot_config._resolve_or_fail", return_value="192.168.1.100"),
            patch("tools.iot_discovery._detect_device_type", return_value="tasmota"),
        ):
            result = _set_flags("192.168.1.100", 1 << 32)
            data = json.loads(result)
            assert data["success"] is False
            assert data["error"]["code"] == "INVALID_PARAM"

    def test_configure_mqtt_tasmota_single(self):
        """Single MQTT host on Tasmota — URL contains MqttHost."""
        with (
            patch("tools.iot_config._resolve_or_fail", return_value="192.168.1.100"),
            patch("tools.iot_discovery._detect_device_type", return_value="tasmota"),
            patch("tools.iot_config._DeviceHttpSession") as mock_session_cls,
        ):
            mock_session = MagicMock()
            mock_session_cls.return_value = mock_session

            result = _configure_mqtt("192.168.1.100", host="192.168.1.1")
            data = json.loads(result)

            assert data["success"] is True
            assert data["data"]["device_type"] == "tasmota"
            assert data["data"]["host"] == "192.168.1.1"
            call_url = mock_session.get_form.call_args[0][0]
            assert "MqttHost" in call_url

    def test_configure_mqtt_tasmota_multi(self):
        """Multiple MQTT params — backlog URL with MqttHost, MqttPort, MqttClient."""
        with (
            patch("tools.iot_config._resolve_or_fail", return_value="192.168.1.100"),
            patch("tools.iot_discovery._detect_device_type", return_value="tasmota"),
            patch("tools.iot_config._DeviceHttpSession") as mock_session_cls,
        ):
            mock_session = MagicMock()
            mock_session_cls.return_value = mock_session

            result = _configure_mqtt(
                "192.168.1.100",
                host="192.168.1.1",
                port=1884,
                client="test_client",
            )
            data = json.loads(result)

            assert data["success"] is True
            call_url = mock_session.get_form.call_args[0][0]
            assert "backlog" in call_url
            assert "MqttHost" in call_url
            assert "MqttPort" in call_url
            assert "MqttClient" in call_url

    def test_start_ha_discovery_tasmota(self):
        """HA discovery on Tasmota — URL contains SetOption19."""
        with (
            patch("tools.iot_config._resolve_or_fail", return_value="192.168.1.100"),
            patch("tools.iot_discovery._detect_device_type", return_value="tasmota"),
            patch("tools.iot_config._DeviceHttpSession") as mock_session_cls,
        ):
            mock_session = MagicMock()
            mock_session_cls.return_value = mock_session

            result = _start_ha_discovery("192.168.1.100")
            data = json.loads(result)

            assert data["success"] is True
            assert data["data"]["device_type"] == "tasmota"
            call_url = mock_session.get_form.call_args[0][0]
            assert "SetOption19" in call_url

    def test_set_startup_command_tasmota(self):
        """Startup command on Tasmota — URL contains Rule1 and System#Boot."""
        with (
            patch("tools.iot_config._resolve_or_fail", return_value="192.168.1.100"),
            patch("tools.iot_discovery._detect_device_type", return_value="tasmota"),
            patch("tools.iot_config._DeviceHttpSession") as mock_session_cls,
        ):
            mock_session = MagicMock()
            mock_session_cls.return_value = mock_session

            result = _set_startup_command("192.168.1.100", "Power1 ON")
            data = json.loads(result)

            assert data["success"] is True
            assert data["data"]["device_type"] == "tasmota"
            call_url = mock_session.get_form.call_args[0][0]
            assert "Rule1" in call_url
            assert "System" in call_url

    def test_set_friendly_name_tasmota(self):
        """Set friendly name on Tasmota — URL contains FriendlyName1."""
        with (
            patch("tools.iot_config._resolve_or_fail", return_value="192.168.1.100"),
            patch("tools.iot_discovery._detect_device_type", return_value="tasmota"),
            patch("tools.iot_config._DeviceHttpSession") as mock_session_cls,
        ):
            mock_session = MagicMock()
            mock_session_cls.return_value = mock_session

            result = _set_friendly_name("192.168.1.100", "Test_Name")
            data = json.loads(result)

            assert data["success"] is True
            assert data["data"]["device_type"] == "tasmota"
            assert data["data"]["friendly_name"] == "Test_Name"
            call_url = mock_session.get_form.call_args[0][0]
            assert "FriendlyName1" in call_url

    def test_get_full_info_tasmota(self):
        """Tasmota Status 0 JSON parsed — version, mac, device_type from fixture."""
        from tests.mock_data.mock_responses import tasmota_status0_response

        with (
            patch("tools.iot_config._resolve_or_fail", return_value="192.168.1.100"),
            patch("tools.iot_discovery._detect_device_type", return_value="tasmota"),
            patch("tools.iot_config._DeviceHttpSession") as mock_session_cls,
        ):
            mock_session = MagicMock()
            mock_session.get_json.return_value = tasmota_status0_response()
            mock_session_cls.return_value = mock_session

            result = _get_full_info("192.168.1.100")
            data = json.loads(result)

            assert data["success"] is True
            assert data["data"]["device_type"] == "tasmota"
            assert data["data"]["version"] == "12.5.0(tasmota)"
            assert data["data"]["mac"] == "AA:BB:CC:DD:EE:22"
            assert data["data"]["wifi_ssid"] == "PabloSPOT"

    def test_get_full_info_tasmota_name_not_resolved(self):
        """Unresolvable identifier — NAME_NOT_RESOLVED."""
        with patch("tools.iot_config._resolve_or_fail", return_value=None):
            result = _get_full_info("UnknownDevice")
            data = json.loads(result)
            assert data["success"] is False
            assert data["error"]["code"] == "NAME_NOT_RESOLVED"

    def test_tasmota_device_not_found(self):
        """No IoT device detected — DEVICE_NOT_FOUND."""
        with (
            patch("tools.iot_config._resolve_or_fail", return_value="192.168.1.100"),
            patch("tools.iot_discovery._detect_device_type", return_value=None),
        ):
            result = _set_name("192.168.1.100", "Test")
            data = json.loads(result)
            assert data["success"] is False
            assert data["error"]["code"] == "DEVICE_NOT_FOUND"

    def test_tasmota_connection_error(self):
        """DeviceConnectionError during HTTP call — DEVICE_ERROR."""
        from tools.http_session import DeviceConnectionError

        with (
            patch("tools.iot_config._resolve_or_fail", return_value="192.168.1.100"),
            patch("tools.iot_discovery._detect_device_type", return_value="tasmota"),
            patch("tools.iot_config._DeviceHttpSession") as mock_session_cls,
        ):
            mock_session = MagicMock()
            mock_session.get_form.side_effect = DeviceConnectionError("Connection refused")
            mock_session_cls.return_value = mock_session

            result = _set_name("192.168.1.100", "Test")
            data = json.loads(result)
            assert data["success"] is False
            assert data["error"]["code"] == "DEVICE_ERROR"
