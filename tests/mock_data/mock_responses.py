"""Mock device responses for use in unit and integration tests.

Functions return deep copies of anonymized real device responses.
All IPs are RFC 5737 documentation addresses (192.0.2.x).
"""

import copy
import json
import os
from typing import Any

_FIXTURES_DIR = os.path.dirname(os.path.abspath(__file__))


def _load_fixture(filename: str) -> dict[str, Any]:
    """Load a JSON fixture file from the fixtures directory."""
    path = os.path.join(_FIXTURES_DIR, filename)
    with open(path) as f:
        return json.load(f)


def openbk_status0_response() -> dict[str, Any]:
    """Return anonymized OpenBK Status 0 JSON response as dict.

    Source: Light_Bedroom (.115), OpenBK7231N v1.17.306
    Returns a deep copy to prevent test interference.
    """
    data = _load_fixture("openbk_115_status0.json")
    return copy.deepcopy(data)


def tasmota_status0_response() -> dict[str, Any]:
    """Return anonymized Tasmota Status 0 JSON response as dict.

    Source: Light_Bathroom_Mirror (.109), Tasmota 12.5.0
    Returns a deep copy to prevent test interference.
    """
    data = _load_fixture("tasmota_109_status0.json")
    return copy.deepcopy(data)


def device_error_response(
    code: str = "DEVICE_ERROR", message: str = "Device error"
) -> dict[str, Any]:
    """Return a device error response dict.

    Args:
        code: Error code string (e.g. "DEVICE_NOT_FOUND", "TIMEOUT").
        message: Human-readable error description.

    Returns:
        Dict with success=False and error details.
    """
    return {
        "success": False,
        "error": {
            "code": code,
            "message": message,
            "retryable": False,
        },
    }


def device_timeout_response() -> dict[str, Any]:
    """Return a connection timeout error response.

    Returns:
        Dict with success=False and TIMEOUT error code.
    """
    return device_error_response(
        code="TIMEOUT",
        message="Connection timed out",
    )


def device_http_error_response(status_code: int = 500) -> dict[str, Any]:
    """Return an HTTP error response with a simulated HTTP status.

    Args:
        status_code: HTTP status code (default 500).

    Returns:
        Dict with success=False and HTTP_ERROR code.
    """
    return device_error_response(
        code="HTTP_ERROR",
        message=f"HTTP {status_code}: Server Error",
    )
