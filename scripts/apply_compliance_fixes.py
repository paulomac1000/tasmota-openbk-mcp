from __future__ import annotations

import re
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AI_SKILLS_REVISION = "b54fc6b27ea80b36a70d5de73445970e17f55789"


def path(name: str) -> Path:
    return ROOT / name


def read(name: str) -> str:
    return path(name).read_text(encoding="utf-8")


def write(name: str, content: str) -> None:
    path(name).write_text(content, encoding="utf-8")


def replace_once(name: str, old: str, new: str) -> None:
    content = read(name)
    count = content.count(old)
    if count != 1:
        raise RuntimeError(f"{name}: expected one occurrence, got {count}: {old[:80]!r}")
    write(name, content.replace(old, new, 1))


def replace_all(name: str, old: str, new: str, *, minimum: int = 1) -> None:
    content = read(name)
    count = content.count(old)
    if count < minimum:
        raise RuntimeError(f"{name}: expected at least {minimum} occurrences, got {count}: {old!r}")
    write(name, content.replace(old, new))


def regex_once(name: str, pattern: str, replacement: str) -> None:
    content = read(name)
    updated, count = re.subn(pattern, replacement, content, count=1, flags=re.MULTILINE | re.DOTALL)
    if count != 1:
        raise RuntimeError(f"{name}: regex expected one occurrence, got {count}: {pattern[:100]!r}")
    write(name, updated)


def dedent(value: str) -> str:
    return textwrap.dedent(value).lstrip("\n")


# ---------------------------------------------------------------------------
# 2.0 contract identity
# ---------------------------------------------------------------------------
replace_once("pyproject.toml", 'version = "1.7.0"', 'version = "2.0.0"')
replace_once("tools/__init__.py", '__version__ = "1.7.0"', '__version__ = "2.0.0"')
replace_once("tools/constants.py", 'TOOLS_VERSION = "1.7.0"', 'TOOLS_VERSION = "2.0.0"')
replace_all("tests/unit/test_constants.py", '"1.7.0"', '"2.0.0"', minimum=2)

# Retire obsolete server-level configuration aliases from the legacy adapter module.
replace_once(
    "tools/constants.py",
    '''MCP_SSE_PORT = int(os.getenv("MCP_SSE_PORT", "9101"))\nREST_API_PORT = int(os.getenv("REST_API_PORT", "9102"))\n\n# Streamable HTTP transport\nMCP_TRANSPORT = os.getenv("MCP_TRANSPORT", "both")  # streamable-http, sse, both\nMCP_ALLOWED_ORIGINS = os.getenv("MCP_ALLOWED_ORIGINS", "http://localhost:*")\n\nHEALTH_CHECK_PORT = int(os.getenv("HEALTH_CHECK_PORT", "9100"))\n''',
    "",
)
replace_once(
    "tools/constants.py",
    '''BIND_HOST = os.getenv("BIND_HOST", "127.0.0.1")\nALLOW_PUBLIC_BIND = os.getenv("MCP_UNSAFE_PUBLIC_ACCESS_CONFIRMED", "0") == "1"\n\n''',
    "",
)
replace_once(
    "tools/constants.py",
    '''# Server-level write guard. Write and destructive tools are rejected before any\n# I/O unless this flag is explicitly enabled. This is a server-level authorization\n# gate decided by the operator - distinct from the per-tool `requires_confirmation`\n# manifest field, which is an agent-level user-consent hint.\nENABLE_WRITE_OPERATIONS = os.getenv("ENABLE_WRITE_OPERATIONS", "0") == "1"\n''',
    '''# Compatibility fallback for direct legacy-adapter tests and scripts. Public MCP\n# calls use the immutable Settings snapshot carried by InvocationContext instead.\nENABLE_WRITE_OPERATIONS = os.getenv("ENABLE_WRITE_OPERATIONS", "0") == "1"\n''',
)
regex_once(
    "tools/constants.py",
    r'''def check_write_enabled\(\) -> None:\n    """Raise ValidationError when server-level write operations are disabled\..*?\n        \)\n''',
    '''def check_write_enabled() -> None:\n    """Fail closed unless the governed invocation or legacy fallback enables writes.\n\n    Public MCP calls are authorized by ``OperationGate`` using the immutable\n    ``Settings`` snapshot. The module-level environment flag remains only for\n    direct legacy-adapter tests and scripts that do not run through the gate.\n    """\n    try:\n        from local_home_devices_mcp.policy import current_context\n    except ImportError:\n        context = None\n    else:\n        context = current_context()\n\n    if context is not None:\n        if context.operation_kind not in {"write", "destructive"}:\n            raise ValidationError("legacy write guard reached from a non-mutating capability")\n        if not context.settings.write_enabled:\n            raise ValidationError("Write operations are disabled by operator policy.")\n        return\n\n    if not ENABLE_WRITE_OPERATIONS:\n        raise ValidationError(\n            "Write operations are disabled. Set ENABLE_WRITE_OPERATIONS=1 on the server to enable."\n        )\n''',
)

# ---------------------------------------------------------------------------
# Immutable HTTP ingress/admission configuration
# ---------------------------------------------------------------------------
replace_once(
    "local_home_devices_mcp/config.py",
    '''    http_max_connections: int = 64\n    http_queue_limit: int = 32\n''',
    '''    http_max_connections: int = 64\n    http_queue_limit: int = 32\n    http_queue_wait_ms: int = 1000\n    http_ingress_timeout_ms: int = 5000\n''',
)
replace_once(
    "local_home_devices_mcp/config.py",
    '''        http_queue_limit=_int(\n            "MCP_HTTP_QUEUE_LIMIT",\n            32,\n            minimum=0,\n            maximum=4096,\n        ),\n    )\n''',
    '''        http_queue_limit=_int(\n            "MCP_HTTP_QUEUE_LIMIT",\n            32,\n            minimum=0,\n            maximum=4096,\n        ),\n        http_queue_wait_ms=_int(\n            "MCP_HTTP_QUEUE_WAIT_MS",\n            1000,\n            minimum=1,\n            maximum=60_000,\n        ),\n        http_ingress_timeout_ms=_int(\n            "MCP_HTTP_INGRESS_TIMEOUT_MS",\n            5000,\n            minimum=100,\n            maximum=60_000,\n        ),\n    )\n''',
)

