# mypy: disable-error-code="untyped-decorator"
"""IoT Device Configuration Tools

Device configuration tools for OpenBK and Tasmota devices.
Uses the _DeviceHttpSession from http_session.py for HTTP communication.
"""

from typing import Any

from tools.constants import (
    _error_response_extended,
    _success_response,
    check_write_enabled,
    increment_tool_count,
    inject_tool_risk_prefix,
    start_tool_context,
)
from tools.http_session import DeviceConnectionError, _build_url, _DeviceHttpSession
from tools.validators import (
    ValidationError,
    validate_channel_range,
    validate_flags_value,
    validate_mqtt_port,
    validate_name_pattern,
    validate_pin_range,
    validate_required_string,
)

__all__ = [
    "register_iot_config_tools",
    "_set_flags",
    "_set_name",
    "_configure_mqtt",
    "_set_gpio",
    "_execute_command",
    "_start_ha_discovery",
    "_get_full_info",
    "_set_startup_command",
    "_set_friendly_name",
]

# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _resolve_or_fail(identifier: str) -> str | None:
    """Resolve identifier to IP or return None and let caller handle error."""
    from tools.iot_discovery import _resolve_ip

    return _resolve_ip(identifier)


def _build_unresolved_response(identifier: str) -> str:
    """Build standard error response when identifier cannot be resolved."""
    return _error_response_extended(
        code="NAME_NOT_RESOLVED",
        message=f"Could not resolve '{identifier}' to an IP address",
        suggestion=(
            "Run iot_discover_devices() first, then use iot_list_devices() to see available names"
        ),
    )


# Command blocklist for execute_command
_BLOCKED_COMMANDS = {"Format", "reset", "restart", "OtaUrl", "flash", "backlog"}


# --------------------------------------------------------------------------- #
# Internal functions
# --------------------------------------------------------------------------- #


def _set_flags(identifier: str, flags: int, timeout_seconds: int = 10) -> str:
    """Set device configuration flags (bitfield) on an IoT device.

    Args:
        identifier: IP address or device name.
        flags: Bitfield of flags to set (0 to 2^64-1).
        timeout_seconds: Request timeout in seconds.

    Returns:
        JSON string with result.
    """
    from tools.iot_discovery import _detect_device_type

    try:
        identifier = validate_required_string(identifier, "identifier")
        flags = validate_flags_value(flags)
    except ValidationError as exc:
        return _error_response_extended(
            code="INVALID_PARAM",
            message=str(exc),
            suggestion="Use a non-empty identifier and a non-negative 64-bit integer for flags.",
        )

    ip_address = _resolve_or_fail(identifier)
    if not ip_address:
        return _build_unresolved_response(identifier)

    device_type = _detect_device_type(ip_address, timeout_seconds)
    if not device_type:
        return _error_response_extended(
            code="DEVICE_NOT_FOUND",
            message=f"No IoT device found at {ip_address} (resolved from '{identifier}')",
        )

    try:
        url_path, dev_type = _build_url(device_type, "set_flags", flags=flags)
        session = _DeviceHttpSession(f"http://{ip_address}", default_timeout=timeout_seconds)

        if dev_type == "openbk":
            session.get_form(url_path)
        else:
            session.get_json(url_path)

        return _success_response(
            {
                "device_type": dev_type,
                "flags_set": flags,
                "ip": ip_address,
            }
        )
    except DeviceConnectionError as exc:
        msg = str(exc)
        if msg.startswith("[UNSUPPORTED_TYPE]"):
            return _error_response_extended(
                code="UNSUPPORTED_TYPE",
                message=msg,
            )
        if msg.startswith("[INVALID_PARAM]"):
            return _error_response_extended(
                code="INVALID_PARAM",
                message=msg,
            )
        return _error_response_extended(code="DEVICE_ERROR", message=msg)


