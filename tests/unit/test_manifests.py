from __future__ import annotations

import pytest

from local_home_devices_mcp.manifests import ManifestError, normalize_manifest

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


def test_normalization_adds_complete_contract():
    manifest = normalize_manifest("read_state", BASE)
    assert manifest["confidentiality"] == "metadata"
    assert manifest["target_binding"]["silent_fallback"] is False
    assert manifest["idempotency_mechanism"] == "none"
    assert manifest["active_state"] == "active"


def test_write_retry_claim_is_forced_fail_closed():
    raw = {**BASE, "name": "set_state", "risk": "WRITE", "side_effects": "write"}
    manifest = normalize_manifest("set_state", raw)
    assert manifest["retryable"] is False


def test_raw_command_is_dangerous_and_disabled():
    raw = {
        **BASE,
        "name": "iot_execute_command",
        "risk": "DESTRUCTIVE",
        "side_effects": "destructive",
    }
    manifest = normalize_manifest("iot_execute_command", raw)
    assert manifest["risk"] == "DANGEROUS"
    assert manifest["active_state"] == "disabled"


def test_name_must_be_valid():
    with pytest.raises(ManifestError):
        normalize_manifest("x", {**BASE, "risk": "UNKNOWN"})


def test_legacy_mutation_is_inactive_until_adapter_migration():
    raw = {**BASE, "name": "iot_set_power", "risk": "WRITE", "side_effects": "write"}
    manifest = normalize_manifest("iot_set_power", raw)
    assert manifest["active_state"] == "disabled"
    assert manifest["idempotent"] is False
    assert manifest["reversible"] is False
    assert manifest["retryable"] is False
    assert manifest["concurrent_safe"] is False


def test_camera_snapshot_requires_personal_confidentiality():
    manifest = normalize_manifest("hikvision_take_snapshot", BASE)
    assert manifest["confidentiality"] == "personal"


def test_legacy_read_positive_claims_are_conservative():
    manifest = normalize_manifest("read_state", BASE)
    assert manifest["idempotent"] is False
    assert manifest["retryable"] is False
    assert manifest["concurrent_safe"] is False
    assert manifest["reversible"] is False


def test_discovery_is_inactive_while_it_persists_cache():
    manifest = normalize_manifest("iot_discover_devices", BASE)
    assert manifest["side_effects"] == "write"
    assert manifest["risk"] == "WRITE"
    assert manifest["active_state"] == "disabled"