HTTP_BOUNDARY = dedent(r'''
    """Bounded ASGI boundary for stateless JSON Streamable HTTP transport."""

    from __future__ import annotations

    import asyncio
    from collections.abc import Awaitable, Callable, Mapping, MutableMapping
    from contextvars import ContextVar
    from dataclasses import dataclass, field
    from typing import Any

    from .config import Settings

    ASGIMessage = MutableMapping[str, Any]
    Receive = Callable[[], Awaitable[ASGIMessage]]
    Send = Callable[[ASGIMessage], Awaitable[None]]
    ASGIApp = Callable[[Mapping[str, Any], Receive, Send], Awaitable[None]]

    _wire_response_limit: ContextVar[int | None] = ContextVar(
        "mcp_wire_response_limit",
        default=None,
    )


    def set_wire_response_limit(limit: int) -> None:
        """Lower the request-local final wire response body limit."""
        current = _wire_response_limit.get()
        if current is None or limit < current:
            _wire_response_limit.set(limit)


    def current_wire_response_limit(default: int) -> int:
        current = _wire_response_limit.get()
        return default if current is None else min(default, current)


    @dataclass(slots=True)
    class _Admission:
        semaphore: asyncio.Semaphore
        queue_limit: int
        waiters: int = 0
        lock: asyncio.Lock | None = None

        def __post_init__(self) -> None:
            self.lock = asyncio.Lock()

        async def acquire(self, timeout_seconds: float) -> bool:
            assert self.lock is not None
            async with self.lock:
                if not self.semaphore.locked():
                    await self.semaphore.acquire()
                    return True
                if self.waiters >= self.queue_limit:
                    return False
                self.waiters += 1
            try:
                try:
                    await asyncio.wait_for(self.semaphore.acquire(), timeout=timeout_seconds)
                except TimeoutError:
                    return False
                return True
            finally:
                async with self.lock:
                    self.waiters -= 1

        def release(self) -> None:
            self.semaphore.release()


    def _header_bytes(headers: list[tuple[bytes, bytes]]) -> int:
        return sum(len(name) + len(value) + 4 for name, value in headers)


    def _header_values(headers: list[tuple[bytes, bytes]], name: bytes) -> list[str]:
        wanted = name.lower()
        return [value.decode("latin-1") for key, value in headers if key.lower() == wanted]


    def _host_matches(raw_host: str, allowed_hosts: tuple[str, ...]) -> bool:
        raw = raw_host.strip().lower().rstrip(".")
        allowed = {item.lower().rstrip(".") for item in allowed_hosts}
        if raw in allowed:
            return True
        if raw.startswith("["):
            closing = raw.find("]")
            host_only = raw[: closing + 1] if closing >= 0 else raw
        elif raw.count(":") == 1:
            host_only = raw.rsplit(":", 1)[0]
        else:
            host_only = raw
        return host_only in allowed


    async def _plain_response(send: Send, status: int, message: str) -> None:
        body = message.encode("utf-8")
        await send(
            {
                "type": "http.response.start",
                "status": status,
                "headers": [
                    (b"content-type", b"text/plain; charset=utf-8"),
                    (b"content-length", str(len(body)).encode("ascii")),
                    (b"cache-control", b"no-store"),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body, "more_body": False})


    async def _buffer_request(receive: Receive, maximum: int) -> bytes | None:
        body = bytearray()
        while True:
            message = await receive()
            kind = message.get("type")
            if kind == "http.disconnect":
                return None
            if kind != "http.request":
                continue
            raw = message.get("body", b"")
            if not isinstance(raw, bytes | bytearray):
                raise ValueError("request body must be bytes")
            body.extend(raw)
            if len(body) > maximum:
                raise ValueError("request body exceeds configured limit")
            if not message.get("more_body", False):
                return bytes(body)


    def _replay_receive(body: bytes) -> Receive:
        sent = False

        async def receive() -> ASGIMessage:
            nonlocal sent
            if not sent:
                sent = True
                return {"type": "http.request", "body": body, "more_body": False}
            await asyncio.sleep(0)
            return {"type": "http.disconnect"}

        return receive


    @dataclass(slots=True)
    class _ResponseCapture:
        """Bound response memory while withholding bytes until limits are proven."""

        settings: Settings
        start: ASGIMessage | None = None
        body: bytearray = field(default_factory=bytearray)
        error: str | None = None
        saw_body: bool = False

        async def send(self, message: ASGIMessage) -> None:
            kind = message.get("type")
            if kind == "http.response.start":
                if self.start is not None:
                    self.error = "invalid server response"
                    return
                headers = list(message.get("headers") or [])
                if _header_bytes(headers) > self.settings.http_max_header_bytes:
                    self.error = "response headers exceed configured limit"
                    return
                lengths = _header_values(headers, b"content-length")
                if len(lengths) > 1:
                    self.error = "invalid server response"
                    return
                if lengths:
                    try:
                        declared = int(lengths[0])
                    except ValueError:
                        self.error = "invalid server response"
                        return
                    maximum = current_wire_response_limit(self.settings.max_response_bytes)
                    if declared < 0 or declared > maximum:
                        self.error = "response exceeds configured wire limit"
                        return
                self.start = dict(message)
                return

            if kind != "http.response.body":
                self.error = "invalid server response"
                return
            self.saw_body = True
            if self.error is not None:
                return
            raw_body = message.get("body", b"")
            if not isinstance(raw_body, bytes | bytearray):
                self.error = "invalid server response"
                return
            maximum = current_wire_response_limit(self.settings.max_response_bytes)
            if len(self.body) + len(raw_body) > maximum:
                self.body.clear()
                self.error = "response exceeds configured wire limit"
                return
            self.body.extend(raw_body)

        async def flush(self, send: Send) -> None:
            if self.error is not None:
                await _plain_response(send, 500, self.error)
                return
            if self.start is None:
                await _plain_response(send, 500, "invalid server response")
                return
            maximum = current_wire_response_limit(self.settings.max_response_bytes)
            if len(self.body) > maximum:
                await _plain_response(send, 500, "response exceeds configured wire limit")
                return
            await send(self.start)
            await send(
                {
                    "type": "http.response.body",
                    "body": bytes(self.body),
                    "more_body": False,
                }
            )


    class HttpBoundaryMiddleware:
        """Enforce host/origin/size/admission policy before MCP dispatch.

        The server intentionally runs FastMCP with ``json_response=True`` and
        ``stateless_http=True``. Responses are therefore captured only up to the
        configured wire limit, then emitted once their final size is proven.
        """

        def __init__(self, app: ASGIApp, settings: Settings) -> None:
            self.app = app
            self.settings = settings
            self._admission = _Admission(
                asyncio.Semaphore(settings.http_max_connections),
                settings.http_queue_limit,
            )

        async def __call__(
            self,
            scope: Mapping[str, Any],
            receive: Receive,
            send: Send,
        ) -> None:
            if scope.get("type") != "http":
                await self.app(scope, receive, send)
                return

            headers = list(scope.get("headers") or [])
            if _header_bytes(headers) > self.settings.http_max_header_bytes:
                await _plain_response(send, 431, "request headers too large")
                return

            host_values = _header_values(headers, b"host")
            if len(host_values) != 1 or not _host_matches(host_values[0], self.settings.allowed_hosts):
                await _plain_response(send, 400, "host is not allowed")
                return

            origin_values = _header_values(headers, b"origin")
            if len(origin_values) > 1:
                await _plain_response(send, 400, "multiple origin headers are not allowed")
                return
            if origin_values and origin_values[0] not in self.settings.allowed_origins:
                await _plain_response(send, 403, "origin is not allowed")
                return

            content_length_values = _header_values(headers, b"content-length")
            if len(content_length_values) > 1:
                await _plain_response(send, 400, "multiple content-length headers are not allowed")
                return
            if content_length_values:
                try:
                    declared_length = int(content_length_values[0])
                except ValueError:
                    await _plain_response(send, 400, "invalid content-length")
                    return
                if declared_length < 0 or declared_length > self.settings.http_max_body_bytes:
                    await _plain_response(send, 413, "request body too large")
                    return

            admitted = await self._admission.acquire(self.settings.http_queue_wait_ms / 1000)
            if not admitted:
                await _plain_response(send, 503, "request queue is full or wait deadline exceeded")
                return

            try:
                try:
                    async with asyncio.timeout(self.settings.http_ingress_timeout_ms / 1000):
                        body = await _buffer_request(receive, self.settings.http_max_body_bytes)
                except TimeoutError:
                    await _plain_response(send, 408, "request body deadline exceeded")
                    return
                except ValueError:
                    await _plain_response(send, 413, "request body too large")
                    return
                if body is None:
                    return

                token = _wire_response_limit.set(self.settings.max_response_bytes)
                capture = _ResponseCapture(self.settings)
                try:
                    await self.app(scope, _replay_receive(body), capture.send)
                    await capture.flush(send)
                finally:
                    _wire_response_limit.reset(token)
            finally:
                self._admission.release()
''')
write("local_home_devices_mcp/http_boundary.py", HTTP_BOUNDARY)

# ---------------------------------------------------------------------------
# Bounded principal rate-limiter registry and invocation context ownership
# ---------------------------------------------------------------------------
regex_once(
    "local_home_devices_mcp/policy.py",
    r'''class AsyncSlidingWindowLimiter:\n.*?\n\n@dataclass\(slots=True\)\nclass _PermitEntry:''',
    '''class AsyncSlidingWindowLimiter:\n    def __init__(\n        self,\n        limit: int = 60,\n        window_seconds: float = 60.0,\n        max_principals: int = 4096,\n    ) -> None:\n        if limit < 1 or window_seconds <= 0 or max_principals < 1:\n            raise ValueError("rate limiter bounds must be positive")\n        self.limit = limit\n        self.window_seconds = window_seconds\n        self.max_principals = max_principals\n        self._events: dict[str, deque[float]] = {}\n        self._lock = asyncio.Lock()\n        self._next_prune_at = 0.0\n\n    def _prune_locked(self, now: float, *, force: bool = False) -> None:\n        if not force and now < self._next_prune_at:\n            return\n        cutoff = now - self.window_seconds\n        for key in list(self._events):\n            events = self._events[key]\n            while events and events[0] <= cutoff:\n                events.popleft()\n            if not events:\n                del self._events[key]\n        self._next_prune_at = now + min(5.0, self.window_seconds / 4)\n\n    async def check(self, key: str, now: float | None = None) -> None:\n        now = time.monotonic() if now is None else now\n        cutoff = now - self.window_seconds\n        async with self._lock:\n            self._prune_locked(now)\n            events = self._events.get(key)\n            if events is None:\n                if len(self._events) >= self.max_principals:\n                    self._prune_locked(now, force=True)\n                if len(self._events) >= self.max_principals:\n                    raise RateLimitExceeded("rate limiter principal capacity exceeded")\n                events = deque()\n                self._events[key] = events\n            while events and events[0] <= cutoff:\n                events.popleft()\n            if len(events) >= self.limit:\n                raise RateLimitExceeded("rate limit exceeded")\n            events.append(now)\n\n    @property\n    def entry_count(self) -> int:\n        return len(self._events)\n\n\n@dataclass(slots=True)\nclass _PermitEntry:''',
)
replace_once(
    "local_home_devices_mcp/policy.py",
    '''class InvocationContext:\n    principal: Principal\n    request_id: str\n    deadline: float\n    target: BoundTarget | None\n    ownership: BackendOwnership = field(default_factory=BackendOwnership)\n''',
    '''class InvocationContext:\n    principal: Principal\n    request_id: str\n    deadline: float\n    settings: Settings\n    operation_kind: str\n    target: BoundTarget | None\n    ownership: BackendOwnership = field(default_factory=BackendOwnership)\n''',
)
replace_once(
    "local_home_devices_mcp/policy.py",
    '''        rate_limit_per_minute: int = 60,\n    ) -> None:\n''',
    '''        rate_limit_per_minute: int = 60,\n        rate_limit_max_principals: int = 4096,\n    ) -> None:\n''',
)
replace_once(
    "local_home_devices_mcp/policy.py",
    '''        self.rate_limiter = AsyncSlidingWindowLimiter(rate_limit_per_minute)\n''',
    '''        self.rate_limiter = AsyncSlidingWindowLimiter(\n            rate_limit_per_minute,\n            max_principals=rate_limit_max_principals,\n        )\n''',
)
replace_once(
    "local_home_devices_mcp/policy.py",
    '''        context = InvocationContext(\n            principal=principal,\n            request_id=f"req_{time.time_ns():x}",\n            deadline=absolute_deadline,\n            target=None,\n        )\n''',
    '''        context = InvocationContext(\n            principal=principal,\n            request_id=f"req_{time.time_ns():x}",\n            deadline=absolute_deadline,\n            settings=self.settings,\n            operation_kind=str(manifest["operation_kind"]),\n            target=None,\n        )\n''',
)

# ---------------------------------------------------------------------------
# Legacy monkey-patches resolve Settings from the active invocation, not first install.
# ---------------------------------------------------------------------------
replace_once(
    "local_home_devices_mcp/legacy_compat.py",
    '''_thread_limiter = anyio.CapacityLimiter(8)\n_TARGET_ARGUMENTS = ("target_id", "identifier", "ip_address", "ip")\n''',
    '''_thread_limiter = anyio.CapacityLimiter(8)\n_TARGET_ARGUMENTS = ("target_id", "identifier", "ip_address", "ip")\n_fallback_settings: Settings | None = None\n\n\ndef _settings_for_call() -> Settings:\n    from .policy import current_context\n\n    context = current_context()\n    if context is not None:\n        return context.settings\n    if _fallback_settings is None:\n        raise RuntimeError("legacy safety settings are not installed")\n    return _fallback_settings\n''',
)
replace_once(
    "local_home_devices_mcp/legacy_compat.py",
    '''def install_legacy_safety(settings: Settings) -> None:\n    import importlib\n''',
    '''def install_legacy_safety(settings: Settings) -> None:\n    import importlib\n\n    global _fallback_settings\n    _fallback_settings = settings\n''',
)
replace_all(
    "local_home_devices_mcp/legacy_compat.py",
    "validate_address(address, settings)",
    "validate_address(address, _settings_for_call())",
)
replace_once(
    "local_home_devices_mcp/legacy_compat.py",
    '''                    iot_discovery._get_cached_devices(),\n                    settings,\n                )\n''',
    '''                    iot_discovery._get_cached_devices(),\n                    _settings_for_call(),\n                )\n''',
)

