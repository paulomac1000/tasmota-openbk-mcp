# mypy: disable-error-code="untyped-decorator"
"""
Tuya IoT Device Tools

Local LAN control via tinytuya (encrypted TCP/UDP) with cloud API fallback.
Supports WiFi-connected devices, BT Gateway sub-devices, and offline devices.
"""

import json
import os
import socket
import threading
import time
from typing import Any

from tools.constants import (
    TUYA_ACCESS_ID,
    TUYA_ACCESS_SECRET,
    TUYA_DEVICES_FILE,
    _error_response_extended,
    _success_response,
    check_write_enabled,
    get_logger,
    increment_tool_count,
    inject_tool_risk_prefix,
    start_tool_context,
)
from tools.validators import ValidationError

__all__ = [
    "register_iot_tuya_tools",
    "_tuya_cloud_list",
    "_tuya_status",
    "_tuya_set_value",
    "_tuya_detect_version",
    "_tuya_verify_dps",
    "_tuya_scan_ports",
    "_tuya_cloud_refresh_keys",
    "_load_tuya_devices",
    "_save_tuya_devices",
    "_get_tuya_cloud",
    "_get_tuya_local",
]

# =============================================================================
# ENVIRONMENT CONFIGURATION
# =============================================================================

TUYA_PORTS = [6668, 6667, 6666]

# =============================================================================
# DPS SPECIFICATION (extendable per device type)
# =============================================================================

TUYA_DPS_SPEC = {
    "enums": {
        "4": {
            "name": "mode",
            "values": [
                "smart",
                "chargego",
                "zone",
                "pose",
                "part",
                "edge",
                "explore",
                "exploreclean",
            ],
        },
        "5": {
            "name": "status",
            "values": [
                "standby",
                "smart",
                "zone_clean",
                "part_clean",
                "cleaning",
                "paused",
                "goto_pos",
                "pos_arrived",
                "pos_unarrive",
                "goto_charge",
                "charging",
                "charge_done",
                "sleep",
                "edge",
                "explore",
                "explore_clean",
                "base_charging",
                "adapter_charging",
                "base_sleeping",
                "adapter_sleeping",
                "continuation_charging",
            ],
        },
        "9": {"name": "suction", "values": ["strong", "normal", "gentle", "max", "closed"]},
        "10": {"name": "cistern", "values": ["low", "middle", "high", "closed"]},
        "12": {
            "name": "direction_control",
            "values": ["foward", "forward", "backward", "turn_left", "turn_right", "stop"],
        },
        "16": {"name": "request", "values": ["get_map", "get_path", "get_both"]},
        "155": {"name": "cleaning_efficiency", "values": ["careful", "normal", "fast"]},
    },
    "integers": {
        "6": {"name": "clean_time", "min": 0, "max": 9999, "unit": "min"},
        "7": {"name": "clean_area", "min": 0, "max": 9999, "unit": "m2"},
        "8": {"name": "battery", "min": 0, "max": 100, "unit": "%"},
        "17": {"name": "edge_brush", "min": 0, "max": 900, "unit": "min"},
        "19": {"name": "roll_brush", "min": 0, "max": 1800, "unit": "min"},
        "21": {"name": "filter", "min": 0, "max": 900, "unit": "min"},
        "26": {"name": "volume", "min": 0, "max": 10, "unit": "%"},
        "29": {"name": "total_area", "min": 0, "max": 2073741824, "unit": "m2"},
        "30": {"name": "total_count", "min": 0, "max": 2073741824},
        "31": {"name": "total_time", "min": 0, "max": 2073741824, "unit": "min"},
        "37": {"name": "dust_collection_num", "min": 0, "max": 99999},
        "127": {"name": "init_status", "min": 0, "max": 255},
        "137": {"name": "robot_info", "min": 0, "max": 1073741824},
        "138": {"name": "language", "min": 0, "max": 255},
        "145": {"name": "pending_save_map", "min": 0, "max": 2073741824},
    },
    "bools": {
        "1": "switch_go",
        "2": "pause",
        "3": "switch_charge",
        "11": "seek",
        "13": "reset_map",
        "18": "reset_edge_brush",
        "20": "reset_roll_brush",
        "22": "reset_filter",
        "25": "switch_disturb",
        "27": "break_clean",
        "38": "dust_collection_switch",
        "45": "auto_boost",
        "149": "y_mop",
        "150": "clean_edge_brush",
        "151": "clean_roll_brush",
        "152": "clean_filter",
    },
    # Kettle-specific (example kettle device):
    "kettle_integers": {
        "10": {"name": "target_temp", "min": 0, "max": 100, "unit": "C"},
        "11": {"name": "current_temp", "min": 0, "max": 100, "unit": "C"},
        "14": {"name": "keep_warm_min", "min": 0, "max": 240, "unit": "min"},
    },
    "kettle_enums": {
        "12": {"name": "temp_unit", "values": ["c", "f"]},
        "15": {"name": "status", "values": ["standby", "heating", "keep_warm", "done"]},
        "16": {"name": "mode", "values": ["temp_setting", "boil", "keep_warm"]},
    },
    "kettle_bools": {
        "1": "power",
        "13": "keep_warm_enabled",
    },
}

# =============================================================================
# TUYA CLIENT FACTORIES
# =============================================================================

_tinytuya_imported = False
_tinytuya = None


