"""Unit tests for OpenHASP tools (fully mocked)."""

import json
from unittest.mock import MagicMock, patch

import pytest

from tools.constants import _success_response

FAKE_IP = "192.168.1.100"

FAKE_CONFIG = {
    "hasp": {"startpage": "1", "theme": "dark", "version": "0.7.0-rc13"},
    "gui": {"bckl": 45, "bcklinv": 0, "idle1": 60, "idle2": 120},
    "mqtt": {"host": "", "port": 1883, "name": "plate"},
    "wifi": {"ssid": "TestWiFi"},
}


def _json(data):
    return _success_response(data)


class TestOpenHASPDetection:
    def test_detect_reachable(self):
        from tools.iot_openhasp import _openhasp_detect

        with patch("tools.iot_openhasp._get_http_client") as mock_client:
            mock_http = MagicMock()
            mock_http.get_json.return_value = FAKE_CONFIG
            mock_client.return_value = mock_http
            result = _openhasp_detect(FAKE_IP)
            parsed = json.loads(result)
            assert parsed["success"] is True
            assert parsed["data"]["is_openhasp"] is True
            assert parsed["data"]["name"] == "plate"

    def test_detect_not_openhasp(self):
        from tools.iot_openhasp import _openhasp_detect

        with patch("tools.iot_openhasp._get_http_client") as mock_client:
            mock_http = MagicMock()
            mock_http.get_json.return_value = {"some": "data"}
            mock_client.return_value = mock_http
            result = _openhasp_detect(FAKE_IP)
            parsed = json.loads(result)
            assert parsed["success"] is False
            assert parsed["error"]["code"] == "NOT_OPENHASP"

    def test_detect_unreachable(self):
        from tools.iot_openhasp import _openhasp_detect

        with patch("tools.iot_openhasp._get_http_client") as mock_client:
            mock_http = MagicMock()
            mock_http.get_json.return_value = None
            mock_client.return_value = mock_http
            result = _openhasp_detect(FAKE_IP)
            parsed = json.loads(result)
            assert parsed["success"] is False


class TestOpenHASPStatus:
    def test_status_full(self):
        from tools.iot_openhasp import _openhasp_status

        telnet_status = {
            "version": "0.7.0-rc13",
            "tftDriver": "ST7796",
            "heapFree": 80000,
            "uptime": 3600,
            "rssi": -45,
            "mac": "AA:BB:CC:DD:EE:FF",
        }

        with (
            patch("tools.iot_openhasp._get_http_client") as mock_client,
            patch("tools.iot_openhasp._get_telnet_client") as mock_telnet,
        ):
            mock_http = MagicMock()
            mock_http.get_json.return_value = FAKE_CONFIG
            mock_http.count_objects.return_value = 1
            mock_http.count_pages.return_value = 1
            mock_client.return_value = mock_http

            mock_tn = MagicMock()
            mock_tn.statusupdate.return_value = telnet_status
            mock_telnet.return_value = mock_tn

            result = _openhasp_status(FAKE_IP)
            parsed = json.loads(result)
            assert parsed["success"] is True
            assert parsed["data"]["version"] == "0.7.0-rc13"
            assert parsed["data"]["tft_driver"] == "ST7796"
            assert parsed["data"]["objects_count"] == 1

    def test_status_not_openhasp(self):
        from tools.iot_openhasp import _openhasp_status

        with patch("tools.iot_openhasp._get_http_client") as mock_client:
            mock_http = MagicMock()
            mock_http.get_json.return_value = None
            mock_client.return_value = mock_http
            result = _openhasp_status(FAKE_IP)
            parsed = json.loads(result)
            assert parsed["success"] is False


class TestOpenHASPBacklight:
    def test_check_backlight_issues(self):
        from tools.iot_openhasp import _openhasp_check_backlight

        dark_config = {
            "hasp": {},
            "gui": {"bckl": 0, "bcklinv": 1, "idle1": 5, "idle2": 3},
        }
        with patch("tools.iot_openhasp._get_http_client") as mock_client:
            mock_http = MagicMock()
            mock_http.get_json.return_value = dark_config
            mock_client.return_value = mock_http
            result = _openhasp_check_backlight(FAKE_IP)
            parsed = json.loads(result)
            assert parsed["success"] is True
            assert parsed["data"]["issues_count"] > 0
            assert parsed["data"]["status"] == "issues_found"

    def test_check_backlight_ok(self):
        from tools.iot_openhasp import _openhasp_check_backlight

        ok_config = {
            "hasp": {},
            "gui": {"bckl": 255, "bcklinv": 0, "idle1": 30, "idle2": 120},
        }
        with patch("tools.iot_openhasp._get_http_client") as mock_client:
            mock_http = MagicMock()
            mock_http.get_json.return_value = ok_config
            mock_client.return_value = mock_http
            result = _openhasp_check_backlight(FAKE_IP)
            parsed = json.loads(result)
            assert parsed["data"]["issues_count"] == 0


