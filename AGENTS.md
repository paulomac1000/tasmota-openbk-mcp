# AGENTS.md — local-home-devices-mcp

> Rules and conventions for maintaining this MCP server for IoT device management.
> Aligned with ha-mcp-readonly standards.

## Language & Naming

- **English only** in all source files, docstrings, comments, tool descriptions, and error messages.
- **Generic names** in test fixtures and examples:
  - Use `Tasmota_Test`, `OpenBK_Test` — never real device names.
  - Use `192.168.1.100`, `192.168.1.101` — never real IPs.
- **No emoji** in tool descriptions, response strings, docstrings, or API output.
- **No Polish text** in source code or documentation (except this rule itself).

## Tool Description Standards

Every tool must follow this pattern:

```python
@mcp.tool()
def tool_name(param: type = default) -> str:
    """One-line summary of what the tool does.

    Args:
        param: Description of the parameter.

    Returns:
        JSON with result fields.
    """
```

- First docstring line must be a complete sentence ending with a period.
- All parameters must be documented in `Args:` block.
- Return value must be documented in `Returns:` block.
- All responses must include a `success` field (boolean).

## Tool Implementation Pattern

Internal functions (prefix `_`) contain all logic and are directly unit-testable. MCP wrappers (`@mcp.tool()`) delegate to internal functions and add `try/except Exception` returning `{"success": False, "error": str(exc)}`.

```python
def _set_power(identifier, state, channel=1):
    # All logic here — testable directly
    ...

def register_iot_control_tools(mcp):
    @mcp.tool()
    def iot_set_power(identifier: str, state: str, channel: int = 1) -> str:
        """..."""
        try:
            return _set_power(identifier, state, channel)
        except Exception as exc:
            return json.dumps({"success": False, "error": str(exc)})
```

## Test Hierarchy

| Suite | Location | Runtime | Requires | Tests | Run with |
|-------|----------|---------|----------|-------|----------|
| Unit | `tests/unit/` | <1s | Nothing | 322 | `pytest tests/unit/ -q` |
| Smoke | `tests/smoke/` | <5s | Running MCP server (localhost:9102) | 17 | `pytest tests/smoke/ -q` |
| Integration | `tests/integration/` | ~60s | Real MQTT broker (`MQTT_BROKER` env) | 68 | `pytest tests/integration/ -q` |
| E2E | `tests/e2e/` | <10s | Running MCP server (localhost:9102) | 19 | `pytest tests/e2e/ -q` |

## Test Rules

### Unit Tests (`tests/unit/`)
- **Zero I/O**: All external calls (HTTP, MQTT, subprocess) must be mocked via `unittest.mock.patch`.
- **No credentials required**: Must pass without `.env` file.
- **Run in CI**: Always executed as part of the CI pipeline.
- **Must test registration functions**: Call `register_*_tools(mock_mcp)`, retrieve tools via `mock_mcp.get_tool("name")`, invoke, assert.
- **Must test exception handlers**: Patch internal function with `side_effect=Exception`, assert `success: false` with error text.

### Smoke Tests (`tests/smoke/`)
- **Direct REST API calls**: Use `requests` library against `localhost:9102`.
- **Dynamic skip**: Probe server port with 1s socket connection before running tests.
- **Skip pattern** (in each test file, NOT in conftest.py):
  ```python
  import socket
  def _server_running():
      try:
          s = socket.create_connection(("localhost", REST_API_PORT), timeout=1)
          s.close()
          return True
      except OSError:
          return False

  pytestmark = pytest.mark.skipif(
      not _server_running(),
      reason="MCP server not running on port {port}. Start with: MCP_SSE_PORT=9111 REST_API_PORT=9112 python server.py"
  )
  ```

### Integration Tests (`tests/integration/`)
- **Real MCP wrapper**: Create FastMCP in `scope="session"` fixture, register all tools, wrap in `MCPWrapper` with `call_tool()`.
- **Must skip** if `MQTT_BROKER` is not configured:
  ```python
  pytestmark = pytest.mark.skipif(
      not bool(os.getenv("MQTT_BROKER")),
      reason="MQTT_BROKER not configured"
  )
  ```
- **Read-only on real devices**: Integration tests call real devices for info/power/wifi queries. Destructive operations (set_power, restart) test only error paths.
- **Async support**: Use shared `asyncio.new_event_loop()` for async tool execution. Do not use `asyncio.run()` inside `ThreadPoolExecutor` when a running loop exists.

### E2E Tests (`tests/e2e/`)
- **Full pipeline**: REST API → tool execution → response validation.
- **Same dynamic skip pattern** as smoke tests.

## Coverage Data

| Suite | Coverage | What it measures |
|-------|----------|-----------------|
| Unit | **>80%** | All code paths exercised with mocks |
| Integration | **66%** (345/523 stmts) | Real MQTT + nmap + Tasmota devices (read-only) — missing 34% requires destructive ops or OpenBK devices |
| Smoke | 0% | Tests external server process over HTTP — coverage.py cannot trace |
| E2E | 0% | Same as smoke — validates response format, not line coverage |

