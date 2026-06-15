# mypy: disable-error-code="untyped-decorator"
"""
Hikvision Doorbell Tools

Debugging and control tools for Hikvision DS-KV6113-WPE1(C) video doorbell.
Integrates Docker CLI, ISAPI HTTP API, and MQTT health monitoring.
"""

import base64
import os
from typing import Any

from tools.constants import (
    CAMERA_GATE_SNAPSHOTS_DIR,
    _error_response_extended,
    _success_response,
    check_write_enabled,
    increment_tool_count,
    inject_tool_risk_prefix,
    start_tool_context,
)
from tools.hikvision.docker_client import (
    _docker_available,
    count_call_events,
    count_vmd_events,
    get_container_logs,
    get_container_status,
    restart_container,
)
from tools.hikvision.isapi_client import create_isapi_client
from tools.validators import ValidationError, validate_required_string

__all__ = [
    "register_hikvision_tools",
    "_hikvision_container_status",
    "_hikvision_container_logs",
    "_hikvision_check_vmd",
    "_hikvision_restart_container",
    "_hikvision_take_snapshot",
    "_hikvision_open_gate",
    "_hikvision_device_info",
    "_hikvision_get_motion_config",
    "_hikvision_set_motion_detection",
    "_hikvision_get_event_config",
    "_hikvision_get_alarm_server",
    "_hikvision_snapshot_to_file",
    "_hikvision_isapi_health",
    "_hikvision_pipeline_diagnose",
]


def _hikvision_container_status() -> str:
    """Get hikvision-doorbell Docker container running status and health."""
    status = get_container_status()
    return _success_response(status)


def _hikvision_container_logs(since: str = "1h", tail: int = 100) -> str:
    """Fetch logs from the hikvision-doorbell container."""
    logs = get_container_logs(since=since, tail=tail)
    return _success_response(
        {
            "since": since,
            "tail": tail,
            "log_size_chars": len(logs),
            "logs": logs,
        }
    )


def _hikvision_check_vmd(since: str = "4h") -> str:
    """Check if VMD events are flowing from the doorbell."""
    result = count_vmd_events(since=since)
    return _success_response(result)


def _hikvision_restart_container() -> str:
    """Restart the hikvision-doorbell Docker container."""
    result = restart_container()
    if result["success"]:
        return _success_response(result)
    return _error_response_extended(
        code="DOCKER_ERROR",
        message=result["message"],
    )


def _hikvision_take_snapshot() -> str:
    """Capture a JPEG snapshot from the doorbell camera via ISAPI HTTP."""
    try:
        client = create_isapi_client()
        img = client.get_snapshot(channel=1)
        if img:
            b64 = base64.b64encode(img).decode("ascii")
            return _success_response(
                {
                    "format": "jpeg",
                    "size_bytes": len(img),
                    "base64": b64,
                }
            )
        return _error_response_extended(
            code="ISAPI_ERROR",
            message="Failed to capture snapshot. Check ISAPI auth and camera.",
        )
    except ValueError as exc:
        return _error_response_extended(
            code="MISSING_CREDENTIALS",
            message=str(exc),
            suggestion="Set HIKVISION_DOORBELL_USER and HIKVISION_DOORBELL_PASSWORD",
        )
    except Exception as exc:
        return _error_response_extended(code="INTERNAL_ERROR", message=str(exc))


def _hikvision_open_gate(door_id: int = 1) -> str:
    """Trigger the electric lock relay to open the gate."""
    try:
        client = create_isapi_client()
        success = client.open_door(door_id=door_id)
        if success:
            return _success_response({"opened": True, "door_id": door_id})
        return _error_response_extended(
            code="ISAPI_ERROR",
            message=f"Failed to open door {door_id}",
        )
    except ValueError as exc:
        return _error_response_extended(code="MISSING_CREDENTIALS", message=str(exc))
    except Exception as exc:
        return _error_response_extended(code="INTERNAL_ERROR", message=str(exc))


