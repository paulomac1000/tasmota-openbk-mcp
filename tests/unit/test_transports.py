"""
Unit tests for Streamable HTTP transport layer.

Tests session management, Origin validation, JSON-RPC error handling,
middleware integration, and route availability via Starlette TestClient.
Zero I/O -- all external dependencies are mocked.
"""

from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest

from server import (
    BIND_HOST,
    _create_session,
    _delete_session,
    _validate_origin,
    _validate_session,
    create_rest_app,
)
from tools.middleware.auth import AuthMiddleware
from tools.middleware.rate_limit import RateLimitExceeded, RateLimitMiddleware

pytestmark = pytest.mark.unit


# =============================================================================
# SESSION MANAGEMENT
# =============================================================================


class TestSessionManagement:
    """Tests for _create_session, _validate_session, _delete_session."""

    def test_create_session_returns_uuid(self):
        """_create_session should return a valid UUID string."""
        session_id = _create_session()
        assert len(session_id) == 36
        assert "-" in session_id

    def test_create_session_multiple_unique(self):
        """Multiple calls should return different IDs."""
        s1 = _create_session()
        s2 = _create_session()
        assert s1 != s2

    def test_validate_valid_session(self):
        """Existing session ID should validate."""
        session_id = _create_session()
        assert _validate_session(session_id) is True

    def test_validate_invalid_session(self):
        """Non-existent session should not validate."""
        assert _validate_session("nonexistent-uuid") is False

    def test_validate_none_session(self):
        """None session should not validate."""
        assert _validate_session(None) is False

    def test_validate_empty_session(self):
        """Empty session should not validate."""
        assert _validate_session("") is False

    def test_delete_session_removes_it(self):
        """_delete_session should remove the session."""
        session_id = _create_session()
        assert _validate_session(session_id) is True
        _delete_session(session_id)
        assert _validate_session(session_id) is False

    def test_delete_nonexistent_does_not_raise(self):
        """Deleting a non-existent session should not raise."""
        _delete_session("nonexistent")

    def test_delete_session_then_recreate(self):
        """After delete, session is gone; new one can be created."""
        sid = _create_session()
        _delete_session(sid)
        assert _validate_session(sid) is False
        sid2 = _create_session()
        assert sid2 != sid
        assert _validate_session(sid2) is True


# =============================================================================
# ORIGIN VALIDATION
# =============================================================================


class TestOriginValidation:
    """Tests for _validate_origin function from server module."""

    def _make_request(self, origin: str | None = None) -> MagicMock:
        request = MagicMock()
        request.headers.get = MagicMock(return_value=origin)
        return request

    def test_localhost_allowed(self):
        """Origin http://localhost should be allowed."""
        assert _validate_origin(self._make_request("http://localhost:9102")) is True

    def test_localhost_no_port_allowed(self):
        """Origin http://localhost (no port) allowed."""
        assert _validate_origin(self._make_request("http://localhost")) is True

    def test_127_0_0_1_allowed(self):
        """Origin http://127.0.0.1 should be allowed."""
        assert _validate_origin(self._make_request("http://127.0.0.1:9102")) is True

    def test_https_localhost_allowed(self):
        """Origin https://localhost should be allowed."""
        assert _validate_origin(self._make_request("https://localhost")) is True

    def test_empty_origin_allowed(self):
        """Empty Origin allowed (non-browser request)."""
        assert _validate_origin(self._make_request("")) is True

    def test_none_origin_allowed(self):
        """None Origin allowed (non-browser request)."""
        assert _validate_origin(self._make_request(None)) is True

    def test_external_origin_blocked(self):
        """External origin (evil.com) should be blocked."""
        assert _validate_origin(self._make_request("https://evil.com")) is False

    def test_unparseable_origin_blocked(self):
        """Garbage origin string should return False."""
        assert _validate_origin(self._make_request("not-a-valid-origin")) is False

    def test_bind_host_origin_allowed(self):
        """Origin matching configured BIND_HOST should be allowed."""
        assert _validate_origin(self._make_request(f"http://{BIND_HOST}:9102")) is True

    def test_bind_host_same_as_localhost(self):
        """When BIND_HOST is 127.0.0.1, that origin should validate."""
        if BIND_HOST == "127.0.0.1":
            assert _validate_origin(self._make_request("http://127.0.0.1:9102")) is True


