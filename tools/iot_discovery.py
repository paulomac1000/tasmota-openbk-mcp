# mypy: disable-error-code="untyped-decorator"
"""
IoT Device Discovery Tools

Fully dynamic discovery using nmap network scanning.
Discovered devices are cached in /app/data/discovered_devices.json.
If the cache is empty, listing tools suggest running discovery first.
"""

import calendar
import json
import os
import re
import shutil
import socket
import subprocess
import threading
import time
from typing import Any

import requests

from tools.constants import (
    DEFAULT_NETWORK_RANGE,
    _error_response_extended,
    _success_response,
    get_logger,
    increment_tool_count,
    inject_tool_risk_prefix,
    start_tool_context,
)
from tools.validators import validate_cidr

# =============================================================================
# CACHE CONFIGURATION
# =============================================================================

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
CACHE_FILE = os.path.join(DATA_DIR, "discovered_devices.json")
CACHE_TTL_SECONDS = 3600  # 1 hour
_cache_lock = threading.Lock()

__all__ = [
    "register_iot_discovery_tools",
    "_detect_device_type",
    "_probe_device_info",
    "_scan_network",
    "_load_cache",
    "_save_cache",
    "_get_cached_devices",
    "_find_device_by_identifier",
    "_resolve_ip",
]


def _ensure_data_dir() -> None:
    """Create data directory if it does not exist."""
    os.makedirs(DATA_DIR, exist_ok=True)


def _load_cache() -> dict[str, Any]:
    """Load discovered devices from cache file.

    Returns:
        Dictionary with devices list, last_scan timestamp and version.
        Returns empty structure if cache does not exist or is corrupted.
    """
    with _cache_lock:
        _ensure_data_dir()
        if not os.path.exists(CACHE_FILE):
            return {"devices": [], "last_scan": None, "version": 1}
        try:
            with open(CACHE_FILE, encoding="utf-8") as f:
                result: Any = json.load(f)
                if not isinstance(result, dict):
                    return {"devices": [], "last_scan": None, "version": 1}
                return result
        except json.JSONDecodeError:
            return {"devices": [], "last_scan": None, "version": 1}
        except OSError:
            return {"devices": [], "last_scan": None, "version": 1}


def _save_cache(devices: list[dict[str, Any]]) -> None:
    """Save discovered devices to cache file.

    Args:
        devices: List of device dictionaries to persist.
    """
    with _cache_lock:
        _ensure_data_dir()
        cache = {
            "version": 1,
            "last_scan": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "device_count": len(devices),
            "devices": devices,
        }
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f, indent=2, ensure_ascii=False)


def _get_cached_devices() -> list[dict[str, Any]]:
    """Return list of cached devices."""
    cache = _load_cache()
    devices = cache.get("devices", [])
    if not isinstance(devices, list):
        return []
    return devices


def _is_cache_fresh() -> bool:
    """Check if the cache is still fresh (within TTL).

    Returns:
        True if cache exists and is younger than CACHE_TTL_SECONDS.
    """
    cache = _load_cache()
    last_scan = cache.get("last_scan")
    if not last_scan:
        return False
    try:
        scan_time = calendar.timegm(time.strptime(last_scan, "%Y-%m-%dT%H:%M:%SZ"))
        return (time.time() - scan_time) < CACHE_TTL_SECONDS
    except ValueError:
        return False
    except OverflowError:
        return False


def _find_device_by_identifier(identifier: str) -> dict[str, Any] | None:
    """Find a device by IP address or name (case-insensitive).

    Args:
        identifier: IP address or device name (or partial name).

    Returns:
        Device dictionary if found, None otherwise.
    """
    devices = _get_cached_devices()
    identifier_lower = identifier.lower().strip()

    # Exact IP match
    for device in devices:
        if device.get("ip") == identifier:
            return device

    # Exact name match (case-insensitive)
    for device in devices:
        name = (device.get("name") or "").lower().strip()
        if name == identifier_lower:
            return device

    # Partial name match (minimum 3 chars to avoid false positives)
    if len(identifier_lower) >= 3:
        for device in devices:
            name = (device.get("name") or "").lower().strip()
            if identifier_lower in name:
                return device

    return None


