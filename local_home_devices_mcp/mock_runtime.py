"""Deterministic zero-I/O runtime and manifests used by tests and smoke checks."""

from __future__ import annotations

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
        "concurrency": {"scope": "target", "limit": 4},
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
        "version": "2.0.0",
        "risk": "READ",
        "side_effects": "read",
        "privacy": "public",
        "timeout_ms": 250,
        "determinism": "deterministic",
        "latency": "local",
        "cost": "none",
        "impact": "none",
        "authorization_scopes": ["devices:read"],
        "concurrency": {"scope": "target", "limit": 1, "queue_limit": 1},
        "max_response_bytes": 4 * 1024,
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