# Readiness is a public operational contract, not merely a registration count.
replace_once(
    "local_home_devices_mcp/targeting.py",
    '''    async def revalidate(self, target: BoundTarget) -> None: ...\n''',
    '''    async def revalidate(self, target: BoundTarget) -> None: ...\n\n    async def readiness(self) -> Mapping[str, Any]: ...\n''',
)
replace_once(
    "local_home_devices_mcp/mock_runtime.py",
    '''    async def revalidate(self, target: BoundTarget) -> None:\n        self.revalidations += 1\n        if target.target_id != "dev_mock_light" or target.fingerprint != "mock-fingerprint-v1":\n            raise TargetNotFound("mock target binding changed")\n''',
    '''    async def revalidate(self, target: BoundTarget) -> None:\n        self.revalidations += 1\n        if target.target_id != "dev_mock_light" or target.fingerprint != "mock-fingerprint-v1":\n            raise TargetNotFound("mock target binding changed")\n\n    async def readiness(self) -> dict[str, Any]:\n        return {"status": "ready", "valid_targets": 1, "source": "mock"}\n''',
)
replace_once(
    "local_home_devices_mcp/legacy_compat.py",
    '''    async def revalidate(self, target: BoundTarget) -> None:\n        devices = await asyncio.to_thread(self._devices)\n        matches = [record for record in devices if str(record.get("ip", "")) == target.address]\n        if len(matches) != 1:\n            raise TargetNotFound("authorized target disappeared or became ambiguous")\n        revalidate_binding(target, matches[0], self.settings)\n''',
    '''    async def revalidate(self, target: BoundTarget) -> None:\n        devices = await asyncio.to_thread(self._devices)\n        matches = [record for record in devices if str(record.get("ip", "")) == target.address]\n        if len(matches) != 1:\n            raise TargetNotFound("authorized target disappeared or became ambiguous")\n        revalidate_binding(target, matches[0], self.settings)\n\n    async def readiness(self) -> dict[str, Any]:\n        from .targeting import TargetError, target_id_for\n\n        try:\n            devices = await asyncio.to_thread(self._devices)\n        except Exception as exc:\n            return {\n                "status": "unavailable",\n                "reason": f"registry-read-failed:{type(exc).__name__}",\n                "valid_targets": 0,\n            }\n        valid = 0\n        for record in devices:\n            try:\n                target_id_for(record)\n                validate_address(str(record.get("ip", "")), self.settings)\n            except TargetError:\n                continue\n            valid += 1\n        return {\n            "status": "ready" if valid else "unavailable",\n            "reason": "available" if valid else "no-valid-stable-targets",\n            "discovered_targets": len(devices),\n            "valid_targets": valid,\n        }\n''',
)

# ---------------------------------------------------------------------------
# Artifact root component symlink policy and readiness.
# ---------------------------------------------------------------------------
replace_once(
    "local_home_devices_mcp/artifacts.py",
    '''class ArtifactStore:\n    def __init__(\n''',
    '''def _reject_symlink_components(root: Path) -> None:\n    absolute = root.absolute()\n    current = Path(absolute.anchor)\n    for part in absolute.parts[1:]:\n        current /= part\n        if current.is_symlink():\n            raise ArtifactError(f"artifact root contains a symlink component: {current}")\n\n\nclass ArtifactStore:\n    def __init__(\n''',
)
replace_once(
    "local_home_devices_mcp/artifacts.py",
    '''    ) -> None:\n        self.root = root.resolve()\n        self.max_artifact_bytes = max_artifact_bytes\n''',
    '''    ) -> None:\n        _reject_symlink_components(root)\n        self.root = root.resolve()\n        self.max_artifact_bytes = max_artifact_bytes\n''',
)
replace_once(
    "local_home_devices_mcp/artifacts.py",
    '''    def _paths(self, artifact_id: str) -> tuple[Path, Path]:\n''',
    '''    def readiness(self) -> dict[str, object]:\n        try:\n            metadata = self.root.stat()\n        except OSError as exc:\n            return {"status": "unavailable", "reason": type(exc).__name__}\n        if not self.root.is_dir():\n            return {"status": "unavailable", "reason": "root-is-not-directory"}\n        if not os.access(self.root, os.R_OK | os.W_OK):\n            return {"status": "unavailable", "reason": "root-is-not-readable-writable"}\n        return {\n            "status": "ready",\n            "mode": oct(metadata.st_mode & 0o777),\n            "root": str(self.root),\n        }\n\n    def _paths(self, artifact_id: str) -> tuple[Path, Path]:\n''',
)

# ---------------------------------------------------------------------------
# Structured public error taxonomy, strict claims parsing and dependency readiness.
# ---------------------------------------------------------------------------
replace_once(
    "local_home_devices_mcp/composition.py",
    '''from .policy import OperationGate, PolicyError, Principal, current_context\n''',
    '''from .policy import (\n    CapabilityUnavailable,\n    OperationGate,\n    PolicyError,\n    Principal,\n    RateLimitExceeded,\n    current_context,\n)\n''',
)
replace_once(
    "local_home_devices_mcp/composition.py",
    '''from .targeting import TargetError\n''',
    '''from .targeting import AmbiguousTarget, TargetError, TargetNotAuthorized, TargetNotFound\n''',
)
replace_once(
    "local_home_devices_mcp/composition.py",
    '''class PublicInvocationError(RuntimeError):\n    """Safe error crossing a public MCP component boundary."""\n''',
    '''class PublicInvocationError(RuntimeError):\n    """Stable machine-readable error crossing a public MCP boundary."""\n\n    def __init__(\n        self,\n        code: str,\n        message: str,\n        *,\n        retryable: bool = False,\n        unknown_outcome: bool = False,\n    ) -> None:\n        super().__init__(message)\n        self.code = code\n        self.message = message\n        self.retryable = retryable\n        self.unknown_outcome = unknown_outcome\n\n    def payload(self) -> dict[str, object]:\n        return {\n            "code": self.code,\n            "message": self.message,\n            "retryable": self.retryable,\n            "unknown_outcome": self.unknown_outcome,\n        }\n\n    def __str__(self) -> str:\n        return json.dumps(self.payload(), sort_keys=True, separators=(",", ":"))\n''',
)
replace_once(
    "local_home_devices_mcp/composition.py",
    '''    except PackageNotFoundError:\n        return "1.7.0"\n''',
    '''    except PackageNotFoundError:\n        return "2.0.0"\n''',
)
regex_once(
    "local_home_devices_mcp/composition.py",
    r'''    claims = getattr\(token, "claims", None\) or \{\}\n    subject = str\(.*?\n    return Principal\(subject, scopes, "http", target_ids\)\n''',
    '''    raw_claims = getattr(token, "claims", None) or {}\n    if not isinstance(raw_claims, Mapping):\n        raise PolicyError("HTTP authentication claims must be an object")\n    claims = raw_claims\n    subject = str(\n        getattr(token, "client_id", None)\n        or claims.get("sub")\n        or claims.get("client_id")\n        or "authenticated"\n    )\n    raw_scopes = getattr(token, "scopes", None) or []\n    if isinstance(raw_scopes, str) or not all(\n        isinstance(item, str) and item.strip() for item in raw_scopes\n    ):\n        raise PolicyError("HTTP authentication scopes are malformed")\n    scopes = frozenset(item.strip() for item in raw_scopes)\n    raw_targets = claims.get("targets")\n    if raw_targets is None or raw_targets == "*":\n        target_ids = None\n    elif isinstance(raw_targets, str):\n        if not raw_targets.strip():\n            raise PolicyError("HTTP target claim must not be empty")\n        target_ids = frozenset({raw_targets.strip()})\n    elif isinstance(raw_targets, list | tuple | set | frozenset):\n        if not raw_targets or not all(\n            isinstance(item, str) and item.strip() and item != "*" for item in raw_targets\n        ):\n            raise PolicyError("HTTP target claim is malformed")\n        target_ids = frozenset(item.strip() for item in raw_targets)\n    else:\n        raise PolicyError("HTTP target claim is malformed")\n    return Principal(subject, scopes, "http", target_ids)\n''',
)
regex_once(
    "local_home_devices_mcp/composition.py",
    r'''async def _invoke_public_component\[T\]\(.*?\n\n\ndef _install_policy_middleware''',
    '''async def _invoke_public_component[T](\n    gate: OperationGate,\n    settings: Settings,\n    capability_name: str,\n    arguments: Mapping[str, Any],\n    principal: Principal,\n    callback: Callable[[], Awaitable[T]],\n) -> T:\n    """Run every public MCP component through one typed governance boundary."""\n    manifest = gate.manifest(capability_name)\n    maximum = effective_response_limit(manifest, settings)\n    set_wire_response_limit(maximum)\n    deadline = time.monotonic() + manifest_timeout_seconds(manifest)\n    operation_kind = str(manifest["operation_kind"])\n    execution_started = False\n    try:\n        async with gate.guard_async(\n            capability_name,\n            arguments,\n            principal,\n            deadline=deadline,\n        ):\n            execution_started = True\n            result = await callback()\n            if encoded_response_bytes(result) > maximum:\n                raise PublicInvocationError(\n                    "RESPONSE_TOO_LARGE",\n                    f"final response exceeds {maximum} bytes",\n                )\n            return result\n    except TimeoutError as exc:\n        unknown = execution_started and operation_kind in {"write", "destructive"}\n        if unknown:\n            raise PublicInvocationError(\n                "UNKNOWN_OUTCOME",\n                "operation deadline exceeded after mutation execution started; "\n                "reconcile state before any retry",\n                unknown_outcome=True,\n            ) from exc\n        raise PublicInvocationError("DEADLINE_EXCEEDED", "operation deadline exceeded") from exc\n    except LegacyToolFailure as exc:\n        raise PublicInvocationError(exc.code, str(exc)) from exc\n    except PublicInvocationError:\n        raise\n    except CapabilityUnavailable as exc:\n        raise PublicInvocationError("CAPABILITY_UNAVAILABLE", str(exc)) from exc\n    except RateLimitExceeded as exc:\n        raise PublicInvocationError("RATE_LIMITED", str(exc)) from exc\n    except TargetNotFound as exc:\n        raise PublicInvocationError("TARGET_NOT_FOUND", str(exc)) from exc\n    except AmbiguousTarget as exc:\n        raise PublicInvocationError("AMBIGUOUS_TARGET", str(exc)) from exc\n    except TargetNotAuthorized as exc:\n        raise PublicInvocationError("TARGET_NOT_AUTHORIZED", str(exc)) from exc\n    except TargetError as exc:\n        raise PublicInvocationError("INVALID_TARGET", str(exc)) from exc\n    except ArtifactError as exc:\n        raise PublicInvocationError("ARTIFACT_UNAVAILABLE", "artifact is unavailable") from exc\n    except PolicyError as exc:\n        raise PublicInvocationError("FORBIDDEN", str(exc)) from exc\n    except ManifestError as exc:\n        logging.getLogger(__name__).error(\n            "capability contract failed for %s: %s", capability_name, type(exc).__name__\n        )\n        raise PublicInvocationError(\n            "INTERNAL_CONTRACT_ERROR", "internal capability contract failure"\n        ) from exc\n    except Exception as exc:\n        logging.getLogger(__name__).error(\n            "public component failed for %s: %s",\n            capability_name,\n            type(exc).__name__,\n        )\n        raise PublicInvocationError("INTERNAL", "internal component failure") from exc\n\n\ndef _install_policy_middleware''',
)
replace_once(
    "local_home_devices_mcp/composition.py",
    '''                except ValidationError as exc:\n                    raise PublicInvocationError(str(exc)) from exc\n''',
    '''                except ValidationError as exc:\n                    raise PublicInvocationError("INVALID_ARGUMENT", str(exc)) from exc\n''',
)
regex_once(
    "local_home_devices_mcp/composition.py",
    r'''    @mcp\.custom_route\("/ready", methods=\["GET"\]\)\n    async def ready\(_request: Any\) -> JSONResponse:\n.*?\n\n    return mcp, gate''',
    '''    @mcp.custom_route("/ready", methods=["GET"])\n    async def ready(_request: Any) -> JSONResponse:\n        # Operator readiness bypasses caller filtering but includes mandatory\n        # local dependency state, not just registration counts.\n        listed_tools = await mcp.list_tools(run_middleware=False)\n        registered_tools = {str(getattr(tool, "name", tool)) for tool in listed_tools}\n        active_tools = {\n            name for name, manifest in tool_catalog.items() if is_runtime_active(manifest)\n        }\n        unexpected_tools = sorted(registered_tools - set(tool_catalog))\n        missing_tools = sorted(active_tools - registered_tools)\n\n        templates = await mcp.list_resource_templates(run_middleware=False)\n        registered_templates = {str(key) for key in templates}\n        artifact_registered = any("artifact://" in item for item in registered_templates)\n        resource_ok = artifact_registered and "artifact_read" in gate.catalog\n\n        resolver_report = await target_resolver.readiness()\n        artifact_report = artifact_store.readiness()\n        dependency_ok = (\n            resolver_report.get("status") == "ready"\n            and artifact_report.get("status") == "ready"\n        )\n        structural_ok = not unexpected_tools and not missing_tools and resource_ok\n        status = "ready" if structural_ok and dependency_ok else "not-ready"\n        return JSONResponse(\n            {\n                "status": status,\n                "registered_tools": len(registered_tools),\n                "governed_components": len(gate.catalog),\n                "unexpected_registered_tools": unexpected_tools,\n                "missing_active_tools": missing_tools,\n                "artifact_resource_governed": resource_ok,\n                "dependencies": {\n                    "target_registry": resolver_report,\n                    "artifact_store": artifact_report,\n                },\n            },\n            status_code=200 if status == "ready" else 503,\n        )\n\n    return mcp, gate''',
)

