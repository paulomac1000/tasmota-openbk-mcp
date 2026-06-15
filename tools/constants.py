import collections
import json
import logging
import os
import re
import sys
import threading
import time
import uuid
from typing import Any

from tools.validators import ValidationError

# =============================================================================
# ENVIRONMENT CONFIGURATION
# =============================================================================

MQTT_BROKER = os.getenv("MQTT_BROKER", "192.168.1.100")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_USER = os.getenv("MQTT_USER", "")
MQTT_PASSWORD = os.getenv("MQTT_PASSWORD", "")
START_IP = os.getenv("START_IP", "192.168.1.1")
END_IP = os.getenv("END_IP", "192.168.1.254")
NETWORK_RANGE = os.getenv("NETWORK_RANGE")
MCP_SSE_PORT = int(os.getenv("MCP_SSE_PORT", "9101"))
REST_API_PORT = int(os.getenv("REST_API_PORT", "9102"))

# Streamable HTTP transport
MCP_TRANSPORT = os.getenv("MCP_TRANSPORT", "both")  # streamable-http, sse, both
MCP_ALLOWED_ORIGINS = os.getenv("MCP_ALLOWED_ORIGINS", "http://localhost:*")

HEALTH_CHECK_PORT = int(os.getenv("HEALTH_CHECK_PORT", "9100"))
OPENHASP_DEFAULT_HOST = os.getenv("OPENHASP_DEFAULT_HOST", "192.168.1.100")
OPENHASP_HTTP_PORT = int(os.getenv("OPENHASP_HTTP_PORT", "80"))
OPENHASP_TELNET_PORT = int(os.getenv("OPENHASP_TELNET_PORT", "23"))
OPENHASP_TIMEOUT = int(os.getenv("OPENHASP_TIMEOUT", "10"))
OPENHASP_TELNET_TIMEOUT = int(os.getenv("OPENHASP_TELNET_TIMEOUT", "5"))
HIKVISION_DOORBELL_HOST = os.getenv("HIKVISION_DOORBELL_HOST", "192.168.1.101")
HIKVISION_DOORBELL_USER = os.getenv("HIKVISION_DOORBELL_USER", "")
HIKVISION_DOORBELL_PASSWORD = os.getenv("HIKVISION_DOORBELL_PASSWORD", "")
HIKVISION_CONTAINER_NAME = os.getenv("HIKVISION_CONTAINER_NAME", "hikvision-doorbell")
DOCKER_SOCKET = os.getenv("DOCKER_SOCKET", "/var/run/docker.sock")
DOCKER_TOOL_NAMES: list[str] = [
    "hikvision_container_status",
    "hikvision_container_logs",
    "hikvision_check_vmd",
    "hikvision_restart_container",
    "hikvision_isapi_health",
    "hikvision_pipeline_diagnose",
]
CAMERA_GATE_SNAPSHOTS_DIR = os.getenv(
    "CAMERA_GATE_SNAPSHOTS_DIR",
    "/config/www/archive/camera_gate",
)
TUYA_ACCESS_ID = os.getenv("TUYA_ACCESS_ID", "")
TUYA_ACCESS_SECRET = os.getenv("TUYA_ACCESS_SECRET", "")
TUYA_PROJECT_CODE = os.getenv("TUYA_PROJECT_CODE", "")
TUYA_DEVICES_FILE = os.getenv("TUYA_DEVICES_FILE", "data/tuya_devices.json")

BIND_HOST = os.getenv("BIND_HOST", "127.0.0.1")
ALLOW_PUBLIC_BIND = os.getenv("MCP_UNSAFE_PUBLIC_ACCESS_CONFIRMED", "0") == "1"

# Server-level write guard. Write and destructive tools are rejected before any
# I/O unless this flag is explicitly enabled. This is a server-level authorization
# gate decided by the operator - distinct from the per-tool `requires_confirmation`
# manifest field, which is an agent-level user-consent hint.
ENABLE_WRITE_OPERATIONS = os.getenv("ENABLE_WRITE_OPERATIONS", "0") == "1"

