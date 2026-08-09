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
