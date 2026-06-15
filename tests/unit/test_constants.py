"""Unit tests for constants module - response helpers, logging, manifests."""

import json

import pytest

from tools.constants import (
    _build_meta,
    _error_response,
    _error_response_extended,
    _success_response,
    get_logger,
    get_tool_manifest,
    sanitize_response_data,
    setup_logging,
)

pytestmark = pytest.mark.unit


class TestResponseHelpers:
    """Tests for response helper functions."""

    def test_success_response_returns_valid_json(self):
        result = _success_response({"key": "value"})
        data = json.loads(result)
        assert data["success"] is True
        assert data["data"] == {"key": "value"}
        assert "_meta" in data
        assert "request_id" in data["_meta"]
        assert data["_meta"]["tool_version"] == "1.6.0"

    def test_success_response_with_list(self):
        result = _success_response([1, 2, 3])
        data = json.loads(result)
        assert data["success"] is True
        assert data["data"] == [1, 2, 3]

    def test_error_response_returns_valid_json(self):
        result = _error_response("Something went wrong")
        data = json.loads(result)
        assert data["success"] is False
        assert data["error"] == "Something went wrong"
        assert "_meta" in data

    def test_error_response_extended_full(self):
        result = _error_response_extended(
            code="TIMEOUT",
            message="Device did not respond",
            retryable=True,
            suggestion="Check power and retry",
            available_names=["Device_A", "Device_B"],
        )
        data = json.loads(result)
        assert data["success"] is False
        err = data["error"]
        assert err["code"] == "TIMEOUT"
        assert err["message"] == "Device did not respond"
        assert err["retryable"] is True
        assert err["suggestion"] == "Check power and retry"
        assert err["available_names"] == ["Device_A", "Device_B"]

    def test_error_response_extended_minimal(self):
        result = _error_response_extended(code="INVALID_PARAM", message="Bad input")
        data = json.loads(result)
        assert data["success"] is False
        err = data["error"]
        assert err["code"] == "INVALID_PARAM"
        assert err["message"] == "Bad input"
        assert err["retryable"] is False
        assert "suggestion" not in err

    def test_build_meta_has_uuid_and_version(self):
        from tools.constants import start_tool_context

        rid = start_tool_context()
        meta = _build_meta()
        # request_id must be the id set at tool entry, not a fresh UUID - so it
        # correlates with the log lines for the same invocation.
        assert meta["request_id"] == rid
        assert len(meta["request_id"]) == 36  # UUID length
        assert meta["tool_version"] == "1.6.0"

    def test_build_meta_with_extra(self):
        meta = _build_meta(cached=True, duration_ms=42)
        assert meta["cached"] is True
        assert meta["duration_ms"] == 42


class TestLogging:
    """Tests for logging setup."""

    def test_setup_logging_creates_logger(self):
        setup_logging()
        logger = get_logger("test")
        assert logger.name == "iot_mcp.test"

    def test_setup_logging_idempotent(self):
        setup_logging()
        setup_logging()
        logger = get_logger("idempotent")
        assert logger.name == "iot_mcp.idempotent"

    def test_get_logger_returns_named_logger(self):
        log = get_logger("server")
        assert log.name == "iot_mcp.server"


class TestToolManifest:
    """Tests for tool manifest accessor."""

    def test_get_tool_manifest_found(self):
        manifest = get_tool_manifest("iot_discover_devices")
        assert manifest is not None
        assert manifest["risk"] == "READ"
        assert manifest["timeout_ms"] == 120000
        assert manifest["determinism"] == "env-dependent"

    def test_get_tool_manifest_missing(self):
        manifest = get_tool_manifest("nonexistent_tool")
        assert manifest is None

    def test_all_manifests_have_required_fields(self):
        required = {
            "name",
            "version",
            "risk",
            "side_effects",
            "idempotent",
            "retryable",
            "concurrent_safe",
            "timeout_ms",
            "requires_confirmation",
            "determinism",
            "latency",
            "cost",
            "impact",
            "privacy",
            "reversible",
        }
        from tools.constants import TOOL_MANIFESTS

        for tool_name, manifest in TOOL_MANIFESTS.items():
            missing = required - set(manifest.keys())
            assert not missing, f"Tool '{tool_name}' missing fields: {missing}"

    def test_new_config_tool_manifests_have_descriptions(self):
        """Verify all 8 new v1.6.0 config tool manifests have non-empty descriptions."""
        from tools.constants import TOOL_MANIFESTS

        new_tools = [
            "iot_set_flags",
            "iot_set_name",
            "iot_configure_mqtt",
            "iot_set_gpio",
            "iot_execute_command",
            "iot_set_startup_command",
            "iot_start_ha_discovery",
            "iot_get_full_info",
        ]

        for tool_name in new_tools:
            manifest = TOOL_MANIFESTS.get(tool_name)
            assert manifest is not None, f"Missing manifest for {tool_name}"
            desc = manifest.get("description", "")
            assert desc, f"Empty description for {tool_name}"


