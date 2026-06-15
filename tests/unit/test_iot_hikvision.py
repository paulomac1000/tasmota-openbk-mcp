"""Unit tests for Hikvision doorbell tools (fully mocked)."""

import json
from unittest.mock import MagicMock, patch

import pytest
import requests

from tools.constants import _success_response

FAKE_HOST = "192.168.1.101"
FAKE_USER = "hikvision_user"
FAKE_PASS = "test_password"

FAKE_XML = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<DeviceInfo xmlns="http://www.isapi.org/ver20/XMLSchema">'
    "<deviceName>Videodoorbell</deviceName>"
    "<model>DS-KV6113-WPE1(C)</model>"
    "<firmwareVersion>V2.2.65</firmwareVersion>"
    "<serialNumber>DS-KV6113-WPE1(C)0120250625RRGC0255224</serialNumber>"
    "<macAddress>a4:d5:c2:6c:54:3b</macAddress>"
    "</DeviceInfo>"
)

FAKE_MOTION_XML = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<MotionDetection xmlns="http://www.isapi.org/ver20/XMLSchema">'
    "<enabled>true</enabled>"
    "<regionType>grid</regionType>"
    "<Grid>"
    "<rowGranularity>18x18</rowGranularity>"
    "<columnGranularity>22x22</columnGranularity>"
    "</Grid>"
    "<MotionDetectionLayout>"
    "<sensitivityLevel>70</sensitivityLevel>"
    "<layout>"
    "<gridMap>0F0F</gridMap>"
    "</layout>"
    "</MotionDetectionLayout>"
    "</MotionDetection>"
)

FAKE_TRIGGERS_XML = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<EventTriggerList xmlns="http://www.isapi.org/ver20/XMLSchema">'
    "<EventTrigger>"
    "<id>vmd-1</id>"
    "<eventType>VMD</eventType>"
    "<EventTriggerNotificationList>"
    "<EventTriggerNotification>"
    "<id>center</id>"
    "<notificationMethod>center</notificationMethod>"
    "<recurrence>beginning</recurrence>"
    "</EventTriggerNotification>"
    "</EventTriggerNotificationList>"
    "</EventTrigger>"
    "<EventTrigger>"
    "<id>videoloss-1</id>"
    "<eventType>videoloss</eventType>"
    "<EventTriggerNotificationList>"
    "<EventTriggerNotification>"
    "<id>center</id>"
    "<notificationMethod>center</notificationMethod>"
    "<recurrence>beginning</recurrence>"
    "</EventTriggerNotification>"
    "</EventTriggerNotificationList>"
    "</EventTrigger>"
    "</EventTriggerList>"
)


def _json(data):
    return _success_response(data)


class TestHikvisionDockerClient:
    def test_container_running(self):
        from tools.hikvision.docker_client import get_container_status

        with patch("tools.hikvision.docker_client._docker_request") as mock_req:
            mock_req.return_value = (
                200,
                json.dumps(
                    {
                        "State": {
                            "Running": True,
                            "Status": "running",
                            "StartedAt": "2026-06-01T18:43:11Z",
                            "Health": {"Status": "healthy"},
                        }
                    }
                ),
            )
            result = get_container_status()
            assert result["running"] is True
            assert result["status"] == "running"
            assert result["health"] == "healthy"

    def test_container_not_found(self):
        from tools.hikvision.docker_client import get_container_status

        with patch("tools.hikvision.docker_client._docker_request") as mock_req:
            mock_req.return_value = (404, "")
            result = get_container_status()
            assert result["running"] is False
            assert result["status"] == "not_found"

    def test_container_error(self):
        from tools.hikvision.docker_client import get_container_status

        with patch("tools.hikvision.docker_client._docker_request") as mock_req:
            mock_req.return_value = None
            result = get_container_status()
            assert result["running"] is False
            assert result["status"] == "not_found"

    def test_count_vmd_events_with_events(self):
        from tools.hikvision.docker_client import count_vmd_events

        with patch("tools.hikvision.docker_client.get_container_logs") as mock_logs:
            mock_logs.return_value = "2026-06-01 Motion detected from Gate\n" * 5
            result = count_vmd_events(since="4h")
            assert result["vmd_count"] == 5
            assert result["isapi_healthy"] is True

    def test_count_vmd_events_isapi_dead(self):
        from tools.hikvision.docker_client import count_vmd_events

        with patch("tools.hikvision.docker_client.get_container_logs") as mock_logs:
            mock_logs.return_value = "(empty - no events)\n"
            result = count_vmd_events(since="4h")
            assert result["vmd_count"] == 0
            assert result["isapi_healthy"] is False

    def test_count_call_events_with_calls(self):
        from tools.hikvision.docker_client import count_call_events

        with patch("tools.hikvision.docker_client.get_container_logs") as mock_logs:
            mock_logs.return_value = (
                "Doorbell ringing\nMotion detected from Gate\nDoorbell ringing\nDoorbell ringing"
            )
            result = count_call_events(since="4h")
            assert result["call_count"] == 3
            assert result["has_calls"] is True

    def test_count_call_events_no_calls(self):
        from tools.hikvision.docker_client import count_call_events

        with patch("tools.hikvision.docker_client.get_container_logs") as mock_logs:
            mock_logs.return_value = "Motion detected from Gate"
            result = count_call_events(since="4h")
            assert result["call_count"] == 0
            assert result["has_calls"] is False

    def test_restart_container_success(self):
        from tools.hikvision.docker_client import restart_container

        with patch("tools.hikvision.docker_client._docker_request") as mock_req:
            mock_req.return_value = (204, "")
            result = restart_container()
            assert result["success"] is True

    def test_restart_container_failure(self):
        from tools.hikvision.docker_client import restart_container

        with patch("tools.hikvision.docker_client._docker_request") as mock_req:
            mock_req.return_value = (500, "error")
            result = restart_container()
            assert result["success"] is False

    def test_get_container_logs_success(self):
        from tools.hikvision.docker_client import get_container_logs

        with patch("tools.hikvision.docker_client._docker_request") as mock_req:
            mock_req.return_value = (200, "log line 1\nlog line 2\n")
            result = get_container_logs(since="1h", tail=50)
            assert "log line 1" in result


