from __future__ import annotations

import ipaddress
import json
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

from local_home_devices_mcp.config import Settings
from local_home_devices_mcp.policy import PolicyError, Principal

pytestmark = pytest.mark.unit


class FakeToolError(RuntimeError):
    pass


class FakeMiddleware:
    pass


class FakeAuthMiddleware:
    def __init__(self, *, auth: Any) -> None:
        self.auth = auth


class FakeStaticTokenVerifier:
    def __init__(self, *, tokens: dict[str, Any], required_scopes: list[str]) -> None:
        self.tokens = tokens
        self.required_scopes = required_scopes


class FakeJWTVerifier:
    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs


class FakeFastMCP:
    last: FakeFastMCP | None = None

    def __init__(
        self,
        *,
        name: str,
        version: str,
        auth: Any = None,
    ) -> None:
        self.name = name
        self.version = version
        self.auth = auth
        self.tools: dict[str, Any] = {}
        self.resources: dict[str, Any] = {}
        self.routes: dict[str, Any] = {}
        self.middlewares: list[Any] = []
        self.disabled: set[str] = set()
        self.run_calls: list[dict[str, Any]] = []
        self.http_app_calls: list[dict[str, Any]] = []
        FakeFastMCP.last = self

    def tool(self, function: Any = None, **_kwargs: Any) -> Any:
        def register(candidate: Any) -> Any:
            self.tools[candidate.__name__] = candidate
            return candidate

        return register(function) if callable(function) else register

    def resource(self, uri: str, **_kwargs: Any) -> Any:
        def register(candidate: Any) -> Any:
            self.resources[uri] = candidate
            return candidate

        return register

    def custom_route(self, path: str, **_kwargs: Any) -> Any:
        def register(candidate: Any) -> Any:
            self.routes[path] = candidate
            return candidate

        return register

    def add_middleware(self, middleware: Any) -> None:
        self.middlewares.append(middleware)

    def disable(self, *, keys: set[str]) -> None:
        self.disabled.update(keys)

    async def list_tools(self, **_: Any) -> list[Any]:
        from types import SimpleNamespace

        return [
            SimpleNamespace(name=name) for name in self.tools if f"tool:{name}" not in self.disabled
        ]

    async def list_resource_templates(self, **_: Any) -> list[Any]:
        from types import SimpleNamespace

        return [SimpleNamespace(uriTemplate=uri) for uri in self.resources]

    def http_app(self, **kwargs: Any) -> Any:
        self.http_app_calls.append(kwargs)
        return SimpleNamespace(path=kwargs.get("path"))

    def run(self, **kwargs: Any) -> None:
        self.run_calls.append(kwargs)


@pytest.fixture
def fake_fastmcp(monkeypatch: pytest.MonkeyPatch):
    access_token: dict[str, Any] = {"value": None}
    modules: dict[str, ModuleType] = {}
    for name in (
        "fastmcp",
        "fastmcp.exceptions",
        "fastmcp.server",
        "fastmcp.server.middleware",
        "fastmcp.server.auth",
        "fastmcp.server.auth.providers",
        "fastmcp.server.auth.providers.jwt",
        "fastmcp.server.dependencies",
    ):
        modules[name] = ModuleType(name)
        monkeypatch.setitem(sys.modules, name, modules[name])

    modules["fastmcp"].FastMCP = FakeFastMCP  # type: ignore[attr-defined]
    modules["fastmcp.exceptions"].ToolError = FakeToolError  # type: ignore[attr-defined]
    modules["fastmcp.server.middleware"].Middleware = FakeMiddleware  # type: ignore[attr-defined]
    modules["fastmcp.server.middleware"].AuthMiddleware = FakeAuthMiddleware  # type: ignore[attr-defined]
    jwt_module = modules["fastmcp.server.auth.providers.jwt"]
    jwt_module.StaticTokenVerifier = FakeStaticTokenVerifier  # type: ignore[attr-defined]
    jwt_module.JWTVerifier = FakeJWTVerifier  # type: ignore[attr-defined]
    modules["fastmcp.server.dependencies"].get_access_token = (  # type: ignore[attr-defined]
        lambda: access_token["value"]
    )
    return access_token


