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


class RegistryMCP:
    """Minimal public registration surface for adapter integration tests."""

    def __init__(self):
        self.tools = {}

    def tool(self, *args, **kwargs):
        def register(function):
            self.tools[kwargs.get("name", function.__name__)] = function
            return function
        if len(args) == 1 and callable(args[0]) and not kwargs:
            return register(args[0])
        return register


class MCPWrapper:
    """Call functions through the same public registry used during registration."""

    def __init__(self, mcp):
        self._mcp = mcp

    def call_tool(self, tool_name, **kwargs):
        try:
            function = self._mcp.tools[tool_name]
        except KeyError as exc:
            raise ValueError(f"Tool {tool_name!r} not found") from exc
        if inspect.iscoroutinefunction(function):
            return _run_async(function, **kwargs)
        return function(**kwargs)


@pytest.fixture(scope="session")
def mcp_client():
    """Register real adapter wrappers without relying on FastMCP private state."""
    from unittest.mock import patch

    from tools.iot_config import register_iot_config_tools
    from tools.iot_control import register_iot_control_tools
    from tools.iot_devices import register_iot_device_tools
    from tools.iot_discovery import register_iot_discovery_tools
    from tools.iot_hikvision import register_hikvision_tools
    from tools.iot_mqtt import register_iot_mqtt_tools
    from tools.iot_openhasp import register_openhasp_tools
    from tools.iot_tuya import register_iot_tuya_tools

    with patch("tools.constants.ENABLE_WRITE_OPERATIONS", True):
        registry = RegistryMCP()
        register_iot_config_tools(registry)
        register_iot_device_tools(registry)
        register_iot_discovery_tools(registry)
        register_iot_control_tools(registry)
        register_iot_mqtt_tools(registry)
        register_iot_tuya_tools(registry)
        register_openhasp_tools(registry)
        register_hikvision_tools(registry)
        yield MCPWrapper(registry)


@pytest.fixture(scope="module")
def iot_configured_flag():
    """Returns True if MQTT broker is configured."""
    return iot_configured
