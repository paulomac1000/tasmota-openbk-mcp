from __future__ import annotations

import pytest

from local_home_devices_mcp.config import load_settings
from local_home_devices_mcp.mock_runtime import run_mock_self_test

pytestmark = pytest.mark.integration


def test_mock_application_workflow(monkeypatch):
    monkeypatch.setenv("MCP_MOCK_MODE", "1")
    monkeypatch.setenv("ENABLE_WRITE_OPERATIONS", "1")
    result = run_mock_self_test(load_settings())
    assert result["success"] is True
    assert result["io"] == "mocked"
    assert result["before"] == {"power": False, "brightness": 50}
    assert result["after"]["power"] is True
    assert result["after"]["identifier"] == "dev_mock_light"
    assert result["restored"]["power"] is False
    assert result["restored"]["brightness"] == 50
    assert result["target_revalidations"] >= 1
