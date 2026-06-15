# mypy: disable-error-code="untyped-decorator"
"""
IoT MQTT Integration Tools

Interact with IoT devices via MQTT broker.
"""

import json
import time
from typing import Any

from tools.constants import (
    MQTT_BROKER,
    MQTT_PASSWORD,
    MQTT_PORT,
    MQTT_USER,
    _error_response_extended,
    _success_response,
    check_write_enabled,
    increment_tool_count,
    inject_tool_risk_prefix,
    start_tool_context,
)
from tools.validators import ValidationError, validate_required_string

__all__ = ["register_iot_mqtt_tools", "_get_mqtt_client", "_mqtt_publish"]


def _get_mqtt_client() -> Any:
    """Get configured MQTT client.

    Returns:
        Configured mqtt.Client instance or None if paho-mqtt is not installed.
    """
    try:
        import paho.mqtt.client as mqtt

        try:
            # paho-mqtt >= 2.0 requires callback_api_version
            CallbackAPIVersion = getattr(mqtt, "CallbackAPIVersion")
            client = mqtt.Client(callback_api_version=CallbackAPIVersion.VERSION1)  # type: ignore[call-arg]
        except AttributeError:
            # paho-mqtt < 2.0
            client = mqtt.Client()
        except TypeError:
            # paho-mqtt < 2.0
            client = mqtt.Client()

        if MQTT_USER:
            client.username_pw_set(MQTT_USER, MQTT_PASSWORD)

        return client
    except ImportError:
        return None


def _mqtt_publish(topic: str, payload: str, retain: bool = False, timeout_seconds: int = 10) -> str:
    """Publish an MQTT message.

    Args:
        topic: MQTT topic (e.g. "cmnd/device_389AF7/Power").
        payload: Message payload (e.g. "ON", "OFF", "TOGGLE").
        retain: Whether to retain the message.
        timeout_seconds: MQTT broker connection timeout in seconds.

    Returns:
        JSON string with result.
    """
    try:
        topic = validate_required_string(topic, "topic")
        payload = validate_required_string(payload, "payload")
    except ValidationError as exc:
        return _error_response_extended(code="INVALID_PARAM", message=str(exc))

    client = _get_mqtt_client()
    if not client:
        return _error_response_extended(
            code="DEPENDENCY_MISSING",
            message="paho-mqtt not installed. Install with: pip install paho-mqtt",
        )

    try:
        client.connect(MQTT_BROKER, MQTT_PORT, timeout_seconds)
        result = client.publish(topic, payload, retain=retain)
        client.disconnect()

        return _success_response(
            {
                "broker": f"{MQTT_BROKER}:{MQTT_PORT}",
                "topic": topic,
                "payload": payload,
                "retain": retain,
                "mqtt_result": result.rc,
            }
        )
    except Exception as exc:
        return _error_response_extended(code="INTERNAL_ERROR", message=str(exc))


def _mqtt_get_state(topic_prefix: str, timeout_seconds: int = 10) -> str:
    """Get current state of a device via MQTT.

    Subscribes to the state topic and returns the latest value.

    Args:
        topic_prefix: Device topic prefix (e.g. "device_389AF7").
        timeout_seconds: How long to wait for state message in seconds.

    Returns:
        JSON string with device state.
    """
    try:
        topic_prefix = validate_required_string(topic_prefix, "topic_prefix")
    except ValidationError as exc:
        return _error_response_extended(code="INVALID_PARAM", message=str(exc))

    client = _get_mqtt_client()
    if not client:
        return _error_response_extended(
            code="DEPENDENCY_MISSING",
            message="paho-mqtt not installed",
        )

    state_topic = f"tele/{topic_prefix}/STATE"
    received_messages: list[dict[str, str]] = []

    def on_message(_client: Any, _userdata: Any, msg: Any) -> None:
        received_messages.append({"topic": msg.topic, "payload": msg.payload.decode()})

    client.on_message = on_message
    try:
        client.connect(MQTT_BROKER, MQTT_PORT, timeout_seconds)
        client.subscribe(state_topic)
        client.loop_start()
        time.sleep(timeout_seconds)
    except Exception as exc:
        return _error_response_extended(code="INTERNAL_ERROR", message=str(exc))
    finally:
        try:
            client.loop_stop()
        except Exception:
            pass
        try:
            client.disconnect()
        except Exception:
            pass

    if not received_messages:
        # Check if device has any active GPIO channels
        try:
            from tools.iot_devices import _get_device_info
            from tools.iot_discovery import _resolve_ip

            ip = _resolve_ip(topic_prefix)
            if ip:
                info_str = _get_device_info(topic_prefix)
                info = json.loads(info_str) if isinstance(info_str, str) else info_str
                if info.get("success"):
                    dev_info = info.get("data", info).get("info", info.get("data", {}))
                    channels = dev_info.get("channels", 1)
                    has_no_channels = (
                        channels == 0
                        or (isinstance(channels, list) and len(channels) == 0)
                        or (isinstance(channels, dict) and len(channels) == 0)
                    )
                    if has_no_channels:
                        return _success_response(
                            {
                                "state": "unknown",
                                "reason": "no_active_channels",
                                "message": (
                                    "Device is connected to MQTT but has no GPIO channels "
                                    "configured. State topics are not published for "
                                    "channel-less devices."
                                ),
                            }
                        )
        except Exception:
            pass

        return _error_response_extended(
            code="TIMEOUT",
            message="No state message received within timeout",
            suggestion=(
                "Device may be connected to MQTT but not publishing state. "
                "Use iot_get_device_info to check if GPIO channels are configured."
            ),
        )

    latest = received_messages[-1]
    try:
        payload = json.loads(latest["payload"])
    except json.JSONDecodeError:
        payload = latest["payload"]

    return _success_response(
        {
            "topic": latest["topic"],
            "state": payload,
            "messages_received": len(received_messages),
        }
    )


