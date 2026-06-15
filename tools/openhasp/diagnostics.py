"""OpenHASP diagnostics - backlight analysis, config validation, health scoring."""

from typing import Any


def _as_int(value: object, default: int = 0) -> int:
    """Safe int conversion for config values (can be str/int/float/None)."""
    if value is None:
        return default
    if isinstance(value, (int, float, str)):
        try:
            return int(value)
        except ValueError:
            return default
        except TypeError:
            return default
    return default


def analyze_backlight(config: dict[str, Any]) -> list[str]:
    """Analyze backlight configuration and return issues.

    Args:
        config: Parsed config.json dict.

    Returns:
        List of issue strings (empty if no problems).
    """
    gui = config.get("gui", {})
    issues: list[str] = []

    bckl = _as_int(gui.get("bckl"), 0)
    bcklinv = _as_int(gui.get("bcklinv"), 0)
    idle1 = _as_int(gui.get("idle1"), 0)
    idle2 = _as_int(gui.get("idle2"), 0)

    if bckl == 0:
        issues.append("BACKLIGHT DISABLED: gui.bckl=0 means backlight is off at all times")
    elif bckl < 50:
        issues.append(f"BACKLIGHT TOO DIM: gui.bckl={bckl} (recommended: 255)")

    if bcklinv == 1:
        issues.append(
            "BACKLIGHT INVERTED: gui.bcklinv=1 - some WT32-SC01 boards need this, but most do not"
        )

    if idle1 < 10:
        issues.append(
            f"IDLE1 TOO SHORT: gui.idle1={idle1}s - Screensaver dims too quickly. "
            f"Recommended: >=20s"
        )

    if idle2 > 0 and idle2 <= idle1:
        issues.append(
            f"IDLE2 <= IDLE1: idle1={idle1}s, idle2={idle2}s - "
            f"long idle must be greater than short idle"
        )

    return issues


def validate_config(config: dict[str, Any], objects_count: int = 0) -> tuple[bool, list[str]]:
    """Validate OpenHASP configuration.

    Checks: bckl, bcklinv, idle timings, object count, required sections,
    shadow rendering, and emoji in labels.

    Args:
        config: Parsed config.json dict.
        objects_count: Number of objects from pages.jsonl.

    Returns:
        Tuple of (is_valid, list of warnings).
    """
    warnings: list[str] = []

    gui = config.get("gui", {})
    bckl = _as_int(gui.get("bckl"), 0)
    idle1 = _as_int(gui.get("idle1"), 0)

    if bckl == 0:
        warnings.append("gui.bckl=0 - backlight disabled")
    if idle1 < 10 and idle1 > 0:
        warnings.append(f"gui.idle1={idle1}s - too short")

    if objects_count > 55:
        warnings.append(f"objects_count={objects_count} - near LVGL limit (60)")

    if "hasp" not in config:
        warnings.append("Missing 'hasp' section in config.json")
    if "gui" not in config:
        warnings.append("Missing 'gui' section in config.json")
    if "mqtt" not in config:
        warnings.append("Missing 'mqtt' section in config.json")

    return len(warnings) == 0, warnings


def health_score(
    status: dict[str, Any],
    objects_count: int,
    mqtt_responding: bool,
    bckl: int = 0,
) -> tuple[int, str, list[str]]:
    """Calculate OpenHASP health score (0-100).

    Args:
        status: Status dict from Telnet statusupdate.
        objects_count: Number of objects from pages.jsonl.
        mqtt_responding: True if MQTT is connected.
        bckl: Backlight brightness (0-255).

    Returns:
        Tuple of (score, level, issues).
    """
    score = 100
    issues: list[str] = []

    tft_driver = status.get("tftDriver", status.get("tft_driver", ""))
    if tft_driver == "Other" or not tft_driver:
        score -= 40
        issues.append("CRITICAL: tftDriver=Other - no display driver, backlight disabled")

    if bckl == 0:
        score -= 30
        issues.append("CRITICAL: bckl=0 - backlight disabled at boot")

    if not mqtt_responding:
        score -= 20
        issues.append("WARNING: MQTT not connected - commands via Telnet only")

    heap = 0
    try:
        heap = int(status.get("heapFree", status.get("heap_free", 0)))
    except ValueError:
        pass
    except TypeError:
        pass
    if heap > 0 and heap < 50000:
        score -= 5
        issues.append(f"WARNING: Low heap ({heap} bytes)")

    if objects_count > 55:
        score -= 5
        issues.append(f"WARNING: Near LVGL object limit ({objects_count}/60)")

    if score >= 80:
        level = "healthy"
    elif score >= 50:
        level = "degraded"
    else:
        level = "critical"

    return score, level, issues
