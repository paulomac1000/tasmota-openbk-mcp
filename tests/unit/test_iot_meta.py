"""Unit tests for canonical capability introspection."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from tools.iot_meta import _describe_capabilities, register_iot_meta_tools

pytestmark = pytest.mark.unit


def test_describe_returns_full_public_catalog():
    data = _describe_capabilities()
    assert data["server"] == "local-home-devices-mcp"
    assert data["schema_version"] == 1
    assert data["supported_count"] == len(data["supported_capabilities"])
    assert data["active_count"] == len(data["active_capabilities"])
    assert data["supported_transports"] == ["stdio", "streamable-http"]
    assert data["protocol_revisions"] == ["2025-11-25"]
    assert data["profiles"]
    artifact = next(
        item for item in data["supported_capabilities"] if item["id"] == "artifact_read"
    )
    assert artifact["extensions"]["component_kind"] == "resource"


def test_every_capability_has_runtime_and_availability_metadata():
    required = {
        "schema_version",
        "id",
        "name",
        "description",
        "operation_kind",
        "risk",
        "active_state",
        "authorization_scopes",
        "concurrency",
        "max_response_bytes",
        "protocol_revisions",
    }
    for capability in _describe_capabilities()["supported_capabilities"]:
        assert not required - capability.keys()
        extensions = capability["extensions"]
        assert extensions["component_kind"] in {"tool", "resource"}
        assert extensions["component_identity"]
        assert extensions["availability_reason"]
        if capability["active_state"] == "inactive":
            assert extensions["inactive_reason"]


def test_registration_uses_typed_result_and_does_not_swallow_failures(mock_mcp):
    register_iot_meta_tools(mock_mcp)
    function = mock_mcp.get_tool("describe_iot_capabilities")
    assert isinstance(function(), dict)
    with patch(
        "tools.iot_meta._describe_capabilities",
        side_effect=RuntimeError("boom"),
    ):
        with pytest.raises(RuntimeError, match="boom"):
            function()
