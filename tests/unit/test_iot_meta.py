"""Capability discovery must expose supported and active catalogs."""

from __future__ import annotations

import json

import pytest

pytest.importorskip("tools.constants")
from tools.iot_meta import _describe_capabilities, register_iot_meta_tools

pytestmark = pytest.mark.unit


def test_capability_document_is_complete(monkeypatch):
    monkeypatch.setenv("MCP_TRANSPORT", "stdio")
    data = json.loads(_describe_capabilities())
    payload = data["data"]
    assert data["success"] is True
    assert payload["server"] == "local-home-devices-mcp"
    assert payload["supported_transports"] == ["stdio", "streamable-http"]
    assert payload["supported_count"] == len(payload["supported_capabilities"])
    assert payload["active_count"] == len(payload["active_capabilities"])
    required = {
        "name",
        "version",
        "risk",
        "side_effects",
        "confidentiality",
        "idempotent",
        "idempotency_mechanism",
        "retryable",
        "retry_conditions",
        "concurrent_safe",
        "concurrency_scope",
        "timeout_ms",
        "requires_confirmation",
        "determinism",
        "latency",
        "cost",
        "impact",
        "reversible",
        "target_binding",
        "active_state",
    }
    for manifest in payload["supported_capabilities"]:
        assert not required - set(manifest)
    assert all(item["active_state"] == "active" for item in payload["active_capabilities"])


def test_registration_creates_protocol_visible_tool():
    class FakeMCP:
        def __init__(self):
            self.tools = {}

        def tool(self):
            def register(function):
                self.tools[function.__name__] = function
                return function

            return register

    mcp = FakeMCP()
    register_iot_meta_tools(mcp)
    assert set(mcp.tools) == {"describe_iot_capabilities"}
    assert json.loads(mcp.tools["describe_iot_capabilities"]())["success"] is True