class TestHikvisionISAPIClient:
    def test_get_motion_config_success(self):
        from tools.hikvision.isapi_client import HikvisionISAPIClient

        with patch("tools.hikvision.isapi_client.requests.Session") as MockSession:
            mock_resp = MagicMock(status_code=200, text=FAKE_MOTION_XML)
            MockSession.return_value.get.return_value = mock_resp
            client = HikvisionISAPIClient(FAKE_HOST, FAKE_USER, FAKE_PASS)
            config = client.get_motion_config()
            assert config is not None
            assert config["enabled"] is True
            assert config["sensitivity"] == 70
            assert config["grid_map"] == "0F0F"
            assert config["grid_rows"] == 18
            assert config["grid_cols"] == 22

    def test_get_motion_config_failure(self):
        from tools.hikvision.isapi_client import HikvisionISAPIClient

        with patch("tools.hikvision.isapi_client.requests.Session") as MockSession:
            MockSession.return_value.get.side_effect = requests.RequestException("Timeout")
            client = HikvisionISAPIClient(FAKE_HOST, FAKE_USER, FAKE_PASS)
            assert client.get_motion_config() is None

    def test_get_device_info_success(self):
        from tools.hikvision.isapi_client import HikvisionISAPIClient

        with patch("tools.hikvision.isapi_client.requests.Session") as MockSession:
            mock_resp = MagicMock(status_code=200, text=FAKE_XML)
            MockSession.return_value.get.return_value = mock_resp
            client = HikvisionISAPIClient(FAKE_HOST, FAKE_USER, FAKE_PASS)
            info = client.get_device_info()
            assert info is not None
            assert info["model"] == "DS-KV6113-WPE1(C)"
            assert info["firmwareVersion"] == "V2.2.65"

    def test_get_snapshot_success(self):
        from tools.hikvision.isapi_client import HikvisionISAPIClient

        with patch("tools.hikvision.isapi_client.requests.Session") as MockSession:
            mock_resp = MagicMock(status_code=200, content=b"fake_jpeg")
            MockSession.return_value.get.return_value = mock_resp
            client = HikvisionISAPIClient(FAKE_HOST, FAKE_USER, FAKE_PASS)
            assert client.get_snapshot() == b"fake_jpeg"

    def test_get_snapshot_auth_failure(self):
        from tools.hikvision.isapi_client import HikvisionISAPIClient

        with patch("tools.hikvision.isapi_client.requests.Session") as MockSession:
            mock_resp = MagicMock(status_code=401)
            mock_resp.raise_for_status.side_effect = Exception("401")
            MockSession.return_value.get.return_value = mock_resp
            client = HikvisionISAPIClient(FAKE_HOST, FAKE_USER, "wrong")
            assert client.get_snapshot() is None

    def test_get_device_info_network_error(self):
        from tools.hikvision.isapi_client import HikvisionISAPIClient

        with patch("tools.hikvision.isapi_client.requests.Session") as MockSession:
            MockSession.return_value.get.side_effect = Exception("Timeout")
            client = HikvisionISAPIClient(FAKE_HOST, FAKE_USER, FAKE_PASS)
            assert client.get_device_info() is None

    def test_open_door_success(self):
        from tools.hikvision.isapi_client import HikvisionISAPIClient

        with patch("tools.hikvision.isapi_client.requests.Session") as MockSession:
            mock_resp = MagicMock(status_code=200)
            MockSession.return_value.put.return_value = mock_resp
            client = HikvisionISAPIClient(FAKE_HOST, FAKE_USER, FAKE_PASS)
            assert client.open_door() is True

    def test_open_door_failure(self):
        from tools.hikvision.isapi_client import HikvisionISAPIClient

        with patch("tools.hikvision.isapi_client.requests.Session") as MockSession:
            mock_resp = MagicMock(status_code=403)
            mock_resp.raise_for_status.side_effect = Exception("403")
            MockSession.return_value.put.return_value = mock_resp
            client = HikvisionISAPIClient(FAKE_HOST, FAKE_USER, FAKE_PASS)
            assert client.open_door() is False

    def test_get_event_triggers_success(self):
        from tools.hikvision.isapi_client import HikvisionISAPIClient

        with patch("tools.hikvision.isapi_client.requests.Session") as MockSession:
            mock_resp = MagicMock(status_code=200, text=FAKE_TRIGGERS_XML)
            MockSession.return_value.get.return_value = mock_resp
            client = HikvisionISAPIClient(FAKE_HOST, FAKE_USER, FAKE_PASS)
            result = client.get_event_triggers()
            assert result is not None
            assert len(result) == 2
            assert result[0]["event_type"] == "VMD"
            assert result[0]["notifications"][0]["method"] == "center"
            assert result[1]["event_type"] == "videoloss"
            assert result[1]["notifications"][0]["recurrence"] == "beginning"

    def test_get_event_triggers_failure(self):
        from tools.hikvision.isapi_client import HikvisionISAPIClient

        with patch("tools.hikvision.isapi_client.requests.Session") as MockSession:
            mock_resp = MagicMock(status_code=500)
            mock_resp.raise_for_status.side_effect = Exception("500")
            MockSession.return_value.get.return_value = mock_resp
            client = HikvisionISAPIClient(FAKE_HOST, FAKE_USER, FAKE_PASS)
            assert client.get_event_triggers() is None

    def test_ping_reachable(self):
        from tools.hikvision.isapi_client import HikvisionISAPIClient

        with patch("tools.hikvision.isapi_client.requests.Session") as MockSession:
            mock_resp = MagicMock(status_code=302)
            MockSession.return_value.get.return_value = mock_resp
            client = HikvisionISAPIClient(FAKE_HOST, FAKE_USER, FAKE_PASS)
            assert client.ping() is True

    def test_set_motion_config_full_update(self):
        from tools.hikvision.isapi_client import HikvisionISAPIClient

        with patch("tools.hikvision.isapi_client.requests.Session") as MockSession:
            mock_put_resp = MagicMock(status_code=200)
            MockSession.return_value.put.return_value = mock_put_resp
            client = HikvisionISAPIClient(FAKE_HOST, FAKE_USER, FAKE_PASS)
            with patch.object(
                client,
                "get_motion_config",
                return_value={
                    "enabled": False,
                    "sensitivity": 50,
                    "grid_map": "FFFF",
                    "grid_rows": 18,
                    "grid_cols": 22,
                },
            ):
                result = client.set_motion_config(enabled=True, sensitivity=60)
                assert result is True
                call_args = MockSession.return_value.put.call_args
                body = call_args[1]["data"]
                assert "<ns0:enabled>true</ns0:enabled>" in body
                assert "<ns0:sensitivityLevel>60</ns0:sensitivityLevel>" in body
                assert "<ns0:regionType>grid</ns0:regionType>" in body
                assert "<ns0:rowGranularity>18x18</ns0:rowGranularity>" in body
                assert "<ns0:columnGranularity>22x22</ns0:columnGranularity>" in body
                assert "<ns0:gridMap>FFFF</ns0:gridMap>" in body

    def test_set_motion_config_partial_update(self):
        from tools.hikvision.isapi_client import HikvisionISAPIClient

        with patch("tools.hikvision.isapi_client.requests.Session") as MockSession:
            mock_put_resp = MagicMock(status_code=200)
            MockSession.return_value.put.return_value = mock_put_resp
            client = HikvisionISAPIClient(FAKE_HOST, FAKE_USER, FAKE_PASS)
            with patch.object(
                client,
                "get_motion_config",
                return_value={
                    "enabled": False,
                    "sensitivity": 50,
                    "grid_map": "0F0F",
                    "grid_rows": 18,
                    "grid_cols": 22,
                },
            ):
                result = client.set_motion_config(sensitivity=60)
                assert result is True
                call_args = MockSession.return_value.put.call_args
                body = call_args[1]["data"]
                assert "<ns0:enabled>false</ns0:enabled>" in body
                assert "<ns0:sensitivityLevel>60</ns0:sensitivityLevel>" in body
                assert "<ns0:gridMap>0F0F</ns0:gridMap>" in body

    def test_set_motion_config_failure(self):
        from tools.hikvision.isapi_client import HikvisionISAPIClient

        with patch("tools.hikvision.isapi_client.requests.Session") as MockSession:
            mock_put_resp = MagicMock(status_code=400)
            mock_put_resp.raise_for_status.side_effect = Exception("400")
            MockSession.return_value.put.return_value = mock_put_resp
            client = HikvisionISAPIClient(FAKE_HOST, FAKE_USER, FAKE_PASS)
            with patch.object(
                client,
                "get_motion_config",
                return_value={
                    "enabled": True,
                    "sensitivity": 50,
                    "grid_map": "FFFF",
                    "grid_rows": 18,
                    "grid_cols": 22,
                },
            ):
                result = client.set_motion_config(enabled=False)
                assert result is False


