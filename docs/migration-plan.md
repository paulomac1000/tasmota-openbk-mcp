---
description: Track completed vertical slices, deferred operations, evidence, and rollback.
doc_id: workflow.ai-skills-compliance-migration
type: workflow
status: evolving
rigor: operational
owners: [repository-maintainers]
verification: Run hosted CI for the exact revision, inspect immutable artifact identities, and complete real-device checks.
---

# AI skills compliance migration plan

## Completed in this stage

- official stdio and Streamable HTTP only;
- real subprocess and HTTP protocol tests through the official client;
- stable target resolution and pre-I/O revalidation in runtime middleware;
- async target-ID locks with idle-entry cleanup;
- bounded execution for blocking legacy adapters;
- MCP-native errors for legacy failure envelopes;
- canonical `BoundTarget.address` propagation through the legacy compatibility boundary;
- cancellation-safe worker supervision that retains target locks until physical I/O finishes;
- corrected Tuya toggle and brightness-DP behavior;
- principal-bound artifact storage plus `artifact://` resource;
- separate HTTP roles and non-loopback TLS-proxy requirement;
- SHA-256-locked wheelhouse installation for the exact wheel and image;
- package-version-checked, protected-environment, digest and attestation-based release promotion.

## Deferred

- read-only discovery separated from registry persistence;
- backend-specific migration and evidence for `iot_set_power` across Tasmota, OpenBK, Tuya, and OpenHASP;
- migration of additional device writes and OpenHASP;
- production identity provider;
- Docker sidecar;
- independent review of the CI-generated transitive dependency lock and update policy;
- real-device reconciliation and disconnect tests;
- provider-backed adoption assessment and independent review.

## Rollback

Stop promotion if transport lifecycle, target revalidation, mocked adapter tests, exact wheel probe, exact image probe, digest verification, or attestation verification fails. Roll back to the previous immutable image digest with writes disabled. Do not restore the removed REST or legacy SSE bridge.
