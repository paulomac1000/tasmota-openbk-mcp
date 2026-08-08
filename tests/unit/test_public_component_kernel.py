from __future__ import annotations

import pytest

from local_home_devices_mcp.composition import (
    PublicInvocationError,
    _invoke_public_component,
)
from local_home_devices_mcp.config import Settings
from local_home_devices_mcp.manifests import ARTIFACT_READ_MANIFEST
from local_home_devices_mcp.policy import OperationGate, Principal

pytestmark = pytest.mark.unit


@pytest.mark.asyncio
async def test_artifact_resource_contract_uses_same_authorization_gate():
    settings = Settings.for_mock()
    gate = OperationGate(settings, {"artifact_read": ARTIFACT_READ_MANIFEST})
    principal = Principal("reader", frozenset({"devices:read"}), "http")
    callback_calls = 0

    async def callback() -> bytes:
        nonlocal callback_calls
        callback_calls += 1
        return b"secret"

    with pytest.raises(PublicInvocationError, match="devices:sensitive"):
        await _invoke_public_component(
            gate,
            settings,
            "artifact_read",
            {"artifact_id": "art_deadbeef"},
            principal,
            callback,
        )
    assert callback_calls == 0
