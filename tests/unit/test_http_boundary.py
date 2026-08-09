from __future__ import annotations

import asyncio
from dataclasses import replace
from typing import Any

import pytest

from local_home_devices_mcp.config import Settings
from local_home_devices_mcp.http_boundary import (
    HttpBoundaryMiddleware,
    set_wire_response_limit,
)


def _settings(**overrides: Any) -> Settings:
    return replace(
        Settings.for_mock(),
        transport="http",
        read_token="r" * 32,
        http_development_mode=True,
        allowed_hosts=("127.0.0.1", "localhost"),
        allowed_origins=("https://client.example",),
        http_max_body_bytes=16,
        http_max_header_bytes=256,
        max_response_bytes=64,
        **overrides,
    )


async def _invoke(
    middleware: HttpBoundaryMiddleware,
    *,
    headers: list[tuple[bytes, bytes]],
    body: bytes = b"",
) -> list[dict[str, Any]]:
    sent: list[dict[str, Any]] = []
    delivered = False

    async def receive() -> dict[str, Any]:
        nonlocal delivered
        if delivered:
            return {"type": "http.disconnect"}
        delivered = True
        return {"type": "http.request", "body": body, "more_body": False}

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    await middleware(
        {"type": "http", "method": "POST", "path": "/mcp", "headers": headers},
        receive,
        send,
    )
    return sent


def _status(messages: list[dict[str, Any]]) -> int:
    return next(m["status"] for m in messages if m["type"] == "http.response.start")


@pytest.mark.asyncio
async def test_rejects_unapproved_host_before_app() -> None:
    calls = 0

    async def app(scope, receive, send):
        nonlocal calls
        calls += 1

    middleware = HttpBoundaryMiddleware(app, _settings())
    messages = await _invoke(middleware, headers=[(b"host", b"evil.example")])
    assert _status(messages) == 400
    assert calls == 0


@pytest.mark.asyncio
async def test_rejects_unapproved_origin_before_app() -> None:
    calls = 0

    async def app(scope, receive, send):
        nonlocal calls
        calls += 1

    middleware = HttpBoundaryMiddleware(app, _settings())
    messages = await _invoke(
        middleware,
        headers=[(b"host", b"127.0.0.1:9102"), (b"origin", b"https://evil.example")],
    )
    assert _status(messages) == 403
    assert calls == 0


@pytest.mark.asyncio
async def test_rejects_oversized_request_before_app() -> None:
    calls = 0

    async def app(scope, receive, send):
        nonlocal calls
        calls += 1

    middleware = HttpBoundaryMiddleware(app, _settings())
    messages = await _invoke(
        middleware,
        headers=[(b"host", b"127.0.0.1")],
        body=b"x" * 17,
    )
    assert _status(messages) == 413
    assert calls == 0


@pytest.mark.asyncio
async def test_final_serialized_wire_response_uses_capability_limit() -> None:
    async def app(scope, receive, send):
        await receive()
        set_wire_response_limit(8)
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"123456789", "more_body": False})

    middleware = HttpBoundaryMiddleware(app, _settings())
    messages = await _invoke(middleware, headers=[(b"host", b"127.0.0.1")])
    assert _status(messages) == 500
    body = b"".join(m.get("body", b"") for m in messages)
    assert b"wire limit" in body


@pytest.mark.asyncio
async def test_exact_origin_and_host_reach_app() -> None:
    async def app(scope, receive, send):
        assert await receive() == {"type": "http.request", "body": b"{}", "more_body": False}
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok", "more_body": False})

    middleware = HttpBoundaryMiddleware(app, _settings())
    messages = await _invoke(
        middleware,
        headers=[
            (b"host", b"127.0.0.1:9102"),
            (b"origin", b"https://client.example"),
        ],
        body=b"{}",
    )
    assert _status(messages) == 200


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
    first = asyncio.create_task(_invoke(middleware, headers=[(b"host", b"127.0.0.1")], body=b"{}"))
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