# ---------------------------------------------------------------------------
# CI pin and release promotion trust boundary
# ---------------------------------------------------------------------------
replace_once(
    ".github/workflows/ci.yml",
    "AI_SKILLS_REVISION: 690a1dd939f8430af71b83a7ae01b35a694b4bc3",
    f"AI_SKILLS_REVISION: {AI_SKILLS_REVISION}",
)

AUTO_TAG = dedent(r'''
    name: Validate release request

    on:
      workflow_dispatch:
        inputs:
          release_ref:
            description: Existing v* tag or full 40-character commit SHA reachable from main
            required: true
            type: string

    permissions:
      contents: read

    concurrency:
      group: validate-release-request
      cancel-in-progress: false

    jobs:
      validate:
        runs-on: ubuntu-24.04
        timeout-minutes: 5
        steps:
          - name: Check out history read-only
            uses: actions/checkout@df4cb1c069e1874edd31b4311f1884172cec0e10 # v6
            with:
              fetch-depth: 0
              persist-credentials: false
          - name: Validate immutable release selection
            env:
              RELEASE_REF: ${{ inputs.release_ref }}
            run: |
              set -euo pipefail
              if [[ "$RELEASE_REF" =~ ^[0-9a-f]{40}$ ]]; then
                SHA="$RELEASE_REF"
              elif [[ "$RELEASE_REF" == v* ]]; then
                git show-ref --verify --quiet "refs/tags/$RELEASE_REF"
                SHA="$(git rev-parse "refs/tags/$RELEASE_REF^{commit}")"
              else
                echo "release_ref must be an existing v* tag or full SHA" >&2
                exit 1
              fi
              git merge-base --is-ancestor "$SHA" origin/main
              echo "Validated release candidate: $SHA"
          - name: Explain protected release flow
            run: |
              echo "This workflow never tags or publishes."
              echo "Run publish.yml only after exact-SHA CI and external acceptance evidence pass."
''')
write(".github/workflows/auto-tag.yml", AUTO_TAG)