def _set_name(
    identifier: str,
    short_name: str,
    full_name: str | None = None,
    timeout_seconds: int = 10,
) -> str:
    """Set the device name on an OpenBK device.

    Args:
        identifier: IP address or device name.
        short_name: Device short name (alphanumeric, underscore, hyphen only).
        full_name: Optional full name for the device.
        timeout_seconds: Request timeout in seconds.

    Returns:
        JSON string with result.
    """
    from tools.iot_discovery import _detect_device_type

    try:
        identifier = validate_required_string(identifier, "identifier")
        short_name = validate_name_pattern(short_name)
        if full_name is not None:
            full_name = validate_name_pattern(full_name)
    except ValidationError as exc:
        return _error_response_extended(
            code="INVALID_PARAM",
            message=str(exc),
            suggestion=(
                "Use a non-empty identifier and names containing only letters, digits, "
                "underscores, and hyphens."
            ),
        )

    ip_address = _resolve_or_fail(identifier)
    if not ip_address:
        return _build_unresolved_response(identifier)

    device_type = _detect_device_type(ip_address, timeout_seconds)
    if not device_type:
        return _error_response_extended(
            code="DEVICE_NOT_FOUND",
            message=f"No IoT device found at {ip_address} (resolved from '{identifier}')",
        )

    params: dict[str, Any] = {"short_name": short_name}
    if full_name:
        params["full_name"] = full_name

    try:
        url_path, dev_type = _build_url(device_type, "set_name", **params)
        session = _DeviceHttpSession(f"http://{ip_address}", default_timeout=timeout_seconds)
        session.get_form(url_path)

        result: dict[str, Any] = {
            "device_type": dev_type,
            "short_name": short_name,
            "ip": ip_address,
        }
        if full_name:
            result["full_name"] = full_name

        return _success_response(result)
    except DeviceConnectionError as exc:
        msg = str(exc)
        if msg.startswith("[UNSUPPORTED_TYPE]"):
            return _error_response_extended(
                code="UNSUPPORTED_TYPE",
                message=msg,
                suggestion=(
                    "Device naming via HTTP is only supported on OpenBK devices. "
                    "For Tasmota, use the WebUI or MQTT tools."
                ),
            )
        return _error_response_extended(code="DEVICE_ERROR", message=msg)


def _configure_mqtt(
    identifier: str,
    host: str | None = None,
    port: int = 1883,
    client: str | None = None,
    group: str | None = None,
    user: str | None = None,
    password: str | None = None,
    timeout_seconds: int = 10,
) -> str:
    """Configure MQTT settings on an OpenBK device.

    All parameters except identifier are optional -- only provided values
    are applied to the device.

    Args:
        identifier: IP address or device name.
        host: MQTT broker hostname or IP.
        port: MQTT broker port (default 1883).
        client: MQTT client ID.
        group: MQTT group topic.
        user: MQTT username.
        password: MQTT password.
        timeout_seconds: Request timeout in seconds.

    Returns:
        JSON string with result.
    """
    from tools.iot_discovery import _detect_device_type

    try:
        identifier = validate_required_string(identifier, "identifier")
        if port is not None:
            port = validate_mqtt_port(port)
    except ValidationError as exc:
        return _error_response_extended(code="INVALID_PARAM", message=str(exc))

    ip_address = _resolve_or_fail(identifier)
    if not ip_address:
        return _build_unresolved_response(identifier)

    device_type = _detect_device_type(ip_address, timeout_seconds)
    if not device_type:
        return _error_response_extended(
            code="DEVICE_NOT_FOUND",
            message=f"No IoT device found at {ip_address} (resolved from '{identifier}')",
        )

    params: dict[str, Any] = {}
    applied: list[str] = []

    if host is not None:
        params["host"] = host
        applied.append("host")
    if port is not None:
        params["port"] = port
        applied.append("port")
    if client is not None:
        params["client"] = client
        applied.append("client")
    if group is not None:
        params["group"] = group
        applied.append("group")
    if user is not None:
        params["user"] = user
        applied.append("user")
    if password is not None:
        params["password"] = password
        applied.append("password")

    try:
        url_path, dev_type = _build_url(device_type, "configure_mqtt", **params)
        session = _DeviceHttpSession(f"http://{ip_address}", default_timeout=timeout_seconds)
        session.get_form(url_path)

        result: dict[str, Any] = {
            "device_type": dev_type,
            "ip": ip_address,
            "applied": applied,
        }
        if host is not None:
            result["host"] = host
        if port is not None:
            result["port"] = port

        return _success_response(result)
    except DeviceConnectionError as exc:
        msg = str(exc)
        if msg.startswith("[UNSUPPORTED_TYPE]"):
            return _error_response_extended(
                code="UNSUPPORTED_TYPE",
                message=msg,
                suggestion=(
                    "MQTT configuration via HTTP is only supported on OpenBK devices. "
                    "For Tasmota, use the WebUI or MQTT tools."
                ),
            )
        return _error_response_extended(code="DEVICE_ERROR", message=msg)


