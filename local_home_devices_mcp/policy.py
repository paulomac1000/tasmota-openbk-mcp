"""Transport-independent authorization, targeting, concurrency, and ownership."""

from __future__ import annotations

import asyncio
import inspect
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Awaitable, Callable, Mapping, TypeVar

from .config import Settings
from .manifests import (
    ManifestError,
    is_runtime_active,
    manifest_availability,
    manifest_timeout_seconds,
    normalize_catalog,
)
from .targeting import (
    BoundTarget,
    TargetError,
    TargetResolver,
    normalize_selector,
    validate_address,
)

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
    target_ids: frozenset[str] | None = None


@dataclass(slots=True)
class BackendOwnership:
    """Backend work that may outlive the client response deadline."""

    completion: asyncio.Future[Any] | asyncio.Task[Any] | None = None


@dataclass(slots=True)
class InvocationContext:
    principal: Principal
    request_id: str
    deadline: float
    target: BoundTarget | None
    ownership: BackendOwnership = field(default_factory=BackendOwnership)


_current_context: ContextVar[InvocationContext | None] = ContextVar(
    "mcp_invocation_context",
    default=None,
)


def current_context() -> InvocationContext | None:
    return _current_context.get()


def register_backend_completion(
    completion: asyncio.Future[Any] | asyncio.Task[Any],
) -> None:
    """Keep concurrency ownership until detached backend work actually stops."""
    context = current_context()
    if context is None:
        raise RuntimeError("backend completion requires an invocation context")
    if context.ownership.completion not in {None, completion}:
        raise RuntimeError("invocation already owns another backend worker")
    context.ownership.completion = completion