def _hikvision_device_info() -> str:
    """Fetch Hikvision doorbell device information via ISAPI."""
    try:
        client = create_isapi_client()
        info = client.get_device_info()
        if info:
            return _success_response(info)
        return _error_response_extended(
            code="ISAPI_ERROR",
            message="Failed to fetch device info. Check credentials and connectivity.",
        )
    except ValueError as exc:
        return _error_response_extended(code="MISSING_CREDENTIALS", message=str(exc))
    except Exception as exc:
        return _error_response_extended(code="INTERNAL_ERROR", message=str(exc))


def _hikvision_get_motion_config() -> str:
    """Fetch VMD motion detection configuration from the doorbell."""
    try:
        client = create_isapi_client()
        config = client.get_motion_config()
        if config:
            return _success_response(config)
        return _error_response_extended(
            code="ISAPI_ERROR",
            message="Failed to fetch motion detection config.",
        )
    except ValueError as exc:
        return _error_response_extended(code="MISSING_CREDENTIALS", message=str(exc))
    except Exception as exc:
        return _error_response_extended(code="INTERNAL_ERROR", message=str(exc))


def _hikvision_set_motion_detection(
    enabled: bool | None = None, sensitivity: int | None = None
) -> str:
    """Enable/disable VMD motion detection or adjust sensitivity."""
    try:
        if sensitivity is not None and not 0 <= sensitivity <= 100:
            return _error_response_extended(
                code="VALIDATION_ERROR",
                message="sensitivity must be between 0 and 100",
            )
        client = create_isapi_client()
        success = client.set_motion_config(enabled=enabled, sensitivity=sensitivity)
        if success:
            return _success_response(
                {
                    "enabled": enabled,
                    "sensitivity": sensitivity,
                    "message": "Motion detection config updated",
                }
            )
        return _error_response_extended(
            code="ISAPI_ERROR",
            message="Failed to update motion detection config. Check ISAPI connectivity.",
        )
    except ValueError as exc:
        return _error_response_extended(code="MISSING_CREDENTIALS", message=str(exc))
    except Exception as exc:
        return _error_response_extended(code="INTERNAL_ERROR", message=str(exc))


def _hikvision_get_event_config() -> str:
    """Fetch event trigger configuration from the doorbell."""
    try:
        client = create_isapi_client()
        triggers = client.get_event_triggers()
        if triggers is not None:
            return _success_response({"triggers": triggers, "count": len(triggers)})
        return _error_response_extended(
            code="ISAPI_ERROR",
            message="Failed to fetch event triggers.",
        )
    except ValueError as exc:
        return _error_response_extended(code="MISSING_CREDENTIALS", message=str(exc))
    except Exception as exc:
        return _error_response_extended(code="INTERNAL_ERROR", message=str(exc))


def _hikvision_get_alarm_server() -> str:
    """Fetch alarm server (HTTP notification host) configuration."""
    try:
        client = create_isapi_client()
        server = client.get_alarm_server()
        if server:
            return _success_response({"alarm_server": server})
        return _error_response_extended(
            code="ISAPI_ERROR",
            message="Failed to fetch alarm server config.",
        )
    except ValueError as exc:
        return _error_response_extended(code="MISSING_CREDENTIALS", message=str(exc))
    except Exception as exc:
        return _error_response_extended(code="INTERNAL_ERROR", message=str(exc))


def _hikvision_snapshot_to_file(filepath: str) -> str:
    """Capture a JPEG snapshot and save it directly to a file on disk."""
    try:
        validated_path = validate_required_string(filepath, "filepath")
        client = create_isapi_client()
        result = client.save_snapshot(filepath=validated_path)
        if result.get("saved"):
            return _success_response(result)
        return _error_response_extended(
            code="ISAPI_ERROR",
            message=str(result.get("error", "Failed to save snapshot")),
        )
    except ValidationError as exc:
        return _error_response_extended(code="VALIDATION_ERROR", message=str(exc))
    except ValueError as exc:
        return _error_response_extended(code="MISSING_CREDENTIALS", message=str(exc))
    except Exception as exc:
        return _error_response_extended(code="INTERNAL_ERROR", message=str(exc))


