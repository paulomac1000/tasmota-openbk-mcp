from __future__ import annotations

import asyncio
import time

import pytest

from local_home_devices_mcp.config import Settings
from local_home_devices_mcp.legacy_compat import _wrap
from local_home_devices_mcp.manifests import (
    MANIFEST_SCHEMA_VERSION,
    is_runtime_active,
    normalize_catalog,
    normalize_manifest,
)
from local_home_devices_mcp.mock_runtime import MOCK_MANIFESTS, MockTargetResolver
from local_home_devices_mcp.policy import OperationGate, PolicyError, Principal


def test_mock_catalog_is_canonical_and_has_no_legacy_top_level_fields():
    catalog = normalize_catalog(MOCK_MANIFESTS)
    for capability_id, manifest in catalog.items():
        assert manifest["schema_version"] == MANIFEST_SCHEMA_VERSION == 1
        assert manifest["id"] == capability_id
        assert manifest["active_state"] == "active"
        assert "side_effects" not in manifest
        assert "timeout_ms" not in manifest
        assert "concurrent_safe" not in manifest
        assert isinstance(manifest["authorization_scopes"], list)
        assert set(manifest["concurrency"]) >= {"scope", "limit"}
        assert manifest["max_response_bytes"] > 0


def test_lifecycle_is_separate_from_runtime_availability():
    degraded = normalize_manifest(
        "sample_read",
        {
            "name": "sample_read",
            "risk": "READ",
            "side_effects": "read",
            "active_state": "degraded",
        },
    )
    unavailable = normalize_manifest(
        "other_read",
        {
            "name": "other_read",
            "risk": "READ",
            "side_effects": "read",
            "active_state": "unavailable",
        },
    )
    assert degraded["active_state"] == "active"
    assert degraded["extensions"]["availability"] == "degraded"
    assert is_runtime_active(degraded)
    assert unavailable["active_state"] == "active"
    assert unavailable["extensions"]["availability"] == "unavailable"
    assert not is_runtime_active(unavailable)


@pytest.mark.asyncio
async def test_authorization_uses_declared_scopes_not_risk_classification():
    gate = OperationGate(
        Settings.for_mock(),
        MOCK_MANIFESTS,
        target_resolver=MockTargetResolver(),
    )
    generic_writer = Principal(
        "writer",
        frozenset({"devices:write"}),
        "stdio",
    )
    exact_writer = Principal(
        "power-writer",
        frozenset({"devices:power:write"}),
        "stdio",
    )
    arguments = {"identifier": "dev_mock_light", "power": True}
    with pytest.raises(PolicyError, match="devices:power:write"):
        gate.authorize("mock_set_power", arguments, generic_writer)
    gate.authorize("mock_set_power", arguments, exact_writer)


@pytest.mark.asyncio
async def test_client_deadline_does_not_release_backend_ownership():
    gate = OperationGate(
        Settings.for_mock(),
        MOCK_MANIFESTS,
        target_resolver=MockTargetResolver(),
    )
    principal = Principal(
        "writer",
        frozenset({"devices:power:write"}),
        "stdio",
    )
    events: list[tuple[str, float]] = []

    def blocking(identifier: str, power: bool) -> dict[str, object]:
        events.append(("first-start", time.monotonic()))
        time.sleep(0.15)
        events.append(("first-end", time.monotonic()))
        return {"identifier": identifier, "power": power}

    wrapped = _wrap(blocking)
    started = time.monotonic()
    with pytest.raises(TimeoutError):
        async with asyncio.timeout(0.02):
            await gate.invoke_async(
                "mock_set_power",
                wrapped,
                {"identifier": "dev_mock_light", "power": True},
                principal,
            )
    returned = time.monotonic()
    assert returned - started < 0.10
    assert gate.supervisor_count == 1

    second_started: float | None = None

    async def second(identifier: str, power: bool) -> dict[str, object]:
        nonlocal second_started
        second_started = time.monotonic()
        return {"identifier": identifier, "power": power}

    await gate.invoke_async(
        "mock_set_power",
        second,
        {"identifier": "dev_mock_light", "power": False},
        principal,
    )
    assert second_started is not None
    first_end = next(at for label, at in events if label == "first-end")
    assert second_started >= first_end
    await asyncio.sleep(0)
    assert gate.supervisor_count == 0
    assert gate.concurrency.entry_count == 0


def test_non_target_capability_uses_capability_concurrency() -> None:
    from local_home_devices_mcp.manifests import normalize_manifest
    from tools.constants import TOOL_MANIFESTS

    manifest = normalize_manifest(
        "describe_iot_capabilities", TOOL_MANIFESTS["describe_iot_capabilities"]
    )
    assert manifest["concurrency"] == {"scope": "capability", "limit": 1}
    assert manifest["extensions"]["target_binding"]["selector"] == "none"