def _set_gpio(
    identifier: str,
    pin: int,
    role: str,
    channel: int = 1,
    timeout_seconds: int = 10,
) -> str:
    """Configure a GPIO pin role on an OpenBK device.

    WARNING: This physically reconfigures device pins. Incorrect configuration
    may cause device malfunction or require a factory reset to recover.

    Args:
        identifier: IP address or device name.
        pin: Pin number (0-63).
        role: GPIO role string (e.g. "Relay", "LED", "Btn").
        channel: Channel number for the pin (0-63, default 1).
        timeout_seconds: Request timeout in seconds.

    Returns:
        JSON string with result.
    """
    from tools.iot_discovery import _detect_device_type

    try:
        identifier = validate_required_string(identifier, "identifier")
        pin = validate_pin_range(pin)
        validate_required_string(role, "role")
        channel = validate_channel_range(channel)
    except ValidationError as exc:
        return _error_response_extended(code="INVALID_PARAM", message=str(exc))

    ip_address = _resolve_or_fail(identifier)
    if not ip_address:
        return _build_unresolved_response(identifier)

    device_type = _detect_device_type(ip_address, timeout_seconds)
    if not device_type:
        return _error_response_extended(
            code="DEVICE_NOT_FOUND",
            message=f"No IoT device found at {ip_address} (resolved from '{identifier}')",
        )

    try:
        url_path, dev_type = _build_url(
            device_type, "set_gpio", pin=pin, role=role, channel=channel
        )
        session = _DeviceHttpSession(f"http://{ip_address}", default_timeout=timeout_seconds)
        session.get_form(url_path)

        return _success_response(
            {
                "device_type": dev_type,
                "pin": pin,
                "role": role,
                "channel": channel,
                "ip": ip_address,
            }
        )
    except DeviceConnectionError as exc:
        msg = str(exc)
        if msg.startswith("[UNSUPPORTED_TYPE]"):
            return _error_response_extended(
                code="UNSUPPORTED_TYPE",
                message=msg,
                suggestion=(
                    "GPIO configuration via HTTP is only supported on OpenBK devices. "
                    "For Tasmota, use the WebUI or Module configuration commands."
                ),
            )
        return _error_response_extended(code="DEVICE_ERROR", message=msg)


def _execute_command(
    identifier: str,
    command: str,
    force: bool = False,
    timeout_seconds: int = 10,
) -> str:
    """Execute a raw command on an IoT device.

    WARNING: Destructive operation. Raw command pass-through to the device.
    Use only when you know the exact device command syntax.

    Args:
        identifier: IP address or device name.
        command: Raw command to send (e.g. "Power1 ON", "Status 0").
        force: Bypass the blocked-commands allowlist. Default False.
        timeout_seconds: Request timeout in seconds.

    Returns:
        JSON string with result.
    """
    from tools.iot_discovery import _detect_device_type

    try:
        identifier = validate_required_string(identifier, "identifier")
        command = validate_required_string(command, "command")
    except ValidationError as exc:
        return _error_response_extended(code="INVALID_PARAM", message=str(exc))

    # Check command against blocklist (unless force=True)
    if not force:
        first_word = command.strip().split()[0] if command.strip() else ""
        for blocked in _BLOCKED_COMMANDS:
            if first_word.lower() == blocked.lower():
                # Smart check: allow 'backlog' if no destructive sub-commands
                if blocked == "backlog":
                    rest = command.strip()[len(first_word) :].strip().lower()
                    has_blocked = any(
                        bad in rest for bad in ("format", "reset", "restart", "ota", "flash")
                    )
                    if has_blocked:
                        return _error_response_extended(
                            code="COMMAND_BLOCKED",
                            message=(
                                f"Command '{command}' is blocked. "
                                f"'backlog' contains destructive sub-commands."
                            ),
                            suggestion=("Remove destructive sub-commands or pass force=True."),
                        )
                    # Safe backlog — allow it
                    continue
                return _error_response_extended(
                    code="COMMAND_BLOCKED",
                    message=(
                        f"Command '{command}' is blocked. "
                        f"'{first_word}' requires force=True to execute."
                    ),
                    suggestion=("Pass force=True to bypass this safety check."),
                )

    ip_address = _resolve_or_fail(identifier)
    if not ip_address:
        return _build_unresolved_response(identifier)

    device_type = _detect_device_type(ip_address, timeout_seconds)
    if not device_type:
        return _error_response_extended(
            code="DEVICE_NOT_FOUND",
            message=f"No IoT device found at {ip_address} (resolved from '{identifier}')",
        )

    try:
        url_path, dev_type = _build_url(device_type, "execute_command", command=command)
        session = _DeviceHttpSession(f"http://{ip_address}", default_timeout=timeout_seconds)
        raw = session.get_form(url_path)

        # Truncate response to 500 chars
        truncated = raw[:500] if len(raw) > 500 else raw

        return _success_response(
            {
                "device_type": dev_type,
                "command": command,
                "response": truncated,
                "ip": ip_address,
            }
        )
    except DeviceConnectionError as exc:
        msg = str(exc)
        if msg.startswith("[UNSUPPORTED_TYPE]"):
            return _error_response_extended(
                code="UNSUPPORTED_TYPE",
                message=msg,
            )
        return _error_response_extended(code="DEVICE_ERROR", message=msg)


