# mypy: disable-error-code="untyped-decorator"
"""
OpenHASP MCP Tools

Discovery, diagnostics, control, and file management for OpenHASP panels.
Uses raw TCP for Telnet (NOT telnetlib) and HTTP for config/files.
"""

import time
from typing import Any

from tools.constants import (
    OPENHASP_DEFAULT_HOST,
    OPENHASP_HTTP_PORT,
    OPENHASP_TIMEOUT,
    _error_response_extended,
    _success_response,
    check_write_enabled,
    increment_tool_count,
    inject_tool_risk_prefix,
    start_tool_context,
)
from tools.validators import (
    ValidationError,
    validate_http_url,
    validate_json_object,
    validate_openhasp_telnet_command,
)

__all__ = [
    "_openhasp_backlight_set",
    "_openhasp_check_backlight",
    "_openhasp_detect",
    "_openhasp_download_file",
    "_openhasp_get_config",
    "_openhasp_get_pages",
    "_openhasp_health",
    "_openhasp_send_command",
    "_openhasp_status",
    "_openhasp_upload_file",
    "register_openhasp_tools",
]

DEFAULT_HOST = OPENHASP_DEFAULT_HOST
DEFAULT_PORT = OPENHASP_HTTP_PORT
DEFAULT_TIMEOUT = OPENHASP_TIMEOUT

CONFIG_FILES = [
    "config.json",
    "pages.jsonl",
    "boot.cmd",
    "online.cmd",
    "offline.cmd",
]


def _get_http_client(host: str) -> Any:
    """Get configured OpenHASP HTTP client."""
    from tools.openhasp.http_client import OpenHASPHTTPClient

    return OpenHASPHTTPClient(host, port=DEFAULT_PORT, timeout=DEFAULT_TIMEOUT)


def _get_telnet_client(host: str) -> Any | None:
    """Get configured OpenHASP Telnet client (raw TCP)."""
    from tools.openhasp.telnet import OpenHASPTelnet

    tn = OpenHASPTelnet(host)
    if tn.connect():
        return tn
    return None


# =============================================================================
# INTERNAL FUNCTIONS
# =============================================================================


def _openhasp_detect(ip: str) -> str:
    """Check if an IP is an OpenHASP panel.

    Args:
        ip: IP address to probe.

    Returns:
        JSON with detection result.
    """
    client = _get_http_client(ip)
    config = client.get_json("/config.json")
    if config and "hasp" in config:
        name = config.get("mqtt", {}).get(
            "name", config.get("hasp", {}).get("startpage", "OpenHASP")
        )
        return _success_response(
            {
                "is_openhasp": True,
                "ip": ip,
                "name": name,
                "gui": {
                    "bckl": config.get("gui", {}).get("bckl", 0),
                    "bcklinv": config.get("gui", {}).get("bcklinv", 0),
                    "idle1": config.get("gui", {}).get("idle1", 0),
                    "idle2": config.get("gui", {}).get("idle2", 0),
                },
                "mqtt_host": config.get("mqtt", {}).get("host", ""),
                "wifi_ssid": config.get("wifi", {}).get("ssid", ""),
            }
        )
    return _error_response_extended(
        code="NOT_OPENHASP",
        message=f"No OpenHASP panel detected at {ip}",
    )


def _openhasp_status(ip: str) -> str:
    """Get full OpenHASP status - HTTP config + Telnet statusupdate."""
    client = _get_http_client(ip)
    config = client.get_json("/config.json")
    if not config or "hasp" not in config:
        return _error_response_extended(code="NOT_OPENHASP", message=f"No OpenHASP panel at {ip}")

    telnet_status: dict[str, Any] = {}
    tn = _get_telnet_client(ip)
    if tn:
        try:
            telnet_status = tn.statusupdate()
            if not telnet_status or (
                isinstance(telnet_status, dict) and not telnet_status.get("version")
            ):
                telnet_status = {}
        finally:
            tn.disconnect()

    version = telnet_status.get("version") or config.get("hasp", {}).get("version", "unknown")
    tft = telnet_status.get("tftDriver") or "unknown"
    mqtt_connected = isinstance(telnet_status, dict) and "tftDriver" in telnet_status

    objects_count = client.count_objects()
    pages_count = client.count_pages()

    return _success_response(
        {
            "ip": ip,
            "name": config.get("mqtt", {}).get("name", "OpenHASP"),
            "version": version,
            "tft_driver": tft,
            "objects_count": objects_count,
            "pages_count": pages_count,
            "heap_free": telnet_status.get("heapFree", 0),
            "uptime": telnet_status.get("uptime", 0),
            "rssi": telnet_status.get("rssi", 0),
            "mac": telnet_status.get("mac", ""),
            "bckl": config.get("gui", {}).get("bckl", 0),
            "bcklinv": config.get("gui", {}).get("bcklinv", 0),
            "idle1": config.get("gui", {}).get("idle1", 0),
            "idle2": config.get("gui", {}).get("idle2", 0),
            "mqtt_host": config.get("mqtt", {}).get("host", ""),
            "mqtt_connected": mqtt_connected,
            "wifi_ssid": config.get("wifi", {}).get("ssid", ""),
            "theme": config.get("hasp", {}).get("theme", ""),
        }
    )


