# Local Home Devices MCP

[![CI](https://github.com/paulomac1000/local-home-devices-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/paulomac1000/local-home-devices-mcp/actions/workflows/ci.yml)
[![Docker](https://github.com/paulomac1000/local-home-devices-mcp/actions/workflows/publish.yml/badge.svg)](https://github.com/paulomac1000/local-home-devices-mcp/actions/workflows/publish.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

MCP (Model Context Protocol) server for IoT device management. Enables AI assistants (Claude Desktop, LibreChat, Cline) to discover and control OpenBK (OpenBeken), Tasmota, and Tuya devices on your local network.

## Requirements

- Docker (recommended) or Python 3.11+ (for local use)
- MQTT broker (optional - required only for MQTT tools)
- OpenBK or Tasmota devices on the same local network
- Tuya devices (WiFi models; optional - requires Tuya cloud API credentials)
- **nmap** - installed automatically in Docker; for local use, install via `apt-get install nmap` (may require root/sudo)

**Note on networking:** Docker uses `--network host` mode to access the local network where your IoT devices are located. This is required for nmap scanning and direct HTTP communication with devices.

## Quick Start

### 1. Configure

```bash
cp .env.example .env
# Edit .env with your MQTT_BROKER and network range
```

### 2. Run with Docker

**Option A -- Pre-built image from GitHub Container Registry:**

```bash
docker run -d \
  --name local-home-devices-mcp \
  --network host \
  -e MQTT_BROKER=192.168.1.100 \
  -e START_IP=192.168.1.1 \
  -e END_IP=192.168.1.254 \
  -v local-home-devices-data:/app/data \
  ghcr.io/paulomac1000/local-home-devices-mcp:latest
```

**Option B -- with docker compose:**

```bash
cp .env.example .env
# edit .env with your settings
docker compose up -d
```

**Option C -- Build locally:**

```bash
docker build -t local-home-devices-mcp .
docker run -d \
  --network host \
  -e MQTT_BROKER=192.168.1.100 \
  -e START_IP=192.168.1.1 \
  -e END_IP=192.168.1.254 \
  -v local-home-devices-data:/app/data \
  local-home-devices-mcp
```

### 3. Run locally (Python 3.11+)

```bash
pip install -r requirements.txt
MQTT_BROKER=192.168.1.100 START_IP=192.168.1.1 END_IP=192.168.1.254 python server.py
```

## Architecture

| Port | Protocol | Purpose | Endpoint |
|------|----------|---------|----------|
| 9100 | HTTP | Health check | `GET /health` |
| 9101 | SSE | MCP transport | `/sse`, `/messages` |
| 9102 | HTTP | REST API | `/api/*` |

### Verify

```bash
# Health check
curl http://localhost:9100/health

# List all MCP tools
curl http://localhost:9102/api/tools

# Call a tool via REST API
curl -X POST http://localhost:9102/api/tools/iot_list_devices \
  -H "Content-Type: application/json" \
  -d '{}'
```

## Available Tools

### Device Discovery

All read-only operations - no device state is modified.

| Tool | Risk | Description |
|------|------|-------------|
| `iot_discover_devices` | [READ] | Scan local network for OpenBK and Tasmota devices |
| `iot_list_devices` | [READ] | List all previously discovered devices from cache |
| `iot_check_device` | [READ] | Quick connectivity and status check for a specific IP |
| `iot_find_device_by_name` | [READ] | Find a device by its friendly name |

### Device Information

All read-only operations - no device state is modified.

| Tool | Risk | Description |
|------|------|-------------|
| `iot_get_device_info` | [READ] | Full device information (name, firmware, chip type, etc.) |
| `iot_get_device_power` | [READ] | Current power state of a specific channel |
| `iot_get_wifi_config` | [READ] | WiFi SSID, RSSI signal strength, MAC, IP address |

### Device Control

| Tool | Risk | Description |
|------|------|-------------|
| `iot_set_power` | [WRITE] | Turn a channel ON, OFF, or TOGGLE |
| `iot_set_brightness` | [WRITE] | Set brightness level (0-100%) |
| `iot_restart_device` | [DESTRUCTIVE] | Restart the device (temporarily disconnects) |

### Device Configuration

| Tool | Risk | Description |
|------|------|-------------|
| `iot_set_flags` | [WRITE] | Set device configuration flags as bitfield (OpenBK /cfg_generic, Tasmota SetOption) |
| `iot_set_name` | [WRITE] | Set device short and full name (OpenBK via /cfg_name) |
| `iot_configure_mqtt` | [WRITE] | Configure MQTT broker connection (OpenBK via /cfg_mqtt_set) |
| `iot_set_gpio` | [WRITE] | Configure GPIO pin role and channel (OpenBK via /cfg_pins) |
| `iot_execute_command` | [DESTRUCTIVE] | Execute raw /cm?cmnd= command with blocked-command safety |
| `iot_start_ha_discovery` | [WRITE] | Trigger Home Assistant MQTT discovery (OpenBK via /ha_discovery) |
| `iot_get_full_info` | [READ] | Enhanced device info: MAC, version, flags, MQTT, WiFi (both OpenBK and Tasmota) |

### Introspection

| Tool | Risk | Description |
|------|------|-------------|
| `describe_iot_capabilities` | [READ] | Describe all IoT tools, manifests, and transports |

### MQTT Integration

| Tool | Risk | Description |
|------|------|-------------|
| `iot_mqtt_publish` | [WRITE] | Publish a command via MQTT |
| `iot_mqtt_get_state` | [READ] | Get device state from MQTT broker |
| `iot_mqtt_build_command_topic` | [READ] | Build MQTT command topic for a device |

### OpenHASP Panels

| Tool | Risk | Description |
|------|------|-------------|
| `openhasp_detect` | [READ] | Check if an IP is an OpenHASP panel |
| `openhasp_status` | [READ] | Full panel status: version, backlight, objects, heap, WiFi |
| `openhasp_check_backlight` | [READ] | Analyze backlight for common issues |
| `openhasp_get_config` | [READ] | Get full config.json from the panel |
| `openhasp_get_pages` | [READ] | Get pages.jsonl with object/page counts |
| `openhasp_screenshot` | [READ] | Capture and download screenshot.bmp |
| `openhasp_download_file` | [READ] | Download any config/cmd file from the panel |
| `openhasp_upload_file` | [WRITE] | Upload a file via POST /edit |
| `openhasp_ota_update` | [DESTRUCTIVE] | OTA firmware update via URL |
| `openhasp_page_set` | [WRITE] | Navigate to a specific page |
| `openhasp_jsonl_send` | [WRITE] | Send JSONL to create/modify UI objects |
| `openhasp_telnet` | [WRITE] | Send raw Telnet command (raw TCP, no telnetlib) |
| `openhasp_backlight_set` | [WRITE] | Set backlight state and brightness |
| `openhasp_config_set` | [WRITE] | Runtime config via Telnet config/gui |
| `openhasp_idle_reset` | [WRITE] | Reset idle timer to wake screen |
| `openhasp_restart` | [DESTRUCTIVE] | Reboot the panel |
| `openhasp_factory_reset` | [DESTRUCTIVE] | Factory reset (EEPROM only, files survive) |
| `openhasp_validate_config` | [READ] | Validate configuration for common issues |
| `openhasp_health` | [READ] | Composite health score 0-100 |
| `openhasp_hardware_test` | [WRITE] | Automated diagnostic sequence |

### Hikvision Doorbell

| Tool | Risk | Description |
|------|------|-------------|
| `hikvision_container_status` | [READ] | [CONTAINER] Get Docker container running status and health |
| `hikvision_container_logs` | [READ] | [CONTAINER] Fetch recent container logs (VMD events, calls, errors) |
| `hikvision_device_info` | [READ] | Fetch doorbell device metadata via ISAPI |
| `hikvision_check_vmd` | [READ] | [CONTAINER] Check VMD motion events -- ISAPI health canary |
| `hikvision_take_snapshot` | [READ] | Capture JPEG snapshot from doorbell camera |
| `hikvision_get_motion_config` | [READ] | Fetch VMD motion detection configuration |
| `hikvision_get_event_config` | [READ] | Fetch ISAPI event trigger configuration |
| `hikvision_get_alarm_server` | [READ] | Fetch HTTP notification host (alarm server) config |
| `hikvision_isapi_health` | [READ] | [CONTAINER] Composite health check (container + VMD + call events) |
| `hikvision_pipeline_diagnose` | [READ] | [CONTAINER] Full pipeline trace (container to ISAPI to events to MQTT to snapshots) |
| `hikvision_open_gate` | [WRITE] | Trigger electric lock relay to open gate |
| `hikvision_set_motion_detection` | [WRITE] | Enable/disable VMD or adjust sensitivity (write-guarded) |
| `hikvision_snapshot_to_file` | [WRITE] | Capture JPEG and save directly to disk (write-guarded) |
| `hikvision_restart_container` | [DESTRUCTIVE] | [CONTAINER] Restart the Docker container |

> **Note**: Tools marked `[CONTAINER]` require the `hikvision-doorbell` Docker container
> and access to `/var/run/docker.sock`. ISAPI-only tools work with any Hikvision doorbell
> accessible via HTTP Digest Auth.

## Configuration

All configuration is via environment variables. See `.env.example` for a complete template.

### Required for MQTT tools (optional otherwise)

| Variable | Description | Example |
|----------|-------------|---------|
| `MQTT_BROKER` | MQTT broker IP address | `192.168.1.100` |

> **Tip:** Without MQTT broker, device discovery and HTTP control still work. Set `MQTT_BROKER` only if you need MQTT-based tools (`iot_mqtt_publish`, `iot_mqtt_get_state`, etc.).

### Network Scanning

| Variable | Default | Description |
|----------|---------|-------------|
| `START_IP` | `192.168.1.1` | First IP in the scan range |
| `END_IP` | `192.168.1.254` | Last IP in the scan range |
| `NETWORK_RANGE` | `192.168.1.0/24` | CIDR range for nmap scan (overrides START_IP/END_IP if set) |

### Optional

| Variable | Default | Description |
|----------|---------|-------------|
| `ENABLE_WRITE_OPERATIONS` | `0` | Set to `1` to enable write/destructive tools (set_power, restart, etc.) |
| `MQTT_PORT` | `1883` | MQTT broker port |
| `MQTT_USER` | -- | MQTT username |
| `MQTT_PASSWORD` | -- | MQTT password |
| `MCP_SSE_PORT` | `9101` | MCP SSE transport port |
| `REST_API_PORT` | `9102` | REST API port |

## Project Structure

- `tools/constants.py` - All shared configuration defaults (no hardcoded IPs in tool files)
- `tools/validators.py` - Input validation for tool parameters
- `tools/iot_control.py` - Power/brightness/restart/WiFi control (4 tools)
- `tools/iot_devices.py` - Device info/power state (2 tools)
- `tools/iot_discovery.py` - Network scanning/device discovery/cache (4 tools)
- `tools/iot_mqtt.py` - MQTT publish/state/topic (3 tools)
- `tools/iot_meta.py` - Capability introspection, manifests and transports (1 tool)
- `tools/iot_tuya.py` - Tuya device cloud + local control + diagnostics (10 tools)
- `tools/iot_openhasp.py` - OpenHASP panel control, diagnostics, Telnet (20 tools)
- `tools/openhasp/` - OpenHASP HTTP, Telnet, diagnostics helpers
- `tools/iot_config.py` - Device configuration tools (7 tools)
- `tools/iot_hikvision.py` - Hikvision doorbell tools (14 tools)
- `tools/hikvision/` - ISAPI HTTP client, Docker socket helper
- `tools/http_session.py` - Generic IoT device HTTP client module

## Supported Devices

### OpenBK (OpenBeken)

- **Chips**: BK7231N, BK7231T, XR809, BL602
- **Devices**: Lights, switches, curtains, sensors
- **Detection**: HTTP `GET /index` returns HTML containing `"openbeken"`

### Tasmota

- **Chips**: ESP8266, ESP32
- **Devices**: Lights, switches, sensors, fans, plugs
- **Detection**: HTTP `GET /cm?cmnd=Status` returns JSON with `"Status"` key

### Tuya

- **Chips**: ESP8266, ESP32, BK7231N/T (varies by vendor)
- **Devices**: Vacuums, kettles, water valves, sensors, gateways
- **Detection**: TCP port 6668 open on local network
- **Requirements**: Tuya cloud API credentials (Access ID, Access Secret) for local key retrieval
- **Protocol**: Encrypted TCP/UDP via `tinytuya` library, cloud API fallback

### OpenHASP

- **Chips**: ESP32 (WT32-SC01, WT32-SC01 Plus, ESP32-S3)
- **Devices**: Touch panel displays, wall-mounted dashboards, control panels
- **Detection**: HTTP `GET /config.json` returns JSON with `"hasp"` key
- **Protocol**: HTTP API for config/files + raw TCP Telnet for control (NOT telnetlib)
- **Telnet**: Uses raw TCP socket - MQTT PUB format when MQTT connected, MSGR format otherwise

### Hikvision Doorbell

- **Models**: DS-KV6113-WPE1(C), DS-KV8113-WPE1(C), VillaVTO series
- **Features**: Camera snapshot, motion detection (VMD), gate control, event triggers, ISAPI health
- **Detection**: Docker container `hikvision-doorbell` manages ISAPI connection
- **Protocol**: ISAPI HTTP Digest Auth + Docker Unix socket API
- **Requirements**: Docker container `hikvision-doorbell`, ISAPI credentials (`HIKVISION_DOORBELL_HOST/USER/PASSWORD`)

## Testing

The project has a 4-tier test hierarchy (see `AGENTS.md` for details):

| Suite | Tests | Coverage | Command |
|-------|-------|----------|---------|
| Unit | 378 | **>80%** | `pytest tests/unit/ -v --tb=short` |
| Integration | 25 | **66%** | `pytest tests/integration/ -q` |
| Smoke | 25 | HTTP validation | `pytest tests/smoke/ -q` |
| E2E | 9 | HTTP validation | `pytest tests/e2e/ -q` |

Unit tests run in CI. Integration, smoke, and e2e tests skip when their dependencies (MQTT broker, running server) are absent.

The server follows the [MCP Server Standards](https://github.com/paulomac1000/ai-skills/blob/main/skills/mcp-server-architect/mcp-server-standards.md) at L2/L3 maturity level.

## Claude Desktop Configuration

Add to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "local-home-devices": {
      "command": "npx",
      "args": ["-y", "mcp-remote", "http://localhost:9101/sse"]
    }
  }
}
```

## License

MIT -- see [LICENSE](LICENSE) for details.