def settings(tmp_path: Path, **overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "transport": "stdio",
        "bind_host": "127.0.0.1",
        "port": 9102,
        "mcp_path": "/mcp",
        "write_enabled": True,
        "dangerous_enabled": False,
        "allow_direct_ip_targets": False,
        "allowed_networks": (ipaddress.ip_network("192.0.2.0/24"),),
        "artifact_root": tmp_path / "artifacts",
        "max_artifact_bytes": 1024,
        "max_artifact_store_bytes": 4096,
        "artifact_retention_seconds": 3600,
        "read_token": None,
        "write_token": None,
        "admin_token": None,
        "trusted_proxy_tls": False,
        "mock_mode": True,
        "http_development_mode": True,
    }
    values.update(overrides)
    return Settings(**values)


def test_auth_and_principal_roles(tmp_path: Path, fake_fastmcp: dict[str, Any]) -> None:
    from local_home_devices_mcp.composition import _build_auth, _principal_from_fastmcp

    stdio = settings(tmp_path)
    assert _build_auth(stdio) is None
    assert _principal_from_fastmcp(stdio) == Principal(
        "trusted-local-process", frozenset({"devices:admin"}), "stdio"
    )

    http = settings(tmp_path, transport="http", read_token="r" * 32)
    verifier = _build_auth(http)
    assert verifier.required_scopes == []
    assert verifier.tokens["r" * 32]["scopes"] == ["devices:read"]
    with pytest.raises(PolicyError, match="authentication is required"):
        _principal_from_fastmcp(http)

    fake_fastmcp["value"] = SimpleNamespace(
        client_id="reader",
        scopes=["devices:read"],
        claims={"targets": ["dev_mock_light"]},
    )
    assert _principal_from_fastmcp(http) == Principal(
        "reader",
        frozenset({"devices:read"}),
        "http",
        target_ids=frozenset({"dev_mock_light"}),
    )


def test_jwt_auth_uses_reviewed_jwks_verifier(tmp_path: Path, fake_fastmcp: dict[str, Any]) -> None:
    from local_home_devices_mcp.composition import _build_auth

    config = settings(
        tmp_path,
        transport="http",
        jwt_jwks_uri="https://auth.example/jwks.json",
        jwt_issuer="https://auth.example",
        jwt_audience="local-home-devices-mcp",
    )
    verifier = _build_auth(config)
    assert verifier.kwargs["jwks_uri"] == "https://auth.example/jwks.json"
    assert verifier.kwargs["ssrf_safe"] is True


