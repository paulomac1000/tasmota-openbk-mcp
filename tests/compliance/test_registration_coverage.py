from __future__ import annotations

import pytest

from local_home_devices_mcp.manifests import (
    ARTIFACT_READ_MANIFEST,
    PUBLIC_RESOURCE_COMPONENTS,
    normalize_catalog,
)
from tools.constants import TOOL_MANIFESTS
from tools.iot_config import register_iot_config_tools
from tools.iot_control import register_iot_control_tools
from tools.iot_devices import register_iot_device_tools
from tools.iot_discovery import register_iot_discovery_tools
from tools.iot_hikvision import register_hikvision_tools
from tools.iot_meta import register_iot_meta_tools
from tools.iot_mqtt import register_iot_mqtt_tools
from tools.iot_openhasp import register_openhasp_tools
from tools.iot_tuya import register_iot_tuya_tools

pytestmark = pytest.mark.unit


class RegistryMCP:
    """Minimal decorator registry used for zero-I/O registration coverage."""

    def __init__(self) -> None:
        self.tools: dict[str, object] = {}

    def tool(self, *args, **kwargs):
        if args and callable(args[0]) and len(args) == 1 and not kwargs:
            function = args[0]
            self.tools[function.__name__] = function
            return function

        def decorator(function):
            self.tools[function.__name__] = function
            return function

        return decorator


def test_every_registered_tool_has_manifest_and_no_unexplained_orphans():
    registry = RegistryMCP()
    for register in (
        register_iot_config_tools,
        register_iot_control_tools,
        register_iot_device_tools,
        register_iot_discovery_tools,
        register_hikvision_tools,
        register_iot_meta_tools,
        register_iot_mqtt_tools,
        register_openhasp_tools,
        register_iot_tuya_tools,
    ):
        register(registry)
    registered = set(registry.tools)
    manifests = set(TOOL_MANIFESTS)
    # Every registered tool must have a manifest; the only tools that may be
    # absent are the Docker-socket-gated ones, whose registration depends on
    # whether /var/run/docker.sock exists in the test environment.
    assert registered <= manifests
    docker_gated = {
        "hikvision_check_vmd",
        "hikvision_container_logs",
        "hikvision_container_status",
        "hikvision_isapi_health",
        "hikvision_pipeline_diagnose",
        "hikvision_restart_container",
    }
    assert manifests - registered <= docker_gated


def test_public_resource_inventory_has_one_manifest_per_component():
    catalog = normalize_catalog(TOOL_MANIFESTS)
    catalog[ARTIFACT_READ_MANIFEST["id"]] = dict(ARTIFACT_READ_MANIFEST)

    assert PUBLIC_RESOURCE_COMPONENTS == {
        "artifact://{artifact_id}": "artifact_read",
    }
    resource_manifest_ids = set(PUBLIC_RESOURCE_COMPONENTS.values())
    assert resource_manifest_ids <= set(catalog)
    assert {catalog[item]["extensions"]["component_kind"] for item in resource_manifest_ids} == {
        "resource"
    }
