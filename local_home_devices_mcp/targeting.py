"""Stable target selection, exact matching, and private-network confinement."""

from __future__ import annotations

import hashlib
import ipaddress
import re
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from .config import Settings

_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_. -]{0,127}$")


class TargetError(ValueError):
    """Base target resolution failure."""


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


def _fingerprint(device: Mapping[str, Any]) -> str:
    identity = "|".join(
        str(device.get(key, ""))
        for key in ("device_id", "mac", "serial", "type", "name")
    )
    if not identity.strip("|"):
        raise TargetError("device has no stable identity attributes")
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


def target_id_for(device: Mapping[str, Any]) -> str:
    explicit = str(device.get("target_id", "")).strip()
    if explicit:
        return explicit
    return f"dev_{_fingerprint(device)[:20]}"


def validate_address(address: str, settings: Settings) -> str:
    """Validate a literal IPv4 address against the operator allowlist."""

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
            raise TargetError("target selector contains unsupported characters")
        return value.casefold()


def resolve_exact_target(
    selector: str,
    devices: Iterable[Mapping[str, Any]],
    settings: Settings,
) -> BoundTarget:
    """Resolve an exact target without partial-name or silent fallback behavior."""

    normalized = normalize_selector(selector)
    records = list(devices)
    matches: list[Mapping[str, Any]] = []
    selector_is_ip = False
    try:
        parsed_selector = ipaddress.ip_address(normalized)
    except ValueError:
        parsed_selector = None

    if parsed_selector is not None:
        ip = str(parsed_selector)
        selector_is_ip = True
        matches = [d for d in records if str(d.get("ip", "")).strip() == ip]
    else:
        matches = [
            d
            for d in records
            if normalized
            in {
                str(d.get("target_id", "")).strip().casefold(),
                str(d.get("name", "")).strip().casefold(),
            }
        ]

    if not matches:
        if selector_is_ip and not settings.allow_direct_ip_targets:
            reason = "direct IP targets are disabled"
        elif selector_is_ip:
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


def revalidate_binding(bound: BoundTarget, current: Mapping[str, Any], settings: Settings) -> None:
    """Fail closed when address-to-identity mapping changed before I/O."""

    address = validate_address(str(current.get("ip", "")), settings)
    if address != bound.address:
        raise TargetNotAuthorized("target address changed after authorization")
    if target_id_for(current) != bound.target_id or _fingerprint(current) != bound.fingerprint:
        raise TargetNotAuthorized("target identity changed after authorization")
