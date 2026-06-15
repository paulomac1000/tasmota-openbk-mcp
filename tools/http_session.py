# mypy: disable-error-code="untyped-decorator"
"""
Generic IoT device HTTP client module with device-type dispatch.

Provides a shared HTTP session class and URL-building dispatch for
OpenBK, Tasmota, and other IoT device types. Used by all Wave 2
configuration tools (set_flags, set_name, configure_mqtt, etc.).
"""

import json
import urllib.parse
from typing import Any, NoReturn

import requests
from requests.adapters import HTTPAdapter

__all__ = [
    "DeviceConnectionError",
    "_DeviceHttpSession",
    "_build_url",
]


class DeviceConnectionError(Exception):
    """Raised when a device connection fails.

    This exception wraps all request-level failures (timeout,
    connection refused, HTTP errors) into a single exception type
    that callers can catch uniformly.
    """


class _DeviceHttpSession:
    """Generic HTTP session for IoT device communication.

    Wraps requests.Session with per-request timeout handling.
    Session-level timeout is NOT supported by requests, so the
    default timeout is stored as an instance attribute and
    passed explicitly on every request.

    Args:
        base_url: Device base URL (e.g. "http://192.168.1.100").
        default_timeout: Default per-request timeout in seconds.
    """

    def __init__(self, base_url: str, default_timeout: int = 10) -> None:
        # ---- Public attributes ------------------------------------------------
        self._base_url: str = base_url.rstrip("/")
        self._default_timeout: int = default_timeout

        # ---- Session setup ----------------------------------------------------
        self._session = requests.Session()
        adapter = HTTPAdapter(max_retries=1)
        self._session.mount("http://", adapter)
        self._session.mount("https://", adapter)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _resolve_timeout(self, timeout: int | None) -> int:
        """Return the explicit timeout or fall back to the instance default."""
        return timeout if timeout is not None else self._default_timeout

    @staticmethod
    def _raise_http_error(exc: requests.HTTPError) -> NoReturn:
        """Convert an HTTPError into a DeviceConnectionError with status and body."""
        status: int = exc.response.status_code if exc.response is not None else 0
        body: str = ""
        if exc.response is not None:
            try:
                body = exc.response.text[:100]
            except Exception:  # nosec B110 - best-effort body extraction
                pass
        raise DeviceConnectionError(f"HTTP {status}: {body}") from exc

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_json(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        timeout: int | None = None,
    ) -> Any:
        """GET request expecting a JSON response.

        Args:
            path: URL path relative to base_url (e.g. ``"/cm?cmnd=Status"``).
            params: Optional query parameters as a dict.
            timeout: Per-request timeout in seconds (uses ``default_timeout``
                when ``None``).

        Returns:
            Parsed JSON response (dict, list, or scalar).

        Raises:
            DeviceConnectionError: On timeout, connection failure, or
                HTTP 4xx/5xx response.
        """
        url = f"{self._base_url}{path}"
        t = self._resolve_timeout(timeout)
        try:
            resp = self._session.get(url, params=params, timeout=t)
            resp.raise_for_status()
            return resp.json()
        except (ValueError, json.JSONDecodeError) as exc:
            raise DeviceConnectionError(f"Invalid JSON response from device: {exc}") from exc
        except requests.exceptions.Timeout as exc:
            raise DeviceConnectionError("Connection timed out") from exc
        except requests.exceptions.ConnectionError as exc:
            raise DeviceConnectionError(f"Connection failed: {exc}") from exc
        except requests.exceptions.HTTPError as exc:
            self._raise_http_error(exc)
        except requests.exceptions.RequestException as exc:
            raise DeviceConnectionError(f"Request error: {exc}") from exc

    def get_form(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        timeout: int | None = None,
    ) -> str:
        """GET request expecting an HTML / text response.

        Used for ``/cfg_*`` endpoints that return HTML forms, not JSON.

        Args:
            path: URL path relative to base_url.
            params: Optional query parameters as a dict.
            timeout: Per-request timeout in seconds (uses ``default_timeout``
                when ``None``).

        Returns:
            Raw response text.

        Raises:
            DeviceConnectionError: On timeout, connection failure, or
                HTTP 4xx/5xx response.
        """
        url = f"{self._base_url}{path}"
        t = self._resolve_timeout(timeout)
        try:
            resp = self._session.get(url, params=params, timeout=t)
            resp.raise_for_status()
            return resp.text
        except requests.exceptions.Timeout as exc:
            raise DeviceConnectionError("Connection timed out") from exc
        except requests.exceptions.ConnectionError as exc:
            raise DeviceConnectionError(f"Connection failed: {exc}") from exc
        except requests.exceptions.HTTPError as exc:
            self._raise_http_error(exc)
        except requests.exceptions.RequestException as exc:
            raise DeviceConnectionError(f"Request error: {exc}") from exc