def _start_ha_discovery(
    identifier: str,
    prefix: str = "homeassistant",
    timeout_seconds: int = 10,
) -> str:
    """Trigger Home Assistant auto-discovery on an OpenBK device.

    Args:
        identifier: IP address or device name.
        prefix: MQTT discovery prefix (default "homeassistant").
        timeout_seconds: Request timeout in seconds.

    Returns:
        JSON string with result.
    """
    from tools.iot_discovery import _detect_device_type

    try:
        identifier = validate_required_string(identifier, "identifier")
    except ValidationError as exc:
        return _error_response_extended(code="INVALID_PARAM", message=str(exc))

    ip_address = _resolve_or_fail(identifier)
    if not ip_address:
        return _build_unresolved_response(identifier)

    device_type = _detect_device_type(ip_address, timeout_seconds)
    if not device_type:
        return _error_response_extended(
            code="DEVICE_NOT_FOUND",
            message=f"No IoT device found at {ip_address} (resolved from '{identifier}')",
        )

    try:
        url_path, dev_type = _build_url(device_type, "start_ha_discovery", prefix=prefix)
        session = _DeviceHttpSession(f"http://{ip_address}", default_timeout=timeout_seconds)
        session.get_form(url_path)

        return _success_response(
            {
                "device_type": dev_type,
                "prefix": prefix,
                "message": "HA discovery triggered",
                "ip": ip_address,
            }
        )
    except DeviceConnectionError as exc:
        msg = str(exc)
        if msg.startswith("[UNSUPPORTED_TYPE]"):
            return _error_response_extended(
                code="UNSUPPORTED_TYPE",
                message=msg,
                suggestion=(
                    "HA discovery via HTTP is only supported on OpenBK devices. "
                    "For Tasmota, use SetOption19 1 via MQTT or the Tasmota WebUI."
                ),
            )
        return _error_response_extended(code="DEVICE_ERROR", message=msg)


def _set_startup_command(identifier: str, command: str, timeout_seconds: int = 10) -> str:
    """Set the startup command (autoexec) on an OpenBK device.

    The startup command persists across reboots and is the only HTTP-based
    way to persist GPIO configuration on OpenBK devices.

    Args:
        identifier: IP address or device name.
        command: Startup command string (e.g. "SetPinRole 6 1; SetPinChannel 6 1").
        timeout_seconds: Request timeout in seconds.

    Returns:
        JSON string with result.
    """
    from tools.iot_discovery import _detect_device_type

    try:
        identifier = validate_required_string(identifier, "identifier")
        command = validate_required_string(command, "command")
    except ValidationError as exc:
        return _error_response_extended(code="INVALID_PARAM", message=str(exc))

    ip_address = _resolve_or_fail(identifier)
    if not ip_address:
        return _build_unresolved_response(identifier)

    device_type = _detect_device_type(ip_address, timeout_seconds)
    if not device_type:
        return _error_response_extended(
            code="DEVICE_NOT_FOUND",
            message=f"No IoT device found at {ip_address}",
        )

    try:
        url_path, dev_type = _build_url(device_type, "set_startup_command", command=command)
        session = _DeviceHttpSession(f"http://{ip_address}", default_timeout=timeout_seconds)
        session.get_form(url_path)
        return _success_response(
            {
                "device_type": dev_type,
                "command": command,
                "ip": ip_address,
                "message": "Startup command set. Device will execute on next boot.",
            }
        )
    except DeviceConnectionError as exc:
        msg = str(exc)
        if msg.startswith("[UNSUPPORTED_TYPE]"):
            return _error_response_extended(code="UNSUPPORTED_TYPE", message=msg)
        return _error_response_extended(code="DEVICE_ERROR", message=msg)


