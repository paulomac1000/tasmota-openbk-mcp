"""Bounded compatibility adapters for legacy tools; no policy decisions live here."""

from __future__ import annotations

import asyncio
import functools
import inspect
import json
from contextvars import ContextVar
from typing import Any, Callable

import anyio

from .config import Settings
from .targeting import (
    BoundTarget,
    TargetNotFound,
    normalize_selector,
    resolve_exact_target,
    revalidate_binding,
    validate_address,
)


class LegacyToolFailure(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class _ContextSlot:
    """Compatibility slot backed by ContextVar instead of thread-local state."""

    def __init__(self) -> None:
        self._value: ContextVar[str] = ContextVar(
            "legacy_request_id",
            default="-",
        )

    @property
    def value(self) -> str:
        return self._value.get()

    @value.setter
    def value(self, value: str) -> None:
        self._value.set(value)


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
    function: Callable[..., Any],
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
) -> tuple[tuple[Any, ...], dict[str, Any]]:
    """Replace a model selector with the address authorized by the gate."""
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
            bound_args, bound_kwargs = _bind_authorized_target(
                function,
                args,
                kwargs,
            )
            return normalize_legacy_result(
                await function(*bound_args, **bound_kwargs)
            )

        return async_wrapper

    @functools.wraps(function)
    async def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
        from .policy import current_context, register_backend_completion

        bound_args, bound_kwargs = _bind_authorized_target(
            function,
            args,
            kwargs,
        )
        call = functools.partial(function, *bound_args, **bound_kwargs)
        worker = asyncio.create_task(
            anyio.to_thread.run_sync(
                call,
                abandon_on_cancel=False,
                limiter=_thread_limiter,
            )
        )
        if current_context() is not None:
            register_backend_completion(worker)
        try:
            value = await asyncio.shield(worker)
        except asyncio.CancelledError:
            # The client response can now honor its deadline immediately.  The
            # operation gate keeps the canonical concurrency permit until this
            # registered worker really exits, so another mutation cannot race
            # an ambiguous in-flight backend outcome.
            raise
        return normalize_legacy_result(value)

    return sync_wrapper


class LegacyRegistrationProxy:
    """Wrap callables before FastMCP registration."""

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
        matches = [
            record
            for record in devices
            if str(record.get("ip", "")) == target.address
        ]
        if len(matches) != 1:
            raise TargetNotFound(
                "authorized target disappeared or became ambiguous"
            )
        revalidate_binding(target, matches[0], self.settings)


def install_legacy_safety(settings: Settings) -> None:
    """Harden legacy lookup and request context at the compatibility boundary."""
    import importlib

    from tools import iot_discovery
    from tools import constants as legacy_constants

    if not isinstance(
        getattr(legacy_constants, "_request_id_context", None),
        _ContextSlot,
    ):
        legacy_constants._request_id_context = _ContextSlot()

    original_find = getattr(iot_discovery, "_find_device_by_identifier", None)
    if not getattr(
        original_find,
        "__exact_target_wrapper__",
        False,
    ):

        def exact_find(selector: str) -> dict[str, Any] | None:
            devices = list(iot_discovery._get_cached_devices())
            normalized = normalize_selector(selector)
            matches = []
            for record in devices:
                selectors: set[str] = set()
                for key in ("ip", "name", "device_id", "id"):
                    value = record.get(key)
                    if not value:
                        continue
                    try:
                        selectors.add(normalize_selector(str(value)))
                    except (TypeError, ValueError):
                        continue
                if normalized in selectors:
                    matches.append(record)
            if len(matches) != 1:
                return None
            address = str(matches[0].get("ip", ""))
            validate_address(address, settings)
            return matches[0]

        setattr(exact_find, "__exact_target_wrapper__", True)
        iot_discovery._find_device_by_identifier = exact_find

    original_resolve = getattr(iot_discovery, "_resolve_ip", None)
    if callable(original_resolve) and not getattr(
        original_resolve,
        "__exact_target_wrapper__",
        False,
    ):

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
                except (TypeError, ValueError):
                    return None
                return (
                    target.address
                    if normalized in authorized_selectors
                    else None
                )
            try:
                target = resolve_exact_target(
                    selector,
                    iot_discovery._get_cached_devices(),
                    settings,
                )
                return target.address
            except TargetNotFound:
                return None

        setattr(exact_resolve, "__exact_target_wrapper__", True)
        iot_discovery._resolve_ip = exact_resolve

    try:
        iot_control = importlib.import_module("tools.iot_control")
        error_response = getattr(
            legacy_constants,
            "_error_response_extended",
        )
    except (ImportError, AttributeError):
        return

    original_power = getattr(iot_control, "_set_power", None)
    original_brightness = getattr(iot_control, "_set_brightness", None)
    if not callable(original_power) or not callable(original_brightness):
        return
    if getattr(original_power, "__tuya_safety_wrapper__", False):
        return

    def safe_set_power(
        identifier: str,
        state: str,
        channel: int = 1,
        timeout_seconds: int = 10,
    ) -> str:
        resolved = iot_discovery._resolve_ip(identifier)
        device_type = (
            iot_discovery._detect_device_type(resolved, timeout_seconds)
            if resolved
            else None
        )
        if device_type == "tuya" and state.upper() == "TOGGLE":
            return error_response(
                code="UNSUPPORTED_OPERATION",
                message=(
                    "Tuya TOGGLE is disabled because it is non-idempotent; "
                    "use explicit ON or OFF."
                ),
            )
        return original_power(identifier, state, channel, timeout_seconds)

    def safe_set_brightness(
        identifier: str,
        brightness: int,
        channel: int = 1,
        timeout_seconds: int = 10,
    ) -> str:
        resolved = iot_discovery._resolve_ip(identifier)
        device_type = (
            iot_discovery._detect_device_type(resolved, timeout_seconds)
            if resolved
            else None
        )
        if device_type != "tuya":
            return original_brightness(
                identifier,
                brightness,
                channel,
                timeout_seconds,
            )
        from tools.iot_tuya import _find_tuya_in_cache, _tuya_set_value

        entry = _find_tuya_in_cache(identifier) or {}
        brightness_dp = entry.get("brightness_dp_id")
        if not brightness_dp:
            return error_response(
                code="UNSUPPORTED_OPERATION",
                message=(
                    "Tuya brightness requires a reviewed brightness_dp_id mapping."
                ),
            )
        return _tuya_set_value(identifier, str(brightness_dp), brightness)

    setattr(safe_set_power, "__tuya_safety_wrapper__", True)
    setattr(safe_set_brightness, "__tuya_safety_wrapper__", True)
    iot_control._set_power = safe_set_power
    iot_control._set_brightness = safe_set_brightness