def _import_tinytuya() -> bool:
    """Lazy-import tinytuya; returns True if available."""
    global _tinytuya_imported, _tinytuya
    if _tinytuya_imported:
        return _tinytuya is not None
    _tinytuya_imported = True
    try:
        import tinytuya

        _tinytuya = tinytuya
        return True
    except ImportError:
        return False


def _get_tuya_cloud() -> Any | None:
    """Get a configured Tuya Cloud client.

    Returns:
        tinytuya.Cloud instance or None if credentials not set or library missing.
    """
    if not _import_tinytuya():
        return None
    if not all([TUYA_ACCESS_ID, TUYA_ACCESS_SECRET]):
        return None
    try:
        return _tinytuya.Cloud(
            apiRegion="eu",
            apiKey=TUYA_ACCESS_ID,
            apiSecret=TUYA_ACCESS_SECRET,
        )
    except Exception as exc:
        get_logger("tuya").warning("Failed to create cloud client: %s", exc)
        return None


def _get_tuya_local(device_id: str, ip: str, local_key: str, version: float = 3.3) -> Any | None:
    """Get a configured tinytuya.Device for local LAN access.

    Args:
        device_id: Tuya device ID (from cloud).
        ip: Device IP address on local network.
        local_key: Local key (from cloud API).
        version: Protocol version (3.1-3.5).

    Returns:
        tinytuya.Device instance or None if library not available.
    """
    if not _import_tinytuya():
        return None
    try:
        d = _tinytuya.Device(device_id, ip, local_key)
        d.set_version(version)
        d.set_socketTimeout(5)
        d.set_socketRetryLimit(1)
        return d
    except Exception as exc:
        get_logger("tuya").warning("Failed to create local client for %s: %s", device_id, exc)
        return None


# =============================================================================
# TUYA DEVICE CACHE (data/tuya_devices.json)
# =============================================================================

_cache_lock = threading.Lock()


def _load_tuya_devices() -> dict[str, Any]:
    """Load Tuya device credentials from local cache.

    Returns:
        Cache dict with shape {"version": 1, "devices": {device_id: {...}}}.
    """
    default = {"version": 1, "devices": {}}
    try:
        with _cache_lock:
            if not os.path.exists(TUYA_DEVICES_FILE):
                return default
            with open(TUYA_DEVICES_FILE) as f:
                data = json.load(f)
            if not isinstance(data, dict) or "devices" not in data:
                return default
            return data
    except (json.JSONDecodeError, OSError) as exc:
        get_logger("tuya").warning("Failed to load Tuya cache: %s", exc)
        return default


def _save_tuya_devices(devices_data: dict[str, Any]) -> None:
    """Save Tuya device credentials to local cache.

    Args:
        devices_data: Cache dict with {"version": 1, "devices": {...}}.
    """
    os.makedirs(os.path.dirname(TUYA_DEVICES_FILE) or ".", exist_ok=True)
    tmp_path = TUYA_DEVICES_FILE + ".tmp"
    try:
        with _cache_lock:
            with open(tmp_path, "w") as f:
                json.dump(devices_data, f, indent=2, default=str)
            os.replace(tmp_path, TUYA_DEVICES_FILE)
    except OSError as exc:
        get_logger("tuya").warning("Failed to save Tuya cache: %s", exc)


def _find_tuya_in_cache(identifier: str) -> dict[str, Any] | None:
    """Find a Tuya device in cache by device_id, IP, or name.

    Args:
        identifier: device_id, IP address, or device name.

    Returns:
        Device entry dict or None.
    """
    cache = _load_tuya_devices()
    devices = cache.get("devices", {})

    if identifier in devices:
        return devices[identifier]

    for did, entry in devices.items():
        if entry.get("ip") == identifier:
            return entry
        name = entry.get("name", "")
        if name and name.lower() == identifier.lower():
            return entry

    for did, entry in devices.items():
        name = entry.get("name", "")
        if name and identifier.lower() in name.lower() and len(identifier) >= 3:
            return entry

    return None


# =============================================================================
# OPERATIONS: CLOUD API
# =============================================================================


