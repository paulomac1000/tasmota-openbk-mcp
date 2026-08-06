---
description: Define the required capability manifest and runtime mappings.
doc_id: contract.local-home-devices-capabilities
type: contract
status: evolving
rigor: normative
owners: [repository-maintainers]
verification: Run `pytest tests/unit/test_manifests.py tests/unit/test_policy.py` and inspect `/ready`.
---

# Capability contract

## Required fields

Every public tool has one application-owned manifest containing name, version, risk, side effects, confidentiality, idempotency and mechanism, retry policy, concurrency and scope, enforced timeout, confirmation hint, determinism, latency, cost, impact, reversibility, target binding, and active state.

## Conservative semantics

A class factory cannot prove semantic safety. Mutating tools default to non-retryable, non-concurrent, and non-reversible until operation-specific tests prove otherwise. Raw commands, firmware updates, factory reset, arbitrary file output, and privileged container access are inactive by default.

## Runtime mapping

- `active_state` controls invocation and readiness.
- `timeout_ms` bounds downstream timeout arguments and lock acquisition.
- `concurrent_safe: false` maps to a target-keyed lock.
- `side_effects` maps to operator and scope gates.
- `target_binding` maps to exact resolution and pre-I/O identity revalidation.
- `confidentiality` maps to minimization, redaction, retention, and audit behavior.
- `retryable` never authorizes blind retry after an ambiguous mutation outcome.

## Compatibility

The capability schema version is independent of the package version. Removing legacy transports, removing `force`, changing target selection from partial to exact, and replacing paths with artifact IDs are intentional breaking changes documented in the migration guide.
