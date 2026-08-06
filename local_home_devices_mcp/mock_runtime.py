"""Zero-I/O mock runtime used for local validation and CI smoke tests."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .config import Settings
from .policy import OperationGate, Principal


@dataclass
class MockDevice:
    target_id: str = "dev_mock_light"
    name: str = "Mock Light"
    ip: str = "192.168.50.10"
    power: bool = False
    brightness: int = 50


MOCK_MANIFESTS: dict[str, dict[str, Any]] = {
    "mock_get_state": {
        "name": "mock_get_state",
        "version": "2.0.0",
        "risk": "READ",
        "side_effects": "read",
        "privacy": "none",
        "idempotent": True,
        "retryable": False,
        "concurrent_safe": True,
        "timeout_ms": 1000,
        "requires_confirmation": False,
        "determinism": "deterministic",
        "latency": "instant",
        "cost": "cheap",
        "impact": "none",
        "reversible": True,
    },
    "mock_set_power": {
        "name": "mock_set_power",
        "version": "2.0.0",
        "risk": "WRITE",
        "side_effects": "write",
        "privacy": "none",
        "idempotent": True,
        "idempotency_mechanism": "natural",
        "retryable": False,
        "concurrent_safe": False,
        "timeout_ms": 1000,
        "requires_confirmation": True,
        "determinism": "deterministic",
        "latency": "instant",
        "cost": "cheap",
        "impact": "transient",
        "reversible": True,
    },
}


def run_mock_self_test(settings: Settings) -> dict[str, Any]:
    device = MockDevice()
    gate = OperationGate(settings, MOCK_MANIFESTS, rate_limit_per_minute=20)
    principal = Principal(
        subject="local-mock-test",
        scopes=frozenset({"devices:read", "devices:write"}),
        transport="local-test",
    )

    def get_state(identifier: str) -> dict[str, Any]:
        return {"identifier": identifier, "power": device.power, "brightness": device.brightness}

    def set_power(identifier: str, state: bool) -> dict[str, Any]:
        device.power = state
        return {"identifier": identifier, "power": device.power}

    before = gate.invoke("mock_get_state", get_state, {"identifier": device.target_id}, principal)
    after = gate.invoke(
        "mock_set_power", set_power, {"identifier": device.target_id, "state": True}, principal
    )
    restored = gate.invoke(
        "mock_set_power", set_power, {"identifier": device.target_id, "state": False}, principal
    )
    return {
        "success": restored["power"] is False,
        "before": before,
        "after": after,
        "restored": restored,
        "io": "mocked",
    }
