"""Unit tests for MCP middleware modules.

Tests for AuthMiddleware, RateLimitMiddleware, and LoggingMiddleware.
Zero I/O -- all external state mocked via unittest.mock.patch.
"""

import os
from unittest.mock import patch

import pytest

from tools.middleware.auth import AuthMiddleware
from tools.middleware.logging_mw import LoggingMiddleware
from tools.middleware.rate_limit import RateLimitExceeded, RateLimitMiddleware

# =============================================================================
# AuthMiddleware
# =============================================================================


class TestAuthMiddleware:
    """Tests for AuthMiddleware -- Bearer token and API key validation."""

    def test_disabled_when_no_env(self):
        """Auth should be disabled when MCP_AUTH_TOKEN and MCP_API_KEY are not set."""
        with patch.dict(os.environ, {}, clear=True):
            am = AuthMiddleware()
            assert am.is_enabled is False

    def test_enabled_when_token_set(self):
        """Auth should be enabled when MCP_AUTH_TOKEN is set."""
        with patch.dict(os.environ, {"MCP_AUTH_TOKEN": "test-token"}, clear=True):
            am = AuthMiddleware()
            assert am.is_enabled is True

    def test_enabled_when_api_key_set(self):
        """Auth should be enabled when MCP_API_KEY is set."""
        with patch.dict(os.environ, {"MCP_API_KEY": "test-key"}, clear=True):
            am = AuthMiddleware()
            assert am.is_enabled is True

    def test_valid_bearer_token(self):
        """Valid Bearer token should be accepted."""
        am = AuthMiddleware()
        am._allowed_token = "valid-token"
        assert am.validate_bearer("valid-token") is True

    def test_invalid_bearer_token(self):
        """Invalid Bearer token should be rejected."""
        am = AuthMiddleware()
        am._allowed_token = "valid-token"
        assert am.validate_bearer("wrong") is False

    def test_empty_bearer_token(self):
        """Empty/None Bearer token should be rejected when auth is enabled."""
        am = AuthMiddleware()
        am._allowed_token = "valid-token"
        assert am.validate_bearer(None) is False
        assert am.validate_bearer("") is False

    def test_bearer_skipped_when_no_token_configured(self):
        """validate_bearer should return True when no allowed token is configured."""
        am = AuthMiddleware()
        am._allowed_token = ""
        assert am.validate_bearer("anything") is True
        assert am.validate_bearer(None) is True

    def test_valid_api_key(self):
        """Valid API key should be accepted."""
        am = AuthMiddleware()
        am._allowed_api_key = "valid-key"
        assert am.validate_api_key("valid-key") is True

    def test_invalid_api_key(self):
        """Invalid API key should be rejected."""
        am = AuthMiddleware()
        am._allowed_api_key = "valid-key"
        assert am.validate_api_key("wrong") is False

    def test_api_key_skipped_when_no_key_configured(self):
        """validate_api_key should return True when no allowed key is configured."""
        am = AuthMiddleware()
        am._allowed_api_key = ""
        assert am.validate_api_key("anything") is True
        assert am.validate_api_key(None) is True

    def test_authenticate_with_valid_bearer(self):
        """authenticate() should succeed with valid Bearer token."""
        am = AuthMiddleware()
        am._allowed_token = "test-token"
        result = am.authenticate({"authorization": "Bearer test-token"})
        assert result["authenticated"] is True
        assert result["user"] == "bearer"

    def test_authenticate_with_valid_bearer_uppercase_header(self):
        """authenticate() should also accept Authorization header with uppercase key."""
        am = AuthMiddleware()
        am._allowed_token = "test-token"
        result = am.authenticate({"Authorization": "Bearer test-token"})
        assert result["authenticated"] is True

    def test_authenticate_with_invalid_bearer(self):
        """authenticate() should fail with invalid Bearer token and include error."""
        am = AuthMiddleware()
        am._allowed_token = "test-token"
        result = am.authenticate({"authorization": "Bearer wrong"})
        assert result["authenticated"] is False
        assert result["user"] is None
        assert "error" in result
        assert result["error"]["code"] == "AUTH_FAILED"

    def test_authenticate_missing_header(self):
        """authenticate() should fail when auth header is missing."""
        am = AuthMiddleware()
        am._allowed_token = "test-token"
        result = am.authenticate({})
        assert result["authenticated"] is False
        assert result["user"] is None
        assert "error" in result
        assert "Missing Bearer token" in result["error"]["message"]

    def test_authenticate_with_valid_api_key(self):
        """authenticate() should succeed with valid API key."""
        am = AuthMiddleware()
        am._allowed_api_key = "test-key"
        result = am.authenticate({"x-api-key": "test-key"})
        assert result["authenticated"] is True
        assert result["user"] == "api-key"

    def test_authenticate_with_valid_api_key_uppercase_header(self):
        """authenticate() should also accept X-Api-Key header with uppercase key."""
        am = AuthMiddleware()
        am._allowed_api_key = "test-key"
        result = am.authenticate({"X-Api-Key": "test-key"})
        assert result["authenticated"] is True

    def test_authenticate_disabled_returns_anonymous(self):
        """authenticate() should return anonymous success when auth is disabled."""
        with patch.dict(os.environ, {}, clear=True):
            am = AuthMiddleware()
            result = am.authenticate({})
            assert result["authenticated"] is True
            assert result["user"] == "anonymous"

    def test_authenticate_bearer_preferred_over_api_key(self):
        """authenticate() should prefer Bearer token when both are set."""
        am = AuthMiddleware()
        am._allowed_token = "token"
        am._allowed_api_key = "key"
        result = am.authenticate(
            {
                "authorization": "Bearer token",
                "x-api-key": "key",
            }
        )
        assert result["authenticated"] is True
        assert result["user"] == "bearer"

    def test_validate_api_key_with_none_when_key_configured(self):
        """validate_api_key(None) should return False when key is configured, covering line 62."""
        am = AuthMiddleware()
        am._allowed_api_key = "test-key"
        assert am.validate_api_key(None) is False
        assert am.validate_api_key("") is False

    def test_authenticate_with_invalid_api_key_present(self):
        """authenticate() with wrong API key should fail and log, covering lines 102, 109-110."""
        am = AuthMiddleware()
        am._allowed_api_key = "valid-key"
        result = am.authenticate({"x-api-key": "wrong-key"})
        assert result["authenticated"] is False
        assert result["user"] is None
        assert "error" in result
        assert "invalid" in result["error"]["message"].lower()

    def test_authenticate_missing_api_key_when_key_configured(self):
        """Missing API key when configured should report error, covering line 114."""
        am = AuthMiddleware()
        am._allowed_token = ""
        am._allowed_api_key = "test-key"
        result = am.authenticate({})  # No auth headers
        assert result["authenticated"] is False
        assert "Missing API key" in result.get("error", {}).get("message", "")


