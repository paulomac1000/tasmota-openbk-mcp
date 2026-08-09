"""Canonical capability manifests and fail-closed legacy compatibility."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import Any

MANIFEST_SCHEMA_VERSION = 1
SERVER_HARD_MAX_RESPONSE_BYTES = 1024 * 1024
DEFAULT_MAX_RESPONSE_BYTES = 256 * 1024

ALLOWED_OPERATION_KINDS = {"read", "write", "destructive"}
ALLOWED_RISKS = {"low", "medium", "high", "critical"}
ALLOWED_DETERMINISM = {"deterministic", "environment-dependent", "nondeterministic"}
ALLOWED_LATENCY = {"interactive", "bounded-long", "background"}
ALLOWED_IMPACT = {"none", "local", "external", "cross-tenant"}
ALLOWED_ACTIVE_STATES = {"active", "inactive", "deprecated"}
ALLOWED_CONCURRENCY_SCOPES = {
    "global",
    "principal",
    "target",
    "credential",
    "resource",
    "capability",
    "principal-target",
    "custom",
}

_REQUIRED_FIELDS = {
    "schema_version",
    "id",
    "name",
    "description",
    "operation_kind",
    "risk",
    "determinism",
    "latency",
    "impact",
    "active_state",
    "retryable",
    "idempotent",
    "reversible",
    "requires_confirmation",
    "idempotency_key_required",
    "authorization_scopes",
    "concurrency",
    "max_response_bytes",
}
_ALLOWED_FIELDS = _REQUIRED_FIELDS | {"approval", "protocol_revisions", "extensions"}
_APPROVAL_BINDS = {"principal", "capability", "target", "arguments-digest", "expires-at"}
_DEFAULT_TARGET_BINDING = {
    "selector": "exact-device-id-or-authorized-address",
    "revalidate_before_io": True,
    "silent_fallback": False,
}
_NON_TARGET_BINDING = {
    "selector": "none",
    "revalidate_before_io": False,
    "silent_fallback": False,
}

_LEGACY_DESTRUCTIVE = {
    "hikvision_restart_container",
    "iot_execute_command",
    "iot_restart_device",
    "openhasp_factory_reset",
    "openhasp_ota_update",
    "openhasp_restart",
}
_LEGACY_NONE_READ = {"describe_iot_capabilities", "iot_mqtt_build_command_topic"}
_LEGACY_READ = {
    "hikvision_check_vmd",
    "hikvision_container_logs",
    "hikvision_container_status",
    "hikvision_device_info",
    "hikvision_get_alarm_server",
    "hikvision_get_event_config",
    "hikvision_get_motion_config",
    "hikvision_isapi_health",
    "hikvision_pipeline_diagnose",
    "hikvision_take_snapshot",
    "iot_check_device",
    "iot_discover_devices",
    "iot_find_device_by_name",
    "iot_get_device_info",
    "iot_get_device_power",
    "iot_get_full_info",
    "iot_get_wifi_config",
    "iot_list_devices",
    "iot_mqtt_get_state",
    "iot_tuya_cloud_list",
    "iot_tuya_detect_version",
    "iot_tuya_get_dps",
    "iot_tuya_monitor",
    "iot_tuya_scan_ports",
    "iot_tuya_verify_dps",
    "openhasp_check_backlight",
    "openhasp_detect",
    "openhasp_download_file",
    "openhasp_get_config",
    "openhasp_get_pages",
    "openhasp_health",
    "openhasp_screenshot",
    "openhasp_status",
    "openhasp_validate_config",
}
_LEGACY_WRITE = {
    "hikvision_open_gate",
    "hikvision_set_motion_detection",
    "hikvision_snapshot_to_file",
    "iot_configure_mqtt",
    "iot_mqtt_publish",
    "iot_set_brightness",
    "iot_set_flags",
    "iot_set_friendly_name",
    "iot_set_gpio",
    "iot_set_name",
    "iot_set_power",
    "iot_set_startup_command",
    "iot_start_ha_discovery",
    "iot_tuya_cloud_control",
    "iot_tuya_cloud_refresh_keys",
    "iot_tuya_remove",
    "iot_tuya_set_dp",
    "openhasp_backlight_set",
    "openhasp_config_set",
    "openhasp_hardware_test",
    "openhasp_idle_reset",
    "openhasp_jsonl_send",
    "openhasp_page_set",
    "openhasp_telnet",
    "openhasp_upload_file",
}
_REVIEWED_LEGACY = _LEGACY_DESTRUCTIVE | _LEGACY_NONE_READ | _LEGACY_READ | _LEGACY_WRITE
_MOCK_CLASSIFICATION = {
    "mock_get_state": ("read", "READ"),
    "mock_set_power": ("write", "WRITE"),
    "mock_capture_snapshot": ("write", "SENSITIVE"),
}

_NON_TARGET_BOUND_CAPABILITIES = {
    "describe_iot_capabilities",
    "iot_list_devices",
    "iot_find_device_by_name",
    "iot_mqtt_get_state",
    "iot_mqtt_build_command_topic",
    "iot_tuya_cloud_list",
    "iot_tuya_scan_ports",
    "hikvision_take_snapshot",
    "hikvision_device_info",
    "hikvision_get_motion_config",
    "hikvision_get_event_config",
    "hikvision_get_alarm_server",
}
_DANGEROUS_NAMES = {
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
_PRIVILEGED_NAMES = {
    "hikvision_container_status",
    "hikvision_container_logs",
    "hikvision_check_vmd",
    "hikvision_restart_container",
    "hikvision_isapi_health",
    "hikvision_pipeline_diagnose",
}
_CONFIDENTIALITY_OVERRIDES = {
    "hikvision_take_snapshot": "personal",
    "hikvision_snapshot_to_file": "personal",
    "hikvision_container_logs": "sensitive",
    "hikvision_get_alarm_server": "sensitive",
    "openhasp_screenshot": "personal",
    "iot_tuya_cloud_refresh_keys": "credential",
    "iot_configure_mqtt": "credential",
    "mock_capture_snapshot": "personal",
}
_EXPLICIT_SCOPE_OVERRIDES: dict[str, tuple[str, ...]] = {
    "mock_get_state": ("devices:read",),
    "mock_set_power": ("devices:power:write",),
    "mock_capture_snapshot": ("camera:snapshot:sensitive",),
    "artifact_read": ("devices:sensitive",),
    "hikvision_take_snapshot": ("camera:snapshot:sensitive",),
    "hikvision_snapshot_to_file": ("camera:snapshot:sensitive",),
    "hikvision_open_gate": ("camera:gate:write",),
    "iot_set_power": ("devices:power:write",),
    "iot_set_brightness": ("devices:brightness:write",),
    "iot_configure_mqtt": ("devices:mqtt:write",),
    "iot_mqtt_publish": ("devices:mqtt:publish",),
    "iot_tuya_cloud_refresh_keys": ("devices:credentials:write",),
}

ARTIFACT_READ_MANIFEST: dict[str, Any] = {
    "schema_version": 1,
    "id": "artifact_read",
    "name": "artifact_read",
    "description": "Read a principal-bound artifact by opaque identifier.",
    "operation_kind": "read",
    "risk": "high",
    "determinism": "environment-dependent",
    "latency": "interactive",
    "impact": "none",
    "active_state": "active",
    "retryable": False,
    "idempotent": False,
    "reversible": False,
    "requires_confirmation": False,
    "idempotency_key_required": False,
    "authorization_scopes": ["devices:sensitive"],
    "concurrency": {"scope": "resource", "limit": 4},
    "max_response_bytes": SERVER_HARD_MAX_RESPONSE_BYTES,
    "extensions": {
        "confidentiality": "sensitive",
        "availability": "available",
        "timeout_ms": 5_000,
        "concurrency_key_argument": "artifact_id",
        "target_binding": deepcopy(_NON_TARGET_BINDING),
        "component_kind": "resource",
        "component_identity": "artifact://{artifact_id}",
    },
}
PUBLIC_RESOURCE_COMPONENTS = {"artifact://{artifact_id}": "artifact_read"}


class ManifestError(ValueError):
    """Raised when a capability manifest is incomplete or inconsistent."""


def _expected_legacy_classification(name: str) -> tuple[str, str] | None:
    if name in _MOCK_CLASSIFICATION:
        return _MOCK_CLASSIFICATION[name]
    if name in _LEGACY_DESTRUCTIVE:
        return "destructive", "DESTRUCTIVE"
    if name in _LEGACY_NONE_READ:
        return "none", "READ"
    if name in _LEGACY_READ:
        return "read", "READ"
    if name in _LEGACY_WRITE:
        return "write", "WRITE"
    return None


def _require_legacy_classification(name: str, raw: Mapping[str, Any]) -> tuple[str, str]:
    expected = _expected_legacy_classification(name)
    if expected is None:
        raise ManifestError(f"{name}: legacy capability is not in the reviewed allowlist")
    if "side_effects" not in raw or "risk" not in raw:
        raise ManifestError(f"{name}: legacy risk and side_effects are required")
    observed = str(raw["side_effects"]).lower(), str(raw["risk"]).upper()
    if observed != expected:
        raise ManifestError(
            f"{name}: legacy safety classification changed: expected {expected}, got {observed}"
        )
    return expected


def _operation_kind(name: str, raw: Mapping[str, Any]) -> str:
    side_effects, _risk = _require_legacy_classification(name, raw)
    if name == "iot_discover_devices":
        return "write"
    if side_effects == "destructive":
        return "destructive"
    if side_effects == "write":
        return "write"
    return "read"


def _risk(name: str, raw: Mapping[str, Any], operation_kind: str) -> str:
    _side_effects, legacy_risk = _require_legacy_classification(name, raw)
    if name in _DANGEROUS_NAMES or legacy_risk == "DESTRUCTIVE":
        return "critical"
    if legacy_risk == "SENSITIVE":
        return "high"
    if legacy_risk == "WRITE" or operation_kind == "write":
        return "medium"
    if legacy_risk == "READ":
        return "low"
    raise ManifestError(f"{name}: unsupported legacy risk")


def _determinism(value: Any) -> str:
    if value is None:
        raise ManifestError("legacy determinism is required")
    raw = str(value).lower()
    if raw == "deterministic":
        return "deterministic"
    if raw in {"nondeterministic", "non-deterministic"}:
        return "nondeterministic"
    if raw in {"env-dependent", "environment-dependent", "eventually-consistent"}:
        return "environment-dependent"
    raise ManifestError(f"unsupported legacy determinism: {value}")


def _latency(value: Any) -> str:
    if value is None:
        raise ManifestError("legacy latency is required")
    raw = str(value).lower()
    if raw in {"instant", "fast", "moderate", "local", "interactive"}:
        return "interactive"
    if raw in {"slow", "long-running", "long_running", "bounded-long"}:
        return "bounded-long"
    if raw in {"background", "async"}:
        return "background"
    raise ManifestError(f"unsupported legacy latency: {value}")


def _confidentiality(name: str, raw: Mapping[str, Any]) -> str:
    if name not in _CONFIDENTIALITY_OVERRIDES and not ({"confidentiality", "privacy"} & raw.keys()):
        raise ManifestError(f"{name}: legacy privacy classification is required")
    value = _CONFIDENTIALITY_OVERRIDES.get(
        name, str(raw.get("confidentiality", raw.get("privacy")))
    ).lower()
    if value == "none":
        return "public"
    if value not in {"public", "internal", "metadata", "personal", "sensitive", "credential"}:
        raise ManifestError(f"{name}: unsupported confidentiality classification {value!r}")
    return value


def _authorization_scopes(
    name: str,
    raw: Mapping[str, Any],
    operation_kind: str,
    confidentiality: str,
) -> list[str]:
    if _expected_legacy_classification(name) is None:
        raise ManifestError(f"{name}: scopes require reviewed capability classification")
    declared = raw.get("authorization_scopes")
    if declared is not None:
        if (
            not isinstance(declared, list | tuple)
            or not declared
            or not all(isinstance(item, str) and item for item in declared)
        ):
            raise ManifestError(f"{name}: invalid authorization_scopes")
        return sorted(set(declared))
    if name in _EXPLICIT_SCOPE_OVERRIDES:
        return list(_EXPLICIT_SCOPE_OVERRIDES[name])
    if operation_kind == "read":
        result = ["devices:read"]
        if confidentiality in {"personal", "sensitive", "credential"}:
            result.append("devices:sensitive")
        return result
    return ["devices:dangerous"] if operation_kind == "destructive" else ["devices:write"]


def _concurrency(name: str, raw: Mapping[str, Any]) -> dict[str, int | str]:
    if _expected_legacy_classification(name) is None:
        raise ManifestError(f"{name}: concurrency requires reviewed capability classification")
    declared = raw.get("concurrency")
    if declared is not None:
        if not isinstance(declared, Mapping):
            raise ManifestError(f"{name}: concurrency must be an object")
        scope = declared.get("scope")
        limit = declared.get("limit")
        if (
            scope not in ALLOWED_CONCURRENCY_SCOPES
            or not isinstance(limit, int)
            or isinstance(limit, bool)
            or limit < 1
        ):
            raise ManifestError(f"{name}: invalid concurrency declaration")
        return dict(declared)
    scope = "capability" if name in _NON_TARGET_BOUND_CAPABILITIES else "target"
    legacy_scope = raw.get("concurrency_scope")
    if legacy_scope is not None:
        if legacy_scope not in ALLOWED_CONCURRENCY_SCOPES:
            raise ManifestError(f"{name}: invalid legacy concurrency_scope")
        if name in _NON_TARGET_BOUND_CAPABILITIES and legacy_scope == "target":
            scope = "capability"
        else:
            scope = str(legacy_scope)
    return {"scope": scope, "limit": 1}


def _legacy_lifecycle(name: str, raw: Mapping[str, Any], operation_kind: str) -> tuple[str, str]:
    raw_state = str(raw.get("active_state", "active")).lower()
    availability = "available"
    if raw_state in {"degraded", "unavailable"}:
        availability, raw_state = raw_state, "active"
    lifecycle = "deprecated" if raw_state == "deprecated" else "active"
    legacy_mutation = operation_kind != "read" and not name.startswith("mock_")
    forced_inactive = (
        name in _DANGEROUS_NAMES
        or name in _PRIVILEGED_NAMES
        or name.startswith("openhasp_")
        or legacy_mutation
    )
    if raw_state in {"disabled", "inactive"} or forced_inactive:
        lifecycle = "inactive"
    return lifecycle, availability


def _approval_policy() -> dict[str, Any]:
    return {
        "enforcement": "server-side",
        "record_required": True,
        "record_ttl_seconds": 300,
        "binds": sorted(_APPROVAL_BINDS),
    }


def _canonical_manifest(name: str, raw: Mapping[str, Any]) -> dict[str, Any]:
    _require_legacy_classification(name, raw)
    for field in ("version", "timeout_ms", "determinism", "latency", "cost", "impact"):
        if field not in raw:
            raise ManifestError(f"{name}: legacy {field} is required")
    operation_kind = _operation_kind(name, raw)
    confidentiality = _confidentiality(name, raw)
    active_state, availability = _legacy_lifecycle(name, raw, operation_kind)
    is_mock = name.startswith("mock_")
    retryable = bool(raw.get("retryable", False)) if is_mock and operation_kind != "read" else False
    idempotent = (
        bool(raw.get("idempotent", False)) if is_mock and operation_kind != "read" else False
    )
    reversible = (
        bool(raw.get("reversible", False)) if is_mock and operation_kind != "read" else False
    )
    if active_state != "active":
        retryable = False
    requires_confirmation = operation_kind == "destructive"
    extensions: dict[str, Any] = {
        "legacy_contract_version": str(raw["version"]),
        "legacy_risk": str(raw["risk"]),
        "legacy_side_effects": str(raw["side_effects"]),
        "confidentiality": confidentiality,
        "availability": availability,
        "timeout_ms": int(raw["timeout_ms"]),
        "cost": str(raw["cost"]),
        "target_binding": deepcopy(
            raw.get(
                "target_binding",
                _NON_TARGET_BINDING
                if name in _NON_TARGET_BOUND_CAPABILITIES
                else _DEFAULT_TARGET_BINDING,
            )
        ),
        "compatibility_boundary": "reviewed-legacy-manifest-translator",
    }
    if retryable:
        extensions["retryable_rationale"] = (
            "Mock capability has deterministic local state and explicit target state."
        )
    if idempotent:
        extensions["idempotent_rationale"] = (
            "Mock capability sets an explicit value instead of toggling state."
        )
    if reversible:
        extensions["reversible_rationale"] = (
            "Mock state can be restored by setting the previous explicit value."
        )
    impact = "none" if operation_kind == "read" else "local"
    if operation_kind == "destructive" or str(raw["impact"]) in {"persistent", "service_outage"}:
        impact = "external"
    result: dict[str, Any] = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "id": name,
        "name": name,
        "description": str(raw.get("description") or f"Local home device capability: {name}."),
        "operation_kind": operation_kind,
        "risk": _risk(name, raw, operation_kind),
        "determinism": _determinism(raw["determinism"]),
        "latency": _latency(raw["latency"]),
        "impact": impact,
        "active_state": active_state,
        "retryable": retryable,
        "idempotent": idempotent,
        "reversible": reversible,
        "requires_confirmation": requires_confirmation,
        "idempotency_key_required": retryable,
        "authorization_scopes": _authorization_scopes(name, raw, operation_kind, confidentiality),
        "concurrency": _concurrency(name, raw),
        "max_response_bytes": int(raw.get("max_response_bytes", DEFAULT_MAX_RESPONSE_BYTES)),
        "extensions": extensions,
    }
    if requires_confirmation:
        result["approval"] = _approval_policy()
    return result


def normalize_manifest(name: str, raw: Mapping[str, Any]) -> dict[str, Any]:
    manifest = (
        deepcopy(dict(raw))
        if raw.get("schema_version") == MANIFEST_SCHEMA_VERSION
        else _canonical_manifest(name, raw)
    )
    if manifest.get("id") != name:
        raise ManifestError(f"{name}: manifest id mismatch")
    validate_manifest(manifest)
    return manifest


def validate_manifest(manifest: Mapping[str, Any]) -> None:
    missing = _REQUIRED_FIELDS - set(manifest)
    if missing:
        raise ManifestError(f"missing {sorted(missing)}")
    unknown = set(manifest) - _ALLOWED_FIELDS
    if unknown:
        raise ManifestError(f"unknown canonical fields: {sorted(unknown)}")
    if manifest["schema_version"] != MANIFEST_SCHEMA_VERSION:
        raise ManifestError("unsupported capability schema_version")
    checks = (
        (manifest["operation_kind"] in ALLOWED_OPERATION_KINDS, "invalid operation_kind"),
        (manifest["risk"] in ALLOWED_RISKS, "invalid risk"),
        (manifest["determinism"] in ALLOWED_DETERMINISM, "invalid determinism"),
        (manifest["latency"] in ALLOWED_LATENCY, "invalid latency"),
        (manifest["impact"] in ALLOWED_IMPACT, "invalid impact"),
        (manifest["active_state"] in ALLOWED_ACTIVE_STATES, "invalid active_state"),
    )
    for valid, message in checks:
        if not valid:
            raise ManifestError(message)
    scopes = manifest["authorization_scopes"]
    if not isinstance(scopes, list) or not all(isinstance(item, str) and item for item in scopes):
        raise ManifestError("authorization_scopes must be a list of non-empty strings")
    if len(scopes) != len(set(scopes)):
        raise ManifestError("authorization_scopes must be unique")
    concurrency = manifest["concurrency"]
    if (
        not isinstance(concurrency, Mapping)
        or concurrency.get("scope") not in ALLOWED_CONCURRENCY_SCOPES
    ):
        raise ManifestError("invalid concurrency")
    limit = concurrency.get("limit")
    if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
        raise ManifestError("concurrency.limit must be a positive integer")
    for optional in ("queue_limit", "global_limit"):
        value = concurrency.get(optional)
        minimum = 0 if optional == "queue_limit" else 1
        if value is not None and (
            not isinstance(value, int) or isinstance(value, bool) or value < minimum
        ):
            raise ManifestError(f"concurrency.{optional} is outside canonical bounds")
    maximum = manifest["max_response_bytes"]
    if not isinstance(maximum, int) or isinstance(maximum, bool) or not 1 <= maximum <= 16_777_216:
        raise ManifestError("max_response_bytes is outside canonical bounds")
    operation = manifest["operation_kind"]
    if operation == "read":
        if manifest["impact"] != "none":
            raise ManifestError("read capability impact must be none")
        for flag in (
            "retryable",
            "idempotent",
            "reversible",
            "requires_confirmation",
            "idempotency_key_required",
        ):
            if manifest[flag] is not False:
                raise ManifestError(f"read capability requires {flag}=false")
    else:
        if not scopes:
            raise ManifestError("mutating capability requires authorization_scopes")
        if manifest["impact"] == "none":
            raise ManifestError("mutating capability impact cannot be none")
    if operation == "destructive":
        if manifest["risk"] not in {"high", "critical"}:
            raise ManifestError("destructive capability risk must be high or critical")
        if manifest["requires_confirmation"] is not True:
            raise ManifestError("destructive capability requires confirmation")
    if manifest["retryable"] and (
        not manifest["idempotent"] or not manifest["idempotency_key_required"]
    ):
        raise ManifestError("retryable requires idempotent and idempotency key")
    if manifest["active_state"] != "active" and manifest["retryable"]:
        raise ManifestError("inactive/deprecated capability cannot be retryable")
    approval = manifest.get("approval")
    if manifest["requires_confirmation"]:
        if not isinstance(approval, Mapping):
            raise ManifestError("confirmation-protected capability requires approval")
        binds = approval.get("binds")
        observed = set(binds) if isinstance(binds, list) else set()
        if not _APPROVAL_BINDS.issubset(observed):
            raise ManifestError("approval.binds is incomplete")
    elif approval is not None:
        raise ManifestError("approval is forbidden when confirmation is false")


def normalize_catalog(raw_catalog: Mapping[str, Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for name, raw in raw_catalog.items():
        declared = raw.get("id", raw.get("name"))
        if declared not in {None, name}:
            raise ManifestError(f"{name}: manifest identifier mismatch")
        result[name] = normalize_manifest(name, raw)
    return result


def manifest_timeout_seconds(manifest: Mapping[str, Any]) -> float:
    extensions = manifest.get("extensions")
    value = extensions.get("timeout_ms", 10_000) if isinstance(extensions, Mapping) else 10_000
    try:
        milliseconds = int(value)
    except (TypeError, ValueError) as exc:
        raise ManifestError("extensions.timeout_ms must be an integer") from exc
    if milliseconds <= 0:
        raise ManifestError("extensions.timeout_ms must be positive")
    return milliseconds / 1000


def manifest_availability(manifest: Mapping[str, Any]) -> str:
    extensions = manifest.get("extensions")
    if not isinstance(extensions, Mapping):
        return "available"
    value = str(extensions.get("availability", "available"))
    return value if value in {"available", "degraded", "unavailable"} else "unavailable"


def is_runtime_active(manifest: Mapping[str, Any]) -> bool:
    return (
        manifest.get("active_state") == "active"
        and manifest_availability(manifest) != "unavailable"
    )
