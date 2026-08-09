"""Deterministic zero-I/O runtime and manifests used by tests and smoke checks."""

from __future__ import annotations

import asyncio
from copy import deepcopy
from typing import Any

from .targeting import BoundTarget, TargetNotFound

MOCK_DEVICE = {
    "target_id": "dev_mock_light",
    "device_id": "mock-light-001",
    "mac": "02:00:00:00:00:01",
    "serial": "MOCK-001",
    "type": "mock",
    "name": "Mock Light",
    "ip": "192.0.2.10",
}

MOCK_MANIFESTS: dict[str, dict[str, Any]] = {
    "mock_get_state": {
        "version": "2.0.0",
        "risk": "READ",
        "side_effects": "read",
        "privacy": "public",
        "timeout_ms": 1000,
        "determinism": "deterministic",
        "latency": "local",
        "cost": "none",
        "impact": "none",
        "authorization_scopes": ["devices:read"],
        "concurrency": {"scope": "target", "limit": 1},
        "max_response_bytes": 32 * 1024,
    },
    "mock_set_power": {
        "version": "2.0.0",
        "risk": "WRITE",
        "side_effects": "write",
        "privacy": "public",
        "idempotent": True,
        "retryable": False,
        "timeout_ms": 1000,
        "determinism": "deterministic",
        "latency": "local",
        "cost": "none",
        "impact": "device-state",
        "reversible": True,
        "authorization_scopes": ["devices:power:write"],
        "concurrency": {"scope": "target", "limit": 1},
        "max_response_bytes": 32 * 1024,
    },
    "mock_capture_snapshot": {
        "version": "2.0.0",
        "risk": "SENSITIVE",
        "side_effects": "write",
        "privacy": "personal",
        "idempotent": False,
        "retryable": False,
        "timeout_ms": 1000,
        "determinism": "deterministic",
        "latency": "local",
        "cost": "storage",
        "impact": "artifact",
        "reversible": True,
        "authorization_scopes": ["camera:snapshot:sensitive"],
        "concurrency": {"scope": "target", "limit": 1},
        "max_response_bytes": 32 * 1024,
    },
    "mock_wait": {
        "schema_version": 1,
        "id": "mock_wait",
        "name": "mock_wait",
        "description": "Wait in-process for exact-artifact timeout and cancellation probes.",
        "operation_kind": "read",
        "risk": "low",
        "determinism": "deterministic",
        "latency": "interactive",
        "impact": "none",
        "active_state": "active",
        "retryable": False,
        "idempotent": False,
        "reversible": False,
        "requires_confirmation": False,
        "idempotency_key_required": False,
        "authorization_scopes": ["devices:read"],
        "concurrency": {"scope": "target", "limit": 1, "queue_limit": 1},
        "max_response_bytes": 4 * 1024,
        "protocol_revisions": ["2025-11-25"],
        "extensions": {
            "confidentiality": "public",
            "availability": "available",
            "availability_reason": "mock-runtime-ready",
            "timeout_ms": 250,
            "target_binding": {
                "selector": "exact-device-id-or-authorized-address",
                "revalidate_before_io": True,
                "silent_fallback": False,
            },
        },
    },
}


class MockTargetResolver:
    """Resolve and revalidate one deterministic device without external I/O."""

    def __init__(self) -> None:
        self.device = deepcopy(MOCK_DEVICE)
        self.resolve_calls = 0
        self.revalidations = 0

    async def resolve(
        self,
        selector: str,
        *,
        allowed_target_ids: frozenset[str] | None = None,
    ) -> BoundTarget:
        self.resolve_calls += 1
        if allowed_target_ids is not None and "dev_mock_light" not in allowed_target_ids:
            raise TargetNotFound(f"{selector!r}: no target in authorized namespace")
        normalized = selector.strip().casefold()
        if normalized not in {"dev_mock_light", "mock light", "192.0.2.10"}:
            raise TargetNotFound(f"{selector!r}: no exact mock target")
        return BoundTarget(
            target_id="dev_mock_light",
            address="192.0.2.10",
            display_name="Mock Light",
            fingerprint="mock-fingerprint-v1",
        )

    async def revalidate(self, target: BoundTarget) -> None:
        self.revalidations += 1
        if target.target_id != "dev_mock_light" or target.fingerprint != "mock-fingerprint-v1":
            raise TargetNotFound("mock target binding changed")

    async def readiness(self) -> dict[str, Any]:
        return {"status": "ready", "valid_targets": 1, "source": "mock"}


def run_mock_self_test(settings: Any) -> dict[str, Any]:
    """Run the deterministic zero-I/O governance workflow for smoke checks.

    Returns the same contract that ``server.py --mock-self-test`` prints so
    subprocess smoke tests and in-process tests exercise identical code.
    """
    from .policy import OperationGate, Principal

    resolver = MockTargetResolver()
    gate = OperationGate(settings, MOCK_MANIFESTS, target_resolver=resolver)
    principal = Principal("mock-self-test", frozenset({"devices:admin"}), "stdio")
    state = {"power": False, "brightness": 50}

    async def run_test() -> dict[str, Any]:
        before = dict(state)
        after = await gate.invoke_async(
            "mock_set_power",
            lambda identifier, power: (
                state.update(power=power) or {"identifier": identifier, **state}
            ),
            {"identifier": "dev_mock_light", "power": True},
            principal,
        )
        state["power"] = before["power"]
        return {
            "success": True,
            "io": "mocked",
            "before": before,
            "after": after,
            "restored": dict(state),
            "target_revalidations": resolver.revalidations,
        }

    return asyncio.run(run_test())
