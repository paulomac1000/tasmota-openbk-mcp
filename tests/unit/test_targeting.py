from __future__ import annotations

import pytest

from local_home_devices_mcp.config import load_settings
from local_home_devices_mcp.targeting import (
    AmbiguousTarget,
    TargetNotAuthorized,
    TargetNotFound,
    resolve_exact_target,
    revalidate_binding,
)

pytestmark = pytest.mark.unit

DEVICES = [
    {"name": "Kitchen Light", "ip": "192.168.1.10", "mac": "AA:00:00:00:00:01", "type": "tasmota"},
    {"name": "Kitchen Plug", "ip": "192.168.1.11", "mac": "AA:00:00:00:00:02", "type": "openbk"},
]


def test_exact_name_resolves():
    target = resolve_exact_target("Kitchen Light", DEVICES, load_settings())
    assert target.address == "192.168.1.10"
    assert target.target_id.startswith("dev_")


def test_partial_name_never_selects_first_device():
    with pytest.raises(TargetNotFound):
        resolve_exact_target("Kitchen", DEVICES, load_settings())


def test_duplicate_exact_name_is_ambiguous():
    duplicate = [DEVICES[0], {**DEVICES[1], "name": "Kitchen Light"}]
    with pytest.raises(AmbiguousTarget):
        resolve_exact_target("Kitchen Light", duplicate, load_settings())


def test_direct_ip_is_disabled_by_default():
    with pytest.raises(TargetNotFound, match="direct IP"):
        resolve_exact_target("192.168.1.99", [], load_settings())


def test_direct_ip_must_be_bound_to_discovered_identity(monkeypatch):
    monkeypatch.setenv("MCP_ALLOW_DIRECT_IP_TARGETS", "1")
    with pytest.raises(TargetNotFound, match="stable target"):
        resolve_exact_target("192.168.1.99", [], load_settings())


def test_discovered_public_ip_is_not_authorized(monkeypatch):
    monkeypatch.setenv("MCP_ALLOW_DIRECT_IP_TARGETS", "1")
    public = [{"name": "bad", "ip": "8.8.8.8", "mac": "AA:BB:CC:DD:EE:FF"}]
    with pytest.raises(TargetNotAuthorized):
        resolve_exact_target("8.8.8.8", public, load_settings())


def test_binding_detects_identity_swap():
    target = resolve_exact_target("Kitchen Light", DEVICES, load_settings())
    swapped = {**DEVICES[0], "mac": "AA:00:00:00:00:FF"}
    with pytest.raises(TargetNotAuthorized, match="identity changed"):
        revalidate_binding(target, swapped, load_settings())