class TestRiskConsistencyMatrix:
    """Compliance: every manifest must satisfy the Risk Consistency Matrix."""

    # risk -> required field values (see mcp-server-standards.md)
    _MATRIX = {
        "READ": {
            "side_effects": {"none", "read"},
            "idempotent": True,
            "retryable": True,
            "reversible": True,
            "requires_confirmation": False,
            "impact": {"none"},
        },
        "WRITE": {
            "side_effects": {"write"},
            "idempotent": True,
            "retryable": True,
            "reversible": True,
            "requires_confirmation": True,
            "impact": {"transient", "persistent"},
        },
        "DESTRUCTIVE": {
            "side_effects": {"destructive"},
            "idempotent": False,
            "retryable": False,
            "reversible": False,
            "requires_confirmation": True,
            "impact": {"persistent", "service_outage"},
        },
    }

    def test_every_manifest_matches_matrix(self):
        from tools.constants import TOOL_MANIFESTS

        for name, m in TOOL_MANIFESTS.items():
            risk = m["risk"]
            assert risk in self._MATRIX, f"{name}: unexpected risk {risk!r}"
            rule = self._MATRIX[risk]
            assert m["side_effects"] in rule["side_effects"], (
                f"{name}: side_effects {m['side_effects']!r} invalid for {risk}"
            )
            assert m["impact"] in rule["impact"], (
                f"{name}: impact {m['impact']!r} invalid for {risk}"
            )
            for field in ("idempotent", "retryable", "reversible", "requires_confirmation"):
                assert m[field] == rule[field], (
                    f"{name}: {field}={m[field]!r} but {risk} requires {rule[field]!r}"
                )

    def test_restart_device_is_destructive_not_dangerous(self):
        from tools.constants import TOOL_MANIFESTS

        manifest = TOOL_MANIFESTS["iot_restart_device"]
        # A device reboot has a fixed command set - it is DESTRUCTIVE, never
        # DANGEROUS (which is reserved for arbitrary shell execution).
        assert manifest["risk"] == "DESTRUCTIVE"
        assert manifest["reversible"] is False
        assert manifest["retryable"] is False


class TestSanitizeResponseData:
    """Tests for response payload sanitization."""

    def test_redacts_bearer_token_in_string(self):
        result = sanitize_response_data("Authorization: Bearer abc123xyz")
        assert "abc123xyz" not in result
        assert "REDACTED" in result

    def test_redacts_password_url_pattern_in_string(self):
        result = sanitize_response_data("https://host?password=secret123&user=test_user")
        assert "secret123" not in result
        assert "REDACTED" in result

    def test_redacts_in_nested_dict(self):
        result = sanitize_response_data(
            {"wifi": {"url": "https://host?password=abc", "ssid": "net"}}
        )
        assert result["wifi"]["ssid"] == "net"
        assert "abc" not in result["wifi"]["url"]
        assert "REDACTED" in result["wifi"]["url"]

    def test_redacts_sensitive_field_names(self):
        result = sanitize_response_data(
            {
                "device_id": "device-1",
                "local_key": "abc123def4567890",
                "access_secret": "secret-value",
                "api_key": "api-value",
            }
        )
        assert result["device_id"] == "device-1"
        assert result["local_key"] == "<REDACTED>"
        assert result["access_secret"] == "<REDACTED>"
        assert result["api_key"] == "<REDACTED>"

    def test_redacts_in_list(self):
        result = sanitize_response_data(["Bearer tok123", "normal text"])
        assert "tok123" not in result[0]
        assert result[1] == "normal text"

    def test_preserves_ip_addresses(self):
        result = sanitize_response_data({"ip": "192.168.1.100", "gateway": "192.168.1.1"})
        assert result["ip"] == "192.168.1.100"
        assert result["gateway"] == "192.168.1.1"

    def test_passes_scalars_through(self):
        assert sanitize_response_data(42) == 42
        assert sanitize_response_data(None) is None
        assert sanitize_response_data(True) is True