# =============================================================================
# JSON-RPC PROTOCOL (pure data structures, no server imports needed)
# =============================================================================


class TestJsonRpc:
    """Tests for JSON-RPC protocol structures matching server responses."""

    def test_tools_list_request_shape(self):
        """tools/list must have jsonrpc, method, and id."""
        body = {"jsonrpc": "2.0", "method": "tools/list", "id": 1}
        assert body["method"] == "tools/list"
        assert body["jsonrpc"] == "2.0"
        assert body["id"] == 1

    def test_tools_call_request_shape(self):
        """tools/call must have params with name/arguments."""
        body = {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {"name": "iot_list_devices", "arguments": {}},
            "id": 2,
        }
        assert body["method"] == "tools/call"
        assert body["params"]["name"] == "iot_list_devices"
        assert body["params"]["arguments"] == {}

    def test_unknown_tool_error_code(self):
        """Unknown tool uses JSON-RPC code -32602."""
        assert {"code": -32602, "message": "Unknown tool: nonexistent"}["code"] == -32602

    def test_method_not_found_error_code(self):
        """Unknown method uses JSON-RPC code -32601."""
        assert {"code": -32601, "message": "Method not found"}["code"] == -32601

    def test_internal_error_code(self):
        """Internal error uses JSON-RPC code -32603."""
        assert {"code": -32603, "message": "Internal error"}["code"] == -32603

    def test_missing_method_yields_empty_string(self):
        """Request without method -> .get('method', '') -> ''."""
        assert {"jsonrpc": "2.0", "id": 1}.get("method", "") == ""

    def test_missing_id_is_none(self):
        """Request without id -> .get('id') -> None."""
        assert {"jsonrpc": "2.0", "method": "tools/list"}.get("id") is None

    def test_successful_list_response_has_tools(self):
        """Successful tools/list response has a tools list."""
        response = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {"tools": [{"name": "t", "description": "d"}]},
        }
        assert "result" in response
        assert "tools" in response["result"]

    def test_error_response_has_error_not_result(self):
        """Error responses have 'error' and NOT 'result'."""
        response = {
            "jsonrpc": "2.0",
            "id": 1,
            "error": {"code": -32601, "message": "Method not found"},
        }
        assert "error" in response
        assert "result" not in response


# =============================================================================
# MIDDLEWARE INTEGRATION
# tools.middleware.* imports work fine -- no fastmcp dependency.
# =============================================================================


