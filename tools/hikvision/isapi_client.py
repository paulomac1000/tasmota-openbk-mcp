"""
Hikvision ISAPI HTTP Client

Provides authenticated HTTP access to Hikvision doorbell ISAPI endpoints
using HTTP Digest Authentication (RFC 2617).

IMPORTANT: The Hikvision ISAPI API returns XML responses, not JSON.
All response parsing uses defusedxml ElementTree helpers.
"""

import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import requests
from defusedxml import ElementTree as SafeET
from requests.auth import HTTPDigestAuth

from tools.constants import (
    HIKVISION_DOORBELL_HOST,
    HIKVISION_DOORBELL_PASSWORD,
    HIKVISION_DOORBELL_USER,
)

# ISAPI XML namespace
ISAPI_NS = "http://www.isapi.org/ver20/XMLSchema"


def _xml_to_dict(element: ET.Element) -> dict[str, str]:
    """Convert an XML Element to a flat dict (first-level children only).

    Strips the ISAPI namespace from tag names. Nested elements are
    converted to their text value. Suitable for flat ISAPI responses
    like deviceInfo.
    """
    result: dict[str, str] = {}
    for child in element:
        tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
        text = child.text.strip() if child.text else ""
        result[tag] = text
    return result


class HikvisionISAPIClient:
    """HTTP client for Hikvision ISAPI API with digest auth."""

    def __init__(self, host: str, username: str, password: str, timeout: int = 10):
        self.base_url = f"http://{host}"
        self.auth = HTTPDigestAuth(username, password)
        self.timeout = timeout
        self.session = requests.Session()

    def get_snapshot(self, channel: int = 1) -> bytes | None:
        """Capture a JPEG snapshot from the doorbell camera.

        Endpoint: GET /ISAPI/Streaming/channels/{channel}01/picture
        Response: binary JPEG image

        Args:
            channel: Camera channel (1 = main doorbell camera).

        Returns:
            JPEG image bytes, or None on failure.
        """
        url = f"{self.base_url}/ISAPI/Streaming/channels/{channel}01/picture"
        try:
            resp = self.session.get(url, auth=self.auth, timeout=self.timeout)
            resp.raise_for_status()
            return resp.content
        except Exception:
            return None

    def get_device_info(self) -> dict[str, str] | None:
        """Fetch device information from ISAPI.

        Endpoint: GET /ISAPI/System/deviceInfo
        Response: XML (application/xml) - parsed to dict via ElementTree

        Returns:
            Dict with keys: deviceName, model, serialNumber, macAddress,
            firmwareVersion, firmwareReleasedDate, etc. None on failure.
        """
        url = f"{self.base_url}/ISAPI/System/deviceInfo"
        try:
            resp = self.session.get(url, auth=self.auth, timeout=self.timeout)
            resp.raise_for_status()
            root = SafeET.fromstring(resp.text)
            return _xml_to_dict(root)
        except Exception:
            return None

    def get_alarm_server(self) -> dict[str, str | int | None] | None:
        """Fetch the first HTTP host notification (alarm server) configuration.

        Endpoint: GET /ISAPI/Event/notification/httpHosts
        Response: XML (application/xml) — parsed to dict via ElementTree

        Returns:
            Dict with keys: id, url, protocol, ip, port (int), auth_method.
            None if no alarm server configured or on error.
        """
        url = f"{self.base_url}/ISAPI/Event/notification/httpHosts"
        try:
            resp = self.session.get(url, auth=self.auth, timeout=self.timeout)
            resp.raise_for_status()
            root = SafeET.fromstring(resp.text)
            notification = root.find(f".//{{{ISAPI_NS}}}HttpHostNotification")
            if notification is None:
                return None
            port_text = notification.findtext(f".//{{{ISAPI_NS}}}portNo")
            return {
                "id": notification.findtext(f".//{{{ISAPI_NS}}}id"),
                "url": notification.findtext(f".//{{{ISAPI_NS}}}url"),
                "protocol": notification.findtext(f".//{{{ISAPI_NS}}}protocolType"),
                "ip": notification.findtext(f".//{{{ISAPI_NS}}}ipAddress"),
                "port": int(port_text) if port_text else None,
                "auth_method": notification.findtext(f".//{{{ISAPI_NS}}}authentication"),
            }
        except Exception:
            return None

    def save_snapshot(self, filepath: str) -> dict[str, str | int | bool]:
        """Capture a snapshot and save it to disk.

        Reuses get_snapshot() to capture the JPEG image, then writes
        it to the given filepath using pathlib.

        Args:
            filepath: Destination path for the JPEG file.

        Returns:
            Dict with saved (bool), filepath, size_bytes, format on success,
            or saved=False with error string on failure.
        """
        try:
            img_bytes = self.get_snapshot(channel=1)
            if img_bytes is None:
                return {"saved": False, "error": "Failed to capture snapshot"}
            Path(filepath).write_bytes(img_bytes)
            return {
                "saved": True,
                "filepath": str(filepath),
                "size_bytes": len(img_bytes),
                "format": "jpeg",
            }
        except Exception as exc:
            return {"saved": False, "error": str(exc)}

    def get_event_triggers(self) -> list[dict[str, Any]] | None:
        """Fetch event trigger configuration from ISAPI.

        Endpoint: GET /ISAPI/Event/triggers
        Response: XML (application/xml) - parsed to list of trigger dicts

        Each trigger dict has keys: id, event_type, notifications.
        notifications is a list of dicts with keys: id, method, recurrence.

        Returns:
            List of trigger dicts, or None on failure.
        """
        url = f"{self.base_url}/ISAPI/Event/triggers"
        try:
            resp = self.session.get(url, auth=self.auth, timeout=self.timeout)
            resp.raise_for_status()
            root = SafeET.fromstring(resp.text)
            triggers = []
            for trigger_elem in root.findall(f".//{{{ISAPI_NS}}}EventTrigger"):
                trigger_id = trigger_elem.find(f"{{{ISAPI_NS}}}id")
                event_type = trigger_elem.find(f"{{{ISAPI_NS}}}eventType")
                trigger: dict[str, Any] = {
                    "id": (
                        trigger_id.text.strip()
                        if trigger_id is not None and trigger_id.text
                        else ""
                    ),
                    "event_type": (
                        event_type.text.strip()
                        if event_type is not None and event_type.text
                        else ""
                    ),
                    "notifications": [],
                }
                notif_list = trigger_elem.find(f"{{{ISAPI_NS}}}EventTriggerNotificationList")
                if notif_list is not None:
                    for notif_elem in notif_list.findall(f"{{{ISAPI_NS}}}EventTriggerNotification"):
                        notif_id = notif_elem.find(f"{{{ISAPI_NS}}}id")
                        method = notif_elem.find(f"{{{ISAPI_NS}}}notificationMethod")
                        recurrence = notif_elem.find(f"{{{ISAPI_NS}}}recurrence")
                        notification: dict[str, Any] = {
                            "id": (
                                notif_id.text.strip()
                                if notif_id is not None and notif_id.text
                                else ""
                            ),
                            "method": (
                                method.text.strip() if method is not None and method.text else ""
                            ),
                            "recurrence": (
                                recurrence.text.strip()
                                if recurrence is not None and recurrence.text
                                else ""
                            ),
                        }
                        trigger["notifications"].append(notification)
                triggers.append(trigger)
            return triggers
        except Exception:
            return None

    def get_motion_config(self) -> dict[str, Any] | None:
        """Fetch motion detection configuration from ISAPI.

        Endpoint: GET /ISAPI/System/Video/inputs/channels/1/MotionDetection
        Response: XML (application/xml)

        Returns:
            Dict with keys: enabled (bool), sensitivity (int), grid_map (str),
            grid_rows (int), grid_cols (int). None on failure.
        """
        url = f"{self.base_url}/ISAPI/System/Video/inputs/channels/1/MotionDetection"
        try:
            resp = self.session.get(url, auth=self.auth, timeout=self.timeout)
            resp.raise_for_status()
            root = SafeET.fromstring(resp.text)
            enabled_text = root.findtext(f"{{{ISAPI_NS}}}enabled", default="false")
            sensitivity_el = root.find(f".//{{{ISAPI_NS}}}sensitivityLevel")
            grid_map_el = root.find(f".//{{{ISAPI_NS}}}gridMap")
            rows_el = root.find(f".//{{{ISAPI_NS}}}rowGranularity")
            cols_el = root.find(f".//{{{ISAPI_NS}}}columnGranularity")
            sensitivity = 50
            if sensitivity_el is not None and sensitivity_el.text:
                sensitivity = int(sensitivity_el.text)
            grid_map = ""
            if grid_map_el is not None and grid_map_el.text:
                grid_map = grid_map_el.text.strip()
            grid_rows = 18
            if rows_el is not None and rows_el.text:
                grid_rows = int(rows_el.text.split("x")[0])
            grid_cols = 22
            if cols_el is not None and cols_el.text:
                grid_cols = int(cols_el.text.split("x")[1])
            return {
                "enabled": enabled_text.strip() == "true",
                "sensitivity": sensitivity,
                "grid_map": grid_map,
                "grid_rows": grid_rows,
                "grid_cols": grid_cols,
            }
        except Exception:
            return None

    def set_motion_config(
        self, enabled: bool | None = None, sensitivity: int | None = None
    ) -> bool:
        """Set motion detection configuration via read-modify-write.

        Fetches current config, overrides specified fields, and PUTs the
        complete XML back. The doorbell requires all fields on PUT.

        Args:
            enabled: Enable or disable motion detection (None = no change).
            sensitivity: Sensitivity level 0-100 (None = no change).

        Returns:
            True if the PUT succeeded, False on any error.
        """
        current = self.get_motion_config()
        if current is None:
            # Full defaults when no current config available
            cur_enabled = True
            cur_sensitivity = 70
            region_type = "grid"
            row_gran = "18x18"
            col_gran = "22x22"
            grid_map = "ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff"
        else:
            cur_enabled = current["enabled"]
            cur_sensitivity = current["sensitivity"]
            region_type = "grid"
            row_gran = f"{current['grid_rows']}x{current['grid_rows']}"
            col_gran = f"{current['grid_cols']}x{current['grid_cols']}"
            grid_map = current["grid_map"]

        if enabled is not None:
            cur_enabled = enabled
        if sensitivity is not None:
            cur_sensitivity = sensitivity

        root = ET.Element(f"{{{ISAPI_NS}}}MotionDetection")
        ET.SubElement(root, f"{{{ISAPI_NS}}}enabled").text = str(cur_enabled).lower()
        ET.SubElement(root, f"{{{ISAPI_NS}}}regionType").text = region_type
        grid = ET.SubElement(root, f"{{{ISAPI_NS}}}Grid")
        ET.SubElement(grid, f"{{{ISAPI_NS}}}rowGranularity").text = row_gran
        ET.SubElement(grid, f"{{{ISAPI_NS}}}columnGranularity").text = col_gran
        layout = ET.SubElement(root, f"{{{ISAPI_NS}}}MotionDetectionLayout")
        ET.SubElement(layout, f"{{{ISAPI_NS}}}sensitivityLevel").text = str(cur_sensitivity)
        layout_inner = ET.SubElement(layout, f"{{{ISAPI_NS}}}layout")
        ET.SubElement(layout_inner, f"{{{ISAPI_NS}}}gridMap").text = grid_map
        body = ET.tostring(root, encoding="unicode", xml_declaration=True)

        url = f"{self.base_url}/ISAPI/System/Video/inputs/channels/1/MotionDetection"
        headers = {"Content-Type": "application/xml"}
        try:
            resp = self.session.put(
                url,
                auth=self.auth,
                data=body,
                headers=headers,
                timeout=self.timeout,
            )
            resp.raise_for_status()
            return True
        except Exception:
            return False

    def open_door(self, door_id: int = 1) -> bool:
        """Trigger the electric lock relay (open gate).

        Endpoint: PUT /ISAPI/AccessControl/RemoteControl/door/{door_id}
        Body: XML <RemoteControlDoor><cmd>open</cmd></RemoteControlDoor>
        Content-Type: application/xml

        Args:
            door_id: Door output number (1 = main gate relay).

        Returns:
            True if successful, False otherwise.
        """
        url = f"{self.base_url}/ISAPI/AccessControl/RemoteControl/door/{door_id}"
        headers = {"Content-Type": "application/xml"}
        body = "<RemoteControlDoor><cmd>open</cmd></RemoteControlDoor>"
        try:
            resp = self.session.put(
                url, auth=self.auth, data=body, headers=headers, timeout=self.timeout
            )
            resp.raise_for_status()
            return True
        except Exception:
            return False

    def ping(self) -> bool:
        """Check if the doorbell is reachable via HTTP.

        Endpoint: GET / (root page, returns 302 redirect)

        Returns:
            True if doorbell responds (any status < 500), False otherwise.
        """
        try:
            resp = self.session.get(self.base_url, timeout=self.timeout)
            return resp.status_code < 500
        except Exception:
            return False


def create_isapi_client() -> HikvisionISAPIClient:
    """Factory: create ISAPI client from environment variables.

    Reads:
        HIKVISION_DOORBELL_HOST
        HIKVISION_DOORBELL_USER (required)
        HIKVISION_DOORBELL_PASSWORD (required)

    Returns:
        Configured HikvisionISAPIClient instance.
    """
    host = HIKVISION_DOORBELL_HOST
    user = HIKVISION_DOORBELL_USER
    password = HIKVISION_DOORBELL_PASSWORD
    if not user or not password:
        raise ValueError(
            "HIKVISION_DOORBELL_USER and HIKVISION_DOORBELL_PASSWORD must be set. "
            "Configure them in the server environment."
        )
    return HikvisionISAPIClient(host, user, password)