class TestHikvisionTools:
    def test_container_status_success(self):
        from tools.iot_hikvision import _hikvision_container_status

        with patch("tools.iot_hikvision.get_container_status") as mock:
            mock.return_value = {"running": True, "status": "running"}
            result = _hikvision_container_status()
            assert '"success": true' in result
            assert '"running": true' in result

    def test_container_logs_return_size(self):
        from tools.iot_hikvision import _hikvision_container_logs

        with patch("tools.iot_hikvision.get_container_logs") as mock:
            mock.return_value = "2026-06-01 Motion detected from Gate\n"
            result = _hikvision_container_logs(since="1h", tail=50)
            assert '"success": true' in result
            assert '"log_size_chars"' in result

    def test_check_vmd_isapi_dead(self):
        from tools.iot_hikvision import _hikvision_check_vmd

        with patch("tools.iot_hikvision.count_vmd_events") as mock:
            mock.return_value = {"vmd_count": 0, "isapi_healthy": False, "check_window": "4h"}
            result = _hikvision_check_vmd(since="4h")
            assert '"isapi_healthy": false' in result

    def test_check_vmd_isapi_alive(self):
        from tools.iot_hikvision import _hikvision_check_vmd

        with patch("tools.iot_hikvision.count_vmd_events") as mock:
            mock.return_value = {"vmd_count": 5, "isapi_healthy": True, "check_window": "4h"}
            result = _hikvision_check_vmd(since="4h")
            assert '"isapi_healthy": true' in result

    def test_restart_container_success(self):
        from tools.iot_hikvision import _hikvision_restart_container

        with patch("tools.iot_hikvision.restart_container") as mock:
            mock.return_value = {"success": True, "message": "restarted"}
            result = _hikvision_restart_container()
            assert '"success": true' in result

    def test_restart_container_error(self):
        from tools.iot_hikvision import _hikvision_restart_container

        with patch("tools.iot_hikvision.restart_container") as mock:
            mock.return_value = {"success": False, "message": "docker error"}
            result = _hikvision_restart_container()
            assert '"DOCKER_ERROR"' in result

    def test_device_info_success(self):
        from tools.iot_hikvision import _hikvision_device_info

        with patch("tools.iot_hikvision.create_isapi_client") as mock_factory:
            mock_client = MagicMock()
            mock_client.get_device_info.return_value = {
                "model": "DS-KV6113-WPE1(C)",
                "firmwareVersion": "V2.2.65",
            }
            mock_factory.return_value = mock_client
            result = _hikvision_device_info()
            assert '"DS-KV6113-WPE1(C)"' in result

    def test_device_info_missing_creds(self):
        from tools.iot_hikvision import _hikvision_device_info

        with patch("tools.iot_hikvision.create_isapi_client") as mock_factory:
            mock_factory.side_effect = ValueError("missing creds")
            result = _hikvision_device_info()
            assert '"MISSING_CREDENTIALS"' in result

    def test_get_event_config_success(self):
        from tools.iot_hikvision import _hikvision_get_event_config

        with patch("tools.iot_hikvision.create_isapi_client") as mock_factory:
            mock_client = MagicMock()
            mock_client.get_event_triggers.return_value = [
                {"event_type": "VMD", "notifications": [{"method": "center"}]},
                {"event_type": "videoloss", "notifications": [{"recurrence": "beginning"}]},
            ]
            mock_factory.return_value = mock_client
            result = _hikvision_get_event_config()
            assert '"success": true' in result
            assert '"count": 2' in result
            assert '"VMD"' in result

    def test_get_event_config_missing_creds(self):
        from tools.iot_hikvision import _hikvision_get_event_config

        with patch("tools.iot_hikvision.create_isapi_client") as mock_factory:
            mock_factory.side_effect = ValueError("missing creds")
            result = _hikvision_get_event_config()
            assert '"MISSING_CREDENTIALS"' in result

    def test_get_alarm_server_success(self):
        from tools.iot_hikvision import _hikvision_get_alarm_server

        with patch("tools.iot_hikvision.create_isapi_client") as mock_factory:
            mock_client = MagicMock()
            mock_client.get_alarm_server.return_value = {
                "url": "/api/hikvision",
                "port": 8123,
                "ip": "192.0.2.1",
            }
            mock_factory.return_value = mock_client
            result = _hikvision_get_alarm_server()
            assert '"success": true' in result
            assert '"alarm_server"' in result
            assert '"port": 8123' in result

    def test_get_alarm_server_internal_error(self):
        from tools.iot_hikvision import _hikvision_get_alarm_server

        with patch("tools.iot_hikvision.create_isapi_client") as mock_factory:
            mock_factory.side_effect = Exception("network error")
            result = _hikvision_get_alarm_server()
            assert '"INTERNAL_ERROR"' in result

    def test_snapshot_to_file_success(self, tmp_path):
        from tools.iot_hikvision import _hikvision_snapshot_to_file

        with patch("tools.iot_hikvision.create_isapi_client") as mock_factory:
            mock_client = MagicMock()
            mock_client.save_snapshot.return_value = {
                "saved": True,
                "size_bytes": 15000,
                "filepath": "/tmp/test.jpg",
                "format": "jpeg",
            }
            mock_factory.return_value = mock_client
            filepath = str(tmp_path / "doorbell.jpg")
            result = _hikvision_snapshot_to_file(filepath)
            assert '"success": true' in result
            assert '"saved": true' in result
            assert '"format": "jpeg"' in result

    def test_snapshot_to_file_validation_error(self):
        from tools.iot_hikvision import _hikvision_snapshot_to_file

        result = _hikvision_snapshot_to_file("")
        assert '"VALIDATION_ERROR"' in result

    def test_get_motion_config_success(self):
        from tools.iot_hikvision import _hikvision_get_motion_config

        with patch("tools.iot_hikvision.create_isapi_client") as mock_factory:
            mock_client = MagicMock()
            mock_client.get_motion_config.return_value = {
                "enabled": True,
                "sensitivity": 70,
                "grid_map": "0F0F",
                "grid_rows": 18,
                "grid_cols": 22,
            }
            mock_factory.return_value = mock_client
            result = _hikvision_get_motion_config()
            assert '"enabled": true' in result
            assert '"sensitivity": 70' in result

    def test_get_motion_config_error(self):
        from tools.iot_hikvision import _hikvision_get_motion_config

        with patch("tools.iot_hikvision.create_isapi_client") as mock_factory:
            mock_factory.side_effect = ValueError("Missing required env vars")
            result = _hikvision_get_motion_config()
            assert '"MISSING_CREDENTIALS"' in result

    def test_set_motion_detection_success(self):
        from tools.iot_hikvision import _hikvision_set_motion_detection

        with patch("tools.iot_hikvision.create_isapi_client") as mock_factory:
            mock_client = MagicMock()
            mock_client.set_motion_config.return_value = True
            mock_factory.return_value = mock_client
            result = _hikvision_set_motion_detection(enabled=True, sensitivity=80)
            assert '"success": true' in result
            assert '"enabled": true' in result
            assert '"sensitivity": 80' in result
            assert '"message"' in result

    def test_set_motion_detection_error(self):
        from tools.iot_hikvision import _hikvision_set_motion_detection

        with patch("tools.iot_hikvision.create_isapi_client") as mock_factory:
            mock_client = MagicMock()
            mock_client.set_motion_config.return_value = False
            mock_factory.return_value = mock_client
            result = _hikvision_set_motion_detection()
            assert '"ISAPI_ERROR"' in result

    def test_isapi_health_healthy(self):
        from tools.iot_hikvision import _hikvision_isapi_health

        with (
            patch("tools.iot_hikvision.get_container_status") as mock_status,
            patch("tools.iot_hikvision.count_vmd_events") as mock_vmd,
            patch("tools.iot_hikvision.count_call_events") as mock_calls,
        ):
            mock_status.return_value = {"running": True, "status": "running"}
            mock_vmd.return_value = {"vmd_count": 5, "isapi_healthy": True, "check_window": "4h"}
            mock_calls.return_value = {"call_count": 2, "has_calls": True, "check_window": "4h"}
            result = _hikvision_isapi_health(since="4h")
            assert '"overall": "healthy"' in result
            assert '"vmd_count": 5' in result
            assert '"call_count": 2' in result

    def test_isapi_health_degraded(self):
        from tools.iot_hikvision import _hikvision_isapi_health

        with (
            patch("tools.iot_hikvision.get_container_status") as mock_status,
            patch("tools.iot_hikvision.count_vmd_events") as mock_vmd,
            patch("tools.iot_hikvision.count_call_events") as mock_calls,
        ):
            mock_status.return_value = {"running": True, "status": "running"}
            mock_vmd.return_value = {"vmd_count": 0, "isapi_healthy": False, "check_window": "4h"}
            mock_calls.return_value = {"call_count": 0, "has_calls": False, "check_window": "4h"}
            result = _hikvision_isapi_health(since="4h")
            assert '"overall": "degraded"' in result
            assert "No VMD or call events" in result

    def test_isapi_health_down(self):
        from tools.iot_hikvision import _hikvision_isapi_health

        with (
            patch("tools.iot_hikvision.get_container_status") as mock_status,
            patch("tools.iot_hikvision.count_vmd_events") as mock_vmd,
            patch("tools.iot_hikvision.count_call_events") as mock_calls,
        ):
            mock_status.return_value = {"running": False, "status": "stopped"}
            mock_vmd.return_value = {"vmd_count": 0, "isapi_healthy": False, "check_window": "4h"}
            mock_calls.return_value = {"call_count": 0, "has_calls": False, "check_window": "4h"}
            result = _hikvision_isapi_health(since="4h")
            assert '"overall": "down"' in result

    def test_pipeline_diagnose_healthy(self):
        from tools.iot_hikvision import _hikvision_pipeline_diagnose

        with (
            patch("tools.iot_hikvision.get_container_status") as mock_status,
            patch("tools.iot_hikvision.get_container_logs") as mock_logs,
            patch("tools.iot_hikvision.os.path.isdir", return_value=True),
            patch(
                "tools.iot_hikvision.os.listdir",
                return_value=["2026-06-01_120000.jpg", "2026-06-01_120100.jpg"],
            ),
        ):
            mock_status.return_value = {"running": True, "status": "running"}
            mock_logs.return_value = (
                "Connected to doorbell: Gate type: VillaVTO\n"
                "Motion detected from Gate\n"
                "Doorbell ringing\n"
                "Invoking device trigger automation\n"
            )
            result = _hikvision_pipeline_diagnose()
            assert '"overall": "healthy"' in result
            assert '"authenticated": true' in result
            assert '"vmd_count": 1' in result

    def test_pipeline_diagnose_degraded(self):
        from tools.iot_hikvision import _hikvision_pipeline_diagnose

        with (
            patch("tools.iot_hikvision.get_container_status") as mock_status,
            patch("tools.iot_hikvision.get_container_logs") as mock_logs,
        ):
            mock_status.return_value = {"running": False, "status": "stopped"}
            mock_logs.return_value = ""
            result = _hikvision_pipeline_diagnose()
            assert '"overall": "degraded"' in result
            assert "Cannot start" in result


