---
description: Operate and develop the policy-governed MCP server for local home devices.
doc_id: guide.repository-readme
type: guide
status: evolving
rigor: operational
owners: [repository-maintainers]
verification: Run the virtual-environment tests, real transport probes, exact-artifact workflow, and separately authorized real-system checks described below.
---

# Local Home Devices MCP

Version 2.0.0 is a fail-closed compatibility migration. It removes the legacy SSE/REST execution surfaces and changes public response, target-selection, and retry semantics, so the change is intentionally a major version.

The branch is an implementation candidate, not an approved ai-skills maturity claim. Candidate-local CI is diagnostic; final adoption requires immutable external verifier evidence and an independent review bound to the exact accepted SHA.

## Safe defaults

- HTTP binds to `127.0.0.1` by default and still requires an authenticated principal.
- Development static tokens require `MCP_HTTP_DEVELOPMENT_MODE=1`; production remote HTTP uses JWT/JWKS and trusted TLS termination.
- Writes and dangerous capabilities are disabled by default.
- Target-bearing calls authorize selector namespace, resolve one stable target, authorize its target ID, serialize by that ID, and revalidate identity immediately before I/O.
- Public errors are JSON machine-readable MCP tool errors with stable `code`, `retryable`, and `unknown_outcome` fields.
- Read timeouts are `DEADLINE_EXCEEDED`; only a mutation whose execution actually started can return `UNKNOWN_OUTCOME`.
- Unmigrated writes, Docker-socket access, unrestricted paths, OTA, raw commands, and OpenHASP writes remain inactive.

## Local development

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev]'
MCP_MOCK_MODE=1 ENABLE_WRITE_OPERATIONS=1 python server.py --mock-self-test
python -m pytest -m 'not real_system'
```

Transport tests spawn real stdio and Streamable HTTP endpoints and use the official MCP client. In-memory `Client(mcp)` calls are not transport evidence.

## Running

Trusted local stdio:

```bash
MCP_TRANSPORT=stdio local-home-devices-mcp
```

Authenticated loopback HTTP for development:

```bash
MCP_TRANSPORT=http \
BIND_HOST=127.0.0.1 \
MCP_HTTP_DEVELOPMENT_MODE=1 \
MCP_AUTH_READ_TOKEN='replace-with-at-least-32-random-characters' \
local-home-devices-mcp
```

A non-loopback bind requires JWT/JWKS authentication plus `MCP_TRUSTED_PROXY_TLS=1` behind a verified TLS-terminating proxy. See [Security model](docs/security-model.md).

`/ready` validates registered components plus the target registry and artifact-store dependency state. A green registration count alone is not readiness.

## Capability status

Capability discovery distinguishes supported and active operations. Disabled operations are not invokable. See [Capability contract](docs/capability-contract.md) and [Migration plan](docs/migration-plan.md).

## Release integrity

CI builds and probes the exact wheel and image. The protected release flow then takes that exact successful-CI image in an unprivileged validation job, pushes it to a separately credentialed quarantine registry, resolves and smoke-tests the registry digest, and passes only that digest to the protected publisher. The publisher performs registry-to-registry promotion and never checks out, loads, builds, or executes candidate source/image bytes.

Configure a quarantine registry on a domain distinct from `ghcr.io` with repository variables `MCP_QUARANTINE_REGISTRY` and `MCP_QUARANTINE_REPOSITORY`, plus scoped write credentials `MCP_QUARANTINE_USERNAME` / `MCP_QUARANTINE_TOKEN` and read-only credentials `MCP_QUARANTINE_READ_USERNAME` / `MCP_QUARANTINE_READ_TOKEN`. Production publication remains protected by the `release` environment.

## Acceptance boundary

Repository CI pins ai-skills revision `b54fc6b27ea80b36a70d5de73445970e17f55789` for deterministic diagnostics. Because the assessed branch controls its own workflow file and pin, that run is not independent approval authority. Final adoption evidence must be produced by a separately governed immutable verifier and independent reviewer for the exact final SHA.
