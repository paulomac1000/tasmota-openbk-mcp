"""Logging middleware for MCP server.

Assigns request_id at the middleware boundary and logs structured
invocation data (method, tool name, session, duration, status).
"""

import time
import uuid
from typing import Any

from tools.constants import get_logger, sanitize_log_line, set_request_id

logger = get_logger("middleware.logging")


class LoggingMiddleware:
    """Logging middleware that assigns request_id and logs structured invocation data.

    Must be called first in the middleware chain so that request_id
    is available for all downstream middleware.
    """

    def create_context(self, tool_name: str, session_id: str | None = None) -> dict[str, Any]:
        """Create a request context with request_id for a tool invocation.

        Args:
            tool_name: Name of the tool being invoked.
            session_id: Optional session identifier.

        Returns:
            Context dict with request_id, tool_name, session_id, and start_time.
        """
        rid = str(uuid.uuid4())
        set_request_id(rid)
        ctx: dict[str, Any] = {
            "request_id": rid,
            "tool_name": tool_name,
            "start_time": time.monotonic(),
            "session_id": session_id or "anonymous",
        }
        logger.debug(
            "Invoked: tool=%s session=%s request_id=%s",
            tool_name,
            ctx["session_id"],
            rid,
        )
        return ctx

    def log_completion(self, ctx: dict[str, Any], status: str, duration_ms: int) -> None:
        """Log the completion of a tool invocation.

        Args:
            ctx: The context dict from create_context().
            status: Status string (e.g. 'success', 'error', 'rate_limited').
            duration_ms: Execution duration in milliseconds.
        """
        logger.info(
            "Complete: tool=%s session=%s status=%s duration=%dms request_id=%s",
            ctx.get("tool_name", "?"),
            ctx.get("session_id", "?"),
            status,
            duration_ms,
            ctx.get("request_id", "?"),
        )

    def log_error(self, ctx: dict[str, Any], error: str, duration_ms: int) -> None:
        """Log a tool invocation error.

        Args:
            ctx: The context dict from create_context().
            error: Error description.
            duration_ms: Execution duration in milliseconds.
        """
        logger.error(
            "Error: tool=%s session=%s error=%s duration=%dms request_id=%s",
            ctx.get("tool_name", "?"),
            ctx.get("session_id", "?"),
            sanitize_log_line(error),
            duration_ms,
            ctx.get("request_id", "?"),
        )