@pytest.mark.asyncio
async def test_mock_server_registration_routes_artifact_and_middleware(
    tmp_path: Path, fake_fastmcp: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    from local_home_devices_mcp.composition import build_server

    _server, gate = build_server(settings(tmp_path))
    mcp = FakeFastMCP.last
    assert mcp is not None
    assert set(mcp.tools) == {
        "mock_get_state",
        "mock_set_power",
        "mock_capture_snapshot",
        "mock_wait",
    }
    assert "artifact://{artifact_id}" in mcp.resources
    assert len(mcp.middlewares) == 2
    assert isinstance(mcp.middlewares[0], FakeAuthMiddleware)

    from local_home_devices_mcp.composition import run

    monkeypatch.setattr("uvicorn.run", lambda app, **_kwargs: None)
    run(settings(tmp_path, transport="http", read_token="r" * 32))
    http_kwargs = FakeFastMCP.last.http_app_calls[0]
    assert http_kwargs["stateless_http"] is True
    assert http_kwargs["json_response"] is True
    assert http_kwargs["path"] == "/mcp"

    principal = Principal("alice", frozenset({"devices:admin"}), "stdio")
    artifact = await gate.invoke_async(
        "mock_capture_snapshot",
        mcp.tools["mock_capture_snapshot"],
        {"identifier": "Mock Light"},
        principal,
    )
    fake_fastmcp["value"] = SimpleNamespace(client_id="alice", scopes=["devices:admin"], claims={})
    content = await mcp.resources["artifact://{artifact_id}"](artifact["artifact_id"])
    assert content.startswith(b"\x89PNG")

    health = await mcp.routes["/health"](None)
    assert health.status_code == 200
    ready = await mcp.routes["/ready"](None)
    assert ready.status_code == 200


@pytest.mark.asyncio
async def test_capability_response_limit_is_enforced_at_mcp_boundary(
    tmp_path: Path, fake_fastmcp: dict[str, Any]
) -> None:
    from local_home_devices_mcp.composition import build_server

    build_server(settings(tmp_path))
    mcp = FakeFastMCP.last
    assert mcp is not None
    context = SimpleNamespace(
        message=SimpleNamespace(name="mock_get_state", arguments={"identifier": "dev_mock_light"})
    )

    async def call_next(_context: Any) -> dict[str, str]:
        return {"value": "x" * (40 * 1024)}

    invocation = mcp.middlewares[1]
    with pytest.raises(FakeToolError, match="final response exceeds 32768 bytes"):
        await invocation.on_call_tool(context, call_next)


@pytest.mark.asyncio
async def test_artifact_resource_rejects_read_scope(
    tmp_path: Path, fake_fastmcp: dict[str, Any]
) -> None:
    from local_home_devices_mcp.artifacts import ArtifactError
    from local_home_devices_mcp.composition import build_server

    build_server(settings(tmp_path))
    mcp = FakeFastMCP.last
    assert mcp is not None
    fake_fastmcp["value"] = SimpleNamespace(client_id="reader", scopes=["devices:read"], claims={})
    with pytest.raises(ArtifactError, match="sensitive"):
        await mcp.resources["artifact://{artifact_id}"]("art_" + "a" * 32)


def test_manifest_authorization_filters_read_only_principal(
    tmp_path: Path, fake_fastmcp: dict[str, Any]
) -> None:
    from local_home_devices_mcp.composition import _manifest_authorization_check, build_server

    _server, gate = build_server(settings(tmp_path, transport="http", read_token="r" * 32))
    check = _manifest_authorization_check(gate)
    token = SimpleNamespace(scopes=["devices:read"])
    assert check(SimpleNamespace(token=token, component=SimpleNamespace(name="mock_get_state")))
    assert not check(SimpleNamespace(token=token, component=SimpleNamespace(name="mock_set_power")))
    assert not check(SimpleNamespace(token=token, component=SimpleNamespace(name="unknown")))


def test_capability_document_is_zero_io(tmp_path: Path) -> None:
    from local_home_devices_mcp.composition import capability_document

    payload = json.loads(capability_document(settings(tmp_path)))
    assert payload["schema_version"] == 1
    assert payload["sdk_version"] == "3.4.6"
    assert payload["protocol_revisions"] == ["2025-11-25"]
    assert {item["name"] for item in payload["capabilities"]} == {
        "mock_get_state",
        "mock_set_power",
        "mock_capture_snapshot",
        "mock_wait",
        "artifact_read",
    }


@pytest.mark.asyncio
async def test_readiness_rejects_missing_active_and_unexpected_tools(
    tmp_path: Path, fake_fastmcp: dict[str, Any]
) -> None:
    from local_home_devices_mcp.composition import build_server

    build_server(settings(tmp_path))
    mcp = FakeFastMCP.last
    assert mcp is not None

    missing = mcp.tools.pop("mock_get_state")
    payload = json.loads((await mcp.routes["/ready"](None)).body)
    assert payload["missing_active_tools"] == ["mock_get_state"]
    assert payload["unexpected_registered_tools"] == []

    mcp.tools["mock_get_state"] = missing
    mcp.tools["unclassified_tool"] = lambda: None
    payload = json.loads((await mcp.routes["/ready"](None)).body)
    assert payload["missing_active_tools"] == []
    assert payload["unexpected_registered_tools"] == ["unclassified_tool"]
