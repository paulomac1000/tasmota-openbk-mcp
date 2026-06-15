"""Unit tests for tools/http_session.py -- Generic IoT device HTTP client."""

import urllib.parse
from unittest.mock import MagicMock, patch

import pytest
import requests

from tools.http_session import (
    DeviceConnectionError,
    _build_url,
    _DeviceHttpSession,
)

pytestmark = pytest.mark.unit


# =============================================================================
# A. DeviceConnectionError
# =============================================================================


class TestDeviceConnectionError:
    """Tests for the DeviceConnectionError exception class."""

    def test_instantiation_with_message(self):
        """DeviceConnectionError can be instantiated with a message."""
        exc = DeviceConnectionError("Something went wrong")
        assert str(exc) == "Something went wrong"

    def test_is_subclass_of_exception(self):
        """DeviceConnectionError is a subclass of Exception."""
        assert issubclass(DeviceConnectionError, Exception)

    def test_can_be_raised_and_caught(self):
        """DeviceConnectionError can be raised and caught."""
        with pytest.raises(DeviceConnectionError, match="Test error"):
            raise DeviceConnectionError("Test error")


# =============================================================================
# B. _DeviceHttpSession constructor
# =============================================================================


class TestDeviceHttpSessionConstructor:
    """Tests for _DeviceHttpSession.__init__."""

    @patch("tools.http_session.requests.Session")
    def test_creates_session_with_adapter_mounts(self, mock_session_cls):
        """Constructor creates requests.Session and mounts HTTPAdapter."""
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session

        _DeviceHttpSession("http://192.168.1.100")

        mock_session_cls.assert_called_once()
        assert mock_session.mount.call_count == 2
        mock_session.mount.assert_any_call("http://", mock_session.mount.call_args_list[0][0][1])
        mock_session.mount.assert_any_call("https://", mock_session.mount.call_args_list[1][0][1])

    @patch("tools.http_session.requests.Session")
    def test_strips_trailing_slash_from_base_url(self, mock_session_cls):
        """Constructor strips trailing slash from base_url."""
        session = _DeviceHttpSession("http://192.168.1.100/")
        assert session._base_url == "http://192.168.1.100"

    @patch("tools.http_session.requests.Session")
    def test_uses_default_timeout(self, mock_session_cls):
        """Constructor sets default_timeout to given value or 10."""
        session = _DeviceHttpSession("http://192.168.1.100")
        assert session._default_timeout == 10

        session2 = _DeviceHttpSession("http://192.168.1.100", default_timeout=30)
        assert session2._default_timeout == 30


# =============================================================================
# C. _DeviceHttpSession._resolve_timeout
# =============================================================================


class TestResolveTimeout:
    """Tests for _DeviceHttpSession._resolve_timeout."""

    def test_returns_explicit_timeout_if_provided(self):
        """Returns the explicit timeout value when provided."""
        session = _DeviceHttpSession.__new__(_DeviceHttpSession)
        session._default_timeout = 10

        result = session._resolve_timeout(5)
        assert result == 5

    def test_falls_back_to_default_timeout_if_none(self):
        """Returns default_timeout when timeout is None."""
        session = _DeviceHttpSession.__new__(_DeviceHttpSession)
        session._default_timeout = 10

        result = session._resolve_timeout(None)
        assert result == 10


# =============================================================================
# D. _DeviceHttpSession.get_json
# =============================================================================


