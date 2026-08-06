"""Single invocation gate shared by every supported transport."""

from __future__ import annotations

import inspect
import threading
import time
from collections import defaultdict, deque
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, Callable, Iterator, Mapping, TypeVar

from .config import Settings
from .manifests import ManifestError, normalize_catalog
from .targeting import normalize_selector

T = TypeVar("T")


class PolicyError(PermissionError):
    pass


class CapabilityUnavailable(PolicyError):
    pass


class RateLimitExceeded(PolicyError):
    pass


@dataclass(frozen=True, slots=True)
class Principal:
    subject: str
    scopes: frozenset[str]
    transport: str


@dataclass(frozen=True, slots=True)
class InvocationContext:
    principal: Principal
    request_id: str
    deadline: float


_current_context: ContextVar[InvocationContext | None] = ContextVar(
    "mcp_invocation_context", default=None
)


@contextmanager
def invocation_context(context: InvocationContext) -> Iterator[None]:
    token = _current_context.set(context)
    try:
        yield
    finally:
        _current_context.reset(token)


def current_context() -> InvocationContext | None:
    return _current_context.get()


class SlidingWindowLimiter:
    def __init__(self, limit: int = 60, window_seconds: float = 60.0) -> None:
        self.limit = limit
        self.window_seconds = window_seconds
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key: str, now: float | None = None) -> None:
        now = time.monotonic() if now is None else now
        cutoff = now - self.window_seconds
        with self._lock:
            events = self._events[key]
            while events and events[0] <= cutoff:
                events.popleft()
            if len(events) >= self.limit:
                raise RateLimitExceeded("rate limit exceeded")
            events.append(now)