# =============================================================================
# RateLimitMiddleware
# =============================================================================


class TestRateLimitMiddleware:
    """Tests for RateLimitMiddleware -- sliding window rate limiting."""

    def test_under_limit(self):
        """Requests under the rate limit should pass."""
        rl = RateLimitMiddleware(max_per_min=5)
        assert rl.check("test-session") is True

    def test_over_limit_raises(self):
        """Requests over the rate limit should raise RateLimitExceeded."""
        rl = RateLimitMiddleware(max_per_min=2)
        rl.check("s1")
        rl.check("s1")
        with pytest.raises(RateLimitExceeded):
            rl.check("s1")

    def test_different_sessions_independent(self):
        """Different sessions should have independent rate limits."""
        rl = RateLimitMiddleware(max_per_min=2)
        rl.check("s1")
        rl.check("s1")
        # s2 should still be allowed
        assert rl.check("s2") is True

    def test_reset_session(self):
        """Reset should clear session counters so requests pass again."""
        rl = RateLimitMiddleware(max_per_min=2)
        rl.check("s1")
        rl.check("s1")
        rl.reset_session("s1")
        assert rl.check("s1") is True

    def test_max_per_min_property(self):
        """max_per_min property should return the configured limit."""
        rl = RateLimitMiddleware(max_per_min=10)
        assert rl.max_per_min == 10

    def test_check_request_under_limit(self):
        """check_request() should return allowed=True when under limit."""
        rl = RateLimitMiddleware(max_per_min=5)
        result = rl.check_request({"mcp-session-id": "s1"})
        assert result["allowed"] is True

    def test_check_request_defaults_to_anonymous(self):
        """check_request() should default to anonymous session when no header."""
        rl = RateLimitMiddleware(max_per_min=5)
        # This should not raise -- anonymous session gets its own counter
        result = rl.check_request({})
        assert result["allowed"] is True

    def test_check_request_over_limit(self):
        """check_request() should return error dict when over limit."""
        rl = RateLimitMiddleware(max_per_min=2)
        # Fill up the counter
        rl.check("s1")
        rl.check("s1")
        # This third call via check_request should trigger the rate limit
        result = rl.check_request({"mcp-session-id": "s1"})
        assert result["allowed"] is False
        assert result["error"]["code"] == "RATE_LIMITED"
        assert result["error"]["retryable"] is True
        assert result["error"]["retry_after_ms"] > 0

    def test_check_request_uppercase_header(self):
        """check_request() should handle Mcp-Session-Id with uppercase key."""
        rl = RateLimitMiddleware(max_per_min=5)
        result = rl.check_request({"Mcp-Session-Id": "s1"})
        assert result["allowed"] is True

    def test_rate_limit_exceeded_attributes(self):
        """RateLimitExceeded should carry retry_after_ms."""
        exc = RateLimitExceeded(retry_after_ms=5000)
        assert exc.retry_after_ms == 5000
        assert "5000" in str(exc)

    def test_time_window_slides(self):
        """Old timestamps outside the window should be cleaned out."""
        rl = RateLimitMiddleware(max_per_min=2)
        # Inject an old timestamp directly
        import time

        old_ts = time.monotonic() - 120.0  # 2 minutes ago
        rl._sessions["s1"] = [old_ts]
        # After cleanup, the old timestamp should be gone and request should pass
        assert rl.check("s1") is True