PUBLISH = dedent(r'''
    name: Publish exact release image

    on:
      push:
        tags: ["v*"]
      workflow_dispatch:
        inputs:
          release_ref:
            description: Existing v* tag or full 40-character main-reachable commit SHA
            required: true
            type: string

    permissions:
      contents: read
      actions: read

    concurrency:
      group: release-${{ github.event_name == 'workflow_dispatch' && inputs.release_ref || github.ref }}
      cancel-in-progress: false

    jobs:
      validate:
        runs-on: ubuntu-24.04
        timeout-minutes: 25
        outputs:
          revision: ${{ steps.release.outputs.revision }}
          version: ${{ steps.release.outputs.version }}
          release_tag: ${{ steps.release.outputs.release_tag }}
          quarantine_ref: ${{ steps.quarantine.outputs.ref }}
          quarantine_digest: ${{ steps.quarantine.outputs.digest }}
        steps:
          - name: Check out source only in unprivileged validation job
            uses: actions/checkout@df4cb1c069e1874edd31b4311f1884172cec0e10 # v6
            with:
              persist-credentials: false
              fetch-depth: 0
          - name: Resolve immutable release identity
            id: release
            env:
              REQUESTED_REF: ${{ github.event_name == 'workflow_dispatch' && inputs.release_ref || github.ref }}
              EVENT_NAME: ${{ github.event_name }}
              EVENT_REF_NAME: ${{ github.ref_name }}
            run: |
              set -euo pipefail
              requested="$REQUESTED_REF"
              release_tag=""
              if [[ "$EVENT_NAME" == "push" ]]; then
                release_tag="$EVENT_REF_NAME"
                requested="refs/tags/$release_tag"
              fi
              if [[ "$requested" =~ ^[0-9a-f]{40}$ ]]; then
                revision="$requested"
              else
                case "$requested" in
                  refs/tags/v*) release_tag="${requested#refs/tags/}" ;;
                  v*) release_tag="$requested" ;;
                  *) echo "release_ref must be an existing v* tag or full SHA" >&2; exit 1 ;;
                esac
                git show-ref --verify --quiet "refs/tags/$release_tag"
                revision="$(git rev-parse "refs/tags/$release_tag^{commit}")"
              fi
              [[ "$revision" =~ ^[0-9a-f]{40}$ ]]
              git cat-file -e "$revision^{commit}"
              git merge-base --is-ancestor "$revision" origin/main
              git checkout --detach "$revision"
              test "$(git rev-parse HEAD)" = "$revision"
              version="$(python -c 'import tomllib; print(tomllib.load(open("pyproject.toml", "rb"))["project"]["version"])')"
              [[ "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]
              if [[ -n "$release_tag" ]]; then
                test "$release_tag" = "v$version"
                test "$(git rev-parse "refs/tags/$release_tag^{commit}")" = "$revision"
              fi
              echo "revision=$revision" >> "$GITHUB_OUTPUT"
              echo "version=$version" >> "$GITHUB_OUTPUT"
              echo "release_tag=$release_tag" >> "$GITHUB_OUTPUT"
          - name: Locate successful CI for exact revision
            id: ci
            env:
              GH_TOKEN: ${{ github.token }}
              REVISION: ${{ steps.release.outputs.revision }}
            run: |
              set -euo pipefail
              RUN_ID="$(gh run list --workflow CI --commit "$REVISION" --status success \
                --json databaseId,headSha --jq ".[] | select(.headSha == \"$REVISION\") | .databaseId" | head -n 1)"
              test -n "$RUN_ID" && test "$RUN_ID" != "null"
              echo "run_id=$RUN_ID" >> "$GITHUB_OUTPUT"
          - name: Download exact image from successful CI
            uses: actions/download-artifact@3e5f45b2cfb9172054b4087a40e8e0b5a5461e7c # v8.0.1
            with:
              name: image-${{ steps.release.outputs.revision }}
              run-id: ${{ steps.ci.outputs.run_id }}
              github-token: ${{ github.token }}
          - name: Verify and smoke-test exact CI image in unprivileged job
            env:
              REVISION: ${{ steps.release.outputs.revision }}
            run: |
              set -euo pipefail
              sha256sum --check image.tar.gz.sha256
              test "$(sed -n 's/^revision=//p' image-metadata.txt)" = "$REVISION"
              gzip -dc image.tar.gz | docker load
              docker image inspect "local-home-devices-mcp:$REVISION" >/dev/null
              docker run --rm \
                -e MCP_MOCK_MODE=1 -e MCP_TRANSPORT=stdio \
                -e ENABLE_WRITE_OPERATIONS=1 \
                "local-home-devices-mcp:$REVISION" --mock-self-test
          - name: Validate isolated quarantine registry configuration
            env:
              QUARANTINE_REGISTRY: ${{ vars.MCP_QUARANTINE_REGISTRY }}
              QUARANTINE_REPOSITORY: ${{ vars.MCP_QUARANTINE_REPOSITORY }}
            run: |
              set -euo pipefail
              test -n "$QUARANTINE_REGISTRY"
              test -n "$QUARANTINE_REPOSITORY"
              test "${QUARANTINE_REGISTRY,,}" != "ghcr.io"
          - name: Log in only to isolated quarantine registry
            uses: docker/login-action@650006c6eb7dba73a995cc03b0b2d7f5ca915bee # v4
            with:
              registry: ${{ vars.MCP_QUARANTINE_REGISTRY }}
              username: ${{ secrets.MCP_QUARANTINE_USERNAME }}
              password: ${{ secrets.MCP_QUARANTINE_TOKEN }}
          - name: Push and resolve exact quarantine digest
            id: quarantine
            env:
              QUARANTINE_REGISTRY: ${{ vars.MCP_QUARANTINE_REGISTRY }}
              QUARANTINE_REPOSITORY: ${{ vars.MCP_QUARANTINE_REPOSITORY }}
              REVISION: ${{ steps.release.outputs.revision }}
            run: |
              set -euo pipefail
              quarantine_ref="$QUARANTINE_REGISTRY/$QUARANTINE_REPOSITORY:sha-$REVISION"
              docker tag "local-home-devices-mcp:$REVISION" "$quarantine_ref"
              docker push "$quarantine_ref"
              digest="$(docker buildx imagetools inspect "$quarantine_ref" --format '{{.Manifest.Digest}}')"
              [[ "$digest" =~ ^sha256:[0-9a-f]{64}$ ]]
              echo "ref=$quarantine_ref" >> "$GITHUB_OUTPUT"
              echo "digest=$digest" >> "$GITHUB_OUTPUT"
          - name: Smoke-test exact quarantined registry digest
            env:
              QUARANTINE_REF: ${{ steps.quarantine.outputs.ref }}
              QUARANTINE_DIGEST: ${{ steps.quarantine.outputs.digest }}
            run: |
              set -euo pipefail
              source_ref="${QUARANTINE_REF%:*}@$QUARANTINE_DIGEST"
              docker pull "$source_ref"
              docker run --rm \
                -e MCP_MOCK_MODE=1 -e MCP_TRANSPORT=stdio \
                -e ENABLE_WRITE_OPERATIONS=1 \
                "$source_ref" --mock-self-test

      publish:
        needs: validate
        runs-on: ubuntu-24.04
        timeout-minutes: 15
        environment: release
        permissions:
          contents: read
          packages: write
          attestations: write
          id-token: write
        steps:
          - name: Set up registry-to-registry promotion tooling
            uses: docker/setup-buildx-action@d7f5e7f509e45cec5c76c4d5afdd7de93d0b3df5 # v3
          - name: Log in read-only to quarantine registry
            uses: docker/login-action@650006c6eb7dba73a995cc03b0b2d7f5ca915bee # v4
            with:
              registry: ${{ vars.MCP_QUARANTINE_REGISTRY }}
              username: ${{ secrets.MCP_QUARANTINE_READ_USERNAME }}
              password: ${{ secrets.MCP_QUARANTINE_READ_TOKEN }}
          - name: Log in to production GHCR
            uses: docker/login-action@650006c6eb7dba73a995cc03b0b2d7f5ca915bee # v4
            with:
              registry: ghcr.io
              username: ${{ github.actor }}
              password: ${{ secrets.GITHUB_TOKEN }}
          - name: Promote exact tested digest without checkout, load, build, or execution
            id: promote
            env:
              QUARANTINE_REF: ${{ needs.validate.outputs.quarantine_ref }}
              EXPECTED_DIGEST: ${{ needs.validate.outputs.quarantine_digest }}
              REVISION: ${{ needs.validate.outputs.revision }}
              VERSION: ${{ needs.validate.outputs.version }}
              RELEASE_TAG: ${{ needs.validate.outputs.release_tag }}
            run: |
              set -euo pipefail
              [[ "$EXPECTED_DIGEST" =~ ^sha256:[0-9a-f]{64}$ ]]
              repository="ghcr.io/${GITHUB_REPOSITORY,,}"
              source_ref="${QUARANTINE_REF%:*}@$EXPECTED_DIGEST"
              immutable_ref="$repository:sha-$REVISION"
              docker buildx imagetools create --tag "$immutable_ref" "$source_ref"
              test "$(docker buildx imagetools inspect "$immutable_ref" --format '{{.Manifest.Digest}}')" = "$EXPECTED_DIGEST"
              if [[ -n "$RELEASE_TAG" ]]; then
                version_ref="$repository:$VERSION"
                latest_ref="$repository:latest"
                docker buildx imagetools create --tag "$version_ref" "$source_ref"
                docker buildx imagetools create --tag "$latest_ref" "$source_ref"
                test "$(docker buildx imagetools inspect "$version_ref" --format '{{.Manifest.Digest}}')" = "$EXPECTED_DIGEST"
                test "$(docker buildx imagetools inspect "$latest_ref" --format '{{.Manifest.Digest}}')" = "$EXPECTED_DIGEST"
              fi
              echo "subject_name=$repository" >> "$GITHUB_OUTPUT"
              echo "digest=$EXPECTED_DIGEST" >> "$GITHUB_OUTPUT"
          - name: Attest promoted immutable image
            uses: actions/attest-build-provenance@96b4a1ef7235a096b17240c259729fdd70c83d45 # v3
            with:
              subject-name: ${{ steps.promote.outputs.subject_name }}
              subject-digest: ${{ steps.promote.outputs.digest }}
              push-to-registry: true
''')
write(".github/workflows/publish.yml", PUBLISH)

# ---------------------------------------------------------------------------
# Operator configuration and documentation: no stale exact-SHA self-claims.
# ---------------------------------------------------------------------------
ENV_EXAMPLE = dedent(r'''
    # Supported transports: stdio or http. Legacy SSE/REST are removed.
    MCP_TRANSPORT=http
    BIND_HOST=127.0.0.1
    MCP_PORT=9102
    MCP_PATH=/mcp

    # Capability gates. Writes and dangerous operations are disabled by default.
    ENABLE_WRITE_OPERATIONS=0
    ENABLE_DANGEROUS_OPERATIONS=0
    MCP_ALLOW_DIRECT_IP_TARGETS=0
    MCP_ALLOWED_TARGET_NETWORKS=192.168.0.0/16

    # Development/test static HTTP principals. Production should use JWT/JWKS.
    MCP_AUTH_READ_TOKEN=
    MCP_AUTH_SENSITIVE_TOKEN=
    MCP_AUTH_WRITE_TOKEN=
    MCP_AUTH_DANGEROUS_TOKEN=
    MCP_AUTH_ADMIN_TOKEN=
    MCP_HTTP_DEVELOPMENT_MODE=0

    # Production JWT/JWKS identity provider.
    MCP_AUTH_JWT_JWKS_URI=
    MCP_AUTH_JWT_ISSUER=
    MCP_AUTH_JWT_AUDIENCE=

    # Remote HTTP boundary. Non-loopback deployment requires trusted TLS termination.
    MCP_TRUSTED_PROXY_TLS=0
    MCP_ALLOWED_HOSTS=127.0.0.1,localhost
    MCP_ALLOWED_ORIGINS=
    MCP_HTTP_MAX_BODY_BYTES=1048576
    MCP_HTTP_MAX_HEADER_BYTES=32768
    MCP_HTTP_MAX_CONNECTIONS=64
    MCP_HTTP_QUEUE_LIMIT=32
    MCP_HTTP_QUEUE_WAIT_MS=1000
    MCP_HTTP_INGRESS_TIMEOUT_MS=5000
    MCP_MAX_RESPONSE_BYTES=1048576

    MCP_ARTIFACT_ROOT=data/artifacts
    MCP_MAX_ARTIFACT_BYTES=8388608
    MCP_MAX_ARTIFACT_STORE_BYTES=134217728
    MCP_ARTIFACT_RETENTION_SECONDS=86400
    MCP_MOCK_MODE=0

    # Legacy backend adapter settings. These are snapshotted when adapters import.
    START_IP=192.168.1.1
    END_IP=192.168.1.254
    NETWORK_RANGE=192.168.1.0/24
    MQTT_BROKER=192.168.1.100
    MQTT_PORT=1883
    MQTT_USER=
    MQTT_PASSWORD=
    OPENHASP_DEFAULT_HOST=192.168.1.100
    OPENHASP_HTTP_PORT=80
    OPENHASP_TELNET_PORT=23
    OPENHASP_TIMEOUT=10
    OPENHASP_TELNET_TIMEOUT=5
    HIKVISION_DOORBELL_HOST=192.168.1.101
    HIKVISION_DOORBELL_USER=
    HIKVISION_DOORBELL_PASSWORD=
    HIKVISION_CONTAINER_NAME=hikvision-doorbell
    DOCKER_SOCKET=/var/run/docker.sock
    CAMERA_GATE_SNAPSHOTS_DIR=/config/www/archive/camera_gate
    TUYA_ACCESS_ID=
    TUYA_ACCESS_SECRET=
    TUYA_PROJECT_CODE=
    TUYA_DEVICES_FILE=data/tuya_devices.json
    IOT_DATA_PATH=data
''')
write(".env.example", ENV_EXAMPLE)