Per-module unit coverage: all modules >80% (`iot_control.py`, `iot_devices.py`, `iot_discovery.py`, `iot_mqtt.py`, `iot_meta.py`, `iot_tuya.py`, `iot_openhasp.py`, `iot_hikvision.py`, `openhasp/`, `hikvision/`, `validators.py`, `constants.py`).

## Code Quality

### Response Format
Every tool response must be a JSON string with a `success` field:

```python
json.dumps({"success": True, "key": "value"})
json.dumps({"success": False, "error": "description"})
```

Error responses must include actionable fields:
```json
{
  "success": false,
  "error": "Could not resolve 'UnknownDevice' to an IP address",
  "suggestion": "Run iot_discover_devices() first, then use iot_list_devices()",
  "available_names": ["Device_A", "Device_B"]
}
```

### Imports
- Group imports: stdlib → third-party → local (`tools.`)
- Use `from tools.constants import ...` for shared configuration values.
- Never hardcode IP addresses, port numbers, or default values — use `tools/constants.py`.

### Logging
- Use `get_logger("component_name")` from `tools.constants` for all log output.
- All log output must target stderr via `logging.StreamHandler(sys.stderr)`.
- Log level is configurable via `LOG_LEVEL` env var (default `INFO`).
- Use `sys.stderr` for diagnostic output in tests.

## File Organization

```
local-home-devices-mcp/
├── server.py                    # Main entry point + REST API + health check
├── Dockerfile                   # Production image (no test files)
├── docker-compose.yml           # Deployment config
├── requirements.txt             # Dependencies
├── .env.example                 # Documented configuration template
├── AGENTS.md                    # This file
├── README.md                    # User-facing documentation
├── CHANGELOG.md                 # Version history
├── tools/
│   ├── __init__.py
│   ├── __main__.py
│   ├── constants.py             # SSOT for shared configuration defaults
│   ├── validators.py            # Input validation
│   ├── iot_control.py           # Power/brightness/restart/WiFi (4 tools)
│   ├── iot_devices.py           # Device info/power (2 tools)
│   ├── iot_discovery.py         # Network scan/discovery/cache (4 tools)
│   ├── iot_mqtt.py              # MQTT publish/state/topic (3 tools)
│   ├── iot_meta.py              # Capability introspection (1 tool)
│   ├── iot_tuya.py              # Tuya cloud + local control (10 tools)
│   ├── iot_openhasp.py          # OpenHASP panel tools (20 tools)
│   ├── iot_hikvision.py         # Hikvision doorbell tools (7 tools)
│   ├── openhasp/                # OpenHASP sub-package (HTTP, Telnet, diagnostics)
│   └── hikvision/               # Hikvision sub-package (ISAPI, Docker)
├── tests/
│   ├── conftest.py              # Root: env loading only (~30 lines)
│   ├── fixtures.py              # Mock data constants (MOCK_TASMOTA_DEVICE, etc.)
│   ├── unit/                    # Unit tests (zero I/O, fully mocked)
│   │   ├── conftest.py          # Unit fixtures (mock_mcp, mock_requests)
│   │   ├── test_constants.py    # 20 tests
│   │   ├── test_validators.py   # 36 tests
│   │   ├── test_iot_control.py  # 47 tests
│   │   ├── test_iot_devices.py  # 28 tests
│   │   ├── test_iot_discovery.py # 49 tests
│   │   ├── test_iot_mqtt.py     # 20 tests
│   │   ├── test_iot_meta.py     # 5 tests
│   │   ├── test_iot_tuya.py     # 38 tests
│   │   ├── test_openhasp.py     # 36 tests
│   │   └── test_iot_hikvision.py # 44 tests
│   ├── smoke/                   # REST API smoke tests
│   │   ├── conftest.py          # Dynamic skip + REST_API_URL
│   │   ├── test_connectivity.py # 3 tests
│   │   └── test_critical_tools.py # 14 tests
│   ├── integration/             # Real MQTT/device tests
│   │   ├── conftest.py          # MCPWrapper + skip-if marker
│   │   ├── test_real_tools.py   # 20 tests
│   │   ├── test_openhasp_tools.py # 34 tests
│   │   └── test_hikvision_tools.py # 7 tests
│   └── e2e/                     # Full pipeline tests
│       ├── conftest.py          # Dynamic skip + REST_API_URL
│       ├── test_server_api.py   # 6 tests
│       ├── test_openhasp_workflow.py # 7 tests
│       └── test_hikvision_workflow.py # 6 tests
├── docs/
│   └── README.md                # User-facing documentation
└── data/                        # Runtime cache (gitignored)
```

## Coverage Requirements

- **Per module minimum**: 80% line coverage for each `tools/*.py` file.
- **Overall**: 80%+ across all Python source files.
- **New tools**: Must include unit tests covering the success path and the primary error handler, plus exception handlers and registration wrappers.
- **Critical tools**: `iot_discover_devices`, `iot_set_power`, `iot_mqtt_publish`, `iot_tuya_get_dps`, `iot_tuya_set_dp` need unit + integration + smoke tests.

## CI Pipeline