def _openhasp_check_backlight(ip: str) -> str:
    """Check backlight configuration for common issues.

    Args:
        ip: Panel IP address.

    Returns:
        JSON with issues and fix commands.
    """
    from tools.openhasp.diagnostics import analyze_backlight

    client = _get_http_client(ip)
    config = client.get_json("/config.json")
    if not config:
        return _error_response_extended(
            code="NOT_OPENHASP",
            message=f"No OpenHASP panel at {ip}",
        )

    issues = analyze_backlight(config)
    gui = config.get("gui", {})
    recommendations: list[str] = []

    has_disabled = any("DISABLED" in i for i in issues)
    has_dim = any("TOO DIM" in i for i in issues)
    has_inverted = any("INVERTED" in i for i in issues)
    has_idle = any("IDLE" in i for i in issues)

    if has_disabled or has_dim:
        recommendations.append("backlight on")
        recommendations.append("backlight 255")
    if has_inverted:
        recommendations.append('config/gui {"bcklinv":0} + saveconfig + restart')
    if has_idle:
        recommendations.append('config/gui {"idle1":20} + saveconfig')

    return _success_response(
        {
            "ip": ip,
            "backlight": {"bckl": gui.get("bckl", 0), "bcklinv": gui.get("bcklinv", 0)},
            "idle": {"idle1": gui.get("idle1", 0), "idle2": gui.get("idle2", 0)},
            "issues_count": len(issues),
            "issues": issues,
            "recommendations": recommendations,
            "status": "ok" if not issues else "issues_found",
        }
    )


def _openhasp_get_config(ip: str) -> str:
    """Get full config.json from OpenHASP panel.

    Args:
        ip: Panel IP address.

    Returns:
        JSON with parsed config.
    """
    client = _get_http_client(ip)
    config = client.get_json("/config.json")
    if not config:
        return _error_response_extended(
            code="NOT_OPENHASP",
            message=f"Could not fetch config from {ip}",
        )
    return _success_response({"ip": ip, "config": config})


def _openhasp_get_pages(ip: str) -> str:
    """Get pages.jsonl from OpenHASP panel.

    Args:
        ip: Panel IP address.

    Returns:
        JSON with pages.jsonl content, object/page counts.
    """
    client = _get_http_client(ip)
    text = client.get_text("/pages.jsonl")
    if text is None:
        return _error_response_extended(
            code="NOT_OPENHASP",
            message=f"Could not fetch pages.jsonl from {ip}",
        )
    raw_lines = [
        line.strip()
        for line in text.strip().split("\n")
        if line.strip() and not line.strip().startswith("//")
    ]
    objects_count = client.count_objects()
    pages_count = client.count_pages()
    return _success_response(
        {
            "ip": ip,
            "pages_jsonl": raw_lines,
            "objects_count": objects_count,
            "pages_count": pages_count,
            "total_lines": len(text.strip().split("\n")),
        }
    )


