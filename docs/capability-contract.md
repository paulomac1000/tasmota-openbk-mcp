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

Every registered tool has an application-owned manifest containing risk, side effects, confidentiality, idempotency mechanism, retry conditions, concurrency scope, deadline, target binding, reversibility, and active state.

Positive semantic claims are operation-specific. Legacy READ or WRITE factories are not evidence. The multi-backend `iot_set_power` capability is disabled: a Tasmota-only mocked path does not establish equivalent behavior for OpenBK, Tuya, and OpenHASP. Reactivation requires backend-specific contracts and evidence for explicit `ON` and `OFF`, invalid responses, timeout and disconnect ambiguity, read-back, and overlapping calls. `TOGGLE` remains rejected.

Legacy JSON envelopes are converted before MCP registration: successful payloads become typed data and `success:false` becomes a `ToolError`. New wrappers return typed values and let the MCP boundary map typed exceptions.

Inactive tools are disabled through the public FastMCP visibility API, so discovery and invocation agree. Changing `active_state` alone is insufficient: a capability also needs target-bound runtime integration, positive and negative tests, timeout behavior, and operation-specific manifest evidence.