def _hikvision_isapi_health(since: str = "4h") -> str:
    """Composite health check for the doorbell pipeline.

    Combines Docker container status, VMD events, and call events
    into a single health assessment. Does not call ISAPI directly --
    uses Docker client functions that inspect container logs.

    Args:
        since: Time window for event counting (default "4h").

    Returns:
        JSON with overall health status, container/vmd/calls details, and issues.
    """
    try:
        status = get_container_status()
        vmd = count_vmd_events(since=since)
        calls = count_call_events(since=since)
        container_ok = status.get("running", False)
        vmd_ok = vmd.get("vmd_count", 0) > 0
        calls_ok = calls.get("call_count", 0) > 0
        if container_ok and (vmd_ok or calls_ok):
            overall = "healthy"
        elif container_ok and not vmd_ok and not calls_ok:
            overall = "degraded"
        else:
            overall = "down"
        issues = []
        if not container_ok:
            issues.append(f"Container not running: {status.get('status', 'unknown')}")
        if not vmd_ok and calls_ok:
            issues.append("VMD event pipeline is dead (call events still flowing)")
        if not vmd_ok and not calls_ok:
            issues.append("No VMD or call events — ISAPI may be disconnected")
        return _success_response(
            {
                "overall": overall,
                "since": since,
                "container": status,
                "vmd": vmd,
                "calls": calls,
                "issues": issues,
            }
        )
    except ValueError as exc:
        return _error_response_extended(code="MISSING_CREDENTIALS", message=str(exc))
    except Exception as exc:
        return _error_response_extended(code="INTERNAL_ERROR", message=str(exc))


def _hikvision_pipeline_diagnose() -> str:
    """Cross-layer diagnostic across all 5 layers of the doorbell pipeline.

    Layers: Docker container -> ISAPI auth -> events (VMD/call) ->
    MQTT triggers -> snapshot files on disk.

    Returns:
        JSON with per-layer status, overall health, and issues list.
    """
    try:
        status = get_container_status()
        container_running = status.get("running", False)
        logs = get_container_logs(since="1h", tail=100)
        isapi_auth = "Connected to doorbell" in logs
        vmd_count = logs.count("Motion detected from Gate")
        call_count = logs.count("Doorbell ringing")
        mqtt_triggers = logs.count("Invoking device trigger automation")
        snapshots_dir = CAMERA_GATE_SNAPSHOTS_DIR
        snapshot_files: list[str] = []
        has_snapshots = False
        try:
            if os.path.isdir(snapshots_dir):
                snapshot_files = sorted(os.listdir(snapshots_dir), reverse=True)[:5]
                has_snapshots = len(snapshot_files) > 0
        except OSError:
            pass
        issues: list[str] = []
        if not container_running:
            issues.append("Cannot start — docker container is not running")
        if not isapi_auth:
            issues.append("Layer 1: ISAPI not authenticated")
        if vmd_count == 0 and call_count == 0:
            issues.append("Layer 2: No events of any kind")
        elif vmd_count == 0 and call_count > 0:
            issues.append("Layer 2: VMD events stopped (call events still flowing)")
        if mqtt_triggers == 0:
            issues.append("Layer 3: No MQTT automation triggers")
        if not has_snapshots:
            issues.append("Layer 4: No snapshots on disk")
        overall = "healthy" if len(issues) == 0 else "degraded"
        return _success_response(
            {
                "overall": overall,
                "layers": {
                    "container": {
                        "running": container_running,
                        "status": status.get("status", "unknown"),
                    },
                    "isapi": {"authenticated": isapi_auth},
                    "events": {"vmd_count": vmd_count, "call_count": call_count},
                    "mqtt": {"triggers_published": mqtt_triggers},
                    "snapshots": {
                        "has_snapshots": has_snapshots,
                        "recent_files": snapshot_files,
                        "directory": snapshots_dir,
                    },
                },
                "issues": issues,
            }
        )
    except ValueError as exc:
        return _error_response_extended(code="MISSING_CREDENTIALS", message=str(exc))
    except Exception as exc:
        return _error_response_extended(code="INTERNAL_ERROR", message=str(exc))


