---
description: Describe the composition root, invocation pipeline, adapters, target registry, and artifacts.
doc_id: reference.system-architecture
type: reference
status: evolving
rigor: operational
owners: [repository-maintainers]
verification: Run unit, adapter integration, real stdio, real Streamable HTTP, wheel, container, and dependency-readiness probes.
---

# System architecture

`server.py` loads immutable `Settings` and delegates to `local_home_devices_mcp.composition`. The composition root creates FastMCP, authentication, the target resolver, `OperationGate`, artifact storage, adapters, and supported transports.

For every tool call, middleware authenticates the principal, authorizes capability and selector namespace, resolves and authorizes a stable target when applicable, applies a bounded principal rate limiter and absolute deadline, acquires concurrency ownership, revalidates identity, invokes the adapter, enforces the final response limit, and maps failures to stable machine-readable MCP error codes.

The HTTP boundary is separate from capability policy. It bounds connections, queue depth, queue wait, ingress read time, headers, body size, Host/Origin policy, and final buffered JSON response bytes before handing the request to FastMCP.

`LegacyRegistrationProxy` is a migration boundary. It replaces model selectors with the authorized address, wraps blocking calls in a bounded worker pool, retains ownership until cancelled physical work ends, and normalizes legacy envelopes. Global compatibility patches obtain Settings from the current invocation context so public calls are not bound to whichever server instance installed a patch first.

`/ready` checks component registration plus target-registry and artifact-store dependency state. Registration count alone is not considered readiness.

Candidate-local CI is not approval authority for itself. Final adoption/release acceptance is bound outside the assessed tree to one immutable SHA and exact artifact identities.