class TestHikvisionToolRegistration:
    @pytest.fixture
    def mcp(self, mock_mcp):
        from tools.iot_hikvision import register_hikvision_tools

        with patch("tools.iot_hikvision._docker_available", return_value=True):
            register_hikvision_tools(mock_mcp)
        return mock_mcp

    def test_all_fourteen_tools_registered(self, mcp):
        hik_tools = [n for n in mcp._tools if n.startswith("hikvision_")]
        assert len(hik_tools) == 14

    def test_eight_isapi_tools_when_docker_unavailable(self):
        from tools.iot_hikvision import register_hikvision_tools

        mcp = MagicMock()
        mcp._tools = {}

        def tool_decorator(*args, **kwargs):
            def wrapper(func):
                tool_name = kwargs.get("name", func.__name__)
                mcp._tools[tool_name] = func
                return func

            if len(args) == 1 and callable(args[0]) and not kwargs:
                mcp._tools[args[0].__name__] = args[0]
                return args[0]

            return wrapper

        mcp.tool = tool_decorator
        mcp.get_tool = lambda name: mcp._tools.get(name)

        with patch("tools.iot_hikvision._docker_available", return_value=False):
            register_hikvision_tools(mcp)

        hik_tools = [n for n in mcp._tools if n.startswith("hikvision_")]
        assert len(hik_tools) == 8
        # Docker tools must NOT be registered
        assert "hikvision_container_status" not in mcp._tools
        assert "hikvision_container_logs" not in mcp._tools
        assert "hikvision_check_vmd" not in mcp._tools
        assert "hikvision_restart_container" not in mcp._tools
        assert "hikvision_isapi_health" not in mcp._tools
        assert "hikvision_pipeline_diagnose" not in mcp._tools
        # ISAPI tools must be registered
        assert "hikvision_take_snapshot" in mcp._tools
        assert "hikvision_device_info" in mcp._tools

    def test_container_status_tool(self, mcp):
        with patch(
            "tools.iot_hikvision._hikvision_container_status", return_value=_json({"running": True})
        ):
            result = mcp.get_tool("hikvision_container_status")()
            assert json.loads(result)["success"] is True

    def test_container_logs_tool(self, mcp):
        with patch(
            "tools.iot_hikvision._hikvision_container_logs",
            return_value=_json({"logs": "test log"}),
        ):
            result = mcp.get_tool("hikvision_container_logs")(since="1h", tail=10)
            assert json.loads(result)["success"] is True

    def test_check_vmd_tool(self, mcp):
        with patch(
            "tools.iot_hikvision._hikvision_check_vmd", return_value=_json({"isapi_healthy": True})
        ):
            result = mcp.get_tool("hikvision_check_vmd")()
            assert json.loads(result)["success"] is True

    def test_restart_container_write_guard(self, mcp):
        with patch(
            "tools.iot_hikvision.check_write_enabled", side_effect=Exception("write disabled")
        ):
            result = mcp.get_tool("hikvision_restart_container")()
            assert json.loads(result)["success"] is False

    def test_open_gate_write_guard(self, mcp):
        with patch(
            "tools.iot_hikvision.check_write_enabled", side_effect=Exception("write disabled")
        ):
            result = mcp.get_tool("hikvision_open_gate")(door_id=1)
            assert json.loads(result)["success"] is False

    def test_device_info_tool(self, mcp):
        with patch(
            "tools.iot_hikvision._hikvision_device_info",
            return_value=_json({"model": "DS-KV6113-WPE1(C)"}),
        ):
            result = mcp.get_tool("hikvision_device_info")()
            assert json.loads(result)["success"] is True

    def test_get_event_config_tool(self, mcp):
        with patch(
            "tools.iot_hikvision._hikvision_get_event_config",
            return_value=_json({"triggers": [], "count": 0}),
        ):
            result = mcp.get_tool("hikvision_get_event_config")()
            assert json.loads(result)["success"] is True

    def test_get_alarm_server_tool(self, mcp):
        with patch(
            "tools.iot_hikvision._hikvision_get_alarm_server",
            return_value=_json({"alarm_server": {"port": 8123}}),
        ):
            result = mcp.get_tool("hikvision_get_alarm_server")()
            assert json.loads(result)["success"] is True

    def test_get_motion_config_tool(self, mcp):
        with patch(
            "tools.iot_hikvision._hikvision_get_motion_config",
            return_value=_json({"enabled": True, "sensitivity": 70}),
        ):
            result = mcp.get_tool("hikvision_get_motion_config")()
            assert json.loads(result)["success"] is True

    def test_snapshot_to_file_tool(self, mcp):
        with patch(
            "tools.iot_hikvision._hikvision_snapshot_to_file",
            return_value=_json({"saved": True}),
        ):
            result = mcp.get_tool("hikvision_snapshot_to_file")(filepath="/tmp/test.jpg")
            assert json.loads(result)["success"] is True

    def test_exception_handler(self, mcp):
        with patch(
            "tools.iot_hikvision._hikvision_container_status", side_effect=Exception("BOOM")
        ):
            result = mcp.get_tool("hikvision_container_status")()
            parsed = json.loads(result)
            assert parsed["success"] is False
            assert "BOOM" in parsed["error"]["message"]


