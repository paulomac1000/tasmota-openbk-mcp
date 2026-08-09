from __future__ import annotations

import pytest

from tools.validators import (
    ValidationError,
    validate_cidr,
    validate_gpio_role,
    validate_http_url,
    validate_ip_format,
)

pytestmark = pytest.mark.unit


def test_ip_octets_are_validated():
    with pytest.raises(ValidationError):
        validate_ip_format("999.1.1.1")


def test_scan_range_is_bounded():
    with pytest.raises(ValidationError, match="too broad"):
        validate_cidr("192.168.0.0/16")


def test_public_scan_range_is_rejected():
    with pytest.raises(ValidationError):
        validate_cidr("8.8.8.0/24")


def test_firmware_url_rejects_embedded_credentials():
    with pytest.raises(ValidationError, match="credentials"):
        validate_http_url("https://user:pass@example.com/fw.bin", "firmware_url")


def test_firmware_hostname_requires_allowlist():
    with pytest.raises(ValidationError, match="allowlisted"):
        validate_http_url("https://example.com/fw.bin", "firmware_url")


def test_gpio_role_is_allowlisted():
    assert validate_gpio_role("Relay") == "Relay"
    with pytest.raises(ValidationError):
        validate_gpio_role("ExecuteAnything")
