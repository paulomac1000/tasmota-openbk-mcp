from __future__ import annotations

from copy import deepcopy

import pytest

from local_home_devices_mcp.manifests import ManifestError, normalize_catalog, normalize_manifest
from local_home_devices_mcp.public_catalog import build_public_catalog
from tools.constants import TOOL_MANIFESTS


def test_complete_legacy_catalog_normalizes_fail_closed() -> None:
    catalog = normalize_catalog(TOOL_MANIFESTS)
    assert len(catalog) == len(TOOL_MANIFESTS)
    assert set(catalog) == set(TOOL_MANIFESTS)


def test_unknown_legacy_capability_never_defaults_to_read() -> None:
    legacy = deepcopy(next(iter(TOOL_MANIFESTS.values())))
    legacy["name"] = "new_unreviewed_capability"
    with pytest.raises(ManifestError, match="reviewed allowlist"):
        normalize_manifest("new_unreviewed_capability", legacy)


def test_public_catalog_includes_governed_artifact_resource() -> None:
    catalog = build_public_catalog(TOOL_MANIFESTS)
    artifact = catalog["artifact_read"]
    assert len(catalog) == len(TOOL_MANIFESTS) + 1
    assert artifact["extensions"]["component_kind"] == "resource"
    assert artifact["extensions"]["component_identity"] == "artifact://{artifact_id}"


def test_every_inactive_capability_has_machine_readable_reason() -> None:
    catalog = build_public_catalog(TOOL_MANIFESTS)
    inactive = [m for m in catalog.values() if m["active_state"] == "inactive"]
    assert inactive
    assert all(m["extensions"].get("availability_reason") for m in inactive)
    assert all(m["extensions"].get("inactive_reason") for m in inactive)
