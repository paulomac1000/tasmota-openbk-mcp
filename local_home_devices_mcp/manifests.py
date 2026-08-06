"""Application-owned capability manifest normalization and validation."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
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


class ManifestError(ValueError):
    """Raised when a capability manifest is missing or inconsistent."""


@dataclass(frozen=True, slots=True)
class RetryConditions:
    categories: tuple[str, ...] = ()
    max_attempts: int = 1
    backoff_ms: int = 0
    reconciliation: str = "required-before-retry"

    def as_dict(self) -> dict[str, Any]:
        return {
            "categories": list(self.categories),
            "max_attempts": self.max_attempts,
            "backoff_ms": self.backoff_ms,
            "reconciliation": self.reconciliation,
        }


def _default_confidentiality(name: str, manifest: Mapping[str, Any]) -> str:
    overrides = {
        "hikvision_take_snapshot": "personal",
        "hikvision_snapshot_to_file": "personal",
        "hikvision_container_logs": "sensitive",
        "hikvision_get_alarm_server": "sensitive",
        "openhasp_screenshot": "personal",
        "iot_tuya_cloud_refresh_keys": "credential",
        "iot_configure_mqtt": "credential",
    }
    if name in overrides:
        return overrides[name]
    privacy = str(manifest.get("confidentiality", manifest.get("privacy", "public")))
    return {"none": "public"}.get(privacy, privacy)


def normalize_manifest(name: str, raw: Mapping[str, Any]) -> dict[str, Any]:
    """Upgrade a legacy manifest to the complete conservative contract."""

    manifest = deepcopy(dict(raw))
    risk = str(manifest.get("risk", "")).upper()
    side_effects = str(manifest.get("side_effects", "read"))
    if risk not in ALLOWED_RISKS:
        raise ManifestError(f"{name}: invalid or missing risk")
    if side_effects not in ALLOWED_SIDE_EFFECTS:
        raise ManifestError(f"{name}: invalid side_effects")

    # Discovery currently persists a cache file, so it is not a pure read. Keep it
    # fail-closed until scanning and persistence are split into separate capabilities.
    if name == "iot_discover_devices":
        side_effects = "write"
        risk = "WRITE"
        manifest["side_effects"] = side_effects

    mutating = side_effects in {"write", "destructive"}
    dangerous = risk == "DANGEROUS" or name in {
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
    degraded_adapter = name in {"iot_set_brightness"}
    privileged_adapter = name in {
        "hikvision_container_status",
        "hikvision_container_logs",
        "hikvision_check_vmd",
        "hikvision_restart_container",
        "hikvision_isapi_health",
        "hikvision_pipeline_diagnose",
    }
    unbound_host_adapter = name.startswith("openhasp_")
    legacy_mutation = mutating and not name.startswith("mock_")
    if dangerous:
        risk = "DANGEROUS"
    forced_inactive = dangerous or privileged_adapter or unbound_host_adapter or legacy_mutation
    if name.startswith("mock_"):
        active_state = str(manifest.get("active_state", "active"))
    elif forced_inactive:
        active_state = "disabled" if not degraded_adapter else "degraded"
    else:
        active_state = str(manifest.get("active_state", "active"))

    manifest.update(
        {
            "name": name,
            "risk": risk,
            "confidentiality": _default_confidentiality(name, manifest),
            # Positive safety claims are retained only for the in-memory mock
            # capabilities whose semantics are executable in this repository. Legacy
            # adapters must earn these claims with operation-specific evidence.
            "idempotent": (
                bool(manifest.get("idempotent", False)) if name.startswith("mock_") else False
            ),
            "idempotency_mechanism": (
                manifest.get("idempotency_mechanism", "natural")
                if name.startswith("mock_") and manifest.get("idempotent")
                else "none"
            ),
            "retryable": (
                bool(manifest.get("retryable", False)) if name.startswith("mock_") else False
            ),
            "retry_conditions": (
                manifest.get("retry_conditions", RetryConditions().as_dict())
                if name.startswith("mock_")
                else RetryConditions().as_dict()
            ),
            "concurrent_safe": (
                bool(manifest.get("concurrent_safe", False))
                if name.startswith("mock_")
                else False
            ),
            "concurrency_scope": manifest.get("concurrency_scope", "target"),
            "timeout_ms": int(manifest.get("timeout_ms", 10_000)),
            "requires_confirmation": bool(manifest.get("requires_confirmation", mutating)),
            "reversible": (
                bool(manifest.get("reversible", False)) if name.startswith("mock_") else False
            ),
            "target_binding": manifest.get(
                "target_binding",
                {
                    "selector": "exact-device-id-or-authorized-address",
                    "revalidate_before_io": True,
                    "silent_fallback": False,
                },
            ),
            "active_state": active_state,
        }
    )
    validate_manifest(manifest)
    return manifest


def validate_manifest(manifest: Mapping[str, Any]) -> None:
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
    missing = sorted(required - set(manifest))
    if missing:
        raise ManifestError(f"{manifest.get('name', '<unknown>')}: missing {missing}")
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


def normalize_catalog(raw_catalog: Mapping[str, Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    """Return a validated catalog and reject name mismatches."""

    result: dict[str, dict[str, Any]] = {}
    for name, raw in raw_catalog.items():
        declared = raw.get("name")
        if declared not in {None, name}:
            raise ManifestError(f"{name}: manifest name mismatch ({declared!r})")
        result[name] = normalize_manifest(name, raw)
    return result
