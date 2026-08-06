from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from local_home_devices_mcp.config import Settings
from local_home_devices_mcp.mock_runtime import MOCK_MANIFESTS, MockTargetResolver
from local_home_devices_mcp.policy import OperationGate, Principal

pytestmark = pytest.mark.unit


def settings(tmp_path: Path) -> Settings:
    import ipaddress

    return Settings(
        transport="stdio",
        bind_host="127.0.0.1",
        port=9102,
        mcp_path="/mcp",
        write_enabled=True,
        dangerous_enabled=False,
        allow_direct_ip_targets=False,
        allowed_networks=(ipaddress.ip_network("192.0.2.0/24"),),
        artifact_root=tmp_path,
        max_artifact_bytes=1024 * 1024,
        max_artifact_store_bytes=4 * 1024 * 1024,
        artifact_retention_seconds=3600,
        read_token=None,
        write_token=None,
        admin_token=None,
        trusted_proxy_tls=False,
        mock_mode=True,
    )


@pytest.mark.asyncio
async def test_runtime_resolves_and_revalidates_target(tmp_path: Path):
    resolver = MockTargetResolver()
    gate = OperationGate(settings(tmp_path), MOCK_MANIFESTS, target_resolver=resolver)
    principal = Principal("test", frozenset({"devices:admin"}), "stdio")

    result = await gate.invoke_async(
        "mock_set_power",
        lambda identifier, power: {"identifier": identifier, "power": power},
        {"identifier": "Mock Light", "power": True},
        principal,
    )

    assert result["power"] is True
    assert resolver.revalidations == 1
    assert gate.locks.entry_count == 0


@pytest.mark.asyncio
async def test_aliases_for_same_target_share_one_lock(tmp_path: Path):
    resolver = MockTargetResolver()
    gate = OperationGate(settings(tmp_path), MOCK_MANIFESTS, target_resolver=resolver)
    principal = Principal("test", frozenset({"devices:admin"}), "stdio")
    active = 0
    max_active = 0

    async def operation(identifier: str, power: bool) -> dict[str, object]:
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)
        await asyncio.sleep(0.03)
        active -= 1
        return {"identifier": identifier, "power": power}

    await asyncio.gather(
        gate.invoke_async(
            "mock_set_power", operation,
            {"identifier": "Mock Light", "power": True}, principal,
        ),
        gate.invoke_async(
            "mock_set_power", operation,
            {"identifier": "dev_mock_light", "power": False}, principal,
        ),
    )

    assert max_active == 1
    assert resolver.revalidations == 2
    assert gate.locks.entry_count == 0


@pytest.mark.asyncio
async def test_target_bearing_tool_fails_closed_without_resolver(tmp_path: Path):
    gate = OperationGate(settings(tmp_path), MOCK_MANIFESTS)
    principal = Principal("test", frozenset({"devices:admin"}), "stdio")
    with pytest.raises(PermissionError, match="target resolver"):
        await gate.invoke_async(
            "mock_get_state",
            lambda identifier: {"identifier": identifier},
            {"identifier": "dev_mock_light"},
            principal,
        )


@pytest.mark.asyncio
async def test_literal_ip_in_identifier_is_rejected_when_disabled(tmp_path: Path):
    resolver = MockTargetResolver()
    gate = OperationGate(settings(tmp_path), MOCK_MANIFESTS, target_resolver=resolver)
    principal = Principal("test", frozenset({"devices:admin"}), "stdio")

    with pytest.raises(PermissionError, match="literal IP targets are disabled"):
        await gate.invoke_async(
            "mock_get_state",
            lambda identifier: {"identifier": identifier},
            {"identifier": "192.0.2.10"},
            principal,
        )


@pytest.mark.asyncio
async def test_principal_target_acl_is_checked_after_resolution(tmp_path: Path):
    resolver = MockTargetResolver()
    gate = OperationGate(settings(tmp_path), MOCK_MANIFESTS, target_resolver=resolver)
    principal = Principal(
        "restricted",
        frozenset({"devices:read"}),
        "http",
        target_ids=frozenset({"dev_other"}),
    )

    with pytest.raises(PermissionError, match="not authorized for target"):
        await gate.invoke_async(
            "mock_get_state",
            lambda identifier: {"identifier": identifier},
            {"identifier": "dev_mock_light"},
            principal,
        )
    assert resolver.revalidations == 0


@pytest.mark.asyncio
async def test_timeout_keeps_target_lock_until_sync_worker_finishes(tmp_path: Path):
    import threading
    import time

    from local_home_devices_mcp.legacy_compat import _wrap

    resolver = MockTargetResolver()
    gate = OperationGate(settings(tmp_path), MOCK_MANIFESTS, target_resolver=resolver)
    principal = Principal("test", frozenset({"devices:admin"}), "stdio")
    active = 0
    max_active = 0
    second_started = threading.Event()

    def operation(identifier: str, power: bool) -> dict[str, object]:
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)
        try:
            if power:
                time.sleep(0.12)
            else:
                second_started.set()
            return {"identifier": identifier, "power": power}
        finally:
            active -= 1

    async def first_call() -> None:
        with pytest.raises(TimeoutError):
            async with asyncio.timeout(0.02):
                await gate.invoke_async(
                    "mock_set_power",
                    _wrap(operation),
                    {"identifier": "Mock Light", "power": True},
                    principal,
                )

    first = asyncio.create_task(first_call())
    await asyncio.sleep(0.04)
    second = asyncio.create_task(
        gate.invoke_async(
            "mock_set_power",
            _wrap(operation),
            {"identifier": "dev_mock_light", "power": False},
            principal,
        )
    )
    await asyncio.sleep(0.04)
    assert not second_started.is_set()
    await asyncio.gather(first, second)

    assert second_started.is_set()
    assert max_active == 1
    assert gate.locks.entry_count == 0
