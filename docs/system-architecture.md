---
description: Describe the composition root, invocation pipeline, adapters, target registry, and artifacts.
doc_id: reference.system-architecture
type: reference
status: evolving
rigor: operational
owners: [repository-maintainers]
verification: Run unit, adapter integration, real stdio, real Streamable HTTP, wheel, and container probes.
---

# System architecture

`server.py` loads immutable `Settings` and delegates to `local_home_devices_mcp.composition`. The composition root creates FastMCP, authentication, the target resolver, `OperationGate`, artifact storage, adapters, and official transports.

For every tool call, middleware resolves the manifest, authenticates the principal, authorizes capability and confidentiality scopes, resolves a stable target when applicable, applies rate limits and a deadline, acquires an async lock keyed by stable target ID, revalidates identity, invokes the adapter, and maps typed failures to MCP errors.

Legacy adapters are registered through `LegacyRegistrationProxy`. It wraps synchronous calls before schema registration, executes them in a bounded worker pool, and converts JSON envelopes to typed outcomes. This is a migration boundary, not the target architecture.

Tests are split into direct adapter tests, invocation-kernel tests, and real protocol tests. Real protocol tests spawn the server over stdio or HTTP and use the official MCP client through initialize, list, call, and shutdown lifecycle.
