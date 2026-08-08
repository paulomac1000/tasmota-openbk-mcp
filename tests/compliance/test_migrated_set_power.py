from __future__ import annotations

import ipaddress
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from local_home_devices_mcp.config import Settings
from local_home_devices_mcp.legacy_compat import _wrap, install_legacy_safety
from local_home_devices_mcp.mock_runtime import MOCK_MANIFESTS
from local_home_devices_mcp.policy import CapabilityUnavailable, OperationGate, Principal
from local_home_devices_mcp.targeting import BoundTarget
from tools.constants import TOOL_MANIFESTS

pytestmark = pytest.mark.unit


class SwappingResolver:
    def __init__(self, cache: list[dict[str, str]]) -> None:
        self.cache = cache
        self.revalidated = 0

    async def resolve(self, selector: str) -> BoundTarget:
        assert selector == "Kitchen Light"
        return BoundTarget("dev_kitchen", "192.168.1.40", "Kitchen Light", "fp-kitchen")

    async def revalidate(self, target: BoundTarget) -> None:
        assert target.target_id == "dev_kitchen"
        self.revalidated += 1
        self.cache[:] = [
            {
                "target_id": "dev_other",
                "name": "Kitchen Light",
                "ip": "192.168.1.99",
                "mac": "00:11:22:33:44:55",
                "type": "tasmota",
            }
        ]


def settings(tmp_path: Path) -> Settings:
    return Settings(
        transport="stdio",
        bind_host="127.0.0.1",
        port=9102,
        mcp_path="/mcp",
        write_enabled=True,
        dangerous_enabled=False,
        allow_direct_ip_targets=False,
        allowed_networks=(ipaddress.ip_network("192.168.0.0/16"),),
        artifact_root=tmp_path,
        max_artifact_bytes=1024,
        max_artifact_store_bytes=4096,
        artifact_retention_seconds=3600,
        read_token=None,
        write_token=None,
        admin_token=None,
        trusted_proxy_tls=False,
        mock_mode=False,
    )


@pytest.mark.asyncio
async def test_legacy_io_uses_authorized_address_after_cache_swap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tools import iot_control, iot_discovery

    cache = [
        {
            "target_id": "dev_kitchen",
            "name": "Kitchen Light",
            "ip": "192.168.1.40",
            "mac": "AA:BB:CC:DD:EE:FF",
            "type": "tasmota",
        }
    ]
    resolver = SwappingResolver(cache)
    gate = OperationGate(settings(tmp_path), MOCK_MANIFESTS, target_resolver=resolver)
    principal = Principal("operator", frozenset({"devices:admin"}), "stdio")
    response = MagicMock(status_code=200)
    response.json.return_value = {"POWER": "ON"}

    original_power = iot_control._set_power
    original_brightness = iot_control._set_brightness
    original_resolve = iot_discovery._resolve_ip
    monkeypatch.setattr(iot_discovery, "_get_cached_devices", lambda: list(cache))
    install_legacy_safety(settings(tmp_path))
    safe_set_power = iot_control._set_power
    try:
        with (
            patch("tools.iot_discovery._detect_device_type", return_value="tasmota"),
            patch("tools.iot_control.requests.get", return_value=response) as request,
        ):
            result = await gate.invoke_async(
                "mock_set_power",
                _wrap(safe_set_power),
                {"identifier": "Kitchen Light", "state": "ON"},
                principal,
            )
    finally:
        iot_control._set_power = original_power
        iot_control._set_brightness = original_brightness
        iot_discovery._resolve_ip = original_resolve

    assert resolver.revalidated == 1
    assert cache[0]["ip"] == "192.168.1.99"
    request.assert_called_once_with("http://192.168.1.40/cm?cmnd=Power1%20ON", timeout=1.0)
    assert result["ip"] == "192.168.1.40"
    assert result["actual_state"] == "ON"


@pytest.mark.asyncio
async def test_multibackend_iot_set_power_stays_inactive_without_evidence(
    tmp_path: Path,
) -> None:
    gate = OperationGate(settings(tmp_path), TOOL_MANIFESTS, target_resolver=SwappingResolver([]))
    principal = Principal("operator", frozenset({"devices:admin"}), "stdio")

    manifest = gate.manifest("iot_set_power")
    assert manifest["active_state"] == "inactive"
    assert manifest["idempotent"] is False
    assert manifest["retryable"] is False
    assert manifest["authorization_scopes"] == ["devices:power:write"]

    with pytest.raises(CapabilityUnavailable, match="inactive"):
        await gate.invoke_async(
            "iot_set_power",
            lambda identifier, state: {"identifier": identifier, "state": state},
            {"identifier": "Kitchen Light", "state": "ON"},
            principal,
        )
