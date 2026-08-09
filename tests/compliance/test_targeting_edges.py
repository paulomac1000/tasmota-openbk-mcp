from __future__ import annotations

import ipaddress
from pathlib import Path

import pytest

from local_home_devices_mcp.config import Settings
from local_home_devices_mcp.targeting import (
    AmbiguousTarget,
    BoundTarget,
    TargetError,
    TargetNotAuthorized,
    TargetNotFound,
    normalize_selector,
    resolve_exact_target,
    revalidate_binding,
    target_id_for,
    validate_address,
)

pytestmark = pytest.mark.unit


def settings(tmp_path: Path, *, direct_ip: bool = False) -> Settings:
    return Settings(
        transport="stdio",
        bind_host="127.0.0.1",
        port=9102,
        mcp_path="/mcp",
        write_enabled=True,
        dangerous_enabled=False,
        allow_direct_ip_targets=direct_ip,
        allowed_networks=(ipaddress.ip_network("192.0.2.0/24"),),
        artifact_root=tmp_path,
        max_artifact_bytes=1024,
        max_artifact_store_bytes=4096,
        artifact_retention_seconds=3600,
        read_token=None,
        write_token=None,
        admin_token=None,
        trusted_proxy_tls=False,
        mock_mode=True,
    )


def device(**overrides):
    value = {
        "target_id": "dev_light",
        "name": "Kitchen Light",
        "ip": "192.0.2.10",
        "mac": "AA:BB:CC:DD:EE:FF",
        "type": "tasmota",
    }
    value.update(overrides)
    return value


def test_selector_and_address_validation_edges(tmp_path: Path):
    config = settings(tmp_path)
    assert normalize_selector(" Kitchen Light ") == "kitchen light"
    assert normalize_selector("192.0.2.10") == "192.0.2.10"
    for selector in ("", "bad/name"):
        with pytest.raises(TargetError):
            normalize_selector(selector)
    for address in ("not-an-ip", "::1", "127.0.0.1", "224.0.0.1", "198.51.100.1"):
        with pytest.raises(TargetError):
            validate_address(address, config)


def test_exact_resolution_and_failure_modes(tmp_path: Path):
    config = settings(tmp_path)
    record = device()
    by_name = resolve_exact_target("Kitchen Light", [record], config)
    by_id = resolve_exact_target("dev_light", [record], config)
    assert by_name == by_id
    assert by_name.target_id == "dev_light"

    with pytest.raises(TargetNotFound, match="direct IP targets are disabled"):
        resolve_exact_target("192.0.2.10", [record], config)
    with pytest.raises(TargetNotFound, match="bound to a discovered"):
        resolve_exact_target("192.0.2.11", [], settings(tmp_path, direct_ip=True))
    with pytest.raises(TargetNotFound, match="no exact"):
        resolve_exact_target("missing", [record], config)
    with pytest.raises(AmbiguousTarget):
        resolve_exact_target("Kitchen Light", [record, device(target_id="dev_2")], config)


def test_fingerprint_target_id_and_revalidation(tmp_path: Path):
    config = settings(tmp_path)
    generated = device(target_id="")
    generated_id = target_id_for(generated)
    assert generated_id.startswith("dev_")
    assert target_id_for(device(target_id="", name="Renamed Light", type="openbk")) == generated_id
    with pytest.raises(TargetError, match="stable identity"):
        target_id_for({"ip": "192.0.2.10", "name": "Name Only"})

    bound = resolve_exact_target("dev_light", [device()], config)
    revalidate_binding(bound, device(), config)
    revalidate_binding(bound, device(name="Renamed Light", type="openbk"), config)
    with pytest.raises(TargetNotAuthorized, match="address changed"):
        revalidate_binding(bound, device(ip="192.0.2.11"), config)
    with pytest.raises(TargetNotAuthorized, match="identity changed"):
        revalidate_binding(bound, device(mac="00:00:00:00:00:00"), config)

    manual = BoundTarget("dev_light", "192.0.2.10", "Kitchen", bound.fingerprint)
    revalidate_binding(manual, device(), config)