def _set_friendly_name(identifier: str, friendly_name: str, timeout_seconds: int = 10) -> str:
    """Set device friendly name (FriendlyName1) -- Tasmota-specific.

    Args:
        identifier: IP address or device name.
        friendly_name: New friendly name for the device.
        timeout_seconds: Request timeout in seconds.

    Returns:
        JSON string with result.
    """
    from tools.iot_discovery import _detect_device_type

    try:
        identifier = validate_required_string(identifier, "identifier")
        friendly_name = validate_required_string(friendly_name, "friendly_name")
    except ValidationError as exc:
        return _error_response_extended(code="INVALID_PARAM", message=str(exc))

    ip_address = _resolve_or_fail(identifier)
    if not ip_address:
        return _build_unresolved_response(identifier)

    device_type = _detect_device_type(ip_address, timeout_seconds)
    if not device_type:
        return _error_response_extended(
            code="DEVICE_NOT_FOUND",
            message=f"No IoT device found at {ip_address}",
        )

    try:
        url_path, dev_type = _build_url(
            device_type, "set_friendly_name", friendly_name=friendly_name
        )
        session = _DeviceHttpSession(f"http://{ip_address}", default_timeout=timeout_seconds)
        session.get_form(url_path)
        return _success_response(
            {
                "device_type": dev_type,
                "friendly_name": friendly_name,
                "ip": ip_address,
            }
        )
    except DeviceConnectionError as exc:
        msg = str(exc)
        if msg.startswith("[UNSUPPORTED_TYPE]"):
            return _error_response_extended(code="UNSUPPORTED_TYPE", message=msg)
        return _error_response_extended(code="DEVICE_ERROR", message=msg)


def _get_full_info(identifier: str, timeout_seconds: int = 10) -> str:
    """Get comprehensive device information including MAC, version, flags, MQTT, WiFi.

    Enhanced device info that fetches Status 0 JSON from both OpenBK and
    Tasmota devices. Returns all available metadata in a structured format.

    Args:
        identifier: IP address or device name.
        timeout_seconds: Request timeout in seconds.

    Returns:
        JSON string with comprehensive device information.
    """
    from tools.iot_discovery import _detect_device_type

    try:
        identifier = validate_required_string(identifier, "identifier")
    except ValidationError as exc:
        return _error_response_extended(code="INVALID_PARAM", message=str(exc))

    ip_address = _resolve_or_fail(identifier)
    if not ip_address:
        return _build_unresolved_response(identifier)

    device_type = _detect_device_type(ip_address, timeout_seconds)
    if not device_type:
        return _error_response_extended(
            code="DEVICE_NOT_FOUND",
            message=f"No IoT device found at {ip_address} (resolved from '{identifier}')",
        )

    try:
        url_path, dev_type = _build_url(device_type, "get_full_info")
        session = _DeviceHttpSession(f"http://{ip_address}", default_timeout=timeout_seconds)
        data = session.get_json(url_path)
    except DeviceConnectionError as exc:
        msg = str(exc)
        if msg.startswith("[UNSUPPORTED_TYPE]"):
            return _error_response_extended(
                code="UNSUPPORTED_TYPE",
                message=msg,
            )
        return _error_response_extended(code="DEVICE_ERROR", message=msg)

    # Parse the Status 0 JSON response
    # Each Status* block is a top-level key in the JSON
    status_main = data.get("Status", {})  # DeviceName, FriendlyName, Topic
    status_fwr = data.get("StatusFWR", {})  # Version, BuildDateTime, Hardware
    status_net = data.get("StatusNET", {})  # Mac, IPAddress, Hostname
    status_mqt = data.get("StatusMQT", {})  # MqttHost, MqttPort, MqttClient
    status_sts = data.get("StatusSTS", {})  # Uptime, UptimeSec, Wifi, POWER
    status_prm = data.get("StatusPRM", {})  # Uptime, GroupTopic, RestartReason
    status_log = data.get("StatusLOG", {})  # SetOption array (flags)

    device_name = data.get("DeviceName", status_main.get("DeviceName", ""))

    # Firmware version -- StatusFWR has Version
    version = (
        status_fwr.get("Version")
        or status_fwr.get("Program_version")
        or status_fwr.get("PRG")
        or "Unknown"
    )

    # MAC address -- StatusNET has Mac
    mac = status_net.get("Mac") or status_net.get("MAC", "")

    # MQTT info -- StatusMQT has MqttHost
    mqtt_host = ""
    if isinstance(status_mqt, dict):
        mqtt_host = status_mqt.get("MqttHost", "")

    # WiFi info -- StatusSTS has Wifi block
    wifi_raw = status_sts.get("Wifi", status_sts.get("WiFi", {}))
    if isinstance(wifi_raw, dict):
        wifi_ssid = wifi_raw.get("SSId", "")
        wifi_rssi = wifi_raw.get("RSSI", "")
        wifi_signal = wifi_raw.get("Signal", "")
    else:
        wifi_ssid = ""
        wifi_rssi = ""
        wifi_signal = ""

    # Uptime -- StatusSTS or StatusPRM
    uptime = status_sts.get("Uptime", status_prm.get("Uptime", ""))
    uptime_sec = status_sts.get("UptimeSec", status_prm.get("UptimeSec", 0))

    # Flags -- OpenBK: StatusLOG.SetOption[0] hex as generic_flags
    # Tasmota: StatusLOG.SetOption array
    flags_data: dict[str, Any] = {}
    if dev_type == "openbk":
        set_option = status_log.get("SetOption", [])
        if isinstance(set_option, list) and len(set_option) >= 2:
            try:
                raw_0 = int(set_option[0], 16) if isinstance(set_option[0], str) else set_option[0]
            except (ValueError, TypeError):  # fmt: skip
                raw_0 = 0
            try:
                raw_1_hex = set_option[1] if isinstance(set_option[1], str) else str(set_option[1])
                # SetOption[1] may contain >32 bits on some OBK versions — mask to uint32
                raw_1 = int(raw_1_hex[-8:] if len(raw_1_hex) > 8 else raw_1_hex, 16)
            except (ValueError, TypeError):  # fmt: skip
                raw_1 = 0
            flags_data["generic_flags"] = raw_0
            flags_data["generic_flags_2"] = raw_1
        elif isinstance(set_option, list) and len(set_option) >= 1:
            try:
                raw_0 = int(set_option[0], 16) if isinstance(set_option[0], str) else set_option[0]
            except (ValueError, TypeError):  # fmt: skip
                raw_0 = 0
            flags_data["generic_flags"] = raw_0
    elif dev_type == "tasmota":
        set_options: dict[str, Any] = {}
        for key, val in data.items():
            if key.startswith("SetOption"):
                set_options[key] = val
        flags_data["set_options"] = set_options

    result: dict[str, Any] = {
        "device_type": dev_type,
        "ip": ip_address,
        "version": version,
        "device_name": device_name,
        "mac": mac,
        "mqtt_host": mqtt_host,
        "wifi_ssid": wifi_ssid,
        "wifi_rssi": wifi_rssi,
        "wifi_signal": wifi_signal,
        "uptime": uptime,
        "uptime_sec": uptime_sec,
        "flags": flags_data,
        "source": "Status 0",
    }

    return _success_response(result)


