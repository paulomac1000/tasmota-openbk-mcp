from __future__ import annotations

import pytest

from local_home_devices_mcp.manifests import (
    MANIFEST_SCHEMA_VERSION,
    ManifestError,
    manifest_availability,
    normalize_manifest,
)

pytestmark = pytest.mark.unit

BASE = {
    "name": "read_state",
    "version": "1.0.0",
    "risk": "READ",
    "side_effects": "read",
    "privacy": "metadata",
    "idempotent": True,
    "retryable": True,
    "concurrent_safe": True,
    "timeout_ms": 1000,
    "requires_confirmation": False,
    "determinism": "env-dependent",
    "latency": "fast",
    "cost": "cheap",
    "impact": "none",
    "reversible": True,
}


def test_normalization_adds_canonical_contract():
    manifest = normalize_manifest("read_state", BASE)
    assert manifest["schema_version"] == MANIFEST_SCHEMA_VERSION == 1
    assert manifest["id"] == "read_state"
    assert manifest["operation_kind"] == "read"
    assert manifest["risk"] == "low"
    assert manifest["active_state"] == "active"
    assert manifest["authorization_scopes"] == ["devices:read"]
    assert manifest["concurrency"] == {"scope": "target", "limit": 1}
    assert manifest["extensions"]["confidentiality"] == "metadata"
    assert manifest["extensions"]["target_binding"]["silent_fallback"] is False
    assert "side_effects" not in manifest
    assert "timeout_ms" not in manifest
    assert "concurrent_safe" not in manifest


def test_read_positive_mutation_claims_are_forced_fail_closed():
    manifest = normalize_manifest("read_state", BASE)
    assert manifest["idempotent"] is False
    assert manifest["retryable"] is False
    assert manifest["reversible"] is False
    assert manifest["idempotency_key_required"] is False


def test_legacy_write_is_inactive_until_typed_adapter_migration():
    raw = {
        **BASE,
        "name": "iot_set_power",
        "risk": "WRITE",
        "side_effects": "write",
    }
    manifest = normalize_manifest("iot_set_power", raw)
    assert manifest["operation_kind"] == "write"
    assert manifest["risk"] == "medium"
    assert manifest["active_state"] == "inactive"
    assert manifest["authorization_scopes"] == ["devices:power:write"]
    assert manifest["idempotent"] is False
    assert manifest["reversible"] is False
    assert manifest["retryable"] is False


def test_raw_command_is_critical_destructive_and_inactive():
    raw = {
        **BASE,
        "name": "iot_execute_command",
        "risk": "DESTRUCTIVE",
        "side_effects": "destructive",
    }
    manifest = normalize_manifest("iot_execute_command", raw)
    assert manifest["operation_kind"] == "destructive"
    assert manifest["risk"] == "critical"
    assert manifest["active_state"] == "inactive"
    assert manifest["requires_confirmation"] is True
    assert manifest["approval"]["enforcement"] == "server-side"


def test_canonical_manifest_rejects_invalid_risk():
    canonical = normalize_manifest("read_state", BASE)
    canonical["risk"] = "UNKNOWN"
    with pytest.raises(ManifestError, match="invalid risk"):
        normalize_manifest("read_state", canonical)


def test_camera_snapshot_confidentiality_is_extension_and_scope_is_explicit():
    manifest = normalize_manifest("hikvision_take_snapshot", BASE)
    assert manifest["extensions"]["confidentiality"] == "personal"
    assert manifest["authorization_scopes"] == ["camera:snapshot:sensitive"]


def test_discovery_is_inactive_write_while_it_persists_cache():
    manifest = normalize_manifest("iot_discover_devices", BASE)
    assert manifest["operation_kind"] == "write"
    assert manifest["risk"] == "medium"
    assert manifest["active_state"] == "inactive"


def test_runtime_availability_is_separate_from_lifecycle():
    manifest = normalize_manifest("read_state", {**BASE, "active_state": "degraded"})
    assert manifest["active_state"] == "active"
    assert manifest_availability(manifest) == "degraded"
