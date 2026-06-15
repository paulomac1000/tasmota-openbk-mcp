"""Input validation for MCP IoT tools."""

import json
import re
from urllib.parse import urlparse


class ValidationError(Exception):
    """Raised when input fails validation."""


def validate_required_string(value: str | None, name: str) -> str:
    """Validate that a required string parameter is non-empty.

    Args:
        value: The string value to validate.
        name: Parameter name for error messages.

    Returns:
        The stripped string.

    Raises:
        ValidationError: If value is None, empty, or whitespace-only.
    """
    if not value or not value.strip():
        raise ValidationError(f"{name} is required and must not be empty")
    return value.strip()


def validate_power_state(state: str) -> str:
    """Validate that a power state is ON, OFF, or TOGGLE.

    Args:
        state: Power state string to validate.

    Returns:
        Uppercase, trimmed state string.

    Raises:
        ValidationError: If state is not a valid power state.
    """
    s = state.upper().strip()
    if s not in ("ON", "OFF", "TOGGLE"):
        raise ValidationError(f"Invalid state '{state}'. Must be ON, OFF, or TOGGLE")
    return s


def validate_brightness(value: int) -> int:
    """Validate that a brightness value is within 0-100 range.

    Args:
        value: Brightness value to validate.

    Returns:
        The validated brightness value.

    Raises:
        ValidationError: If value is outside 0-100.
    """
    if not 0 <= value <= 100:
        raise ValidationError(f"Brightness must be 0-100, got {value}")
    return value


def validate_channel(channel: int) -> int:
    """Validate that a channel number is 1 or higher.

    Args:
        channel: Channel number to validate.

    Returns:
        The validated channel number.

    Raises:
        ValidationError: If channel is less than 1.
    """
    if channel < 1:
        raise ValidationError(f"Channel must be >= 1, got {channel}")
    return channel