def _remaining(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("operation deadline exceeded")
    return remaining


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
class _PermitEntry:
    semaphore: asyncio.Semaphore
    limit: int
    users: int = 0


@dataclass(slots=True)
class _PermitLease:
    manager: "AsyncConcurrencyManager"
    key: str
    entry: _PermitEntry
    released: bool = False

    def release(self) -> None:
        if self.released:
            return
        self.released = True
        self.manager._release(self.key, self.entry)


class AsyncConcurrencyManager:
    """Bounded keyed semaphore registry implementing canonical scope + limit."""

    def __init__(self) -> None:
        self._entries: dict[str, _PermitEntry] = {}

    async def acquire(
        self,
        key: str,
        *,
        limit: int,
        timeout: float,
        queue_limit: int | None = None,
    ) -> _PermitLease:
        entry = self._entries.get(key)
        if entry is None:
            entry = _PermitEntry(asyncio.Semaphore(limit), limit)
            self._entries[key] = entry
        elif entry.limit != limit:
            raise PolicyError("concurrency contract changed while capability is active")
        if queue_limit is not None and entry.users >= limit + queue_limit:
            raise PolicyError("capability concurrency queue is full")

        entry.users += 1
        acquired = False
        try:
            await asyncio.wait_for(entry.semaphore.acquire(), timeout=timeout)
            acquired = True
            return _PermitLease(self, key, entry)
        except TimeoutError as exc:
            raise PolicyError("capability concurrency wait exceeded deadline") from exc
        finally:
            if not acquired:
                entry.users -= 1
                if entry.users == 0:
                    self._entries.pop(key, None)

    def _release(self, key: str, entry: _PermitEntry) -> None:
        entry.semaphore.release()
        entry.users -= 1
        if entry.users == 0 and self._entries.get(key) is entry:
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
        self.concurrency = AsyncConcurrencyManager()
        self.locks = self.concurrency
        self._supervisors: set[asyncio.Task[None]] = set()

    def manifest(self, capability_name: str) -> Mapping[str, Any]:
        try:
            return self.catalog[capability_name]
        except KeyError as exc:
            raise ManifestError(f"unclassified capability: {capability_name}") from exc

    def authorize(
        self,
        capability_name: str,
        arguments: Mapping[str, Any],
        principal: Principal,
    ) -> None:
        manifest = self.manifest(capability_name)
        if capability_name == "iot_execute_command" and "force" in arguments:
            raise PolicyError(
                "model input cannot override dangerous-operation policy"
            )
        if not is_runtime_active(manifest):
            raise CapabilityUnavailable(
                f"{capability_name} is {manifest['active_state']} "
                f"({manifest_availability(manifest)})"
            )

        operation = str(manifest["operation_kind"])
        if operation in {"write", "destructive"} and not self.settings.write_enabled:
            raise PolicyError("write operations are disabled by the operator")
        if (
            operation == "destructive" or manifest["risk"] == "critical"
        ) and not self.settings.dangerous_enabled:
            raise PolicyError("dangerous operations are disabled by the operator")

        if "devices:admin" not in principal.scopes:
            required = {str(item) for item in manifest["authorization_scopes"]}
            missing = sorted(required - principal.scopes)
            if missing:
                raise PolicyError(f"missing required scopes: {', '.join(missing)}")

        if manifest["requires_confirmation"]:
            raise PolicyError(
                "capability requires a server-verified approval record and is not invokable"
            )

        if (
            capability_name == "iot_set_power"
            and str(arguments.get("state", "")).upper() == "TOGGLE"
        ):
            raise PolicyError(
                "TOGGLE is non-idempotent; request explicit ON or OFF"
            )
        if "timeout_seconds" in arguments:
            maximum = manifest_timeout_seconds(manifest)
            try:
                requested = float(arguments["timeout_seconds"])
            except (TypeError, ValueError) as exc:
                raise PolicyError("timeout_seconds must be numeric") from exc
            if requested <= 0 or requested > maximum:
                raise PolicyError(
                    f"timeout_seconds must be between 0 and {maximum:g}"
                )

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
                    "literal IP targets are disabled; use an exact target_id "
                    "or device name"
                )

    @staticmethod
    def selector(arguments: Mapping[str, Any]) -> str | None:
        for key in ("target_id", "identifier", "ip_address", "ip"):
            value = arguments.get(key)
            if isinstance(value, str) and value.strip():
                return value
        return None

    @staticmethod
    def authorize_selector(
        selector: str | None,
        principal: Principal,
    ) -> None:
        """Reject selectors provably outside the caller namespace before resolution."""
        if (
            selector is None
            or "devices:admin" in principal.scopes
            or principal.target_ids is None
        ):
            return
        normalized = normalize_selector(selector)
        allowed = {normalize_selector(item) for item in principal.target_ids}
        if normalized.startswith("dev_") and normalized not in allowed:
            raise PolicyError(
                f"principal is not authorized for target selector: {selector}"
            )

    async def _resolve_target(
        self,
        arguments: Mapping[str, Any],
        principal: Principal,
    ) -> BoundTarget | None:
        selector = self.selector(arguments)
        if selector is None:
            return None
        self.authorize_selector(selector, principal)
        if self.target_resolver is None:
            raise PolicyError(
                "target resolver is unavailable for a target-bearing capability"
            )
        allowed = None if "devices:admin" in principal.scopes else principal.target_ids
        return await self.target_resolver.resolve(
            selector,
            allowed_target_ids=allowed,
        )

    @staticmethod
    def authorize_target(
        target: BoundTarget | None,
        principal: Principal,
    ) -> None:
        if target is None or "devices:admin" in principal.scopes:
            return
        if (
            principal.target_ids is not None
            and target.target_id not in principal.target_ids
        ):
            raise PolicyError(
                f"principal is not authorized for target: {target.target_id}"
            )

    @staticmethod
    def _concurrency_key(
        manifest: Mapping[str, Any],
        principal: Principal,
        target: BoundTarget | None,
        arguments: Mapping[str, Any],
    ) -> str:
        concurrency = manifest["concurrency"]
        scope = str(concurrency["scope"])
        capability_id = str(manifest["id"])
        if scope == "global":
            return "global"
        if scope == "capability":
            return f"capability:{capability_id}"
        if scope == "principal":
            return f"principal:{principal.subject}"
        if scope == "target":
            if target is None:
                raise PolicyError("target concurrency requires a bound target")
            return f"target:{target.target_id}"
        if scope == "principal-target":
            if target is None:
                raise PolicyError(
                    "principal-target concurrency requires a bound target"
                )
            return f"principal-target:{principal.subject}:{target.target_id}"

        extensions = manifest.get("extensions")
        key_argument = (
            extensions.get("concurrency_key_argument")
            if isinstance(extensions, Mapping)
            else None
        )
        if scope in {"credential", "resource", "custom"}:
            if not isinstance(key_argument, str) or not key_argument:
                raise PolicyError(
                    f"{scope} concurrency requires extensions.concurrency_key_argument"
                )
            value = arguments.get(key_argument)
            if not isinstance(value, str | int) or str(value) == "":
                raise PolicyError(
                    f"missing concurrency key argument: {key_argument}"
                )
            return f"{scope}:{value}"
        raise PolicyError(f"unsupported concurrency scope: {scope}")

    async def _acquire_permits(
        self,
        manifest: Mapping[str, Any],
        principal: Principal,
        target: BoundTarget | None,
        arguments: Mapping[str, Any],
        deadline: float,
    ) -> list[_PermitLease]:
        concurrency = manifest["concurrency"]
        key = self._concurrency_key(manifest, principal, target, arguments)
        queue_limit = concurrency.get("queue_limit")
        primary = await self.concurrency.acquire(
            key,
            limit=int(concurrency["limit"]),
            timeout=_remaining(deadline),
            queue_limit=int(queue_limit) if queue_limit is not None else None,
        )
        leases = [primary]
        global_limit = concurrency.get("global_limit")
        if global_limit is None or concurrency["scope"] == "global":
            return leases
        try:
            leases.append(
                await self.concurrency.acquire(
                    f"global-capability:{manifest['id']}",
                    limit=int(global_limit),
                    timeout=_remaining(deadline),
                )
            )
        except BaseException:
            primary.release()
            raise
        return leases

    def _defer_release(
        self,
        completion: asyncio.Future[Any] | asyncio.Task[Any],
        leases: list[_PermitLease],
    ) -> None:
        async def release_after_backend() -> None:
            try:
                await asyncio.shield(completion)
            except BaseException:
                pass
            finally:
                for lease in reversed(leases):
                    lease.release()

        task = asyncio.create_task(release_after_backend())
        self._supervisors.add(task)
        task.add_done_callback(self._supervisors.discard)

    @property
    def supervisor_count(self) -> int:
        return len(self._supervisors)

    @asynccontextmanager
    async def guard_async(
        self,
        capability_name: str,
        arguments: Mapping[str, Any],
        principal: Principal,
        *,
        deadline: float | None = None,
    ) -> AsyncIterator[Mapping[str, Any]]:
        manifest = self.manifest(capability_name)
        budget = manifest_timeout_seconds(manifest)
        ingress_deadline = time.monotonic() + budget
        absolute_deadline = (
            ingress_deadline if deadline is None else min(deadline, ingress_deadline)
        )
        context = InvocationContext(
            principal=principal,
            request_id=f"req_{time.time_ns():x}",
            deadline=absolute_deadline,
            target=None,
        )
        token = _current_context.set(context)
        leases: list[_PermitLease] = []
        deferred = False
        try:
            async with asyncio.timeout_at(absolute_deadline):
                await self.rate_limiter.check(principal.subject)
                self.authorize(capability_name, arguments, principal)
                target = await self._resolve_target(arguments, principal)
                self.authorize_target(target, principal)
                context.target = target
                leases = await self._acquire_permits(
                    manifest,
                    principal,
                    target,
                    arguments,
                    absolute_deadline,
                )
                if target and self.target_resolver:
                    await self.target_resolver.revalidate(target)
                yield manifest
        finally:
            _current_context.reset(token)
            completion = context.ownership.completion
            if completion is not None and not completion.done() and leases:
                deferred = True
                self._defer_release(completion, leases)
            if not deferred:
                for lease in reversed(leases):
                    lease.release()

    async def invoke_async(
        self,
        capability_name: str,
        function: Callable[..., T] | Callable[..., Awaitable[T]],
        arguments: Mapping[str, Any],
        principal: Principal,
        *,
        deadline: float | None = None,
    ) -> T:
        bounded = dict(arguments)
        signature = inspect.signature(function)
        manifest = self.manifest(capability_name)
        maximum = manifest_timeout_seconds(manifest)
        if "timeout_seconds" in signature.parameters:
            requested = float(bounded.get("timeout_seconds", maximum))
            bounded["timeout_seconds"] = max(0.1, min(requested, maximum))
        async with self.guard_async(
            capability_name,
            bounded,
            principal,
            deadline=deadline,
        ):
            result = function(**bounded)
            if inspect.isawaitable(result):
                return await result
            return result

    def invoke(
        self,
        capability_name: str,
        function: Callable[..., T],
        arguments: Mapping[str, Any],
        principal: Principal,
    ) -> T:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(
                self.invoke_async(
                    capability_name,
                    function,
                    arguments,
                    principal,
                )
            )
        raise RuntimeError(
            "invoke() cannot be used in an active event loop; use invoke_async()"
        )
