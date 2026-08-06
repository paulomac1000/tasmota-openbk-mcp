from __future__ import annotations

import threading
import time

import pytest

from local_home_devices_mcp.config import load_settings
from local_home_devices_mcp.mock_runtime import MOCK_MANIFESTS
from local_home_devices_mcp.policy import (
    OperationGate,
    PolicyError,
    Principal,
    RateLimitExceeded,
    current_context,
)

pytestmark = pytest.mark.unit

READ = Principal("reader", frozenset({"devices:read"}), "test")
WRITER = Principal("writer", frozenset({"devices:read", "devices:write"}), "test")
ADMIN = Principal("admin", frozenset({"devices:admin"}), "test")


def test_read_scope_can_read():
    gate = OperationGate(load_settings(), MOCK_MANIFESTS)
    result = gate.invoke(
        "mock_get_state",
        lambda identifier: identifier,
        {"identifier": "dev_1"},
        READ,
    )
    assert result == "dev_1"


def test_read_scope_cannot_write(monkeypatch):
    monkeypatch.setenv("ENABLE_WRITE_OPERATIONS", "1")
    gate = OperationGate(load_settings(), MOCK_MANIFESTS)
    with pytest.raises(PolicyError, match="scope"):
        gate.invoke(
            "mock_set_power",
            lambda identifier, power: power,
            {"identifier": "dev_1", "power": True},
            READ,
        )


def test_write_requires_operator_enablement():
    gate = OperationGate(load_settings(), MOCK_MANIFESTS)
    with pytest.raises(PolicyError, match="disabled"):
        gate.invoke(
            "mock_set_power",
            lambda identifier, power: power,
            {"identifier": "dev_1", "power": True},
            WRITER,
        )


def test_request_context_is_scoped(monkeypatch):
    monkeypatch.setenv("ENABLE_WRITE_OPERATIONS", "1")
    gate = OperationGate(load_settings(), MOCK_MANIFESTS)
    observed = gate.invoke(
        "mock_set_power",
        lambda identifier, power: current_context(),
        {"identifier": "dev_1", "power": True},
        WRITER,
    )
    assert observed is not None and observed.principal.subject == "writer"
    assert current_context() is None


def test_rate_limit_is_per_principal():
    gate = OperationGate(load_settings(), MOCK_MANIFESTS, rate_limit_per_minute=1)
    gate.invoke("mock_get_state", lambda identifier: identifier, {"identifier": "dev_1"}, READ)
    with pytest.raises(RateLimitExceeded):
        gate.invoke("mock_get_state", lambda identifier: identifier, {"identifier": "dev_1"}, READ)


def test_model_force_argument_is_rejected(monkeypatch):
    raw = {
        "iot_execute_command": {
            **MOCK_MANIFESTS["mock_set_power"],
            "name": "iot_execute_command",
            "risk": "DANGEROUS",
            "side_effects": "destructive",
        }
    }
    monkeypatch.setenv("ENABLE_WRITE_OPERATIONS", "1")
    monkeypatch.setenv("ENABLE_DANGEROUS_OPERATIONS", "1")
    gate = OperationGate(load_settings(), raw)
    with pytest.raises(PolicyError, match="cannot override"):
        gate.authorize("iot_execute_command", {"force": True}, ADMIN)


def test_non_concurrent_tool_is_serialized(monkeypatch):
    monkeypatch.setenv("ENABLE_WRITE_OPERATIONS", "1")
    gate = OperationGate(load_settings(), MOCK_MANIFESTS)
    order: list[str] = []

    def operation(identifier: str, power: bool) -> bool:
        order.append("start")
        time.sleep(0.03)
        order.append("end")
        return power

    threads = [
        threading.Thread(
            target=lambda: gate.invoke(
                "mock_set_power", operation, {"identifier": "same", "power": True}, WRITER
            )
        )
        for _ in range(2)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert order == ["start", "end", "start", "end"]


def test_sensitive_read_requires_sensitive_scope():
    raw = {
        "secret_read": {
            **MOCK_MANIFESTS["mock_get_state"],
            "name": "secret_read",
            "confidentiality": "sensitive",
        }
    }
    gate = OperationGate(load_settings(), raw)
    with pytest.raises(PolicyError, match="devices:sensitive"):
        gate.authorize("secret_read", {}, READ)


def test_timeout_above_manifest_budget_is_rejected():
    gate = OperationGate(load_settings(), MOCK_MANIFESTS)
    with pytest.raises(PolicyError, match="timeout_seconds"):
        gate.authorize("mock_get_state", {"timeout_seconds": 2}, READ)


def test_hostname_in_ip_parameter_is_rejected():
    gate = OperationGate(load_settings(), MOCK_MANIFESTS)
    with pytest.raises(PolicyError, match="literal authorized IPv4"):
        gate.authorize("mock_get_state", {"ip_address": "localhost"}, READ)
