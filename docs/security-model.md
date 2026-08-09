---
description: Define authentication, target authorization, artifacts, and privileged-operation boundaries.
doc_id: reference.security-model
type: reference
status: evolving
rigor: operational
owners: [repository-maintainers]
verification: Run policy, target-binding, artifact, HTTP-boundary, auth, and real-transport tests for the assessed revision.
---

# Security model

## Trust boundary

The MCP composition root owns authentication and the invocation gate. Legacy adapters do not approve callers, choose fallback targets, or weaken operator policy. Public calls carry the immutable `Settings` snapshot in invocation context; the legacy module-level write flag is a compatibility fallback only for direct adapter tests/scripts outside the governed path.

## HTTP authentication

All HTTP, including loopback HTTP, requires a configured identity provider. Static tokens are development/test-only and require `MCP_HTTP_DEVELOPMENT_MODE=1` (or mock mode). Production uses JWT/JWKS. A non-loopback bind additionally requires `MCP_TRUSTED_PROXY_TLS=1`; this acknowledges a separately verified TLS-terminating trusted proxy and does not create TLS itself.

Static development roles are separated into read, sensitive-read, write, dangerous, and admin tokens. Scope checks and stable-target ACLs remain server-side. Malformed scope/target claims fail closed.

## HTTP resource boundary

Host and Origin policy run before dispatch. Connection admission occurs before request-body buffering. Queue wait and ingress-body read have explicit time limits; body/header sizes and concurrent connections are bounded. Stateless JSON responses are retained only up to the effective capability wire limit, so an oversized response cannot force unbounded response-memory accumulation.

## Target authorization

For target-bearing tools the order is selector normalization, capability/selector authorization, exact resolution within the authorized namespace, stable-target authorization, target-keyed concurrency admission, identity/address revalidation, then replacement of the model selector with the authorized address immediately before the legacy adapter call. Partial matching and silent fallback are prohibited.

## Blocking adapters and ambiguous outcomes

Synchronous legacy adapters run in a bounded AnyIO worker pool. Cancellation retains concurrency ownership until physical work stops. A timeout before mutation execution starts is `DEADLINE_EXCEEDED`; a timeout after mutation execution starts is `UNKNOWN_OUTCOME` and requires reconciliation before retry. Read operations never report mutation-unknown wording.

## Artifacts

Artifact roots reject existing symlink components. Artifacts use opaque 128-bit IDs, server-owned paths, exclusive no-follow data creation where supported, restrictive modes, quotas, expiry, integrity hashes, and owner checks. Readiness includes artifact-store accessibility.

## Privileged operations

Docker socket access, caller-selected paths, firmware update, raw commands, factory reset, direct DPS mutation, and unbound OpenHASP writes remain inactive until separately reviewed. Docker operations require a least-privileged sidecar; the MCP container must not mount `docker.sock`.