README = dedent(r'''
    ---
    description: Operate and develop the policy-governed MCP server for local home devices.
    doc_id: guide.repository-readme
    type: guide
    status: evolving
    rigor: operational
    owners: [repository-maintainers]
    verification: Run the virtual-environment tests, real transport probes, exact-artifact workflow, and separately authorized real-system checks described below.
    ---

    # Local Home Devices MCP

    Version 2.0.0 is a fail-closed compatibility migration. It removes the legacy SSE/REST execution surfaces and changes public response, target-selection, and retry semantics, so the change is intentionally a major version.

    The branch is an implementation candidate, not an approved ai-skills maturity claim. Candidate-local CI is diagnostic; final adoption requires immutable external verifier evidence and an independent review bound to the exact accepted SHA.

    ## Safe defaults

    - HTTP binds to `127.0.0.1` by default and still requires an authenticated principal.
    - Development static tokens require `MCP_HTTP_DEVELOPMENT_MODE=1`; production remote HTTP uses JWT/JWKS and trusted TLS termination.
    - Writes and dangerous capabilities are disabled by default.
    - Target-bearing calls authorize selector namespace, resolve one stable target, authorize its target ID, serialize by that ID, and revalidate identity immediately before I/O.
    - Public errors are JSON machine-readable MCP tool errors with stable `code`, `retryable`, and `unknown_outcome` fields.
    - Read timeouts are `DEADLINE_EXCEEDED`; only a mutation whose execution actually started can return `UNKNOWN_OUTCOME`.
    - Unmigrated writes, Docker-socket access, unrestricted paths, OTA, raw commands, and OpenHASP writes remain inactive.

    ## Local development

    ```bash
    python -m venv .venv
    . .venv/bin/activate
    python -m pip install -e '.[dev]'
    MCP_MOCK_MODE=1 ENABLE_WRITE_OPERATIONS=1 python server.py --mock-self-test
    python -m pytest -m 'not real_system'
    ```

    Transport tests spawn real stdio and Streamable HTTP endpoints and use the official MCP client. In-memory `Client(mcp)` calls are not transport evidence.

    ## Running

    Trusted local stdio:

    ```bash
    MCP_TRANSPORT=stdio local-home-devices-mcp
    ```

    Authenticated loopback HTTP for development:

    ```bash
    MCP_TRANSPORT=http \
    BIND_HOST=127.0.0.1 \
    MCP_HTTP_DEVELOPMENT_MODE=1 \
    MCP_AUTH_READ_TOKEN='replace-with-at-least-32-random-characters' \
    local-home-devices-mcp
    ```

    A non-loopback bind requires JWT/JWKS authentication plus `MCP_TRUSTED_PROXY_TLS=1` behind a verified TLS-terminating proxy. See [Security model](docs/security-model.md).

    `/ready` validates registered components plus the target registry and artifact-store dependency state. A green registration count alone is not readiness.

    ## Capability status

    Capability discovery distinguishes supported and active operations. Disabled operations are not invokable. See [Capability contract](docs/capability-contract.md) and [Migration plan](docs/migration-plan.md).

    ## Release integrity

    CI builds and probes the exact wheel and image. The protected release flow then takes that exact successful-CI image in an unprivileged validation job, pushes it to a separately credentialed quarantine registry, resolves and smoke-tests the registry digest, and passes only that digest to the protected publisher. The publisher performs registry-to-registry promotion and never checks out, loads, builds, or executes candidate source/image bytes.

    Configure a quarantine registry on a domain distinct from `ghcr.io` with repository variables `MCP_QUARANTINE_REGISTRY` and `MCP_QUARANTINE_REPOSITORY`, plus scoped write credentials `MCP_QUARANTINE_USERNAME` / `MCP_QUARANTINE_TOKEN` and read-only credentials `MCP_QUARANTINE_READ_USERNAME` / `MCP_QUARANTINE_READ_TOKEN`. Production publication remains protected by the `release` environment.

    ## Acceptance boundary

    Repository CI pins ai-skills revision `b54fc6b27ea80b36a70d5de73445970e17f55789` for deterministic diagnostics. Because the assessed branch controls its own workflow file and pin, that run is not independent approval authority. Final adoption evidence must be produced by a separately governed immutable verifier and independent reviewer for the exact final SHA.
''')
write("README.md", README)

ADOPTION = dedent(r'''
    ---
    description: State which ai-skills compliance claims are implemented, verified, or still pending.
    doc_id: reference.ai-skills-adoption-status
    type: reference
    status: evolving
    rigor: operational
    owners: [repository-maintainers]
    verification: Run candidate-local diagnostics, then bind external provider evidence and an independent review to the exact immutable candidate SHA.
    ---

    # AI skills adoption status

    ## Answer

    This branch is a candidate adoption of `mcp-server-architect` 1.2.0 from ai-skills revision `b54fc6b27ea80b36a70d5de73445970e17f55789`. The application package is 2.0.0 because the migration removes transports and changes public target-selection, response, and retry semantics.

    It does **not** claim an approved maturity level. The repository-controlled CI workflow is useful diagnostic evidence but cannot approve the same candidate tree that controls the verifier pin and workflow definition.

    ## Implemented controls

    - One FastMCP composition root and one application-owned invocation kernel.
    - Capability and selector authorization before network-backed target resolution, followed by exact stable-target authorization and pre-I/O identity revalidation.
    - Official stdio and Streamable HTTP only.
    - Conservative canonical manifests; unclassified legacy capabilities fail closed.
    - Bounded HTTP admission, queue wait, ingress read, body size, header size, connection count, and response capture.
    - Bounded principal rate-limiter state.
    - Stable machine-readable public error codes with mutation-only unknown-outcome semantics.
    - Principal-owned artifacts with confined paths, integrity, retention, quota, and governed resource access.
    - Exact wheel/image CI plus quarantine-digest release promotion with no candidate execution in the protected publisher.

    ## Candidate-local verification

    Run:

    ```bash
    MCP_MOCK_MODE=1 ENABLE_WRITE_OPERATIONS=1 python server.py --mock-self-test
    python -m pytest -m 'not real_system'
    ```

    Hosted CI additionally executes Ruff, mypy, Bandit, capability-manifest validation, AFDS/AGENTS/workflow policy checks, exact-wheel installation, official-client stdio/HTTP probes, and the exact container artifact. Every source change invalidates previous exact-SHA CI evidence.

    ## Pending acceptance evidence

    Final approval requires all of the following to reference one immutable candidate SHA:

    - a schema-valid provider-backed migration/adoption assessment;
    - exact workflow/run and wheel/image identities;
    - acceptance validation from an immutable verifier outside the assessed candidate tree;
    - an independent reviewer who did not author the candidate or its evidence;
    - authorized real-system evidence for the physical-device cases listed in `tests/real_system_todos.py`.

    Release quarantine credentials and registry isolation are deployment-owner configuration and must be exercised before the first production 2.0.0 promotion.

    ## Failure and recovery

    Keep unsafe adapters inactive when any required evidence is missing. Do not weaken the assessment, restore the removed REST/SSE bridges, interpret an unassigned runner as success, or manufacture placeholder reviewer/run/digest identities.
''')
write("docs/adoption-status.md", ADOPTION)

SECURITY = dedent(r'''
    ---
    description: Define authentication, target authorization, artifacts, and privileged-operation boundaries.
    doc_id: reference.security-model
    type: reference
    status: evolving
    rigor: operational
    owners: [repository-maintainers]
    verification: Run policy, target-binding, artifact, HTTP-boundary, auth, and real-transport tests for the assessed revision.
    ---

    # Security model

    ## Trust boundary

    The MCP composition root owns authentication and the invocation gate. Legacy adapters do not approve callers, choose fallback targets, or weaken operator policy. Public calls carry the immutable `Settings` snapshot in invocation context; the legacy module-level write flag is a compatibility fallback only for direct adapter tests/scripts outside the governed path.

    ## HTTP authentication

    All HTTP, including loopback HTTP, requires a configured identity provider. Static tokens are development/test-only and require `MCP_HTTP_DEVELOPMENT_MODE=1` (or mock mode). Production uses JWT/JWKS. A non-loopback bind additionally requires `MCP_TRUSTED_PROXY_TLS=1`; this acknowledges a separately verified TLS-terminating trusted proxy and does not create TLS itself.

    Static development roles are separated into read, sensitive-read, write, dangerous, and admin tokens. Scope checks and stable-target ACLs remain server-side. Malformed scope/target claims fail closed.

    ## HTTP resource boundary

    Host and Origin policy run before dispatch. Connection admission occurs before request-body buffering. Queue wait and ingress-body read have explicit time limits; body/header sizes and concurrent connections are bounded. Stateless JSON responses are retained only up to the effective capability wire limit, so an oversized response cannot force unbounded response-memory accumulation.

    ## Target authorization

    For target-bearing tools the order is selector normalization, capability/selector authorization, exact resolution within the authorized namespace, stable-target authorization, target-keyed concurrency admission, identity/address revalidation, then replacement of the model selector with the authorized address immediately before the legacy adapter call. Partial matching and silent fallback are prohibited.

    ## Blocking adapters and ambiguous outcomes

    Synchronous legacy adapters run in a bounded AnyIO worker pool. Cancellation retains concurrency ownership until physical work stops. A timeout before mutation execution starts is `DEADLINE_EXCEEDED`; a timeout after mutation execution starts is `UNKNOWN_OUTCOME` and requires reconciliation before retry. Read operations never report mutation-unknown wording.

    ## Artifacts

    Artifact roots reject existing symlink components. Artifacts use opaque 128-bit IDs, server-owned paths, exclusive no-follow data creation where supported, restrictive modes, quotas, expiry, integrity hashes, and owner checks. Readiness includes artifact-store accessibility.

    ## Privileged operations

    Docker socket access, caller-selected paths, firmware update, raw commands, factory reset, direct DPS mutation, and unbound OpenHASP writes remain inactive until separately reviewed. Docker operations require a least-privileged sidecar; the MCP container must not mount `docker.sock`.
''')
write("docs/security-model.md", SECURITY)

