"""E2E tests for IoT configuration tool workflows via REST API.

Covers read-only workflows, write-gate behavior, and command blocklist
validation. All tests use the REST API endpoint and handle both
success and expected-failure responses gracefully.
"""

import json
import urllib.error
import urllib.request

import pytest

from .conftest import REST_API_URL, server_is_running

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(
        not server_is_running(),
        reason="MCP server not running",
    ),
]

# Test identifiers that work without real devices on the network.
# TEST-NET-1 address per RFC 5737 -- guaranteed non-routable.
_UNREACHABLE_IP = "192.0.2.1"
# Placeholder identifier for validation-only tests (never reaches device).
_PLACEHOLDER_ID = "test_device"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _api_get(path: str) -> dict:
    """Perform a GET request to the REST API and return parsed JSON."""
    req = urllib.request.Request(f"{REST_API_URL}{path}")
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return json.loads(exc.read())
    except Exception as exc:
        return {"success": False, "error": str(exc)}


def _api_post(tool_name: str, data: dict) -> dict:
    """Call a REST API tool via POST and return the parsed wrapper response.

    The REST API wraps tool responses as:
        {"success": <bool>, "tool": <name>, "result": <tool response dict>}
    """
    url = f"{REST_API_URL}/api/tools/{tool_name}"
    payload = json.dumps(data).encode()
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return json.loads(exc.read())
    except Exception as exc:
        return {"success": False, "error": str(exc)}


def _get_tool_result(api_response: dict) -> dict:
    """Extract the inner tool result dict from the REST API wrapper."""
    return api_response.get("result", {})


def _get_error_code(api_response: dict) -> str | None:
    """Extract the error code from a tool result, if present."""
    result = _get_tool_result(api_response)
    error = result.get("error", {})
    if isinstance(error, dict):
        return error.get("code")
    if isinstance(error, str):
        return "STRING_ERROR"
    return None


def _tool_succeeded(api_response: dict) -> bool:
    """Return True if the tool call returned success."""
    return _get_tool_result(api_response).get("success", False)


def _get_data(api_response: dict) -> dict:
    """Extract the data payload from a successful tool result."""
    return _get_tool_result(api_response).get("data", {})


def _failure_is_allowed(code: str | None) -> bool:
    """Check whether an error code is an expected/acceptable failure mode.

    These codes are normal when no real devices exist or write ops are
    disabled -- they indicate graceful error handling, not bugs.
    """
    return code in (
        "WRITE_DISABLED",
        "COMMAND_BLOCKED",
        "INVALID_PARAM",
        "NAME_NOT_RESOLVED",
        "DEVICE_NOT_FOUND",
        "DEVICE_ERROR",
        "UNSUPPORTED_TYPE",
        "STRING_ERROR",
    )


def _get_first_device_name() -> str | None:
    """Discover the first device name from the server cache, or None."""
    resp = _api_post("iot_list_devices", {})
    data = _get_data(resp)
    devices = data.get("devices", [])
    if devices and isinstance(devices, list) and len(devices) > 0:
        first = devices[0]
        if isinstance(first, dict):
            return first.get("name") or first.get("ip")
    return None


# ---------------------------------------------------------------------------
# Workflow Tests
# ---------------------------------------------------------------------------


