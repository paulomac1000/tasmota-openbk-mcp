from __future__ import annotations

import pytest

from local_home_devices_mcp.config import load_settings

pytestmark = pytest.mark.unit


def test_default_transport_is_streamable_http_alias_http():
    assert load_settings().transport == "http"


def test_legacy_sse_is_rejected(monkeypatch):
    monkeypatch.setenv("MCP_TRANSPORT", "sse")
    with pytest.raises(ValueError, match="legacy SSE"):
        load_settings()


def test_public_bind_requires_auth(monkeypatch):
    monkeypatch.setenv("BIND_HOST", "0.0.0.0")
    with pytest.raises(ValueError, match="MCP_AUTH_TOKEN"):
        load_settings()


def test_public_bind_with_token_is_valid(monkeypatch):
    monkeypatch.setenv("BIND_HOST", "0.0.0.0")
    monkeypatch.setenv("MCP_AUTH_TOKEN", "t" * 32)
    assert load_settings().auth_token == "t" * 32


def test_artifact_root_cannot_be_root(monkeypatch):
    monkeypatch.setenv("MCP_ARTIFACT_ROOT", "/")
    with pytest.raises(ValueError, match="filesystem root"):
        load_settings()


def test_short_auth_token_is_rejected(monkeypatch):
    monkeypatch.setenv("MCP_AUTH_TOKEN", "short")
    with pytest.raises(ValueError, match="at least 32"):
        load_settings()


def test_external_auth_environment_does_not_bypass_missing_provider(monkeypatch):
    monkeypatch.setenv("BIND_HOST", "0.0.0.0")
    monkeypatch.setenv("FASTMCP_SERVER_AUTH", "https://issuer.invalid")
    with pytest.raises(ValueError, match="MCP_AUTH_TOKEN"):
        load_settings()
