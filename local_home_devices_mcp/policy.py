"""Single async invocation gate shared by every supported transport."""

from __future__ import annotations

import asyncio
import inspect
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, AsyncIterator, Awaitable, Callable, Mapping, TypeVar

from .config import Settings
from .manifests import ManifestError, normalize_catalog
from .targeting import BoundTarget, TargetError, TargetResolver, validate_address

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
    target: BoundTarget | None


_current_context: ContextVar[InvocationContext | None] = ContextVar(
    "mcp_invocation_context", default=None
)


def current_context() -> InvocationContext | None:
    return _current_context.get()


class AsyncSlidingWindowLimiter:
    def __init__(self, limit: int = 60, window_seconds: float = 60.0) -> None:
        self.limit = limit
        self.window_seconds = window_seconds
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = asyncio.Lock()

    async def check(self, key: str, now: float | None = None) -> None:
        now = time.monotonic() if now is None else now
        cutoff = now - self.window_seconds
        async with self._lock:
            events = self._events[key]
            while events and events[0] <= cutoff:
                events.popleft()
            if len(events) >= self.limit:
                raise RateLimitExceeded("rate limit exceeded")
            events.append(now)


@dataclass(slots=True)
class _LockEntry:
    lock: asyncio.Lock
    users: int = 0


class AsyncKeyedLockManager:
    """Reference-counted lock table that cannot grow after entries become idle."""

    def __init__(self) -> None:
        self._entries: dict[str, _LockEntry] = {}
        self._guard = asyncio.Lock()

    @asynccontextmanager
    async def acquire(self, key: str, timeout: float) -> AsyncIterator[None]:
        async with self._guard:
            entry = self._entries.setdefault(key, _LockEntry(asyncio.Lock()))
            entry.users += 1
        acquired = False
        try:
            await asyncio.wait_for(entry.lock.acquire(), timeout=timeout)
            acquired = True
            yield
        except TimeoutError as exc:
            raise PolicyError("target is busy") from exc
        finally:
            if acquired:
                entry.lock.release()
            async with self._guard:
                entry.users -= 1
                if entry.users == 0 and not entry.lock.locked():
                    self._entries.pop(key, None)

    @property
    def entry_count(self) -> int:
        return len(self._entries)


