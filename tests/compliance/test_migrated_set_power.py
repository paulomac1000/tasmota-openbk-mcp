from __future__ import annotations

import ipaddress
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from local_home_devices_mcp.config import Settings
from local_home_devices_mcp.legacy_compat import _wrap
from local_home_devices_mcp.policy import OperationGate, Principal
from local_home_devices_mcp.targeting import BoundTarget
from tools.constants import TOOL_MANIFESTS
from tools.iot_control import _set_power

pytestmark = pytest.mark.unit


class Resolver:
    def __init__(self) -> None:
        self.revalidated = 0

    async def resolve(self, selector: str) -> BoundTarget:
        assert selector in {"Kitchen Light", "dev_kitchen"}
        return BoundTarget("dev_kitchen", "192.168.1.40", "Kitchen Light", "fp-kitchen")

    async def revalidate(self, target: BoundTarget) -> None:
        assert target.target_id == "dev_kitchen"
        self.revalidated += 1


def settings(tmp_path: Path) -> Settings:
    return Settings(
        transport="stdio", bind_host="127.0.0.1", port=9102, mcp_path="/mcp",
        write_enabled=True, dangerous_enabled=False, allow_direct_ip_targets=False,
        allowed_networks=(ipaddress.ip_network("192.168.0.0/16"),),
        artifact_root=tmp_path, max_artifact_bytes=1024, max_artifact_store_bytes=4096,
        artifact_retention_seconds=3600, read_token=None, write_token=None, admin_token=None,
        trusted_proxy_tls=False, mock_mode=False,
    )


@pytest.mark.asyncio
async def test_explicit_set_power_is_target_bound_and_typed(tmp_path: Path):
    resolver = Resolver()
    gate = OperationGate(settings(tmp_path), TOOL_MANIFESTS, target_resolver=resolver)
    principal = Principal("operator", frozenset({"devices:admin"}), "stdio")
    response = MagicMock(status_code=200)
    response.json.return_value = {"POWER": "ON"}

    with (
        patch("tools.iot_discovery._resolve_ip", return_value="192.168.1.40"),
        patch("tools.iot_discovery._detect_device_type", return_value="tasmota"),
        patch("tools.iot_control.requests.get", return_value=response),
    ):
        result = await gate.invoke_async(
            "iot_set_power",
            _wrap(_set_power),
            {"identifier": "Kitchen Light", "state": "ON"},
            principal,
        )

    assert result["actual_state"] == "ON"
    assert result["ip"] == "192.168.1.40"
    assert resolver.revalidated == 1
    assert gate.manifest("iot_set_power")["active_state"] == "active"
    assert gate.manifest("iot_set_power")["idempotency_mechanism"] == "explicit-target-state"
