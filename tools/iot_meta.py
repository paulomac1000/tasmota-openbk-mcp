"""Protocol-visible capability discovery backed by the application manifest."""

from __future__ import annotations

from typing import Any

from local_home_devices_mcp.composition import package_version
from local_home_devices_mcp.config import load_settings
from local_home_devices_mcp.manifests import normalize_catalog
from tools.constants import (
    TOOL_MANIFESTS,
    increment_tool_count,
    inject_tool_risk_prefix,
    start_tool_context,
)

__all__ = ["register_iot_meta_tools", "_describe_capabilities"]


def _describe_capabilities() -> dict[str, Any]:
    settings = load_settings()
    catalog = normalize_catalog(TOOL_MANIFESTS)
    active = [manifest for manifest in catalog.values() if manifest["active_state"] == "active"]
    return {
        "server": "local-home-devices-mcp",
        "schema_version": "2.1",
        "server_version": package_version(),
        "sdk_family": "fastmcp",
        "sdk_version": "3.4.4",
        "supported_transports": ["stdio", "streamable-http"],
        "active_transport": settings.transport,
        "supported_count": len(catalog),
        "active_count": len(active),
        "supported_capabilities": list(catalog.values()),
        "active_capabilities": active,
    }


def register_iot_meta_tools(mcp: Any) -> None:
    @mcp.tool()
    @inject_tool_risk_prefix
    def describe_iot_capabilities() -> dict[str, Any]:
        """Describe supported and active capabilities through MCP."""
        start_tool_context()
        increment_tool_count("describe_iot_capabilities")
        return _describe_capabilities()
