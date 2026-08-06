"""Input validation for MCP IoT tools."""

from __future__ import annotations

import ipaddress
import json
import re
from urllib.parse import urlparse


class ValidationError(Exception):
    """Raised when input fails validation."""


def validate_required_string(value: str | None, name: str) -> str:
    if not value or not value.strip():
        raise ValidationError(f"{name} is required and must not be empty")
    return value.strip()


def validate_power_state(state: str) -> str:
    value = state.upper().strip()
    if value not in {"ON", "OFF", "TOGGLE"}:
        raise ValidationError(f"Invalid state '{state}'. Must be ON, OFF, or TOGGLE")
    return value


def validate_brightness(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 100:
        raise ValidationError(f"Brightness must be 0-100, got {value}")
    return value


def validate_channel(channel: int) -> int:
    if isinstance(channel, bool) or not isinstance(channel, int) or channel < 1:
        raise ValidationError(f"Channel must be >= 1, got {channel}")
    return channel


def validate_ip_format(ip: str) -> str:
    try:
        parsed = ipaddress.ip_address(ip.strip())
    except ValueError as exc:
        raise ValidationError(f"Invalid IP address format: {ip}") from exc
    if not isinstance(parsed, ipaddress.IPv4Address):
        raise ValidationError("Only IPv4 addresses are supported")
    return str(parsed)


def validate_cidr(cidr: str | None) -> str:
    value = validate_required_string(cidr, "network_range")
    try:
        network = ipaddress.ip_network(value, strict=False)
    except ValueError as exc:
        raise ValidationError(f"Invalid CIDR notation: {value!r}") from exc
    if not isinstance(network, ipaddress.IPv4Network):
        raise ValidationError("Only IPv4 CIDR ranges are supported")
    min_prefix = int(__import__("os").getenv("MCP_MIN_SCAN_PREFIX", "24"))
    if network.prefixlen < min_prefix:
        raise ValidationError(
            f"Network range {network} is too broad; minimum prefix is /{min_prefix}"
        )
    if not network.is_private:
        raise ValidationError("Network scanning is restricted to private ranges")
    return str(network)


_NAME_PATTERN = re.compile(r"^[a-zA-Z0-9_-]+$")
_OPENHASP_TELNET_ALLOWLIST = [
    re.compile(r"^backlight(?:\s+(?:on|off|[0-9]{1,3}))?$"),
    re.compile(r"^idle\s+off$"),
    re.compile(r"^page\s+(?:[1-9]|1[0-2])$"),
    re.compile(r"^statusupdate$"),
]
_GPIO_ROLES = {
    "Relay",
    "Relay_n",
    "LED",
    "LED_n",
    "Btn",
    "Btn_n",
    "PWM",
    "WifiLED",
    "WifiLED_n",
    "None",
}


def validate_openhasp_telnet_command(command: str | None) -> str:
    value = validate_required_string(command, "command")
    if any(pattern.fullmatch(value) for pattern in _OPENHASP_TELNET_ALLOWLIST):
        if value.startswith("backlight "):
            part = value.split()[1]
            if part.isdigit() and int(part) > 255:
                raise ValidationError("backlight brightness must be 0-255")
        return value
    raise ValidationError(
        "Command is not allowed. Use one of: backlight, backlight on/off/0-255, "
        "idle off, page 1-12, statusupdate."
    )


def validate_json_object(text: str | None, name: str) -> str:
    value = validate_required_string(text, name)
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValidationError(f"{name} must be valid JSON") from exc
    if not isinstance(parsed, dict):
        raise ValidationError(f"{name} must be a JSON object")
    return value


def validate_http_url(value: str | None, name: str) -> str:
    value = validate_required_string(value, name)
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValidationError(f"{name} must be an HTTP or HTTPS URL")
    if parsed.username or parsed.password or parsed.fragment:
        raise ValidationError(f"{name} must not contain credentials or a fragment")
    try:
        host = ipaddress.ip_address(parsed.hostname)
    except ValueError:
        if not __import__("os").getenv("MCP_ALLOWED_FIRMWARE_HOSTS"):
            raise ValidationError(
                f"{name} hostname must be allowlisted in MCP_ALLOWED_FIRMWARE_HOSTS"
            )
        allowed = {
            item.strip().casefold()
            for item in __import__("os").getenv("MCP_ALLOWED_FIRMWARE_HOSTS", "").split(",")
            if item.strip()
        }
        if parsed.hostname.casefold() not in allowed:
            raise ValidationError(f"{name} hostname is not allowlisted")
    else:
        if not host.is_private:
            raise ValidationError(f"{name} IP must be private or explicitly proxied")
    return value


def validate_flags_value(flags: int) -> int:
    if not isinstance(flags, int) or isinstance(flags, bool):
        raise ValidationError(f"Flags must be an integer, got {type(flags).__name__}")
    if not 0 <= flags < 2**64:
        raise ValidationError("Flags must fit in an unsigned 64-bit integer")
    return flags


def validate_pin_range(pin: int) -> int:
    if not isinstance(pin, int) or isinstance(pin, bool) or not 0 <= pin <= 63:
        raise ValidationError(f"Pin must be 0-63, got {pin}")
    return pin


def validate_channel_range(channel: int) -> int:
    if not isinstance(channel, int) or isinstance(channel, bool) or not 0 <= channel <= 63:
        raise ValidationError(f"Channel must be 0-63, got {channel}")
    return channel


def validate_gpio_role(role: str) -> str:
    value = validate_required_string(role, "role")
    if value not in _GPIO_ROLES:
        raise ValidationError(f"Unsupported GPIO role: {value}")
    return value


def validate_name_pattern(name: str) -> str:
    value = validate_required_string(name, "name")
    if not _NAME_PATTERN.fullmatch(value):
        raise ValidationError(
            f"Name '{value}' contains invalid characters. "
            "Only letters, digits, underscores, and hyphens are allowed."
        )
    return value


def validate_mqtt_port(port: int) -> int:
    if not isinstance(port, int) or isinstance(port, bool) or not 1 <= port <= 65535:
        raise ValidationError(f"Port must be 1-65535, got {port}")
    return port


def validate_positive_int(value: int, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValidationError(f"{name} must be a positive integer")
    return value