class TestHikvisionDockerClientDeep:
    def test_decode_chunked_normal(self):
        from tools.hikvision.docker_client import _decode_chunked

        assert _decode_chunked("5\r\nhello\r\n0\r\n\r\n") == "hello"

    def test_decode_chunked_empty(self):
        from tools.hikvision.docker_client import _decode_chunked

        assert _decode_chunked("") == ""

    def test_decode_chunked_no_chunks(self):
        from tools.hikvision.docker_client import _decode_chunked

        assert _decode_chunked("plain text") == "plain text"

    def test_get_container_status_invalid_json(self):
        from tools.hikvision.docker_client import get_container_status

        with patch("tools.hikvision.docker_client._docker_request") as mock_req:
            mock_req.return_value = (200, "not json")
            result = get_container_status()
            assert result["running"] is False

    def test_get_container_logs_error(self):
        from tools.hikvision.docker_client import get_container_logs

        with patch("tools.hikvision.docker_client._docker_request") as mock_req:
            mock_req.return_value = (500, "server error")
            result = get_container_logs(since="1h")
            assert "HTTP 500" in result

    def test_get_container_logs_unreachable(self):
        from tools.hikvision.docker_client import get_container_logs

        with patch("tools.hikvision.docker_client._docker_request") as mock_req:
            mock_req.return_value = None
            result = get_container_logs(since="1h")
            assert "unreachable" in result.lower()

    def test_restart_container_unreachable(self):
        from tools.hikvision.docker_client import restart_container

        with patch("tools.hikvision.docker_client._docker_request") as mock_req:
            mock_req.return_value = None
            result = restart_container()
            assert result["success"] is False

    def test_count_vmd_events_direct(self):
        from tools.hikvision.docker_client import count_vmd_events

        with patch("tools.hikvision.docker_client.get_container_logs") as mock_logs:
            mock_logs.return_value = "2026-06-01 Motion detected from Gate\n"
            result = count_vmd_events(since="4h")
            assert result["vmd_count"] == 1


FAKE_ALARM_SERVER_XML = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<HttpHostNotificationList xmlns="http://www.isapi.org/ver20/XMLSchema">'
    "<HttpHostNotification>"
    "<id>1</id>"
    "<url>/api/hikvision</url>"
    "<protocolType>HTTP</protocolType>"
    "<ipAddress>192.0.2.1</ipAddress>"
    "<portNo>8123</portNo>"
    "<authentication>none</authentication>"
    "</HttpHostNotification>"
    "</HttpHostNotificationList>"
)