# =============================================================================
# LoggingMiddleware
# =============================================================================


class TestLoggingMiddleware:
    """Tests for LoggingMiddleware -- request context and structured logging."""

    def test_create_context_has_request_id(self):
        """create_context() should generate a UUID request_id."""
        lm = LoggingMiddleware()
        ctx = lm.create_context("test_tool", "sess_123")
        assert "request_id" in ctx
        assert isinstance(ctx["request_id"], str)
        assert len(ctx["request_id"]) == 36  # UUID4 hex with dashes
        assert ctx["tool_name"] == "test_tool"
        assert ctx["session_id"] == "sess_123"
        assert ctx["start_time"] > 0

    def test_create_context_default_session(self):
        """create_context() should default session_id to 'anonymous'."""
        lm = LoggingMiddleware()
        ctx = lm.create_context("test_tool")
        assert ctx["session_id"] == "anonymous"

    def test_create_context_sets_thread_local(self):
        """create_context() should set the thread-local request_id."""
        from tools.constants import get_request_id

        lm = LoggingMiddleware()
        ctx = lm.create_context("tool_a")
        # The request_id in context should match thread-local
        assert get_request_id() == ctx["request_id"]

    def test_log_completion(self):
        """log_completion() should not raise."""
        lm = LoggingMiddleware()
        ctx = lm.create_context("test", "s1")
        lm.log_completion(ctx, "success", 42)

    def test_log_completion_no_context_keys(self):
        """log_completion() should handle missing context keys gracefully."""
        lm = LoggingMiddleware()
        lm.log_completion({}, "success", 0)  # should not raise

    def test_log_error(self):
        """log_error() should not raise."""
        lm = LoggingMiddleware()
        ctx = lm.create_context("test", "s1")
        lm.log_error(ctx, "test error", 99)

    def test_log_error_no_context_keys(self):
        """log_error() should handle missing context keys gracefully."""
        lm = LoggingMiddleware()
        lm.log_error({}, "some error", 0)  # should not raise
