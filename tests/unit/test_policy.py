from __future__ import annotations

import asyncio

import pytest

from local_home_devices_mcp.config import Settings
from local_home_devices_mcp.mock_runtime import MOCK_MANIFESTS, MockTargetResolver
from local_home_devices_mcp.targeting import TargetError
from local_home_devices_mcp.policy import (
    OperationGate,
    PolicyError,
    Principal,
    RateLimitExceeded,
    current_context,
)

pytestmark = pytest.mark.unit

READ = Principal("reader", frozenset({"devices:read"}), "test")
POWER_WRITER = Principal("writer", frozenset({"devices:power:write"}), "test")
GENERIC_WRITER = Principal("writer", frozenset({"devices:write"}), "test")
ADMIN = Principal("admin", frozenset({"devices:admin"}), "test")


def gate(*, write_enabled: bool = True, rate_limit: int = 60) -> OperationGate:
    base = Settings.for_mock()
    settings = Settings(
        **{
            **{field: getattr(base, field) for field in base.__dataclass_fields__},
            "write_enabled": write_enabled,
        }
    )
    return OperationGate(
        settings,
        MOCK_MANIFESTS,
        target_resolver=MockTargetResolver(),
        rate_limit_per_minute=rate_limit,
    )


@pytest.mark.asyncio
async def test_read_scope_can_read():
    runtime = gate()
    result = await runtime.invoke_async(
        "mock_get_state",
        lambda identifier: identifier,
        {"identifier": "dev_mock_light"},
        READ,
    )
    assert result == "dev_mock_light"


@pytest.mark.asyncio
async def test_generic_write_scope_does_not_authorize_power_write():
    runtime = gate()
    with pytest.raises(PolicyError, match="devices:power:write"):
        await runtime.invoke_async(
            "mock_set_power",
            lambda identifier, power: power,
            {"identifier": "dev_mock_light", "power": True},
            GENERIC_WRITER,
        )


@pytest.mark.asyncio
async def test_exact_write_scope_can_write_when_operator_enabled():
    runtime = gate()
    result = await runtime.invoke_async(
        "mock_set_power",
        lambda identifier, power: power,
        {"identifier": "dev_mock_light", "power": True},
        POWER_WRITER,
    )
    assert result is True


@pytest.mark.asyncio
async def test_write_requires_operator_enablement():
    runtime = gate(write_enabled=False)
    with pytest.raises(PolicyError, match="disabled"):
        await runtime.invoke_async(
            "mock_set_power",
            lambda identifier, power: power,
            {"identifier": "dev_mock_light", "power": True},
            POWER_WRITER,
        )


@pytest.mark.asyncio
async def test_request_context_is_scoped():
    runtime = gate()
    observed = await runtime.invoke_async(
        "mock_set_power",
        lambda identifier, power: current_context(),
        {"identifier": "dev_mock_light", "power": True},
        POWER_WRITER,
    )
    assert observed is not None and observed.principal.subject == "writer"
    assert current_context() is None


@pytest.mark.asyncio
async def test_rate_limit_is_per_principal():
    runtime = gate(rate_limit=1)
    await runtime.invoke_async(
        "mock_get_state",
        lambda identifier: identifier,
        {"identifier": "dev_mock_light"},
        READ,
    )
    with pytest.raises(RateLimitExceeded):
        await runtime.invoke_async(
            "mock_get_state",
            lambda identifier: identifier,
            {"identifier": "dev_mock_light"},
            READ,
        )


def test_model_force_argument_is_rejected():
    raw = {
        "iot_execute_command": {
            **MOCK_MANIFESTS["mock_set_power"],
            "name": "iot_execute_command",
            "risk": "DANGEROUS",
            "side_effects": "destructive",
        }
    }
    runtime = OperationGate(Settings.for_mock(), raw)
    with pytest.raises(PolicyError, match="cannot override"):
        runtime.authorize("iot_execute_command", {"force": True}, ADMIN)


@pytest.mark.asyncio
async def test_target_concurrency_honors_limit_one():
    runtime = gate()
    active = 0
    max_active = 0

    async def operation(identifier: str, power: bool) -> bool:
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)
        await asyncio.sleep(0.02)
        active -= 1
        return power

    await asyncio.gather(
        runtime.invoke_async(
            "mock_set_power",
            operation,
            {"identifier": "Mock Light", "power": True},
            POWER_WRITER,
        ),
        runtime.invoke_async(
            "mock_set_power",
            operation,
            {"identifier": "dev_mock_light", "power": False},
            POWER_WRITER,
        ),
    )
    assert max_active == 1


def test_timeout_above_manifest_budget_is_rejected():
    runtime = gate()
    with pytest.raises(PolicyError, match="timeout_seconds"):
        runtime.authorize("mock_get_state", {"timeout_seconds": 2}, READ)


def test_hostname_in_ip_parameter_is_rejected():
    runtime = gate()
    with pytest.raises(TargetError, match="invalid IP address"):
        runtime.authorize("mock_get_state", {"ip_address": "localhost"}, READ)
