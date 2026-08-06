"""Regression coverage for network and structured input validation."""

from __future__ import annotations

import pytest

from tools.validators import (
    ValidationError,
    validate_cidr,
    validate_gpio_role,
    validate_http_url,
    validate_ip_format,
    validate_openhasp_telnet_command,
)

pytestmark = pytest.mark.unit


def test_ipv4_validation_checks_octets():
    assert validate_ip_format("192.168.1.10") == "192.168.1.10"
    with pytest.raises(ValidationError):
        validate_ip_format("999.168.1.10")


def test_scan_range_is_private_and_bounded():
    assert validate_cidr("192.168.1.9/24") == "192.168.1.0/24"
    with pytest.raises(ValidationError, match="too broad"):
        validate_cidr("10.0.0.0/8")
    with pytest.raises(ValidationError, match="private"):
        validate_cidr("8.8.8.0/24")


def test_firmware_url_requires_operator_allowlist(monkeypatch):
    monkeypatch.setenv("MCP_ALLOWED_FIRMWARE_HOSTS", "firmware.example")
    assert (
        validate_http_url("https://firmware.example/release.bin", "firmware_url")
        == "https://firmware.example/release.bin"
    )
    with pytest.raises(ValidationError, match="allowlisted"):
        validate_http_url("https://attacker.example/release.bin", "firmware_url")


def test_raw_telnet_allowlist_enforces_value_range():
    assert validate_openhasp_telnet_command("backlight 255") == "backlight 255"
    with pytest.raises(ValidationError):
        validate_openhasp_telnet_command("backlight 999")
    with pytest.raises(ValidationError):
        validate_openhasp_telnet_command("restart")


def test_gpio_role_is_enumerated():
    assert validate_gpio_role("Relay") == "Relay"
    with pytest.raises(ValidationError):
        validate_gpio_role("ArbitraryRole")