def _tuya_cloud_refresh_keys() -> str:
    """Fetch all devices from Tuya cloud and store their local keys in cache.

    Returns:
        JSON with device list and cache status.
    """
    if not all([TUYA_ACCESS_ID, TUYA_ACCESS_SECRET]):
        return _error_response_extended(
            code="MISSING_CREDENTIALS",
            message="TUYA_ACCESS_ID or TUYA_ACCESS_SECRET not configured",
            suggestion="Set TUYA_ACCESS_ID and TUYA_ACCESS_SECRET in .env.",
        )

    cloud = _get_tuya_cloud()
    if cloud is None:
        return _error_response_extended(
            code="DEPENDENCY_MISSING",
            message="tinytuya not installed. Install with: pip install tinytuya",
        )

    try:
        devices = cloud.getdevices()
    except Exception as exc:
        return _error_response_extended(
            code="CLOUD_API_ERROR",
            message=f"Failed to fetch devices from Tuya cloud: {exc}",
            retryable=True,
        )

    cache = _load_tuya_devices()
    registered = 0
    updated_keys = 0
    device_list: list[dict[str, Any]] = []

    for dev in devices:
        did = dev.get("id", "")
        name = dev.get("name", "Unknown")
        ip = dev.get("ip", "")
        local_key = dev.get("key") or dev.get("local_key", "")

        online = False
        if did:
            try:
                online = bool(cloud.getconnectstatus(did))
            except Exception:
                pass

        entry: dict[str, Any] = {
            "device_id": did,
            "name": name,
            "ip": ip,
            "online": online,
        }

        if did and local_key:
            existing = cache["devices"].get(did, {})
            cache["devices"][did] = {
                "device_id": did,
                "name": name,
                "ip": ip if ip else existing.get("ip", ""),
                "local_key": local_key,
                "version": existing.get("version", 3.3),
                "power_dp_id": existing.get("power_dp_id", "1"),
                "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            }
            if not existing:
                registered += 1
            elif str(existing.get("local_key")) != str(local_key):
                updated_keys += 1
            entry["cached"] = True
        else:
            entry["cached"] = False

        device_list.append(entry)

    _save_tuya_devices(cache)

    return _success_response(
        {
            "devices_found": len(device_list),
            "devices_cached": registered + updated_keys,
            "newly_registered": registered,
            "updated_keys": updated_keys,
            "devices": device_list,
        }
    )


def _tuya_cloud_list() -> str:
    """List Tuya cloud devices without modifying the local credential cache.

    Returns:
        JSON with sanitized cloud device metadata only.
    """
    if not all([TUYA_ACCESS_ID, TUYA_ACCESS_SECRET]):
        return _error_response_extended(
            code="MISSING_CREDENTIALS",
            message="TUYA_ACCESS_ID or TUYA_ACCESS_SECRET not configured",
            suggestion="Set TUYA_ACCESS_ID and TUYA_ACCESS_SECRET in .env.",
        )

    cloud = _get_tuya_cloud()
    if cloud is None:
        return _error_response_extended(
            code="DEPENDENCY_MISSING",
            message="tinytuya not installed. Install with: pip install tinytuya",
        )

    try:
        devices = cloud.getdevices()
    except Exception as exc:
        return _error_response_extended(
            code="CLOUD_API_ERROR",
            message=f"Failed to fetch devices from Tuya cloud: {exc}",
            retryable=True,
        )

    cache = _load_tuya_devices()
    cached_ids = set(cache.get("devices", {}))
    device_list: list[dict[str, Any]] = []

    for dev in devices:
        did = dev.get("id", "")
        online = False
        if did:
            try:
                online = bool(cloud.getconnectstatus(did))
            except Exception:
                pass
        device_list.append(
            {
                "device_id": did,
                "name": dev.get("name", "Unknown"),
                "ip": dev.get("ip", ""),
                "online": online,
                "cached": did in cached_ids,
            }
        )

    return _success_response(
        {
            "devices_found": len(device_list),
            "devices_cached": len([d for d in device_list if d["cached"]]),
            "devices": device_list,
        }
    )


# =============================================================================
# OPERATIONS: LOCAL CONTROL
# =============================================================================


def _tuya_status(identifier: str, prefer: str = "local") -> str:
    """Get DPS from a Tuya device.

    Tries local first, falls back to cloud if local fails.

    Args:
        identifier: device_id, IP, or device name.
        prefer: "local" (try local first) or "cloud" (cloud only).

    Returns:
        JSON with DPS dictionary.
    """
    entry = _find_tuya_in_cache(identifier)
    if not entry:
        return _error_response_extended(
            code="TUYA_NOT_FOUND",
            message=f"Tuya device '{identifier}' not found in cache",
            suggestion="Run iot_tuya_cloud_refresh_keys() first.",
        )

    did = entry["device_id"]
    ip = entry.get("ip", "")
    local_key = entry.get("local_key", "")
    version = entry.get("version", 3.3)

    if prefer != "cloud" and ip and local_key:
        device = _get_tuya_local(did, ip, local_key, version)
        if device:
            try:
                data = device.status()
                if data and "dps" in data:
                    return _success_response(
                        {
                            "device_id": did,
                            "name": entry["name"],
                            "ip": ip,
                            "transport": "local",
                            "dps": data["dps"],
                            "dps_spec": _enrich_dps_with_spec(data["dps"]),
                        }
                    )
            except Exception as exc:
                get_logger("tuya").warning("Local status failed for %s: %s", did, exc)

    cloud = _get_tuya_cloud()
    if cloud is None:
        return _error_response_extended(
            code="DEVICE_UNREACHABLE",
            message=f"Local connection failed for '{identifier}' and cloud not configured",
            suggestion="Ensure the device is online and cloud credentials are set.",
        )

    try:
        status = cloud.getstatus(did)
        if status and "result" in status:
            raw_status = status["result"]
            dps = {}
            for st in raw_status:
                code = st.get("code", "")
                val = st.get("value")
                if code:
                    dps[code] = val
            return _success_response(
                {
                    "device_id": did,
                    "name": entry["name"],
                    "online": True,
                    "transport": "cloud",
                    "dps": dps,
                    "dps_spec": _enrich_dps_with_spec(dps),
                }
            )
        return _error_response_extended(
            code="DEVICE_NOT_FOUND",
            message=f"Device '{did}' returned no status from cloud",
        )
    except Exception as exc:
        return _error_response_extended(
            code="DEVICE_UNREACHABLE",
            message=f"Local and cloud access failed for '{identifier}': {exc}",
        )


def _tuya_set_value(identifier: str, dp_id: str, value: Any, prefer: str = "local") -> str:
    """Set a DPS value on a Tuya device.

    Tries local first, falls back to cloud.

    Args:
        identifier: device_id, IP, or device name.
        dp_id: DPS ID to set (as string, e.g. "1").
        value: Value to set. Auto-detected type: bool, int, str.

    Returns:
        JSON with result.
    """
    if isinstance(value, str):
        if value.lower() == "true":
            value = True
        elif value.lower() == "false":
            value = False
        elif value.isdigit():
            value = int(value)

    entry = _find_tuya_in_cache(identifier)
    if not entry:
        return _error_response_extended(
            code="TUYA_NOT_FOUND",
            message=f"Tuya device '{identifier}' not found in cache",
            suggestion="Run iot_tuya_cloud_refresh_keys() first.",
        )

    did = entry["device_id"]
    ip = entry.get("ip", "")
    local_key = entry.get("local_key", "")
    version = entry.get("version", 3.3)

    if prefer != "cloud" and ip and local_key:
        device = _get_tuya_local(did, ip, local_key, version)
        if device:
            try:
                result = device.set_value(dp_id, value)
                time.sleep(0.5)
                verify = device.status()
                current_val = verify.get("dps", {}).get(dp_id) if verify else None
                return _success_response(
                    {
                        "device_id": did,
                        "name": entry["name"],
                        "transport": "local",
                        "dp_id": dp_id,
                        "set_value": value,
                        "current_value": current_val,
                        "result": str(result),
                    }
                )
            except Exception as exc:
                get_logger("tuya").warning("Local set failed for %s: %s", did, exc)

    cloud = _get_tuya_cloud()
    if cloud is None:
        return _error_response_extended(
            code="DEVICE_UNREACHABLE",
            message="Local connection failed and cloud not configured",
            suggestion="Set TUYA_ACCESS_ID/TUYA_ACCESS_SECRET or ensure device is online locally.",
        )

    try:
        commands = [{"code": dp_id, "value": value}]
        cloud.sendcommand(did, commands)
        time.sleep(1)
        status = cloud.getstatus(did)
        current_val = None
        if status and "result" in status:
            for st in status["result"]:
                if st.get("code") == dp_id:
                    current_val = st.get("value")
                    break
        return _success_response(
            {
                "device_id": did,
                "name": entry["name"],
                "transport": "cloud",
                "dp_id": dp_id,
                "set_value": value,
                "current_value": current_val,
            }
        )
    except Exception as exc:
        return _error_response_extended(
            code="DEVICE_UNREACHABLE",
            message=f"Failed to set DP {dp_id} on '{identifier}': {exc}",
        )


def _tuya_detect_version(identifier: str) -> str:
    """Auto-detect the Tuya protocol version for a device.

    Safe - only sends DP_QUERY payloads, never writes.

    Args:
        identifier: device_id, IP, or device name.

    Returns:
        JSON with working version and current DPS.
    """
    entry = _find_tuya_in_cache(identifier)
    if not entry:
        return _error_response_extended(
            code="TUYA_NOT_FOUND",
            message=f"Tuya device '{identifier}' not found in cache",
        )

    if not _import_tinytuya():
        return _error_response_extended(
            code="DEPENDENCY_MISSING",
            message="tinytuya not installed. Install with: pip install tinytuya",
        )

    did = entry["device_id"]
    ip = entry.get("ip", "")
    local_key = entry.get("local_key", "")

    if not ip or not local_key:
        return _error_response_extended(
            code="MISSING_CREDENTIALS",
            message="Device has no IP or local_key in cache",
            suggestion="Run iot_tuya_cloud_refresh_keys() to populate credentials.",
        )

    versions_to_try = [
        (3.5, False, "3.5"),
        (3.4, False, "3.4"),
        (3.3, False, "3.3"),
        (3.3, True, "3.22 (device22)"),
        (3.2, False, "3.2"),
        (3.1, False, "3.1"),
    ]

    logger = get_logger("tuya")
    results: dict[str, Any] = {}

    for ver, use_device22, label in versions_to_try:
        try:
            if use_device22:
                d = _tinytuya.Device(did, ip, local_key, dev_type="device22", version=ver)
            else:
                d = _tinytuya.Device(did, ip, local_key)
                d.version = ver
                d.version_bytes = str(ver).encode("latin1")
                d.version_header = str(ver).encode("latin1")
                version_map = {3.2: b"3.2", 3.3: b"3.3", 3.4: b"3.4", 3.5: b"3.5"}
                if ver in version_map:
                    d.version_bytes = version_map[ver]
                    d.version_header = version_map[ver]

            d.set_socketTimeout(5)
            d.set_socketRetryLimit(1)

            payload = d.generate_payload(_tinytuya.DP_QUERY)
            d.send(payload)
            data = d.receive()

            if data and "dps" in data and "Error" not in str(data):
                results[label] = {
                    "version": ver,
                    "label": label,
                    "device22": use_device22,
                    "dps": data["dps"],
                }
                logger.info("Tuya version %s works for %s (%d DPS)", label, did, len(data["dps"]))
        except Exception:
            pass

    if not results:
        return _error_response_extended(
            code="DEVICE_UNREACHABLE",
            message=f"Could not find working protocol version for '{identifier}'",
            suggestion="Check device online, correct local_key, close Tuya app.",
        )

    best = list(results.values())[0]
    cache = _load_tuya_devices()
    if did in cache.get("devices", {}):
        cache["devices"][did]["version"] = best["version"]
        _save_tuya_devices(cache)

    return _success_response(
        {
            "device_id": did,
            "name": entry["name"],
            "recommended_version": best["label"],
            "recommended_version_num": best["version"],
            "tested_versions": list(results.keys()),
            "total_tested": len(versions_to_try),
            "working_count": len(results),
            "dps": best["dps"],
            "dps_count": len(best["dps"]),
        }
    )


def _tuya_verify_dps(identifier: str, spec: dict[str, Any] | None = None) -> str:
    """Verify DPS values against a known specification.

    Args:
        identifier: device_id, IP, or device name.
        spec: Optional custom DPS spec. Uses built-in TUYA_DPS_SPEC if not provided.

    Returns:
        JSON with verification results per DPS.
    """
    result_raw = _tuya_status(identifier)
    try:
        parsed = json.loads(result_raw)
    except json.JSONDecodeError:
        return result_raw
    except TypeError:
        return result_raw

    if not parsed.get("success"):
        return result_raw

    dps = parsed.get("data", {}).get("dps", {})
    if not dps:
        return _error_response_extended(
            code="NO_DPS_DATA",
            message="No DPS data received from device",
        )

    use_spec = spec or TUYA_DPS_SPEC
    # Merge kettle-specific keys if using built-in spec
    if not spec:
        enums_spec = {**use_spec.get("enums", {}), **use_spec.get("kettle_enums", {})}
        ints_spec = {**use_spec.get("integers", {}), **use_spec.get("kettle_integers", {})}
        bools_spec = {**use_spec.get("bools", {}), **use_spec.get("kettle_bools", {})}
    else:
        enums_spec = use_spec.get("enums", {})
        ints_spec = use_spec.get("integers", {})
        bools_spec = use_spec.get("bools", {})
        # Also merge kettle if user-provided spec has them
        enums_spec = {**enums_spec, **use_spec.get("kettle_enums", {})}
        ints_spec = {**ints_spec, **use_spec.get("kettle_integers", {})}
        bools_spec = {**bools_spec, **use_spec.get("kettle_bools", {})}

    all_known: set[str] = set(enums_spec) | set(ints_spec) | set(bools_spec)

    results_enum: list[dict[str, Any]] = []
    results_int: list[dict[str, Any]] = []
    results_bool: list[dict[str, Any]] = []
    unknown: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []

    for dp_id, spec_info in sorted(enums_spec.items(), key=lambda x: int(x[0])):
        entry = {"dp_id": dp_id, "name": spec_info["name"]}
        if dp_id in dps:
            val = dps[dp_id]
            ok = val in spec_info["values"]
            entry["value"] = val
            entry["valid"] = ok
            if not ok:
                entry["expected"] = spec_info["values"]
            results_enum.append(entry)
        else:
            entry["present"] = False
            missing.append(entry)

    for dp_id, spec_info in sorted(ints_spec.items(), key=lambda x: int(x[0])):
        entry = {"dp_id": dp_id, "name": spec_info["name"]}
        if dp_id in dps:
            val = dps[dp_id]
            ok = isinstance(val, (int, float)) and spec_info["min"] <= val <= spec_info["max"]
            entry["value"] = val
            entry["valid"] = ok
            entry["unit"] = spec_info.get("unit", "")
            results_int.append(entry)
        else:
            entry["present"] = False
            missing.append(entry)

    for dp_id, name in sorted(bools_spec.items(), key=lambda x: int(x[0])):
        entry = {"dp_id": dp_id, "name": name}
        if dp_id in dps:
            val = dps[dp_id]
            ok = isinstance(val, bool)
            entry["value"] = val
            entry["valid"] = ok
            results_bool.append(entry)
        else:
            entry["present"] = False
            missing.append(entry)

    for dp_id in sorted(dps.keys(), key=lambda x: int(x)):
        if dp_id not in all_known:
            val = dps[dp_id]
            val_repr = repr(val)
            if len(val_repr) > 100:
                val_repr = val_repr[:97] + "..."
            unknown.append({"dp_id": dp_id, "value": val_repr, "type": type(val).__name__})

    errors = sum(
        1
        for r in results_enum + results_int + results_bool
        if r.get("present", True) and not r.get("valid", True)
    )

    return _success_response(
        {
            "device_id": parsed.get("data", {}).get("device_id"),
            "transport": parsed.get("data", {}).get("transport"),
            "dps_total": len(dps),
            "total_checks": len(all_known),
            "errors_found": errors,
            "missing_in_device": len([m for m in missing]),
            "unknown_in_device": len(unknown),
            "results": {
                "enum": results_enum,
                "integer": results_int,
                "bool": results_bool,
                "unknown": unknown,
                "missing": missing[:20],
            },
            "all_valid": errors == 0 and len(unknown) == 0,
        }
    )


def _tuya_scan_ports(network_range: str | None = None) -> str:
    """Scan local network for open Tuya TCP ports (6666-6668).

    Args:
        network_range: Optional CIDR range. Uses env default if not set.

    Returns:
        JSON with list of IPs that have Tuya ports open.
    """
    if network_range is None:
        from tools.constants import DEFAULT_NETWORK_RANGE

        network_range = DEFAULT_NETWORK_RANGE

    from tools.constants import END_IP, START_IP

    start_octets = START_IP.split(".")
    end_octets = END_IP.split(".")

    if len(start_octets) != 4 or len(end_octets) != 4:
        return _error_response_extended(
            code="INVALID_PARAM",
            message="Invalid network range configuration",
        )

    base = ".".join(start_octets[:3])
    start_last = int(start_octets[3])
    end_last = int(end_octets[3])

    found: list[dict[str, Any]] = []

    for last in range(start_last, min(end_last + 1, start_last + 20)):
        ip = f"{base}.{last}"
        for port in TUYA_PORTS:
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(1)
                result = sock.connect_ex((ip, port))
                sock.close()
                if result == 0:
                    found.append({"ip": ip, "port": port, "type": "tuya"})
                    break
            except Exception:
                pass

    if not found:
        return _success_response(
            {
                "ips_scanned": min(end_last - start_last + 1, 20),
                "ports_checked": TUYA_PORTS,
                "devices_found": 0,
                "devices": [],
                "note": (
                    f"Scanned first 20 IPs in {base}.{start_last}"
                    f"-{base}.{min(end_last, start_last + 19)}."
                ),
            }
        )

    return _success_response(
        {
            "ips_scanned": min(end_last - start_last + 1, 20),
            "ports_checked": TUYA_PORTS,
            "devices_found": len(found),
            "devices": found,
        }
    )


def _enrich_dps_with_spec(dps: dict[str, Any]) -> dict[str, Any]:
    """Add spec metadata to DPS values for display."""
    enriched: dict[str, dict[str, Any]] = {}
    enums = {
        **TUYA_DPS_SPEC.get("enums", {}),
        **TUYA_DPS_SPEC.get("kettle_enums", {}),
    }
    integers = {
        **TUYA_DPS_SPEC.get("integers", {}),
        **TUYA_DPS_SPEC.get("kettle_integers", {}),
    }
    bools = {
        **TUYA_DPS_SPEC.get("bools", {}),
        **TUYA_DPS_SPEC.get("kettle_bools", {}),
    }

    for dp_id, value in dps.items():
        entry: dict[str, Any] = {"value": value}
        if dp_id in enums:
            entry["name"] = enums[dp_id]["name"]
            entry["type"] = "enum"
            entry["valid"] = value in enums[dp_id]["values"]
        elif dp_id in integers:
            entry["name"] = integers[dp_id]["name"]
            entry["type"] = "integer"
            entry["unit"] = integers[dp_id].get("unit", "")
            valid = isinstance(value, (int, float))
            if valid:
                valid = integers[dp_id]["min"] <= value <= integers[dp_id]["max"]
            entry["valid"] = valid
        elif dp_id in bools:
            entry["name"] = bools[dp_id]
            entry["type"] = "bool"
            entry["valid"] = isinstance(value, bool)
        else:
            entry["type"] = "unknown"
            entry["valid"] = True
        enriched[dp_id] = entry
    return enriched


def _tuya_monitor(identifier: str, duration_seconds: int = 30) -> str:
    """Monitor DPS changes on a Tuya device in real-time.

    Opens a persistent TCP socket, reads initial DPS snapshot, then listens
    for changes for the specified duration. Useful for debugging -
    operate the device physically or via the app to see DPS changes.

    Args:
        identifier: device_id, IP, or device name.
        duration_seconds: How long to monitor (1-120, default 30).

    Returns:
        JSON with initial DPS snapshot and list of changes with timestamps.
    """
    if duration_seconds < 1:
        duration_seconds = 1
    if duration_seconds > 120:
        duration_seconds = 120

    entry = _find_tuya_in_cache(identifier)
    if not entry:
        return _error_response_extended(
            code="TUYA_NOT_FOUND",
            message=f"Tuya device '{identifier}' not found in cache",
            suggestion="Run iot_tuya_cloud_refresh_keys() first.",
        )

    if not _import_tinytuya():
        return _error_response_extended(
            code="DEPENDENCY_MISSING",
            message="tinytuya not installed. Install with: pip install tinytuya",
        )

    did = entry["device_id"]
    ip = entry["ip"]
    local_key = entry["local_key"]
    version = entry.get("version", 3.3)

    if not ip or not local_key:
        return _error_response_extended(
            code="DEVICE_UNREACHABLE",
            message="Device has no IP or local_key - cannot open persistent connection",
            suggestion="Run iot_tuya_cloud_refresh_keys() to populate credentials.",
        )

    logger = get_logger("tuya")

    try:
        d = _tinytuya.Device(did, ip, local_key)
        d.set_version(version)
        d.set_socketPersistent(True)
        d.set_socketTimeout(3)
    except Exception as exc:
        return _error_response_extended(
            code="DEVICE_UNREACHABLE",
            message=f"Failed to connect to {ip}: {exc}",
        )

    try:
        initial = d.status()
    except Exception as exc:
        return _error_response_extended(
            code="DEVICE_UNREACHABLE",
            message=f"Failed to get initial status from {ip}: {exc}",
        )

    if not initial or "dps" not in initial:
        return _error_response_extended(
            code="DEVICE_UNREACHABLE",
            message="Device returned no DPS data",
        )

    initial_dps = initial["dps"]
    changes: list[dict[str, Any]] = []
    start_time = time.time()
    deadline = start_time + duration_seconds

    logger.info(
        "Monitoring %s (%s) for %ds, initial DPS: %d",
        entry.get("name", did),
        ip,
        duration_seconds,
        len(initial_dps),
    )

    while time.time() < deadline:
        try:
            data = d.receive()
            if data and "dps" in data:
                ts = time.strftime("%H:%M:%S")
                elapsed = round(time.time() - start_time, 1)
                for dp_id, val in sorted(data["dps"].items(), key=lambda x: int(x[0])):
                    old_val = initial_dps.get(dp_id, "(unknown)")
                    val_repr = repr(val)
                    if len(val_repr) > 80:
                        val_repr = val_repr[:77] + "..."
                    changes.append(
                        {
                            "timestamp": ts,
                            "elapsed_seconds": elapsed,
                            "dp_id": dp_id,
                            "previous_value": old_val,
                            "new_value": val,
                        }
                    )
        except Exception:
            time.sleep(0.5)

    try:
        d.close()
    except Exception:
        pass

    return _success_response(
        {
            "device_id": did,
            "name": entry.get("name", did),
            "ip": ip,
            "duration_seconds": duration_seconds,
            "changes_count": len(changes),
            "initial_dps": initial_dps,
            "initial_dps_count": len(initial_dps),
            "changes": changes,
            "note": (
                f"Monitored for {duration_seconds}s. "
                f"Found {len(changes)} changes across {len(initial_dps)} DPS. "
                "Operate the device physically or via the app to trigger more changes."
            ),
        }
    )


# =============================================================================
# TOOL REGISTRATION
# =============================================================================


def register_iot_tuya_tools(mcp: Any) -> None:
    """Register Tuya IoT tools with the MCP server."""

    @mcp.tool()
    @inject_tool_risk_prefix
    def iot_tuya_cloud_list() -> str:
        """List all Tuya devices from the cloud account.

        Returns:
            JSON with device list, online/offline status, and cache status.

        @since v1.4.0
        """
        try:
            start_tool_context()
            increment_tool_count("iot_tuya_cloud_list")
            return _tuya_cloud_list()
        except Exception as exc:
            return _error_response_extended(code="INTERNAL_ERROR", message=str(exc))

    @mcp.tool()
    @inject_tool_risk_prefix
    def iot_tuya_cloud_refresh_keys() -> str:
        """Fetch local keys for all Tuya devices from the cloud and store in cache.

        Returns:
            JSON with cache update summary.

        @since v1.4.0
        """
        try:
            start_tool_context()
            check_write_enabled()
            increment_tool_count("iot_tuya_cloud_refresh_keys")
            return _tuya_cloud_refresh_keys()
        except ValidationError as exc:
            return _error_response_extended(
                code="WRITE_DISABLED",
                message=str(exc),
                suggestion="Ask the server operator to set ENABLE_WRITE_OPERATIONS=1.",
            )
        except Exception as exc:
            return _error_response_extended(code="INTERNAL_ERROR", message=str(exc))

    @mcp.tool()
    @inject_tool_risk_prefix
    def iot_tuya_cloud_control(device_id: str, dp_id: str, value: str) -> str:
        """Control a Tuya device via cloud API (useful for gateway sub-devices).

        Args:
            device_id: Tuya device ID (e.g. "bf5397fdf1491fc79ac2gr").
            dp_id: DPS ID to set (e.g. "1" for power).
            value: Value to set. Auto-detected type (bool, int, str).

        Returns:
            JSON with result.

        @since v1.4.0
        """
        try:
            start_tool_context()
            check_write_enabled()
            increment_tool_count("iot_tuya_cloud_control")
            return _tuya_set_value(device_id, dp_id, value, prefer="cloud")
        except ValidationError as exc:
            return _error_response_extended(
                code="WRITE_DISABLED",
                message=str(exc),
                suggestion="Ask the server operator to set ENABLE_WRITE_OPERATIONS=1.",
            )
        except Exception as exc:
            return _error_response_extended(code="INTERNAL_ERROR", message=str(exc))

    @mcp.tool()
    @inject_tool_risk_prefix
    def iot_tuya_get_dps(identifier: str, dp_id: str | None = None) -> str:
        """Get DPS (Data Points) from a Tuya device.

        Tries local connection first, falls back to cloud API.

        Args:
            identifier: Device ID, IP address, or device name from cache.
            dp_id: Optional specific DPS ID to return. If omitted, returns all.

        Returns:
            JSON with DPS dictionary and spec metadata.

        @since v1.4.0
        """
        try:
            start_tool_context()
            increment_tool_count("iot_tuya_get_dps")
            result = _tuya_status(identifier)
            if dp_id is not None:
                parsed = json.loads(result)
                if parsed.get("success"):
                    dps = parsed.get("data", {}).get("dps", {})
                    if dp_id in dps:
                        return _success_response(
                            {
                                "dp_id": dp_id,
                                "value": dps[dp_id],
                                "spec": _enrich_dps_with_spec(dps).get(dp_id, {}),
                                "device_id": parsed["data"].get("device_id"),
                                "transport": parsed["data"].get("transport"),
                            }
                        )
                    return _error_response_extended(
                        code="DP_NOT_FOUND",
                        message=f"DP {dp_id} not found. Available: {list(dps.keys())}",
                    )
            return result
        except Exception as exc:
            return _error_response_extended(code="INTERNAL_ERROR", message=str(exc))

    @mcp.tool()
    @inject_tool_risk_prefix
    def iot_tuya_set_dp(identifier: str, dp_id: str, value: str) -> str:
        """Set a DPS (Data Point) value on a Tuya device.

        Tries local connection first, falls back to cloud API.

        Args:
            identifier: Device ID, IP address, or device name from cache.
            dp_id: DPS ID to set (e.g. "1" for power switch).
            value: Value to set. Auto-detected type: "true"/"false" -> bool,
                "123" -> int, otherwise string.

        Returns:
            JSON with result and current value after set.

        @since v1.4.0
        """
        try:
            start_tool_context()
            check_write_enabled()
            increment_tool_count("iot_tuya_set_dp")
            return _tuya_set_value(identifier, dp_id, value)
        except ValidationError as exc:
            return _error_response_extended(
                code="WRITE_DISABLED",
                message=str(exc),
                suggestion="Ask the server operator to set ENABLE_WRITE_OPERATIONS=1.",
            )
        except Exception as exc:
            return _error_response_extended(code="INTERNAL_ERROR", message=str(exc))

    @mcp.tool()
    @inject_tool_risk_prefix
    def iot_tuya_detect_version(identifier: str) -> str:
        """Auto-detect the Tuya protocol version for a device.

        Safe - only sends DP_QUERY (read) payloads. Never writes to the device.

        Args:
            identifier: Device ID, IP address, or device name from cache.

        Returns:
            JSON with recommended version and current DPS.

        @since v1.4.0
        """
        try:
            start_tool_context()
            increment_tool_count("iot_tuya_detect_version")
            return _tuya_detect_version(identifier)
        except Exception as exc:
            return _error_response_extended(code="INTERNAL_ERROR", message=str(exc))

    @mcp.tool()
    @inject_tool_risk_prefix
    def iot_tuya_verify_dps(identifier: str, spec: str | None = None) -> str:
        """Verify a device's DPS values against a known specification.

        Uses the built-in vacuum DPS spec by default. Provide a custom spec
        JSON string for other device types.

        Args:
            identifier: Device ID, IP address, or device name from cache.
            spec: Optional JSON string with custom DPS specification
                (shape: {"enums": {...}, "integers": {...}, "bools": {...}}).

        Returns:
            JSON with verification results per DPS.

        @since v1.4.0
        """
        try:
            start_tool_context()
            increment_tool_count("iot_tuya_verify_dps")
            spec_dict = None
            if spec is not None:
                spec_dict = json.loads(spec) if isinstance(spec, str) else spec
                if not isinstance(spec_dict, dict):
                    return _error_response_extended(
                        code="INVALID_PARAM",
                        message="spec must be a JSON object with enums/integers/bools keys",
                    )
            return _tuya_verify_dps(identifier, spec_dict)
        except json.JSONDecodeError:
            return _error_response_extended(
                code="INVALID_PARAM",
                message="spec is not valid JSON",
            )
        except Exception as exc:
            return _error_response_extended(code="INTERNAL_ERROR", message=str(exc))

    @mcp.tool()
    @inject_tool_risk_prefix
    def iot_tuya_scan_ports(network_range: str | None = None) -> str:
        """Scan local network for open Tuya TCP ports (6666-6668).

        Args:
            network_range: Optional CIDR range. Uses env default if not set.

        Returns:
            JSON with list of IPs that have Tuya ports open.

        @since v1.4.0
        """
        try:
            start_tool_context()
            increment_tool_count("iot_tuya_scan_ports")
            return _tuya_scan_ports(network_range)
        except Exception as exc:
            return _error_response_extended(code="INTERNAL_ERROR", message=str(exc))

    @mcp.tool()
    @inject_tool_risk_prefix
    def iot_tuya_remove(device_id: str) -> str:
        """Remove a Tuya device from the local cache.

        Does not delete the device from Tuya cloud - only removes local credentials.

        Args:
            device_id: Tuya device ID to remove from cache.

        Returns:
            JSON with result.

        @since v1.4.0
        """
        try:
            start_tool_context()
            check_write_enabled()
            increment_tool_count("iot_tuya_remove")
            cache = _load_tuya_devices()
            if device_id in cache.get("devices", {}):
                name = cache["devices"][device_id].get("name", device_id)
                del cache["devices"][device_id]
                _save_tuya_devices(cache)
                return _success_response(
                    {
                        "removed": True,
                        "device_id": device_id,
                        "name": name,
                        "note": "Device removed from local cache only. Cloud device unchanged.",
                    }
                )
            return _error_response_extended(
                code="TUYA_NOT_FOUND",
                message=f"Device '{device_id}' not found in local cache",
            )
        except ValidationError as exc:
            return _error_response_extended(
                code="WRITE_DISABLED",
                message=str(exc),
                suggestion="Ask the server operator to set ENABLE_WRITE_OPERATIONS=1.",
            )
        except Exception as exc:
            return _error_response_extended(code="INTERNAL_ERROR", message=str(exc))

    @mcp.tool()
    @inject_tool_risk_prefix
    def iot_tuya_monitor(identifier: str, duration_seconds: int = 30) -> str:
        """Monitor DPS changes on a Tuya device in real-time.

        Opens a persistent TCP socket and listens for DPS changes.
        Operate the device physically or via the Tuya/Smart Life app to see
        DPS updates in real-time. Great for diagnostics and debugging.

        Args:
            identifier: Device ID, IP address, or device name from cache.
            duration_seconds: How long to monitor (1-120, default 30).

        Returns:
            JSON with initial DPS snapshot and list of timestamped changes.

        @since v1.4.0
        """
        try:
            start_tool_context()
            increment_tool_count("iot_tuya_monitor")
            return _tuya_monitor(identifier, duration_seconds)
        except Exception as exc:
            return _error_response_extended(code="INTERNAL_ERROR", message=str(exc))