class TestReadOnlyWorkflows:
    """Read-only tool chains that do not require device access."""

    def test_read_only_workflow(self):
        """Chain health -> tools list -> list_devices. Verify each step."""
        # Step 1: health check
        health = _api_get("/health")
        assert health.get("status") == "healthy", f"Health check failed: {health}"

        # Step 2: tools list
        tools = _api_get("/api/tools")
        assert tools.get("success") is True, f"Tools list failed: {tools}"
        tool_names = [t["name"] for t in tools.get("tools", [])]
        assert "iot_get_full_info" in tool_names, "iot_get_full_info missing from tools"
        assert "iot_execute_command" in tool_names, "iot_execute_command missing from tools"
        assert "iot_set_flags" in tool_names, "iot_set_flags missing from tools"

        # Step 3: list devices (works without real devices -- returns cache)
        devices_resp = _api_post("iot_list_devices", {})
        assert devices_resp.get("success") is True, f"list_devices failed: {devices_resp}"
        assert "result" in devices_resp

    def test_get_full_info_to_execute_workflow(self):
        """Chain get_full_info -> execute_command Status 0.

        Verifies both calls return well-structured responses.
        Handles missing devices and disabled write ops gracefully.
        """
        device = _get_first_device_name() or _UNREACHABLE_IP

        # Step 1: get_full_info
        full_info = _api_post("iot_get_full_info", {"identifier": device})
        fi_result = _get_tool_result(full_info)

        if fi_result.get("success"):
            # Verify response structure when device is reachable
            data = fi_result.get("data", {})
            assert "device_type" in data, f"Missing device_type: {data}"
            assert data["device_type"] in ("openbk", "tasmota"), (
                f"Unexpected device_type: {data.get('device_type')}"
            )
        else:
            # Graceful error when device unreachable
            code = _get_error_code(full_info)
            assert _failure_is_allowed(code), f"get_full_info unexpected error: {fi_result}"

        # Step 2: execute_command Status 0
        cmd_resp = _api_post(
            "iot_execute_command",
            {"identifier": device, "command": "Status 0"},
        )
        cmd_result = _get_tool_result(cmd_resp)

        if cmd_result.get("success"):
            # Verify response fields on success
            data = cmd_result.get("data", {})
            assert "command" in data, f"Missing command in response: {data}"
            assert data.get("command") == "Status 0", (
                f"Unexpected command echoed: {data.get('command')}"
            )
            assert "device_type" in data
        else:
            # Expected failure modes
            code = _get_error_code(cmd_resp)
            assert _failure_is_allowed(code), (
                f"execute_command unexpected error code: {code} - {cmd_result}"
            )


class TestInputValidation:
    """Validation checks that happen before any device communication."""

    def test_set_flags_validates_input(self):
        """Test that invalid flags input is rejected with INVALID_PARAM.

        Checks: empty identifier, negative flags, out-of-range flags.
        When write is disabled, WRITE_DISABLED is returned instead.
        """
        tests = [
            ("empty identifier", "", 0),
            ("negative flags", _PLACEHOLDER_ID, -1),
            ("flags exceeds 64-bit", _PLACEHOLDER_ID, 2**64),
        ]

        for desc, ident, flags in tests:
            resp = _api_post("iot_set_flags", {"identifier": ident, "flags": flags})
            code = _get_error_code(resp)
            assert code in ("INVALID_PARAM", "WRITE_DISABLED"), (
                f"{desc}: expected INVALID_PARAM or WRITE_DISABLED, got {code}: {resp}"
            )

    def test_set_name_validates_input(self):
        """Test name validation: spaces rejected, valid pattern allowed.

        When write is disabled, WRITE_DISABLED takes precedence.
        """
        # Invalid name with spaces -- should be rejected
        resp_invalid = _api_post(
            "iot_set_name",
            {"identifier": _PLACEHOLDER_ID, "short_name": "bad name with spaces"},
        )
        code_invalid = _get_error_code(resp_invalid)
        assert code_invalid in ("INVALID_PARAM", "WRITE_DISABLED"), (
            f"Invalid name: expected INVALID_PARAM or WRITE_DISABLED, got {code_invalid}"
        )

        # Valid name with underscores -- should pass validation
        resp_valid = _api_post(
            "iot_set_name",
            {"identifier": _PLACEHOLDER_ID, "short_name": "valid_device_name"},
        )
        code_valid = _get_error_code(resp_valid)

        if code_valid == "WRITE_DISABLED":
            # Expected when write ops off
            pass
        elif code_valid is None and _tool_succeeded(resp_valid):
            # Validation passed; device may be unreachable or operation succeeded
            pass
        else:
            # Any error besides WRITE_DISABLED must be about the device, not the name
            assert code_valid != "INVALID_PARAM", (
                f"Valid name should not fail validation: {resp_valid}"
            )
            assert _failure_is_allowed(code_valid), (
                f"Valid name unexpected error: {code_valid} - {resp_valid}"
            )

    def test_configure_mqtt_invalid_port(self):
        """Test that port 99999 (out of range) is rejected with INVALID_PARAM."""
        resp = _api_post(
            "iot_configure_mqtt",
            {"identifier": _PLACEHOLDER_ID, "port": 99999},
        )
        code = _get_error_code(resp)
        assert code in ("INVALID_PARAM", "WRITE_DISABLED"), (
            f"Port 99999: expected INVALID_PARAM or WRITE_DISABLED, got {code}: {resp}"
        )