def _resolve_ip(identifier: str) -> str | None:
    """Resolve an identifier (IP or name) to an IP address using cache.

    Args:
        identifier: IP address or device name.

    Returns:
        IP address string if resolved, None otherwise.
    """
    if re.match(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$", identifier):
        return identifier

    device = _find_device_by_identifier(identifier)
    if device:
        return device.get("ip")

    return None


# =============================================================================
# DEVICE DETECTION
# =============================================================================


def _detect_device_type(ip: str, timeout: int = 5) -> str | None:
    """Detect if device is OpenBK, Tasmota, or Tuya by probing endpoints.

    New probe order (2026-06-07): OpenBK first, then Tasmota, then Tuya, then OpenHASP.
    OpenBK also responds to Tasmota's /cm?cmnd=Status endpoint, so we must
    check OpenBK-specific endpoints BEFORE the Tasmota probe.

    Args:
        ip: IP address of the device to probe.
        timeout: Request timeout in seconds.

    Returns:
        "openbk", "tasmota", "tuya", "openhasp" or None.
    """
    # === PROBE 1: OpenBK via /api/info (unique JSON endpoint) ===
    try:
        resp = requests.get(
            f"http://{ip}/api/info",
            timeout=timeout,
            allow_redirects=False,
        )
        if resp.status_code == 200:
            try:
                data = resp.json()
                if isinstance(data, dict) and "build" in data:
                    return "openbk"
            except Exception:
                pass
    except Exception:
        pass

    # === PROBE 2: OpenBK via /index HTML ===
    try:
        resp = requests.get(
            f"http://{ip}/index",
            timeout=timeout,
            allow_redirects=False,
        )
        if resp.status_code == 200:
            text = resp.text.lower()
            if "openbeken" in text or "openshwprojects" in text:
                return "openbk"
    except Exception:
        pass

    # === PROBE 3: Tasmota via /cm?cmnd=Status ===
    try:
        resp = requests.get(
            f"http://{ip}/cm?cmnd=Status",
            timeout=timeout,
            allow_redirects=False,
        )
        if resp.status_code == 200 and '"Status"' in resp.text:
            return "tasmota"
    except Exception:
        pass

    # === PROBE 4: Tuya TCP port 6668 ===
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(2)
        result = sock.connect_ex((ip, 6668))
        sock.close()
        if result == 0:
            return "tuya"
    except Exception:
        pass

    # === PROBE 5: Tuya TCP port 6667 ===
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(2)
        result = sock.connect_ex((ip, 6667))
        sock.close()
        if result == 0:
            return "tuya"
    except Exception:
        pass

    # === PROBE 6: OpenHASP via /config.json ===
    try:
        resp = requests.get(
            f"http://{ip}/config.json",
            timeout=timeout,
            allow_redirects=False,
        )
        if resp.status_code == 200:
            try:
                data = resp.json()
                if "hasp" in data:
                    return "openhasp"
            except Exception:
                pass
    except Exception:
        pass

    return None


def _probe_device_info(ip: str, device_type: str, timeout: int = 5) -> dict[str, Any]:
    """Get basic info from a device.

    Args:
        ip: IP address of the device.
        device_type: "tasmota", "openbk", or "tuya".
        timeout: Request timeout in seconds.

    Returns:
        Dictionary with device information. "reachable" is False on error.
    """
    info: dict[str, Any] = {
        "ip": ip,
        "type": device_type,
        "reachable": False,
        "name": None,
        "version": None,
        "rssi": None,
        "mac": None,
    }

    if device_type == "tasmota":
        try:
            resp = requests.get(f"http://{ip}/cm?cmnd=Status%200", timeout=timeout)
            if resp.status_code == 200:
                data = resp.json()
                status = data.get("Status", {})
                info["reachable"] = True
                info["name"] = status.get("FriendlyName", ["Unknown"])[0]
                info["version"] = status.get("Version", "Unknown")
                info["device_name"] = status.get("DeviceName", "")
                info["topic"] = status.get("Topic", "")
                info["module"] = status.get("Module", 0)
                info["power_on_state"] = status.get("PowerOnState", 0)

                # BK7231N_/BK7231T_ MQTT topic prefix = OpenBK device
                # Re-classify even when Tasmota compatibility layer returns Status JSON
                if info["topic"] and (
                    info["topic"].startswith("BK7231N_") or info["topic"].startswith("BK7231T_")
                ):
                    info["type"] = "openbk"

                try:
                    wifi_resp = requests.get(f"http://{ip}/cm?cmnd=Status%205", timeout=timeout)
                    if wifi_resp.status_code == 200:
                        wifi_data = wifi_resp.json()
                        wifi = wifi_data.get("StatusSTS", {}).get("Wifi", {})
                        if wifi.get("RSSI") is not None:
                            info["rssi"] = wifi.get("RSSI")
                        if wifi.get("Mac"):
                            info["mac"] = wifi.get("Mac")
                        if wifi.get("SSId"):
                            info["ssid"] = wifi.get("SSId")
                except Exception:
                    pass
        except Exception:
            pass

    elif device_type == "openbk":
        try:
            resp = requests.get(f"http://{ip}/index", timeout=timeout)
            if resp.status_code == 200:
                info["reachable"] = True
                text = resp.text
                title_match = re.search(r"<title>([^<]+)</title>", text)
                if title_match:
                    info["name"] = title_match.group(1).strip()

                ver_match = re.search(r"version\s+([\d.]+)", text)
                if ver_match:
                    info["version"] = ver_match.group(1)

                rssi_match = re.search(r"Wifi RSSI:\s+([\w\s]+)\s*\((-?\d+)dBm\)", text)
                if rssi_match:
                    info["rssi"] = int(rssi_match.group(2))
                    info["signal_quality"] = rssi_match.group(1).strip()

                mac_match = re.search(r"Device MAC:\s*([0-9A-Fa-f:]{17})", text)
                if mac_match:
                    info["mac"] = mac_match.group(1)

                channels = re.findall(r"Channel\s+(\d+)\s+=\s+([\d.]+)", text)
                info["channels"] = [{"channel": int(c[0]), "value": float(c[1])} for c in channels]
        except Exception:
            pass

    elif device_type == "tuya":
        info["reachable"] = True
        try:
            from tools.iot_tuya import (
                _find_tuya_in_cache,
                _get_tuya_local,
                _load_tuya_devices,
                _save_tuya_devices,
            )

            entry = _find_tuya_in_cache(ip)
            if entry and entry.get("device_id"):
                info["name"] = entry.get("name", "Tuya_Device")
                info["device_id"] = entry.get("device_id")
                info["version"] = f"protocol {entry.get('version', '3.3')}"
            else:
                cache = _load_tuya_devices()
                logger = get_logger("discovery")
                for did, dev_entry in cache.get("devices", {}).items():
                    local_key = dev_entry.get("local_key", "")
                    if not local_key:
                        continue
                    version = dev_entry.get("version", 3.3)
                    device = _get_tuya_local(did, ip, local_key, version)
                    if device is None:
                        continue
                    try:
                        data = device.status()
                        if data and "dps" in data and "Error" not in str(data):
                            cache["devices"][did]["ip"] = ip
                            _save_tuya_devices(cache)
                            info["name"] = dev_entry.get("name", "Tuya_Device")
                            info["device_id"] = did
                            info["version"] = f"protocol {version}"
                            logger.info(
                                "Identified Tuya device %s at %s (%d DPS)",
                                dev_entry.get("name", did),
                                ip,
                                len(data.get("dps", {})),
                            )
                            break
                    except Exception:
                        continue
                else:
                    info["name"] = "Tuya_Device"
                    info["requires_registration"] = True
        except Exception:
            info["name"] = "Tuya_Device"
            info["requires_registration"] = True

    elif device_type == "openhasp":
        info["reachable"] = True
        try:
            from tools.openhasp.http_client import OpenHASPHTTPClient

            client = OpenHASPHTTPClient(ip, timeout=5)
            config = client.get_json("/config.json")
            if config:
                info["name"] = config.get("mqtt", {}).get("name", "OpenHASP")
                info["version"] = config.get("hasp", {}).get("version", "unknown")
                info["bckl"] = config.get("gui", {}).get("bckl", 0)
                info["objects_count"] = client.count_objects()
            else:
                info["name"] = "OpenHASP"
        except Exception:
            info["name"] = "OpenHASP"

    return info


def _scan_network(network_range: str, timeout: int = 5) -> list[str]:
    """Scan network with nmap and return list of alive IPs.

    Args:
        network_range: CIDR range to scan (e.g. "192.168.1.0/24").
        timeout: Unused (kept for API compatibility).

    Returns:
        List of alive IP addresses.

    Raises:
        RuntimeError: If nmap is not installed or scan fails.
    """
    del timeout  # nmap has its own timeout handling
    try:
        network_range = validate_cidr(network_range)
        # TODO: [L3] Check cancellation signal before starting nmap
        result = subprocess.run(
            ["nmap", "-sn", "-oG", "-", network_range],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )

        alive_ips: list[str] = []
        for line in result.stdout.splitlines():
            if "Host:" in line and "Status: Up" in line:
                ip_match = re.search(r"Host:\s+([\d.]+)", line)
                if ip_match:
                    alive_ips.append(ip_match.group(1))

        return alive_ips
    except FileNotFoundError as exc:
        raise RuntimeError("nmap is not installed. Install it with: apt-get install nmap") from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("nmap scan timed out (>120s). Try a smaller network range.") from exc
    except Exception as exc:
        raise RuntimeError(f"nmap scan failed: {exc}") from exc


# =============================================================================
# INTERNAL TOOL IMPLEMENTATIONS (testable)
# =============================================================================


def _iot_discover_devices(network_range: str | None = None, timeout_seconds: int = 10) -> str:
    """Discover OpenBK and Tasmota devices on the network using nmap.

    Args:
        network_range: CIDR range to scan (defaults to NETWORK_RANGE env or 192.168.1.0/24).
        timeout_seconds: Timeout per device probe in seconds.

    Returns:
        JSON string with discovered devices list and scan summary.
    """
    if network_range is None:
        network_range = DEFAULT_NETWORK_RANGE
    # Check nmap availability before attempting scan
    if not shutil.which("nmap"):
        return _error_response_extended(
            code="DEPENDENCY_MISSING",
            message="nmap is not installed. Install it with: apt-get install nmap",
            suggestion="Install nmap via your package manager (apt, dnf, brew). "
            "The Docker image includes it automatically.",
        )

    try:
        alive_ips = _scan_network(network_range, timeout_seconds)

        if not alive_ips:
            return _success_response(
                {
                    "total_found": 0,
                    "scanned_ips": 0,
                    "note": "No alive hosts found in the network range",
                }
            )

        devices: list[dict[str, Any]] = []
        for ip in alive_ips:
            # TODO: [L3] Check cancellation signal here for long scans
            device_type = _detect_device_type(ip, timeout_seconds)
            if device_type:
                info = _probe_device_info(ip, device_type, timeout_seconds)
                if info["reachable"]:
                    devices.append(info)

        _save_cache(devices)

        by_type: dict[str, list[dict[str, Any]]] = {}
        for device in devices:
            t = device["type"]
            by_type.setdefault(t, []).append(
                {
                    "ip": device["ip"],
                    "name": device.get("name", "Unknown"),
                    "rssi": device.get("rssi"),
                }
            )

        return _success_response(
            {
                "total_found": len(devices),
                "scanned_ips": len(alive_ips),
                "network_range": network_range,
                "cache_file": CACHE_FILE,
                "by_type": by_type,
                "devices": devices,
            }
        )

    except RuntimeError as exc:
        return _error_response_extended(code="INTERNAL_ERROR", message=str(exc))
    except Exception as exc:
        return _error_response_extended(code="INTERNAL_ERROR", message=f"Discovery failed: {exc}")


def _iot_list_devices() -> str:
    """List all discovered IoT devices from the local cache.

    Returns:
        JSON string with cached devices or suggestion to run discovery.
    """
    try:
        cache = _load_cache()
        devices = cache.get("devices", [])

        if not devices:
            return _success_response(
                {
                    "device_count": 0,
                    "cached": False,
                    "suggestion": (
                        "No devices in cache. Run iot_discover_devices() to scan the network."
                    ),
                    "devices": [],
                }
            )

        summary = [
            {
                "ip": d.get("ip"),
                "name": d.get("name", "Unknown"),
                "type": d.get("type"),
                "rssi": d.get("rssi"),
                "reachable": d.get("reachable", False),
            }
            for d in devices
        ]

        return _success_response(
            {
                "device_count": len(devices),
                "cached": True,
                "last_scan": cache.get("last_scan"),
                "cache_file": CACHE_FILE,
                "cache_fresh": _is_cache_fresh(),
                "devices": summary,
            }
        )

    except Exception as exc:
        return _error_response_extended(code="INTERNAL_ERROR", message=str(exc))


def _iot_check_device(ip_address: str, timeout_seconds: int = 10) -> str:
    """Check if a specific IP is an IoT device and identify its type.

    Args:
        ip_address: IP address to check.
        timeout_seconds: Request timeout in seconds.

    Returns:
        JSON string with device identification.
    """
    try:
        device_type = _detect_device_type(ip_address, timeout_seconds)

        if not device_type:
            return _success_response(
                {
                    "is_iot_device": False,
                    "ip": ip_address,
                    "note": "No IoT device detected at this IP",
                }
            )

        info = _probe_device_info(ip_address, device_type, timeout_seconds)

        return _success_response({"is_iot_device": True, "device": info})

    except Exception as exc:
        return _error_response_extended(code="INTERNAL_ERROR", message=str(exc))


def _iot_find_device_by_name(name: str) -> str:
    """Find a device in the cache by its friendly name (partial match supported).

    Args:
        name: Device name or part of it (case-insensitive).

    Returns:
        JSON string with matching device or error if not found.
    """
    try:
        device = _find_device_by_identifier(name)

        if not device:
            return _error_response_extended(
                code="NAME_NOT_RESOLVED",
                message=f"Device '{name}' not found in cache",
                suggestion=(
                    "Run iot_discover_devices() first, or check "
                    "iot_list_devices() for available names"
                ),
            )

        return _success_response({"device": device})

    except Exception as exc:
        return _error_response_extended(code="INTERNAL_ERROR", message=str(exc))


# =============================================================================
# MCP TOOL REGISTRATION
# =============================================================================


def register_iot_discovery_tools(mcp: Any) -> None:
    """Register IoT device discovery tools with the MCP server."""

    @mcp.tool()
    @inject_tool_risk_prefix
    def iot_discover_devices(network_range: str | None = None, timeout_seconds: int = 10) -> str:
        """Discover OpenBK and Tasmota devices on the network using nmap.

        Results are saved to a local cache file for fast lookups.
        The default scan range is configured via NETWORK_RANGE, START_IP, and END_IP env vars.

        Args:
            network_range: CIDR range to scan (e.g. "192.168.1.0/24"). Uses env default if not set.
            timeout_seconds: Timeout per device probe in seconds (default 10).

        Returns:
            JSON with discovered devices list and scan summary.

        @since v1.2.0
        """
        try:
            start_tool_context()
            increment_tool_count("iot_discover_devices")
            return _iot_discover_devices(network_range, timeout_seconds)
        except Exception as exc:
            return _error_response_extended(code="INTERNAL_ERROR", message=str(exc))

    @mcp.tool()
    @inject_tool_risk_prefix
    def iot_list_devices() -> str:
        """List all discovered IoT devices from the local cache.

        If the cache is empty, suggests running iot_discover_devices first.

        Returns:
            JSON with cached devices or suggestion to run discovery.

        @since v1.2.0
        """
        try:
            start_tool_context()
            increment_tool_count("iot_list_devices")
            return _iot_list_devices()
        except Exception as exc:
            return _error_response_extended(code="INTERNAL_ERROR", message=str(exc))

    @mcp.tool()
    @inject_tool_risk_prefix
    def iot_check_device(ip_address: str, timeout_seconds: int = 10) -> str:
        """Check if a specific IP is an IoT device and identify its type.

        Args:
            ip_address: IP address to check.
            timeout_seconds: Request timeout in seconds (default 10).

        Returns:
            JSON with device identification.

        @since v1.2.0
        """
        try:
            start_tool_context()
            increment_tool_count("iot_check_device")
            return _iot_check_device(ip_address, timeout_seconds)
        except Exception as exc:
            return _error_response_extended(code="INTERNAL_ERROR", message=str(exc))

    @mcp.tool()
    @inject_tool_risk_prefix
    def iot_find_device_by_name(name: str) -> str:
        """Find a device in the cache by its friendly name (partial match).

        Args:
            name: Device name or part of it (case-insensitive).

        Returns:
            JSON with matching device or error if not found.

        @since v1.2.0
        """
        try:
            start_tool_context()
            increment_tool_count("iot_find_device_by_name")
            return _iot_find_device_by_name(name)
        except Exception as exc:
            return _error_response_extended(code="INTERNAL_ERROR", message=str(exc))
