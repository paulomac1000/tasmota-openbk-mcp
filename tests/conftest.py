"""
Root conftest - environment loading only.
Specific fixtures live in subdirectory conftest.py files.
"""

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
                        # IOT_DATA_PATH is a container deployment setting
                        # provided by docker-compose; the container-only /app
                        # path must not leak into local test runs.
                        if key.strip() == "IOT_DATA_PATH":
                            continue
                        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
        except Exception:
            pass

REST_API_PORT = int(os.getenv("REST_API_PORT", "9102"))
REST_API_URL = f"http://localhost:{REST_API_PORT}"


def pytest_collection_modifyitems(config, items):
    """Skip dependency-specific tests only when an optional runtime is absent."""
    import importlib.util

    missing = {
        "paho": importlib.util.find_spec("paho") is None,
        "tinytuya": importlib.util.find_spec("tinytuya") is None,
    }
    for item in items:
        nodeid = item.nodeid
        if missing["paho"] and any(
            name in nodeid
            for name in (
                "test_get_client_success",
                "test_get_client_v2_api",
                "test_get_client_v1_api",
            )
        ):
            item.add_marker(
                pytest.mark.skip(reason="paho-mqtt is not installed in this isolated environment")
            )
        if missing["tinytuya"] and any(
            name in nodeid
            for name in (
                "test_local_client_returns_device",
                "test_detect_version",
            )
        ):
            item.add_marker(
                pytest.mark.skip(reason="tinytuya is not installed in this isolated environment")
            )