def _openhasp_download_file(ip: str, filename: str) -> str:
    """Download a file from the OpenHASP panel.

    Args:
        ip: Panel IP address.
        filename: File to download (e.g. "config.json", "boot.cmd").

    Returns:
        JSON with file content.
    """
    if filename not in CONFIG_FILES:
        return _error_response_extended(
            code="INVALID_PARAM",
            message=f"Unknown file: {filename}. Available: {CONFIG_FILES}",
        )
    client = _get_http_client(ip)
    content = client.get_text(f"/{filename}")
    if content is None:
        return _error_response_extended(
            code="HTTP_ERROR",
            message=f"Failed to download {filename} from {ip}",
        )
    return _success_response(
        {
            "ip": ip,
            "filename": filename,
            "content": content,
            "size": len(content),
        }
    )


def _openhasp_upload_file(ip: str, filename: str, content: str) -> str:
    """Upload a file to the OpenHASP panel via POST /edit.

    Args:
        ip: Panel IP address.
        filename: Target filename on the panel.
        content: File content as string.

    Returns:
        JSON with result.
    """
    client = _get_http_client(ip)
    ok = client.upload_file(filename, content)
    if ok:
        return _success_response(
            {
                "ip": ip,
                "filename": filename,
                "uploaded": True,
                "size": len(content),
            }
        )
    return _error_response_extended(
        code="UPLOAD_FAILED",
        message=f"Failed to upload {filename} to {ip}",
    )


def _openhasp_send_command(ip: str, command: str, wait: float = 1.5) -> str:
    """Send a raw Telnet command to an OpenHASP panel.

    Uses raw TCP socket, NOT telnetlib.

    Args:
        ip: Panel IP address.
        command: Telnet command (e.g. "backlight", "page 1", "restart").
        wait: Seconds to wait for response.

    Returns:
        JSON with raw response and parsed result.
    """
    tn = _get_telnet_client(ip)
    if not tn:
        return _error_response_extended(
            code="TELNET_FAILED",
            message=f"Could not connect to Telnet on {ip}:23",
        )
    try:
        raw = tn.send_command(command, wait=wait)
        parsed = tn.parse_response(raw)
        return _success_response(
            {
                "ip": ip,
                "command": command,
                "raw_response": raw.strip()[:500],
                "parsed": parsed,
            }
        )
    finally:
        tn.disconnect()


def _openhasp_backlight_set(ip: str, state: str = "on", brightness: int = 255) -> str:
    """Set OpenHASP backlight state and brightness.

    Sends idle off first to prevent Screensaver override.

    Args:
        ip: Panel IP address.
        state: "on" or "off".
        brightness: Brightness 0-255 (only used when state="on").

    Returns:
        JSON with result.
    """
    tn = _get_telnet_client(ip)
    if not tn:
        return _error_response_extended(
            code="TELNET_FAILED",
            message=f"Could not connect to Telnet on {ip}:23",
        )
    try:
        tn.idle_off()
        time.sleep(0.3)
        raw = tn.backlight_set(state if state == "off" else str(brightness))
        return _success_response(
            {
                "ip": ip,
                "state": state,
                "brightness": brightness,
                "response": raw.strip()[:200],
            }
        )
    finally:
        tn.disconnect()


def _openhasp_health(ip: str) -> str:
    """Calculate health score for an OpenHASP panel.

    Checks tftDriver, bckl, MQTT, heap, objects.

    Args:
        ip: Panel IP address.

    Returns:
        JSON with score, level, and issues.
    """
    from tools.openhasp.diagnostics import health_score

    client = _get_http_client(ip)
    config = client.get_json("/config.json")
    if not config or "hasp" not in config:
        return _error_response_extended(
            code="NOT_OPENHASP",
            message=f"No OpenHASP panel at {ip}",
        )

    telnet_status: dict[str, Any] = {}
    mqtt_connected = False
    tn = _get_telnet_client(ip)
    if tn:
        try:
            telnet_status = tn.statusupdate()
            if not telnet_status or (
                isinstance(telnet_status, dict) and not telnet_status.get("version")
            ):
                telnet_status = {}
            mqtt_connected = isinstance(telnet_status, dict) and "tftDriver" in telnet_status
        finally:
            tn.disconnect()

    objects_count = client.count_objects()
    bckl_val = config.get("gui", {}).get("bckl", 0)
    score, level, issues = health_score(telnet_status, objects_count, mqtt_connected, bckl=bckl_val)

    return _success_response(
        {
            "ip": ip,
            "name": config.get("mqtt", {}).get("name", "OpenHASP"),
            "health_score": score,
            "health_level": level,
            "issues": issues,
            "details": {
                "tft_driver": telnet_status.get("tftDriver", "unknown"),
                "bckl": bckl_val,
                "mqtt_connected": mqtt_connected,
                "heap_free": telnet_status.get("heapFree", 0),
                "objects_count": objects_count,
                "version": telnet_status.get("version", "unknown"),
            },
        }
    )


