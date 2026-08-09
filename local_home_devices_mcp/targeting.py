"""Stable target selection, exact matching, and private-network confinement."""

from __future__ import annotations

import hashlib
import ipaddress
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from .config import Settings

_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_. -]{0,127}$")


class TargetError(ValueError):
    pass


class TargetNotFound(TargetError):
    pass


class AmbiguousTarget(TargetError):
    pass


class TargetNotAuthorized(TargetError):
    pass


@dataclass(frozen=True, slots=True)
class BoundTarget:
    target_id: str
    address: str
    display_name: str
    fingerprint: str


class TargetResolver(Protocol):
    async def resolve(
        self,
        selector: str,
        *,
        allowed_target_ids: frozenset[str] | None = None,
    ) -> BoundTarget: ...

    async def revalidate(self, target: BoundTarget) -> None: ...

    async def readiness(self) -> Mapping[str, Any]: ...


def _normalized_identity_parts(device: Mapping[str, Any]) -> list[str]:
    parts: list[str] = []
    for key in ("device_id", "serial", "mac", "target_id"):
        value = str(device.get(key, "")).strip()
        if not value:
            continue
        if key == "mac":
            compact = re.sub(r"[^0-9A-Fa-f]", "", value).lower()
            if len(compact) != 12:
                raise TargetError("device MAC address is not a stable 48-bit identifier")
            value = compact
        else:
            value = value.casefold()
        parts.append(f"{key}:{value}")
    return parts


def _fingerprint(device: Mapping[str, Any]) -> str:
    parts = _normalized_identity_parts(device)
    if not parts:
        raise TargetError("device has no stable identity attributes")
    return hashlib.sha256("|".join(parts).encode()).hexdigest()


def target_id_for(device: Mapping[str, Any]) -> str:
    explicit = str(device.get("target_id", "")).strip()
    return explicit or f"dev_{_fingerprint(device)[:20]}"


def validate_address(address: str, settings: Settings) -> str:
    try:
        parsed = ipaddress.ip_address(address.strip())
    except ValueError as exc:
        raise TargetError(f"invalid IP address: {address!r}") from exc
    if not isinstance(parsed, ipaddress.IPv4Address):
        raise TargetError("only IPv4 device targets are supported")
    if parsed.is_multicast or parsed.is_unspecified or parsed.is_loopback:
        raise TargetNotAuthorized(f"target address {parsed} is not a device address")
    if not any(parsed in network for network in settings.allowed_networks):
        raise TargetNotAuthorized(f"target address {parsed} is outside allowed networks")
    return str(parsed)


def normalize_selector(selector: str) -> str:
    value = selector.strip()
    if not value:
        raise TargetError("target selector must not be empty")
    try:
        return str(ipaddress.ip_address(value))
    except ValueError:
        if not _SAFE_NAME.fullmatch(value):
            raise TargetError("target selector contains unsupported characters") from None
        return value.casefold()


def resolve_exact_target(
    selector: str,
    devices: Iterable[Mapping[str, Any]],
    settings: Settings,
    *,
    allowed_target_ids: frozenset[str] | None = None,
) -> BoundTarget:
    normalized = normalize_selector(selector)
    records = list(devices)
    if allowed_target_ids is not None:
        records = [record for record in records if target_id_for(record) in allowed_target_ids]

    try:
        parsed_selector = ipaddress.ip_address(normalized)
    except ValueError:
        parsed_selector = None

    if parsed_selector is not None:
        if not settings.allow_direct_ip_targets:
            raise TargetNotFound(f"{selector!r}: direct IP targets are disabled")
        matches = [
            device
            for device in records
            if str(device.get("ip", "")).strip() == str(parsed_selector)
        ]
    else:
        matches = [
            device
            for device in records
            if normalized
            in {
                str(device.get("target_id", "")).strip().casefold(),
                str(device.get("name", "")).strip().casefold(),
            }
        ]

    if not matches:
        if allowed_target_ids is not None:
            reason = "no exact target match in authorized namespace"
        elif parsed_selector is not None and not settings.allow_direct_ip_targets:
            reason = "direct IP targets are disabled"
        elif parsed_selector is not None:
            reason = "address is not bound to a discovered stable target"
        else:
            reason = "no exact target match"
        raise TargetNotFound(f"{selector!r}: {reason}")
    if len(matches) > 1:
        raise AmbiguousTarget(f"{selector!r} matched {len(matches)} devices")

    device = matches[0]
    address = validate_address(str(device.get("ip", "")), settings)
    return BoundTarget(
        target_id=target_id_for(device),
        address=address,
        display_name=str(device.get("name") or address),
        fingerprint=_fingerprint(device),
    )


def revalidate_binding(
    bound: BoundTarget,
    current: Mapping[str, Any],
    settings: Settings,
) -> None:
    address = validate_address(str(current.get("ip", "")), settings)
    if address != bound.address:
        raise TargetNotAuthorized("target address changed after authorization")
    if target_id_for(current) != bound.target_id or _fingerprint(current) != bound.fingerprint:
        raise TargetNotAuthorized("target identity changed after authorization")