class TestGetJson:
    """Tests for _DeviceHttpSession.get_json."""

    @patch("tools.http_session.requests.Session")
    def test_success_returns_parsed_json(self, mock_session_cls):
        """Successful GET with JSON response returns parsed dict."""
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"key": "value"}
        mock_session.get.return_value = mock_resp

        session = _DeviceHttpSession("http://192.168.1.100")
        result = session.get_json("/test")

        assert result == {"key": "value"}
        mock_session.get.assert_called_once_with(
            "http://192.168.1.100/test", params=None, timeout=10
        )

    @patch("tools.http_session.requests.Session")
    def test_success_with_custom_params_and_timeout(self, mock_session_cls):
        """get_json passes params and timeout through to session.get."""
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = [1, 2, 3]
        mock_session.get.return_value = mock_resp

        session = _DeviceHttpSession("http://192.168.1.100")
        result = session.get_json("/test", params={"a": "b"}, timeout=5)

        assert result == [1, 2, 3]
        mock_session.get.assert_called_once_with(
            "http://192.168.1.100/test", params={"a": "b"}, timeout=5
        )

    @patch("tools.http_session.requests.Session")
    def test_timeout_raises_device_connection_error(self, mock_session_cls):
        """Timeout raises DeviceConnectionError with 'Connection timed out'."""
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session
        mock_session.get.side_effect = requests.exceptions.Timeout()

        session = _DeviceHttpSession("http://192.168.1.100")

        with pytest.raises(DeviceConnectionError, match="Connection timed out"):
            session.get_json("/test")

    @patch("tools.http_session.requests.Session")
    def test_connection_error_raises_device_connection_error(self, mock_session_cls):
        """ConnectionError raises DeviceConnectionError with 'Connection failed'."""
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session
        mock_session.get.side_effect = requests.exceptions.ConnectionError("Connection refused")

        session = _DeviceHttpSession("http://192.168.1.100")

        with pytest.raises(DeviceConnectionError, match="Connection failed"):
            session.get_json("/test")

    @patch("tools.http_session.requests.Session")
    def test_http_404_raises_device_connection_error(self, mock_session_cls):
        """HTTP 404 response raises DeviceConnectionError with status and body."""
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session

        mock_resp = MagicMock()
        mock_resp.status_code = 404
        mock_resp.text = "Not Found"
        http_error = requests.exceptions.HTTPError(response=mock_resp)
        mock_session.get.return_value = mock_resp
        mock_resp.raise_for_status.side_effect = http_error

        session = _DeviceHttpSession("http://192.168.1.100")

        with pytest.raises(DeviceConnectionError, match="HTTP 404"):
            session.get_json("/test")

    @patch("tools.http_session.requests.Session")
    def test_generic_request_exception_raises_device_connection_error(self, mock_session_cls):
        """Generic RequestException raises DeviceConnectionError."""
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session
        mock_session.get.side_effect = requests.exceptions.RequestException("Something broke")

        session = _DeviceHttpSession("http://192.168.1.100")

        with pytest.raises(DeviceConnectionError, match="Request error"):
            session.get_json("/test")


# =============================================================================
# E. _DeviceHttpSession.get_form
# =============================================================================


class TestGetForm:
    """Tests for _DeviceHttpSession.get_form."""

    @patch("tools.http_session.requests.Session")
    def test_success_returns_raw_text(self, mock_session_cls):
        """Successful GET returns raw text response."""
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "<html><body>Form</body></html>"
        mock_session.get.return_value = mock_resp

        session = _DeviceHttpSession("http://192.168.1.100")
        result = session.get_form("/cfg_name")

        assert result == "<html><body>Form</body></html>"
        mock_session.get.assert_called_once_with(
            "http://192.168.1.100/cfg_name", params=None, timeout=10
        )

    @patch("tools.http_session.requests.Session")
    def test_timeout_raises_device_connection_error(self, mock_session_cls):
        """Timeout raises DeviceConnectionError."""
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session
        mock_session.get.side_effect = requests.exceptions.Timeout()

        session = _DeviceHttpSession("http://192.168.1.100")

        with pytest.raises(DeviceConnectionError, match="Connection timed out"):
            session.get_form("/cfg_name")

    @patch("tools.http_session.requests.Session")
    def test_connection_error_raises_device_connection_error(self, mock_session_cls):
        """ConnectionError raises DeviceConnectionError."""
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session
        mock_session.get.side_effect = requests.exceptions.ConnectionError("Connection refused")

        session = _DeviceHttpSession("http://192.168.1.100")

        with pytest.raises(DeviceConnectionError, match="Connection failed"):
            session.get_form("/cfg_name")

    @patch("tools.http_session.requests.Session")
    def test_http_500_raises_device_connection_error(self, mock_session_cls):
        """HTTP 500 response raises DeviceConnectionError."""
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session

        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.text = "Internal Server Error"
        http_error = requests.exceptions.HTTPError(response=mock_resp)
        mock_session.get.return_value = mock_resp
        mock_resp.raise_for_status.side_effect = http_error

        session = _DeviceHttpSession("http://192.168.1.100")

        with pytest.raises(DeviceConnectionError, match="HTTP 500"):
            session.get_form("/cfg_name")


