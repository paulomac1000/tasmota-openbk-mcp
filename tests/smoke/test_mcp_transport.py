from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.smoke


def test_mock_entrypoint_runs_without_device_io(tmp_path: Path):
    env = {
        **os.environ,
        "MCP_MOCK_MODE": "1",
        "ENABLE_WRITE_OPERATIONS": "1",
        "MCP_ARTIFACT_ROOT": str(tmp_path / "artifacts"),
    }
    completed = subprocess.run(
        [sys.executable, "server.py", "--mock-self-test"],
        env=env,
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    result = json.loads(completed.stdout)
    assert result["success"] is True
    assert result["io"] == "mocked"
    assert result["target_revalidations"] == 1
