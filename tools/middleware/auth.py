"""Authentication middleware for MCP server.

Validates Bearer tokens and API keys before tool execution.
Token validation uses hmac.compare_digest for timing-safe comparison.
"""

import hmac
import os
from typing import Any

from tools.constants import get_logger

logger = get_logger("middleware.auth")


class AuthMiddleware:
    """Validates Bearer tokens and API keys for the MCP server.

    Reads allowed tokens from env vars:
    - MCP_AUTH_TOKEN: Bearer token for Authorization header
    - MCP_API_KEY: API key for X-Api-Key header

    When neither is set, authentication is skipped (open access).
    """

    def __init__(self) -> None:
        self._allowed_token = os.getenv("MCP_AUTH_TOKEN", "")
        self._allowed_api_key = os.getenv("MCP_API_KEY", "")

    @property
    def is_enabled(self) -> bool:
        """Whether authentication is enabled (at least one credential configured)."""
        return bool(self._allowed_token) or bool(self._allowed_api_key)

    def validate_bearer(self, token: str | None) -> bool:
        """Validate a Bearer token using timing-safe comparison.

        Args:
            token: The Bearer token value to validate.

        Returns:
            True if the token is valid or auth is disabled.
        """
        if not self._allowed_token:
            return True  # No token configured -- skip validation
        if not token:
            return False
        return hmac.compare_digest(token, self._allowed_token)

    def validate_api_key(self, api_key: str | None) -> bool:
        """Validate an API key using timing-safe comparison.

        Args:
            api_key: The API key value to validate.

        Returns:
            True if the key is valid or auth is disabled.
        """
        if not self._allowed_api_key:
            return True  # No API key configured -- skip validation
        if not api_key:
            return False
        return hmac.compare_digest(api_key, self._allowed_api_key)

    def authenticate(self, headers: dict[str, str]) -> dict[str, Any]:
        """Authenticate a request from HTTP headers.

        Bearer token (Authorization header) and API key (X-Api-Key header)
        are treated as alternatives -- either one is sufficient.

        Args:
            headers: HTTP headers dict (keys are normalized to lowercase for matching).

        Returns:
            Context dict with 'authenticated' bool and 'user' info.
            On failure, 'error' is set with structured error response.
        """
        if not self.is_enabled:
            return {"authenticated": True, "user": "anonymous"}

        # Normalize headers to lowercase for case-insensitive matching
        normalized_headers = {k.lower(): v for k, v in headers.items()}

        # Extract credentials from headers
        auth_header = normalized_headers.get("authorization", "")
        bearer_token = auth_header[7:] if auth_header.startswith("Bearer ") else None
        api_key = normalized_headers.get("x-api-key", "")

        # Track what is needed/was attempted for error reporting
        bearer_expected = bool(self._allowed_token)
        api_key_expected = bool(self._allowed_api_key)

        # Try Bearer token
        bearer_valid = False
        if bearer_expected and bearer_token:
            if self.validate_bearer(bearer_token):
                return {"authenticated": True, "user": "bearer"}
            bearer_valid = False  # token was present but invalid

        # Try API key
        api_key_valid = False
        if api_key_expected and api_key:
            if self.validate_api_key(api_key):
                return {"authenticated": True, "user": "api-key"}
            api_key_valid = False  # key was present but invalid

        # Determine error message
        if bearer_expected and bearer_token and not bearer_valid:
            logger.warning("Invalid Bearer token rejected")
            msg = "Authentication failed -- invalid credentials"
        elif api_key_expected and api_key and not api_key_valid:
            logger.warning("Invalid API key rejected")
            msg = "Authentication failed -- invalid credentials"
        elif bearer_expected and not bearer_token:
            msg = "Missing Bearer token in Authorization header"
        else:
            msg = "Missing API key in X-Api-Key header"

        return {
            "authenticated": False,
            "user": None,
            "error": {
                "code": "AUTH_FAILED",
                "message": msg,
                "retryable": False,
            },
        }