class OperationGate:
    """Authorize, classify, serialize, and budget every public tool call."""

    def __init__(
        self,
        settings: Settings,
        raw_catalog: Mapping[str, Mapping[str, Any]],
        *,
        rate_limit_per_minute: int = 60,
    ) -> None:
        self.settings = settings
        self.catalog = normalize_catalog(raw_catalog)
        self.rate_limiter = SlidingWindowLimiter(rate_limit_per_minute)
        self._locks: dict[str, threading.RLock] = defaultdict(threading.RLock)
        self._locks_guard = threading.Lock()

    def manifest(self, tool_name: str) -> Mapping[str, Any]:
        try:
            return self.catalog[tool_name]
        except KeyError as exc:
            raise ManifestError(f"unclassified capability: {tool_name}") from exc

    def _scope_required(self, manifest: Mapping[str, Any]) -> str:
        effects = manifest["side_effects"]
        if manifest["risk"] == "DANGEROUS":
            return "devices:dangerous"
        if effects in {"write", "destructive"}:
            return "devices:write"
        return "devices:read"

    def authorize(self, tool_name: str, arguments: Mapping[str, Any], principal: Principal) -> None:
        manifest = self.manifest(tool_name)
        if tool_name == "iot_execute_command" and "force" in arguments:
            raise PolicyError("model input cannot override dangerous-operation policy")
        state = manifest["active_state"]
        if state != "active":
            raise CapabilityUnavailable(f"{tool_name} is {state}")
        if manifest["side_effects"] in {"write", "destructive"} and not self.settings.write_enabled:
            raise PolicyError("write operations are disabled by the operator")
        if manifest["risk"] == "DANGEROUS" and not self.settings.dangerous_enabled:
            raise PolicyError("dangerous operations are disabled by the operator")
        required = self._scope_required(manifest)
        if required not in principal.scopes and "devices:admin" not in principal.scopes:
            raise PolicyError(f"missing required scope: {required}")
        if manifest["confidentiality"] in {"personal", "sensitive", "credential"}:
            has_sensitive_scope = (
                "devices:sensitive" in principal.scopes
                or "devices:admin" in principal.scopes
            )
            if not has_sensitive_scope:
                raise PolicyError("missing required scope: devices:sensitive")
        if tool_name == "iot_set_power" and str(arguments.get("state", "")).upper() == "TOGGLE":
            raise PolicyError(
                "TOGGLE is non-idempotent and not exposed; read current state and request ON or OFF"
            )
        if tool_name == "hikvision_snapshot_to_file":
            raise PolicyError(
                "caller-provided filesystem paths are not supported; use artifact storage"
            )
        if tool_name == "iot_configure_mqtt":
            changed = {"host", "client", "group", "user", "password"} & set(arguments)
            if changed and "port" not in arguments:
                raise PolicyError(
                    "port must be supplied explicitly when changing MQTT settings; "
                    "the legacy adapter must not silently apply 1883"
                )
        if "timeout_seconds" in arguments:
            maximum = manifest["timeout_ms"] / 1000
            try:
                requested_timeout = float(arguments["timeout_seconds"])
            except (TypeError, ValueError) as exc:
                raise PolicyError("timeout_seconds must be numeric") from exc
            if requested_timeout <= 0 or requested_timeout > maximum:
                raise PolicyError(f"timeout_seconds must be between 0 and {maximum:g}")
        if "role" in arguments:
            from tools.validators import validate_gpio_role

            validate_gpio_role(str(arguments["role"]))
        for key in ("identifier", "ip", "ip_address", "target_id"):
            value = arguments.get(key)
            if not isinstance(value, str):
                continue
            normalized = normalize_selector(value)
            try:
                import ipaddress

                ipaddress.ip_address(normalized)
                is_literal_ip = True
            except ValueError:
                is_literal_ip = False

            # Parameters named ip/ip_address are network addresses, not aliases.
            # Reject hostnames such as localhost before an adapter can perform DNS.
            if key in {"ip", "ip_address"} and not is_literal_ip:
                raise PolicyError(f"{key} must be a literal authorized IPv4 address")
            if not is_literal_ip:
                continue
            if not self.settings.allow_direct_ip_targets:
                raise PolicyError(
                    "literal IP targets are disabled; use an exact discovered name or target_id"
                )
            from .targeting import validate_address

            validate_address(normalized, self.settings)

    def _lock_key(self, tool_name: str, arguments: Mapping[str, Any]) -> str:
        for key in ("target_id", "identifier", "ip_address", "ip"):
            value = arguments.get(key)
            if value is not None:
                return f"target:{normalize_selector(str(value))}"
        return f"{tool_name}:global"

    @contextmanager
    def guard(
        self, tool_name: str, arguments: Mapping[str, Any], principal: Principal
    ) -> Iterator[Mapping[str, Any]]:
        manifest = self.manifest(tool_name)
        self.rate_limiter.check(principal.subject)
        self.authorize(tool_name, arguments, principal)
        timeout_seconds = manifest["timeout_ms"] / 1000
        context = InvocationContext(
            principal=principal,
            request_id=f"req_{time.time_ns():x}",
            deadline=time.monotonic() + timeout_seconds,
        )
        lock: threading.RLock | None = None
        if not manifest["concurrent_safe"]:
            key = self._lock_key(tool_name, arguments)
            with self._locks_guard:
                lock = self._locks[key]
            if not lock.acquire(timeout=timeout_seconds):
                raise PolicyError("target is busy")
        try:
            with invocation_context(context):
                yield manifest
        finally:
            if lock is not None:
                lock.release()

    def invoke(
        self,
        tool_name: str,
        function: Callable[..., T],
        arguments: Mapping[str, Any],
        principal: Principal,
    ) -> T:
        signature = inspect.signature(function)
        bounded = dict(arguments)
        manifest = self.manifest(tool_name)
        if "timeout_seconds" in signature.parameters:
            requested = bounded.get("timeout_seconds", manifest["timeout_ms"] / 1000)
            bounded["timeout_seconds"] = max(
                0.1, min(float(requested), manifest["timeout_ms"] / 1000)
            )
        with self.guard(tool_name, bounded, principal):
            return function(**bounded)