# --------------------------------------------------------------------------- #
# MCP tool registration
# --------------------------------------------------------------------------- #


def register_iot_config_tools(mcp: Any) -> None:
    """Register IoT device configuration tools with the MCP server."""

    @mcp.tool()
    @inject_tool_risk_prefix
    def iot_set_flags(identifier: str, flags: int, timeout_seconds: int = 10) -> str:
        """Set device configuration flags (bitfield) on an IoT device.

        OpenBK supports up to 64-bit flags via /cfg_generic endpoint.
        Tasmota supports SetOption commands for options 0-31.
        For flags beyond 31, only OpenBK devices are supported.

        Args:
            identifier: IP address or device name.
            flags: Bitfield of flags to set (0 to 2^64-1). Each bit corresponds
                to a flag number (bit 0 = flag 0, bit 6 = flag 6, etc.).
            timeout_seconds: Request timeout in seconds (default 10).

        Returns:
            JSON with result.

        @since v1.6.0
        """
        try:
            start_tool_context()
            check_write_enabled()
            increment_tool_count("iot_set_flags")
            return _set_flags(identifier, flags, timeout_seconds)
        except ValidationError as exc:
            return _error_response_extended(
                code="WRITE_DISABLED",
                message=str(exc),
                retryable=False,
                suggestion="Ask the server operator to set ENABLE_WRITE_OPERATIONS=1.",
            )
        except Exception as exc:
            return _error_response_extended(code="INTERNAL_ERROR", message=str(exc))

    @mcp.tool()
    @inject_tool_risk_prefix
    def iot_set_name(
        identifier: str,
        short_name: str,
        full_name: str | None = None,
        timeout_seconds: int = 10,
    ) -> str:
        """Set the device name on an OpenBK device.

        Only OpenBK devices support name changes via HTTP. Tasmota devices
        must be renamed through the WebUI or MQTT tools.

        Args:
            identifier: IP address or device name.
            short_name: Device short name (alphanumeric, underscore, hyphen only).
            full_name: Optional full name for the device.
            timeout_seconds: Request timeout in seconds (default 10).

        Returns:
            JSON with result.

        @since v1.6.0
        """
        try:
            start_tool_context()
            check_write_enabled()
            increment_tool_count("iot_set_name")
            return _set_name(identifier, short_name, full_name, timeout_seconds)
        except ValidationError as exc:
            return _error_response_extended(
                code="WRITE_DISABLED",
                message=str(exc),
                retryable=False,
                suggestion="Ask the server operator to set ENABLE_WRITE_OPERATIONS=1.",
            )
        except Exception as exc:
            return _error_response_extended(code="INTERNAL_ERROR", message=str(exc))

    @mcp.tool()
    @inject_tool_risk_prefix
    def iot_configure_mqtt(
        identifier: str,
        host: str | None = None,
        port: int = 1883,
        client: str | None = None,
        group: str | None = None,
        user: str | None = None,
        password: str | None = None,
        timeout_seconds: int = 10,
    ) -> str:
        """Configure MQTT settings on an OpenBK device.

        All parameters except identifier are optional. Only provided values
        are applied to the device. Unspecified settings remain unchanged.

        Only OpenBK devices support MQTT configuration via HTTP. Tasmota
        devices must be configured through the WebUI or MQTT tools.

        Args:
            identifier: IP address or device name.
            host: MQTT broker hostname or IP address.
            port: MQTT broker port (default 1883).
            client: MQTT client ID for this device.
            group: MQTT group topic.
            user: MQTT username for broker authentication.
            password: MQTT password for broker authentication.
            timeout_seconds: Request timeout in seconds (default 10).

        Returns:
            JSON with result and list of applied settings.

        @since v1.6.0
        """
        try:
            start_tool_context()
            check_write_enabled()
            increment_tool_count("iot_configure_mqtt")
            return _configure_mqtt(
                identifier, host, port, client, group, user, password, timeout_seconds
            )
        except ValidationError as exc:
            return _error_response_extended(
                code="WRITE_DISABLED",
                message=str(exc),
                retryable=False,
                suggestion="Ask the server operator to set ENABLE_WRITE_OPERATIONS=1.",
            )
        except Exception as exc:
            return _error_response_extended(code="INTERNAL_ERROR", message=str(exc))

    @mcp.tool()
    @inject_tool_risk_prefix
    def iot_set_gpio(
        identifier: str,
        pin: int,
        role: str,
        channel: int = 1,
        timeout_seconds: int = 10,
    ) -> str:
        """Configure a GPIO pin role on an OpenBK device.

        WARNING: This physically reconfigures device pins. Incorrect pin
        configuration may cause device malfunction or require a factory
        reset to recover. Verify pin assignments before executing.

        Only OpenBK devices support GPIO configuration via HTTP. Tasmota
        devices must use the WebUI or Module configuration commands.

        Args:
            identifier: IP address or device name.
            pin: Pin number (0-63). Refer to device datasheet for correct pin
                mapping before changing roles.
            role: GPIO role string (e.g. "Relay", "LED", "Btn", "WifiLED").
                Case-sensitive; must match an OpenBK IORole constant.
            channel: Channel number for the pin (0-63, default 1).
            timeout_seconds: Request timeout in seconds (default 10).

        Returns:
            JSON with result.

        @since v1.6.0
        """
        try:
            start_tool_context()
            check_write_enabled()
            increment_tool_count("iot_set_gpio")
            return _set_gpio(identifier, pin, role, channel, timeout_seconds)
        except ValidationError as exc:
            return _error_response_extended(
                code="WRITE_DISABLED",
                message=str(exc),
                retryable=False,
                suggestion="Ask the server operator to set ENABLE_WRITE_OPERATIONS=1.",
            )
        except Exception as exc:
            return _error_response_extended(code="INTERNAL_ERROR", message=str(exc))

    @mcp.tool()
    @inject_tool_risk_prefix
    def iot_execute_command(
        identifier: str,
        command: str,
        force: bool = False,
        timeout_seconds: int = 10,
    ) -> str:
        """Execute a raw command on an IoT device.

        WARNING: Destructive operation. Raw command pass-through to the device
        via /cm?cmnd= endpoint. The command is URL-encoded and sent via HTTP GET.

        Dangerous commands (Format, reset, restart, OtaUrl, flash, backlog)
        are blocked unless force=True is passed.

        Args:
            identifier: IP address or device name.
            command: Raw command string (e.g. "Power1 ON", "Status 0",
                "SetOption19 1"). Space-separated; the first word is checked
                against the blocklist.
            force: Bypass the command blocklist. Set to True only when you
                intend to execute a blocked command. Default False.
            timeout_seconds: Request timeout in seconds (default 10).

        Returns:
            JSON with result, including truncated response text (up to 500 chars).

        @since v1.6.0
        """
        try:
            start_tool_context()
            check_write_enabled()
            increment_tool_count("iot_execute_command")
            return _execute_command(identifier, command, force, timeout_seconds)
        except ValidationError as exc:
            return _error_response_extended(
                code="WRITE_DISABLED",
                message=str(exc),
                retryable=False,
                suggestion="Ask the server operator to set ENABLE_WRITE_OPERATIONS=1.",
            )
        except Exception as exc:
            return _error_response_extended(code="INTERNAL_ERROR", message=str(exc))

    @mcp.tool()
    @inject_tool_risk_prefix
    def iot_start_ha_discovery(
        identifier: str,
        prefix: str = "homeassistant",
        timeout_seconds: int = 10,
    ) -> str:
        """Trigger Home Assistant auto-discovery on an OpenBK device.

        Sends the /ha_discovery command which causes the device to publish
        MQTT discovery messages using the given prefix.

        Only OpenBK devices support HA discovery via HTTP. For Tasmota,
        enable SetOption19 via MQTT or use the WebUI.

        Args:
            identifier: IP address or device name.
            prefix: MQTT discovery prefix (default "homeassistant").
            timeout_seconds: Request timeout in seconds (default 10).

        Returns:
            JSON with result.

        @since v1.6.0
        """
        try:
            start_tool_context()
            check_write_enabled()
            increment_tool_count("iot_start_ha_discovery")
            return _start_ha_discovery(identifier, prefix, timeout_seconds)
        except ValidationError as exc:
            return _error_response_extended(
                code="WRITE_DISABLED",
                message=str(exc),
                retryable=False,
                suggestion="Ask the server operator to set ENABLE_WRITE_OPERATIONS=1.",
            )
        except Exception as exc:
            return _error_response_extended(code="INTERNAL_ERROR", message=str(exc))

    @mcp.tool()
    @inject_tool_risk_prefix
    def iot_set_startup_command(identifier: str, command: str, timeout_seconds: int = 10) -> str:
        """Set device startup command (autoexec) on an OpenBK device.

        The startup command is the only HTTP-based way to persist GPIO
        pin configuration across reboots on OpenBK devices. Critical for
        device automation without Web App access.

        Args:
            identifier: IP address or device name.
            command: Startup command string (e.g. "SetPinRole 6 1; SetPinChannel 6 1").
            timeout_seconds: Request timeout in seconds (default 10).

        Returns:
            JSON with result.

        @since v1.6.0
        """
        try:
            start_tool_context()
            check_write_enabled()
            increment_tool_count("iot_set_startup_command")
            return _set_startup_command(identifier, command, timeout_seconds)
        except ValidationError as exc:
            return _error_response_extended(
                code="WRITE_DISABLED",
                message=str(exc),
                retryable=False,
                suggestion="Ask the server operator to set ENABLE_WRITE_OPERATIONS=1.",
            )
        except Exception as exc:
            return _error_response_extended(code="INTERNAL_ERROR", message=str(exc))

    @mcp.tool()
    @inject_tool_risk_prefix
    def iot_get_full_info(identifier: str, timeout_seconds: int = 10) -> str:
        """Get comprehensive device information including MAC, version, flags, MQTT, and WiFi.

        Fetches Status 0 JSON from both OpenBK and Tasmota devices and returns
        all available metadata: firmware version, device name, MAC address,
        MQTT broker host, WiFi SSID, RSSI signal strength, uptime, and flags.

        Args:
            identifier: IP address or device name.
            timeout_seconds: Request timeout in seconds (default 10).

        Returns:
            JSON with comprehensive device information.

        @since v1.6.0
        """
        try:
            start_tool_context()
            increment_tool_count("iot_get_full_info")
            return _get_full_info(identifier, timeout_seconds)
        except Exception as exc:
            return _error_response_extended(code="INTERNAL_ERROR", message=str(exc))

    @mcp.tool()
    @inject_tool_risk_prefix
    def iot_set_friendly_name(
        identifier: str, friendly_name: str, timeout_seconds: int = 10
    ) -> str:
        """Set device friendly name (FriendlyName1) on Tasmota devices.

        Args:
            identifier: IP address or device name.
            friendly_name: New friendly name for the device.
            timeout_seconds: Request timeout in seconds (default 10).

        Returns:
            JSON with result.

        @since v1.6.0
        """
        try:
            start_tool_context()
            check_write_enabled()
            increment_tool_count("iot_set_friendly_name")
            return _set_friendly_name(identifier, friendly_name, timeout_seconds)
        except ValidationError as exc:
            return _error_response_extended(
                code="WRITE_DISABLED",
                message=str(exc),
                retryable=False,
                suggestion="Ask the server operator to set ENABLE_WRITE_OPERATIONS=1.",
            )
        except Exception as exc:
            return _error_response_extended(code="INTERNAL_ERROR", message=str(exc))
