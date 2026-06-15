#!/usr/bin/env python3
"""
IoT MCP Server

Model Context Protocol server for IoT device management.
Supports OpenBK (OpenBeken), Tasmota, Tuya, and OpenHASP devices.

Architecture:
- Port 9100: Health check (lightweight HTTP server)
- Port 9101: MCP SSE transport - /sse, /messages
- Port 9102: REST API (Starlette) - /api/*
"""

import inspect
import json
import os
import shutil
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

from fastmcp import FastMCP

from tools.constants import (
    ALLOW_PUBLIC_BIND,
    BIND_HOST,
    DEFAULT_NETWORK_RANGE,
    DOCKER_SOCKET,
    END_IP,
    HEALTH_CHECK_PORT,
    MCP_ALLOWED_ORIGINS,
    MCP_SSE_PORT,
    MCP_TRANSPORT,
    MQTT_BROKER,
    MQTT_PORT,
    REST_API_PORT,
    START_IP,
    TOOL_MANIFESTS,
    TOOLS_VERSION,
    get_logger,
    get_tool_counts,
    setup_logging,
)
from tools.iot_config import register_iot_config_tools
from tools.iot_control import register_iot_control_tools
from tools.iot_devices import register_iot_device_tools
from tools.iot_discovery import register_iot_discovery_tools
from tools.iot_hikvision import register_hikvision_tools
from tools.iot_meta import register_iot_meta_tools
from tools.iot_mqtt import register_iot_mqtt_tools
from tools.iot_openhasp import register_openhasp_tools
from tools.iot_tuya import register_iot_tuya_tools
from tools.middleware.auth import AuthMiddleware
from tools.middleware.logging_mw import LoggingMiddleware
from tools.middleware.rate_limit import RateLimitMiddleware

# =============================================================================
# HEALTH CHECK SERVER (port 9100)
# =============================================================================

HEALTH_STATE: dict[str, Any] = {
    "status": "starting",
    "tools": 0,
    "tools_version": TOOLS_VERSION,
    "last_heartbeat": time.time(),
}


class HealthHandler(BaseHTTPRequestHandler):
    """Simple HTTP handler for health check endpoint."""

    def do_GET(self) -> None:
        """Handle GET requests."""
        if self.path == "/health":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(HEALTH_STATE).encode())
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format: str, *args: Any) -> None:
        """Suppress request logging."""
        pass


def start_health_server(port: int = 9100) -> HTTPServer:
    """Start lightweight HTTP server for health checks.

    Args:
        port: Port number to listen on.

    Returns:
        The HTTP server instance.
    """
    server = HTTPServer((BIND_HOST, port), HealthHandler)
    threading.Thread(target=server.serve_forever, daemon=True, name="HealthServer").start()
    get_logger("health").info("HTTP health endpoint started on port %d", port)
    return server


# =============================================================================
# CONFIGURATION
# =============================================================================

# =============================================================================
# INITIALIZE MCP SERVER
# =============================================================================

mcp = FastMCP("IoT-Observer", host=BIND_HOST, port=MCP_SSE_PORT)

# Middleware instances
auth_middleware = AuthMiddleware()
rate_limit_middleware = RateLimitMiddleware()
logging_middleware = LoggingMiddleware()

# =============================================================================
# REGISTER ALL TOOLS
# =============================================================================

register_iot_device_tools(mcp)
register_iot_discovery_tools(mcp)
register_iot_control_tools(mcp)
register_iot_config_tools(mcp)
register_iot_mqtt_tools(mcp)
register_iot_meta_tools(mcp)
register_iot_tuya_tools(mcp)
register_openhasp_tools(mcp)
register_hikvision_tools(mcp)


# =============================================================================
# TOOL HELPERS
# =============================================================================


def get_all_tools() -> Any:
    """Return a dictionary of all registered tools."""
    if hasattr(mcp, "_tool_manager") and hasattr(mcp._tool_manager, "_tools"):
        return mcp._tool_manager._tools
    if hasattr(mcp, "_tools"):
        return mcp._tools
    return {}


def get_tool(name: str) -> Any | None:
    """Return tool by name if available."""
    return get_all_tools().get(name)


def get_tool_count() -> int:
    """Return the number of registered tools."""
    return len(get_all_tools())