class OperationGate:
    def __init__(
        self,
        settings: Settings,
        raw_catalog: Mapping[str, Mapping[str, Any]],
        *,
        target_resolver: TargetResolver | None = None,
        rate_limit_per_minute: int = 60,
    ) -> None:
        self.settings = settings
        self.catalog = normalize_catalog(raw_catalog)
        self.target_resolver = target_resolver
        self.rate_limiter = AsyncSlidingWindowLimiter(rate_limit_per_minute)
        self.locks = AsyncKeyedLockManager()

    def manifest(self, tool_name: str) -> Mapping[str, Any]:
        try:
            return self.catalog[tool_name]
        except KeyError as exc:
            raise ManifestError(f"unclassified capability: {tool_name}") from exc

    def _scope_required(self, manifest: Mapping[str, Any]) -> str:
        if manifest["risk"] == "DANGEROUS":
            return "devices:dangerous"
        if manifest["side_effects"] in {"write", "destructive"}:
            return "devices:write"
        return "devices:read"

    def authorize(self, tool_name: str, arguments: Mapping[str, Any], principal: Principal) -> None:
        manifest = self.manifest(tool_name)
        if tool_name == "iot_execute_command" and "force" in arguments:
            raise PolicyError("model input cannot override dangerous-operation policy")
        if manifest["active_state"] != "active":
            raise CapabilityUnavailable(f"{tool_name} is {manifest['active_state']}")
        if manifest["side_effects"] in {"write", "destructive"} and not self.settings.write_enabled:
            raise PolicyError("write operations are disabled by the operator")
        if manifest["risk"] == "DANGEROUS" and not self.settings.dangerous_enabled:
            raise PolicyError("dangerous operations are disabled by the operator")
        required = self._scope_required(manifest)
        if required not in principal.scopes and "devices:admin" not in principal.scopes:
            raise PolicyError(f"missing required scope: {required}")
        if manifest["confidentiality"] in {"personal", "sensitive", "credential"} and not (
            {"devices:sensitive", "devices:admin"} & principal.scopes
        ):
            raise PolicyError("missing required scope: devices:sensitive")
        if tool_name == "iot_set_power" and str(arguments.get("state", "")).upper() == "TOGGLE":
            raise PolicyError("TOGGLE is non-idempotent; request explicit ON or OFF")
        if "timeout_seconds" in arguments:
            maximum = manifest["timeout_ms"] / 1000
            try:
                requested = float(arguments["timeout_seconds"])
            except (TypeError, ValueError) as exc:
                raise PolicyError("timeout_seconds must be numeric") from exc
            if requested <= 0 or requested > maximum:
                raise PolicyError(f"timeout_seconds must be between 0 and {maximum:g}")
        for key in ("target_id", "identifier", "ip", "ip_address"):
            value = arguments.get(key)
            if not isinstance(value, str):
                continue
            try:
                validated = validate_address(value, self.settings)
            except TargetError:
                if key in {"ip", "ip_address"}:
                    raise
                continue
            if validated and not self.settings.allow_direct_ip_targets:
                raise PolicyError(
                    "literal IP targets are disabled; use an exact target_id or device name"
                )

    @staticmethod
    def selector(arguments: Mapping[str, Any]) -> str | None:
        for key in ("target_id", "identifier", "ip_address", "ip"):
            value = arguments.get(key)
            if isinstance(value, str) and value.strip():
                return value
        return None

    async def _resolve_target(self, arguments: Mapping[str, Any]) -> BoundTarget | None:
        selector = self.selector(arguments)
        if selector is None:
            return None
        if self.target_resolver is None:
            # Target-bearing tools cannot silently bypass stable binding.
            raise PolicyError("target resolver is unavailable for a target-bearing capability")
        return await self.target_resolver.resolve(selector)

    @asynccontextmanager
    async def guard_async(
        self, tool_name: str, arguments: Mapping[str, Any], principal: Principal
    ) -> AsyncIterator[Mapping[str, Any]]:
        manifest = self.manifest(tool_name)
        await self.rate_limiter.check(principal.subject)
        self.authorize(tool_name, arguments, principal)
        target = await self._resolve_target(arguments)
        timeout = manifest["timeout_ms"] / 1000
        context = InvocationContext(
            principal=principal,
            request_id=f"req_{time.time_ns():x}",
            deadline=time.monotonic() + timeout,
            target=target,
        )
        token = _current_context.set(context)
        lock_key = target.target_id if target else f"global:{tool_name}"
        try:
            if manifest["concurrent_safe"]:
                if target and self.target_resolver:
                    await self.target_resolver.revalidate(target)
                yield manifest
            else:
                async with self.locks.acquire(lock_key, timeout):
                    if target and self.target_resolver:
                        await self.target_resolver.revalidate(target)
                    yield manifest
        finally:
            _current_context.reset(token)

    async def invoke_async(
        self,
        tool_name: str,
        function: Callable[..., T] | Callable[..., Awaitable[T]],
        arguments: Mapping[str, Any],
        principal: Principal,
    ) -> T:
        bounded = dict(arguments)
        signature = inspect.signature(function)
        manifest = self.manifest(tool_name)
        if "timeout_seconds" in signature.parameters:
            requested = float(bounded.get("timeout_seconds", manifest["timeout_ms"] / 1000))
            bounded["timeout_seconds"] = max(0.1, min(requested, manifest["timeout_ms"] / 1000))
        async with self.guard_async(tool_name, bounded, principal):
            result = function(**bounded)
            if inspect.isawaitable(result):
                return await result
            return result

    def invoke(
        self,
        tool_name: str,
        function: Callable[..., T],
        arguments: Mapping[str, Any],
        principal: Principal,
    ) -> T:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self.invoke_async(tool_name, function, arguments, principal))
        raise RuntimeError("invoke() cannot be used in an active event loop; use invoke_async()")