class TestOpenHASPConfig:
    def test_get_config(self):
        from tools.iot_openhasp import _openhasp_get_config

        with patch("tools.iot_openhasp._get_http_client") as mock_client:
            mock_http = MagicMock()
            mock_http.get_json.return_value = FAKE_CONFIG
            mock_client.return_value = mock_http
            result = _openhasp_get_config(FAKE_IP)
            parsed = json.loads(result)
            assert parsed["success"] is True
            assert parsed["data"]["config"]["hasp"]["theme"] == "dark"


class TestOpenHASPPages:
    def test_get_pages(self):
        from tools.iot_openhasp import _openhasp_get_pages

        with patch("tools.iot_openhasp._get_http_client") as mock_client:
            mock_http = MagicMock()
            mock_http.get_text.return_value = '{"page":1}\n{"obj":"btn","page":1}'
            mock_http.count_objects.return_value = 1
            mock_http.count_pages.return_value = 1
            mock_client.return_value = mock_http
            result = _openhasp_get_pages(FAKE_IP)
            parsed = json.loads(result)
            assert parsed["success"] is True
            assert parsed["data"]["objects_count"] == 1


class TestOpenHASPFileOps:
    def test_download_file(self):
        from tools.iot_openhasp import _openhasp_download_file

        with patch("tools.iot_openhasp._get_http_client") as mock_client:
            mock_http = MagicMock()
            mock_http.get_text.return_value = '{"key":"value"}'
            mock_client.return_value = mock_http
            result = _openhasp_download_file(FAKE_IP, "config.json")
            parsed = json.loads(result)
            assert parsed["success"] is True
            assert parsed["data"]["filename"] == "config.json"

    def test_download_unknown_file(self):
        from tools.iot_openhasp import _openhasp_download_file

        result = _openhasp_download_file(FAKE_IP, "nonexistent.txt")
        parsed = json.loads(result)
        assert parsed["success"] is False
        assert parsed["error"]["code"] == "INVALID_PARAM"

    def test_upload_file(self):
        from tools.iot_openhasp import _openhasp_upload_file

        with patch("tools.iot_openhasp._get_http_client") as mock_client:
            mock_http = MagicMock()
            mock_http.upload_file.return_value = True
            mock_client.return_value = mock_http
            result = _openhasp_upload_file(FAKE_IP, "boot.cmd", "echo hi")
            parsed = json.loads(result)
            assert parsed["success"] is True


class TestOpenHASPTelnet:
    def test_send_command_success(self):
        from tools.iot_openhasp import _openhasp_send_command

        with patch("tools.iot_openhasp._get_telnet_client") as mock_telnet:
            mock_tn = MagicMock()
            mock_tn.send_command.return_value = "MSGR: backlight=on"
            mock_tn.parse_response.return_value = {"backlight": "on"}
            mock_telnet.return_value = mock_tn
            result = _openhasp_send_command(FAKE_IP, "backlight")
            parsed = json.loads(result)
            assert parsed["success"] is True
            assert parsed["data"]["parsed"] == {"backlight": "on"}

    def test_telnet_failed(self):
        from tools.iot_openhasp import _openhasp_send_command

        with patch("tools.iot_openhasp._get_telnet_client", return_value=None):
            result = _openhasp_send_command(FAKE_IP, "backlight")
            parsed = json.loads(result)
            assert parsed["success"] is False
            assert parsed["error"]["code"] == "TELNET_FAILED"


class TestOpenHASPBacklightSet:
    def test_backlight_on(self):
        from tools.iot_openhasp import _openhasp_backlight_set

        with patch("tools.iot_openhasp._get_telnet_client") as mock_telnet:
            mock_tn = MagicMock()
            mock_tn.backlight_set.return_value = "MSGR: backlight=255"
            mock_telnet.return_value = mock_tn
            result = _openhasp_backlight_set(FAKE_IP, "on", 255)
            parsed = json.loads(result)
            assert parsed["success"] is True


