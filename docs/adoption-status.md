---
description: State which ai-skills compliance claims are implemented, verified, or still pending.
doc_id: reference.ai-skills-adoption-status
type: reference
status: evolving
rigor: operational
owners: [repository-maintainers]
verification: Run the exact-revision CI workflow and create provider-backed assessment evidence only after independent review exists.
---

# AI skills adoption status

## Answer

This branch is a candidate adoption of `mcp-server-architect` version `1.2.0` from
`ai-skills` revision `c6dc6b13b2dd40b6e087140cd071b45067d75b39`. It does not claim an
approved maturity level before provider-backed CI evidence and independent review are bound to
an immutable project revision.

The project uses the independently distributed `fastmcp==3.4.6` package. The pinned `ai-skills`
FastMCP profile has no verified baseline versions or repository-tested protocol revisions for
that SDK family. Therefore `3.4.6` is a repo-local candidate lane backed by this repository's own
tests; it is not presented as an `ai-skills`-verified FastMCP baseline.

## Implemented controls

- One FastMCP composition root and application-owned invocation kernel for public components.
- Capability and selector-namespace authorization before target resolution, followed by exact
  stable-target authorization and identity revalidation.
- Official stdio and Streamable HTTP transports only.
- Complete, conservative application-owned capability manifests that reject unknown or
  unclassified legacy capabilities instead of defaulting them to read access.
- One absolute request deadline propagated through resolution, concurrency admission,
  revalidation, and backend execution.
- Server-side scopes and operator gates independent from model arguments.
- Principal-bound opaque artifact IDs and governed artifact-resource access.
- Exact wheel-to-image promotion and digest-based release promotion.
- AFDS-governed architecture, security, capability, migration, and operations documents.

## Local evidence

Run:

```bash
.venv/bin/python server.py --mock-self-test
.venv/bin/python -m pytest -m 'not real_system'
```

The local isolated environment is used for every zero-I/O test available in the workspace.
Hosted CI remains authoritative for the pinned Ruff, mypy, Bandit, FastMCP client, exact-wheel,
and container lanes that are unavailable in the restricted local package/network environment.

## Pending evidence

A schema-valid `migration-assessment.yaml` is not treated as complete until its exact project
revision, exact `ai-skills` revision, skill version, maturity/profile selection, provider-backed
workflow evidence, artifact identities, and independent decision all refer to the same immutable
candidate. Placeholder run IDs, digests, reviewers, or approval decisions are forbidden.

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
independent review. Until then the repository describes itself as a candidate adoption only.
