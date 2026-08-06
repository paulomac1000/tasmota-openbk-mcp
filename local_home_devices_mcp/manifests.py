"""Application-owned capability manifest normalization and validation."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

ALLOWED_RISKS = {"READ", "WRITE", "DESTRUCTIVE", "DANGEROUS", "SENSITIVE"}
ALLOWED_SIDE_EFFECTS = {"none", "read", "write", "destructive"}
ALLOWED_CONFIDENTIALITY = {
    "public",
    "internal",
    "metadata",
    "personal",
    "sensitive",
    "credential",
}
ALLOWED_ACTIVE_STATES = {"active", "disabled", "degraded", "unavailable", "deprecated"}

_DEFAULT_RETRY_CONDITIONS = {
    "categories": [],
    "max_attempts": 1,
    "backoff_ms": 0,
    "reconciliation": "required-before-retry",
}
_DEFAULT_TARGET_BINDING = {
    "selector": "exact-device-id-or-authorized-address",
    "revalidate_before_io": True,
    "silent_fallback": False,
}


class ManifestError(ValueError):
    """Raised when a capability manifest is incomplete or inconsistent."""


def normalize_manifest(name: str, raw: Mapping[str, Any]) -> dict[str, Any]:
    """Upgrade one legacy manifest to a conservative application contract."""
    manifest = deepcopy(dict(raw))
    risk = str(manifest.get("risk", "READ")).upper()
    side_effects = str(manifest.get("side_effects", "read"))
    if risk not in ALLOWED_RISKS or side_effects not in ALLOWED_SIDE_EFFECTS:
        raise ManifestError(f"{name}: invalid risk or side_effects")

    mutating = side_effects in {"write", "destructive"}
    dangerous_names = {
        "iot_execute_command",
        "openhasp_ota_update",
        "openhasp_factory_reset",
        "openhasp_hardware_test",
        "hikvision_open_gate",
        "hikvision_snapshot_to_file",
        "iot_set_flags",
        "iot_set_gpio",
        "iot_set_startup_command",
        "iot_tuya_set_dp",
        "iot_tuya_cloud_refresh_keys",
    }
    privileged = {
        "hikvision_container_status",
        "hikvision_container_logs",
        "hikvision_check_vmd",
        "hikvision_restart_container",
        "hikvision_isapi_health",
        "hikvision_pipeline_diagnose",
    }
    unbound_openhasp = name.startswith("openhasp_")

    if name == "iot_discover_devices":
        risk, side_effects, mutating = "WRITE", "write", True
    if name in dangerous_names:
        risk = "DANGEROUS"

    # Legacy multi-backend writes remain disabled until every backend has
    # backend-specific evidence and ambiguous-outcome reconciliation.
    migrated_mutations: set[str] = set()
    legacy_mutation = (
        mutating and not name.startswith("mock_") and name not in migrated_mutations
    )
    forced_inactive = (
        name in dangerous_names
        or name in privileged
        or unbound_openhasp
        or legacy_mutation
    )
    active_state = "disabled" if forced_inactive else str(
        manifest.get("active_state", "active")
    )

    confidentiality_overrides = {
        "hikvision_take_snapshot": "personal",
        "hikvision_snapshot_to_file": "personal",
        "hikvision_container_logs": "sensitive",
        "hikvision_get_alarm_server": "sensitive",
        "openhasp_screenshot": "personal",
        "iot_tuya_cloud_refresh_keys": "credential",
        "iot_configure_mqtt": "credential",
        "mock_capture_snapshot": "personal",
    }
    confidentiality = confidentiality_overrides.get(
        name,
        str(manifest.get("confidentiality", manifest.get("privacy", "public"))),
    )
    if confidentiality == "none":
        confidentiality = "public"

    mock = name.startswith("mock_")
    verified_explicit_set = False
    retry_conditions = (
        manifest.get("retry_conditions", deepcopy(_DEFAULT_RETRY_CONDITIONS))
        if mock
        else deepcopy(_DEFAULT_RETRY_CONDITIONS)
    )
    target_binding = manifest.get(
        "target_binding", deepcopy(_DEFAULT_TARGET_BINDING)
    )

    manifest.update(
        {
            "name": name,
            "risk": risk,
            "side_effects": side_effects,
            "confidentiality": confidentiality,
            "idempotent": (
                bool(manifest.get("idempotent", False))
                if mock
                else verified_explicit_set
            ),
            "idempotency_mechanism": (
                manifest.get("idempotency_mechanism", "natural")
                if mock and manifest.get("idempotent")
                else "explicit-target-state"
                if verified_explicit_set
                else "none"
            ),
            "retryable": bool(manifest.get("retryable", False)) if mock else False,
            "retry_conditions": retry_conditions,
            "concurrent_safe": (
                bool(manifest.get("concurrent_safe", False)) if mock else False
            ),
            "concurrency_scope": manifest.get("concurrency_scope", "target"),
            "timeout_ms": int(manifest.get("timeout_ms", 10_000)),
            "requires_confirmation": bool(
                manifest.get("requires_confirmation", mutating)
            ),
            "reversible": (
                bool(manifest.get("reversible", False)) if mock else False
            ),
            "target_binding": target_binding,
            "active_state": active_state,
            "determinism": manifest.get("determinism", "environment-dependent"),
            "latency": manifest.get("latency", "network"),
            "cost": manifest.get("cost", "local-network"),
            "impact": manifest.get(
                "impact", "none" if not mutating else "device-state"
            ),
            "version": str(manifest.get("version", "2.0.0")),
        }
    )
    validate_manifest(manifest)
    return manifest


def validate_manifest(manifest: Mapping[str, Any]) -> None:
    """Reject missing fields and unsafe semantic combinations."""
    required = {
        "name",
        "version",
        "risk",
        "side_effects",
        "confidentiality",
        "idempotent",
        "idempotency_mechanism",
        "retryable",
        "retry_conditions",
        "concurrent_safe",
        "concurrency_scope",
        "timeout_ms",
        "requires_confirmation",
        "determinism",
        "latency",
        "cost",
        "impact",
        "reversible",
        "target_binding",
        "active_state",
    }
    missing = required - set(manifest)
    if missing:
        name = manifest.get("name", "<unknown>")
        raise ManifestError(f"{name}: missing {sorted(missing)}")
    if manifest["risk"] not in ALLOWED_RISKS:
        raise ManifestError("invalid risk")
    if manifest["side_effects"] not in ALLOWED_SIDE_EFFECTS:
        raise ManifestError("invalid side_effects")
    if manifest["confidentiality"] not in ALLOWED_CONFIDENTIALITY:
        raise ManifestError("invalid confidentiality")
    if manifest["active_state"] not in ALLOWED_ACTIVE_STATES:
        raise ManifestError("invalid active_state")
    if not isinstance(manifest["timeout_ms"], int) or manifest["timeout_ms"] <= 0:
        raise ManifestError("timeout_ms must be positive")
    if manifest["side_effects"] in {"write", "destructive"} and manifest["retryable"]:
        raise ManifestError("mutating capabilities default to retryable=false")


def normalize_catalog(
    raw_catalog: Mapping[str, Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Normalize a complete catalog and reject key/name mismatches."""
    result: dict[str, dict[str, Any]] = {}
    for name, raw in raw_catalog.items():
        declared = raw.get("name")
        if declared not in {None, name}:
            raise ManifestError(f"{name}: manifest name mismatch")
        result[name] = normalize_manifest(name, raw)
    return result
