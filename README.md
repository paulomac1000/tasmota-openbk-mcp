---
description: Run and operate the policy-governed MCP server for local home devices.
doc_id: guide.local-home-devices-mcp
type: guide
status: evolving
rigor: operational
owners: [repository-maintainers]
verification: Run `python server.py --mock-self-test` and `pytest -m 'not real_system'`.
---

# Local Home Devices MCP

This server exposes local OpenBK, Tasmota, Tuya, OpenHASP, MQTT, and Hikvision adapters through the Model Context Protocol. The public entrypoints are **stdio** and official FastMCP **Streamable HTTP** at `/mcp`.

Legacy HTTP+SSE and the custom REST tool bridge are intentionally removed. They created separate execution paths that did not share authentication, authorization, rate limiting, target binding, or MCP lifecycle behavior.

## Safe defaults

- HTTP binds to `127.0.0.1` unless configured otherwise.
- A non-loopback bind requires `MCP_AUTH_TOKEN`; external identity-provider wiring is not yet implemented in this repository.
- Write operations require `ENABLE_WRITE_OPERATIONS=1`.
- Dangerous and privileged capabilities are inactive by default.
- Direct IP targeting is disabled by default; use discovered exact device identities.
- Network scans are private and bounded to `/24` or smaller unless the operator tightens or explicitly changes policy.
- Caller-provided filesystem paths are not accepted for artifacts.

## Local verification

Create an isolated environment and install the project:

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev]'
python server.py --mock-self-test
pytest -m 'not real_system'
```

The mock self-test performs no device, network, MQTT, Docker, or filesystem I/O outside its temporary artifact directory.

## Run

Stdio:

```bash
MCP_TRANSPORT=stdio local-home-devices-mcp
```

Streamable HTTP on loopback:

```bash
MCP_TRANSPORT=http MCP_PORT=9102 local-home-devices-mcp
```

Authenticated LAN deployment:

```bash
MCP_TRANSPORT=http \
BIND_HOST=0.0.0.0 \
MCP_AUTH_TOKEN='<operator-generated-secret-at-least-32-characters>' \
local-home-devices-mcp
```

Container deployment uses an immutable image identity rather than `latest`:

```bash
export MCP_IMAGE='ghcr.io/paulomac1000/local-home-devices-mcp@sha256:<digest>'
docker compose up -d
```

The Compose profile publishes only to host loopback, drops Linux capabilities,
uses a read-only root filesystem, and does not mount the Docker socket.

The static token verifier is suitable only for controlled local or LAN deployments. Internet-facing production deployment remains blocked until an explicit external FastMCP identity-provider adapter is implemented and tested.

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `MCP_TRANSPORT` | `http` | `http` or `stdio` |
| `MCP_PORT` | `9102` | Streamable HTTP port |
| `MCP_PATH` | `/mcp` | MCP endpoint path |
| `BIND_HOST` | `127.0.0.1` | Listener address |
| `MCP_AUTH_TOKEN` | unset | Static bearer token, minimum 32 characters; controlled local/LAN use only |
| `ENABLE_WRITE_OPERATIONS` | `0` | Operator write gate |
| `ENABLE_DANGEROUS_OPERATIONS` | `0` | Additional dangerous-operation gate |
| `MCP_ALLOWED_TARGET_NETWORKS` | RFC1918 ranges | Target allowlist |
| `MCP_ALLOW_DIRECT_IP_TARGETS` | `0` | Allow IP selectors only for discovered stable identities |
| `MCP_MIN_SCAN_PREFIX` | `24` | Broadest accepted scan prefix |
| `MCP_ARTIFACT_ROOT` | `data/artifacts` | Confined artifact directory |
| `MCP_MAX_ARTIFACT_BYTES` | `8388608` | Per-artifact limit |
| `MCP_MOCK_MODE` | `0` | Register deterministic zero-I/O tools only |

Backend-specific variables remain documented in `.env.example` and the adapter documentation.

## Architecture and security

- [System architecture](docs/system-architecture.md)
- [Security model](docs/security-model.md)
- [Capability contract](docs/capability-contract.md)
- [Legacy transport migration](docs/migration-from-legacy-transports.md)
- [Adoption status](docs/adoption-status.md)
- [Migration plan](docs/migration-plan.md)
- [Real-system verification TODOs](tests/real_system_todos.py)

The repository does not claim a maturity level merely because files resemble a standard. Compliance is established by the adoption assessment, executable checks, and evidence tied to an immutable revision.
