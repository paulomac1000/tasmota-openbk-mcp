from __future__ import annotations

import os

import pytest

from local_home_devices_mcp.config import load_settings

pytestmark = pytest.mark.unit


def _clear_mcp_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in tuple(os.environ):
        if key.startswith("MCP_") or key in {
            "BIND_HOST",
            "ENABLE_WRITE_OPERATIONS",
            "ENABLE_DANGEROUS_OPERATIONS",
        }:
            monkeypatch.delenv(key, raising=False)


def test_default_transport_is_stdio(monkeypatch: pytest.MonkeyPatch):
    _clear_mcp_env(monkeypatch)
    assert load_settings().transport == "stdio"


def test_legacy_sse_is_rejected(monkeypatch: pytest.MonkeyPatch):
    _clear_mcp_env(monkeypatch)
    monkeypatch.setenv("MCP_TRANSPORT", "sse")
    with pytest.raises(ValueError, match="legacy SSE"):
        load_settings()


def test_loopback_http_requires_auth(monkeypatch: pytest.MonkeyPatch):
    _clear_mcp_env(monkeypatch)
    monkeypatch.setenv("MCP_TRANSPORT", "http")
    with pytest.raises(ValueError, match="HTTP transport requires"):
        load_settings()


def test_public_http_requires_production_auth_and_trusted_tls(monkeypatch: pytest.MonkeyPatch):
    _clear_mcp_env(monkeypatch)
    monkeypatch.setenv("MCP_TRANSPORT", "http")
    monkeypatch.setenv("BIND_HOST", "0.0.0.0")
    monkeypatch.setenv("MCP_AUTH_JWT_JWKS_URI", "https://auth.example/jwks.json")
    monkeypatch.setenv("MCP_AUTH_JWT_ISSUER", "https://auth.example")
    monkeypatch.setenv("MCP_AUTH_JWT_AUDIENCE", "local-home-devices-mcp")
    with pytest.raises(ValueError, match="MCP_TRUSTED_PROXY_TLS"):
        load_settings()
    monkeypatch.setenv("MCP_TRUSTED_PROXY_TLS", "1")
    assert load_settings().auth_profile == "jwt-jwks"


def test_static_http_token_is_development_only(monkeypatch: pytest.MonkeyPatch):
    _clear_mcp_env(monkeypatch)
    monkeypatch.setenv("MCP_TRANSPORT", "http")
    monkeypatch.setenv("MCP_AUTH_TOKEN", "t" * 32)
    with pytest.raises(ValueError, match="development/test only"):
        load_settings()
    monkeypatch.setenv("MCP_HTTP_DEVELOPMENT_MODE", "1")
    assert load_settings().auth_token == "t" * 32


def test_artifact_root_cannot_be_root(monkeypatch: pytest.MonkeyPatch):
    _clear_mcp_env(monkeypatch)
    monkeypatch.setenv("MCP_ARTIFACT_ROOT", "/")
    with pytest.raises(ValueError, match="filesystem root"):
        load_settings()


def test_short_auth_token_is_rejected(monkeypatch: pytest.MonkeyPatch):
    _clear_mcp_env(monkeypatch)
    monkeypatch.setenv("MCP_AUTH_TOKEN", "short")
    with pytest.raises(ValueError, match="at least 32"):
        load_settings()


def test_external_auth_environment_does_not_bypass_missing_provider(
    monkeypatch: pytest.MonkeyPatch,
):
    _clear_mcp_env(monkeypatch)
    monkeypatch.setenv("MCP_TRANSPORT", "http")
    monkeypatch.setenv("FASTMCP_SERVER_AUTH", "https://issuer.invalid")
    with pytest.raises(ValueError, match="HTTP transport requires"):
        load_settings()


def test_http_queue_and_ingress_deadlines_are_configurable(monkeypatch: pytest.MonkeyPatch):
    _clear_mcp_env(monkeypatch)
    monkeypatch.setenv("MCP_HTTP_QUEUE_WAIT_MS", "250")
    monkeypatch.setenv("MCP_HTTP_INGRESS_TIMEOUT_MS", "1500")
    config = load_settings()
    assert config.http_queue_wait_ms == 250
    assert config.http_ingress_timeout_ms == 1500
