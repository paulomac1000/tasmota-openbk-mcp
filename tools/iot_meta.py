"""Protocol-visible capability discovery backed by the canonical public catalog."""

from __future__ import annotations

from typing import Any

from local_home_devices_mcp.composition import (
    ADOPTION_PROFILES,
    SUPPORTED_PROTOCOL_REVISIONS,
    package_version,
)
from local_home_devices_mcp.config import load_settings
from local_home_devices_mcp.manifests import (
    MANIFEST_SCHEMA_VERSION,
    is_runtime_active,
)
from local_home_devices_mcp.public_catalog import build_public_catalog
from tools.constants import (
    TOOL_MANIFESTS,
    increment_tool_count,
    inject_tool_risk_prefix,
    start_tool_context,
)

__all__ = ["_describe_capabilities", "register_iot_meta_tools"]


def _describe_capabilities() -> dict[str, Any]:
    settings = load_settings()
    catalog = build_public_catalog(TOOL_MANIFESTS)
    active = [manifest for manifest in catalog.values() if is_runtime_active(manifest)]
    return {
        "server": "local-home-devices-mcp",
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "server_version": package_version(),
        "sdk_family": "fastmcp",
        "sdk_version": "3.4.6",
        "profiles": ADOPTION_PROFILES,
        "protocol_revisions": SUPPORTED_PROTOCOL_REVISIONS,
        "supported_transports": ["stdio", "streamable-http"],
        "active_transport": settings.transport,
        "auth_profile": settings.auth_profile,
        "supported_count": len(catalog),
        "active_count": len(active),
        "supported_capabilities": list(catalog.values()),
        "active_capabilities": active,
    }


def register_iot_meta_tools(mcp: Any) -> None:
    @mcp.tool()  # type: ignore[untyped-decorator]
    @inject_tool_risk_prefix
    def describe_iot_capabilities() -> dict[str, Any]:
        """Describe supported and active public components through MCP."""
        start_tool_context()
        increment_tool_count("describe_iot_capabilities")
        return _describe_capabilities()
