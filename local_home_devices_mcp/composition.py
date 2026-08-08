"""FastMCP composition root with one canonical public-component policy kernel."""

from __future__ import annotations

import base64
import json
import logging
import time
from importlib.metadata import PackageNotFoundError, version
from typing import Any, Awaitable, Callable, Mapping, TypeVar

from .artifacts import ArtifactError, ArtifactStore
from .config import Settings, load_settings
from .http_boundary import HttpBoundaryMiddleware, set_wire_response_limit
from .legacy_compat import (
    LegacyRegistrationProxy,
    LegacyTargetResolver,
    LegacyToolFailure,
)
from .manifests import (
    MANIFEST_SCHEMA_VERSION,
    SERVER_HARD_MAX_RESPONSE_BYTES,
    ManifestError,
    is_runtime_active,
    manifest_timeout_seconds,
)
from .public_catalog import (
    PUBLIC_RESOURCE_COMPONENTS,
    build_public_catalog,
    component_kind,
)
from .mock_runtime import MockTargetResolver
from .policy import OperationGate, PolicyError, Principal, current_context
from .targeting import TargetError

T = TypeVar("T")
SUPPORTED_PROTOCOL_REVISIONS = ["2025-11-25"]
ADOPTION_PROFILES = [
    "mcp-server-architect@1.2.0",
    "python-fastmcp-package@1.2.0",
]


class PublicInvocationError(RuntimeError):
    """Safe error crossing a public MCP component boundary."""


def package_version() -> str:
    try:
        return version("local-home-devices-mcp")
    except PackageNotFoundError:
        return "2.0.0"


def _build_auth(settings: Settings) -> Any | None:
    if settings.transport == "stdio":
        return None
    if settings.has_jwt_auth:
        from fastmcp.server.auth.providers.jwt import JWTVerifier

        assert settings.jwt_jwks_uri is not None
        assert settings.jwt_issuer is not None
        assert settings.jwt_audience is not None
        return JWTVerifier(
            jwks_uri=settings.jwt_jwks_uri,
            issuer=settings.jwt_issuer,
            audience=settings.jwt_audience,
            required_scopes=[],
            ssrf_safe=True,
        )

    tokens = settings.static_tokens()
    if not tokens:
        raise ValueError("HTTP authentication provider is not configured")
    from fastmcp.server.auth.providers.jwt import StaticTokenVerifier

    return StaticTokenVerifier(tokens=tokens, required_scopes=[])


def _principal_from_fastmcp(settings: Settings) -> Principal:
    from fastmcp.server.dependencies import get_access_token

    try:
        token = get_access_token()
    except RuntimeError as exc:
        if settings.transport != "stdio":
            raise PolicyError("HTTP authentication context is unavailable") from exc
        token = None

    if token is None:
        if settings.transport == "stdio":
            return Principal(
                "trusted-local-process",
                frozenset({"devices:admin"}),
                "stdio",
            )
        raise PolicyError("HTTP authentication is required")

    claims = getattr(token, "claims", None) or {}
    subject = str(
        getattr(token, "client_id", None)
        or claims.get("sub")
        or claims.get("client_id")
        or "authenticated"
    )
    scopes = frozenset(
        str(item) for item in (getattr(token, "scopes", None) or [])
    )
    raw_targets = claims.get("targets")
    if raw_targets is None or raw_targets == "*":
        target_ids = None
    elif isinstance(raw_targets, str):
        target_ids = frozenset({raw_targets})
    else:
        target_ids = frozenset(str(item) for item in raw_targets)
    return Principal(subject, scopes, "http", target_ids)


def _component_manifest_name(component: Any, gate: OperationGate) -> str | None:
    """Map a FastMCP public component to the application-owned manifest identity."""
    name = getattr(component, "name", None)
    if isinstance(name, str) and name in gate.catalog:
        return name
    if name == "read_artifact" and "artifact_read" in gate.catalog:
        return "artifact_read"

    for attribute in ("uri", "uri_template"):
        value = getattr(component, attribute, None)
        if value is None:
            continue
        identity = str(value)
        mapped = PUBLIC_RESOURCE_COMPONENTS.get(identity)
        if mapped is not None and mapped in gate.catalog:
            return mapped
    return None


def _manifest_authorization_check(gate: OperationGate) -> Callable[[Any], bool]:
    """Filter discovery and direct access using canonical manifest scopes."""

    def authorize(context: Any) -> bool:
        token = getattr(context, "token", None)
        component = getattr(context, "component", None)
        if token is None or component is None:
            return False
        manifest_name = _component_manifest_name(component, gate)
        if manifest_name is None:
            return False
        manifest = gate.manifest(manifest_name)
        if not is_runtime_active(manifest):
            return False
        scopes = {str(item) for item in (getattr(token, "scopes", None) or [])}
        if "devices:admin" in scopes:
            return True
        required = {str(item) for item in manifest["authorization_scopes"]}
        return required.issubset(scopes)

    return authorize


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, bytes):
        return base64.b64encode(value).decode("ascii")
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list | tuple | set | frozenset):
        return [_jsonable(item) for item in value]
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        try:
            return _jsonable(model_dump(mode="json"))
        except TypeError:
            return _jsonable(model_dump())
    if hasattr(value, "__dict__"):
        return _jsonable(vars(value))
    return str(value)


