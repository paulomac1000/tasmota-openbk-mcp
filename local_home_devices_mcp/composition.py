"""FastMCP composition root with one policy pipeline for every transport."""

from __future__ import annotations

import asyncio
import json
import logging
from importlib.metadata import PackageNotFoundError, version
from typing import Any

from .artifacts import ArtifactError, ArtifactStore
from .config import Settings, load_settings
from .legacy_compat import LegacyRegistrationProxy, LegacyTargetResolver, LegacyToolFailure
from .manifests import ManifestError, normalize_catalog
from .mock_runtime import MockTargetResolver
from .policy import OperationGate, PolicyError, Principal, current_context
from .targeting import TargetError


def package_version() -> str:
    try:
        return version("local-home-devices-mcp")
    except PackageNotFoundError:
        return "2.0.0"


def _build_auth(settings: Settings) -> Any | None:
    tokens = settings.static_tokens()
    if not tokens:
        return None
    from fastmcp.server.auth.providers.jwt import StaticTokenVerifier

    return StaticTokenVerifier(tokens=tokens, required_scopes=["devices:read"])


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
                scopes=frozenset({"devices:admin"}),
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
                async with gate.guard_async(name, arguments, principal):
                    async with asyncio.timeout(manifest["timeout_ms"] / 1000):
                        return await call_next(context)
            except TimeoutError as exc:
                raise ToolError(
                    "operation deadline exceeded; mutation outcome may require reconciliation"
                ) from exc
            except LegacyToolFailure as exc:
                raise ToolError(f"{exc.code}: {exc}") from exc
            except ToolError:
                raise
            except (PolicyError, ManifestError, TargetError, ValidationError, ArtifactError) as exc:
                raise ToolError(str(exc)) from exc
            except Exception as exc:
                logging.getLogger(__name__).error(
                    "tool invocation failed for %s: %s", name, type(exc).__name__
                )
                raise ToolError("internal tool failure") from exc

    mcp.add_middleware(InvocationPolicyMiddleware())


def _register_legacy_tools(mcp: Any) -> None:
    from tools.iot_config import register_iot_config_tools
    from tools.iot_control import register_iot_control_tools
    from tools.iot_devices import register_iot_device_tools
    from tools.iot_discovery import register_iot_discovery_tools
    from tools.iot_hikvision import register_hikvision_tools
    from tools.iot_meta import register_iot_meta_tools
    from tools.iot_mqtt import register_iot_mqtt_tools
    from tools.iot_openhasp import register_openhasp_tools
    from tools.iot_tuya import register_iot_tuya_tools

    proxy = LegacyRegistrationProxy(mcp)
    register_iot_device_tools(proxy)
    register_iot_discovery_tools(proxy)
    register_iot_control_tools(proxy)
    register_iot_config_tools(proxy)
    register_iot_mqtt_tools(proxy)
    register_iot_meta_tools(proxy)
    register_iot_tuya_tools(proxy)
    register_openhasp_tools(proxy)
    register_hikvision_tools(proxy)


def _register_mock_tools(
    mcp: Any, artifact_store: ArtifactStore, settings: Settings
) -> None:
    state = {"power": False, "brightness": 50}

    @mcp.tool
    def mock_get_state(identifier: str = "dev_mock_light") -> dict[str, Any]:
        """Return deterministic state from the zero-I/O mock device."""
        return {"identifier": identifier, **state}

    @mcp.tool
    def mock_set_power(identifier: str, power: bool) -> dict[str, Any]:
        """Set power explicitly on the zero-I/O mock device."""
        state["power"] = power
        return {"identifier": identifier, **state}

    @mcp.tool
    def mock_capture_snapshot(identifier: str = "dev_mock_light") -> dict[str, Any]:
        """Persist a deterministic mock image through the confined artifact store."""
        payload = b"\x89PNG\r\n\x1a\nmock-device-snapshot"
        context = current_context()
        if context is None or context.target is None:
            raise ArtifactError("artifact creation requires an authorized target context")
        metadata = artifact_store.save(
            payload,
            "image/png",
            owner_subject=context.principal.subject,
            target_id=context.target.target_id,
            operation="mock_capture_snapshot",
        )
        return {
            "identifier": identifier,
            "artifact_id": metadata.artifact_id,
            "uri": f"artifact://{metadata.artifact_id}",
            "media_type": metadata.media_type,
            "size": metadata.size,
            "sha256": metadata.sha256,
            "expires_at": metadata.expires_at,
        }

    @mcp.resource("artifact://{artifact_id}", mime_type="application/octet-stream")
    def read_artifact(artifact_id: str) -> bytes:
        """Read one integrity-checked artifact by opaque ID."""
        principal = _principal_from_fastmcp(settings)
        if not ({"devices:sensitive", "devices:admin"} & principal.scopes):
            raise ArtifactError("missing required scope: devices:sensitive")
        _metadata, content = artifact_store.read(
            artifact_id,
            requester_subject=principal.subject,
            allow_admin="devices:admin" in principal.scopes,
        )
        return content


def build_server(settings: Settings | None = None) -> tuple[Any, OperationGate]:
    """Build a server without starting a transport or performing device I/O."""
    from fastmcp import FastMCP
    from starlette.responses import JSONResponse

    settings = settings or load_settings()
    if settings.mock_mode:
        from .mock_runtime import MOCK_MANIFESTS

        raw_catalog = MOCK_MANIFESTS
        target_resolver = MockTargetResolver()
    else:
        from tools.constants import TOOL_MANIFESTS

        raw_catalog = TOOL_MANIFESTS
        target_resolver = LegacyTargetResolver(settings)

    catalog = normalize_catalog(raw_catalog)
    gate = OperationGate(settings, catalog, target_resolver=target_resolver)
    artifact_store = ArtifactStore(
        settings.artifact_root,
        max_artifact_bytes=settings.max_artifact_bytes,
        max_store_bytes=settings.max_artifact_store_bytes,
        retention_seconds=settings.artifact_retention_seconds,
    )
    mcp = FastMCP(
        name="Local Home Devices",
        version=package_version(),
        auth=_build_auth(settings),
    )
    if settings.mock_mode:
        _register_mock_tools(mcp, artifact_store, settings)
    else:
        from .legacy_compat import install_legacy_safety

        install_legacy_safety(settings)
        _register_legacy_tools(mcp)

    for name, manifest in catalog.items():
        if manifest["active_state"] != "active":
            mcp.disable(keys={f"tool:{name}"})
    _install_policy_middleware(mcp, gate, settings)

    @mcp.custom_route("/health", methods=["GET"])
    async def health(_request: Any) -> JSONResponse:
        return JSONResponse(
            {
                "status": "healthy",
                "service": "local-home-devices-mcp",
                "version": package_version(),
                "transport": settings.transport,
                "mock_mode": settings.mock_mode,
            }
        )

    @mcp.custom_route("/ready", methods=["GET"])
    async def ready(_request: Any) -> JSONResponse:
        registered = set(await mcp.get_tools())
        governed = set(catalog)
        missing = sorted(registered - governed)
        status = "ready" if not missing else "not-ready"
        return JSONResponse(
            {
                "status": status,
                "registered": len(registered),
                "governed": len(governed),
                "missing_manifests": missing,
                "inactive_or_optional": sorted(governed - registered),
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
            "schema_version": "2.1",
            "server_version": package_version(),
            "sdk_family": "fastmcp",
            "sdk_version": "3.4.4",
            "supported_transports": ["stdio", "streamable-http"],
            "active_transport": settings.transport,
            "capabilities": list(normalize_catalog(raw).values()),
        },
        sort_keys=True,
    )