FAKE_ALARM_SERVER_EMPTY_XML = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<HttpHostNotificationList xmlns="http://www.isapi.org/ver20/XMLSchema"/>'
)


class TestHikvisionISAPIClientDeep:
    """Additional ISAPI client tests for uncovered edge cases."""

    def test_get_alarm_server_success(self):
        from tools.hikvision.isapi_client import HikvisionISAPIClient

        with patch("tools.hikvision.isapi_client.requests.Session") as MockSession:
            mock_resp = MagicMock(status_code=200, text=FAKE_ALARM_SERVER_XML)
            MockSession.return_value.get.return_value = mock_resp
            client = HikvisionISAPIClient(FAKE_HOST, FAKE_USER, FAKE_PASS)
            result = client.get_alarm_server()
            assert result is not None
            assert result["url"] == "/api/hikvision"
            assert result["port"] == 8123
            assert result["ip"] == "192.0.2.1"
            assert result["protocol"] == "HTTP"
            assert result["auth_method"] == "none"

    def test_get_alarm_server_not_configured(self):
        from tools.hikvision.isapi_client import HikvisionISAPIClient

        with patch("tools.hikvision.isapi_client.requests.Session") as MockSession:
            mock_resp = MagicMock(status_code=200, text=FAKE_ALARM_SERVER_EMPTY_XML)
            MockSession.return_value.get.return_value = mock_resp
            client = HikvisionISAPIClient(FAKE_HOST, FAKE_USER, FAKE_PASS)
            result = client.get_alarm_server()
            assert result is None

    def test_ping_reachable(self):
        from tools.hikvision.isapi_client import HikvisionISAPIClient

        with patch("tools.hikvision.isapi_client.requests.Session") as MockSession:
            mock_resp = MagicMock(status_code=302)
            MockSession.return_value.get.return_value = mock_resp
            client = HikvisionISAPIClient(FAKE_HOST, FAKE_USER, FAKE_PASS)
            assert client.ping() is True

    def test_ping_unreachable(self):
        from tools.hikvision.isapi_client import HikvisionISAPIClient

        with patch("tools.hikvision.isapi_client.requests.Session") as MockSession:
            MockSession.return_value.get.side_effect = Exception("timeout")
            client = HikvisionISAPIClient(FAKE_HOST, FAKE_USER, FAKE_PASS)
            assert client.ping() is False

    def test_get_device_info_xml_parse_failure(self):
        from tools.hikvision.isapi_client import HikvisionISAPIClient

        with patch("tools.hikvision.isapi_client.requests.Session") as MockSession:
            mock_resp = MagicMock(status_code=200, text="not valid xml ><")
            MockSession.return_value.get.return_value = mock_resp
            client = HikvisionISAPIClient(FAKE_HOST, FAKE_USER, FAKE_PASS)
            assert client.get_device_info() is None

    def test_get_snapshot_http_error(self):
        from tools.hikvision.isapi_client import HikvisionISAPIClient

        with patch("tools.hikvision.isapi_client.requests.Session") as MockSession:
            mock_resp = MagicMock(status_code=500)
            mock_resp.raise_for_status.side_effect = Exception("500")
            MockSession.return_value.get.return_value = mock_resp
            client = HikvisionISAPIClient(FAKE_HOST, FAKE_USER, FAKE_PASS)
            assert client.get_snapshot() is None

    def test_create_isapi_client_missing_creds(self):
        from tools.hikvision.isapi_client import create_isapi_client

        with (
            patch("tools.hikvision.isapi_client.HIKVISION_DOORBELL_USER", ""),
            patch("tools.hikvision.isapi_client.HIKVISION_DOORBELL_PASSWORD", ""),
        ):
            try:
                create_isapi_client()
                assert False, "Should raise ValueError"
            except ValueError as exc:
                assert "HIKVISION_DOORBELL_USER" in str(exc)

    def test_save_snapshot_success(self, tmp_path):
        from tools.hikvision.isapi_client import HikvisionISAPIClient

        with patch("tools.hikvision.isapi_client.requests.Session") as _:
            client = HikvisionISAPIClient(FAKE_HOST, FAKE_USER, FAKE_PASS)
            client.get_snapshot = MagicMock(return_value=b"fake_jpeg_bytes")
            filepath = str(tmp_path / "test.jpg")
            result = client.save_snapshot(filepath=filepath)
            assert result["saved"] is True
            assert result["size_bytes"] == 15
            assert result["filepath"].endswith("test.jpg")
            assert result["format"] == "jpeg"
            client.get_snapshot.assert_called_once_with(channel=1)

    def test_save_snapshot_failure(self):
        from tools.hikvision.isapi_client import HikvisionISAPIClient

        with patch("tools.hikvision.isapi_client.requests.Session") as _:
            client = HikvisionISAPIClient(FAKE_HOST, FAKE_USER, FAKE_PASS)
            client.get_snapshot = MagicMock(return_value=None)
            result = client.save_snapshot(filepath="/tmp/nonexistent/test.jpg")
            assert result["saved"] is False
            assert "error" in result
            assert "Failed to capture" in result["error"]