class TestCommandBlocklist:
    """Blocked command safety checks."""

    def test_execute_command_restart_blocked(self):
        """'restart' without force=True is blocked by the command blocklist."""
        resp = _api_post(
            "iot_execute_command",
            {"identifier": _PLACEHOLDER_ID, "command": "restart"},
        )
        code = _get_error_code(resp)
        assert code in ("COMMAND_BLOCKED", "WRITE_DISABLED"), (
            f"restart: expected COMMAND_BLOCKED or WRITE_DISABLED, got {code}: {resp}"
        )

    def test_execute_command_restart_force_allowed(self):
        """'restart' with force=True bypasses the blocklist.

        The command may still fail with NAME_NOT_RESOLVED or DEVICE_NOT_FOUND
        if no real device is available -- that is expected and acceptable.
        """
        resp = _api_post(
            "iot_execute_command",
            {"identifier": _PLACEHOLDER_ID, "command": "restart", "force": True},
        )
        code = _get_error_code(resp)

        if code is None and _tool_succeeded(resp):
            # Blocklist bypassed, command executed
            data = _get_data(resp)
            assert "command" in data
        else:
            # Must NOT be COMMAND_BLOCKED -- force=True should bypass
            assert code != "COMMAND_BLOCKED", f"force=True should bypass blocklist, got: {resp}"
            # Other errors are acceptable (no device, write disabled, etc.)
            assert _failure_is_allowed(code) or code is None, (
                f"Unexpected error for force=True restart: {code} - {resp}"
            )

    def test_execute_command_format_blocked(self):
        """'Format 1' is blocked by the command blocklist."""
        resp = _api_post(
            "iot_execute_command",
            {"identifier": _PLACEHOLDER_ID, "command": "Format 1"},
        )
        code = _get_error_code(resp)
        assert code in ("COMMAND_BLOCKED", "WRITE_DISABLED"), (
            f"Format 1: expected COMMAND_BLOCKED or WRITE_DISABLED, got {code}: {resp}"
        )


class TestWriteGateAndErrors:
    """Write-gate enforcement and graceful error handling."""

    def test_set_flags_write_disabled(self):
        """Any write tool returns WRITE_DISABLED when ENABLE_WRITE_OPERATIONS=0.

        When write operations ARE enabled, the call proceeds (may succeed
        or get a device-level error -- both are valid).
        """
        resp = _api_post("iot_set_flags", {"identifier": _PLACEHOLDER_ID, "flags": 0})
        code = _get_error_code(resp)

        if code == "WRITE_DISABLED":
            # Server has write protection on -- this is the expected behavior
            pass
        elif code is None and _tool_succeeded(resp):
            # Write enabled, command succeeded
            pass
        else:
            # Write enabled, but device unreachable / validation failed
            assert _failure_is_allowed(code), f"set_flags unexpected error: {code} - {resp}"

    def test_get_full_info_works_with_bad_identifier(self):
        """Unreachable IP returns structured error, never a crash.

        Uses TEST-NET-1 (192.0.2.1) which is guaranteed non-routable.
        """
        resp = _api_post("iot_get_full_info", {"identifier": _UNREACHABLE_IP})

        # The REST API wrapper must not crash (status 200 or 500, not 5xx crash)
        assert "result" in resp or "error" in resp, f"Response missing result/error: {resp}"

        result = _get_tool_result(resp)
        if result.get("success"):
            # Unexpected but not wrong -- maybe the network resolved it
            pass
        else:
            error = result.get("error", {})
            if isinstance(error, dict):
                code = error.get("code", "UNKNOWN")
                assert code in (
                    "DEVICE_NOT_FOUND",
                    "DEVICE_ERROR",
                    "NAME_NOT_RESOLVED",
                ), f"Unexpected error code for bad IP: {code} - {error}"
            elif isinstance(error, str):
                # Simple string error from tool
                pass
            else:
                # Top-level REST API error
                pass

    def test_nonexistent_tool_returns_structured_error(self):
        """Calling a tool that does not exist returns a 404 with details."""
        resp = _api_post("iot_nonexistent_tool_123", {})
        assert resp.get("success") is False, f"Nonexistent tool should fail: {resp}"
        # Should include available_tools or an error message
        has_context = "available_tools" in resp or "error" in resp or "total_tools" in resp
        assert has_context, f"Error response lacks context: {resp}"
