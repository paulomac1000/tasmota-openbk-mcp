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
6. replace the model-supplied selector at the compatibility boundary with the authorized `BoundTarget.address`;
7. invoke the adapter without a second registry lookup.

Partial name matching and silent fallback are prohibited. Legacy adapters receive only the canonical authorized address. The compatibility resolver recognizes that address from invocation context and never switches to a newly matching cache record after revalidation.

## Blocking adapters and ambiguous outcomes

Legacy synchronous adapters run through a bounded AnyIO worker pool. A client deadline cannot stop an already-running system call, so cancellation is shielded until the worker exits and the target lock remains owned for the entire physical operation. The client then receives an ambiguous-outcome timeout. Such mutations are not automatically retried and require reconciliation before a later attempt. Unverified mutations stay inactive.

## Artifacts

Artifacts use opaque 128-bit identifiers, server-owned paths, exclusive no-follow creation where supported, `0600` files, per-item and total quotas, expiry, integrity hashes, and principal ownership. The `artifact://<id>` resource is registered in mock and production compositions and requires sensitive or admin scope plus owner matching unless the caller is an administrator. Production device adapters are not yet all wired as artifact writers and must be migrated separately.

## Privileged operations

Docker socket access, caller-selected paths, firmware update, raw commands, factory reset, direct DPS mutation, and unbound OpenHASP writes remain disabled. Docker operations require a separately reviewed least-privileged sidecar before reactivation.