# Build default network range for discovery (CIDR notation)
_DEFAULT_OCTETS = START_IP.rsplit(".", 1)[0]
DEFAULT_NETWORK_RANGE = NETWORK_RANGE or f"{_DEFAULT_OCTETS}.0/24"

TOOLS_VERSION = "1.6.0"

DEFAULT_HA_DISCOVERY_PREFIX = "homeassistant"

# =============================================================================
# TOOL INVOCATION COUNTERS
# =============================================================================

_tool_invocation_counts: dict[str, int] = collections.defaultdict(int)
_counter_lock = threading.Lock()


def increment_tool_count(tool_name: str) -> None:
    """Increment invocation counter for a tool.

    Args:
        tool_name: Name of the registered tool.
    """
    with _counter_lock:
        _tool_invocation_counts[tool_name] += 1


def get_tool_counts() -> dict[str, int]:
    """Return invocation counts for all tools.

    Returns:
        Dict mapping tool names to invocation counts.
    """
    with _counter_lock:
        return dict(_tool_invocation_counts)


def record_invocation(tool_name: str) -> None:
    """Record a tool invocation for health endpoint metrics.

    Args:
        tool_name: Name of the tool being invoked.
    """
    increment_tool_count(tool_name)


# =============================================================================
# LOGGING AND SANITIZATION
# =============================================================================

_LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
_LOGGER_INITIALIZED = False

# Credential patterns are redacted everywhere - in log output AND in the response
# payload returned to the agent.
_CREDENTIAL_PATTERNS = [
    (r"Bearer\s+[A-Za-z0-9\-._~+/]+=*", "Bearer <REDACTED>"),
    (r"Authorization:\s*[^\s]+", "Authorization: <REDACTED>"),
    (r"password[=:]\s*[^\s&]+", "password=<REDACTED>"),
]

_SENSITIVE_RESPONSE_FIELDS = {
    "access_key",
    "access_secret",
    "api_key",
    "apikey",
    "authorization",
    "bearer",
    "local_key",
    "password",
    "secret",
    "token",
}

