from __future__ import annotations

import sys
from types import ModuleType, SimpleNamespace

import pytest

from local_home_devices_mcp.config import load_settings
from local_home_devices_mcp.legacy_compat import _ContextSlot

pytestmark = pytest.mark.unit


def test_context_slot_is_contextvar_backed():
    slot = _ContextSlot()
    assert slot.value == "-"
    slot.value = "req-1"
    assert slot.value == "req-1"


def test_exact_legacy_resolution_rejects_partial(monkeypatch, tmp_path):
    constants = ModuleType("tools.constants")
    constants.TUYA_DEVICES_FILE = str(tmp_path / "tuya.json")
    constants._request_id_context = SimpleNamespace(value="-")
    discovery = ModuleType("tools.iot_discovery")
    discovery._get_cached_devices = lambda: [
        {"name": "Kitchen Light", "ip": "192.168.1.10"},
        {"name": "Kitchen Plug", "ip": "192.168.1.11"},
    ]
    tools_pkg = ModuleType("tools")
    tools_pkg.__path__ = []
    monkeypatch.setitem(sys.modules, "tools", tools_pkg)
    monkeypatch.setitem(sys.modules, "tools.constants", constants)
    monkeypatch.setitem(sys.modules, "tools.iot_discovery", discovery)
    from local_home_devices_mcp.legacy_compat import install_legacy_safety

    install_legacy_safety(load_settings())
    assert discovery._find_device_by_identifier("Kitchen Light")["ip"] == "192.168.1.10"
    assert discovery._find_device_by_identifier("Kitchen") is None


def test_exact_legacy_resolution_rejects_out_of_allowlist(monkeypatch, tmp_path):
    constants = ModuleType("tools.constants")
    constants.TUYA_DEVICES_FILE = str(tmp_path / "tuya.json")
    constants._request_id_context = SimpleNamespace(value="-")
    discovery = ModuleType("tools.iot_discovery")
    discovery._get_cached_devices = lambda: [
        {"name": "Outside", "ip": "203.0.113.10", "mac": "00:11:22:33:44:55"}
    ]
    tools_pkg = ModuleType("tools")
    tools_pkg.__path__ = []
    monkeypatch.setitem(sys.modules, "tools", tools_pkg)
    monkeypatch.setitem(sys.modules, "tools.constants", constants)
    monkeypatch.setitem(sys.modules, "tools.iot_discovery", discovery)
    from local_home_devices_mcp.legacy_compat import install_legacy_safety
    from local_home_devices_mcp.targeting import TargetNotAuthorized

    install_legacy_safety(load_settings())
    with pytest.raises(TargetNotAuthorized):
        discovery._find_device_by_identifier("Outside")