class TestOpenHASPHealth:
    def test_health_score(self):
        from tools.iot_openhasp import _openhasp_health

        status = {"version": "0.7.0", "tftDriver": "ST7796", "heapFree": 80000}
        with (
            patch("tools.iot_openhasp._get_http_client") as mock_client,
            patch("tools.iot_openhasp._get_telnet_client") as mock_telnet,
        ):
            mock_http = MagicMock()
            mock_http.get_json.return_value = FAKE_CONFIG
            mock_http.count_objects.return_value = 1
            mock_client.return_value = mock_http

            mock_tn = MagicMock()
            mock_tn.statusupdate.return_value = status
            mock_telnet.return_value = mock_tn

            result = _openhasp_health(FAKE_IP)
            parsed = json.loads(result)
            assert parsed["success"] is True
            assert parsed["data"]["health_score"] == 100
            assert parsed["data"]["health_level"] == "healthy"

    def test_health_critical(self):
        from tools.iot_openhasp import _openhasp_health

        bad_config = dict(FAKE_CONFIG)
        bad_config["gui"]["bckl"] = 0
        status = {"tftDriver": "Other", "heapFree": 10000}

        with (
            patch("tools.iot_openhasp._get_http_client") as mock_client,
            patch("tools.iot_openhasp._get_telnet_client") as mock_telnet,
        ):
            mock_http = MagicMock()
            mock_http.get_json.return_value = bad_config
            mock_http.count_objects.return_value = 60
            mock_client.return_value = mock_http

            mock_tn = MagicMock()
            mock_tn.statusupdate.return_value = status
            mock_telnet.return_value = mock_tn

            result = _openhasp_health(FAKE_IP)
            parsed = json.loads(result)
            assert parsed["success"] is True
            assert "critical" in parsed["data"]["health_level"]


class TestOpenHASPDiagnostics:
    def test_analyze_backlight_disabled(self):
        from tools.openhasp.diagnostics import analyze_backlight

        config = {"gui": {"bckl": 0, "bcklinv": 0, "idle1": 60, "idle2": 120}}
        issues = analyze_backlight(config)
        assert any("DISABLED" in i for i in issues)

    def test_analyze_backlight_ok(self):
        from tools.openhasp.diagnostics import analyze_backlight

        config = {"gui": {"bckl": 255, "bcklinv": 0, "idle1": 30, "idle2": 120}}
        issues = analyze_backlight(config)
        assert len(issues) == 0

    def test_validate_config_warnings(self):
        from tools.openhasp.diagnostics import validate_config

        config = {"gui": {"bckl": 0, "idle1": 5}}
        is_valid, warnings = validate_config(config, 60)
        assert is_valid is False
        assert len(warnings) > 0

    def test_validate_config_ok(self):
        from tools.openhasp.diagnostics import validate_config

        config = {"hasp": {}, "gui": {"bckl": 255, "idle1": 30}, "mqtt": {}}
        is_valid, _warnings = validate_config(config, 10)
        assert is_valid is True

    def test_health_score_healthy(self):
        from tools.openhasp.diagnostics import health_score

        score, level, _issues = health_score(
            {"tftDriver": "ST7796", "heapFree": 80000},
            objects_count=10,
            mqtt_responding=True,
            bckl=255,
        )
        assert score == 100
        assert level == "healthy"

    def test_health_score_critical_tft_other(self):
        from tools.openhasp.diagnostics import health_score

        score, level, _issues = health_score(
            {"tftDriver": "Other"},
            objects_count=1,
            mqtt_responding=False,
            bckl=0,
        )
        assert score < 50
        assert level == "critical"


