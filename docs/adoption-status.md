---
description: State which ai-skills compliance claims are implemented, verified, or still pending.
doc_id: reference.ai-skills-adoption-status
type: reference
status: evolving
rigor: operational
owners: [repository-maintainers]
verification: Run the CI workflow and create a provider-backed assessment only after immutable evidence and independent review exist.
---

# AI skills adoption status

## Answer

The candidate implements the architectural controls from `ai-skills` revision
`661ff01a5e70d58d6c94a12545b24647e52063ed`, but it does not claim an approved maturity
level before provider-backed CI evidence and independent review are bound to an immutable
revision.

## Implemented controls

- One FastMCP composition root and one invocation policy path.
- Official stdio and Streamable HTTP transports only.
- Complete, conservative application-owned capability manifests.
- Exact target matching, network allowlists, and identity revalidation primitives.
- Server-side scopes and operator gates independent from model arguments.
- Confined artifact IDs instead of caller-controlled paths.
- Exact wheel-to-image promotion and digest-based release promotion.
- AFDS-governed architecture, security, capability, migration, and operations documents.

## Local evidence

Run:

```bash
.venv/bin/python server.py --mock-self-test
.venv/bin/python -m pytest -m 'not real_system'
```

The local isolated environment verifies all zero-I/O tests. Official FastMCP client tests,
package installation, container smoke, AFDS validation, and AGENTS validation are executed by
hosted CI because the local environment has no package-network or container runtime access.

## Pending evidence

A schema-valid `adoption-assessment.yaml` is intentionally not committed yet. The current
`ai-skills` schema requires GitHub Actions run, job, check, artifact, report, reviewer, and digest
identities even when the result is `not-run` or the decision is `request-changes`. Inventing those
values would be false evidence. A trusted verifier must generate the assessment after CI and an
independent review exist.
The public pull request remains a draft until those hosted checks and review are complete.

Real-device checks are separately enumerated in `tests/real_system_todos.py` and remain blocking
for claims about physical target identity, ambiguous mutation outcomes, expected disconnects,
and backend-specific compensation.

## Failure and recovery

If hosted conformance fails, keep the pull request in draft, leave unsafe adapters inactive, and
fix the canonical implementation or test. Do not weaken the assessment, restore the REST bridge,
or insert placeholder provider identities.

## Verification

The acceptance condition is a schema-valid provider-backed assessment referencing the exact
candidate SHA, exact wheel and image digests, official-client transport results, and an
independent GitHub review.