tool_count = get_tool_count()


# Session store for Streamable HTTP
_sessions: dict[str, float] = {}
_session_lock = threading.Lock()


SESSION_TTL_SECONDS = int(os.getenv("MCP_SESSION_TTL", "1800"))


def _cleanup_stale_sessions() -> None:
    """Remove sessions older than SESSION_TTL_SECONDS to prevent memory leak."""
    now = time.time()
    with _session_lock:
        stale = [sid for sid, ts in _sessions.items() if now - ts > SESSION_TTL_SECONDS]
        for sid in stale:
            _sessions.pop(sid, None)
            rate_limit_middleware.reset_session(sid)


def _create_session() -> str:
    _cleanup_stale_sessions()  # Prune expired sessions
    session_id = str(uuid.uuid4())
    with _session_lock:
        _sessions[session_id] = time.time()
    return session_id


def _validate_session(session_id: str | None) -> bool:
    if not session_id:
        return False
    with _session_lock:
        return session_id in _sessions


def _delete_session(session_id: str) -> None:
    with _session_lock:
        _sessions.pop(session_id, None)
        rate_limit_middleware.reset_session(session_id)


def _validate_origin(request: Any) -> bool:
    """Validate the Origin header to prevent DNS rebinding.

    Checks against allowed origins from MCP_ALLOWED_ORIGINS env var
    (comma-separated list of pattern URLs like 'http://localhost:*').
    Also allows localhost, 127.0.0.1, and BIND_HOST by default.
    """
    origin = request.headers.get("origin", "")
    if not origin:
        return True  # Non-browser request — DNS rebinding not applicable
    from urllib.parse import urlparse

    parsed = urlparse(origin)

    # Always allow localhost and loopback
    if parsed.hostname in ("localhost", "127.0.0.1") or parsed.hostname == BIND_HOST:
        return True

    # Check against configurable allowed origins
    allowed = [p.strip() for p in MCP_ALLOWED_ORIGINS.split(",")]
    for pattern in allowed:
        pattern_parsed = urlparse(pattern)
        if pattern_parsed.hostname == parsed.hostname:
            port_match = (
                pattern_parsed.port is None
                or str(pattern_parsed.port) == "*"
                or str(parsed.port) == str(pattern_parsed.port)
            )
            if port_match:
                return True

    return False


# =============================================================================
# REST API (Starlette on separate port 9102)
# =============================================================================


