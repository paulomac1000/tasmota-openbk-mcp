"""Smoke the installed-style CLI using deterministic mock state."""

from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

pytestmark = pytest.mark.smoke


def test_mock_cli_smoke():
    env = {
        **os.environ,
        "MCP_MOCK_MODE": "1",
        "ENABLE_WRITE_OPERATIONS": "1",
        "MCP_TRANSPORT": "stdio",
    }
    completed = subprocess.run(
        [sys.executable, "server.py", "--mock-self-test"],
        check=True,
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )
    result = json.loads(completed.stdout)
    assert result["success"] is True
    assert result["io"] == "mocked"
    assert result["restored"]["power"] is False
