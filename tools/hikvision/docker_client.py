"""
Hikvision Docker Client

Provides Docker API access to the hikvision-doorbell container.
Uses Docker HTTP API via unix socket (/var/run/docker.sock).
No external dependencies - uses only Python stdlib.
"""

import json
import os
import socket
import time
from typing import Any

from tools.constants import DOCKER_SOCKET, HIKVISION_CONTAINER_NAME

CONTAINER_NAME = HIKVISION_CONTAINER_NAME

__all__ = [
    "_docker_available",
    "get_container_status",
    "get_container_logs",
    "count_vmd_events",
    "count_call_events",
    "restart_container",
]

_docker_available_cache: bool | None = None


def _docker_available() -> bool:
    """Check if Docker socket is accessible at startup.

    Returns True only if the socket file exists and is connectable.
    Result is cached — socket path doesn't change during server lifetime.

    Returns:
        True if Docker socket is available, False otherwise.
    """
    global _docker_available_cache
    if _docker_available_cache is not None:
        return _docker_available_cache

    if not os.path.exists(DOCKER_SOCKET):
        _docker_available_cache = False
        return False

    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(2)
        sock.connect(DOCKER_SOCKET)
        sock.close()
        _docker_available_cache = True
        return True
    except Exception:
        _docker_available_cache = False
        return False


def _docker_request(method: str, path: str, timeout: int = 10) -> tuple[int, str] | None:
    """Make an HTTP request to the Docker API via unix socket.

    Args:
        method: HTTP method (GET, POST).
        path: API path (e.g. "/containers/hikvision-doorbell/json").
        timeout: Socket timeout in seconds.

    Returns:
        Tuple of (status_code, response_body) or None on failure.
    """
    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        sock.connect(DOCKER_SOCKET)

        request = f"{method} {path} HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n"
        sock.sendall(request.encode("utf-8"))

        response = b""
        while True:
            try:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                response += chunk
            except TimeoutError:
                break

        sock.close()

        text = response.decode("utf-8", errors="ignore")
        parts = text.split("\r\n\r\n", 1)
        if len(parts) < 2:
            return None

        headers_part, body = parts
        status_line = headers_part.split("\r\n")[0]
        try:
            status_code = int(status_line.split(" ")[1])
        except ValueError:
            return None
        except IndexError:
            return None

        # Handle chunked transfer encoding
        is_chunked = "transfer-encoding: chunked" in headers_part.lower()
        if is_chunked:
            body = _decode_chunked(body)

        return status_code, body
    except Exception:
        return None


def _decode_chunked(data: str) -> str:
    """Decode HTTP chunked transfer encoding.

    Args:
        data: Raw chunked response body.

    Returns:
        Decoded body without chunk headers.
    """
    result = []
    pos = 0
    while pos < len(data):
        crlf = data.find("\r\n", pos)
        if crlf == -1:
            break
        try:
            chunk_size = int(data[pos:crlf], 16)
        except ValueError:
            break
        if chunk_size == 0:
            break
        pos = crlf + 2
        result.append(data[pos : pos + chunk_size])
        pos += chunk_size + 2
    return "".join(result) if result else data


def get_container_status() -> dict[str, Any]:
    """Get status of the hikvision-doorbell container.

    Returns:
        Dict with: running (bool), status (str), started_at (str), health (str|None).
    """
    result = _docker_request("GET", f"/containers/{CONTAINER_NAME}/json")
    if result is None:
        return {
            "running": False,
            "status": "not_found",
            "error": f"Container {CONTAINER_NAME} not found or Docker API unreachable",
        }
    status_code, body = result
    if status_code != 200:
        return {
            "running": False,
            "status": "not_found",
            "error": f"Docker API returned HTTP {status_code}",
        }

    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        return {"running": False, "status": "error", "error": "Invalid JSON response"}

    state = data.get("State", {})
    health = state.get("Health", {}).get("Status", "no_healthcheck")

    return {
        "running": state.get("Running", False),
        "status": state.get("Status", "unknown"),
        "started_at": state.get("StartedAt", ""),
        "health": health,
    }


def get_container_logs(since: str = "1h", tail: int = 100) -> str:
    """Fetch logs from the hikvision-doorbell container.

    Args:
        since: Time window (e.g. "1h", "4h", "24h").
        tail: Number of lines from end (default 100).

    Returns:
        Log text, or error message.
    """
    since_seconds = 0
    if since.endswith("h"):
        try:
            since_seconds = int(since[:-1]) * 3600
        except ValueError:
            pass
    elif since.endswith("m"):
        try:
            since_seconds = int(since[:-1]) * 60
        except ValueError:
            pass

    now = int(time.time())
    since_ts = now - since_seconds if since_seconds > 0 else now - 3600

    path = f"/containers/{CONTAINER_NAME}/logs?stdout=true&stderr=true&tail={tail}&since={since_ts}"

    result = _docker_request("GET", path, timeout=15)
    if result is None:
        return "Error: Docker API unreachable"
    status_code, body = result
    if status_code != 200:
        return f"Error: HTTP {status_code}"
    return body


def restart_container() -> dict[str, Any]:
    """Restart the hikvision-doorbell container.

    Returns:
        Dict with: success (bool), message (str).
    """
    result = _docker_request("POST", f"/containers/{CONTAINER_NAME}/restart", timeout=30)
    if result is None:
        return {"success": False, "message": "Docker API unreachable"}
    status_code, _body = result
    if 200 <= status_code < 300:
        return {"success": True, "message": f"Container {CONTAINER_NAME} restarted"}
    return {"success": False, "message": f"Docker API returned HTTP {status_code}"}


def count_vmd_events(since: str = "4h") -> dict[str, Any]:
    """Count VMD (Video Motion Detection) events in container logs.

    VMD events appear as: 'Motion detected from Gate'
    Zero events for 4+ hours indicates ISAPI connection failure.

    Args:
        since: Time window (default "4h").

    Returns:
        Dict with: vmd_count (int), isapi_healthy (bool), check_window (str).
    """
    logs = get_container_logs(since=since, tail=200)
    vmd_count = logs.count("Motion detected from Gate")
    return {
        "vmd_count": vmd_count,
        "isapi_healthy": vmd_count > 0,
        "check_window": since,
    }


def count_call_events(since: str = "4h") -> dict[str, Any]:
    """Count call events in container logs.

    Call events appear as: 'Doorbell ringing'
    Zero events indicates the doorbell button may not be working.

    Args:
        since: Time window (default "4h").

    Returns:
        Dict with: call_count (int), has_calls (bool), check_window (str).
    """
    logs = get_container_logs(since=since, tail=200)
    call_count = logs.count("Doorbell ringing")
    return {
        "call_count": call_count,
        "has_calls": call_count > 0,
        "check_window": since,
    }
