"""FastMCP composition root with one policy pipeline for every transport."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from .config import Settings, load_settings
from .manifests import ManifestError, normalize_catalog
from .policy import OperationGate, PolicyError, Principal
from .targeting import TargetError


def _build_auth(settings: Settings) -> Any | None:
    if not settings.auth_token:
        return None
    from fastmcp.server.auth.providers.jwt import StaticTokenVerifier

    return StaticTokenVerifier(
        tokens={
            settings.auth_token: {
                "client_id": "local-home-devices-operator",
                "scopes": [
                    "devices:read",
                    "devices:sensitive",
                    "devices:write",
                    "devices:dangerous",
                ],
            }
        },
        required_scopes=["devices:read"],
    )


def _principal_from_fastmcp(settings: Settings) -> Principal:
    try:
        from fastmcp.server.dependencies import get_access_token

        token = get_access_token()
    except Exception:
        token = None
    if token is None:
        if settings.transport == "stdio":
            return Principal(
                subject="trusted-local-process",
                scopes=frozenset(
                    {"devices:read", "devices:sensitive", "devices:write", "devices:dangerous"}
                ),
                transport="stdio",
            )
        return Principal(
            subject="anonymous-loopback-http",
            scopes=frozenset({"devices:read"}),
            transport="http",
        )
    claims = getattr(token, "claims", None) or {}
    subject = str(
        getattr(token, "client_id", None)
        or claims.get("sub")
        or claims.get("client_id")
        or "authenticated"
    )
    scopes = frozenset(str(item) for item in (getattr(token, "scopes", None) or []))
    return Principal(subject=subject, scopes=scopes, transport="http")


def _install_policy_middleware(mcp: Any, gate: OperationGate, settings: Settings) -> None:
    from fastmcp.exceptions import ToolError
    from fastmcp.server.middleware import Middleware
    from tools.validators import ValidationError

    class InvocationPolicyMiddleware(Middleware):
        async def on_call_tool(self, context: Any, call_next: Any) -> Any:
            name = str(context.message.name)
            arguments = dict(context.message.arguments or {})
            principal = _principal_from_fastmcp(settings)
            try:
                manifest = gate.manifest(name)
                with gate.guard(name, arguments, principal):
                    async with asyncio.timeout(manifest["timeout_ms"] / 1000):
                        return await call_next(context)
            except TimeoutError as exc:
                raise ToolError("operation deadline exceeded") from exc
            except ToolError:
                raise
            except (PolicyError, ManifestError, TargetError, ValidationError) as exc:
                raise ToolError(str(exc)) from exc
            except Exception as exc:
                logging.getLogger(__name__).error(
                    "tool invocation failed for %s: %s", name, type(exc).__name__
                )
                raise ToolError("internal tool failure") from exc

    mcp.add_middleware(InvocationPolicyMiddleware())


def _register_legacy_tools(mcp: Any) -> None:
    """Register adapters only; policy remains outside adapter modules."""

    from tools.iot_config import register_iot_config_tools
    from tools.iot_control import register_iot_control_tools
    from tools.iot_devices import register_iot_device_tools
    from tools.iot_discovery import register_iot_discovery_tools
    from tools.iot_hikvision import register_hikvision_tools
    from tools.iot_meta import register_iot_meta_tools
    from tools.iot_mqtt import register_iot_mqtt_tools
    from tools.iot_openhasp import register_openhasp_tools
    from tools.iot_tuya import register_iot_tuya_tools

    register_iot_device_tools(mcp)
    register_iot_discovery_tools(mcp)
    register_iot_control_tools(mcp)
    register_iot_config_tools(mcp)
    register_iot_mqtt_tools(mcp)
    register_iot_meta_tools(mcp)
    register_iot_tuya_tools(mcp)
    register_openhasp_tools(mcp)
    register_hikvision_tools(mcp)


def _register_mock_tools(mcp: Any) -> None:
    state = {"power": False, "brightness": 50}

    @mcp.tool
    def mock_get_state(identifier: str = "dev_mock_light") -> dict[str, Any]:
        """Return deterministic state from the zero-I/O mock device."""
        return {"identifier": identifier, **state}

    @mcp.tool
    def mock_set_power(identifier: str, power: bool) -> dict[str, Any]:
        """Set power on the zero-I/O mock device."""
        state["power"] = power
        return {"identifier": identifier, **state}


def build_server(settings: Settings | None = None) -> tuple[Any, OperationGate]:
    """Build a server without starting a transport or performing device I/O."""

    from fastmcp import FastMCP
    from starlette.responses import JSONResponse

    settings = settings or load_settings()
    if settings.mock_mode:
        from .mock_runtime import MOCK_MANIFESTS

        raw_catalog = MOCK_MANIFESTS
    else:
        from tools.constants import TOOL_MANIFESTS

        raw_catalog = TOOL_MANIFESTS

    catalog = normalize_catalog(raw_catalog)
    gate = OperationGate(settings, catalog)
    mcp = FastMCP(
        name="Local Home Devices",
        version="2.0.0",
        auth=_build_auth(settings),
    )
    if settings.mock_mode:
        _register_mock_tools(mcp)
    else:
        from .legacy_compat import install_legacy_safety

        install_legacy_safety(settings)
        _register_legacy_tools(mcp)

    # Discovery and invocation must agree. Inactive capabilities are removed
    # through the public FastMCP API instead of remaining visible-but-denied.
    for name, manifest in catalog.items():
        if manifest["active_state"] != "active":
            # FastMCP 3 component visibility is policy-driven. Disable through
            # the public component API so discovery and invocation agree.
            mcp.disable(keys={f"tool:{name}"})
    _install_policy_middleware(mcp, gate, settings)

    @mcp.custom_route("/health", methods=["GET"])
    async def health(_request: Any) -> JSONResponse:
        return JSONResponse(
            {
                "status": "healthy",
                "service": "local-home-devices-mcp",
                "transport": settings.transport,
                "mock_mode": settings.mock_mode,
            }
        )

    @mcp.custom_route("/ready", methods=["GET"])
    async def ready(_request: Any) -> JSONResponse:
        tools = await mcp.get_tools()
        registered = set(tools)
        governed = set(catalog)
        missing = sorted(registered - governed)
        orphaned = sorted(governed - registered)
        status = "ready" if not missing else "not-ready"
        return JSONResponse(
            {
                "status": status,
                "registered": len(registered),
                "governed": len(governed),
                "missing_manifests": missing,
                "inactive_or_optional": orphaned,
            },
            status_code=200 if status == "ready" else 503,
        )

    return mcp, gate


def run(settings: Settings | None = None) -> None:
    settings = settings or load_settings()
    mcp, _gate = build_server(settings)
    if settings.transport == "stdio":
        mcp.run(transport="stdio")
        return
    mcp.run(
        transport="http",
        host=settings.bind_host,
        port=settings.port,
        path=settings.mcp_path,
    )


def capability_document(settings: Settings | None = None) -> str:
    settings = settings or load_settings()
    if settings.mock_mode:
        from .mock_runtime import MOCK_MANIFESTS as raw
    else:
        from tools.constants import TOOL_MANIFESTS as raw
    return json.dumps(
        {
            "schema_version": "2.0",
            "server_version": "2.0.0",
            "sdk_family": "fastmcp",
            "sdk_version": "3.4.6",
            "supported_transports": ["stdio", "streamable-http"],
            "active_transport": settings.transport,
            "capabilities": list(normalize_catalog(raw).values()),
        },
        sort_keys=True,
    )
