---
description: Explain the server boundaries, invocation flow, lifecycle, and failure behavior.
doc_id: system.local-home-devices-architecture
type: system
status: evolving
rigor: operational
owners: [repository-maintainers]
verification: Run `pytest tests/unit/test_policy.py tests/integration/test_mock_runtime.py`.
---

# System architecture

## Responsibility

The server translates MCP tool calls into bounded operations against explicitly configured home-device adapters. It does not provide a generic REST executor, arbitrary network proxy, shell, filesystem API, or Docker administration API.

## Composition

`server.py` loads immutable settings and delegates to `local_home_devices_mcp.composition`. The composition root creates one FastMCP server, registers adapters, installs one invocation middleware chain, and starts either stdio or Streamable HTTP.

The domain-independent control path is:

1. FastMCP validates the MCP request and tool schema.
2. HTTP authentication runs before tool invocation; stdio inherits the local process trust boundary.
3. `OperationGate` loads the application-owned manifest.
4. Principal scope, active state, operator gates, input safety, rate limit, target key, concurrency, and deadline are enforced.
5. The adapter performs bounded backend I/O.
6. The adapter returns a structured, sanitized result or a protocol-native tool error.

## State and identity

Discovery records mutable addresses and stable identity attributes. Exact target names or `target_id` values are accepted. Partial matches and silent fallback are forbidden. Before high-impact I/O, adapters must revalidate that the current address still represents the authorized stable identity.

## Failure modes

- Missing manifest: registration/readiness failure.
- Missing scope or operator gate: tool error before backend I/O.
- Unknown or ambiguous target: fail closed; never pick the first result.
- Changed identity: abort before mutation.
- Deadline or ambiguous mutation outcome: return unknown outcome and reconcile before any retry.
- Optional backend unavailable: capability remains governed but inactive/unavailable.
- Artifact too large or unsafe: reject without creating a partial file.

## Lifecycle

`/health` proves the process and HTTP stack respond. `/ready` compares registered and governed capability sets. Shutdown and transport lifecycle are owned by FastMCP rather than independent background HTTP servers.