# =============================================================================
# F. _build_url -- OpenBK endpoints
# =============================================================================


class TestBuildUrlOpenBK:
    """Tests for _build_url with device_type='openbk'."""

    def test_get_full_info(self):
        """openbk get_full_info returns Status 0 URL."""
        path, dtype = _build_url("openbk", "get_full_info")
        assert path == "/cm?cmnd=Status%200"
        assert dtype == "openbk"

    def test_execute_command(self):
        """openbk execute_command returns URL with encoded command."""
        path, dtype = _build_url("openbk", "execute_command", command="Power1 ON")
        assert path == "/cm?cmnd=Power1%20ON"
        assert dtype == "openbk"

    def test_execute_command_empty(self):
        """openbk execute_command with no command returns URL with empty cmnd."""
        path, dtype = _build_url("openbk", "execute_command")
        assert path == "/cm?cmnd="
        assert dtype == "openbk"

    def test_set_flags_zero(self):
        """openbk set_flags with flags=0 returns only setFlags=1."""
        path, dtype = _build_url("openbk", "set_flags", flags=0)
        assert path == "/cfg_generic?setFlags=1"
        assert dtype == "openbk"

    def test_set_flags_compound(self):
        """openbk set_flags with flags=134218820 generates correct flag params.

        134218820 = 2^27 + 2^10 + 2^6 + 2^2 → flags 2, 6, 10, 27.
        Total 5 query params: 4 flag bits + setFlags=1.
        """
        path, dtype = _build_url("openbk", "set_flags", flags=134218820)
        assert dtype == "openbk"
        assert "flag2=1" in path
        assert "flag6=1" in path
        assert "flag10=1" in path
        assert "flag27=1" in path
        assert "setFlags=1" in path
        # Verify no other flag params are present
        assert path.startswith("/cfg_generic?")
        parts = path.split("?")[1].split("&")
        assert len(parts) == 5

    def test_set_flags_invalid_type_raises(self):
        """openbk set_flags with non-int flags raises DeviceConnectionError."""
        with pytest.raises(DeviceConnectionError, match="INVALID_PARAM"):
            _build_url("openbk", "set_flags", flags="abc")

    def test_set_flags_negative_raises(self):
        """openbk set_flags with negative flags raises DeviceConnectionError."""
        with pytest.raises(DeviceConnectionError, match="INVALID_PARAM"):
            _build_url("openbk", "set_flags", flags=-1)

    def test_set_name(self):
        """openbk set_name returns URL with shortName and name."""
        path, dtype = _build_url("openbk", "set_name", short_name="Test", full_name="Test_Device")
        assert dtype == "openbk"
        assert path.startswith("/cfg_name?")
        # shortName is URL-quoted raw, then name is URL-quoted
        assert "shortName=Test" in path
        assert "name=Test_Device" in path

    def test_set_name_with_name_fallback(self):
        """openbk set_name uses 'name' kwarg as fallback for full_name."""
        path, dtype = _build_url("openbk", "set_name", name="Fallback_Name")
        assert dtype == "openbk"
        assert "name=Fallback_Name" in path

    def test_configure_mqtt_minimal(self):
        """openbk configure_mqtt with required params only."""
        path, dtype = _build_url(
            "openbk",
            "configure_mqtt",
            host="192.168.1.1",
            port=1883,
            client="test",
        )
        assert dtype == "openbk"
        assert path.startswith("/cfg_mqtt_set?")
        assert "host=192.168.1.1" in path
        assert "port=1883" in path
        assert "client=test" in path
        assert "group=" not in path
        assert "user=" not in path
        assert "password=" not in path

    def test_configure_mqtt_full(self):
        """openbk configure_mqtt with all params."""
        path, dtype = _build_url(
            "openbk",
            "configure_mqtt",
            host="192.168.1.1",
            port=1883,
            client="test",
            user="admin",
            password="secret",
            group="group1",
        )
        assert dtype == "openbk"
        assert "host=192.168.1.1" in path
        assert "port=1883" in path
        assert "client=test" in path
        assert "user=admin" in path
        assert "group=group1" in path
        assert "password=secret" in path

    def test_set_gpio(self):
        """openbk set_gpio returns URL with pin role and channel."""
        path, dtype = _build_url("openbk", "set_gpio", pin=6, role="Relay", channel=1)
        assert dtype == "openbk"
        assert path.startswith("/cfg_pins?")
        assert "pin6_role=Relay" in path
        assert "pin6_channel=1" in path

    def test_set_gpio_quotes_special_chars(self):
        """openbk set_gpio URL-encodes role with special characters."""
        path, dtype = _build_url("openbk", "set_gpio", pin=0, role="Relay High", channel=2)
        assert dtype == "openbk"
        assert "pin0_role=Relay%20High" in path
        assert "pin0_channel=2" in path

    def test_start_ha_discovery(self):
        """openbk start_ha_discovery returns URL with prefix."""
        path, dtype = _build_url("openbk", "start_ha_discovery", prefix="homeassistant")
        assert dtype == "openbk"
        assert path == "/ha_discovery?prefix=homeassistant"

    def test_start_ha_discovery_custom_prefix(self):
        """openbk start_ha_discovery with custom prefix."""
        path, dtype = _build_url("openbk", "start_ha_discovery", prefix="custom_prefix")
        assert dtype == "openbk"
        assert path == "/ha_discovery?prefix=custom_prefix"