1. **Lint**: `ruff check` + `ruff format --check`
2. **Unit tests**: `pytest tests/unit/ -v --tb=short`
3. **Docker build**: Build image and verify tool count via `python -c "from server import get_tool_count"`
4. **Smoke test (Docker)**: Start container, curl health + tools endpoints, assert tool count, stop container

## Pre-commit Hooks

This project uses pre-commit hooks to catch issues before they reach CI. The hooks mirror our CI lint and test jobs exactly.

### Setup

```bash
pip install pre-commit
pre-commit install
```

### Manual Run

```bash
pre-commit run --all-files
```

### Hook Summary

| Hook | Stage | Purpose | CI Equivalent |
|------|-------|---------|---------------|
| trailing-whitespace | pre-commit | Remove trailing whitespace | -- |
| end-of-file-fixer | pre-commit | Ensure files end with newline | -- |
| check-yaml/toml/json | pre-commit | Validate config file syntax | -- |
| detect-private-key | pre-commit | Prevent committing secrets | -- |
| ruff check | pre-commit | Lint Python code | ci.yml lint job |
| ruff format --check | pre-commit | Format Python code | ci.yml lint job |
| mypy | pre-commit | Static type checking | ci.yml lint job |
| bandit | pre-commit | Security scanning | ci.yml lint job |
| pytest unit | pre-commit | Run unit tests | ci.yml test job |
| tool count validate | pre-commit | Verify MCP tool count | ci.yml docker-smoke |

## Conditional Tool Registration

Some tools depend on optional infrastructure (Docker socket, system binaries like nmap, Python libraries like tinytuya). These tools should fail gracefully rather than crash the server.

### Pattern: `_X_available()` check -> `DEPENDENCY_MISSING` error

Follow the existing Canonical Template 1 pattern:

1. **Lazy import check at module level** -- `_import_tinytuya()` in `tools/iot_tuya.py` returns `True` only if the library is importable.
2. **Tool checks at invocation time** -- if `_import_tinytuya()` returns `False`, return `_error_response_extended(code="DEPENDENCY_MISSING", ...)`.
3. **Docker tools check socket existence** -- `_docker_available()` in `tools/hikvision/docker_client.py` checks if `/var/run/docker.sock` exists.
4. **System binaries** -- `shutil.which("nmap")` in `tools/iot_discovery.py` returns the path or `None`.

### Examples in this codebase

| Dependency | Check Function | Tool Type |
|------------|---------------|-----------|
| tinytuya library | `_import_tinytuya()` | Tuya cloud/local |
| paho-mqtt library | `_get_mqtt_client()` | MQTT publish/state |
| Docker socket | `_docker_available()` | Hikvision container tools |
| nmap binary | `shutil.which("nmap")` | Device discovery |

### Tool Registration Rules

- **ISAPI/HTTP tools** (direct device communication) -- always registered, no infrastructure dependency.
- **Docker tools** (container status, logs, restart) -- registered only when `_docker_available()`.
- **MQTT tools** -- always registered, return `DEPENDENCY_MISSING` at invocation time.
- **Discovery** -- always registered, check nmap before scanning.

## Common Pitfalls

### Hardcoded IPs and Ports
- Use `tools/constants.py` for all configuration defaults.
- Access via `os.getenv("VAR", DEFAULT)` pattern in one place only.
- Never duplicate default values across files.

### Fixture Auto-Discovery
- Pytest discovers fixtures only from `conftest.py` files.
- Root `tests/conftest.py` handles env loading only — no fixtures.
- Each test suite has its own `conftest.py` with suite-specific fixtures.

### Mock MCP for Unit Tests
- Unit tests that test tool registration must use the `mock_mcp` fixture from `tests/unit/conftest.py`.
- The mock must handle both decorator forms: `@mcp.tool` (no parentheses) and `@mcp.tool()` (with parentheses).
- Without the `callable(args[0])` check for `@mcp.tool` form, the function is never added to `_tools`.

### pytestmark Skip Placement
- `pytestmark` in `conftest.py` does NOT skip tests. Must be placed in each test file directly.
- Smoke/e2e use dynamic socket check, not hardcoded boolean.

### Device Name Resolution
- Tools accept both IP addresses and device names (from discovery cache).
- Use `_resolve_ip()` and `_find_device_by_identifier()` from `iot_discovery.py`.
- Always return `success: false` with a `suggestion` field when the name cannot be resolved.

### HTTP Timeouts
- All HTTP requests to devices must include a timeout (default 5-10 seconds).
- Devices may be offline — never let a request hang indefinitely.

### Nmap Scanning
- `nmap` must be installed in the environment (Docker image includes it).
- The `_scan_network()` function handles nmap not being available and returns an error.
- Scans are cached for 1 hour in `data/discovered_devices.json`.

### Dead Code
- Branches like `"Unknown device type"` and `"Device not found or unsupported"` are dead code because `_detect_device_type()` only returns `tasmota`, `openbk`, or `None`. These branches exist as safety fallbacks.

### Optional Dependencies
- MQTT tools check for `paho-mqtt` at runtime. If not installed, `_get_mqtt_client()` returns `None` and tools return controlled errors. The server never crashes from missing optional libraries.