# =============================================================================
# URL dispatch
# =============================================================================


def _build_url(device_type: str, endpoint_name: str, **params: Any) -> tuple[str, str]:
    """Build a device-specific URL path for a named endpoint.

    The returned path is relative to the device root (e.g. ``"/cm?cmnd=Status%200"``)
    and is intended to be used with :class:`_DeviceHttpSession`.

    Args:
        device_type: ``"openbk"``, ``"tasmota"``, ``"tuya"``, or ``"openhasp"``.
        endpoint_name: One of ``"set_flags"``, ``"set_name"``,
            ``"configure_mqtt"``, ``"set_gpio"``, ``"start_ha_discovery"``,
            ``"get_full_info"``, ``"execute_command"``.
        **params: Endpoint-specific keyword arguments.

    Returns:
        Tuple of ``(url_path, device_type)``.

    Raises:
        DeviceConnectionError: If the combination is unsupported
            (error code ``UNSUPPORTED_TYPE`` in the message prefix).
    """
    if device_type not in ("openbk", "tasmota", "tuya", "openhasp"):
        raise DeviceConnectionError(f"[UNSUPPORTED_TYPE] Unknown device type: {device_type}")

    # --- Common endpoints -- identical URL pattern on OpenBK and Tasmota ---

    if endpoint_name == "get_full_info":
        if device_type in ("openbk", "tasmota"):
            return ("/cm?cmnd=Status%200", device_type)
        raise DeviceConnectionError(
            f"[UNSUPPORTED_TYPE] get_full_info is not supported for {device_type}"
        )

    if endpoint_name == "execute_command":
        if device_type in ("openbk", "tasmota"):
            command: str = str(params.get("command", ""))
            encoded = urllib.parse.quote(command, safe="")
            return (f"/cm?cmnd={encoded}", device_type)
        raise DeviceConnectionError(
            f"[UNSUPPORTED_TYPE] execute_command is not supported for {device_type}"
        )

    if endpoint_name == "set_startup_command":
        if device_type == "openbk":
            cmd = str(params.get("command", ""))
            encoded = urllib.parse.quote(cmd, safe="")
            return (f"/startup_command?startup_cmd=1&data={encoded}", "openbk")
        if device_type == "tasmota":
            return _build_tasmota_url(endpoint_name, **params)
        raise DeviceConnectionError(
            "[UNSUPPORTED_TYPE] set_startup_command is only supported on OpenBK and Tasmota"
        )

    # --- Dispatch by device type ---

    if device_type == "openbk":
        return _build_openbk_url(endpoint_name, **params)

    if device_type == "tasmota":
        return _build_tasmota_url(endpoint_name, **params)

    # tuya / openhasp endpoints are not routed through HTTP dispatch
    raise DeviceConnectionError(
        f"[UNSUPPORTED_TYPE] HTTP endpoints are not available for {device_type} devices"
    )


# --------------------------------------------------------------------------- #
# OpenBK URL builders
# --------------------------------------------------------------------------- #


def _build_openbk_url(endpoint_name: str, **params: Any) -> tuple[str, str]:
    """Build OpenBK-specific URL for a named endpoint."""

    if endpoint_name == "set_flags":
        flags: int = params.get("flags", 0)
        if not isinstance(flags, int) or flags < 0:
            raise DeviceConnectionError(
                "[INVALID_PARAM] flags must be a non-negative integer bitfield"
            )
        flag_parts: list[str] = []
        for bit in range(64):
            if (flags >> bit) & 1:
                flag_parts.append(f"flag{bit}=1")
        flag_parts.append("setFlags=1")
        return (f"/cfg_generic?{'&'.join(flag_parts)}", "openbk")

    if endpoint_name == "set_name":
        short = str(params.get("short_name", ""))
        full = urllib.parse.quote(str(params.get("full_name", params.get("name", ""))))
        return (
            f"/cfg_name?shortName={urllib.parse.quote(short)}&name={full}",
            "openbk",
        )

    if endpoint_name == "configure_mqtt":
        host = str(params.get("host", ""))
        port = str(params.get("port", "1883"))
        client = str(params.get("client", ""))
        group = str(params.get("group", ""))
        user = str(params.get("user", ""))
        password = str(params.get("password", ""))
        parts = [
            f"host={urllib.parse.quote(host)}",
            f"port={port}",
            f"client={urllib.parse.quote(client)}",
        ]
        if group:
            parts.append(f"group={urllib.parse.quote(group)}")
        if user:
            parts.append(f"user={urllib.parse.quote(user)}")
        if password:
            parts.append(f"password={urllib.parse.quote(password)}")
        return (f"/cfg_mqtt_set?{'&'.join(parts)}", "openbk")

    if endpoint_name == "set_gpio":
        pin: int = params.get("pin", 0)
        role = str(params.get("role", ""))
        channel: int = params.get("channel", 0)
        return (
            f"/cfg_pins?pin{pin}_role={urllib.parse.quote(role)}&pin{pin}_channel={channel}",
            "openbk",
        )

    if endpoint_name == "start_ha_discovery":
        prefix = str(params.get("prefix", "homeassistant"))
        return (f"/ha_discovery?prefix={urllib.parse.quote(prefix)}", "openbk")

    raise DeviceConnectionError(
        f"[UNSUPPORTED_TYPE] Endpoint '{endpoint_name}' is not supported on OpenBK"
    )


