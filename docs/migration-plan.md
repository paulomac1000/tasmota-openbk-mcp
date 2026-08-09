---
description: Track completed vertical slices, deferred operations, evidence, and rollback.
doc_id: workflow.ai-skills-compliance-migration
type: workflow
status: evolving
rigor: operational
owners: [repository-maintainers]
verification: Run candidate CI for the exact revision, inspect immutable artifact identities, and complete separately authorized real-system and external-acceptance checks.
---

# AI skills compliance migration plan

## Completed in the implementation candidate

- major-version 2.0 contract for removed transports and changed target/retry/response semantics;
- official stdio and stateless JSON Streamable HTTP only;
- exact target authorization and pre-I/O revalidation;
- bounded principal rate-limit registry and target/resource concurrency;
- bounded HTTP admission, queue wait, ingress, headers, body, and response capture;
- stable machine-readable public error taxonomy and mutation-only unknown outcomes;
- cancellation-safe supervision for blocking legacy workers;
- principal-owned artifact resource with symlink-root policy, quota, expiry, and integrity;
- dependency-aware readiness;
- exact wheel/image CI and isolated-quarantine digest promotion design;
- ai-skills candidate diagnostic pin updated to `b54fc6b27ea80b36a70d5de73445970e17f55789`.

## Deferred / requires external or physical evidence

- provider-backed adoption assessment and independent review from authority outside the candidate tree;
- first real execution of the isolated quarantine registry release path with scoped credentials;
- real-device DHCP identity-change, disconnect/reconciliation, Hikvision relay, and backend compensation checks;
- backend-specific migration/evidence for additional mutations and OpenHASP;
- production identity-provider deployment evidence;
- least-privileged Docker sidecar;
- read-only discovery separated from registry persistence.

Previous 1.7-era real-device observations do not automatically transfer to 2.0.0 after runtime-boundary changes. Re-run the cases in `tests/real_system_todos.py` on the exact final artifact.

## Rollback

Stop promotion if transport lifecycle, target revalidation, dependency readiness, exact wheel/image probes, quarantine digest verification, or external acceptance fails. Roll back to the previous immutable production digest with writes disabled. Do not restore legacy REST or SSE execution bridges.