# =============================================================================
# G. _build_url -- Tasmota endpoints
# =============================================================================


class TestBuildUrlTasmota:
    """Tests for _build_url with device_type='tasmota'."""

    def test_get_full_info(self):
        """tasmota get_full_info returns Status 0 URL."""
        path, dtype = _build_url("tasmota", "get_full_info")
        assert path == "/cm?cmnd=Status%200"
        assert dtype == "tasmota"

    def test_execute_command(self):
        """tasmota execute_command returns URL with encoded command."""
        path, dtype = _build_url("tasmota", "execute_command", command="Power1 ON")
        assert path == "/cm?cmnd=Power1%20ON"
        assert dtype == "tasmota"

    def test_execute_command_special_chars(self):
        """tasmota execute_command encodes special characters."""
        path, dtype = _build_url(
            "tasmota", "execute_command", command="Backlog Power1 ON; Power2 OFF"
        )
        assert dtype == "tasmota"
        # spaces encoded as %20, semicolon as %3B
        assert "Backlog%20Power1%20ON%3B%20Power2%20OFF" in path

    def test_set_flags_bit0(self):
        """tasmota set_flags with bit 0 set returns SetOption0."""
        path, dtype = _build_url("tasmota", "set_flags", flags=1)
        assert dtype == "tasmota"
        assert path == "/cm?cmnd=SetOption0%201"

    def test_set_flags_bit10(self):
        """tasmota set_flags with bit 10 set returns SetOption10."""
        path, dtype = _build_url("tasmota", "set_flags", flags=1024)
        assert dtype == "tasmota"
        assert path == "/cm?cmnd=SetOption10%201"

    def test_set_flags_no_bits_raises(self):
        """tasmota set_flags with flags=0 raises DeviceConnectionError."""
        with pytest.raises(DeviceConnectionError, match="INVALID_PARAM"):
            _build_url("tasmota", "set_flags", flags=0)

    def test_set_flags_bit30_is_valid(self):
        """tasmota set_flags with bit 30 returns SetOption30."""
        path, dtype = _build_url("tasmota", "set_flags", flags=1 << 30)
        assert dtype == "tasmota"
        assert path == "/cm?cmnd=SetOption30%201"

    def test_set_flags_bit31_is_valid(self):
        """tasmota set_flags with bit 31 returns SetOption31."""
        path, dtype = _build_url("tasmota", "set_flags", flags=1 << 31)
        assert dtype == "tasmota"
        assert path == "/cm?cmnd=SetOption31%201"

    def test_set_flags_invalid_type_raises(self):
        """tasmota set_flags with non-int flags raises DeviceConnectionError."""
        with pytest.raises(DeviceConnectionError, match="INVALID_PARAM"):
            _build_url("tasmota", "set_flags", flags="abc")

    def test_set_flags_negative_raises(self):
        """tasmota set_flags with negative flags raises DeviceConnectionError."""
        with pytest.raises(DeviceConnectionError, match="INVALID_PARAM"):
            _build_url("tasmota", "set_flags", flags=-1)

    def test_set_name_tasmota_short_only(self):
        """tasmota set_name with only short_name returns DeviceName URL."""
        path, dtype = _build_url("tasmota", "set_name", short_name="Test")
        assert dtype == "tasmota"
        assert path == "/cm?cmnd=DeviceName%20Test"

    def test_configure_mqtt_tasmota_single(self):
        """tasmota configure_mqtt with single param returns single command URL."""
        path, dtype = _build_url("tasmota", "configure_mqtt", host="192.168.1.1")
        assert dtype == "tasmota"
        assert path == "/cm?cmnd=MqttHost%20192.168.1.1"

    def test_set_gpio_raises_unsupported(self):
        """tasmota set_gpio raises UNSUPPORTED_TYPE."""
        with pytest.raises(DeviceConnectionError, match="UNSUPPORTED_TYPE"):
            _build_url("tasmota", "set_gpio", pin=6, role="Relay")

    def test_start_ha_discovery_tasmota(self):
        """tasmota start_ha_discovery returns SetOption19 URL."""
        path, dtype = _build_url("tasmota", "start_ha_discovery")
        assert dtype == "tasmota"
        assert path == "/cm?cmnd=SetOption19%201"


