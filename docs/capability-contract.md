---
description: Define capability manifests, active-state rules, errors, targets, and retries.
doc_id: reference.capability-contract
type: reference
status: evolving
rigor: operational
owners: [repository-maintainers]
verification: Enumerate registered and active components and run positive plus negative tests for every reactivated capability.
---

# Capability contract

Every public component has an application-owned canonical manifest. The repository also preserves reviewed legacy semantic metadata under canonical extensions while ai-skills' machine schema and richer normative manifest reference remain separate representations.

Positive semantic claims are operation-specific. Legacy factories are not evidence. Multi-backend mutations stay inactive until backend-specific contracts prove explicit state transitions, invalid-response handling, timeout/disconnect ambiguity, read-back/reconciliation, and overlap behavior.

Public failures cross MCP as JSON error text with stable fields: `code`, `message`, `retryable`, and `unknown_outcome`. Callers must branch on `code`, not parse prose. `DEADLINE_EXCEEDED` means execution did not establish an ambiguous mutation; `UNKNOWN_OUTCOME` is reserved for a mutation whose execution started before the deadline/cancellation outcome became unknowable.

Inactive tools are disabled through the public FastMCP visibility API so discovery and invocation agree. Changing `active_state` alone is insufficient: target binding, dependency readiness, positive/negative tests, timeout behavior, and operation-specific evidence are required before reactivation.
