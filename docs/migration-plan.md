---
description: Define the behavior changes, rollback, and residual risks for the compliance refactor.
doc_id: workflow.ai-skills-compliance-migration
type: workflow
status: evolving
rigor: operational
owners: [repository-maintainers]
verification: Run official-client lifecycle tests, exact artifact smoke tests, and the provider-backed adoption assessment for the final revision.
---

# AI skills compliance migration plan

## Answer

Migrate from the custom REST and legacy SSE architecture to a single FastMCP 3 policy path,
while retaining backend adapter code only behind conservative manifests. Unsafe or unverified
adapters remain inactive rather than being advertised with unsupported safety claims.

## Scope

The migration covers MCP transport, invocation policy, capability manifests, target selection,
artifact handling, tests, documentation, CI, and release promotion. It does not claim that
physical-device behavior is verified without real-system evidence.

## Behavior changes

- Remove legacy HTTP+SSE and the custom `/api/tools` executor.
- Reject partial target names, model-controlled `force`, `TOGGLE`, and arbitrary output paths.
- Disable raw commands, OTA, factory reset, Docker-socket access, unbound OpenHASP hosts,
  direct Tuya DPS mutation, and other legacy writes until operation-specific evidence exists.
- Treat discovery as a write while it persists a cache.
- Use FastMCP 3.4.6 instead of the FastMCP 2 line named by the assessed standards revision.

## Evidence

Implementation owners are `local_home_devices_mcp/composition.py`, `policy.py`,
`manifests.py`, `targeting.py`, and `artifacts.py`. Regression owners are `tests/unit`,
`tests/integration/test_mock_runtime.py`, and the official-client tests.

## Failure and recovery

Stop deployment if official-client initialize, discovery, representative read, write boundary,
or exact artifact smoke fails. Roll back to the previous immutable artifact on loopback with
writes disabled. Do not restore the removed REST bridge in the candidate branch.

## Residual risks

- Physical-device identity, disconnect, compensation, and ambiguous-outcome tests require an
  authorized real-system agent.
- Transitive dependency hashes must be generated and reviewed on a trusted networked builder.
- Privileged Docker operations require a separate sidecar.
- The assessed `ai-skills` revision lacks a secure-current SDK lane; this repository uses the
  current FastMCP 3 line as a documented safety override.

## Verification

Run the full hosted CI workflow, inspect exact artifact digests, and generate the external
provider-backed assessment described in [AI skills adoption status](adoption-status.md).
