---
description: Record why stdio and Streamable HTTP are the only supported MCP transports.
doc_id: decision.supported-mcp-transports
type: decision
status: active
rigor: normative
owners: [repository-maintainers]
verification: Inspect `server.py` and run the official-client transport tests.
---

# Supported MCP transports

## Context

The previous server implemented legacy SSE and a partial custom JSON-RPC/REST bridge. The paths had different policy coverage and did not implement the complete MCP lifecycle.

## Decision

Support FastMCP stdio and Streamable HTTP only. FastMCP owns protocol framing, sessions, schemas, lifecycle, and errors. Health and readiness are custom routes on the same HTTP application, not independent tool executors.

## Alternatives

Keeping SSE for convenience was rejected because it preserves a deprecated contract and doubles conformance work. Keeping REST as an administrative shortcut was rejected because direct function invocation bypassed MCP and policy middleware.

## Consequences and review trigger

Clients must migrate. Reconsider only if the MCP specification introduces a new supported transport and the official SDK provides a complete implementation with conformance tests.
