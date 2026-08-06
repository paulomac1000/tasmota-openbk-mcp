"""Bounded compatibility adapters for legacy tools; no policy decisions live here."""

from __future__ import annotations

import asyncio
import functools
import inspect
import json
from typing import Any, Callable

import anyio

from .config import Settings
from .targeting import (
    BoundTarget,
    TargetNotFound,
    normalize_selector,
    resolve_exact_target,
    revalidate_binding,
)


class LegacyToolFailure(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def normalize_legacy_result(value: Any) -> Any:
    """Convert legacy JSON envelopes to typed results or protocol-visible failures."""
    if not isinstance(value, str):
        return value
    try:
        payload = json.loads(value)
    except json.JSONDecodeError:
        return value
    if not isinstance(payload, dict) or "success" not in payload:
        return payload
    if payload.get("success") is False:
        error = payload.get("error") or {}
        raise LegacyToolFailure(
            str(error.get("code", "LEGACY_ERROR")),
            str(error.get("message", "legacy tool failed")),
        )
    return payload.get("data", payload)


_thread_limiter = anyio.CapacityLimiter(8)
_TARGET_ARGUMENTS = ("target_id", "identifier", "ip_address", "ip")


def _bind_authorized_target(
    function: Callable[..., Any], args: tuple[Any, ...], kwargs: dict[str, Any]
) -> tuple[tuple[Any, ...], dict[str, Any]]:
    """Replace a model selector with the address authorized by the invocation gate.

    This is the migration boundary that prevents legacy tools from re-resolving a
    mutable name after authorization and identity revalidation.
    """
    from .policy import current_context

    context = current_context()
    if context is None or context.target is None:
        return args, kwargs
    signature = inspect.signature(function)
    bound = signature.bind_partial(*args, **kwargs)
    for name in _TARGET_ARGUMENTS:
        if name in bound.arguments:
            bound.arguments[name] = context.target.address
            return bound.args, bound.kwargs
    return args, kwargs


def _wrap(function: Callable[..., Any]) -> Callable[..., Any]:
    if inspect.iscoroutinefunction(function):

        @functools.wraps(function)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            bound_args, bound_kwargs = _bind_authorized_target(function, args, kwargs)
            return normalize_legacy_result(await function(*bound_args, **bound_kwargs))

        return async_wrapper

    @functools.wraps(function)
    async def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
        bound_args, bound_kwargs = _bind_authorized_target(function, args, kwargs)
        call = functools.partial(function, *bound_args, **bound_kwargs)
        worker = asyncio.create_task(
            anyio.to_thread.run_sync(
                call,
                abandon_on_cancel=False,
                limiter=_thread_limiter,
            )
        )
        try:
            value = await asyncio.shield(worker)
        except asyncio.CancelledError:
            # A timed-out client must not release the target lock while a legacy
            # mutation is still executing in its worker thread.
            await asyncio.shield(worker)
            raise
        return normalize_legacy_result(value)

    return sync_wrapper


class LegacyRegistrationProxy:
    """Wrap callables before FastMCP registration so schemas and errors stay correct."""

    def __init__(self, mcp: Any) -> None:
        self._mcp = mcp

    def tool(self, *args: Any, **kwargs: Any) -> Any:
        if args and callable(args[0]) and len(args) == 1 and not kwargs:
            return self._mcp.tool(_wrap(args[0]))
        decorator = self._mcp.tool(*args, **kwargs)
        return lambda function: decorator(_wrap(function))

    def __getattr__(self, name: str) -> Any:
        return getattr(self._mcp, name)


class LegacyTargetResolver:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @staticmethod
    def _devices() -> list[dict[str, Any]]:
        from tools.iot_discovery import _get_cached_devices

        return list(_get_cached_devices())

    async def resolve(self, selector: str) -> BoundTarget:
        devices = await asyncio.to_thread(self._devices)
        return resolve_exact_target(selector, devices, self.settings)

    async def revalidate(self, target: BoundTarget) -> None:
        devices = await asyncio.to_thread(self._devices)
        matches = [record for record in devices if str(record.get("ip", "")) == target.address]
        if len(matches) != 1:
            raise TargetNotFound("authorized target disappeared or became ambiguous")
        revalidate_binding(target, matches[0], self.settings)


def install_legacy_safety(settings: Settings) -> None:
    """Make legacy lookup exact and patch known unsafe Tuya dispatch behavior."""
    from tools import iot_control, iot_discovery
    from tools.constants import _error_response_extended

    original_resolve = iot_discovery._resolve_ip

    def exact_resolve(selector: str) -> str | None:
        from .policy import current_context

        context = current_context()
        if context is not None and context.target is not None:
            target = context.target
            try:
                normalized = normalize_selector(selector)
                authorized_selectors = {
                    normalize_selector(target.address),
                    normalize_selector(target.target_id),
                    normalize_selector(target.display_name),
                }
            except Exception:
                return None
            if normalized in authorized_selectors:
                return target.address
            return None
        try:
            target = resolve_exact_target(
                selector, iot_discovery._get_cached_devices(), settings
            )
            return target.address
        except Exception:
            return None

    if not getattr(original_resolve, "__exact_target_wrapper__", False):
        setattr(exact_resolve, "__exact_target_wrapper__", True)
        iot_discovery._resolve_ip = exact_resolve

    original_power = iot_control._set_power
    original_brightness = iot_control._set_brightness
    if getattr(original_power, "__tuya_safety_wrapper__", False):
        return

    def safe_set_power(
        identifier: str, state: str, channel: int = 1, timeout_seconds: int = 10
    ) -> str:
        resolved = iot_discovery._resolve_ip(identifier)
        device_type = (
            iot_discovery._detect_device_type(resolved, timeout_seconds) if resolved else None
        )
        if device_type == "tuya" and state.upper() == "TOGGLE":
            return _error_response_extended(
                code="UNSUPPORTED_OPERATION",
                message=(
                    "Tuya TOGGLE is disabled because it is non-idempotent; "
                    "use explicit ON or OFF."
                ),
            )
        return original_power(identifier, state, channel, timeout_seconds)

    def safe_set_brightness(
        identifier: str, brightness: int, channel: int = 1, timeout_seconds: int = 10
    ) -> str:
        resolved = iot_discovery._resolve_ip(identifier)
        device_type = (
            iot_discovery._detect_device_type(resolved, timeout_seconds) if resolved else None
        )
        if device_type != "tuya":
            return original_brightness(identifier, brightness, channel, timeout_seconds)
        from tools.iot_tuya import _find_tuya_in_cache, _tuya_set_value

        entry = _find_tuya_in_cache(identifier) or {}
        brightness_dp = entry.get("brightness_dp_id")
        if not brightness_dp:
            return _error_response_extended(
                code="UNSUPPORTED_OPERATION",
                message="Tuya brightness requires a reviewed brightness_dp_id mapping.",
            )
        return _tuya_set_value(identifier, str(brightness_dp), brightness)

    setattr(safe_set_power, "__tuya_safety_wrapper__", True)
    setattr(safe_set_brightness, "__tuya_safety_wrapper__", True)
    iot_control._set_power = safe_set_power
    iot_control._set_brightness = safe_set_brightness