class TestOpenHASPTelnetClient:
    def test_parse_response_msgr_format(self):
        from tools.openhasp.telnet import OpenHASPTelnet

        tn = OpenHASPTelnet("1.2.3.4")
        raw = "#backlight\r\nMSGR: backlight=on\r\n"
        result = tn.parse_response(raw)
        assert result == {"backlight": "on"}

    def test_parse_response_mqtt_pub_format(self):
        from tools.openhasp.telnet import OpenHASPTelnet

        tn = OpenHASPTelnet("1.2.3.4")
        raw = '#backlight\r\nMQTT PUB: backlight => {"state":"on","brightness":255}\r\n'
        result = tn.parse_response(raw)
        assert result == {"state": "on", "brightness": 255}

    def test_parse_response_ansi_cleanup(self):
        from tools.openhasp.telnet import OpenHASPTelnet

        tn = OpenHASPTelnet("1.2.3.4")
        raw = "\x1b[1000D\x1b[0KMSGR: backlight=255\r\n\x1b]2;Some Title\x07"
        result = tn.parse_response(raw)
        assert result == {"backlight": "255"}

    def test_parse_response_unknown_format(self):
        from tools.openhasp.telnet import OpenHASPTelnet

        tn = OpenHASPTelnet("1.2.3.4")
        result = tn.parse_response("some random output")
        assert result is None


class TestOpenHASPHTTPClient:
    def test_get_json(self):
        from tools.openhasp.http_client import OpenHASPHTTPClient

        with patch("tools.openhasp.http_client.requests.get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"hasp": {}}
            mock_get.return_value = mock_resp
            client = OpenHASPHTTPClient("1.2.3.4")
            result = client.get_json("/config.json")
            assert result == {"hasp": {}}

    def test_is_reachable(self):
        from tools.openhasp.http_client import OpenHASPHTTPClient

        with patch("tools.openhasp.http_client.requests.get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_get.return_value = mock_resp
            client = OpenHASPHTTPClient("1.2.3.4")
            assert client.is_reachable() is True


class TestOpenHASPToolRegistration:
    @pytest.fixture
    def mcp(self, mock_mcp):
        from tools.iot_openhasp import register_openhasp_tools

        register_openhasp_tools(mock_mcp)
        return mock_mcp

    def test_all_twenty_tools_registered(self, mcp):
        hasp_tools = [n for n in mcp._tools if n.startswith("openhasp_")]
        assert len(hasp_tools) == 20

    def test_detect_tool(self, mcp):
        with patch(
            "tools.iot_openhasp._openhasp_detect",
            return_value=_json({"is_openhasp": True, "name": "plate"}),
        ):
            result = mcp.get_tool("openhasp_detect")(ip_address=FAKE_IP)
            parsed = json.loads(result)
            assert parsed["success"] is True

    def test_status_tool(self, mcp):
        with patch(
            "tools.iot_openhasp._openhasp_status",
            return_value=_json({"version": "0.7.0", "tft_driver": "ST7796"}),
        ):
            result = mcp.get_tool("openhasp_status")(identifier=FAKE_IP)
            parsed = json.loads(result)
            assert parsed["success"] is True

    def test_backlight_diag_tool(self, mcp):
        with patch(
            "tools.iot_openhasp._openhasp_check_backlight", return_value=_json({"issues_count": 0})
        ):
            result = mcp.get_tool("openhasp_check_backlight")(identifier=FAKE_IP)
            parsed = json.loads(result)
            assert parsed["success"] is True

    def test_write_tool_guard(self, mcp):
        with patch(
            "tools.iot_openhasp.check_write_enabled", side_effect=Exception("write disabled")
        ):
            result = mcp.get_tool("openhasp_telnet")(identifier=FAKE_IP, command="backlight")
            parsed = json.loads(result)
            assert parsed["success"] is False

    def test_raw_telnet_rejects_unlisted_command(self, mcp):
        with (
            patch("tools.iot_openhasp.check_write_enabled", return_value=None),
            patch("tools.iot_openhasp._openhasp_send_command") as mock_send,
        ):
            result = mcp.get_tool("openhasp_telnet")(identifier=FAKE_IP, command="restart")
            parsed = json.loads(result)
            assert parsed["success"] is False
            assert parsed["error"]["code"] == "INVALID_PARAM"
            mock_send.assert_not_called()

    def test_health_tool(self, mcp):
        with patch(
            "tools.iot_openhasp._openhasp_health",
            return_value=_json({"health_score": 100, "health_level": "healthy"}),
        ):
            result = mcp.get_tool("openhasp_health")(identifier=FAKE_IP)
            parsed = json.loads(result)
            assert parsed["success"] is True

    def test_exception_handler(self, mcp):
        with patch("tools.iot_openhasp._openhasp_status", side_effect=Exception("BOOM")):
            result = mcp.get_tool("openhasp_status")(identifier=FAKE_IP)
            parsed = json.loads(result)
            assert parsed["success"] is False
            assert "BOOM" in parsed["error"]["message"]
