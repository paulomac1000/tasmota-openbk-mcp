"""Integration test conftest - real MQTT broker + devices, skip if not configured."""

import asyncio
import inspect
import os
from pathlib import Path

import pytest

env_paths = [Path("/app/.env"), Path(".env")]
for env_path in env_paths:
    if env_path.exists():
        try:
            with open(env_path) as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        key, value = line.split("=", 1)
                        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
        except Exception:
            pass

MQTT_BROKER = os.getenv("MQTT_BROKER", "")

_PLACEHOLDER_VALUES = {"", "your_broker_here"}

iot_configured = bool(MQTT_BROKER) and MQTT_BROKER not in _PLACEHOLDER_VALUES


def _run_async(func, *args, **kwargs):
    """Run an async function from sync context."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop is None:
        return asyncio.run(func(*args, **kwargs))
    else:
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor() as ex:
            return ex.submit(asyncio.run, func(*args, **kwargs)).result()


class MCPWrapper:
    """Simple wrapper to call tools on a FastMCP instance."""

    def __init__(self, mcp):
        self._mcp = mcp

    def call_tool(self, tool_name, **kwargs):
        """Look up and execute a registered tool by name."""
        # FastMCP 3.x: get_tool is async, tool_manager._tools removed
        if hasattr(self._mcp, "_tool_manager") and hasattr(self._mcp._tool_manager, "_tools"):
            tools = self._mcp._tool_manager._tools
            tool = tools.get(tool_name)
        elif hasattr(self._mcp, "_tools"):
            tool = self._mcp._tools.get(tool_name)
        else:
            # FastMCP 3.x: use async get_tool
            try:
                tool = asyncio.run(self._mcp.get_tool(tool_name))
            except Exception:
                tool = None

        if tool is None:
            # Get available tools for error message
            try:
                all_tools = asyncio.run(self._mcp.list_tools())
                available = [t.name for t in all_tools]
            except Exception:
                available = []
            raise ValueError(f"Tool '{tool_name}' not found among {available}")

        # FastMCP 3.x tool functions may have a different wrapper
        fn = getattr(tool, "fn", tool) if not isinstance(tool, dict) else tool
        if inspect.iscoroutinefunction(fn):
            return _run_async(fn, **kwargs)
        return fn(**kwargs)


@pytest.fixture(scope="session")
def mcp_client():
    """Create real MCP server and return a call_tool wrapper."""
    from unittest.mock import patch

    from fastmcp import FastMCP

    from tools.iot_config import register_iot_config_tools
    from tools.iot_control import register_iot_control_tools
    from tools.iot_devices import register_iot_device_tools
    from tools.iot_discovery import register_iot_discovery_tools
    from tools.iot_hikvision import register_hikvision_tools
    from tools.iot_mqtt import register_iot_mqtt_tools
    from tools.iot_openhasp import register_openhasp_tools
    from tools.iot_tuya import register_iot_tuya_tools

    # Write-tool error-path tests need the guard enabled so calls reach
    # the tool logic (name resolution, validation) and not the gate.
    with patch("tools.constants.ENABLE_WRITE_OPERATIONS", True):
        mcp = FastMCP("IoT-Integration-Test")

        register_iot_config_tools(mcp)
        register_iot_device_tools(mcp)
        register_iot_discovery_tools(mcp)
        register_iot_control_tools(mcp)
        register_iot_mqtt_tools(mcp)
        register_iot_tuya_tools(mcp)
        register_openhasp_tools(mcp)
        register_hikvision_tools(mcp)

        yield MCPWrapper(mcp)


@pytest.fixture(scope="module")
def iot_configured_flag():
    """Returns True if MQTT broker is configured."""
    return iot_configured
