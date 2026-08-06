from __future__ import annotations

import ipaddress
from pathlib import Path

import pytest

from local_home_devices_mcp.config import Settings

pytestmark = pytest.mark.unit


def make(tmp_path: Path, **overrides):
    values = dict(
        transport="http",
        bind_host="0.0.0.0",
        port=9102,
        mcp_path="/mcp",
        write_enabled=False,
        dangerous_enabled=False,
        allow_direct_ip_targets=False,
        allowed_networks=(ipaddress.ip_network("192.168.0.0/16"),),
        artifact_root=tmp_path,
        max_artifact_bytes=1024,
        max_artifact_store_bytes=4096,
        artifact_retention_seconds=3600,
        read_token="r" * 32,
        write_token=None,
        admin_token=None,
        trusted_proxy_tls=False,
        mock_mode=True,
    )
    values.update(overrides)
    return Settings(**values)


def test_non_loopback_requires_trusted_tls_proxy(tmp_path: Path):
    with pytest.raises(ValueError, match="TLS"):
        make(tmp_path).validate()


def test_static_tokens_have_separate_scopes(tmp_path: Path):
    config = make(
        tmp_path,
        trusted_proxy_tls=True,
        read_token="r" * 32,
        write_token="w" * 32,
        admin_token="a" * 32,
    )
    config.validate()
    tokens = config.static_tokens()
    assert tokens["r" * 32]["scopes"] == ["devices:read"]
    assert "devices:dangerous" not in tokens["w" * 32]["scopes"]
    assert tokens["a" * 32]["scopes"] == [
        "devices:read",
        "devices:sensitive",
        "devices:write",
        "devices:dangerous",
        "devices:admin",
    ]


def test_admin_token_includes_required_read_scope(tmp_path: Path):
    config = make(tmp_path, admin_token="a" * 32)
    token = config.static_tokens()["a" * 32]
    assert "devices:read" in token["scopes"]
    assert "devices:admin" in token["scopes"]