# =============================================================================
# TOOL REGISTRATION
# =============================================================================


def register_openhasp_tools(mcp: Any) -> None:
    """Register OpenHASP tools with the MCP server."""

    @mcp.tool()
    @inject_tool_risk_prefix
    def openhasp_detect(ip_address: str) -> str:
        """Check if an IP address is an OpenHASP panel.

        Probes GET /config.json and looks for the \"hasp\" key.

        Args:
            ip_address: IP address to probe.

        Returns:
            JSON with detection result, name, and basic stats.

        @since v1.4.0
        """
        try:
            start_tool_context()
            increment_tool_count("openhasp_detect")
            return _openhasp_detect(ip_address)
        except Exception as exc:
            return _error_response_extended(code="INTERNAL_ERROR", message=str(exc))

    @mcp.tool()
    @inject_tool_risk_prefix
    def openhasp_status(identifier: str) -> str:
        """Get full status of an OpenHASP panel.

        Combines HTTP config.json with Telnet statusupdate for version,
        tftDriver, heap, uptime, RSSI, and MAC.

        Args:
            identifier: IP address of the panel.

        Returns:
            JSON with full device status.

        @since v1.4.0
        """
        try:
            start_tool_context()
            increment_tool_count("openhasp_status")
            return _openhasp_status(identifier)
        except Exception as exc:
            return _error_response_extended(code="INTERNAL_ERROR", message=str(exc))

    @mcp.tool()
    @inject_tool_risk_prefix
    def openhasp_check_backlight(identifier: str) -> str:
        """Check OpenHASP backlight for common issues.

        Detects: bckl=0 (disabled), bcklinv=1 (inverted), idle1<10 (too short).

        Args:
            identifier: IP address of the panel.

        Returns:
            JSON with issues, recommendations, and Telnet fix commands.

        @since v1.4.0
        """
        try:
            start_tool_context()
            increment_tool_count("openhasp_check_backlight")
            return _openhasp_check_backlight(identifier)
        except Exception as exc:
            return _error_response_extended(code="INTERNAL_ERROR", message=str(exc))

    @mcp.tool()
    @inject_tool_risk_prefix
    def openhasp_get_config(identifier: str) -> str:
        """Get the full config.json from an OpenHASP panel.

        Args:
            identifier: IP address of the panel.

        Returns:
            JSON with the complete configuration.

        @since v1.4.0
        """
        try:
            start_tool_context()
            increment_tool_count("openhasp_get_config")
            return _openhasp_get_config(identifier)
        except Exception as exc:
            return _error_response_extended(code="INTERNAL_ERROR", message=str(exc))

    @mcp.tool()
    @inject_tool_risk_prefix
    def openhasp_get_pages(identifier: str) -> str:
        """Get pages.jsonl from an OpenHASP panel.

        Returns the complete UI definition with object and page counts.

        Args:
            identifier: IP address of the panel.

        Returns:
            JSON with pages.jsonl content and object/page counts.

        @since v1.4.0
        """
        try:
            start_tool_context()
            increment_tool_count("openhasp_get_pages")
            return _openhasp_get_pages(identifier)
        except Exception as exc:
            return _error_response_extended(code="INTERNAL_ERROR", message=str(exc))

    @mcp.tool()
    @inject_tool_risk_prefix
    def openhasp_screenshot(identifier: str) -> str:
        """Capture a screenshot from an OpenHASP panel.

        Sends Telnet "screenshot" command then downloads /screenshot.bmp.
        Note: screenshot is a BMP - large file, may timeout.

        Args:
            identifier: IP address of the panel.

        Returns:
            JSON with base64-encoded screenshot data.

        @since v1.4.0
        """
        try:
            start_tool_context()
            increment_tool_count("openhasp_screenshot")
            tn = _get_telnet_client(identifier)
            if not tn:
                return _error_response_extended(
                    code="TELNET_FAILED",
                    message=f"Could not connect to Telnet on {identifier}:23",
                )
            tn.send_command("screenshot", wait=2.0)
            tn.disconnect()
            time.sleep(1)

            import base64

            try:
                import requests

                resp = requests.get(
                    f"http://{identifier}/screenshot.bmp",
                    timeout=15,
                )
                if resp.status_code == 200:
                    b64 = base64.b64encode(resp.content).decode("ascii")
                    return _success_response(
                        {
                            "ip": identifier,
                            "format": "bmp",
                            "size_bytes": len(resp.content),
                            "data_base64": b64[:500] + "...(truncated)",
                        }
                    )
            except Exception:
                pass
            return _error_response_extended(
                code="SCREENSHOT_FAILED",
                message="Screenshot capture failed",
            )
        except Exception as exc:
            return _error_response_extended(code="INTERNAL_ERROR", message=str(exc))

    @mcp.tool()
    @inject_tool_risk_prefix
    def openhasp_download_file(identifier: str, filename: str) -> str:
        """Download a file from an OpenHASP panel.

        Available files: config.json, pages.jsonl, boot.cmd, online.cmd, offline.cmd.

        Args:
            identifier: IP address of the panel.
            filename: File to download.

        Returns:
            JSON with file content.

        @since v1.4.0
        """
        try:
            start_tool_context()
            increment_tool_count("openhasp_download_file")
            return _openhasp_download_file(identifier, filename)
        except Exception as exc:
            return _error_response_extended(code="INTERNAL_ERROR", message=str(exc))

    @mcp.tool()
    @inject_tool_risk_prefix
    def openhasp_upload_file(identifier: str, filename: str, content: str) -> str:
        """Upload a file to an OpenHASP panel via POST /edit.

        Note: config.json uploads are OVERWRITTEN by firmware on boot.
        Use openhasp_config_set for runtime changes.

        Args:
            identifier: IP address of the panel.
            filename: Target filename on the panel.
            content: File content as a string.

        Returns:
            JSON with upload result.

        @since v1.4.0
        """
        try:
            start_tool_context()
            check_write_enabled()
            increment_tool_count("openhasp_upload_file")
            return _openhasp_upload_file(identifier, filename, content)
        except ValidationError as exc:
            return _error_response_extended(
                code="WRITE_DISABLED",
                message=str(exc),
                suggestion="Ask the server operator to set ENABLE_WRITE_OPERATIONS=1.",
            )
        except Exception as exc:
            return _error_response_extended(code="INTERNAL_ERROR", message=str(exc))

    @mcp.tool()
    @inject_tool_risk_prefix
    def openhasp_ota_update(identifier: str, firmware_url: str) -> str:
        """Update OpenHASP firmware via OTA URL.

        Sends Telnet "update <url>" command. Panel will reboot on success.

        Args:
            identifier: IP address of the panel.
            firmware_url: URL to .bin firmware file.

        Returns:
            JSON with result.

        @since v1.4.0
        """
        try:
            start_tool_context()
            check_write_enabled()
            increment_tool_count("openhasp_ota_update")
            try:
                firmware_url = validate_http_url(firmware_url, "firmware_url")
            except ValidationError as exc:
                return _error_response_extended(code="INVALID_PARAM", message=str(exc))
            tn = _get_telnet_client(identifier)
            if not tn:
                return _error_response_extended(
                    code="TELNET_FAILED",
                    message=f"Could not connect to Telnet on {identifier}:23",
                )
            raw = tn.send_command(f"update {firmware_url}", wait=3.0)
            tn.disconnect()
            return _success_response(
                {
                    "ip": identifier,
                    "firmware_url": firmware_url,
                    "response": raw.strip()[:200],
                    "note": "Panel will reboot if update succeeds",
                }
            )
        except ValidationError as exc:
            return _error_response_extended(
                code="WRITE_DISABLED",
                message=str(exc),
                suggestion="Ask the server operator to set ENABLE_WRITE_OPERATIONS=1.",
            )
        except Exception as exc:
            return _error_response_extended(code="INTERNAL_ERROR", message=str(exc))

    @mcp.tool()
    @inject_tool_risk_prefix
    def openhasp_page_set(identifier: str, page: int) -> str:
        """Navigate to a specific page on an OpenHASP panel.

        Args:
            identifier: IP address of the panel.
            page: Page number (1-12).

        Returns:
            JSON with result.

        @since v1.4.0
        """
        try:
            start_tool_context()
            check_write_enabled()
            increment_tool_count("openhasp_page_set")
            result = _openhasp_send_command(identifier, f"page {page}")
            return result
        except ValidationError as exc:
            return _error_response_extended(
                code="WRITE_DISABLED",
                message=str(exc),
                suggestion="Ask the server operator to set ENABLE_WRITE_OPERATIONS=1.",
            )
        except Exception as exc:
            return _error_response_extended(code="INTERNAL_ERROR", message=str(exc))

    @mcp.tool()
    @inject_tool_risk_prefix
    def openhasp_jsonl_send(identifier: str, jsonl: str) -> str:
        """Create or modify UI objects on an OpenHASP panel via Telnet.

        Sends Telnet "jsonl {...}" command. Use for remote UI changes.

        Args:
            identifier: IP address of the panel.
            jsonl: JSONL string with object definition.

        Returns:
            JSON with result.

        @since v1.4.0
        """
        try:
            start_tool_context()
            check_write_enabled()
            increment_tool_count("openhasp_jsonl_send")
            try:
                jsonl = validate_json_object(jsonl, "jsonl")
            except ValidationError as exc:
                return _error_response_extended(code="INVALID_PARAM", message=str(exc))
            result = _openhasp_send_command(identifier, f"jsonl {jsonl}")
            return result
        except ValidationError as exc:
            return _error_response_extended(
                code="WRITE_DISABLED",
                message=str(exc),
                suggestion="Ask the server operator to set ENABLE_WRITE_OPERATIONS=1.",
            )
        except Exception as exc:
            return _error_response_extended(code="INTERNAL_ERROR", message=str(exc))

    @mcp.tool()
    @inject_tool_risk_prefix
    def openhasp_telnet(identifier: str, command: str) -> str:
        """Send a raw Telnet command to an OpenHASP panel.

        Uses raw TCP socket (NOT telnetlib). See docs for command reference.

        Args:
            identifier: IP address of the panel.
            command: Telnet command (e.g. "backlight", "statusupdate", "page 1").

        Returns:
            JSON with raw response and parsed result.

        @since v1.4.0
        """
        try:
            start_tool_context()
            check_write_enabled()
            increment_tool_count("openhasp_telnet")
            try:
                command = validate_openhasp_telnet_command(command)
            except ValidationError as exc:
                return _error_response_extended(code="INVALID_PARAM", message=str(exc))
            return _openhasp_send_command(identifier, command)
        except ValidationError as exc:
            return _error_response_extended(
                code="WRITE_DISABLED",
                message=str(exc),
                suggestion="Ask the server operator to set ENABLE_WRITE_OPERATIONS=1.",
            )
        except Exception as exc:
            return _error_response_extended(code="INTERNAL_ERROR", message=str(exc))

    @mcp.tool()
    @inject_tool_risk_prefix
    def openhasp_backlight_set(identifier: str, state: str = "on", brightness: int = 255) -> str:
        """Set OpenHASP backlight state and brightness.

        Sends idle off first to prevent Screensaver override.
        Must consider bcklinv - some boards invert the PWM signal.

        Args:
            identifier: IP address of the panel.
            state: "on" or "off".
            brightness: Brightness 0-255 (when state="on").

        Returns:
            JSON with result.

        @since v1.4.0
        """
        try:
            start_tool_context()
            check_write_enabled()
            increment_tool_count("openhasp_backlight_set")
            return _openhasp_backlight_set(identifier, state, brightness)
        except ValidationError as exc:
            return _error_response_extended(
                code="WRITE_DISABLED",
                message=str(exc),
                suggestion="Ask the server operator to set ENABLE_WRITE_OPERATIONS=1.",
            )
        except Exception as exc:
            return _error_response_extended(code="INTERNAL_ERROR", message=str(exc))

    @mcp.tool()
    @inject_tool_risk_prefix
    def openhasp_config_set(identifier: str, config_json: str) -> str:
        """Set runtime GUI configuration on an OpenHASP panel.

        Sends Telnet config/gui {"KEY":VAL} then saveconfig.
        Only mutable keys work: bcklinv, idle1, idle2, rotate, cursor, invert.
        bckl is READ-ONLY at runtime!

        Args:
            identifier: IP address of the panel.
            config_json: JSON string with key-value pairs (e.g. '{"idle1":20}').

        Returns:
            JSON with result.

        @since v1.4.0
        """
        try:
            start_tool_context()
            check_write_enabled()
            increment_tool_count("openhasp_config_set")
            try:
                config_json = validate_json_object(config_json, "config_json")
            except ValidationError as exc:
                return _error_response_extended(code="INVALID_PARAM", message=str(exc))
            tn = _get_telnet_client(identifier)
            if not tn:
                return _error_response_extended(
                    code="TELNET_FAILED",
                    message=f"Could not connect to Telnet on {identifier}:23",
                )
            try:
                tn.send_command(f"config/gui {config_json}", wait=1.5)
                tn.send_command("saveconfig", wait=1.0)
                return _success_response(
                    {
                        "ip": identifier,
                        "config_set": config_json,
                        "saved": True,
                    }
                )
            finally:
                tn.disconnect()
        except ValidationError as exc:
            return _error_response_extended(
                code="WRITE_DISABLED",
                message=str(exc),
                suggestion="Ask the server operator to set ENABLE_WRITE_OPERATIONS=1.",
            )
        except Exception as exc:
            return _error_response_extended(code="INTERNAL_ERROR", message=str(exc))

    @mcp.tool()
    @inject_tool_risk_prefix
    def openhasp_idle_reset(identifier: str) -> str:
        """Reset OpenHASP idle timer.

        Sends Telnet "idle off". Critical before backlight tests - prevents
        Screensaver from dimming the screen.

        Args:
            identifier: IP address of the panel.

        Returns:
            JSON with result.

        @since v1.4.0
        """
        try:
            start_tool_context()
            check_write_enabled()
            increment_tool_count("openhasp_idle_reset")
            result = _openhasp_send_command(identifier, "idle off")
            return result
        except ValidationError as exc:
            return _error_response_extended(
                code="WRITE_DISABLED",
                message=str(exc),
                suggestion="Ask the server operator to set ENABLE_WRITE_OPERATIONS=1.",
            )
        except Exception as exc:
            return _error_response_extended(code="INTERNAL_ERROR", message=str(exc))

    @mcp.tool()
    @inject_tool_risk_prefix
    def openhasp_restart(identifier: str) -> str:
        """Restart an OpenHASP panel.

        Sends Telnet "restart" command. Panel will reboot.

        Args:
            identifier: IP address of the panel.

        Returns:
            JSON with result.

        @since v1.4.0
        """
        try:
            start_tool_context()
            check_write_enabled()
            increment_tool_count("openhasp_restart")
            tn = _get_telnet_client(identifier)
            if not tn:
                return _error_response_extended(
                    code="TELNET_FAILED",
                    message=f"Could not connect to Telnet on {identifier}:23",
                )
            tn.restart()
            return _success_response(
                {
                    "ip": identifier,
                    "restarted": True,
                    "note": "Panel is rebooting. Wait 10-15 seconds before reconnecting.",
                }
            )
        except ValidationError as exc:
            return _error_response_extended(
                code="WRITE_DISABLED",
                message=str(exc),
                suggestion="Ask the server operator to set ENABLE_WRITE_OPERATIONS=1.",
            )
        except Exception as exc:
            return _error_response_extended(code="INTERNAL_ERROR", message=str(exc))

    @mcp.tool()
    @inject_tool_risk_prefix
    def openhasp_factory_reset(identifier: str) -> str:
        """Factory reset an OpenHASP panel.

        WARNING: Sends Telnet "factoryreset". Clears EEPROM only - WiFi settings
        and pages.jsonl survive. Does NOT wipe files.

        Args:
            identifier: IP address of the panel.

        Returns:
            JSON with result.

        @since v1.4.0
        """
        try:
            start_tool_context()
            check_write_enabled()
            increment_tool_count("openhasp_factory_reset")
            tn = _get_telnet_client(identifier)
            if not tn:
                return _error_response_extended(
                    code="TELNET_FAILED",
                    message=f"Could not connect to Telnet on {identifier}:23",
                )
            tn.send_command("factoryreset", wait=1.0)
            tn.disconnect()
            return _success_response(
                {
                    "ip": identifier,
                    "reset": True,
                    "note": "EEPROM cleared. WiFi and files survive. Panel will reboot.",
                }
            )
        except ValidationError as exc:
            return _error_response_extended(
                code="WRITE_DISABLED",
                message=str(exc),
                suggestion="Ask the server operator to set ENABLE_WRITE_OPERATIONS=1.",
            )
        except Exception as exc:
            return _error_response_extended(code="INTERNAL_ERROR", message=str(exc))

    @mcp.tool()
    @inject_tool_risk_prefix
    def openhasp_validate_config(identifier: str) -> str:
        """Validate OpenHASP configuration.

        Checks: bckl, idle timings, object count, required sections.

        Args:
            identifier: IP address of the panel.

        Returns:
            JSON with validation result and warnings.

        @since v1.4.0
        """
        try:
            start_tool_context()
            increment_tool_count("openhasp_validate_config")
            from tools.openhasp.diagnostics import validate_config

            client = _get_http_client(identifier)
            config = client.get_json("/config.json")
            if not config or "hasp" not in config:
                return _error_response_extended(
                    code="NOT_OPENHASP",
                    message=f"No OpenHASP panel at {identifier}",
                )
            objects_count = client.count_objects()
            is_valid, warnings = validate_config(config, objects_count)
            return _success_response(
                {
                    "ip": identifier,
                    "valid": is_valid,
                    "warnings": warnings,
                    "objects_count": objects_count,
                }
            )
        except Exception as exc:
            return _error_response_extended(code="INTERNAL_ERROR", message=str(exc))

    @mcp.tool()
    @inject_tool_risk_prefix
    def openhasp_health(identifier: str) -> str:
        """Calculate health score for an OpenHASP panel.

        Score 0-100 based on: tftDriver (40pts), bckl (30pts), MQTT (20pts),
        heap (5pts), objects (5pts). Returns healthy/degraded/critical.

        Args:
            identifier: IP address of the panel.

        Returns:
            JSON with health score, level, issues, and details.

        @since v1.4.0
        """
        try:
            start_tool_context()
            increment_tool_count("openhasp_health")
            return _openhasp_health(identifier)
        except Exception as exc:
            return _error_response_extended(code="INTERNAL_ERROR", message=str(exc))

    @mcp.tool()
    @inject_tool_risk_prefix
    def openhasp_hardware_test(identifier: str) -> str:
        """Run an automated hardware diagnostic sequence on an OpenHASP panel.

        Sequence: idle off -> backlight on/255 -> antiburn on (30s color cycle)
        -> screenshot -> backlight query -> statusupdate.

        Args:
            identifier: IP address of the panel.

        Returns:
            JSON with test results: screenshot, backlight state, tftDriver, health.

        @since v1.4.0
        """
        try:
            start_tool_context()
            check_write_enabled()
            increment_tool_count("openhasp_hardware_test")

            tn = _get_telnet_client(identifier)
            if not tn:
                return _error_response_extended(
                    code="TELNET_FAILED",
                    message=f"Could not connect to Telnet on {identifier}:23",
                )
            try:
                tn.idle_off()
                time.sleep(0.3)
                tn.backlight_set(255)
                time.sleep(0.5)
                tn.send_command("antiburn on", wait=1.0)
                time.sleep(0.5)
                tn.send_command("screenshot", wait=2.0)
                time.sleep(0.5)
                backlight_state = tn.backlight_query()
                status = tn.statusupdate()
            finally:
                tn.disconnect()

            return _success_response(
                {
                    "ip": identifier,
                    "backlight_state": backlight_state,
                    "tft_driver": status.get("tftDriver") if isinstance(status, dict) else None,
                    "version": status.get("version") if isinstance(status, dict) else None,
                    "heap_free": status.get("heapFree") if isinstance(status, dict) else None,
                    "note": ("Hardware test completed. Antiburn cycles colors for 30s then stops."),
                }
            )
        except ValidationError as exc:
            return _error_response_extended(
                code="WRITE_DISABLED",
                message=str(exc),
                suggestion="Ask the server operator to set ENABLE_WRITE_OPERATIONS=1.",
            )
        except Exception as exc:
            return _error_response_extended(code="INTERNAL_ERROR", message=str(exc))