def create_rest_app() -> Any:
    """Create REST API application for tools (alternative access, not MCP)."""
    from starlette.applications import Starlette
    from starlette.middleware import Middleware
    from starlette.middleware.cors import CORSMiddleware
    from starlette.responses import JSONResponse
    from starlette.routing import Route

    async def health(request: Any) -> JSONResponse:
        return JSONResponse(
            {
                "status": "healthy",
                "server": "IoT-Observer",
                "version": TOOLS_VERSION,
                "tool_count": get_tool_count(),
                "tools_registered": get_tool_count(),
                "tool_invocation_counts": get_tool_counts(),
                "endpoints": {
                    "mcp_sse": f"http://{BIND_HOST}:{MCP_SSE_PORT}/sse",
                    "mcp_messages": f"http://{BIND_HOST}:{MCP_SSE_PORT}/messages",
                    "mcp_streamable_http": f"http://{BIND_HOST}:{REST_API_PORT}/mcp",
                    "rest_api": f"http://{BIND_HOST}:{REST_API_PORT}/api/",
                },
            }
        )

    async def list_tools_endpoint(request: Any) -> JSONResponse:
        tools = get_all_tools()
        tool_list = []
        for name, tool in tools.items():
            desc = None
            if hasattr(tool, "description") and tool.description:
                desc = tool.description
            elif hasattr(tool, "fn") and hasattr(tool.fn, "__doc__") and tool.fn.__doc__:
                desc = tool.fn.__doc__.strip().split("\n")[0]
            tool_list.append({"name": name, "description": desc})
        return JSONResponse(
            {
                "success": True,
                "total": len(tool_list),
                "tool_count": len(tool_list),
                "tools": sorted(tool_list, key=lambda x: str(x.get("name", ""))),
            }
        )

    async def call_tool_endpoint(request: Any) -> JSONResponse:
        tool_name = request.path_params.get("tool_name", "")

        try:
            body = await request.body()
            args = json.loads(body) if body else {}
        except json.JSONDecodeError:
            args = {}
        except Exception:
            args = {}

        tool = get_tool(tool_name)

        if tool is None:
            all_tool_names = list(get_all_tools().keys())
            return JSONResponse(
                {
                    "success": False,
                    "error": f"Tool '{tool_name}' not found",
                    "available_tools": sorted(all_tool_names)[:30],
                    "total_tools": len(all_tool_names),
                },
                status_code=404,
            )

        try:
            if hasattr(tool, "fn") and callable(tool.fn):
                fn = tool.fn
            elif callable(tool):
                fn = tool
            else:
                return JSONResponse(
                    {
                        "success": False,
                        "error": f"Tool '{tool_name}' is not callable",
                    },
                    status_code=500,
                )

            if inspect.iscoroutinefunction(fn):
                result = await fn(**args)
            else:
                result = fn(**args)

            if isinstance(result, str):
                try:
                    result = json.loads(result)
                except json.JSONDecodeError:
                    pass

            success = result.get("success", True) if isinstance(result, dict) else True
            return JSONResponse({"success": bool(success), "tool": tool_name, "result": result})

        except TypeError as exc:
            return JSONResponse(
                {
                    "success": False,
                    "error": f"Invalid arguments: {exc}",
                    "tool": tool_name,
                },
                status_code=400,
            )
        except Exception as exc:
            return JSONResponse(
                {
                    "success": False,
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                    "tool": tool_name,
                },
                status_code=500,
            )

    async def tool_manifest_endpoint(request: Any) -> JSONResponse:
        tool_name = request.path_params.get("tool_name", "")
        manifest = TOOL_MANIFESTS.get(tool_name)
        if manifest is None:
            return JSONResponse(
                {"success": False, "error": f"Tool '{tool_name}' not found"},
                status_code=404,
            )
        return JSONResponse({"success": True, "data": manifest})

    async def mcp_post(request: Any) -> JSONResponse:
        """Handle POST /mcp -- JSON-RPC message handling."""
        if not _validate_origin(request):
            return JSONResponse({"error": "Origin not allowed"}, status_code=403)

        session_id = request.headers.get("Mcp-Session-Id", "") or request.headers.get(
            "mcp-session-id", ""
        )

        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"error": "Invalid JSON"}, status_code=400)

        method = body.get("method", "")
        msg_id = body.get("id")

        # tools/list -- no session needed
        if method == "tools/list":
            tools = get_all_tools()
            tool_list = []
            for name, t in tools.items():
                desc = None
                if hasattr(t, "description") and t.description:
                    desc = t.description
                elif hasattr(t, "fn") and hasattr(t.fn, "__doc__") and t.fn.__doc__:
                    desc = t.fn.__doc__.strip().split("\n")[0]
                tool_list.append(
                    {
                        "name": name,
                        "description": desc,
                        "inputSchema": {"type": "object"},
                    }
                )
            return JSONResponse({"jsonrpc": "2.0", "id": msg_id, "result": {"tools": tool_list}})

        # tools/list_categories -- L3+ discovery
        if method == "tools/list_categories":
            return JSONResponse(
                {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": {"categories": [{"name": "iot", "tool_count": get_tool_count()}]},
                }
            )

        # tools/get_schema
        if method == "tools/get_schema":
            tool_name = body.get("params", {}).get("name", "")
            tool = get_tool(tool_name)
            if not tool:
                return JSONResponse(
                    {
                        "jsonrpc": "2.0",
                        "id": msg_id,
                        "error": {"code": -32602, "message": f"Unknown tool: {tool_name}"},
                    },
                    status_code=404,
                )
            return JSONResponse(
                {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": {"name": tool_name, "inputSchema": {"type": "object"}},
                }
            )

        # tools/call -- requires middleware chain
        if method == "tools/call":
            params = body.get("params", {})
            tool_name = params.get("name", "")
            arguments = params.get("arguments", {})

            if not tool_name:
                return JSONResponse(
                    {
                        "jsonrpc": "2.0",
                        "id": msg_id,
                        "error": {"code": -32602, "message": "Missing tool name"},
                    },
                    status_code=400,
                )

            if session_id and not _validate_session(session_id):
                return JSONResponse(
                    {
                        "jsonrpc": "2.0",
                        "id": msg_id,
                        "error": {"code": -32001, "message": "Invalid or expired session"},
                    },
                    status_code=401,
                )

            ctx = logging_middleware.create_context(tool_name, session_id)

            headers_dict = {k.lower(): v for k, v in request.headers.items()}
            auth_result = auth_middleware.authenticate(headers_dict)
            if not auth_result.get("authenticated", False):
                err = auth_result.get(
                    "error",
                    {"code": "AUTH_FAILED", "message": "Authentication failed"},
                )
                logging_middleware.log_error(ctx, err.get("message", "Auth failed"), 0)
                return JSONResponse(
                    {
                        "jsonrpc": "2.0",
                        "id": msg_id,
                        "error": {"code": -32001, "message": err.get("message", "Auth failed")},
                    },
                    status_code=401,
                )

            rate_result = rate_limit_middleware.check_request(headers_dict)
            if not rate_result.get("allowed", False):
                err = rate_result.get("error", {"code": "RATE_LIMITED", "message": "Rate limited"})
                logging_middleware.log_error(ctx, err.get("message", "Rate limited"), 0)
                return JSONResponse(
                    {
                        "jsonrpc": "2.0",
                        "id": msg_id,
                        "error": {"code": -32000, "message": err.get("message", "Rate limited")},
                    },
                    status_code=429,
                )

            start = time.monotonic()
            tool = get_tool(tool_name)
            if not tool:
                return JSONResponse(
                    {
                        "jsonrpc": "2.0",
                        "id": msg_id,
                        "error": {"code": -32602, "message": f"Unknown tool: {tool_name}"},
                    },
                    status_code=404,
                )

            try:
                if hasattr(tool, "fn") and callable(tool.fn):
                    fn = tool.fn
                elif callable(tool):
                    fn = tool
                else:
                    raise TypeError("Tool not callable")

                if inspect.iscoroutinefunction(fn):
                    result = await fn(**arguments)
                else:
                    result = fn(**arguments)

                duration = int((time.monotonic() - start) * 1000)
                logging_middleware.log_completion(ctx, "success", duration)

                if isinstance(result, str):
                    try:
                        result = json.loads(result)
                    except json.JSONDecodeError:
                        pass

                return JSONResponse(
                    {
                        "jsonrpc": "2.0",
                        "id": msg_id,
                        "result": {
                            "success": True,
                            "data": result,
                            "_meta": {"duration_ms": duration},
                        },
                    }
                )
            except Exception as exc:
                duration = int((time.monotonic() - start) * 1000)
                logging_middleware.log_error(ctx, str(exc), duration)
                return JSONResponse(
                    {
                        "jsonrpc": "2.0",
                        "id": msg_id,
                        "error": {"code": -32603, "message": str(exc)},
                    },
                    status_code=500,
                )

        return JSONResponse(
            {
                "jsonrpc": "2.0",
                "id": msg_id,
                "error": {"code": -32601, "message": f"Method not found: {method}"},
            },
            status_code=404,
        )

    async def mcp_sse(request: Any) -> JSONResponse:
        """Handle GET /mcp -- placeholder for SSE stream endpoint."""
        return JSONResponse(
            {
                "jsonrpc": "2.0",
                "result": {"stream": "mcp-events"},
                "_meta": {"note": "SSE stream available at /sse on port 9101"},
            }
        )

    async def mcp_delete(request: Any) -> JSONResponse:
        """Handle DELETE /mcp -- session termination."""
        if not _validate_origin(request):
            return JSONResponse({"error": "Origin not allowed"}, status_code=403)
        session_id = request.headers.get("Mcp-Session-Id", "") or request.headers.get(
            "mcp-session-id", ""
        )
        if session_id:
            _delete_session(session_id)
        return JSONResponse({"success": True, "message": "Session terminated"})

    routes = [
        Route("/health", endpoint=health, methods=["GET"]),
        Route("/api/health", endpoint=health, methods=["GET"]),
        Route("/api/tools", endpoint=list_tools_endpoint, methods=["GET"]),
        Route(
            "/api/tools/{tool_name}",
            endpoint=call_tool_endpoint,
            methods=["POST"],
        ),
        Route(
            "/api/tools/{tool_name}/manifest",
            endpoint=tool_manifest_endpoint,
            methods=["GET"],
        ),
        Route("/mcp", endpoint=mcp_post, methods=["POST"]),
        Route("/mcp", endpoint=mcp_sse, methods=["GET"]),
        Route("/mcp", endpoint=mcp_delete, methods=["DELETE"]),
    ]

    middleware = [
        Middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_methods=["*"],
            allow_headers=["*"],
        )
    ]

    return Starlette(routes=routes, middleware=middleware)


