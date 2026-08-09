"""Single protocol-visible capability catalog for gates and discovery."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import Any

from .manifests import ARTIFACT_READ_MANIFEST, is_runtime_active, normalize_catalog

SUPPORTED_PROTOCOL_REVISIONS = ("2025-11-25",)
PUBLIC_RESOURCE_COMPONENTS = {"artifact://{artifact_id}": "artifact_read"}


def _availability_reason(name: str, manifest: Mapping[str, Any]) -> str:
    extensions = manifest.get("extensions")
    if isinstance(extensions, Mapping):
        explicit = extensions.get("availability_reason") or extensions.get("inactive_reason")
        if explicit:
            return str(explicit)
        availability = str(extensions.get("availability", "available"))
        if availability != "available":
            return f"backend-{availability}"
    if is_runtime_active(manifest):
        return "available"
    if name.startswith("openhasp_"):
        return "backend-host-binding-not-verified"
    if name.startswith("hikvision_") and name in {
        "hikvision_container_status",
        "hikvision_container_logs",
        "hikvision_check_vmd",
        "hikvision_restart_container",
        "hikvision_isapi_health",
        "hikvision_pipeline_diagnose",
    }:
        return "privileged-sidecar-not-configured"
    if manifest.get("operation_kind") in {"write", "destructive"}:
        return "mutation-evidence-not-yet-approved"
    return "runtime-disabled"


def _decorate(
    name: str,
    manifest: Mapping[str, Any],
    *,
    kind: str,
    identity: str,
) -> dict[str, Any]:
    result = deepcopy(dict(manifest))
    result["protocol_revisions"] = list(SUPPORTED_PROTOCOL_REVISIONS)
    extensions = dict(result.get("extensions") or {})
    extensions["component_kind"] = kind
    extensions["component_identity"] = identity
    extensions["availability_reason"] = _availability_reason(name, result)
    if result.get("active_state") != "active":
        extensions["inactive_reason"] = extensions["availability_reason"]
    result["extensions"] = extensions
    return result


def build_public_catalog(
    raw_tool_catalog: Mapping[str, Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Build the exact catalog consumed by OperationGate and discovery."""
    tools = normalize_catalog(raw_tool_catalog)
    if "artifact_read" in tools:
        raise ValueError("artifact_read is reserved for the governed resource")
    result = {
        name: _decorate(name, manifest, kind="tool", identity=name)
        for name, manifest in tools.items()
    }
    result["artifact_read"] = _decorate(
        "artifact_read",
        ARTIFACT_READ_MANIFEST,
        kind="resource",
        identity="artifact://{artifact_id}",
    )
    return result


def component_kind(manifest: Mapping[str, Any]) -> str:
    extensions = manifest.get("extensions")
    if not isinstance(extensions, Mapping):
        return "unknown"
    return str(extensions.get("component_kind", "unknown"))
