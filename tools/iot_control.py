# mypy: disable-error-code="untyped-decorator"
"""
IoT Device Control Tools

Control OpenBK and Tasmota devices (power, brightness, etc.)
Supports lookup by IP address or device name from the discovery cache.
"""

from typing import Any

import requests

from tools.constants import (
    _error_response_extended,
    _success_response,
    check_write_enabled,
    increment_tool_count,
    inject_tool_risk_prefix,
    start_tool_context,
)
from tools.validators import (
    ValidationError,
    validate_brightness,
    validate_channel,
    validate_power_state,
    validate_required_string,
)

__all__ = [
    "register_iot_control_tools",
    "_set_power",
    "_set_brightness",
    "_restart_device",
    "_get_wifi_config",
]


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


def _set_power(identifier: str, state: str, channel: int = 1, timeout_seconds: int = 10) -> str:
    """Set power state of an IoT device channel.

    Args:
        identifier: IP address or device name.
        state: Power state - "ON", "OFF", or "TOGGLE".
        channel: Channel number (1-based, default 1).
        timeout_seconds: Request timeout in seconds.

    Returns:
        JSON string with result.
    """
    from tools.iot_discovery import _detect_device_type

    try:
        identifier = validate_required_string(identifier, "identifier")
        channel = validate_channel(channel)
        state = validate_power_state(state)
    except ValidationError as exc:
        return _error_response_extended(
            code="INVALID_PARAM",
            message=str(exc),
            suggestion="Use a non-empty identifier, channel >= 1, and state ON, OFF, or TOGGLE.",
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

    if device_type == "tasmota":
        resp = requests.get(
            f"http://{ip_address}/cm?cmnd=Power{channel}%20{state}",
            timeout=timeout_seconds,
        )
        if resp.status_code == 200:
            data = resp.json()
            power_key = f"POWER{channel}"
            result_state = data.get(power_key) or data.get("POWER")
            return _success_response(
                {
                    "device_type": "tasmota",
                    "resolved_from": identifier,
                    "ip": ip_address,
                    "channel": channel,
                    "requested_state": state,
                    "actual_state": result_state,
                }
            )
        return _error_response_extended(code="HTTP_ERROR", message=f"HTTP {resp.status_code}")

    if device_type == "openbk":
        if state == "TOGGLE":
            resp = requests.get(f"http://{ip_address}/index?tgl={channel}", timeout=timeout_seconds)
        else:
            value = 1 if state == "ON" else 0
            resp = requests.get(
                f"http://{ip_address}/index?set={channel}&val={value}",
                timeout=timeout_seconds,
            )
        if resp.status_code == 200:
            return _success_response(
                {
                    "device_type": "openbk",
                    "resolved_from": identifier,
                    "ip": ip_address,
                    "channel": channel,
                    "requested_state": state,
                    "note": "Command sent successfully",
                }
            )
        return _error_response_extended(code="HTTP_ERROR", message=f"HTTP {resp.status_code}")

    if device_type == "tuya":
        from tools.iot_tuya import _tuya_set_value

        tuya_state = True if state == "ON" else False
        return _tuya_set_value(identifier, "1", tuya_state)

    if device_type == "openhasp":
        from tools.openhasp.telnet import OpenHASPTelnet

        tn = OpenHASPTelnet(ip_address)
        if tn.connect():
            tn.idle_off()
            tn.backlight_set("on" if state == "ON" else "off")
            tn.disconnect()
            return _success_response(
                {
                    "device_type": "openhasp",
                    "resolved_from": identifier,
                    "ip": ip_address,
                    "channel": channel,
                    "requested_state": state,
                    "note": "Backlight command sent via Telnet",
                }
            )
        return _error_response_extended(
            code="DEVICE_UNREACHABLE",
            message="Telnet connection failed",
        )

    return _error_response_extended(
        code="UNSUPPORTED_TYPE",
        message=f"Unsupported device type: {device_type}",
    )


def _set_brightness(
    identifier: str, brightness: int, channel: int = 1, timeout_seconds: int = 10
) -> str:
    """Set brightness of an IoT device channel (0-100).

    Args:
        identifier: IP address or device name.
        brightness: Brightness value (0-100).
        channel: Channel number (1-based, default 1).
        timeout_seconds: Request timeout in seconds.

    Returns:
        JSON string with result.
    """
    from tools.iot_discovery import _detect_device_type

    try:
        identifier = validate_required_string(identifier, "identifier")
        channel = validate_channel(channel)
        brightness = validate_brightness(brightness)
    except ValidationError as exc:
        return _error_response_extended(
            code="INVALID_PARAM",
            message=str(exc),
            suggestion="Use a non-empty identifier, channel >= 1, and brightness 0-100.",
        )

    ip_address = _resolve_or_fail(identifier)
    if not ip_address:
        return _build_unresolved_response(identifier)

    device_type = _detect_device_type(ip_address, timeout_seconds)
    if not device_type:
        return _error_response_extended(
            code="DEVICE_NOT_FOUND",
            message=f"No IoT device found at {ip_address}",
        )

    if device_type == "tasmota":
        resp = requests.get(
            f"http://{ip_address}/cm?cmnd=Channel{channel}%20{brightness}",
            timeout=timeout_seconds,
        )
        if resp.status_code == 200:
            return _success_response(
                {
                    "device_type": "tasmota",
                    "resolved_from": identifier,
                    "ip": ip_address,
                    "channel": channel,
                    "brightness": brightness,
                }
            )

    elif device_type == "openbk":
        resp = requests.get(
            f"http://{ip_address}/index?set={channel}&val={brightness}",
            timeout=timeout_seconds,
        )
        if resp.status_code == 200:
            return _success_response(
                {
                    "device_type": "openbk",
                    "resolved_from": identifier,
                    "ip": ip_address,
                    "channel": channel,
                    "brightness": brightness,
                }
            )

    if device_type == "tuya":
        from tools.iot_tuya import _find_tuya_in_cache, _tuya_set_value

        entry = _find_tuya_in_cache(identifier)
        power_dp = entry.get("power_dp_id", "1") if entry else "1"
        return _tuya_set_value(identifier, power_dp, brightness)

    if device_type == "openhasp":
        from tools.openhasp.telnet import OpenHASPTelnet

        # Map 0-100 to 0-255
        raw_brightness = int(brightness * 255 / 100)
        tn = OpenHASPTelnet(ip_address)
        if tn.connect():
            tn.idle_off()
            tn.backlight_set(raw_brightness)
            tn.disconnect()
            return _success_response(
                {
                    "device_type": "openhasp",
                    "resolved_from": identifier,
                    "ip": ip_address,
                    "channel": channel,
                    "brightness": brightness,
                    "raw_brightness": raw_brightness,
                    "note": "Backlight brightness set via Telnet",
                }
            )
        return _error_response_extended(
            code="DEVICE_UNREACHABLE",
            message="Telnet connection failed",
        )

    return _error_response_extended(
        code="UNSUPPORTED_TYPE",
        message=f"Unsupported device type: {device_type}",
    )


def _restart_device(identifier: str, timeout_seconds: int = 10) -> str:
    """Restart an IoT device.

    WARNING: This will temporarily disconnect the device!

    Args:
        identifier: IP address or device name.
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

    if device_type == "tasmota":
        resp = requests.get(f"http://{ip_address}/cm?cmnd=Restart%201", timeout=timeout_seconds)
        if resp.status_code == 200:
            return _success_response(
                {
                    "device_type": "tasmota",
                    "resolved_from": identifier,
                    "ip": ip_address,
                    "message": "Restart command sent",
                }
            )

    elif device_type == "openbk":
        resp = requests.get(f"http://{ip_address}/index?restart=1", timeout=timeout_seconds)
        if resp.status_code == 200:
            return _success_response(
                {
                    "device_type": "openbk",
                    "resolved_from": identifier,
                    "ip": ip_address,
                    "message": "Restart command sent",
                }
            )

    elif device_type == "tuya":
        return _error_response_extended(
            code="UNSUPPORTED_OPERATION",
            message="Tuya devices do not support a universal restart command",
            suggestion="Use iot_tuya_set_dp to control individual DPS values.",
        )

    elif device_type == "openhasp":
        from tools.openhasp.telnet import OpenHASPTelnet

        tn = OpenHASPTelnet(ip_address)
        if tn.connect():
            tn.restart()
            return _success_response(
                {
                    "device_type": "openhasp",
                    "resolved_from": identifier,
                    "ip": ip_address,
                    "message": "Restart command sent via Telnet",
                }
            )
        return _error_response_extended(
            code="DEVICE_UNREACHABLE",
            message="Telnet connection failed",
        )

    return _error_response_extended(code="DEVICE_NOT_FOUND", message="Device not found")


def _get_wifi_config(identifier: str, timeout_seconds: int = 10) -> str:
    """Get WiFi configuration from an IoT device.

    Args:
        identifier: IP address or device name.
        timeout_seconds: Request timeout in seconds.

    Returns:
        JSON string with WiFi configuration.
    """
    from tools.iot_devices import _get_openbk_status
    from tools.iot_discovery import _detect_device_type

    try:
        identifier = validate_required_string(identifier, "identifier")
    except ValidationError as exc:
        return _error_response_extended(code="INVALID_PARAM", message=str(exc))

    ip_address = _resolve_or_fail(identifier)
    if not ip_address:
        return _build_unresolved_response(identifier)

    device_type = _detect_device_type(ip_address, timeout_seconds)

    if device_type == "tasmota":
        resp = requests.get(f"http://{ip_address}/cm?cmnd=Status%205", timeout=timeout_seconds)
        if resp.status_code == 200:
            data = resp.json()
            wifi = data.get("StatusSTS", {}).get("Wifi", {})
            return _success_response(
                {
                    "device_type": "tasmota",
                    "resolved_from": identifier,
                    "ip": ip_address,
                    "wifi": {
                        "ssid": wifi.get("SSId"),
                        "rssi": wifi.get("RSSI"),
                        "signal": wifi.get("Signal"),
                        "mac": wifi.get("Mac"),
                        "ip": wifi.get("IPAddress"),
                        "gateway": wifi.get("Gateway"),
                        "mode": wifi.get("Mode"),
                    },
                }
            )

    elif device_type == "openbk":
        info = _get_openbk_status(ip_address, timeout_seconds)
        return _success_response(
            {
                "device_type": "openbk",
                "resolved_from": identifier,
                "ip": ip_address,
                "wifi": {
                    "ssid": info.get("ssid"),
                    "rssi": info.get("rssi"),
                    "signal": info.get("signal"),
                    "mac": info.get("mac"),
                    "ip": info.get("ip"),
                    "gateway": info.get("gateway"),
                    "hostname": info.get("hostname"),
                    "dns": info.get("dns"),
                },
            }
        )

    elif device_type == "tuya":
        return _error_response_extended(
            code="NOT_AVAILABLE",
            message="Tuya devices do not expose WiFi configuration via local API",
            suggestion="Check WiFi info via Tuya cloud or use the Tuya/Smart Life app.",
        )

    elif device_type == "openhasp":
        from tools.openhasp.http_client import OpenHASPHTTPClient

        client = OpenHASPHTTPClient(ip_address, timeout=5)
        config = client.get_json("/config.json")
        if config:
            wifi = config.get("wifi", {})
            return _success_response(
                {
                    "device_type": "openhasp",
                    "resolved_from": identifier,
                    "ip": ip_address,
                    "wifi": {
                        "ssid": wifi.get("ssid", ""),
                        "rssi": None,
                        "mac": None,
                    },
                }
            )
        return _error_response_extended(
            code="DEVICE_UNREACHABLE",
            message="Failed to fetch config from OpenHASP panel",
        )

    return _error_response_extended(code="DEVICE_NOT_FOUND", message="Device not found")


def register_iot_control_tools(mcp: Any) -> None:
    """Register IoT device control tools with the MCP server."""

    @mcp.tool()
    @inject_tool_risk_prefix
    def iot_set_power(
        identifier: str, state: str, channel: int = 1, timeout_seconds: int = 10
    ) -> str:
        """Set power state of an IoT device channel.

        Accepts either an IP address or a device name from the discovery cache.

        Args:
            identifier: IP address or device name.
            state: Power state - "ON", "OFF", or "TOGGLE".
            channel: Channel number (1-based, default 1).
            timeout_seconds: Request timeout in seconds (default 10).

        Returns:
            JSON with result.

        @since v1.2.0
        """
        try:
            start_tool_context()
            check_write_enabled()
            increment_tool_count("iot_set_power")
            return _set_power(identifier, state, channel, timeout_seconds)
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
    def iot_set_brightness(
        identifier: str, brightness: int, channel: int = 1, timeout_seconds: int = 10
    ) -> str:
        """Set brightness of an IoT device channel (0-100).

        Accepts either an IP address or a device name from the discovery cache.

        Args:
            identifier: IP address or device name.
            brightness: Brightness value (0-100).
            channel: Channel number (1-based, default 1).
            timeout_seconds: Request timeout in seconds (default 10).

        Returns:
            JSON with result.

        @since v1.2.0
        """
        try:
            start_tool_context()
            check_write_enabled()
            increment_tool_count("iot_set_brightness")
            return _set_brightness(identifier, brightness, channel, timeout_seconds)
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
    def iot_restart_device(identifier: str, timeout_seconds: int = 10) -> str:
        """Restart an IoT device.

        WARNING: This will temporarily disconnect the device!

        Accepts either an IP address or a device name from the discovery cache.

        Args:
            identifier: IP address or device name.
            timeout_seconds: Request timeout in seconds (default 10).

        Returns:
            JSON with result.

        @since v1.2.0
        """
        try:
            start_tool_context()
            check_write_enabled()
            increment_tool_count("iot_restart_device")
            return _restart_device(identifier, timeout_seconds)
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
    def iot_get_wifi_config(identifier: str, timeout_seconds: int = 10) -> str:
        """Get WiFi configuration from an IoT device.

        Accepts either an IP address or a device name from the discovery cache.

        Args:
            identifier: IP address or device name.
            timeout_seconds: Request timeout in seconds (default 10).

        Returns:
            JSON with WiFi configuration.

        @since v1.2.0
        """
        try:
            start_tool_context()
            increment_tool_count("iot_get_wifi_config")
            return _get_wifi_config(identifier, timeout_seconds)
        except Exception as exc:
            return _error_response_extended(code="INTERNAL_ERROR", message=str(exc))
