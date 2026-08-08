"""Canonical capability manifest translation and runtime helpers.

The application runtime exposes only the ai-skills capability contract.  The
legacy ``tools.constants.TOOL_MANIFESTS`` dictionaries are accepted solely at
this compatibility boundary and are translated into that contract.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

MANIFEST_SCHEMA_VERSION = 1
SERVER_HARD_MAX_RESPONSE_BYTES = 1024 * 1024
DEFAULT_MAX_RESPONSE_BYTES = 256 * 1024

ALLOWED_OPERATION_KINDS = {"read", "write", "destructive"}
ALLOWED_RISKS = {"low", "medium", "high", "critical"}
ALLOWED_DETERMINISM = {
    "deterministic",
    "environment-dependent",
    "nondeterministic",
}
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
_ALLOWED_FIELDS = _REQUIRED_FIELDS | {
    "approval",
    "protocol_revisions",
    "extensions",
}
_APPROVAL_BINDS = {
    "principal",
    "capability",
    "target",
    "arguments-digest",
    "expires-at",
}

_DEFAULT_TARGET_BINDING = {
    "selector": "exact-device-id-or-authorized-address",
    "revalidate_before_io": True,
    "silent_fallback": False,
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

_NON_TARGET_BINDING = {
    "selector": "none",
    "revalidate_before_io": False,
    "silent_fallback": False,
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
    "hikvision_take_snapshot": ("camera:snapshot:sensitive",),
    "hikvision_snapshot_to_file": ("camera:snapshot:sensitive",),
    "hikvision_open_gate": ("camera:gate:write",),
    "iot_set_power": ("devices:power:write",),
    "iot_set_brightness": ("devices:brightness:write",),
    "iot_configure_mqtt": ("devices:mqtt:write",),
    "iot_mqtt_publish": ("devices:mqtt:publish",),
    "iot_tuya_cloud_refresh_keys": ("devices:credentials:write",),
}


class ManifestError(ValueError):
    """Raised when a capability manifest is incomplete or inconsistent."""


def _operation_kind(name: str, raw: Mapping[str, Any]) -> str:
    if name == "iot_discover_devices":
        return "write"
    side_effects = str(raw.get("side_effects", "read")).lower()
    if side_effects == "destructive":
        return "destructive"
    if side_effects == "write":
        return "write"
    return "read"


def _risk(name: str, raw: Mapping[str, Any], operation_kind: str) -> str:
    if name in _DANGEROUS_NAMES:
        return "critical"
    raw_risk = str(raw.get("risk", "READ")).upper()
    if raw_risk == "DANGEROUS":
        return "critical"
    if raw_risk in {"DESTRUCTIVE", "SENSITIVE"}:
        return "high"
    if raw_risk == "WRITE" or operation_kind == "write":
        return "medium"
    return "low"


def _determinism(value: Any) -> str:
    raw = str(value or "environment-dependent").lower()
    if raw == "deterministic":
        return "deterministic"
    if raw in {"nondeterministic", "non-deterministic"}:
        return "nondeterministic"
    return "environment-dependent"


def _latency(value: Any) -> str:
    raw = str(value or "moderate").lower()
    if raw in {"slow", "long-running", "long_running"}:
        return "bounded-long"
    if raw in {"background", "async"}:
        return "background"
    return "interactive"


def _confidentiality(name: str, raw: Mapping[str, Any]) -> str:
    value = _CONFIDENTIALITY_OVERRIDES.get(
        name,
        str(raw.get("confidentiality", raw.get("privacy", "public"))),
    ).lower()
    if value == "none":
        return "public"
    if value not in {
        "public",
        "internal",
        "metadata",
        "personal",
        "sensitive",
        "credential",
    }:
        return "internal"
    return value


def _authorization_scopes(
    name: str,
    raw: Mapping[str, Any],
    operation_kind: str,
    confidentiality: str,
) -> list[str]:
    declared = raw.get("authorization_scopes")
    if isinstance(declared, (list, tuple)) and all(
        isinstance(item, str) and item for item in declared
    ):
        return sorted(set(declared))
    if name in _EXPLICIT_SCOPE_OVERRIDES:
        return list(_EXPLICIT_SCOPE_OVERRIDES[name])
    if operation_kind == "read":
        scopes = ["devices:read"]
        if confidentiality in {"personal", "sensitive", "credential"}:
            scopes.append("devices:sensitive")
        return scopes
    if operation_kind == "destructive":
        return ["devices:dangerous"]
    return ["devices:write"]


def _concurrency(
    name: str, raw: Mapping[str, Any], operation_kind: str
) -> dict[str, int | str]:
    declared = raw.get("concurrency")
    if isinstance(declared, Mapping):
        result = dict(declared)
        scope = str(result.get("scope", ""))
        limit = result.get("limit")
        if scope in ALLOWED_CONCURRENCY_SCOPES and isinstance(limit, int) and limit > 0:
            return result  # type: ignore[return-value]
    default_scope = (
        "capability" if name in _NON_TARGET_BOUND_CAPABILITIES else "target"
    )
    scope = str(raw.get("concurrency_scope", default_scope))
    if scope not in ALLOWED_CONCURRENCY_SCOPES:
        scope = default_scope
    if scope == "target" and name in _NON_TARGET_BOUND_CAPABILITIES:
        scope = "capability"
    return {"scope": scope, "limit": 1}


def _legacy_lifecycle(
    name: str,
    raw: Mapping[str, Any],
    operation_kind: str,
) -> tuple[str, str]:
    raw_state = str(raw.get("active_state", "active")).lower()
    availability = "available"
    if raw_state in {"degraded", "unavailable"}:
        availability = raw_state
        raw_state = "active"
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
    operation_kind = _operation_kind(name, raw)
    confidentiality = _confidentiality(name, raw)
    active_state, availability = _legacy_lifecycle(name, raw, operation_kind)
    is_mock = name.startswith("mock_")

    retryable = False
    idempotent = False
    reversible = False
    if is_mock and operation_kind != "read":
        retryable = bool(raw.get("retryable", False))
        idempotent = bool(raw.get("idempotent", False))
        reversible = bool(raw.get("reversible", False))
    if operation_kind == "read":
        retryable = idempotent = reversible = False
    if active_state != "active":
        retryable = False

    requires_confirmation = operation_kind == "destructive"
    extensions: dict[str, Any] = {
        "legacy_contract_version": str(raw.get("version", "unknown")),
        "legacy_risk": str(raw.get("risk", "READ")),
        "legacy_side_effects": str(raw.get("side_effects", "read")),
        "confidentiality": confidentiality,
        "availability": availability,
        "timeout_ms": int(raw.get("timeout_ms", 10_000)),
        "cost": str(raw.get("cost", "local-network")),
        "target_binding": deepcopy(
            raw.get(
                "target_binding",
                _NON_TARGET_BINDING
                if name in _NON_TARGET_BOUND_CAPABILITIES
                else _DEFAULT_TARGET_BINDING,
            )
        ),
        "compatibility_boundary": "legacy-manifest-translator",
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
    if operation_kind == "destructive" or str(raw.get("impact", "")) in {
        "persistent",
        "service_outage",
    }:
        impact = "external"

    result: dict[str, Any] = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "id": name,
        "name": name,
        "description": str(
            raw.get("description") or f"Local home device capability: {name}."
        ),
        "operation_kind": operation_kind,
        "risk": _risk(name, raw, operation_kind),
        "determinism": _determinism(raw.get("determinism")),
        "latency": _latency(raw.get("latency")),
        "impact": impact,
        "active_state": active_state,
        "retryable": retryable,
        "idempotent": idempotent,
        "reversible": reversible,
        "requires_confirmation": requires_confirmation,
        "idempotency_key_required": retryable,
        "authorization_scopes": _authorization_scopes(
            name,
            raw,
            operation_kind,
            confidentiality,
        ),
        "concurrency": _concurrency(name, raw, operation_kind),
        "max_response_bytes": int(
            raw.get("max_response_bytes", DEFAULT_MAX_RESPONSE_BYTES)
        ),
        "extensions": extensions,
    }
    if requires_confirmation:
        result["approval"] = _approval_policy()
    return result


def normalize_manifest(name: str, raw: Mapping[str, Any]) -> dict[str, Any]:
    """Return one canonical manifest; legacy input never leaks past this boundary."""
    if raw.get("schema_version") == MANIFEST_SCHEMA_VERSION:
        manifest = deepcopy(dict(raw))
    else:
        manifest = _canonical_manifest(name, raw)
    if manifest.get("id") != name:
        raise ManifestError(f"{name}: manifest id mismatch")
    validate_manifest(manifest)
    return manifest


def validate_manifest(manifest: Mapping[str, Any]) -> None:
    """Validate the canonical subset required by the runtime fail-closed."""
    missing = _REQUIRED_FIELDS - set(manifest)
    if missing:
        raise ManifestError(f"missing {sorted(missing)}")
    unknown = set(manifest) - _ALLOWED_FIELDS
    if unknown:
        raise ManifestError(f"unknown canonical fields: {sorted(unknown)}")
    if manifest["schema_version"] != MANIFEST_SCHEMA_VERSION:
        raise ManifestError("unsupported capability schema_version")
    if manifest["operation_kind"] not in ALLOWED_OPERATION_KINDS:
        raise ManifestError("invalid operation_kind")
    if manifest["risk"] not in ALLOWED_RISKS:
        raise ManifestError("invalid risk")
    if manifest["determinism"] not in ALLOWED_DETERMINISM:
        raise ManifestError("invalid determinism")
    if manifest["latency"] not in ALLOWED_LATENCY:
        raise ManifestError("invalid latency")
    if manifest["impact"] not in ALLOWED_IMPACT:
        raise ManifestError("invalid impact")
    if manifest["active_state"] not in ALLOWED_ACTIVE_STATES:
        raise ManifestError("invalid active_state")

    scopes = manifest["authorization_scopes"]
    if not isinstance(scopes, list) or not all(
        isinstance(item, str) and item for item in scopes
    ):
        raise ManifestError("authorization_scopes must be a list of non-empty strings")
    if len(scopes) != len(set(scopes)):
        raise ManifestError("authorization_scopes must be unique")

    concurrency = manifest["concurrency"]
    if not isinstance(concurrency, Mapping):
        raise ManifestError("concurrency must be an object")
    if concurrency.get("scope") not in ALLOWED_CONCURRENCY_SCOPES:
        raise ManifestError("invalid concurrency.scope")
    limit = concurrency.get("limit")
    if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
        raise ManifestError("concurrency.limit must be a positive integer")
    for optional in ("queue_limit", "global_limit"):
        value = concurrency.get(optional)
        if value is not None and (
            not isinstance(value, int)
            or isinstance(value, bool)
            or value < (0 if optional == "queue_limit" else 1)
        ):
            raise ManifestError(f"concurrency.{optional} is outside canonical bounds")

    maximum = manifest["max_response_bytes"]
    if (
        not isinstance(maximum, int)
        or isinstance(maximum, bool)
        or not 1 <= maximum <= 16_777_216
    ):
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
    if manifest["retryable"]:
        if not manifest["idempotent"] or not manifest["idempotency_key_required"]:
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


def normalize_catalog(
    raw_catalog: Mapping[str, Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Normalize a complete catalog and reject key/identifier mismatches."""
    result: dict[str, dict[str, Any]] = {}
    for name, raw in raw_catalog.items():
        declared = raw.get("id", raw.get("name"))
        if declared not in {None, name}:
            raise ManifestError(f"{name}: manifest identifier mismatch")
        result[name] = normalize_manifest(name, raw)
    return result


def manifest_timeout_seconds(manifest: Mapping[str, Any]) -> float:
    """Return the bounded compatibility timeout carried in extensions."""
    extensions = manifest.get("extensions")
    value = (
        extensions.get("timeout_ms", 10_000)
        if isinstance(extensions, Mapping)
        else 10_000
    )
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
    return (
        value
        if value in {"available", "degraded", "unavailable"}
        else "unavailable"
    )


def is_runtime_active(manifest: Mapping[str, Any]) -> bool:
    """Separate lifecycle state from transient runtime availability."""
    return (
        manifest.get("active_state") == "active"
        and manifest_availability(manifest) != "unavailable"
    )
