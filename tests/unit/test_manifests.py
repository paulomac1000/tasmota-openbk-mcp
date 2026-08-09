from __future__ import annotations

from copy import deepcopy

import pytest

from local_home_devices_mcp.manifests import (
    MANIFEST_SCHEMA_VERSION,
    ManifestError,
    manifest_availability,
    normalize_manifest,
)
from tools.constants import TOOL_MANIFESTS

pytestmark = pytest.mark.unit


def raw(name: str) -> dict[str, object]:
    return deepcopy(TOOL_MANIFESTS[name])


def test_normalization_adds_canonical_contract():
    manifest = normalize_manifest(
        "iot_get_device_power",
        raw("iot_get_device_power"),
    )
    assert manifest["schema_version"] == MANIFEST_SCHEMA_VERSION == 1
    assert manifest["id"] == "iot_get_device_power"
    assert manifest["operation_kind"] == "read"
    assert manifest["risk"] == "low"
    assert manifest["active_state"] == "active"
    assert manifest["authorization_scopes"] == ["devices:read"]
    assert manifest["concurrency"] == {"scope": "target", "limit": 1}
    assert manifest["extensions"]["confidentiality"] == "public"
    assert manifest["extensions"]["target_binding"]["silent_fallback"] is False
    assert "side_effects" not in manifest
    assert "timeout_ms" not in manifest
    assert "concurrent_safe" not in manifest


def test_read_positive_mutation_claims_are_forced_fail_closed():
    manifest = normalize_manifest(
        "iot_get_device_power",
        raw("iot_get_device_power"),
    )
    assert manifest["idempotent"] is False
    assert manifest["retryable"] is False
    assert manifest["reversible"] is False
    assert manifest["idempotency_key_required"] is False


def test_legacy_write_is_inactive_until_typed_adapter_migration():
    manifest = normalize_manifest("iot_set_power", raw("iot_set_power"))
    assert manifest["operation_kind"] == "write"
    assert manifest["risk"] == "medium"
    assert manifest["active_state"] == "inactive"
    assert manifest["authorization_scopes"] == ["devices:power:write"]
    assert manifest["idempotent"] is False
    assert manifest["reversible"] is False
    assert manifest["retryable"] is False


def test_raw_command_is_critical_destructive_and_inactive():
    manifest = normalize_manifest(
        "iot_execute_command",
        raw("iot_execute_command"),
    )
    assert manifest["operation_kind"] == "destructive"
    assert manifest["risk"] == "critical"
    assert manifest["active_state"] == "inactive"
    assert manifest["requires_confirmation"] is True
    assert manifest["approval"]["enforcement"] == "server-side"


def test_canonical_manifest_rejects_invalid_risk():
    canonical = normalize_manifest(
        "iot_get_device_power",
        raw("iot_get_device_power"),
    )
    canonical["risk"] = "UNKNOWN"
    with pytest.raises(ManifestError, match="invalid risk"):
        normalize_manifest("iot_get_device_power", canonical)


def test_camera_snapshot_confidentiality_is_extension_and_scope_is_explicit():
    manifest = normalize_manifest(
        "hikvision_take_snapshot",
        raw("hikvision_take_snapshot"),
    )
    assert manifest["extensions"]["confidentiality"] == "personal"
    assert manifest["authorization_scopes"] == ["camera:snapshot:sensitive"]


def test_discovery_is_inactive_write_while_it_persists_cache():
    manifest = normalize_manifest(
        "iot_discover_devices",
        raw("iot_discover_devices"),
    )
    assert manifest["operation_kind"] == "write"
    assert manifest["risk"] == "medium"
    assert manifest["active_state"] == "inactive"


def test_runtime_availability_is_separate_from_lifecycle():
    legacy = raw("iot_get_device_power")
    legacy["active_state"] = "degraded"
    manifest = normalize_manifest("iot_get_device_power", legacy)
    assert manifest["active_state"] == "active"
    assert manifest_availability(manifest) == "degraded"


def test_unknown_legacy_capability_never_defaults_to_read():
    legacy = raw("iot_get_device_power")
    legacy["name"] = "new_unreviewed_capability"
    with pytest.raises(ManifestError, match="reviewed allowlist"):
        normalize_manifest("new_unreviewed_capability", legacy)


@pytest.mark.parametrize("field", ["risk", "side_effects"])
def test_missing_legacy_safety_classification_fails_registration(field: str):
    legacy = raw("iot_get_device_power")
    legacy.pop(field)
    with pytest.raises(ManifestError, match="required"):
        normalize_manifest("iot_get_device_power", legacy)


def test_changed_legacy_safety_classification_fails_registration():
    legacy = raw("iot_get_device_power")
    legacy["side_effects"] = "write"
    legacy["risk"] = "WRITE"
    with pytest.raises(ManifestError, match="classification changed"):
        normalize_manifest("iot_get_device_power", legacy)
