"""Typed server configuration loaded once at the composition root."""

from __future__ import annotations

import ipaddress
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

Transport = Literal["stdio", "http"]


def _bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int, *, minimum: int, maximum: int) -> int:
    raw = os.getenv(name, str(default))
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return value


def _token(value: str | None, name: str) -> str | None:
    if not value:
        return None
    if len(value) < 32:
        raise ValueError(f"{name} must contain at least 32 characters")
    return value


@dataclass(frozen=True, slots=True)
class Settings:
    transport: Transport
    bind_host: str
    port: int
    mcp_path: str
    write_enabled: bool
    dangerous_enabled: bool
    allow_direct_ip_targets: bool
    allowed_networks: tuple[ipaddress.IPv4Network, ...]
    artifact_root: Path
    max_artifact_bytes: int
    max_artifact_store_bytes: int
    artifact_retention_seconds: int
    read_token: str | None
    write_token: str | None
    admin_token: str | None
    trusted_proxy_tls: bool
    mock_mode: bool

    @property
    def is_loopback(self) -> bool:
        try:
            return ipaddress.ip_address(self.bind_host).is_loopback
        except ValueError:
            return self.bind_host == "localhost"

    @property
    def has_auth(self) -> bool:
        return any((self.read_token, self.write_token, self.admin_token))

    def validate(self) -> None:
        if self.transport == "http" and not self.is_loopback:
            if not self.has_auth:
                raise ValueError("an MCP auth token is required for a non-loopback HTTP bind")
            if not self.trusted_proxy_tls:
                raise ValueError(
                    "non-loopback HTTP requires MCP_TRUSTED_PROXY_TLS=1 "
                    "and a TLS-terminating trusted proxy"
                )
        if not self.mcp_path.startswith("/") or "?" in self.mcp_path or "#" in self.mcp_path:
            raise ValueError("MCP_PATH must be an absolute URL path without query or fragment")
        if self.artifact_root == Path("/"):
            raise ValueError("MCP_ARTIFACT_ROOT cannot be the filesystem root")
        tokens = [token for token in (self.read_token, self.write_token, self.admin_token) if token]
        if len(tokens) != len(set(tokens)):
            raise ValueError("read, write, and admin tokens must be distinct")

    def static_tokens(self) -> dict[str, dict[str, object]]:
        tokens: dict[str, dict[str, object]] = {}
        if self.read_token:
            tokens[self.read_token] = {
                "client_id": "local-home-devices-reader",
                "scopes": ["devices:read"],
            }
        if self.write_token:
            tokens[self.write_token] = {
                "client_id": "local-home-devices-writer",
                "scopes": ["devices:read", "devices:sensitive", "devices:write"],
            }
        if self.admin_token:
            tokens[self.admin_token] = {
                "client_id": "local-home-devices-admin",
                "scopes": [
                    "devices:read",
                    "devices:sensitive",
                    "devices:write",
                    "devices:dangerous",
                    "devices:admin",
                ],
            }
        return tokens


def load_settings() -> Settings:
    transport_raw = os.getenv("MCP_TRANSPORT", "http").strip().lower()
    if transport_raw in {"streamable-http", "streamable_http"}:
        transport_raw = "http"
    if transport_raw not in {"stdio", "http"}:
        raise ValueError("MCP_TRANSPORT must be 'stdio' or 'http'; legacy SSE is not supported")

    raw_networks = os.getenv(
        "MCP_ALLOWED_TARGET_NETWORKS", "10.0.0.0/8,172.16.0.0/12,192.168.0.0/16"
    )
    networks: list[ipaddress.IPv4Network] = []
    for item in raw_networks.split(","):
        item = item.strip()
        if not item:
            continue
        network = ipaddress.ip_network(item, strict=False)
        if not isinstance(network, ipaddress.IPv4Network):
            raise ValueError("Only IPv4 target networks are currently supported")
        networks.append(network)
    if not networks:
        raise ValueError("MCP_ALLOWED_TARGET_NETWORKS must contain at least one network")

    legacy = _token(os.getenv("MCP_AUTH_TOKEN"), "MCP_AUTH_TOKEN")
    read_token = _token(os.getenv("MCP_AUTH_READ_TOKEN") or legacy, "MCP_AUTH_READ_TOKEN")
    settings = Settings(
        transport=transport_raw,  # type: ignore[arg-type]
        bind_host=os.getenv("BIND_HOST", "127.0.0.1"),
        port=_int("MCP_PORT", 9102, minimum=1, maximum=65535),
        mcp_path=os.getenv("MCP_PATH", "/mcp"),
        write_enabled=_bool("ENABLE_WRITE_OPERATIONS", False),
        dangerous_enabled=_bool("ENABLE_DANGEROUS_OPERATIONS", False),
        allow_direct_ip_targets=_bool("MCP_ALLOW_DIRECT_IP_TARGETS", False),
        allowed_networks=tuple(networks),
        artifact_root=Path(os.getenv("MCP_ARTIFACT_ROOT", "data/artifacts")).resolve(),
        max_artifact_bytes=_int(
            "MCP_MAX_ARTIFACT_BYTES", 8 * 1024 * 1024, minimum=1024, maximum=64 * 1024 * 1024
        ),
        max_artifact_store_bytes=_int(
            "MCP_MAX_ARTIFACT_STORE_BYTES",
            128 * 1024 * 1024,
            minimum=1024,
            maximum=4 * 1024 * 1024 * 1024,
        ),
        artifact_retention_seconds=_int(
            "MCP_ARTIFACT_RETENTION_SECONDS", 86400, minimum=60, maximum=31 * 86400
        ),
        read_token=read_token,
        write_token=_token(os.getenv("MCP_AUTH_WRITE_TOKEN"), "MCP_AUTH_WRITE_TOKEN"),
        admin_token=_token(os.getenv("MCP_AUTH_ADMIN_TOKEN"), "MCP_AUTH_ADMIN_TOKEN"),
        trusted_proxy_tls=_bool("MCP_TRUSTED_PROXY_TLS", False),
        mock_mode=_bool("MCP_MOCK_MODE", False),
    )
    settings.validate()
    return settings