def encoded_response_bytes(value: Any) -> int:
    encoded = json.dumps(
        _jsonable(value),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return len(encoded)


def effective_response_limit(
    manifest: Mapping[str, Any],
    settings: Settings,
) -> int:
    return min(
        SERVER_HARD_MAX_RESPONSE_BYTES,
        settings.max_response_bytes,
        int(manifest["max_response_bytes"]),
    )


async def _invoke_public_component(
    gate: OperationGate,
    settings: Settings,
    capability_name: str,
    arguments: Mapping[str, Any],
    principal: Principal,
    callback: Callable[[], Awaitable[T]],
) -> T:
    """Run every public MCP component through the same governance kernel."""
    manifest = gate.manifest(capability_name)
    maximum = effective_response_limit(manifest, settings)
    set_wire_response_limit(maximum)
    deadline = time.monotonic() + manifest_timeout_seconds(manifest)
    try:
        async with gate.guard_async(
            capability_name,
            arguments,
            principal,
            deadline=deadline,
        ):
            result = await callback()
            # This catches oversized application values before adapter serialization.
            # HttpBoundaryMiddleware independently enforces the actual final ASGI body.
            if encoded_response_bytes(result) > maximum:
                raise PublicInvocationError(
                    f"final response exceeds {maximum} bytes"
                )
            return result
    except TimeoutError as exc:
        raise PublicInvocationError(
            "operation deadline exceeded; mutation outcome may be unknown "
            "and requires reconciliation"
        ) from exc
    except LegacyToolFailure as exc:
        raise PublicInvocationError(f"{exc.code}: {exc}") from exc
    except PublicInvocationError:
        raise
    except (
        PolicyError,
        ManifestError,
        TargetError,
        ArtifactError,
    ) as exc:
        raise PublicInvocationError(str(exc)) from exc
    except Exception as exc:
        logging.getLogger(__name__).error(
            "public component failed for %s: %s",
            capability_name,
            type(exc).__name__,
        )
        raise PublicInvocationError("internal component failure") from exc


def _install_policy_middleware(
    mcp: Any,
    gate: OperationGate,
    settings: Settings,
) -> None:
    from fastmcp.exceptions import ToolError
    from fastmcp.server.middleware import AuthMiddleware, Middleware
    from tools.validators import ValidationError

    # FastMCP's AuthMiddleware filters list responses and independently rejects
    # unauthorized direct execution. It is skipped by FastMCP for stdio.
    mcp.add_middleware(AuthMiddleware(auth=_manifest_authorization_check(gate)))

    class InvocationPolicyMiddleware(Middleware):
        async def on_call_tool(self, context: Any, call_next: Any) -> Any:
            name = str(context.message.name)
            arguments = dict(context.message.arguments or {})
            principal = _principal_from_fastmcp(settings)

            async def callback() -> Any:
                try:
                    return await call_next(context)
                except ValidationError as exc:
                    raise PublicInvocationError(str(exc)) from exc

            try:
                return await _invoke_public_component(
                    gate,
                    settings,
                    name,
                    arguments,
                    principal,
                    callback,
                )
            except PublicInvocationError as exc:
                raise ToolError(str(exc)) from exc

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


def _register_mock_tools(mcp: Any, artifact_store: ArtifactStore) -> None:
    state = {"power": False, "brightness": 50}

    @mcp.tool
    def mock_get_state(identifier: str = "dev_mock_light") -> dict[str, Any]:
        return {"identifier": identifier, **state}

    @mcp.tool
    def mock_set_power(identifier: str, power: bool) -> dict[str, Any]:
        state["power"] = power
        return {"identifier": identifier, **state}

    @mcp.tool
    async def mock_wait(
        identifier: str = "dev_mock_light",
        delay_seconds: float = 1.0,
    ) -> dict[str, Any]:
        import asyncio

        if delay_seconds < 0 or delay_seconds > 5:
            raise ValueError("delay_seconds must be between 0 and 5")
        await asyncio.sleep(delay_seconds)
        return {"identifier": identifier, "waited_seconds": delay_seconds}

    @mcp.tool
    def mock_capture_snapshot(
        identifier: str = "dev_mock_light",
    ) -> dict[str, Any]:
        context = current_context()
        if context is None or context.target is None:
            raise ArtifactError(
                "artifact creation requires an authorized target context"
            )
        metadata = artifact_store.save(
            b"\x89PNG\r\n\x1a\nmock-device-snapshot",
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


def _register_artifact_resource(
    mcp: Any,
    artifact_store: ArtifactStore,
    gate: OperationGate,
    settings: Settings,
) -> None:
    @mcp.resource(
        "artifact://{artifact_id}",
        mime_type="application/octet-stream",
    )
    async def read_artifact(artifact_id: str) -> bytes:
        principal = _principal_from_fastmcp(settings)

        async def callback() -> bytes:
            _metadata, content = artifact_store.read(
                artifact_id,
                requester_subject=principal.subject,
                allow_admin="devices:admin" in principal.scopes,
            )
            return content

        try:
            return await _invoke_public_component(
                gate,
                settings,
                "artifact_read",
                {"artifact_id": artifact_id},
                principal,
                callback,
            )
        except PublicInvocationError as exc:
            raise ArtifactError(str(exc)) from exc


def build_server(
    settings: Settings | None = None,
) -> tuple[Any, OperationGate]:
    from fastmcp import FastMCP
    from starlette.responses import JSONResponse

    settings = settings or load_settings()
    if settings.mock_mode:
        from .mock_runtime import MOCK_MANIFESTS

        raw_tool_catalog = MOCK_MANIFESTS
        target_resolver = MockTargetResolver()
    else:
        from tools.constants import TOOL_MANIFESTS

        raw_tool_catalog = TOOL_MANIFESTS
        target_resolver = LegacyTargetResolver(settings)

    public_catalog = build_public_catalog(raw_tool_catalog)
    tool_catalog = {
        name: manifest
        for name, manifest in public_catalog.items()
        if component_kind(manifest) == "tool"
    }
    gate = OperationGate(
        settings,
        public_catalog,
        target_resolver=target_resolver,
    )
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
        stateless_http=True,
        json_response=True,
    )

    if settings.mock_mode:
        _register_mock_tools(mcp, artifact_store)
    else:
        from .legacy_compat import install_legacy_safety

        install_legacy_safety(settings)
        _register_legacy_tools(mcp)
    _register_artifact_resource(mcp, artifact_store, gate, settings)

    for name, manifest in tool_catalog.items():
        if not is_runtime_active(manifest):
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
                "auth_profile": settings.auth_profile,
                "mock_mode": settings.mock_mode,
            }
        )

    @mcp.custom_route("/ready", methods=["GET"])
    async def ready(_request: Any) -> JSONResponse:
        registered_tools = set(await mcp.get_tools())
        active_tools = {
            name
            for name, manifest in tool_catalog.items()
            if is_runtime_active(manifest)
        }
        unexpected_tools = sorted(registered_tools - set(tool_catalog))
        missing_tools = sorted(active_tools - registered_tools)

        templates_getter = getattr(mcp, "get_resource_templates", None)
        templates = await templates_getter() if callable(templates_getter) else {}
        registered_templates = {str(key) for key in templates}
        artifact_registered = any(
            "artifact://" in item for item in registered_templates
        )
        resource_ok = artifact_registered and "artifact_read" in gate.catalog
        status = (
            "ready"
            if not unexpected_tools and not missing_tools and resource_ok
            else "not-ready"
        )
        return JSONResponse(
            {
                "status": status,
                "registered_tools": len(registered_tools),
                "governed_components": len(gate.catalog),
                "unexpected_registered_tools": unexpected_tools,
                "missing_active_tools": missing_tools,
                "artifact_resource_governed": resource_ok,
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

    import uvicorn

    app = HttpBoundaryMiddleware(
        mcp.http_app(path=settings.mcp_path),
        settings,
    )
    uvicorn.run(
        app,
        host=settings.bind_host,
        port=settings.port,
        limit_concurrency=settings.http_max_connections,
        backlog=max(1, settings.http_queue_limit),
        h11_max_incomplete_event_size=settings.http_max_header_bytes,
    )


def capability_document(settings: Settings | None = None) -> str:
    settings = settings or load_settings()
    if settings.mock_mode:
        from .mock_runtime import MOCK_MANIFESTS as raw
    else:
        from tools.constants import TOOL_MANIFESTS as raw

    catalog = build_public_catalog(raw)
    return json.dumps(
        {
            "schema_version": MANIFEST_SCHEMA_VERSION,
            "server_version": package_version(),
            "sdk_family": "fastmcp",
            "sdk_version": "3.4.6",
            "profiles": ADOPTION_PROFILES,
            "protocol_revisions": SUPPORTED_PROTOCOL_REVISIONS,
            "supported_transports": ["stdio", "streamable-http"],
            "active_transport": settings.transport,
            "auth_profile": settings.auth_profile,
            "supported_count": len(catalog),
            "active_count": sum(
                1 for manifest in catalog.values() if is_runtime_active(manifest)
            ),
            "active_capability_ids": sorted(
                name
                for name, manifest in catalog.items()
                if is_runtime_active(manifest)
            ),
            "capabilities": list(catalog.values()),
        },
        sort_keys=True,
    )