# IP redaction applies to LOG output only. Device IP addresses are functional
# payload for an IoT discovery server - an agent needs them to address devices in
# follow-up calls - so they are intentionally NOT redacted from response payloads.
_LOG_PATTERNS = _CREDENTIAL_PATTERNS + [
    (r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b", "<IP_REDACTED>"),
]


def sanitize_log_line(line: str) -> str:
    """Remove sensitive data (credentials, IP addresses) from a log line.

    Args:
        line: Raw log line that may contain credentials or tokens.

    Returns:
        Sanitized line with sensitive patterns replaced by REDACTED markers.
    """
    for pattern, replacement in _LOG_PATTERNS:
        line = re.sub(pattern, replacement, line, flags=re.IGNORECASE)
    return line


def _sanitize_secrets(text: str) -> str:
    """Redact credential patterns from a string (no IP redaction)."""
    for pattern, replacement in _CREDENTIAL_PATTERNS:
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
    return text


def sanitize_response_data(data: Any) -> Any:
    """Recursively redact credentials from a response payload before returning it.

    Applied at the `_success_response()` boundary so a tool that forgets to
    sanitize cannot leak a token or password to the agent. Device IP addresses
    are preserved - they are functional data, not secrets.

    Args:
        data: Arbitrary response payload (str, dict, list, or scalar).

    Returns:
        The payload with credential patterns redacted.
    """
    if isinstance(data, str):
        return _sanitize_secrets(data)
    if isinstance(data, dict):
        sanitized = {}
        for k, v in data.items():
            normalized_key = str(k).lower().replace("-", "_")
            is_sensitive_key = (
                normalized_key in _SENSITIVE_RESPONSE_FIELDS
                or normalized_key.endswith("_key")
                or normalized_key.endswith("_password")
                or normalized_key.endswith("_secret")
                or normalized_key.endswith("_token")
            )
            sanitized[k] = "<REDACTED>" if is_sensitive_key else sanitize_response_data(v)
        return sanitized
    if isinstance(data, list):
        return [sanitize_response_data(item) for item in data]
    return data


_request_id_context = threading.local()


class RequestIdFilter(logging.Filter):
    """Logging filter that injects request_id from thread-local context."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = getattr(_request_id_context, "value", "-")
        return True


def set_request_id(request_id: str) -> None:
    """Set request_id for the current thread's log context.

    Args:
        request_id: UUID string identifying the current tool invocation.
    """
    _request_id_context.value = request_id


def get_request_id() -> str:
    """Get request_id for the current thread, or '-' if not set.

    Returns:
        UUID string or '-'.
    """
    return getattr(_request_id_context, "value", "-")


def start_tool_context() -> str:
    """Initialize request_id for a tool invocation.

    Should be called at the start of every tool wrapper before any
    I/O or logging. Returns the generated UUID.

    Returns:
        UUID string for the current invocation.
    """
    rid = str(uuid.uuid4())
    set_request_id(rid)
    return rid


def setup_logging() -> None:
    """Initialize logging once at startup.

    All log output targets stderr to avoid corrupting MCP stdio transport.
    """
    global _LOGGER_INITIALIZED
    if _LOGGER_INITIALIZED:
        return
    logger = logging.getLogger("iot_mcp")
    logger.setLevel(getattr(logging, _LOG_LEVEL, logging.INFO))
    handler = logging.StreamHandler(sys.stderr)

    class SanitizingFormatter(logging.Formatter):
        def format(self, record: logging.LogRecord) -> str:
            return sanitize_log_line(super().format(record))

    handler.setFormatter(
        SanitizingFormatter(
            "%(asctime)s [%(levelname)s] [%(request_id)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    handler.addFilter(RequestIdFilter())
    logger.addHandler(handler)
    logger.propagate = False
    _LOGGER_INITIALIZED = True


def get_logger(name: str) -> logging.Logger:
    """Get a named logger under the iot_mcp hierarchy.

    Args:
        name: Component name (e.g. "server", "discovery").

    Returns:
        Configured logger instance.
    """
    return logging.getLogger(f"iot_mcp.{name}")


# =============================================================================
# WRITE GUARD
# =============================================================================


def check_write_enabled() -> None:
    """Raise ValidationError when server-level write operations are disabled.

    MUST be called at the start of every write/destructive tool wrapper, before
    any I/O. See ENABLE_WRITE_OPERATIONS.

    Raises:
        ValidationError: If ENABLE_WRITE_OPERATIONS is not enabled.
    """
    if not ENABLE_WRITE_OPERATIONS:
        raise ValidationError(
            "Write operations are disabled. Set ENABLE_WRITE_OPERATIONS=1 on the server to enable."
        )


# =============================================================================
# RESPONSE HELPERS
# =============================================================================


def _build_meta(
    duration_ms: int | None = None,
    cached: bool | None = None,
    retry_safe: bool | None = None,
    **extra: Any,
) -> dict[str, Any]:
    """Build _meta envelope for responses.

    The request_id is read from the current tool context (set by
    start_tool_context) so that it matches the id written to log lines for the
    same invocation. It is NOT regenerated here.

    Args:
        duration_ms: Optional elapsed time in milliseconds.
        cached: Optional whether the response came from cache.
        retry_safe: Optional whether the operation can be safely retried.
        extra: Additional metadata fields to include.

    Returns:
        Dictionary with request_id, tool_version and extra fields.
    """
    meta: dict[str, Any] = {
        "request_id": get_request_id(),
        "tool_version": TOOLS_VERSION,
    }
    if duration_ms is not None:
        meta["duration_ms"] = duration_ms
    if cached is not None:
        meta["cached"] = cached
    if retry_safe is not None:
        meta["retry_safe"] = retry_safe
    meta.update(extra)
    return meta


def build_meta(tool_name: str, start_time: float | None = None, **extra: Any) -> dict[str, Any]:
    """Build _meta envelope and record the invocation.

    Wraps _build_meta() and adds invocation recording as a side effect.
    The request_id is read from the current tool context so it matches
    log lines for the same invocation.

    Args:
        tool_name: Tool name for invocation counting.
        start_time: Optional time.monotonic() timestamp for duration_ms.
        extra: Additional metadata fields.

    Returns:
        Dictionary with request_id, tool_version and extra fields.
    """
    record_invocation(tool_name)
    duration_ms = None
    if start_time is not None:
        duration_ms = int((time.monotonic() - start_time) * 1000)
    return _build_meta(duration_ms=duration_ms, **extra)


def _success_response(
    data: Any,
    duration_ms: int | None = None,
    cached: bool | None = None,
    retry_safe: bool | None = None,
    **meta_extra: Any,
) -> str:
    """Build consistent success response as JSON string.

    The payload is run through sanitize_response_data() at this boundary so no
    tool can leak credentials to the agent.

    Args:
        data: Data payload to include in the response.
        duration_ms: Optional elapsed time in milliseconds.
        cached: Optional whether the response came from cache.
        retry_safe: Optional whether the operation can be safely retried.
        meta_extra: Additional _meta fields.

    Returns:
        JSON string with success response and _meta envelope.
    """
    return json.dumps(
        {
            "success": True,
            "data": sanitize_response_data(data),
            "_meta": _build_meta(
                duration_ms=duration_ms, cached=cached, retry_safe=retry_safe, **meta_extra
            ),
        }
    )


def _error_response(
    error: str,
    duration_ms: int | None = None,
    cached: bool | None = None,
    retry_safe: bool | None = None,
    **meta_extra: Any,
) -> str:
    """Build consistent error response as JSON string.

    Args:
        error: Error message string.
        duration_ms: Optional elapsed time in milliseconds.
        cached: Optional whether the response came from cache.
        retry_safe: Optional whether the operation can be safely retried.
        meta_extra: Additional _meta fields.

    Returns:
        JSON string with error response and _meta envelope.
    """
    return json.dumps(
        {
            "success": False,
            "error": error,
            "_meta": _build_meta(
                duration_ms=duration_ms, cached=cached, retry_safe=retry_safe, **meta_extra
            ),
        }
    )


def _error_response_extended(
    code: str,
    message: str,
    retryable: bool = False,
    suggestion: str | None = None,
    available_names: list[str] | None = None,
    duration_ms: int | None = None,
    cached: bool | None = None,
    retry_safe: bool | None = None,
    **meta_extra: Any,
) -> str:
    """Build structured error response with machine-readable fields.

    Args:
        code: Machine-readable error code (UPPER_SNAKE_CASE).
        message: Human-readable error description.
        retryable: Whether the operation can be retried safely.
        suggestion: Actionable next step for the user.
        available_names: List of valid alternatives when relevant.
        duration_ms: Optional elapsed time in milliseconds.
        cached: Optional whether the response came from cache.
        retry_safe: Optional whether the operation can be safely retried.
        meta_extra: Additional _meta fields.

    Returns:
        JSON string with structured error response and _meta envelope.
    """
    err: dict[str, Any] = {"code": code, "message": message, "retryable": retryable}
    if suggestion:
        err["suggestion"] = suggestion
    if available_names:
        err["available_names"] = available_names[:50]
    return json.dumps(
        {
            "success": False,
            "error": err,
            "_meta": _build_meta(
                duration_ms=duration_ms, cached=cached, retry_safe=retry_safe, **meta_extra
            ),
        }
    )


def _error_dict_extended(
    code: str,
    message: str,
    retryable: bool = False,
    suggestion: str | None = None,
    available_names: list[str] | None = None,
) -> dict[str, Any]:
    """Return an error dict for internal function composition (before JSON serialization).

    Unlike _error_response_extended which returns a JSON string, this variant
    returns a dict suitable for composing with other dicts before serialization.

    Args:
        code: Machine-readable error code (UPPER_SNAKE_CASE).
        message: Human-readable error description.
        retryable: Whether the operation can be safely retried.
        suggestion: Actionable next step for the user.
        available_names: List of valid alternatives when relevant.

    Returns:
        Dict with success=False and error details.
    """
    error: dict[str, Any] = {"code": code, "message": message, "retryable": retryable}
    if suggestion:
        error["suggestion"] = suggestion
    if available_names:
        error["available_names"] = available_names[:50]
    return {"success": False, "error": error}


# =============================================================================
# TOOL MANIFEST FACTORIES
# =============================================================================
#
# Picking the factory IS the criticality decision. There is no fourth ad-hoc
# path. Each factory's output satisfies the Risk Consistency Matrix from
# mcp-server-standards.md; tests/unit/test_constants.py asserts this.


def _make_manifest(
    name: str,
    *,
    timeout_ms: int = 10000,
    latency: str = "moderate",
    cost: str = "moderate",
    determinism: str = "env-dependent",
    side_effects: str = "read",
    concurrent_safe: bool = True,
    privacy: str = "none",
) -> dict[str, Any]:
    """Build a READ-tool manifest. READ tools are idempotent, retryable, reversible.

    Args:
        name: Registered tool name.
        timeout_ms: Expected maximum execution time in milliseconds.
        latency: Latency class (instant/fast/moderate/slow/long-running).
        cost: Cost class (cheap/moderate/expensive).
        determinism: Determinism class.
        side_effects: "none" for pure tools, "read" for tools that read backends.
        concurrent_safe: Whether concurrent invocations are safe.
        privacy: "none", "metadata", or "personal".

    Returns:
        A manifest dict for a READ tool.
    """
    return {
        "name": name,
        "version": TOOLS_VERSION,
        "risk": "READ",
        "side_effects": side_effects,
        "idempotent": True,
        "retryable": True,
        "concurrent_safe": concurrent_safe,
        "timeout_ms": timeout_ms,
        "requires_confirmation": False,
        "determinism": determinism,
        "latency": latency,
        "cost": cost,
        "impact": "none",
        "privacy": privacy,
        "reversible": True,
    }


def _make_write_manifest(
    name: str,
    *,
    timeout_ms: int = 10000,
    latency: str = "moderate",
    cost: str = "moderate",
    determinism: str = "env-dependent",
    impact: str = "transient",
) -> dict[str, Any]:
    """Build a WRITE-tool manifest. WRITE tools are reversible and retryable.

    Use only for operations designed as reversible/idempotent (set a value,
    publish a message). Irreversible operations MUST use
    _make_destructive_manifest() instead.

    Args:
        name: Registered tool name.
        timeout_ms: Expected maximum execution time in milliseconds.
        latency: Latency class.
        cost: Cost class.
        determinism: Determinism class.
        impact: "transient" or "persistent".

    Returns:
        A manifest dict for a WRITE tool.
    """
    return {
        "name": name,
        "version": TOOLS_VERSION,
        "risk": "WRITE",
        "side_effects": "write",
        "idempotent": True,
        "retryable": True,
        "concurrent_safe": False,
        "timeout_ms": timeout_ms,
        "requires_confirmation": True,
        "determinism": determinism,
        "latency": latency,
        "cost": cost,
        "impact": impact,
        "privacy": "none",
        "reversible": True,
    }


def _make_destructive_manifest(
    name: str,
    *,
    timeout_ms: int = 30000,
    latency: str = "slow",
    cost: str = "expensive",
    determinism: str = "env-dependent",
    impact: str = "service_outage",
) -> dict[str, Any]:
    """Build a DESTRUCTIVE-tool manifest for irreversible operations.

    Use for reboot, factory reset, delete - operations whose effect cannot be
    undone at the application level. The manifest advertises
    retryable=false / reversible=false so the agent never re-issues them blindly.

    Args:
        name: Registered tool name.
        timeout_ms: Expected maximum execution time in milliseconds.
        latency: Latency class.
        cost: Cost class.
        determinism: Determinism class.
        impact: "persistent" or "service_outage".

    Returns:
        A manifest dict for a DESTRUCTIVE tool.
    """
    return {
        "name": name,
        "version": TOOLS_VERSION,
        "risk": "DESTRUCTIVE",
        "side_effects": "destructive",
        "idempotent": False,
        "retryable": False,
        "concurrent_safe": False,
        "timeout_ms": timeout_ms,
        "requires_confirmation": True,
        "determinism": determinism,
        "latency": latency,
        "cost": cost,
        "impact": impact,
        "privacy": "none",
        "reversible": False,
    }


# =============================================================================
# TOOL MANIFESTS
# =============================================================================

TOOL_MANIFESTS: dict[str, dict[str, Any]] = {
    "iot_discover_devices": _make_manifest(
        "iot_discover_devices",
        timeout_ms=120000,
        latency="slow",
        cost="expensive",
    ),
    "iot_list_devices": _make_manifest(
        "iot_list_devices",
        timeout_ms=1000,
        latency="instant",
        cost="cheap",
        determinism="eventually-consistent",
    ),
    "iot_execute_command": {
        **_make_destructive_manifest("iot_execute_command", timeout_ms=10000, latency="slow"),
        "description": "Execute raw /cm?cmnd command with blocked-command allowlist for safety",
    },
    "iot_check_device": _make_manifest("iot_check_device", timeout_ms=10000),
    "iot_configure_mqtt": {
        **_make_write_manifest("iot_configure_mqtt", timeout_ms=10000),
        "description": (
            "Configure MQTT broker connection settings "
            "(host, port, client, group) via /cfg_mqtt_set"
        ),
    },
    "iot_find_device_by_name": _make_manifest(
        "iot_find_device_by_name",
        timeout_ms=1000,
        latency="instant",
        cost="cheap",
        determinism="deterministic",
    ),
    "iot_get_full_info": {
        **_make_manifest(
            "iot_get_full_info", timeout_ms=10000, latency="moderate", privacy="metadata"
        ),
        "description": (
            "Get comprehensive device info (MAC, firmware version, flags, MQTT, WiFi) from Status 0"
        ),
    },
    "iot_get_device_info": _make_manifest(
        "iot_get_device_info",
        timeout_ms=10000,
        privacy="metadata",
    ),
    "iot_get_device_power": _make_manifest("iot_get_device_power", timeout_ms=10000),
    "iot_get_wifi_config": _make_manifest(
        "iot_get_wifi_config",
        timeout_ms=10000,
        privacy="metadata",
    ),
    "iot_set_power": _make_write_manifest("iot_set_power", timeout_ms=10000),
    "iot_set_startup_command": {
        **_make_write_manifest("iot_set_startup_command", timeout_ms=10000),
        "description": "Set device startup command / autoexec on OpenBK via /startup_command",
    },
    "iot_set_brightness": _make_write_manifest("iot_set_brightness", timeout_ms=10000),
    "iot_restart_device": _make_destructive_manifest(
        "iot_restart_device",
        timeout_ms=10000,
        latency="slow",
    ),
    "iot_set_flags": {
        **_make_write_manifest("iot_set_flags", timeout_ms=10000),
        "description": (
            "Set device configuration flags (64-bit bitfield) "
            "via /cfg_generic or /cm?cmnd=SetOption"
        ),
    },
    "iot_set_friendly_name": {
        **_make_write_manifest("iot_set_friendly_name", timeout_ms=10000),
        "description": "Set device friendly name (FriendlyName1) on Tasmota devices",
    },
    "iot_set_gpio": {
        **_make_write_manifest("iot_set_gpio", timeout_ms=10000),
        "description": "Configure GPIO pin role and channel on device via /cfg_pins",
    },
    "iot_set_name": {
        **_make_write_manifest("iot_set_name", timeout_ms=10000),
        "description": "Set device short and full name via /cfg_name",
    },
    "iot_mqtt_publish": _make_write_manifest("iot_mqtt_publish", timeout_ms=5000),
    "iot_mqtt_get_state": _make_manifest("iot_mqtt_get_state", timeout_ms=10000),
    "iot_mqtt_build_command_topic": _make_manifest(
        "iot_mqtt_build_command_topic",
        timeout_ms=100,
        latency="instant",
        cost="cheap",
        determinism="deterministic",
        side_effects="none",
    ),
    "iot_start_ha_discovery": {
        **_make_write_manifest("iot_start_ha_discovery", timeout_ms=10000),
        "description": "Trigger Home Assistant MQTT discovery on device via /ha_discovery",
    },
    "describe_iot_capabilities": _make_manifest(
        "describe_iot_capabilities",
        timeout_ms=100,
        latency="instant",
        cost="cheap",
        determinism="deterministic",
        side_effects="none",
    ),
    "iot_tuya_cloud_list": _make_manifest(
        "iot_tuya_cloud_list",
        timeout_ms=30000,
        latency="slow",
        cost="moderate",
        privacy="metadata",
    ),
    "iot_tuya_cloud_refresh_keys": _make_write_manifest(
        "iot_tuya_cloud_refresh_keys",
        timeout_ms=30000,
        latency="slow",
        impact="persistent",
    ),
    "iot_tuya_cloud_control": _make_write_manifest(
        "iot_tuya_cloud_control",
        timeout_ms=15000,
        latency="slow",
    ),
    "iot_tuya_get_dps": _make_manifest(
        "iot_tuya_get_dps",
        timeout_ms=10000,
        privacy="metadata",
    ),
    "iot_tuya_set_dp": _make_write_manifest(
        "iot_tuya_set_dp",
        timeout_ms=10000,
    ),
    "iot_tuya_detect_version": _make_manifest(
        "iot_tuya_detect_version",
        timeout_ms=30000,
        latency="slow",
        cost="expensive",
    ),
    "iot_tuya_verify_dps": _make_manifest(
        "iot_tuya_verify_dps",
        timeout_ms=15000,
        privacy="metadata",
    ),
    "iot_tuya_scan_ports": _make_manifest(
        "iot_tuya_scan_ports",
        timeout_ms=30000,
        latency="slow",
        cost="moderate",
    ),
    "iot_tuya_remove": _make_write_manifest(
        "iot_tuya_remove",
        timeout_ms=2000,
        latency="fast",
        impact="persistent",
    ),
    "iot_tuya_monitor": _make_manifest(
        "iot_tuya_monitor",
        timeout_ms=120000,
        latency="slow",
        cost="expensive",
        privacy="metadata",
    ),
    "openhasp_detect": _make_manifest(
        "openhasp_detect", timeout_ms=5000, latency="fast", cost="cheap"
    ),
    "openhasp_status": _make_manifest("openhasp_status", timeout_ms=15000, privacy="metadata"),
    "openhasp_check_backlight": _make_manifest(
        "openhasp_check_backlight", timeout_ms=5000, privacy="metadata"
    ),
    "openhasp_get_config": _make_manifest(
        "openhasp_get_config", timeout_ms=5000, privacy="metadata"
    ),
    "openhasp_get_pages": _make_manifest("openhasp_get_pages", timeout_ms=5000, privacy="personal"),
    "openhasp_screenshot": _make_manifest(
        "openhasp_screenshot", timeout_ms=30000, latency="slow", cost="expensive"
    ),
    "openhasp_download_file": _make_manifest("openhasp_download_file", timeout_ms=10000),
    "openhasp_upload_file": _make_write_manifest(
        "openhasp_upload_file", timeout_ms=30000, latency="slow"
    ),
    "openhasp_ota_update": _make_destructive_manifest(
        "openhasp_ota_update", timeout_ms=60000, latency="slow"
    ),
    "openhasp_page_set": _make_write_manifest("openhasp_page_set", timeout_ms=5000, latency="fast"),
    "openhasp_jsonl_send": _make_write_manifest(
        "openhasp_jsonl_send", timeout_ms=5000, latency="fast"
    ),
    "openhasp_telnet": _make_write_manifest("openhasp_telnet", timeout_ms=10000),
    "openhasp_backlight_set": _make_write_manifest("openhasp_backlight_set", timeout_ms=10000),
    "openhasp_config_set": _make_write_manifest("openhasp_config_set", timeout_ms=10000),
    "openhasp_idle_reset": _make_write_manifest(
        "openhasp_idle_reset", timeout_ms=5000, latency="fast"
    ),
    "openhasp_restart": _make_destructive_manifest(
        "openhasp_restart", timeout_ms=15000, latency="slow"
    ),
    "openhasp_factory_reset": _make_destructive_manifest(
        "openhasp_factory_reset", timeout_ms=15000, latency="slow", impact="persistent"
    ),
    "openhasp_validate_config": _make_manifest("openhasp_validate_config", timeout_ms=10000),
    "openhasp_health": _make_manifest("openhasp_health", timeout_ms=15000, privacy="metadata"),
    "openhasp_hardware_test": _make_write_manifest(
        "openhasp_hardware_test", timeout_ms=45000, latency="slow", cost="expensive"
    ),
    "hikvision_container_status": _make_manifest(
        "hikvision_container_status",
        timeout_ms=10000,
        latency="fast",
        cost="cheap",
    ),
    "hikvision_container_logs": _make_manifest(
        "hikvision_container_logs",
        timeout_ms=15000,
        latency="fast",
        privacy="metadata",
    ),
    "hikvision_check_vmd": _make_manifest(
        "hikvision_check_vmd",
        timeout_ms=15000,
        latency="fast",
        cost="cheap",
        privacy="metadata",
    ),
    "hikvision_restart_container": _make_destructive_manifest(
        "hikvision_restart_container",
        timeout_ms=30000,
        latency="slow",
    ),
    "hikvision_take_snapshot": _make_manifest(
        "hikvision_take_snapshot",
        timeout_ms=15000,
        latency="moderate",
        cost="expensive",
        privacy="personal",
    ),
    "hikvision_open_gate": _make_write_manifest(
        "hikvision_open_gate",
        timeout_ms=15000,
        latency="moderate",
        impact="transient",
    ),
    "hikvision_device_info": _make_manifest(
        "hikvision_device_info",
        timeout_ms=10000,
        latency="fast",
        cost="cheap",
        privacy="metadata",
    ),
    "hikvision_get_motion_config": _make_manifest(
        "hikvision_get_motion_config",
        timeout_ms=10000,
        latency="moderate",
        cost="moderate",
        privacy="metadata",
    ),
    "hikvision_set_motion_detection": _make_write_manifest(
        "hikvision_set_motion_detection",
        timeout_ms=15000,
        latency="moderate",
        impact="transient",
    ),
    "hikvision_get_event_config": _make_manifest(
        "hikvision_get_event_config",
        timeout_ms=10000,
        latency="moderate",
        cost="moderate",
        privacy="metadata",
    ),
    "hikvision_get_alarm_server": _make_manifest(
        "hikvision_get_alarm_server",
        timeout_ms=10000,
        latency="fast",
        cost="cheap",
        privacy="metadata",
    ),
    "hikvision_snapshot_to_file": _make_write_manifest(
        "hikvision_snapshot_to_file",
        timeout_ms=15000,
        impact="persistent",
    ),
    "hikvision_isapi_health": _make_manifest(
        "hikvision_isapi_health",
        timeout_ms=10000,
        latency="fast",
        cost="cheap",
        privacy="none",
    ),
    "hikvision_pipeline_diagnose": _make_manifest(
        "hikvision_pipeline_diagnose",
        timeout_ms=15000,
        latency="slow",
        cost="expensive",
        privacy="metadata",
    ),
}


def get_tool_manifest(tool_name: str) -> dict[str, Any] | None:
    """Get the manifest for a specific tool.

    Args:
        tool_name: Name of the registered tool.

    Returns:
        Manifest dict or None if tool not found.
    """
    return TOOL_MANIFESTS.get(tool_name)


def inject_tool_risk_prefix(func: Any) -> Any:
    """Inject the risk prefix from TOOL_MANIFESTS into func.__doc__.

    The prefix (e.g. [READ], [WRITE], [DESTRUCTIVE]) is taken from the manifest
    so the manifest stays the single source of truth. It is prepended only if
    the docstring does not already start with '['.

    Args:
        func: The tool function being decorated.

    Returns:
        The same function with an updated __doc__.
    """
    manifest = TOOL_MANIFESTS.get(func.__name__)
    if manifest:
        doc = (func.__doc__ or "").strip()
        if doc and not doc.startswith("["):
            func.__doc__ = f"[{manifest['risk']}] {doc}"
    return func