# --------------------------------------------------------------------------- #
# Tasmota URL builders
# --------------------------------------------------------------------------- #


def _build_tasmota_url(endpoint_name: str, **params: Any) -> tuple[str, str]:
    """Build Tasmota-specific URL for a named endpoint.

    Configuration endpoints use ``/cm?cmnd=`` with ``backlog`` for multi-command
    sequences.  Callers catch ``DeviceConnectionError`` for unsupported
    combinations.
    """

    if endpoint_name == "set_flags":
        flags: int = params.get("flags", 0)
        if not isinstance(flags, int) or flags < 0:
            raise DeviceConnectionError("[INVALID_PARAM] flags must be non-negative")
        # Tasmota SetOption 0-31. Build backlog for multi-bit.
        commands: list[str] = []
        for bit in range(32):
            if (flags >> bit) & 1:
                commands.append(f"SetOption{bit} 1")
        if not commands:
            raise DeviceConnectionError("[INVALID_PARAM] No flags set in bitfield")
        cmd = "; ".join(commands)
        if len(commands) > 1:
            return (f"/cm?cmnd=backlog%20{urllib.parse.quote(cmd)}", "tasmota")
        return (f"/cm?cmnd={urllib.parse.quote(commands[0])}", "tasmota")

    if endpoint_name == "set_name":
        short = str(params.get("short_name", ""))
        full = str(params.get("full_name", params.get("name", "")))
        if full:
            cmd = f"DeviceName {full}; FriendlyName1 {short}"
            return (f"/cm?cmnd=backlog%20{urllib.parse.quote(cmd)}", "tasmota")
        return (f"/cm?cmnd=DeviceName%20{urllib.parse.quote(short)}", "tasmota")

    if endpoint_name == "configure_mqtt":
        parts = []
        for key, cmd in [
            ("host", "MqttHost"),
            ("port", "MqttPort"),
            ("client", "MqttClient"),
            ("group", "GroupTopic"),
            ("user", "MqttUser"),
            ("password", "MqttPassword"),
        ]:
            val = params.get(key)
            if val is not None and str(val):
                parts.append(f"{cmd} {val}")
        if not parts:
            raise DeviceConnectionError("[INVALID_PARAM] No MQTT parameters provided")
        if len(parts) == 1:
            return (f"/cm?cmnd={urllib.parse.quote(parts[0])}", "tasmota")
        return (f"/cm?cmnd=backlog%20{urllib.parse.quote('; '.join(parts))}", "tasmota")

    if endpoint_name == "set_friendly_name":
        name = str(params.get("friendly_name", ""))
        return (f"/cm?cmnd=FriendlyName1%20{urllib.parse.quote(name)}", "tasmota")

    if endpoint_name == "start_ha_discovery":
        return ("/cm?cmnd=SetOption19%201", "tasmota")

    if endpoint_name == "set_startup_command":
        command = str(params.get("command", ""))
        rule = f"Rule1 ON System#Boot do {command} endon"
        return (f"/cm?cmnd=backlog%20{urllib.parse.quote(rule)}%3BRule1%201", "tasmota")

    if endpoint_name in ("set_gpio",):
        raise DeviceConnectionError(
            "[UNSUPPORTED_TYPE] GPIO configuration requires Module/GPIO commands "
            "on Tasmota -- use the WebUI or iot_execute_command instead."
        )

    raise DeviceConnectionError(
        f"[UNSUPPORTED_TYPE] Endpoint '{endpoint_name}' is not supported on Tasmota"
    )
