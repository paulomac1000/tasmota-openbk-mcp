---
description: Define authentication, authorization, target, data, and privileged-operation controls.
doc_id: system.local-home-devices-security
type: system
status: evolving
rigor: normative
owners: [repository-maintainers]
verification: Run `pytest tests/unit/test_policy.py tests/unit/test_targeting.py tests/unit/test_artifacts.py`.
---

# Security model

## Trust boundaries

HTTP clients are untrusted until FastMCP authentication succeeds. The current repository implements only a static bearer-token verifier for controlled local or LAN use; an internet-facing deployment is not supported until an external identity-provider adapter is implemented and tested. Stdio callers inherit the operating-system identity and permissions of the process launcher. Tool descriptions, model arguments, device responses, logs, filenames, URLs, and discovery records remain untrusted data.

## Authorization

Authorization is server-side. `requires_confirmation` is a consumer hint, not permission. Model arguments cannot enable writes, dangerous tools, direct IP targeting, privileged adapters, or retries.

Scopes are:

- `devices:read`
- `devices:sensitive`
- `devices:write`
- `devices:dangerous`
- `devices:admin` as an operator-controlled superset

Writes require both scope and `ENABLE_WRITE_OPERATIONS=1`. Dangerous operations additionally require `ENABLE_DANGEROUS_OPERATIONS=1` and remain inactive unless an operation-specific server-side approval mechanism exists.

## Targets and SSRF

Selectors are normalized without network I/O. Network-backed resolution follows authorization of the selector namespace. Literal targets must be IPv4 addresses in the operator allowlist. Discovery scans are private and bounded. Redirect, DNS, OTA, and webhook behavior must not permit a target to escape the authorized network or hostname allowlist.

## Files and artifacts

Clients receive artifact IDs, not filesystem paths. The artifact store creates unpredictable names under one root, uses exclusive no-follow creation where available, applies mode `0600`, enforces size limits, and verifies containment on read.

## Privileged adapters

Docker-socket capabilities are disabled. A future implementation must use a separate least-privileged sidecar with a fixed RPC contract and container allowlist. The main MCP process must not mount `/var/run/docker.sock`.

## Sensitive data

Tuya local keys, MQTT credentials, bearer tokens, camera snapshots, logs, MAC addresses, and alarm-server configuration receive explicit confidentiality classes. Responses and logs are minimized and sanitized. Credential files require restricted permissions and must not follow symlinks.