def validate_ip_format(ip: str) -> str:
    """Validate that a string is a valid IPv4 address format.

    Args:
        ip: IP address string to validate.

    Returns:
        The trimmed IP address string.

    Raises:
        ValidationError: If the string does not match IPv4 format.
    """
    if not re.match(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$", ip.strip()):
        raise ValidationError(f"Invalid IP address format: {ip}")
    return ip.strip()


_CIDR_RE = re.compile(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}/(\d{1,2})$")


def validate_cidr(cidr: str | None) -> str:
    """Validate a CIDR notation network range.

    Args:
        cidr: CIDR string (e.g. "192.168.1.0/24") or None.

    Returns:
        The trimmed CIDR string.

    Raises:
        ValidationError: If CIDR is None, empty, or does not match valid format.
    """
    if not cidr or not cidr.strip():
        raise ValidationError("Network range is required")
    cidr = cidr.strip()
    m = _CIDR_RE.match(cidr)
    if not m:
        raise ValidationError(f"Invalid CIDR notation: {cidr!r}. Expected format: 192.168.1.0/24")
    prefix = int(m.group(1))
    if not 0 <= prefix <= 32:
        raise ValidationError(f"Invalid CIDR prefix length: {prefix}. Must be 0-32")
    octets = cidr.split("/")[0].split(".")
    for octet in octets:
        if not 0 <= int(octet) <= 255:
            raise ValidationError(f"Invalid IP octet in CIDR: {cidr!r}. Each octet must be 0-255")
    return cidr


_NAME_PATTERN = re.compile(r"^[a-zA-Z0-9_-]+$")

_OPENHASP_TELNET_ALLOWLIST = [
    re.compile(r"^backlight(?:\s+(?:on|off|[0-9]{1,3}))?$"),
    re.compile(r"^idle\s+off$"),
    re.compile(r"^page\s+(?:[1-9]|1[0-2])$"),
    re.compile(r"^statusupdate$"),
]


def validate_openhasp_telnet_command(command: str | None) -> str:
    """Validate a raw OpenHASP Telnet command against a strict allowlist.

    Args:
        command: Raw Telnet command from the tool caller.

    Returns:
        The trimmed command.

    Raises:
        ValidationError: If the command is empty or not explicitly allowed.
    """
    command = validate_required_string(command, "command")
    if any(pattern.fullmatch(command) for pattern in _OPENHASP_TELNET_ALLOWLIST):
        return command
    raise ValidationError(
        "Command is not allowed. Use one of: backlight, backlight on/off/0-255, "
        "idle off, page 1-12, statusupdate."
    )


def validate_json_object(text: str | None, name: str) -> str:
    """Validate that a string contains a JSON object.

    Args:
        text: JSON text to validate.
        name: Parameter name for error messages.

    Returns:
        The original text if valid.

    Raises:
        ValidationError: If the text is empty, invalid JSON, or not an object.
    """
    text = validate_required_string(text, name)
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValidationError(f"{name} must be valid JSON") from exc
    if not isinstance(parsed, dict):
        raise ValidationError(f"{name} must be a JSON object")
    return text


def validate_http_url(value: str | None, name: str) -> str:
    """Validate that a string is an HTTP or HTTPS URL.

    Args:
        value: URL string to validate.
        name: Parameter name for error messages.

    Returns:
        The trimmed URL.

    Raises:
        ValidationError: If the URL is empty or not HTTP(S).
    """
    value = validate_required_string(value, name)
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValidationError(f"{name} must be an HTTP or HTTPS URL")
    return value


def validate_flags_value(flags: int) -> int:
    """Validate that a flags bitfield value is a non-negative integer within 64-bit range.

    Args:
        flags: Flags bitfield value to validate.

    Returns:
        The validated flags value.

    Raises:
        ValidationError: If value is not a non-negative integer or exceeds 2^64.
    """
    if not isinstance(flags, int) or isinstance(flags, bool):
        raise ValidationError(f"Flags must be an integer, got {type(flags).__name__}")
    if flags < 0:
        raise ValidationError(f"Flags must be non-negative, got {flags}")
    if flags >= 2**64:
        raise ValidationError(f"Flags value exceeds 64-bit range: {flags}")
    return flags


def validate_pin_range(pin: int) -> int:
    """Validate that a pin number is within valid range (0-63 for BK7231N).

    Args:
        pin: Pin number to validate.

    Returns:
        The validated pin number.

    Raises:
        ValidationError: If pin is outside 0-63 range.
    """
    if not isinstance(pin, int) or isinstance(pin, bool):
        raise ValidationError(f"Pin must be an integer, got {type(pin).__name__}")
    if not 0 <= pin <= 63:
        raise ValidationError(f"Pin must be 0-63, got {pin}")
    return pin


def validate_channel_range(channel: int) -> int:
    """Validate that a channel number is within valid range (0-63).

    Note: This is for pin channel assignment (0-63), not the device channel
    number used in power control (which is 1-based and validated by validate_channel).

    Args:
        channel: Channel number to validate.

    Returns:
        The validated channel number.

    Raises:
        ValidationError: If channel is outside 0-63 range.
    """
    if not isinstance(channel, int) or isinstance(channel, bool):
        raise ValidationError(f"Channel must be an integer, got {type(channel).__name__}")
    if not 0 <= channel <= 63:
        raise ValidationError(f"Channel must be 0-63, got {channel}")
    return channel


def validate_name_pattern(name: str) -> str:
    """Validate that a device name matches the allowed pattern.

    OpenBK device names only allow: letters (a-z, A-Z), digits (0-9),
    underscores (_), and hyphens (-). No spaces or special characters.

    Args:
        name: Name string to validate.

    Returns:
        The trimmed name string.

    Raises:
        ValidationError: If name contains invalid characters or is empty.
    """
    name = validate_required_string(name, "name")
    if not _NAME_PATTERN.match(name):
        raise ValidationError(
            f"Name '{name}' contains invalid characters. "
            "Only letters, digits, underscores, and hyphens are allowed."
        )
    return name


def validate_mqtt_port(port: int) -> int:
    """Validate that an MQTT port number is within valid range (1-65535).

    Args:
        port: Port number to validate.

    Returns:
        The validated port number.

    Raises:
        ValidationError: If port is outside 1-65535 range.
    """
    if not isinstance(port, int) or isinstance(port, bool):
        raise ValidationError(f"Port must be an integer, got {type(port).__name__}")
    if not 1 <= port <= 65535:
        raise ValidationError(f"Port must be 1-65535, got {port}")
    return port


def validate_positive_int(value: int, name: str) -> int:
    """Validate that a value is a positive integer.

    Args:
        value: Value to validate.
        name: Parameter name for error messages.

    Returns:
        The validated value.

    Raises:
        ValidationError: If value is not a positive integer.
    """
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValidationError(f"{name} must be an integer, got {type(value).__name__}")
    if value <= 0:
        raise ValidationError(f"{name} must be positive, got {value}")
    return value
