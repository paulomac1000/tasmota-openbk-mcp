"""Test defaults use zero-I/O targets and explicit operator controls."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def secure_test_environment(monkeypatch: pytest.MonkeyPatch, tmp_path):
    monkeypatch.setenv("MCP_TRANSPORT", "http")
    monkeypatch.setenv("BIND_HOST", "127.0.0.1")
    monkeypatch.setenv("MCP_ALLOWED_TARGET_NETWORKS", "192.168.0.0/16")
    monkeypatch.setenv("MCP_ARTIFACT_ROOT", str(tmp_path / "artifacts"))
    monkeypatch.setenv("MCP_ALLOWED_FIRMWARE_HOSTS", "example.invalid")
    monkeypatch.delenv("MCP_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("ENABLE_DANGEROUS_OPERATIONS", raising=False)
    monkeypatch.delenv("MCP_ALLOW_DIRECT_IP_TARGETS", raising=False)