# =============================================================================
# H. _build_url -- unsupported combinations
# =============================================================================


class TestBuildUrlUnsupported:
    """Tests for _build_url with unsupported device_type/endpoint combinations."""

    def test_tuya_get_full_info_unsupported(self):
        """Tuya get_full_info raises UNSUPPORTED_TYPE."""
        with pytest.raises(DeviceConnectionError, match="UNSUPPORTED_TYPE"):
            _build_url("tuya", "get_full_info")

    def test_tuya_execute_command_unsupported(self):
        """Tuya execute_command raises UNSUPPORTED_TYPE."""
        with pytest.raises(DeviceConnectionError, match="UNSUPPORTED_TYPE"):
            _build_url("tuya", "execute_command", command="foo")

    def test_tuya_set_flags_unsupported(self):
        """Tuya set_flags raises UNSUPPORTED_TYPE (HTTP endpoints unavailable)."""
        with pytest.raises(DeviceConnectionError, match="UNSUPPORTED_TYPE"):
            _build_url("tuya", "set_flags", flags=0)

    def test_openhasp_get_full_info_unsupported(self):
        """OpenHASP get_full_info raises UNSUPPORTED_TYPE."""
        with pytest.raises(DeviceConnectionError, match="UNSUPPORTED_TYPE"):
            _build_url("openhasp", "get_full_info")

    def test_openhasp_set_flags_unsupported(self):
        """OpenHASP set_flags raises UNSUPPORTED_TYPE."""
        with pytest.raises(DeviceConnectionError, match="UNSUPPORTED_TYPE"):
            _build_url("openhasp", "set_flags", flags=0)

    def test_unknown_device_type_unsupported(self):
        """Unknown device type raises UNSUPPORTED_TYPE immediately."""
        with pytest.raises(DeviceConnectionError, match="UNSUPPORTED_TYPE"):
            _build_url("unknown", "get_full_info")

    def test_openbk_nonexistent_endpoint_unsupported(self):
        """OpenBK with nonexistent endpoint raises UNSUPPORTED_TYPE."""
        with pytest.raises(DeviceConnectionError, match="UNSUPPORTED_TYPE"):
            _build_url("openbk", "nonexistent_endpoint")

    def test_tasmota_nonexistent_endpoint_unsupported(self):
        """Tasmota with nonexistent endpoint raises UNSUPPORTED_TYPE."""
        with pytest.raises(DeviceConnectionError, match="UNSUPPORTED_TYPE"):
            _build_url("tasmota", "nonexistent_endpoint")


# =============================================================================
# I. _build_url -- Tasmota V2 endpoints (v1.6.0+)
# =============================================================================