def _mqtt_build_command_topic(device_name: str, command: str = "Power") -> str:
    """Build MQTT command topic for a device.

    Args:
        device_name: Device MQTT topic (e.g. "device_389AF7").
        command: Command name (default "Power").

    Returns:
        JSON string with topic information.
    """
    try:
        device_name = validate_required_string(device_name, "device_name")
        command = validate_required_string(command, "command")
    except ValidationError as exc:
        return _error_response_extended(code="INVALID_PARAM", message=str(exc))

    topic = f"cmnd/{device_name}/{command}"
    state_topic = f"stat/{device_name}/{command}"
    tele_topic = f"tele/{device_name}/STATE"

    return _success_response(
        {
            "device_name": device_name,
            "command": command,
            "command_topic": topic,
            "state_topic": state_topic,
            "telemetry_topic": tele_topic,
            "example_payloads": {
                "ON": "Turn device ON",
                "OFF": "Turn device OFF",
                "TOGGLE": "Toggle device state",
                "0": "Set brightness/channel to 0",
                "100": "Set brightness/channel to 100",
            },
        }
    )


def register_iot_mqtt_tools(mcp: Any) -> None:
    """Register IoT MQTT tools with the MCP server."""

    @mcp.tool()
    @inject_tool_risk_prefix
    def iot_mqtt_publish(
        topic: str, payload: str, retain: bool = False, timeout_seconds: int = 10
    ) -> str:
        """Publish an MQTT message to control an IoT device.

        Args:
            topic: MQTT topic (e.g. "cmnd/device_389AF7/Power").
            payload: Message payload (e.g. "ON", "OFF", "TOGGLE").
            retain: Whether to retain the message (default False).
            timeout_seconds: MQTT broker connection timeout in seconds (default 10).

        Returns:
            JSON with result.

        @since v1.2.0
        """
        try:
            start_tool_context()
            check_write_enabled()
            increment_tool_count("iot_mqtt_publish")
            return _mqtt_publish(topic, payload, retain, timeout_seconds)
        except ValidationError as exc:
            return _error_response_extended(
                code="WRITE_DISABLED",
                message=str(exc),
                retryable=False,
                suggestion="Ask the server operator to set ENABLE_WRITE_OPERATIONS=1.",
            )
        except Exception as exc:
            return _error_response_extended(code="INTERNAL_ERROR", message=str(exc))

    @mcp.tool()
    @inject_tool_risk_prefix
    def iot_mqtt_get_state(topic_prefix: str, timeout_seconds: int = 10) -> str:
        """Get current state of a device via MQTT.

        Subscribes to the state topic and returns the latest value.

        Args:
            topic_prefix: Device topic prefix (e.g. "device_389AF7").
            timeout_seconds: How long to wait for state message in seconds (default 10).

        Returns:
            JSON with device state.

        @since v1.2.0
        """
        try:
            start_tool_context()
            increment_tool_count("iot_mqtt_get_state")
            return _mqtt_get_state(topic_prefix, timeout_seconds)
        except Exception as exc:
            return _error_response_extended(code="INTERNAL_ERROR", message=str(exc))

    @mcp.tool()
    @inject_tool_risk_prefix
    def iot_mqtt_build_command_topic(device_name: str, command: str = "Power") -> str:
        """Build MQTT command topic for a device.

        Args:
            device_name: Device MQTT topic (e.g. "device_389AF7").
            command: Command name (default "Power").

        Returns:
            JSON with topic information.

        @since v1.2.0
        """
        try:
            start_tool_context()
            increment_tool_count("iot_mqtt_build_command_topic")
            return _mqtt_build_command_topic(device_name, command)
        except Exception as exc:
            return _error_response_extended(code="INTERNAL_ERROR", message=str(exc))
