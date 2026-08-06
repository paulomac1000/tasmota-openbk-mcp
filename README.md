---
description: Operate and develop the policy-governed MCP server for local home devices.
doc_id: guide.repository-readme
type: guide
status: evolving
rigor: operational
owners: [repository-maintainers]
verification: Run the virtual-environment tests, real transport probes, and exact artifact workflow described below.
---

# Local Home Devices MCP

This branch is a **fail-closed compliance migration**, not an approved L2/L3 declaration. It exposes local-device operations through official MCP stdio and Streamable HTTP transports, with one application-owned authorization and target-binding pipeline.

## Safe defaults

- HTTP binds to `127.0.0.1` by default.
- Writes and dangerous capabilities are disabled by default.
- Target-bearing calls resolve an exact cached device, authorize its stable ID, serialize by that ID, and revalidate identity immediately before adapter invocation.
- Legacy failures are raised as MCP tool errors rather than returned as successful JSON text.
- Unmigrated writes, Docker-socket access, unrestricted paths, OTA, raw commands, and OpenHASP writes remain inactive.
- Multi-backend `iot_set_power` remains inactive until every backend has its own contract, timeout, read-back, overlap, and real-device evidence; `TOGGLE` remains rejected at the policy boundary.

## Local development

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev]'
MCP_MOCK_MODE=1 ENABLE_WRITE_OPERATIONS=1 python server.py --mock-self-test
python -m pytest -m 'not real_system'
```

The transport tests start an actual subprocess for stdio and an actual HTTP server for Streamable HTTP. `Client(mcp)` in-memory tests are not accepted as transport evidence.

## Running

Local subprocess integration:

```bash
MCP_TRANSPORT=stdio local-home-devices-mcp
```

Loopback HTTP:

```bash
MCP_TRANSPORT=http BIND_HOST=127.0.0.1 local-home-devices-mcp
```

A non-loopback bind requires distinct authentication tokens and an explicitly configured TLS-terminating trusted proxy. Direct plaintext LAN deployment is rejected. See [Security model](docs/security-model.md).

## Capability status

Capability discovery distinguishes supported and active operations. Disabled operations are not visible or invokable. The complete behavior contract is owned by [Capability contract](docs/capability-contract.md); migration status and remaining evidence are tracked in [Migration plan](docs/migration-plan.md).

## Release integrity

CI builds one wheel, resolves runtime dependencies into a SHA-256-locked wheelhouse, probes the offline-installed wheel over real stdio, builds one image without package-index access, probes the image over real stdio and HTTP, publishes the tested image, and records `repository@sha256:digest`. Release promotion checks that the release version matches `pyproject.toml`, requires the `release` environment, verifies the exact CI identity and attestation, and promotes the digest without rebuilding.