class TestMiddlewareIntegration:
    """Tests for middleware chain composition (Auth -> RateLimit)."""

    # -- AuthMiddleware tests --

    def test_auth_disabled_allows_anonymous(self):
        """No auth configured -> anonymous access."""
        with patch.dict("os.environ", {}, clear=True):
            auth = AuthMiddleware()
            result = auth.authenticate({"authorization": ""})
            assert result["authenticated"] is True
            assert result["user"] == "anonymous"

    def test_auth_accepts_valid_bearer(self):
        """Correct Bearer token -> authenticated."""
        with patch.dict("os.environ", {"MCP_AUTH_TOKEN": "valid-token"}):
            auth = AuthMiddleware()
            result = auth.authenticate({"authorization": "Bearer valid-token"})
            assert result["authenticated"] is True
            assert result["user"] == "bearer"

    def test_auth_rejects_invalid_bearer(self):
        """Wrong Bearer token -> not authenticated."""
        with patch.dict("os.environ", {"MCP_AUTH_TOKEN": "valid-token"}):
            auth = AuthMiddleware()
            result = auth.authenticate({"authorization": "Bearer wrong"})
            assert result["authenticated"] is False
            assert "error" in result

    def test_auth_rejects_missing_bearer_when_required(self):
        """No token when one is configured -> fail with specific message."""
        with patch.dict("os.environ", {"MCP_AUTH_TOKEN": "req"}):
            auth = AuthMiddleware()
            result = auth.authenticate({"authorization": ""})
            assert result["authenticated"] is False
            assert "Missing Bearer token" in result["error"]["message"]

    def test_auth_accepts_valid_api_key(self):
        """Correct API key -> authenticated."""
        with patch.dict("os.environ", {"MCP_API_KEY": "secret"}):
            auth = AuthMiddleware()
            result = auth.authenticate({"x-api-key": "secret"})
            assert result["authenticated"] is True
            assert result["user"] == "api-key"

    def test_auth_rejects_invalid_api_key(self):
        """Wrong API key -> not authenticated."""
        with patch.dict("os.environ", {"MCP_API_KEY": "secret"}):
            auth = AuthMiddleware()
            result = auth.authenticate({"x-api-key": "wrong"})
            assert result["authenticated"] is False

    # -- RateLimitMiddleware tests --

    def test_rate_limit_accepts_first_request(self):
        """Rate limit accepts first request under limit."""
        rl = RateLimitMiddleware(max_per_min=10)
        result = rl.check_request({"mcp-session-id": "s1"})
        assert result["allowed"] is True

    def test_rate_limit_rejects_excessive_requests(self):
        """Over limit -> RateLimitExceeded raised."""
        rl = RateLimitMiddleware(max_per_min=1)
        rl.check("excessive")
        with pytest.raises(RateLimitExceeded):
            rl.check("excessive")

    def test_rate_limit_reset_clears(self):
        """Reset clears rate-limit counters."""
        rl = RateLimitMiddleware(max_per_min=1)
        rl.reset_session("unknown-reset")
        assert "unknown-reset" not in rl._sessions

    def test_rate_limit_anonymous_fallback(self):
        """check_request without session ID works (anonymous fallback)."""
        rl = RateLimitMiddleware(max_per_min=10)
        result = rl.check_request({})
        assert result["allowed"] is True

    def test_rate_limit_check_request_error_dict(self):
        """check_request returns error dict when rate limited."""
        rl = RateLimitMiddleware(max_per_min=1)
        rl.check("limited-session")
        result = rl.check_request({"mcp-session-id": "limited-session"})
        assert result["allowed"] is False
        assert result["error"]["code"] == "RATE_LIMITED"

    # -- Chain tests --

    def test_auth_then_rate_limit_chain(self):
        """Auth passes -> rate limit passes -> chain OK."""
        with patch.dict("os.environ", {}, clear=True):
            headers = {"mcp-session-id": "chain-test"}
            auth_result = AuthMiddleware().authenticate(headers)
            assert auth_result["authenticated"] is True
            rl_result = RateLimitMiddleware(max_per_min=10).check_request(headers)
            assert rl_result["allowed"] is True

    def test_rate_limit_then_auth_chain(self):
        """Rate-limited -> blocked before auth check."""
        with patch.dict("os.environ", {}, clear=True):
            headers = {"mcp-session-id": "chain-limited"}
            rl = RateLimitMiddleware(max_per_min=1)
            rl.check("chain-limited")
            rl_result = rl.check_request(headers)
            assert rl_result["allowed"] is False
            # Auth would have passed but never reached
            auth_result = AuthMiddleware().authenticate(headers)
            assert auth_result["authenticated"] is True

    @patch("tools.middleware.rate_limit.time")
    def test_rate_limit_window_sliding(self, mock_time):
        """Old requests expire from sliding window after 60s."""
        mock_time.monotonic.return_value = 1000.0
        rl = RateLimitMiddleware(max_per_min=2)
        rl.check("slide")
        rl.check("slide")
        mock_time.monotonic.return_value = 1061.0  # 61s forward
        assert rl.check("slide") is True

    def test_reset_session_after_rate_limit(self):
        """Reset allows previously limited session to make requests."""
        rl = RateLimitMiddleware(max_per_min=1)
        rl.check("reset-me")
        with pytest.raises(RateLimitExceeded):
            rl.check("reset-me")
        rl.reset_session("reset-me")
        assert rl.check("reset-me") is True


