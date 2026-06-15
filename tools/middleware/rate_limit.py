"""Rate limiting middleware for MCP server.

Enforces per-session request quotas using an in-memory sliding window.
Lock-protected to ensure thread safety.
"""

import os
import threading
import time
from typing import Any

from tools.constants import get_logger

logger = get_logger("middleware.rate_limit")

# Default: 60 requests per minute per session
_MCP_RATE_LIMIT_RAW = os.getenv("MCP_RATE_LIMIT", "60")
try:
    _MCP_RATE_LIMIT_VALUE = int(_MCP_RATE_LIMIT_RAW)
except ValueError:
    raise ValueError(f"MCP_RATE_LIMIT must be an integer, got: {_MCP_RATE_LIMIT_RAW}")
if _MCP_RATE_LIMIT_VALUE <= 0:
    raise ValueError(f"MCP_RATE_LIMIT must be > 0, got: {_MCP_RATE_LIMIT_VALUE}")
DEFAULT_MAX_PER_MIN = _MCP_RATE_LIMIT_VALUE


class RateLimitExceeded(Exception):
    """Raised when the rate limit is exceeded."""

    def __init__(self, retry_after_ms: int) -> None:
        self.retry_after_ms = retry_after_ms
        super().__init__(f"Rate limit exceeded, retry after {retry_after_ms}ms")


class RateLimitMiddleware:
    """Per-session rate limiting with in-memory sliding window.

    Tracks request timestamps per session ID and rejects requests
    that exceed the configured limit within the time window.
    """

    def __init__(self, max_per_min: int = DEFAULT_MAX_PER_MIN) -> None:
        if max_per_min <= 0:
            raise ValueError(f"max_per_min must be > 0, got: {max_per_min}")
        self._max_per_min = max_per_min
        self._sessions: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    @property
    def max_per_min(self) -> int:
        """Get the configured max requests per minute."""
        return self._max_per_min

    def check(self, session_id: str) -> bool:
        """Check whether a request from this session should be allowed.

        Returns True if the request is within limits, False if rate limited.
        """
        now = time.monotonic()
        window_start = now - 60.0  # 1 minute sliding window

        with self._lock:
            timestamps = self._sessions.get(session_id, [])

            # Remove timestamps outside the sliding window
            timestamps = [t for t in timestamps if t > window_start]

            if len(timestamps) >= self._max_per_min:
                # Rate limited -- calculate retry_after
                oldest = timestamps[0]
                retry_after_ms = int((oldest + 60.0 - now) * 1000) + 1
                logger.warning("Rate limit exceeded for session %s", session_id[:8])
                raise RateLimitExceeded(retry_after_ms=retry_after_ms)

            timestamps.append(now)
            self._sessions[session_id] = timestamps
            return True

    def check_request(self, headers: dict[str, str]) -> dict[str, Any]:
        """Check rate limit from request headers.

        Extracts session ID from Mcp-Session-Id header.

        Args:
            headers: HTTP headers dict.

        Returns:
            Context dict with 'allowed' bool. On failure, 'error' set.
        """
        normalized_headers = {k.lower(): v for k, v in headers.items()}
        session_id = normalized_headers.get("mcp-session-id", "") or "anonymous"
        try:
            self.check(session_id)
            return {"allowed": True}
        except RateLimitExceeded as exc:
            return {
                "allowed": False,
                "error": {
                    "code": "RATE_LIMITED",
                    "message": f"Rate limit exceeded. Max {self._max_per_min} requests per minute.",
                    "retryable": True,
                    "retry_after_ms": exc.retry_after_ms,
                },
            }

    def reset_session(self, session_id: str) -> None:
        """Reset rate limit counters for a session (e.g., on session end).

        Args:
            session_id: Session ID to reset.
        """
        with self._lock:
            self._sessions.pop(session_id, None)
