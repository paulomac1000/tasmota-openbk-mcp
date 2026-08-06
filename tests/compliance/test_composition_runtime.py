from __future__ import annotations

import ipaddress
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

from local_home_devices_mcp.config import Settings
from local_home_devices_mcp.policy import Principal

pytestmark = pytest.mark.unit


class FakeToolError(RuntimeError):
    pass


class FakeMiddleware:
    pass


class FakeStaticTokenVerifier:
    def __init__(self, *, tokens: dict[str, Any], required_scopes: list[str]) -> None:
        self.tokens = tokens
        self.required_scopes = required_scopes


class FakeFastMCP:
    last: "FakeFastMCP | None" = None

    def __init__(self, *, name: str, version: str, auth: Any = None) -> None:
        self.name = name
        self.version = version
        self.auth = auth
        self.tools: dict[str, Any] = {}
        self.resources: dict[str, Any] = {}
        self.routes: dict[str, Any] = {}
        self.middlewares: list[Any] = []
        self.disabled: set[str] = set()
        self.run_calls: list[dict[str, Any]] = []
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

    async def get_tools(self) -> dict[str, Any]:
        return {
            name: function
            for name, function in self.tools.items()
            if f"tool:{name}" not in self.disabled
        }

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
    jwt_module = modules["fastmcp.server.auth.providers.jwt"]
    jwt_module.StaticTokenVerifier = (  # type: ignore[attr-defined]
        FakeStaticTokenVerifier
    )
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
    }
    values.update(overrides)
    return Settings(**values)


def test_auth_and_principal_roles(
    tmp_path: Path, fake_fastmcp: dict[str, Any]
) -> None:
    from local_home_devices_mcp.composition import _build_auth, _principal_from_fastmcp

    stdio = settings(tmp_path)
    assert _build_auth(stdio) is None
    assert _principal_from_fastmcp(stdio) == Principal(
        "trusted-local-process", frozenset({"devices:admin"}), "stdio"
    )

    http = settings(
        tmp_path,
        transport="http",
        read_token="r" * 32,
        write_token="w" * 32,
        admin_token="a" * 32,
    )
    verifier = _build_auth(http)
    assert verifier.required_scopes == ["devices:read"]
    assert verifier.tokens["r" * 32]["scopes"] == ["devices:read"]
    assert _principal_from_fastmcp(http).subject == "anonymous-loopback-http"

    fake_fastmcp["value"] = SimpleNamespace(
        client_id="reader",
        scopes=["devices:read"],
        claims={"sub": "ignored", "targets": ["dev_mock_light"]},
    )
    principal = _principal_from_fastmcp(http)
    assert principal == Principal(
        "reader",
        frozenset({"devices:read"}),
        "http",
        target_ids=frozenset({"dev_mock_light"}),
    )


@pytest.mark.asyncio
async def test_mock_server_registration_routes_artifact_and_middleware(
    tmp_path: Path, fake_fastmcp: dict[str, Any]
) -> None:
    from local_home_devices_mcp.composition import build_server

    config = settings(tmp_path)
    _server, gate = build_server(config)
    mcp = FakeFastMCP.last
    assert mcp is not None
    assert set(mcp.tools) == {
        "mock_get_state",
        "mock_set_power",
        "mock_capture_snapshot",
    }
    assert "artifact://{artifact_id}" in mcp.resources
    assert len(mcp.middlewares) == 1

    principal = Principal("alice", frozenset({"devices:admin"}), "stdio")
    artifact = await gate.invoke_async(
        "mock_capture_snapshot",
        mcp.tools["mock_capture_snapshot"],
        {"identifier": "Mock Light"},
        principal,
    )
    assert artifact["uri"].startswith("artifact://art_")

    fake_fastmcp["value"] = SimpleNamespace(
        client_id="alice", scopes=["devices:admin"], claims={}
    )
    artifact_id = artifact["artifact_id"]
    content = mcp.resources["artifact://{artifact_id}"](artifact_id)
    assert content.startswith(b"\x89PNG")

    health = await mcp.routes["/health"](None)
    assert health.status_code == 200
    assert b'"mock_mode":true' in health.body
    ready = await mcp.routes["/ready"](None)
    assert ready.status_code == 200

    context = SimpleNamespace(
        message=SimpleNamespace(
            name="mock_get_state", arguments={"identifier": "dev_mock_light"}
        )
    )

    async def call_next(_context: Any) -> dict[str, bool]:
        return {"ok": True}

    result = await mcp.middlewares[0].on_call_tool(context, call_next)
    assert result == {"ok": True}


@pytest.mark.asyncio
async def test_artifact_resource_rejects_read_scope(
    tmp_path: Path, fake_fastmcp: dict[str, Any]
) -> None:
    from local_home_devices_mcp.artifacts import ArtifactError
    from local_home_devices_mcp.composition import build_server

    build_server(settings(tmp_path))
    mcp = FakeFastMCP.last
    assert mcp is not None
    fake_fastmcp["value"] = SimpleNamespace(
        client_id="reader", scopes=["devices:read"], claims={}
    )
    with pytest.raises(ArtifactError, match="sensitive"):
        mcp.resources["artifact://{artifact_id}"]("art_" + "a" * 32)


def test_run_selects_stdio_and_http(
    tmp_path: Path, fake_fastmcp: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    from local_home_devices_mcp import composition

    composition.run(settings(tmp_path, transport="stdio"))
    assert FakeFastMCP.last is not None
    assert FakeFastMCP.last.run_calls[-1] == {"transport": "stdio"}

    composition.run(settings(tmp_path, transport="http", port=9123, mcp_path="/rpc"))
    assert FakeFastMCP.last is not None
    assert FakeFastMCP.last.run_calls[-1] == {
        "transport": "http",
        "host": "127.0.0.1",
        "port": 9123,
        "path": "/rpc",
    }

    monkeypatch.setattr(composition, "version", lambda _name: "9.8.7")
    assert composition.package_version() == "9.8.7"


def test_capability_document_is_zero_io(tmp_path: Path) -> None:
    import json

    from local_home_devices_mcp.composition import capability_document

    payload = json.loads(capability_document(settings(tmp_path)))
    assert payload["sdk_version"] == "3.4.4"
    assert payload["active_transport"] == "stdio"
    assert {item["name"] for item in payload["capabilities"]} == {
        "mock_get_state",
        "mock_set_power",
        "mock_capture_snapshot",
    }
