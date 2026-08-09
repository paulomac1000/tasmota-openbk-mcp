from __future__ import annotations

import os

import pytest

from local_home_devices_mcp.config import load_settings


def _clear_mcp_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in tuple(os.environ):
        if key.startswith("MCP_") or key in {
            "BIND_HOST",
            "ENABLE_WRITE_OPERATIONS",
            "ENABLE_DANGEROUS_OPERATIONS",
        }:
            monkeypatch.delenv(key, raising=False)


def test_safe_default_transport_is_stdio(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_mcp_env(monkeypatch)
    settings = load_settings()
    assert settings.transport == "stdio"
    assert settings.auth_profile == "stdio-local-process"


def test_http_requires_auth_even_on_loopback(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_mcp_env(monkeypatch)
    monkeypatch.setenv("MCP_TRANSPORT", "http")
    with pytest.raises(ValueError, match="HTTP transport requires"):
        load_settings()


def test_static_http_tokens_require_development_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_mcp_env(monkeypatch)
    monkeypatch.setenv("MCP_TRANSPORT", "http")
    monkeypatch.setenv("MCP_AUTH_READ_TOKEN", "r" * 32)
    with pytest.raises(ValueError, match="development/test only"):
        load_settings()
    monkeypatch.setenv("MCP_HTTP_DEVELOPMENT_MODE", "1")
    assert load_settings().auth_profile == "static-development"


def test_production_jwt_profile_requires_complete_triple(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_mcp_env(monkeypatch)
    monkeypatch.setenv("MCP_TRANSPORT", "http")
    monkeypatch.setenv("MCP_AUTH_JWT_JWKS_URI", "https://auth.example/jwks.json")
    with pytest.raises(ValueError, match="configured together"):
        load_settings()
    monkeypatch.setenv("MCP_AUTH_JWT_ISSUER", "https://auth.example")
    monkeypatch.setenv("MCP_AUTH_JWT_AUDIENCE", "local-home-devices-mcp")
    assert load_settings().auth_profile == "jwt-jwks"


def test_http_host_and_origin_policy_is_exact(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_mcp_env(monkeypatch)
    monkeypatch.setenv("MCP_TRANSPORT", "http")
    monkeypatch.setenv("MCP_AUTH_READ_TOKEN", "r" * 32)
    monkeypatch.setenv("MCP_HTTP_DEVELOPMENT_MODE", "1")
    monkeypatch.setenv("MCP_ALLOWED_HOSTS", "*")
    with pytest.raises(ValueError, match="wildcard"):
        load_settings()
