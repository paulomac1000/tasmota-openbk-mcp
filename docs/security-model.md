---
description: Define authentication, target authorization, artifacts, and privileged-operation boundaries.
doc_id: reference.security-model
type: reference
status: evolving
rigor: operational
owners: [repository-maintainers]
verification: Run policy, target-binding, artifact, auth, and real-transport tests for the assessed revision.
---

# Security model

## Trust boundary

The MCP composition root owns authentication and the invocation gate. Adapter modules do not approve callers, choose fallback targets, or weaken operator policy.

## HTTP authentication

Loopback HTTP may serve anonymous read-only calls. A non-loopback bind is rejected unless authentication is configured and `MCP_TRUSTED_PROXY_TLS=1` confirms that a trusted reverse proxy terminates TLS. This flag does not create TLS; deployment owners must prove proxy and network configuration separately.

Static tokens are separated by role:

- read token: `devices:read`;
- write token: read, sensitive read, and write;
- admin token: `devices:admin`.

Dangerous access is not granted to every valid token. Static verification remains suitable only for controlled environments; production should replace it with reviewed JWT/JWKS or introspection.

## Target authorization

For target-bearing tools, runtime order is:

1. parse the local selector;
2. authorize the capability and selector form;
3. resolve an exact cached record to `BoundTarget`;
4. use `BoundTarget.target_id` as the concurrency key;
5. re-read the registry and revalidate address plus fingerprint;
6. invoke the adapter.

Partial name matching and silent fallback are prohibited. An adapter may receive the legacy selector for compatibility, but exact resolution is installed globally and the authorized binding remains in request context.

## Blocking adapters and ambiguous outcomes

Legacy synchronous adapters run through a bounded AnyIO worker pool. Cancellation abandons the wait but cannot stop an already-running system call. Therefore migrated mutations have backend timeouts, are not automatically retried, and require reconciliation before retry after a timeout. Unverified mutations stay inactive.

## Artifacts

Artifacts use opaque 128-bit identifiers, server-owned paths, exclusive no-follow creation where supported, `0600` files, per-item and total quotas, expiry, integrity hashes, and principal ownership. `artifact://<id>` reads require sensitive or admin scope and owner matching unless the caller is an administrator.

## Privileged operations

Docker socket access, caller-selected paths, firmware update, raw commands, factory reset, direct DPS mutation, and unbound OpenHASP writes remain disabled. Docker operations require a separately reviewed least-privileged sidecar before reactivation.
