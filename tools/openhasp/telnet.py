"""OpenHASP Telnet client - raw TCP socket, NOT telnetlib.

telnetlib sends IAC negotiation bytes (0xFF 0xFD...) that crash
OpenHASP. Use plain socket.socket() + sendall() + recv().
"""

import json
import re
import socket
import time
from typing import Any, cast

from tools.constants import OPENHASP_TELNET_PORT, OPENHASP_TELNET_TIMEOUT


class OpenHASPTelnet:
    """Raw TCP Telnet client for OpenHASP panel.

    Handles character-by-character echo, ANSI escape stripping,
    and two response formats: MQTT PUB (JSON) and MSGR (key=value).
    """

    def __init__(
        self,
        host: str,
        port: int = OPENHASP_TELNET_PORT,
        timeout: int = OPENHASP_TELNET_TIMEOUT,
    ):
        self.host = host
        self.port = port
        self.timeout = timeout
        self._sock: socket.socket | None = None

    def connect(self) -> bool:
        """Open raw TCP connection to the panel.

        Returns:
            True if connected.
        """
        try:
            self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._sock.settimeout(self.timeout)
            self._sock.connect((self.host, self.port))
            time.sleep(0.5)
            # Drain welcome banner
            self._read_available(0.5)
            return True
        except Exception:
            self._sock = None
            return False

    def disconnect(self) -> None:
        """Close the TCP connection."""
        if self._sock:
            try:
                self._sock.close()
            except Exception:
                pass
            self._sock = None

    def send_command(self, command: str, wait: float = 1.5) -> str:
        """Send a command and return the response.

        Args:
            command: Telnet command (e.g. "backlight", "statusupdate").
            wait: Seconds to wait for response.

        Returns:
            Raw response text (ANSI codes stripped).
        """
        if not self._sock:
            return ""
        try:
            self._sock.sendall(f"{command}\n".encode())
            time.sleep(wait)
            return self._read_available(0.5)
        except Exception:
            return ""

    def parse_response(self, raw: str) -> dict[str, Any] | str | None:
        """Parse Telnet output into structured data.

        Handles three formats:
        1. MQTT PUB: command => {"key":"val",...}  (MQTT connected)
        2. MSGR: key=value                          (MQTT disconnected)
        3. MSGR: key (query, no value)
        """

        for line in raw.split("\r\n"):
            clean = re.sub(r"\x1b\[[\d;]*[a-zA-Z]", "", line)
            clean = re.sub(r"\x1b\]2;.*?\x07", "", clean)
            clean = clean.strip()
            if not clean or clean.startswith("#"):
                continue

            # Format 1: MQTT PUB (with MQTT connected)
            if "MQTT PUB:" in clean:
                parts = clean.split("=>", 1)
                if len(parts) == 2:
                    payload = parts[1].strip()
                    try:
                        parsed = json.loads(payload)
                        if isinstance(parsed, dict):
                            return cast(dict[str, Any], parsed)
                        return str(parsed)
                    except json.JSONDecodeError:
                        return payload

            # Format 2: MSGR key=value (set commands)
            if clean.startswith("MSGR:"):
                kv = clean[5:].strip()
                if "=" in kv:
                    key, val = kv.split("=", 1)
                    return {key.strip(): val.strip()}
                # Format 3: MSGR key (query, no value)
                return kv

        return None

    def statusupdate(self) -> dict[str, Any]:
        """Send statusupdate and return parsed device status.

        Returns:
            Dict with keys: node, version, tftDriver, heapFree, uptime, rssi, mac.
        """
        raw = self.send_command("statusupdate", wait=2.0)
        parsed = self.parse_response(raw)
        if isinstance(parsed, dict):
            return parsed
        return {}

    def backlight_query(self) -> dict[str, Any] | None:
        """Query current backlight state.

        Returns:
            Dict like {"state": "on", "brightness": 255} or None.
        """
        raw = self.send_command("backlight", wait=1.5)
        parsed = self.parse_response(raw) if raw else None
        if isinstance(parsed, dict):
            return parsed
        return None

    def backlight_set(self, value: str | int) -> str:
        """Set backlight state.

        Args:
            value: "on", "off", or brightness 0-255.

        Returns:
            Raw response.
        """
        return self.send_command(f"backlight {value}", wait=1.5)

    def idle_off(self) -> str:
        """Reset idle timer to prevent Screensaver from dimming.

        Returns:
            Raw response.
        """
        return self.send_command("idle off", wait=1.0)

    def restart(self) -> None:
        """Send restart command. Connection will drop."""
        self.send_command("restart", wait=0.5)
        self.disconnect()

    def _read_available(self, wait: float) -> str:
        """Read all available data from socket.

        Args:
            wait: Seconds to wait before reading.

        Returns:
            Decoded string.
        """
        if not self._sock:
            return ""
        time.sleep(wait)
        self._sock.settimeout(0.5)
        chunks: list[bytes] = []
        try:
            while True:
                chunk = self._sock.recv(4096)
                if not chunk:
                    break
                chunks.append(chunk)
        except TimeoutError:
            pass
        except BlockingIOError:
            pass
        except OSError:
            pass
        self._sock.settimeout(self.timeout)
        return b"".join(chunks).decode("utf-8", errors="ignore")
