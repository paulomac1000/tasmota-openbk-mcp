"""Transport contract tests for supported FastMCP entrypoints."""

from __future__ import annotations

import inspect

import pytest

from local_home_devices_mcp import composition
from local_home_devices_mcp.config import load_settings

pytestmark = pytest.mark.unit


def test_legacy_sse_is_rejected(monkeypatch):
    monkeypatch.setenv("MCP_TRANSPORT", "sse")
    with pytest.raises(ValueError, match="legacy SSE"):
        load_settings()


def test_composition_uses_only_public_component_visibility_api():
    source = inspect.getsource(composition)
    assert "_tool_manager" not in source
    assert "._tools" not in source
    assert 'mcp.disable(keys={f"tool:{name}"})' in source


def test_entrypoint_does_not_define_custom_json_rpc_or_rest_bridge():
    source = inspect.getsource(__import__("server"))
    assert "tools/call" not in source
    assert "/api/tools" not in source
    assert "create_rest_app" not in source


def test_http_anonymous_principal_is_read_only(monkeypatch):
    monkeypatch.setenv("MCP_TRANSPORT", "http")
    principal = composition._principal_from_fastmcp(load_settings())
    assert principal.scopes == frozenset({"devices:read"})


def test_stdio_process_principal_is_explicitly_trusted(monkeypatch):
    monkeypatch.setenv("MCP_TRANSPORT", "stdio")
    principal = composition._principal_from_fastmcp(load_settings())
    assert "devices:write" in principal.scopes
    assert principal.transport == "stdio"