ARCH = dedent(r'''
    ---
    description: Describe the composition root, invocation pipeline, adapters, target registry, and artifacts.
    doc_id: reference.system-architecture
    type: reference
    status: evolving
    rigor: operational
    owners: [repository-maintainers]
    verification: Run unit, adapter integration, real stdio, real Streamable HTTP, wheel, container, and dependency-readiness probes.
    ---

    # System architecture

    `server.py` loads immutable `Settings` and delegates to `local_home_devices_mcp.composition`. The composition root creates FastMCP, authentication, the target resolver, `OperationGate`, artifact storage, adapters, and supported transports.

    For every tool call, middleware authenticates the principal, authorizes capability and selector namespace, resolves and authorizes a stable target when applicable, applies a bounded principal rate limiter and absolute deadline, acquires concurrency ownership, revalidates identity, invokes the adapter, enforces the final response limit, and maps failures to stable machine-readable MCP error codes.

    The HTTP boundary is separate from capability policy. It bounds connections, queue depth, queue wait, ingress read time, headers, body size, Host/Origin policy, and final buffered JSON response bytes before handing the request to FastMCP.

    `LegacyRegistrationProxy` is a migration boundary. It replaces model selectors with the authorized address, wraps blocking calls in a bounded worker pool, retains ownership until cancelled physical work ends, and normalizes legacy envelopes. Global compatibility patches obtain Settings from the current invocation context so public calls are not bound to whichever server instance installed a patch first.

    `/ready` checks component registration plus target-registry and artifact-store dependency state. Registration count alone is not considered readiness.

    Candidate-local CI is not approval authority for itself. Final adoption/release acceptance is bound outside the assessed tree to one immutable SHA and exact artifact identities.
''')
write("docs/system-architecture.md", ARCH)

CAPABILITY = dedent(r'''
    ---
    description: Define capability manifests, active-state rules, errors, targets, and retries.
    doc_id: reference.capability-contract
    type: reference
    status: evolving
    rigor: operational
    owners: [repository-maintainers]
    verification: Enumerate registered and active components and run positive plus negative tests for every reactivated capability.
    ---

    # Capability contract

    Every public component has an application-owned canonical manifest. The repository also preserves reviewed legacy semantic metadata under canonical extensions while ai-skills' machine schema and richer normative manifest reference remain separate representations.

    Positive semantic claims are operation-specific. Legacy factories are not evidence. Multi-backend mutations stay inactive until backend-specific contracts prove explicit state transitions, invalid-response handling, timeout/disconnect ambiguity, read-back/reconciliation, and overlap behavior.

    Public failures cross MCP as JSON error text with stable fields: `code`, `message`, `retryable`, and `unknown_outcome`. Callers must branch on `code`, not parse prose. `DEADLINE_EXCEEDED` means execution did not establish an ambiguous mutation; `UNKNOWN_OUTCOME` is reserved for a mutation whose execution started before the deadline/cancellation outcome became unknowable.

    Inactive tools are disabled through the public FastMCP visibility API so discovery and invocation agree. Changing `active_state` alone is insufficient: target binding, dependency readiness, positive/negative tests, timeout behavior, and operation-specific evidence are required before reactivation.
''')
write("docs/capability-contract.md", CAPABILITY)

MIGRATION = dedent(r'''
    ---
    description: Track completed vertical slices, deferred operations, evidence, and rollback.
    doc_id: workflow.ai-skills-compliance-migration
    type: workflow
    status: evolving
    rigor: operational
    owners: [repository-maintainers]
    verification: Run candidate CI for the exact revision, inspect immutable artifact identities, and complete separately authorized real-system and external-acceptance checks.
    ---

    # AI skills compliance migration plan

    ## Completed in the implementation candidate

    - major-version 2.0 contract for removed transports and changed target/retry/response semantics;
    - official stdio and stateless JSON Streamable HTTP only;
    - exact target authorization and pre-I/O revalidation;
    - bounded principal rate-limit registry and target/resource concurrency;
    - bounded HTTP admission, queue wait, ingress, headers, body, and response capture;
    - stable machine-readable public error taxonomy and mutation-only unknown outcomes;
    - cancellation-safe supervision for blocking legacy workers;
    - principal-owned artifact resource with symlink-root policy, quota, expiry, and integrity;
    - dependency-aware readiness;
    - exact wheel/image CI and isolated-quarantine digest promotion design;
    - ai-skills candidate diagnostic pin updated to `b54fc6b27ea80b36a70d5de73445970e17f55789`.

    ## Deferred / requires external or physical evidence

    - provider-backed adoption assessment and independent review from authority outside the candidate tree;
    - first real execution of the isolated quarantine registry release path with scoped credentials;
    - real-device DHCP identity-change, disconnect/reconciliation, Hikvision relay, and backend compensation checks;
    - backend-specific migration/evidence for additional mutations and OpenHASP;
    - production identity-provider deployment evidence;
    - least-privileged Docker sidecar;
    - read-only discovery separated from registry persistence.

    Previous 1.7-era real-device observations do not automatically transfer to 2.0.0 after runtime-boundary changes. Re-run the cases in `tests/real_system_todos.py` on the exact final artifact.

    ## Rollback

    Stop promotion if transport lifecycle, target revalidation, dependency readiness, exact wheel/image probes, quarantine digest verification, or external acceptance fails. Roll back to the previous immutable production digest with writes disabled. Do not restore legacy REST or SSE execution bridges.
''')
write("docs/migration-plan.md", MIGRATION)

# Replace only the unreleased/current top changelog section; preserve historical releases.
CHANGELOG_2 = dedent(r'''
    ## [2.0.0] — 2026-08-09

    ### Breaking
    - Removed legacy SSE and custom REST/JSON-RPC execution surfaces; supported transports are stdio and Streamable HTTP.
    - Public legacy JSON-string success/error semantics are replaced by typed data and MCP tool errors.
    - Target selection is exact and authorization-bound with no silent fallback; retry/timeout behavior is now fail-closed with explicit unknown outcomes. These semantic changes require a major version.

    ### Added
    - Application-owned policy kernel with stable target authorization/revalidation, bounded concurrency, principal ACLs, governed artifacts, and dependency-aware readiness.
    - Bounded HTTP connection admission, queue wait, ingress read, headers/body limits, Host/Origin checks, and bounded final response capture.
    - Stable public error codes with `retryable` and `unknown_outcome` fields.
    - Isolated-quarantine registry release flow that promotes only a smoke-tested registry digest in the protected publisher.

    ### Fixed
    - Rate-limiter principal registry now has bounded cardinality and expiry cleanup.
    - Public MCP calls use the invocation's immutable Settings for the legacy write guard and safety target wrappers rather than stale first-import/first-install server state.
    - Release publishing no longer loads or executes candidate image bytes in the privileged job.
    - Repository diagnostic validation is pinned to ai-skills revision `b54fc6b27ea80b36a70d5de73445970e17f55789`.

    ### Verification status
    - Candidate-local quality, tests, exact wheel, and container CI must pass on the final 2.0.0 SHA after these changes.
    - Previous real-device observations were made on an earlier candidate and are not acceptance evidence for the new SHA. Re-run `tests/real_system_todos.py` on the final deployed image.
    - Provider-backed external acceptance and independent review remain required before claiming ai-skills adoption approval.

''')
content = read("CHANGELOG.md")
updated, count = re.subn(
    r"## \[1\.7\.0\] — 2026-08-09\n.*?(?=## \[1\.6\.0\])",
    CHANGELOG_2,
    content,
    count=1,
    flags=re.DOTALL,
)
if count != 1:
    raise RuntimeError("CHANGELOG.md: could not replace 1.7.0 section")
write("CHANGELOG.md", updated)

# ---------------------------------------------------------------------------
# Tests for the hardening changes
# ---------------------------------------------------------------------------
replace_once(
    "tests/unit/test_http_boundary.py",
    "from __future__ import annotations\n\nfrom dataclasses import replace\n",
    "from __future__ import annotations\n\nimport asyncio\nfrom dataclasses import replace\n",
)
write(
    "tests/unit/test_http_boundary.py",
    read("tests/unit/test_http_boundary.py")
    + dedent(r'''

        @pytest.mark.asyncio
        async def test_queue_wait_is_bounded() -> None:
            started = asyncio.Event()
            release = asyncio.Event()

            async def app(scope, receive, send):
                await receive()
                started.set()
                await release.wait()
                await send({"type": "http.response.start", "status": 200, "headers": []})
                await send({"type": "http.response.body", "body": b"ok", "more_body": False})

            middleware = HttpBoundaryMiddleware(
                app,
                _settings(http_max_connections=1, http_queue_limit=1, http_queue_wait_ms=10),
            )
            first = asyncio.create_task(
                _invoke(middleware, headers=[(b"host", b"127.0.0.1")], body=b"{}")
            )
            await started.wait()
            second = await _invoke(
                middleware,
                headers=[(b"host", b"127.0.0.1")],
                body=b"{}",
            )
            assert _status(second) == 503
            release.set()
            assert _status(await first) == 200


        @pytest.mark.asyncio
        async def test_ingress_body_read_has_deadline() -> None:
            sent: list[dict[str, Any]] = []

            async def app(scope, receive, send):
                raise AssertionError("app must not run after ingress timeout")

            async def receive() -> dict[str, Any]:
                await asyncio.sleep(0.05)
                return {"type": "http.request", "body": b"{}", "more_body": False}

            async def send(message: dict[str, Any]) -> None:
                sent.append(message)

            middleware = HttpBoundaryMiddleware(app, _settings(http_ingress_timeout_ms=10))
            await middleware(
                {"type": "http", "method": "POST", "path": "/mcp", "headers": [(b"host", b"127.0.0.1")]},
                receive,
                send,
            )
            assert _status(sent) == 408
    '''),
)

replace_once(
    "tests/unit/test_policy.py",
    '''from local_home_devices_mcp.policy import (\n    OperationGate,\n''',
    '''from local_home_devices_mcp.policy import (\n    AsyncSlidingWindowLimiter,\n    OperationGate,\n''',
)
write(
    "tests/unit/test_policy.py",
    read("tests/unit/test_policy.py")
    + dedent(r'''

        @pytest.mark.asyncio
        async def test_rate_limiter_principal_registry_is_bounded_and_expires() -> None:
            limiter = AsyncSlidingWindowLimiter(limit=2, window_seconds=1.0, max_principals=2)
            await limiter.check("alice", now=0.0)
            await limiter.check("bob", now=0.0)
            assert limiter.entry_count == 2
            with pytest.raises(RateLimitExceeded, match="capacity"):
                await limiter.check("charlie", now=0.1)
            await limiter.check("charlie", now=2.0)
            assert limiter.entry_count == 1
    '''),
)