class TestBuildUrlTasmotaV2:
    """Tests for new Tasmota URL builders added in v1.6.0."""

    def test_set_flags_single_bit(self):
        """tasmota set_flags with single bit returns single SetOption command."""
        url, dt = _build_url("tasmota", "set_flags", flags=1)  # bit 0
        assert urllib.parse.quote("SetOption0 1") in url
        assert dt == "tasmota"

    def test_set_flags_multi_bit(self):
        """tasmota set_flags with multiple bits returns backlog command."""
        url, dt = _build_url("tasmota", "set_flags", flags=9)  # bits 0, 3
        assert "backlog" in url
        assert "SetOption0" in url
        assert "SetOption3" in url
        assert dt == "tasmota"

    def test_set_flags_zero_bits_raises(self):
        """tasmota set_flags with flags=0 raises INVALID_PARAM."""
        with pytest.raises(DeviceConnectionError, match="INVALID_PARAM"):
            _build_url("tasmota", "set_flags", flags=0)

    def test_set_name_short_only(self):
        """tasmota set_name with only short_name returns DeviceName URL."""
        url, dt = _build_url("tasmota", "set_name", short_name="Test")
        assert "DeviceName" in url
        assert "Test" in url
        assert dt == "tasmota"

    def test_set_name_with_full_name(self):
        """tasmota set_name with full_name returns backlog with FriendlyName1."""
        url, dt = _build_url("tasmota", "set_name", short_name="Short", full_name="Full_Name")
        assert "backlog" in url
        assert "DeviceName" in url
        assert "FriendlyName1" in url
        assert "Short" in url
        assert "Full_Name" in url

    def test_set_name_with_name_fallback(self):
        """When full_name not provided but 'name' param is, use 'name' as full_name."""
        url, dt = _build_url("tasmota", "set_name", short_name="S", name="N")
        assert "DeviceName" in url
        assert "FriendlyName1" in url
        assert dt == "tasmota"

    def test_configure_mqtt_single_param(self):
        """tasmota configure_mqtt with single param returns single command URL."""
        url, dt = _build_url("tasmota", "configure_mqtt", host="192.168.1.1")
        assert "MqttHost" in url
        assert "192.168.1.1" in url
        assert "backlog" not in url
        assert dt == "tasmota"

    def test_configure_mqtt_multi_param(self):
        """tasmota configure_mqtt with multiple params returns backlog URL."""
        url, dt = _build_url(
            "tasmota", "configure_mqtt", host="192.168.1.1", port=1883, client="test"
        )
        assert "backlog" in url
        assert "MqttHost" in url
        assert "MqttPort" in url
        assert "MqttClient" in url

    def test_configure_mqtt_no_params_raises(self):
        """tasmota configure_mqtt with no params raises INVALID_PARAM."""
        with pytest.raises(DeviceConnectionError, match="INVALID_PARAM"):
            _build_url("tasmota", "configure_mqtt")

    def test_set_startup_command(self):
        """tasmota set_startup_command returns Rule1 with System#Boot trigger."""
        url, dt = _build_url("tasmota", "set_startup_command", command="Power1 ON")
        assert "Rule1" in url
        assert "System%23Boot" in url  # # is URL-encoded
        assert "Power1%20ON" in url
        assert dt == "tasmota"

    def test_set_friendly_name(self):
        """tasmota set_friendly_name returns FriendlyName1 URL."""
        url, dt = _build_url("tasmota", "set_friendly_name", friendly_name="Bathroom_Light")
        assert "FriendlyName1" in url
        assert "Bathroom_Light" in url
        assert dt == "tasmota"

    def test_start_ha_discovery(self):
        """tasmota start_ha_discovery returns SetOption19 URL."""
        url, dt = _build_url("tasmota", "start_ha_discovery")
        assert "SetOption19" in url
        assert dt == "tasmota"

    def test_set_gpio_unsupported(self):
        """tasmota set_gpio raises UNSUPPORTED_TYPE."""
        with pytest.raises(DeviceConnectionError, match="UNSUPPORTED_TYPE"):
            _build_url("tasmota", "set_gpio", pin=6, role="Relay")
