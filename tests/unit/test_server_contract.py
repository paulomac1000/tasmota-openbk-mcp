from __future__ import annotations

import ast
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit


def test_server_has_no_custom_json_rpc_or_legacy_sse():
    source = Path("server.py").read_text(encoding="utf-8")
    assert "/sse" not in source
    assert "/messages" not in source
    assert "/api/tools" not in source
    assert "_tool_manager" not in source
    assert 'transport="http"' not in source


def test_composition_uses_official_transports_and_bounded_http_app():
    source = Path("local_home_devices_mcp/composition.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    text = ast.unparse(tree)
    assert "mcp.run(transport='stdio')" in text
    assert "mcp.http_app(path=settings.mcp_path" in text
    assert "HttpBoundaryMiddleware" in text
    assert "uvicorn.run" in text
    assert "mcp.add_middleware" in text


def test_fastmcp_security_floor_and_v3_visibility_api():
    project = Path("pyproject.toml").read_text(encoding="utf-8")
    composition = Path("local_home_devices_mcp/composition.py").read_text(encoding="utf-8")
    assert '"fastmcp==3.4.6"' in project
    assert 'mcp.disable(keys={f"tool:{name}"})' in composition
    assert "AuthMiddleware" in composition
    assert "remove_tool(" not in composition
