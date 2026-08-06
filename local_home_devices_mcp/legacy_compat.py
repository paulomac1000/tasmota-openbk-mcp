"""Narrow compatibility hardening for adapters pending full domain extraction."""

from __future__ import annotations

from contextvars import ContextVar
import os
from pathlib import Path
from typing import Any

from .config import Settings
from .targeting import validate_address


class _ContextSlot:
    """Expose the old `.value` protocol while using async-safe ContextVar state."""

    def __init__(self) -> None:
        self._value: ContextVar[str] = ContextVar("legacy_request_id", default="-")

    @property
    def value(self) -> str:
        return self._value.get()

    @value.setter
    def value(self, value: str) -> None:
        self._value.set(value)


def install_legacy_safety(settings: Settings) -> None:
    """Install fail-closed compatibility hooks before adapter registration."""

    # Credentials and caches created by legacy adapters inherit owner-only permissions.
    os.umask(0o077)

    from tools import constants

    constants._request_id_context = _ContextSlot()  # type: ignore[attr-defined]

    # Reject credential-cache symlinks and restrict existing cache permissions.
    cache_path = Path(constants.TUYA_DEVICES_FILE)
    if cache_path.is_symlink():
        raise RuntimeError("TUYA_DEVICES_FILE must not be a symbolic link")
    if cache_path.exists():
        os.chmod(cache_path, 0o600)

    # Replace partial-name first-match resolution with exact-only resolution.
    from tools import iot_discovery

    def exact_find(identifier: str) -> dict[str, Any] | None:
        devices = iot_discovery._get_cached_devices()
        value = identifier.strip().casefold()
        exact = [
            device
            for device in devices
            if value
            in {
                str(device.get("ip", "")).strip().casefold(),
                str(device.get("name", "")).strip().casefold(),
                str(device.get("target_id", "")).strip().casefold(),
            }
        ]
        if len(exact) > 1:
            raise ValueError(f"AMBIGUOUS_TARGET: {identifier!r} matched {len(exact)} devices")
        if not exact:
            return None
        validate_address(str(exact[0].get("ip", "")), settings)
        return exact[0]

    iot_discovery._find_device_by_identifier = exact_find

    # Tuya identifiers are also exact-only; never select the first partial match.
    try:
        from tools import iot_tuya
    except ImportError:
        iot_tuya = None

    if iot_tuya is not None:

        def exact_tuya(identifier: str) -> dict[str, Any] | None:
            cache = iot_tuya._load_tuya_devices()
            devices = cache.get("devices", {})
            value = identifier.strip().casefold()
            matches: list[dict[str, Any]] = []
            for device_id, entry in devices.items():
                candidates = {
                    str(device_id).strip().casefold(),
                    str(entry.get("device_id", "")).strip().casefold(),
                    str(entry.get("ip", "")).strip().casefold(),
                    str(entry.get("name", "")).strip().casefold(),
                }
                if value in candidates:
                    matches.append(entry)
            if len(matches) > 1:
                raise ValueError(
                    f"AMBIGUOUS_TARGET: {identifier!r} matched {len(matches)} devices"
                )
            if not matches:
                return None
            address = str(matches[0].get("ip", "")).strip()
            if address:
                validate_address(address, settings)
            return matches[0]

        iot_tuya._find_tuya_in_cache = exact_tuya