def register_hikvision_tools(mcp: Any) -> None:
    """Register Hikvision doorbell tools with the MCP server.

    ISAPI tools (direct device communication) always register.
    Docker-dependent tools require /var/run/docker.sock.
    """

    # Docker-dependent tools — only when Docker socket is available
    if _docker_available():

        @mcp.tool()
        @inject_tool_risk_prefix
        def hikvision_container_status() -> str:
            """Get hikvision-doorbell Docker container running status and health.

            Returns container state (running/stopped/error), health check status,
            and start time. First step in any doorbell debugging session.

            Returns:
                JSON with running (bool), status (str), started_at (str), health (str).

            @since v1.4.0
            """
            try:
                start_tool_context()
                increment_tool_count("hikvision_container_status")
                return _hikvision_container_status()
            except Exception as exc:
                return _error_response_extended(code="INTERNAL_ERROR", message=str(exc))

        @mcp.tool()
        @inject_tool_risk_prefix
        def hikvision_container_logs(since: str = "1h", tail: int = 100) -> str:
            """Fetch recent logs from the hikvision-doorbell Docker container.

            Key log patterns to look for:
            - "Motion detected from Gate" - VMD (Video Motion Detection) events
            - "Doorbell ringing" - someone pressed the call button
            - "Connected to doorbell: Gate type: VillaVTO" - ISAPI auth successful
            - "Call dismissed" - ring ended
            - "Door X unlocked" - gate relay triggered
            - "tampering_alarm" - physical tamper detected

            Args:
                since: Time window for logs (e.g. "1h", "4h", "24h"). Default "1h".
                tail: Maximum number of lines to return (default 100).

            Returns:
                JSON with since, tail, log_size_chars, and logs text.

            @since v1.4.0
            """
            try:
                start_tool_context()
                increment_tool_count("hikvision_container_logs")
                return _hikvision_container_logs(since, tail)
            except Exception as exc:
                return _error_response_extended(code="INTERNAL_ERROR", message=str(exc))

        @mcp.tool()
        @inject_tool_risk_prefix
        def hikvision_check_vmd(since: str = "4h") -> str:
            """Check if VMD (Video Motion Detection) events are flowing from the doorbell.

            Deprecated -- use hikvision_isapi_health for comprehensive health check
            (container + VMD + call events).

            The Hikvision doorbell built-in VMD generates "Motion detected from Gate"
            events on ANY motion including shadows, lighting changes, car headlights.
            These false positives are NORMAL and expected. They are the canary for ISAPI
            health: zero events for 4+ hours means the ISAPI connection from the
            hikvision-doorbell container to the physical doorbell is silently dead.

            The container will still show "running" - use hikvision_container_status()
            first to confirm, then this tool to diagnose the ISAPI layer.

            Args:
                since: Time window to check (default "4h"). Use "8h" overnight.

            Returns:
                JSON with vmd_count (int), isapi_healthy (bool), check_window (str).

            @since v1.4.0
            """
            try:
                start_tool_context()
                increment_tool_count("hikvision_check_vmd")
                return _hikvision_check_vmd(since)
            except Exception as exc:
                return _error_response_extended(code="INTERNAL_ERROR", message=str(exc))

        @mcp.tool()
        @inject_tool_risk_prefix
        def hikvision_restart_container() -> str:
            """Restart the hikvision-doorbell Docker container.

            WARNING: Write operation - drops the ISAPI connection to the doorbell
            and re-authenticates. The doorbell is unmonitored for ~10-15 seconds
            during restart. Use only when hikvision_check_vmd() confirms ISAPI is
            dead (isapi_healthy=false for 4+ hours).

            After restart, verify recovery with:
            1. hikvision_container_logs(since="30s") - look for "Connected to doorbell"
            2. hikvision_check_vmd(since="30s") - VMD should resume within seconds

            Returns:
                JSON with success (bool) and message (str).

            @since v1.4.0
            """
            try:
                start_tool_context()
                check_write_enabled()
                increment_tool_count("hikvision_restart_container")
                return _hikvision_restart_container()
            except ValidationError as exc:
                return _error_response_extended(
                    code="WRITE_DISABLED",
                    message=str(exc),
                    suggestion="Ask the server operator to set ENABLE_WRITE_OPERATIONS=1.",
                )
            except Exception as exc:
                return _error_response_extended(code="INTERNAL_ERROR", message=str(exc))

    # ISAPI tools — always registered (direct device communication)
    @mcp.tool()
    @inject_tool_risk_prefix
    def hikvision_take_snapshot() -> str:
        """Capture a JPEG snapshot from the doorbell camera via ISAPI HTTP.

        Uses HTTP Digest Auth (HIKVISION_DOORBELL_USER/PASSWORD from .env).
        Returns base64-encoded JPEG - the AI agent can display this directly
        to see what the doorbell camera is currently viewing.

        Use for: verifying camera works, checking who is at the gate,
        debugging motion detection (is the view obstructed? is it dark?),
        post-restart verification that the camera stream is alive.

        Returns:
            JSON with format ("jpeg"), size_bytes (int), and base64 (str).

        @since v1.4.0
        """
        try:
            start_tool_context()
            increment_tool_count("hikvision_take_snapshot")
            return _hikvision_take_snapshot()
        except Exception as exc:
            return _error_response_extended(code="INTERNAL_ERROR", message=str(exc))

    @mcp.tool()
    @inject_tool_risk_prefix
    def hikvision_open_gate(door_id: int = 1) -> str:
        """Trigger the electric lock relay to open the gate.

        WARNING: Write operation - physically opens the gate! Sends XML command
        to ISAPI AccessControl/RemoteControl endpoint with digest auth. The relay
        pulses for the duration configured in the doorbell (typically 5 seconds).

        Verify success with: hikvision_container_logs(since="30s") and look for
        "Door X unlocked" entries.

        Args:
            door_id: Door output number (1 = main gate relay). Default 1.

        Returns:
            JSON with opened (bool) and door_id (int).

        @since v1.4.0
        """
        try:
            start_tool_context()
            check_write_enabled()
            increment_tool_count("hikvision_open_gate")
            return _hikvision_open_gate(door_id)
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
    def hikvision_device_info() -> str:
        """Fetch Hikvision doorbell device metadata via ISAPI.

        Returns model, firmware version, serial number, MAC address, and other
        metadata from the doorbell /ISAPI/System/deviceInfo endpoint.

        Use for: verifying doorbell identity, checking firmware compatibility
        (ONVIF requires V2.2.65+), troubleshooting ISAPI auth issues.

        Returns:
            JSON with deviceInfo fields (deviceName, model, firmwareVersion,
            serialNumber, macAddress, etc.).

        @since v1.4.0
        """
        try:
            start_tool_context()
            increment_tool_count("hikvision_device_info")
            return _hikvision_device_info()
        except Exception as exc:
            return _error_response_extended(code="INTERNAL_ERROR", message=str(exc))

    @mcp.tool()
    @inject_tool_risk_prefix
    def hikvision_get_event_config() -> str:
        """Fetch event trigger configuration from the doorbell via ISAPI.

        Returns the list of event triggers (VMD, videoloss, etc.) configured
        on the doorbell along with their notification methods and schedules.

        Returns:
            JSON with triggers list and count.

        @since v1.4.0
        """
        try:
            start_tool_context()
            increment_tool_count("hikvision_get_event_config")
            return _hikvision_get_event_config()
        except Exception as exc:
            return _error_response_extended(code="INTERNAL_ERROR", message=str(exc))

    @mcp.tool()
    @inject_tool_risk_prefix
    def hikvision_get_alarm_server() -> str:
        """Fetch alarm server (HTTP notification host) configuration from the doorbell.

        Returns the HTTP host notification settings configured on the doorbell
        (IP address, port, URL path, protocol, and authentication method).

        Returns:
            JSON with alarm_server dict.

        @since v1.4.0
        """
        try:
            start_tool_context()
            increment_tool_count("hikvision_get_alarm_server")
            return _hikvision_get_alarm_server()
        except Exception as exc:
            return _error_response_extended(code="INTERNAL_ERROR", message=str(exc))

    @mcp.tool()
    @inject_tool_risk_prefix
    def hikvision_snapshot_to_file(filepath: str) -> str:
        """Capture a JPEG snapshot from the doorbell and save it to a file on disk.

        Writes the camera snapshot directly to the specified file path instead
        of returning base64 data. Useful for saving snapshots for later analysis.

        Args:
            filepath: Absolute path where the JPEG file should be saved.

        Returns:
            JSON with saved (bool), size_bytes (int), filepath (str), and format (str).

        @since v1.4.0
        """
        try:
            start_tool_context()
            check_write_enabled()
            increment_tool_count("hikvision_snapshot_to_file")
            return _hikvision_snapshot_to_file(filepath)
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
    def hikvision_get_motion_config() -> str:
        """Fetch VMD motion detection configuration from the doorbell.

        Returns the motion detection configuration including enabled status,
        sensitivity level, and grid settings from the doorbell ISAPI endpoint.

        Returns:
            JSON with motion config fields (enabled, sensitivity, grid_map,
            grid_rows, grid_cols).

        @since v1.5.0
        """
        try:
            start_tool_context()
            increment_tool_count("hikvision_get_motion_config")
            return _hikvision_get_motion_config()
        except Exception as exc:
            return _error_response_extended(code="INTERNAL_ERROR", message=str(exc))

    @mcp.tool()
    @inject_tool_risk_prefix
    def hikvision_set_motion_detection(
        enabled: bool | None = None, sensitivity: int | None = None
    ) -> str:
        """Enable or disable VMD motion detection, or adjust sensitivity.

        WARNING: Write operation -- modifies the doorbell's motion detection config.
        Sends XML PUT to ISAPI Smart/MotionDetection endpoint with digest auth.
        Uses read-modify-write: fetches current config, overrides the specified
        fields, and writes the complete XML back.

        Args:
            enabled: Enable (True) or disable (False) motion detection.
            sensitivity: Sensitivity level 0-100.

        Returns:
            JSON with enabled, sensitivity, and message fields.

        @since v1.5.0
        """
        try:
            start_tool_context()
            check_write_enabled()
            increment_tool_count("hikvision_set_motion_detection")
            return _hikvision_set_motion_detection(enabled, sensitivity)
        except ValidationError as exc:
            return _error_response_extended(
                code="WRITE_DISABLED",
                message=str(exc),
                suggestion="Ask the server operator to set ENABLE_WRITE_OPERATIONS=1.",
            )
        except Exception as exc:
            return _error_response_extended(code="INTERNAL_ERROR", message=str(exc))

    # Docker-dependent composite tools — only when Docker socket is available
    if _docker_available():

        @mcp.tool()
        @inject_tool_risk_prefix
        def hikvision_isapi_health(since: str = "4h") -> str:
            """Check doorbell pipeline health: container + VMD + call events.

            Composite health check that combines Docker container status,
            VMD motion events, and doorbell call events into a single
            health assessment (healthy/degraded/down).

            Args:
                since: Time window for event counting (default "4h"). Use "8h" overnight.

            Returns:
                JSON with overall health, container info, vmd/calls event counts,
                and any issues detected.

            @since v1.6.0
            """
            try:
                start_tool_context()
                increment_tool_count("hikvision_isapi_health")
                return _hikvision_isapi_health(since)
            except Exception as exc:
                return _error_response_extended(code="INTERNAL_ERROR", message=str(exc))

        @mcp.tool()
        @inject_tool_risk_prefix
        def hikvision_pipeline_diagnose() -> str:
            """Cross-layer diagnostic of the entire doorbell pipeline.

            Inspects 5 layers: Docker container, ISAPI auth, events (VMD/call),
            MQTT automation triggers, and snapshot files on disk. Returns per-layer
            status and a consolidated issues list.

            Returns:
                JSON with overall health, per-layer status dict, and issues list.

            @since v1.6.0
            """
            try:
                start_tool_context()
                increment_tool_count("hikvision_pipeline_diagnose")
                return _hikvision_pipeline_diagnose()
            except Exception as exc:
                return _error_response_extended(code="INTERNAL_ERROR", message=str(exc))
