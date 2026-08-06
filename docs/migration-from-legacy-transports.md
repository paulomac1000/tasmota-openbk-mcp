---
description: Migrate clients from custom REST and legacy SSE to supported MCP transports.
doc_id: workflow.migrate-legacy-mcp-transports
type: workflow
status: active
rigor: operational
owners: [repository-maintainers]
verification: Connect an official FastMCP client to stdio and `/mcp`, list tools, and call a read-only mock tool.
---

# Migrate from legacy transports

## Preconditions

Upgrade the client to support MCP Streamable HTTP or stdio. Record any dependency on `/sse`, `/messages`, `/api/tools`, direct IP selectors, `force`, or caller-selected output paths.

## Procedure

1. Replace `http://host:9101/sse` with `http://host:9102/mcp`.
2. Remove calls to `/api/tools/*`; use MCP `tools/list` and `tools/call` through an official client.
3. Supply bearer authentication for non-loopback HTTP.
4. Replace partial device names with an exact discovered name or stable target ID.
5. Replace `TOGGLE` with a read followed by explicit `ON` or `OFF`.
6. Replace caller paths with server-issued artifact IDs.
7. Do not send `force`; dangerous approval is operator-side.

## Verification

Run the official-client test in `tests/integration/test_fastmcp_protocol.py`. Confirm `/ready` reports no registered tool without a manifest.

## Safe stop and rollback

Do not re-enable the custom REST bridge as rollback. If a client cannot migrate, keep the previous server artifact isolated on loopback with writes disabled while upgrading the client. Legacy SSE may be run only from the previous artifact under a documented, time-bounded exception.