class TestHikvisionErrorPaths:
    """Error-path tests for Hikvision tool functions to hit uncovered branches."""

    # _hikvision_device_info error paths

    def test_device_info_isapi_error(self):
        from tools.iot_hikvision import _hikvision_device_info

        with patch("tools.iot_hikvision.create_isapi_client") as mock_create:
            mock_client = MagicMock()
            mock_client.get_device_info.return_value = None
            mock_create.return_value = mock_client
            result = _hikvision_device_info()
        data = json.loads(result)
        assert data["success"] is False
        assert data["error"]["code"] == "ISAPI_ERROR"

    def test_device_info_internal_error(self):
        from tools.iot_hikvision import _hikvision_device_info

        with patch("tools.iot_hikvision.create_isapi_client") as mock_create:
            mock_create.side_effect = Exception("network timeout")
            result = _hikvision_device_info()
        data = json.loads(result)
        assert data["success"] is False
        assert data["error"]["code"] == "INTERNAL_ERROR"

    # _hikvision_take_snapshot error paths

    def test_take_snapshot_isapi_error(self):
        from tools.iot_hikvision import _hikvision_take_snapshot

        with patch("tools.iot_hikvision.create_isapi_client") as mock_create:
            mock_client = MagicMock()
            mock_client.get_snapshot.return_value = None
            mock_create.return_value = mock_client
            result = _hikvision_take_snapshot()
        data = json.loads(result)
        assert data["success"] is False
        assert data["error"]["code"] == "ISAPI_ERROR"

    def test_take_snapshot_internal_error(self):
        from tools.iot_hikvision import _hikvision_take_snapshot

        with patch("tools.iot_hikvision.create_isapi_client") as mock_create:
            mock_create.side_effect = Exception("socket timeout")
            result = _hikvision_take_snapshot()
        data = json.loads(result)
        assert data["success"] is False
        assert data["error"]["code"] == "INTERNAL_ERROR"

    # _hikvision_open_gate error paths

    def test_open_gate_isapi_error(self):
        from tools.iot_hikvision import _hikvision_open_gate

        with patch("tools.iot_hikvision.create_isapi_client") as mock_create:
            mock_client = MagicMock()
            mock_client.open_door.return_value = False
            mock_create.return_value = mock_client
            result = _hikvision_open_gate(door_id=1)
        data = json.loads(result)
        assert data["success"] is False
        assert data["error"]["code"] == "ISAPI_ERROR"

    def test_open_gate_missing_creds(self):
        from tools.iot_hikvision import _hikvision_open_gate

        with patch("tools.iot_hikvision.create_isapi_client") as mock_create:
            mock_create.side_effect = ValueError("Missing creds")
            result = _hikvision_open_gate(door_id=1)
        data = json.loads(result)
        assert data["success"] is False
        assert data["error"]["code"] == "MISSING_CREDENTIALS"

    def test_open_gate_internal_error(self):
        from tools.iot_hikvision import _hikvision_open_gate

        with patch("tools.iot_hikvision.create_isapi_client") as mock_create:
            mock_create.side_effect = Exception("connection refused")
            result = _hikvision_open_gate(door_id=1)
        data = json.loads(result)
        assert data["success"] is False
        assert data["error"]["code"] == "INTERNAL_ERROR"

    # _hikvision_get_motion_config error paths

    def test_get_motion_config_isapi_error(self):
        from tools.iot_hikvision import _hikvision_get_motion_config

        with patch("tools.iot_hikvision.create_isapi_client") as mock_create:
            mock_client = MagicMock()
            mock_client.get_motion_config.return_value = None
            mock_create.return_value = mock_client
            result = _hikvision_get_motion_config()
        data = json.loads(result)
        assert data["success"] is False
        assert data["error"]["code"] == "ISAPI_ERROR"

    def test_get_motion_config_internal_error(self):
        from tools.iot_hikvision import _hikvision_get_motion_config

        with patch("tools.iot_hikvision.create_isapi_client") as mock_create:
            mock_create.side_effect = Exception("ISAPI down")
            result = _hikvision_get_motion_config()
        data = json.loads(result)
        assert data["success"] is False
        assert data["error"]["code"] == "INTERNAL_ERROR"

    # _hikvision_set_motion_detection error paths

    def test_set_motion_detection_sensitivity_negative(self):
        from tools.iot_hikvision import _hikvision_set_motion_detection

        with patch("tools.iot_hikvision.create_isapi_client"):
            result = _hikvision_set_motion_detection(sensitivity=-1)
        data = json.loads(result)
        assert data["success"] is False
        assert data["error"]["code"] == "VALIDATION_ERROR"

    def test_set_motion_detection_sensitivity_too_high(self):
        from tools.iot_hikvision import _hikvision_set_motion_detection

        with patch("tools.iot_hikvision.create_isapi_client"):
            result = _hikvision_set_motion_detection(sensitivity=101)
        data = json.loads(result)
        assert data["success"] is False
        assert data["error"]["code"] == "VALIDATION_ERROR"

    def test_set_motion_detection_missing_creds(self):
        from tools.iot_hikvision import _hikvision_set_motion_detection

        with patch("tools.iot_hikvision.create_isapi_client") as mock_create:
            mock_create.side_effect = ValueError("Missing env vars")
            result = _hikvision_set_motion_detection(enabled=True)
        data = json.loads(result)
        assert data["success"] is False
        assert data["error"]["code"] == "MISSING_CREDENTIALS"

    def test_set_motion_detection_internal_error(self):
        from tools.iot_hikvision import _hikvision_set_motion_detection

        with patch("tools.iot_hikvision.create_isapi_client") as mock_create:
            mock_create.side_effect = Exception("unexpected failure")
            result = _hikvision_set_motion_detection(enabled=False)
        data = json.loads(result)
        assert data["success"] is False
        assert data["error"]["code"] == "INTERNAL_ERROR"

    # _hikvision_get_event_config error paths

    def test_get_event_config_isapi_error(self):
        from tools.iot_hikvision import _hikvision_get_event_config

        with patch("tools.iot_hikvision.create_isapi_client") as mock_create:
            mock_client = MagicMock()
            mock_client.get_event_triggers.return_value = None
            mock_create.return_value = mock_client
            result = _hikvision_get_event_config()
        data = json.loads(result)
        assert data["success"] is False
        assert data["error"]["code"] == "ISAPI_ERROR"

    def test_get_event_config_internal_error(self):
        from tools.iot_hikvision import _hikvision_get_event_config

        with patch("tools.iot_hikvision.create_isapi_client") as mock_create:
            mock_create.side_effect = Exception("timeout")
            result = _hikvision_get_event_config()
        data = json.loads(result)
        assert data["success"] is False
        assert data["error"]["code"] == "INTERNAL_ERROR"

    # _hikvision_get_alarm_server error paths

    def test_get_alarm_server_isapi_error(self):
        from tools.iot_hikvision import _hikvision_get_alarm_server

        with patch("tools.iot_hikvision.create_isapi_client") as mock_create:
            mock_client = MagicMock()
            mock_client.get_alarm_server.return_value = None
            mock_create.return_value = mock_client
            result = _hikvision_get_alarm_server()
        data = json.loads(result)
        assert data["success"] is False
        assert data["error"]["code"] == "ISAPI_ERROR"

    def test_get_alarm_server_missing_creds(self):
        from tools.iot_hikvision import _hikvision_get_alarm_server

        with patch("tools.iot_hikvision.create_isapi_client") as mock_create:
            mock_create.side_effect = ValueError("Missing credentials")
            result = _hikvision_get_alarm_server()
        data = json.loads(result)
        assert data["success"] is False
        assert data["error"]["code"] == "MISSING_CREDENTIALS"

    # _hikvision_snapshot_to_file error paths

    def test_snapshot_to_file_isapi_error(self):
        from tools.iot_hikvision import _hikvision_snapshot_to_file

        with patch("tools.iot_hikvision.create_isapi_client") as mock_create:
            mock_client = MagicMock()
            mock_client.save_snapshot.return_value = {
                "saved": False,
                "error": "disk full",
            }
            mock_create.return_value = mock_client
            result = _hikvision_snapshot_to_file("/tmp/test.jpg")
        data = json.loads(result)
        assert data["success"] is False
        assert data["error"]["code"] == "ISAPI_ERROR"

    def test_snapshot_to_file_missing_creds(self):
        from tools.iot_hikvision import _hikvision_snapshot_to_file

        with patch("tools.iot_hikvision.create_isapi_client") as mock_create:
            mock_create.side_effect = ValueError("Missing creds")
            result = _hikvision_snapshot_to_file("/tmp/test.jpg")
        data = json.loads(result)
        assert data["success"] is False
        assert data["error"]["code"] == "MISSING_CREDENTIALS"

    def test_snapshot_to_file_internal_error(self):
        from tools.iot_hikvision import _hikvision_snapshot_to_file

        with patch("tools.iot_hikvision.create_isapi_client") as mock_create:
            mock_create.side_effect = Exception("permission denied")
            result = _hikvision_snapshot_to_file("/tmp/test.jpg")
        data = json.loads(result)
        assert data["success"] is False
        assert data["error"]["code"] == "INTERNAL_ERROR"

    # _hikvision_isapi_health error paths

    def test_isapi_health_vmd_dead_calls_ok(self):
        from tools.iot_hikvision import _hikvision_isapi_health

        with (
            patch("tools.iot_hikvision.get_container_status") as mock_status,
            patch("tools.iot_hikvision.count_vmd_events") as mock_vmd,
            patch("tools.iot_hikvision.count_call_events") as mock_calls,
        ):
            mock_status.return_value = {"running": True, "status": "running"}
            mock_vmd.return_value = {
                "vmd_count": 0,
                "isapi_healthy": False,
                "check_window": "4h",
            }
            mock_calls.return_value = {
                "call_count": 3,
                "has_calls": True,
                "check_window": "4h",
            }
            result = _hikvision_isapi_health(since="4h")
        data = json.loads(result)
        assert data["data"]["overall"] == "healthy"
        assert "VMD event pipeline is dead" in result

    def test_isapi_health_value_error(self):
        from tools.iot_hikvision import _hikvision_isapi_health

        with patch(
            "tools.iot_hikvision.get_container_status",
            side_effect=ValueError("config error"),
        ):
            result = _hikvision_isapi_health(since="4h")
        data = json.loads(result)
        assert data["success"] is False
        assert data["error"]["code"] == "MISSING_CREDENTIALS"

    def test_isapi_health_internal_error(self):
        from tools.iot_hikvision import _hikvision_isapi_health

        with patch(
            "tools.iot_hikvision.get_container_status",
            side_effect=Exception("docker daemon down"),
        ):
            result = _hikvision_isapi_health(since="4h")
        data = json.loads(result)
        assert data["success"] is False
        assert data["error"]["code"] == "INTERNAL_ERROR"

    # _hikvision_pipeline_diagnose error paths

    def test_pipeline_diagnose_oserror_handling(self):
        from tools.iot_hikvision import _hikvision_pipeline_diagnose

        with (
            patch("tools.iot_hikvision.get_container_status") as mock_status,
            patch("tools.iot_hikvision.get_container_logs") as mock_logs,
            patch("tools.iot_hikvision.os.path.isdir", return_value=True),
            patch(
                "tools.iot_hikvision.os.listdir",
                side_effect=OSError("permission error"),
            ),
        ):
            mock_status.return_value = {"running": True, "status": "running"}
            mock_logs.return_value = (
                "Connected to doorbell: Gate type: VillaVTO\n"
                "Motion detected from Gate\n"
                "Doorbell ringing\n"
                "Invoking device trigger automation\n"
            )
            result = _hikvision_pipeline_diagnose()
        data = json.loads(result)
        assert data["data"]["overall"] == "degraded"
        assert any("No snapshots" in i for i in data["data"]["issues"])

    def test_pipeline_diagnose_vmd_stopped_calls_ok(self):
        from tools.iot_hikvision import _hikvision_pipeline_diagnose

        with (
            patch("tools.iot_hikvision.get_container_status") as mock_status,
            patch("tools.iot_hikvision.get_container_logs") as mock_logs,
            patch("tools.iot_hikvision.os.path.isdir", return_value=True),
            patch("tools.iot_hikvision.os.listdir", return_value=[]),
        ):
            mock_status.return_value = {"running": True, "status": "running"}
            mock_logs.return_value = "Doorbell ringing\n"
            result = _hikvision_pipeline_diagnose()
        data = json.loads(result)
        assert data["data"]["overall"] == "degraded"
        assert any("VMD events stopped" in i for i in data["data"]["issues"])

    def test_pipeline_diagnose_value_error(self):
        from tools.iot_hikvision import _hikvision_pipeline_diagnose

        with patch(
            "tools.iot_hikvision.get_container_status",
            side_effect=ValueError("bad config"),
        ):
            result = _hikvision_pipeline_diagnose()
        data = json.loads(result)
        assert data["success"] is False
        assert data["error"]["code"] == "MISSING_CREDENTIALS"

    def test_pipeline_diagnose_internal_error(self):
        from tools.iot_hikvision import _hikvision_pipeline_diagnose

        with patch(
            "tools.iot_hikvision.get_container_status",
            side_effect=Exception("docker error"),
        ):
            result = _hikvision_pipeline_diagnose()
        data = json.loads(result)
        assert data["success"] is False
        assert data["error"]["code"] == "INTERNAL_ERROR"

    def test_take_snapshot_success(self):
        from tools.iot_hikvision import _hikvision_take_snapshot

        with patch("tools.iot_hikvision.create_isapi_client") as mock_create:
            mock_client = MagicMock()
            mock_client.get_snapshot.return_value = b"fake_jpeg_bytes"
            mock_create.return_value = mock_client
            result = _hikvision_take_snapshot()
        data = json.loads(result)
        assert data["success"] is True
        assert data["data"]["format"] == "jpeg"
        assert "base64" in data["data"]

    def test_take_snapshot_missing_creds(self):
        from tools.iot_hikvision import _hikvision_take_snapshot

        with patch("tools.iot_hikvision.create_isapi_client") as mock_create:
            mock_create.side_effect = ValueError("Missing creds")
            result = _hikvision_take_snapshot()
        data = json.loads(result)
        assert data["success"] is False
        assert data["error"]["code"] == "MISSING_CREDENTIALS"

    def test_open_gate_success(self):
        from tools.iot_hikvision import _hikvision_open_gate

        with patch("tools.iot_hikvision.create_isapi_client") as mock_create:
            mock_client = MagicMock()
            mock_client.open_door.return_value = True
            mock_create.return_value = mock_client
            result = _hikvision_open_gate(door_id=1)
        data = json.loads(result)
        assert data["success"] is True
        assert data["data"]["opened"] is True
        assert data["data"]["door_id"] == 1