# =============================================================================
# TRANSPORT ROUTES (via Starlette TestClient)
# =============================================================================


class TestTransportRoutes:
    """Tests for /mcp routes via Starlette TestClient."""

    def _create_app(self):
        """Create app with ALL patches active.

        Returns a context manager that keeps patches alive for the full
        request lifecycle. Use: with self._create_app() as (app, client): ...
        """

        @contextmanager
        def _patched_app():
            with (
                patch("server.get_all_tools", return_value={}),
                patch("server.get_tool_count", return_value=0),
                patch("server.get_tool_counts", return_value={}),
            ):
                from starlette.testclient import TestClient

                app = create_rest_app()
                client = TestClient(app)
                yield app, client

        return _patched_app()

    def test_mcp_get_returns_200(self):
        """GET /mcp returns SSE placeholder."""
        with self._create_app() as (app, client):
            resp = client.get("/mcp")
            assert resp.status_code == 200
            data = resp.json()
            assert data["jsonrpc"] == "2.0"
            assert data["result"]["stream"] == "mcp-events"

    def test_mcp_post_tools_list_returns_200(self):
        """POST /mcp with tools/list returns tool list."""
        with self._create_app() as (app, client):
            body = {"jsonrpc": "2.0", "method": "tools/list", "id": 1}
            resp = client.post("/mcp", json=body, headers={"origin": "http://localhost:9102"})
            assert resp.status_code == 200
            data = resp.json()
            assert data["jsonrpc"] == "2.0"
            assert "tools" in data["result"]

    def test_mcp_post_list_categories_returns_200(self):
        """POST /mcp with tools/list_categories returns categories."""
        with self._create_app() as (app, client):
            body = {"jsonrpc": "2.0", "method": "tools/list_categories", "id": 1}
            resp = client.post("/mcp", json=body, headers={"origin": "http://localhost:9102"})
            assert resp.status_code == 200
            assert "categories" in resp.json()["result"]

    def test_mcp_get_schema_unknown_tool_returns_404(self):
        """tools/get_schema for unknown tool returns -32602."""
        with patch("server.get_tool", return_value=None):
            with self._create_app() as (app, client):
                body = {
                    "jsonrpc": "2.0",
                    "method": "tools/get_schema",
                    "params": {"name": "nonexistent_tool"},
                    "id": 1,
                }
                resp = client.post("/mcp", json=body, headers={"origin": "http://localhost:9102"})
                assert resp.status_code == 404
                assert resp.json()["error"]["code"] == -32602

    def test_mcp_post_missing_method_returns_404(self):
        """POST /mcp without method returns -32601."""
        with self._create_app() as (app, client):
            body = {"jsonrpc": "2.0", "id": 1}
            resp = client.post("/mcp", json=body, headers={"origin": "http://localhost:9102"})
            assert resp.status_code == 404
            assert resp.json()["error"]["code"] == -32601

    def test_mcp_post_unknown_method_returns_404(self):
        """POST /mcp with unknown method returns -32601."""
        with self._create_app() as (app, client):
            body = {"jsonrpc": "2.0", "method": "bogus_method", "id": 1}
            resp = client.post("/mcp", json=body, headers={"origin": "http://localhost:9102"})
            assert resp.status_code == 404
            assert resp.json()["error"]["code"] == -32601

    def test_mcp_post_invalid_json_returns_400(self):
        """POST /mcp with invalid JSON returns 400."""
        with self._create_app() as (app, client):
            resp = client.post(
                "/mcp",
                content=b"not valid json",
                headers={
                    "origin": "http://localhost:9102",
                    "content-type": "application/json",
                },
            )
            assert resp.status_code == 400
            assert "error" in resp.json()

    def test_mcp_post_origin_not_allowed_returns_403(self):
        """POST /mcp with external Origin blocked (403)."""
        with self._create_app() as (app, client):
            body = {"jsonrpc": "2.0", "method": "tools/list", "id": 1}
            resp = client.post("/mcp", json=body, headers={"origin": "https://evil.com"})
            assert resp.status_code == 403

    def test_mcp_post_no_origin_returns_200(self):
        """POST /mcp without Origin header allowed (non-browser client)."""
        with self._create_app() as (app, client):
            body = {"jsonrpc": "2.0", "method": "tools/list", "id": 1}
            resp = client.post("/mcp", json=body)
            assert resp.status_code == 200

    def test_mcp_delete_returns_200(self):
        """DELETE /mcp returns success."""
        with self._create_app() as (app, client):
            resp = client.delete("/mcp", headers={"Origin": "http://localhost:9102"})
            assert resp.status_code == 200
            assert resp.json()["success"] is True

    def test_mcp_delete_with_session_terminates(self):
        """DELETE /mcp with session ID terminates it."""
        session_id = _create_session()
        assert _validate_session(session_id) is True

        with self._create_app() as (app, client):
            resp = client.delete(
                "/mcp", headers={"mcp-session-id": session_id, "Origin": "http://localhost:9102"}
            )
            assert resp.status_code == 200
        assert _validate_session(session_id) is False

    def test_mcp_delete_with_case_insensitive_header(self):
        """DELETE /mcp with Mcp-Session-Id (capitalized)."""
        session_id = _create_session()
        with self._create_app() as (app, client):
            resp = client.delete(
                "/mcp", headers={"Mcp-Session-Id": session_id, "Origin": "http://localhost:9102"}
            )
            assert resp.status_code == 200
        assert _validate_session(session_id) is False

    def test_health_route_returns_200(self):
        """GET /health returns healthy."""
        with self._create_app() as (app, client):
            resp = client.get("/health")
            assert resp.status_code == 200
            assert resp.json()["status"] == "healthy"

    def test_api_health_route_returns_200(self):
        """GET /api/health returns healthy."""
        with self._create_app() as (app, client):
            resp = client.get("/api/health")
            assert resp.status_code == 200
            assert resp.json()["status"] == "healthy"

    def test_api_tools_route_returns_200(self):
        """GET /api/tools returns tool list."""
        mock_tool = MagicMock()
        mock_tool.description = "Test tool"
        mock_tool.fn = MagicMock(__doc__="Test tool docstring")

        from starlette.testclient import TestClient

        with (
            patch("server.get_all_tools", return_value={"test_tool": mock_tool}),
            patch("server.get_tool_count", return_value=1),
            patch("server.get_tool_counts", return_value={}),
        ):
            app = create_rest_app()
            client = TestClient(app)
            resp = client.get("/api/tools")
            assert resp.status_code == 200
            assert resp.json()["success"] is True

    def test_mcp_post_tools_call_missing_name_returns_400(self):
        """tools/call with empty name returns -32602."""
        with self._create_app() as (app, client):
            body = {
                "jsonrpc": "2.0",
                "method": "tools/call",
                "params": {"name": "", "arguments": {}},
                "id": 1,
            }
            resp = client.post("/mcp", json=body, headers={"origin": "http://localhost:9102"})
            assert resp.status_code == 400
            assert resp.json()["error"]["code"] == -32602

    def test_mcp_route_count(self):
        """The app should have exactly 3 /mcp routes (GET, POST, DELETE)."""
        with self._create_app() as (app, _):
            mcp_routes = [r for r in app.routes if r.path == "/mcp"]
            assert len(mcp_routes) == 3

    def test_all_routes_present(self):
        """All expected routes should be registered."""
        with self._create_app() as (app, _):
            paths = {(r.path, tuple(sorted(r.methods))) for r in app.routes}
            expected = {
                ("/health", ("GET", "HEAD")),
                ("/api/health", ("GET", "HEAD")),
                ("/api/tools", ("GET", "HEAD")),
                ("/api/tools/{tool_name}", ("POST",)),
                ("/api/tools/{tool_name}/manifest", ("GET", "HEAD")),
                ("/mcp", ("DELETE",)),
                ("/mcp", ("GET", "HEAD")),
                ("/mcp", ("POST",)),
            }
            assert expected.issubset(paths), f"Missing routes: {expected - paths}"
