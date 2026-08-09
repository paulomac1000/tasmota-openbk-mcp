from __future__ import annotations

import json

import pytest

from local_home_devices_mcp.legacy_compat import LegacyToolFailure, normalize_legacy_result

pytestmark = pytest.mark.unit


def test_legacy_success_becomes_typed_data():
    result = normalize_legacy_result(json.dumps({"success": True, "data": {"power": "ON"}}))
    assert result == {"power": "ON"}


def test_legacy_failure_becomes_exception():
    with pytest.raises(LegacyToolFailure, match="device missing") as caught:
        normalize_legacy_result(
            json.dumps(
                {
                    "success": False,
                    "error": {"code": "NOT_FOUND", "message": "device missing"},
                }
            )
        )
    assert caught.value.code == "NOT_FOUND"


@pytest.mark.asyncio
async def test_legacy_registration_proxy_wraps_sync_and_async_tools():
    from local_home_devices_mcp.legacy_compat import LegacyRegistrationProxy

    class Registry:
        def __init__(self):
            self.tools = {}

        def tool(self, function=None, **kwargs):
            def register(candidate):
                self.tools[candidate.__name__] = candidate
                return candidate

            return register(function) if callable(function) else register

    registry = Registry()
    proxy = LegacyRegistrationProxy(registry)

    @proxy.tool
    def sync_tool(value: int):
        return json.dumps({"success": True, "data": {"value": value}})

    @proxy.tool()
    async def async_tool(value: int):
        return json.dumps({"success": True, "data": {"value": value + 1}})

    assert await registry.tools["sync_tool"](3) == {"value": 3}
    assert await registry.tools["async_tool"](3) == {"value": 4}
    assert proxy.tools is registry.tools


def test_legacy_result_passthrough_and_default_failure():
    assert normalize_legacy_result(7) == 7
    assert normalize_legacy_result("plain text") == "plain text"
    assert normalize_legacy_result(json.dumps({"value": 1})) == {"value": 1}
    with pytest.raises(LegacyToolFailure) as caught:
        normalize_legacy_result(json.dumps({"success": False}))
    assert caught.value.code == "LEGACY_ERROR"
