---
description: State which ai-skills compliance claims are implemented, verified, or still pending.
doc_id: reference.ai-skills-adoption-status
type: reference
status: evolving
rigor: operational
owners: [repository-maintainers]
verification: Run candidate-local diagnostics, then bind external provider evidence and an independent review to the exact immutable candidate SHA.
---

# AI skills adoption status

## Answer

This branch is a candidate adoption of `mcp-server-architect` 1.2.0 from ai-skills revision `b54fc6b27ea80b36a70d5de73445970e17f55789`. The application package is 2.0.0 because the migration removes transports and changes public target-selection, response, and retry semantics.

It does **not** claim an approved maturity level. The repository-controlled CI workflow is useful diagnostic evidence but cannot approve the same candidate tree that controls the verifier pin and workflow definition.

## Implemented controls

- One FastMCP composition root and one application-owned invocation kernel.
- Capability and selector authorization before network-backed target resolution, followed by exact stable-target authorization and pre-I/O identity revalidation.
- Official stdio and Streamable HTTP only.
- Conservative canonical manifests; unclassified legacy capabilities fail closed.
- Bounded HTTP admission, queue wait, ingress read, body size, header size, connection count, and response capture.
- Bounded principal rate-limiter state.
- Stable machine-readable public error codes with mutation-only unknown-outcome semantics.
- Principal-owned artifacts with confined paths, integrity, retention, quota, and governed resource access.
- Exact wheel/image CI plus quarantine-digest release promotion with no candidate execution in the protected publisher.

## Candidate-local verification

Run:

```bash
MCP_MOCK_MODE=1 ENABLE_WRITE_OPERATIONS=1 python server.py --mock-self-test
python -m pytest -m 'not real_system'
```

Hosted CI additionally executes Ruff, mypy, Bandit, capability-manifest validation, AFDS/AGENTS/workflow policy checks, exact-wheel installation, official-client stdio/HTTP probes, and the exact container artifact. Every source change invalidates previous exact-SHA CI evidence.

## Pending acceptance evidence

Final approval requires all of the following to reference one immutable candidate SHA:

- a schema-valid provider-backed migration/adoption assessment;
- exact workflow/run and wheel/image identities;
- acceptance validation from an immutable verifier outside the assessed candidate tree;
- an independent reviewer who did not author the candidate or its evidence;
- authorized real-system evidence for the physical-device cases listed in `tests/real_system_todos.py`.

Release quarantine credentials and registry isolation are deployment-owner configuration and must be exercised before the first production 2.0.0 promotion.

## Failure and recovery

Keep unsafe adapters inactive when any required evidence is missing. Do not weaken the assessment, restore the removed REST/SSE bridges, interpret an unassigned runner as success, or manufacture placeholder reviewer/run/digest identities.