def run_rest_api() -> None:
    """Start REST API in a separate thread."""
    import uvicorn

    app = create_rest_app()
    get_logger("rest").info("REST API started on port %d", REST_API_PORT)
    uvicorn.run(app, host=BIND_HOST, port=REST_API_PORT, log_level="warning")


# =============================================================================
# MAIN ENTRY POINT
# =============================================================================


def main() -> None:
    """Entry point for the IoT MCP server."""
    setup_logging()
    logger = get_logger("server")

    # Guard: public binding requires explicit confirmation
    if BIND_HOST == "0.0.0.0" and not ALLOW_PUBLIC_BIND:
        logger.critical(
            "Binding to 0.0.0.0 without MCP_UNSAFE_PUBLIC_ACCESS_CONFIRMED=1. "
            "Set MCP_UNSAFE_PUBLIC_ACCESS_CONFIRMED=1 to confirm."
        )
        sys.exit(1)
    if BIND_HOST == "0.0.0.0":
        logger.critical("Server bound to 0.0.0.0 — tools are exposed to the network.")

    # 1. Start health check server (port 9100)
    start_health_server(port=HEALTH_CHECK_PORT)
    HEALTH_STATE["status"] = "healthy"
    HEALTH_STATE["tools"] = tool_count
    HEALTH_STATE["tool_count"] = tool_count
    HEALTH_STATE["tools_version"] = TOOLS_VERSION
    HEALTH_STATE["last_heartbeat"] = time.time()

    logger.info("=" * 50)
    logger.info("IoT-Observer MCP Server")
    logger.info("=" * 50)
    logger.info("MQTT Broker: %s:%s", MQTT_BROKER, MQTT_PORT)
    logger.info("Network Range: %s - %s", START_IP, END_IP)
    logger.info("Scan CIDR: %s", DEFAULT_NETWORK_RANGE)
    logger.info("Device Cache: /app/data/discovered_devices.json")
    logger.info("Registered tools: %d", tool_count)
    logger.info("-" * 50)

    # Check optional dependencies
    if not os.path.exists(DOCKER_SOCKET):
        logger.warning(
            "Docker socket %s not found -- 6 Hikvision Docker tools "
            "(container_status, container_logs, check_vmd, restart_container, "
            "isapi_health, pipeline_diagnose) will return errors.",
            DOCKER_SOCKET,
        )
    if not shutil.which("nmap"):
        logger.warning(
            "nmap not found -- iot_discover_devices will fail. Install with: apt-get install nmap"
        )

    # 2. Start REST API in a separate thread (port 9102)
    rest_thread = threading.Thread(target=run_rest_api, daemon=True, name="RestAPI")
    rest_thread.start()

    logger.info("Endpoints:")
    logger.info("  Health:      http://%s:%s/health", BIND_HOST, HEALTH_CHECK_PORT)
    logger.info("  MCP SSE:     http://%s:%s/sse", BIND_HOST, MCP_SSE_PORT)
    logger.info("  MCP MSG:     http://%s:%s/messages", BIND_HOST, MCP_SSE_PORT)
    logger.info("  REST API:    http://%s:%s/api/", BIND_HOST, REST_API_PORT)
    logger.info("=" * 50)

    # 3. Start MCP SSE server (port 9101) - only if MCP_TRANSPORT includes sse
    if MCP_TRANSPORT in ("sse", "both"):
        logger.info("Starting MCP SSE transport on port %s...", MCP_SSE_PORT)
        mcp.run(transport="sse", host=BIND_HOST, port=MCP_SSE_PORT)
    else:
        logger.info("Streamable HTTP enabled on port %d (/mcp). SSE disabled.", REST_API_PORT)
        threading.Event().wait()


if __name__ == "__main__":
    main()
