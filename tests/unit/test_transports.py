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


def test_composition_uses_official_transports_and_async_gate():
    source = Path("local_home_devices_mcp/composition.py").read_text(encoding="utf-8")
    text = ast.unparse(ast.parse(source))
    assert "mcp.run(transport='stdio')" in text
    assert "mcp.http_app(" in text
    assert "gate.guard_async" in text
    assert "mcp.add_middleware" in text


def test_real_transport_tests_use_subprocess_and_streamable_http():
    source = Path("tests/compliance/test_real_transports.py").read_text(encoding="utf-8")
    assert "stdio_client(params)" in source
    assert "subprocess.Popen" in source
    assert "streamable_http_client" in source
    assert "ClientSession" in source
