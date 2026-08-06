---
description: Record the decision to bind authorization and concurrency to stable target identity.
doc_id: decision.runtime-target-binding
type: decision
status: accepted
rigor: operational
owners: [repository-maintainers]
verification: Run alias-concurrency, exact-resolution, identity-change, and migrated set-power tests.
---

# Runtime target binding

## Decision

Target-bearing calls resolve an exact selector to `BoundTarget` before lock acquisition. Authorization context and concurrency use `target_id`, not the caller's alias or address. The resolver re-reads the registry immediately before adapter invocation and rejects changes to target ID, address, or fingerprint.

## Consequences

Two aliases for the same device serialize on one async lock. Direct adapter re-resolution remains only as a bounded compatibility behavior and is forced exact. Future adapters must accept `BoundTarget` directly before they can remove the compatibility layer.