class TestManifestFactories:
    """Tests for _make_manifest, _make_write_manifest, _make_destructive_manifest."""

    def test_make_manifest_defaults(self):
        from tools.constants import _make_manifest

        m = _make_manifest("test_read")
        assert m["risk"] == "READ"
        assert m["idempotent"] is True
        assert m["retryable"] is True
        assert m["reversible"] is True
        assert m["requires_confirmation"] is False
        assert m["impact"] == "none"
        assert m["privacy"] == "none"
        assert m["side_effects"] == "read"

    def test_make_manifest_override(self):
        from tools.constants import _make_manifest

        m = _make_manifest(
            "test", privacy="metadata", side_effects="none", determinism="deterministic"
        )
        assert m["privacy"] == "metadata"
        assert m["side_effects"] == "none"
        assert m["determinism"] == "deterministic"

    def test_make_write_manifest_defaults(self):
        from tools.constants import _make_write_manifest

        m = _make_write_manifest("test_write")
        assert m["risk"] == "WRITE"
        assert m["idempotent"] is True
        assert m["retryable"] is True
        assert m["reversible"] is True
        assert m["requires_confirmation"] is True
        assert m["side_effects"] == "write"
        assert m["concurrent_safe"] is False

    def test_make_destructive_manifest_defaults(self):
        from tools.constants import _make_destructive_manifest

        m = _make_destructive_manifest("test_destroy")
        assert m["risk"] == "DESTRUCTIVE"
        assert m["idempotent"] is False
        assert m["retryable"] is False
        assert m["reversible"] is False
        assert m["requires_confirmation"] is True
        assert m["side_effects"] == "destructive"
        assert m["concurrent_safe"] is False
        assert m["impact"] == "service_outage"


class TestMetaHelpers:
    """Tests for _build_meta and build_meta optional parameters."""

    def test_build_meta_with_cached(self):
        """_build_meta with cached=True should include cached in meta."""
        meta = _build_meta(cached=True)
        assert meta.get("cached") is True

    def test_build_meta_with_retry_safe(self):
        """_build_meta with retry_safe=True should include retry_safe in meta."""
        meta = _build_meta(retry_safe=True)
        assert meta.get("retry_safe") is True

    def test_build_meta_with_extra_kwargs(self):
        """_build_meta with extra kwargs should merge them into meta."""
        meta = _build_meta(**{"custom_field": "custom_value"})
        assert meta.get("custom_field") == "custom_value"

    def test_error_dict_extended_with_all_options(self):
        """_error_dict_extended with suggestion and available_names should include both."""
        from tools.constants import _error_dict_extended

        err = _error_dict_extended(
            "TEST_CODE", "test message", True, suggestion="try X", available_names=["a", "b"]
        )
        assert err["success"] is False
        assert err["error"]["suggestion"] == "try X"
        assert err["error"]["available_names"] == ["a", "b"]

    def test_build_meta_records_invocation(self):
        """build_meta should record the tool invocation."""
        from tools.constants import build_meta, get_tool_counts

        counts_before = get_tool_counts().get("test_meta_tool", 0)
        build_meta("test_meta_tool")
        counts_after = get_tool_counts().get("test_meta_tool", 0)
        assert counts_after == counts_before + 1

    def test_build_meta_with_start_time(self):
        """build_meta with start_time should compute duration_ms."""
        import time

        from tools.constants import build_meta

        start = time.monotonic()
        meta = build_meta("test_meta_time", start_time=start)
        assert "request_id" in meta
        assert "duration_ms" in meta
        assert isinstance(meta["duration_ms"], int)
        assert meta["duration_ms"] >= 0


class TestUtilityFunctions:
    """Tests for utility functions (get_tool_counts, sanitize_log_line, etc.)."""

    def test_get_tool_counts(self):
        """get_tool_counts should return a dict."""
        from tools.constants import get_tool_counts

        counts = get_tool_counts()
        assert isinstance(counts, dict)

    def test_sanitize_log_line(self):
        """sanitize_log_line should redact sensitive patterns."""
        from tools.constants import sanitize_log_line

        result = sanitize_log_line("Authorization: Bearer secret123")
        assert "secret123" not in result
        assert "REDACTED" in result

    def test_sanitize_log_line_preserves_normal(self):
        """sanitize_log_line should preserve normal log text."""
        from tools.constants import sanitize_log_line

        result = sanitize_log_line("Normal log message")
        assert result == "Normal log message"

    def test_request_id_filter(self):
        """RequestIdFilter should inject request_id from thread-local."""
        import logging

        from tools.constants import RequestIdFilter, set_request_id

        set_request_id("test-rid-123")
        filt = RequestIdFilter()
        record = logging.LogRecord("test", logging.INFO, "", 0, "msg", (), None)
        assert filt.filter(record) is True
        assert record.request_id == "test-rid-123"

    def test_inject_tool_risk_prefix(self):
        """inject_tool_risk_prefix should prepend risk prefix to docstring."""
        from tools.constants import inject_tool_risk_prefix

        def fake_tool():
            """Do something."""
            pass

        fake_tool.__name__ = "iot_get_device_info"
        wrapped = inject_tool_risk_prefix(fake_tool)
        assert wrapped.__doc__ == "[READ] Do something."

    def test_inject_tool_risk_prefix_unknown(self):
        """inject_tool_risk_prefix should pass through for unknown tools."""
        from tools.constants import inject_tool_risk_prefix

        def fake_tool():
            """Do something."""
            pass

        fake_tool.__name__ = "nonexistent_tool"
        wrapped = inject_tool_risk_prefix(fake_tool)
        assert wrapped.__doc__ == "Do something."