replace_once(
    "tests/compliance/test_composition_runtime.py",
    "from __future__ import annotations\n\nimport ipaddress\n",
    "from __future__ import annotations\n\nimport asyncio\nimport ipaddress\n",
)
regex_once(
    "tests/compliance/test_composition_runtime.py",
    r'''@pytest\.mark\.asyncio\nasync def test_capability_response_limit_is_enforced_at_mcp_boundary\(.*?\n\n\n@pytest\.mark\.asyncio\nasync def test_artifact_resource_rejects_read_scope''',
    '''@pytest.mark.asyncio\nasync def test_capability_response_limit_is_enforced_at_mcp_boundary(\n    tmp_path: Path, fake_fastmcp: dict[str, Any]\n) -> None:\n    from local_home_devices_mcp.composition import build_server\n\n    build_server(settings(tmp_path))\n    mcp = FakeFastMCP.last\n    assert mcp is not None\n    context = SimpleNamespace(\n        message=SimpleNamespace(name="mock_get_state", arguments={"identifier": "dev_mock_light"})\n    )\n\n    async def call_next(_context: Any) -> dict[str, str]:\n        return {"value": "x" * (40 * 1024)}\n\n    invocation = mcp.middlewares[1]\n    with pytest.raises(FakeToolError) as caught:\n        await invocation.on_call_tool(context, call_next)\n    payload = json.loads(str(caught.value))\n    assert payload["code"] == "RESPONSE_TOO_LARGE"\n    assert payload["retryable"] is False\n    assert payload["unknown_outcome"] is False\n\n\n@pytest.mark.asyncio\nasync def test_artifact_resource_rejects_read_scope''',
)
write(
    "tests/compliance/test_composition_runtime.py",
    read("tests/compliance/test_composition_runtime.py")
    + dedent(r'''

        @pytest.mark.asyncio
        async def test_mutation_timeout_is_machine_readable_unknown_outcome(
            tmp_path: Path, fake_fastmcp: dict[str, Any]
        ) -> None:
            from local_home_devices_mcp.composition import build_server

            _server, gate = build_server(settings(tmp_path))
            mcp = FakeFastMCP.last
            assert mcp is not None
            gate.catalog["mock_set_power"]["extensions"]["timeout_ms"] = 10
            context = SimpleNamespace(
                message=SimpleNamespace(
                    name="mock_set_power",
                    arguments={"identifier": "dev_mock_light", "power": True},
                )
            )

            async def call_next(_context: Any) -> dict[str, bool]:
                await asyncio.sleep(0.05)
                return {"power": True}

            with pytest.raises(FakeToolError) as caught:
                await mcp.middlewares[1].on_call_tool(context, call_next)
            payload = json.loads(str(caught.value))
            assert payload["code"] == "UNKNOWN_OUTCOME"
            assert payload["unknown_outcome"] is True
            assert payload["retryable"] is False


        @pytest.mark.asyncio
        async def test_readiness_fails_when_mandatory_dependency_is_unavailable(
            tmp_path: Path, fake_fastmcp: dict[str, Any]
        ) -> None:
            from local_home_devices_mcp.composition import build_server

            _server, gate = build_server(settings(tmp_path))
            mcp = FakeFastMCP.last
            assert mcp is not None

            async def unavailable() -> dict[str, Any]:
                return {"status": "unavailable", "reason": "test", "valid_targets": 0}

            assert gate.target_resolver is not None
            gate.target_resolver.readiness = unavailable  # type: ignore[method-assign]
            response = await mcp.routes["/ready"](None)
            payload = json.loads(response.body)
            assert response.status_code == 503
            assert payload["status"] == "not-ready"
            assert payload["dependencies"]["target_registry"]["status"] == "unavailable"
    '''),
)

write(
    "tests/unit/test_artifacts.py",
    read("tests/unit/test_artifacts.py")
    + dedent(r'''

        def test_store_rejects_symlink_root_component(tmp_path: Path) -> None:
            real = tmp_path / "real-artifacts"
            real.mkdir()
            linked = tmp_path / "linked-artifacts"
            linked.symlink_to(real, target_is_directory=True)
            with pytest.raises(ArtifactError, match="symlink component"):
                ArtifactStore(
                    linked,
                    max_artifact_bytes=100,
                    max_store_bytes=200,
                    retention_seconds=3600,
                )


        def test_store_readiness_reports_accessible_root(tmp_path: Path) -> None:
            assert _store(tmp_path).readiness()["status"] == "ready"
    '''),
)

write(
    "tests/unit/test_config.py",
    read("tests/unit/test_config.py")
    + dedent(r'''

        def test_http_queue_and_ingress_deadlines_are_configurable(monkeypatch: pytest.MonkeyPatch):
            _clear_mcp_env(monkeypatch)
            monkeypatch.setenv("MCP_HTTP_QUEUE_WAIT_MS", "250")
            monkeypatch.setenv("MCP_HTTP_INGRESS_TIMEOUT_MS", "1500")
            config = load_settings()
            assert config.http_queue_wait_ms == 250
            assert config.http_ingress_timeout_ms == 1500
    '''),
)

RELEASE_TEST = dedent(r'''
    from __future__ import annotations

    import tomllib
    from pathlib import Path

    import pytest

    from scripts.lock_wheelhouse import lock_lines

    pytestmark = pytest.mark.unit

    ROOT = Path(__file__).resolve().parents[2]


    def test_hash_lock_is_generated_from_pip_report() -> None:
        report = {
            "install": [
                {
                    "metadata": {"name": "local-home-devices-mcp", "version": "2.0.0"},
                    "download_info": {"archive_info": {"hashes": {"sha256": "a" * 64}}},
                },
                {
                    "metadata": {"name": "AnyIO", "version": "4.14.2"},
                    "download_info": {"archive_info": {"hashes": {"sha256": "b" * 64}}},
                },
            ]
        }
        assert lock_lines(report) == [f"AnyIO==4.14.2 --hash=sha256:{'b' * 64}"]


    def test_hash_lock_rejects_unverifiable_dependency() -> None:
        report = {
            "install": [
                {
                    "metadata": {"name": "AnyIO", "version": "4.14.2"},
                    "download_info": {"archive_info": {}},
                }
            ]
        }
        with pytest.raises(ValueError, match="no SHA-256"):
            lock_lines(report)


    def test_container_installs_only_from_hash_locked_wheelhouse() -> None:
        dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
        assert "--no-index" in dockerfile
        assert "--find-links=/tmp/wheelhouse" in dockerfile
        assert "--require-hashes" in dockerfile
        assert "--no-deps /tmp/package/*.whl" in dockerfile

        workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
        assert "scripts/lock_wheelhouse.py" in workflow
        assert "pip download --require-hashes" in workflow
        assert "wheelhouse/" in workflow


    def test_major_version_matches_breaking_contract() -> None:
        project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        assert project["project"]["version"] == "2.0.0"


    def test_release_uses_quarantine_digest_and_non_executing_publisher() -> None:
        workflow = (ROOT / ".github/workflows/publish.yml").read_text(encoding="utf-8")
        validate, publisher = workflow.split("\n  publish:\n", 1)
        assert "environment: release" in publisher
        assert "MCP_QUARANTINE_REGISTRY" in validate
        assert "test \"${QUARANTINE_REGISTRY,,}\" != \"ghcr.io\"" in validate
        assert "docker load" in validate
        assert "Smoke-test exact quarantined registry digest" in validate
        assert "docker buildx imagetools create" in publisher
        assert "docker load" not in publisher
        assert "docker run" not in publisher
        assert "actions/checkout" not in publisher
        assert "docker build " not in publisher
''')
write("tests/compliance/test_release_and_image_contract.py", RELEASE_TEST)

write(
    "tests/unit/test_server_contract.py",
    read("tests/unit/test_server_contract.py")
    + dedent(f'''

        def test_major_version_and_ai_skills_diagnostic_pin():
            project = Path("pyproject.toml").read_text(encoding="utf-8")
            workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
            assert 'version = "2.0.0"' in project
            assert "AI_SKILLS_REVISION: {AI_SKILLS_REVISION}" in workflow
    '''),
)

REAL_TODOS = dedent(r'''
    """Physical-system verification that must be rerun on the exact final 2.0.0 artifact.

    TODO(real-system-agent): Deploy the exact CI-produced 2.0.0 image by immutable digest and
    rerun official-client list/info/wifi/power reads against representative OpenBK, Tasmota,
    Tuya, OpenHASP, and Hikvision devices. Record exact image digest, device classes, and results.

    TODO(real-system-agent): Verify `/ready` transitions on the real deployment when the device
    registry is valid, deliberately unavailable/empty, and restored. Confirm orchestration does
    not report `ready` while mandatory target-registry access is unavailable.

    TODO(real-system-agent): Verify target identity revalidation against a device whose DHCP
    address changes between authorization and I/O. The authorized stable identity must not move
    silently to another address/device.

    TODO(real-system-agent): Verify OTA expected-disconnect and unknown-outcome reconciliation
    using signed firmware hosted on an operator allowlisted origin. Do not auto-retry ambiguous
    mutation outcomes.

    TODO(real-system-agent): Verify Hikvision gate authorization with a physical relay and prove
    that an ambiguous timeout is never retried automatically.

    TODO(real-system-agent): Verify machine-readable HTTP/stdio error codes on real failure paths,
    especially DEADLINE_EXCEEDED versus UNKNOWN_OUTCOME, target disappearance, and authorization.

    TODO(real-system-agent): Verify Docker sidecar confinement once the privileged adapter is split
    from the MCP process; the MCP container must not mount docker.sock directly.

    TODO(release-owner): Configure an isolated quarantine registry on a domain other than ghcr.io,
    with scoped write and separate read-only credentials, then execute a disposable 2.0.0 release
    rehearsal proving quarantine digest == promoted GHCR digest and that the protected publisher
    never checks out, loads, builds, or executes the candidate image/source.

    TODO(acceptance-owner): Produce provider-backed adoption evidence with an immutable verifier
    outside the assessed tree and obtain an independent review bound to the same exact final SHA.
    """
''')
write("tests/real_system_todos.py", REAL_TODOS)

# Ensure the script itself did not accidentally leave stale current-version claims in key files.
for key_file in (
    "pyproject.toml",
    "tools/__init__.py",
    "tools/constants.py",
    "README.md",
    "docs/adoption-status.md",
    "docs/migration-plan.md",
):
    if "1.7.0" in read(key_file):
        raise RuntimeError(f"{key_file}: stale 1.7.0 current-version claim remains")

print("compliance hardening edits applied")
