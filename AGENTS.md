# AGENTS.md

These instructions apply to the repository. User and platform instructions take precedence.
Nested instructions may add only material subtree-specific differences.

## Mission and non-goals

- Maintain a policy-governed MCP server for explicitly authorized local home devices.
- Do not add generic network proxying, arbitrary filesystem access, shell execution,
  alternate public tool executors, or model-controlled approval.

## Operating modes

- Read-only audit: inspect and report without changing repository or external state.
- Implementation: reproduce with mock data, add regression evidence, change the canonical
  owner, and run the focused and full gates.
- Release: promote only an immutable artifact already tested for the exact revision.

## Read before editing

1. Read [the system architecture](docs/system-architecture.md) before changing composition,
   transports, lifecycle, or adapter boundaries.
2. Read [the security model](docs/security-model.md) before changing authentication,
   authorization, targets, URLs, files, credentials, or privileged operations.
3. Read [the capability contract](docs/capability-contract.md) before adding or changing a tool.
4. Read [the adoption status](docs/adoption-status.md) before making a compliance claim.

## Sources of truth

1. `local_home_devices_mcp/policy.py` owns invocation authorization, rate limits,
   concurrency, and deadlines.
2. `local_home_devices_mcp/manifests.py` owns capability classification and active state.
3. `local_home_devices_mcp/targeting.py` owns exact target resolution and identity binding.
4. `local_home_devices_mcp/artifacts.py` owns filesystem confinement.
5. `tests/` owns executable regressions. Documentation summarizes and links these owners.

Stop when implementation, tests, and normative documents disagree. Reconcile the canonical
owner instead of selecting the easiest version.

## Architecture and safety boundaries

- `local_home_devices_mcp/composition.py` is the only public composition root.
- `tools/` contains backend adapters. Adapters must not add transports or bypass policy.
- Missing or incomplete manifests fail closed. Inactive tools are hidden from discovery.
- Never add `force`, unsafe fallback, partial target selection, arbitrary paths, unrestricted
  URLs, or caller-selected retry after an ambiguous mutation.
- Never mount the Docker socket into the MCP process. Privileged operations require an
  isolated, least-privileged sidecar and remain disabled until separately verified.
- Ordinary tests must not contact devices, MQTT, cloud APIs, Docker, or external networks.
  Mark physical-system checks `real_system` and keep them opt-in.
- Never log credentials, local keys, bearer tokens, camera data, or raw personal data.

## Commands

- Setup: `python -m venv .venv && .venv/bin/python -m pip install -e '.[dev]'`
- Focused check: `python -m pytest tests/unit tests/integration/test_mock_runtime.py -q`
- Full local gate: `python -m pytest -m 'not real_system'`
- Mock application smoke: `python server.py --mock-self-test`
- Exact artifact gate: `python -m build` followed by installation and smoke of `dist/*.whl`

Hosted CI additionally runs lint, typing, security, AFDS and AGENTS validation, official-client
MCP lifecycle tests, exact-wheel installation, and exact-image smoke tests.

## Definition of done

- Changed behavior has focused regression evidence and no alternate policy path.
- Public schemas, manifests, discovery, documentation, and implementation agree.
- The full gate passes for the exact revision, or skipped checks are reported explicitly.
- Artifacts are built once, identified by digest, tested, and promoted without rebuilding.
- The final diff contains no secrets, private data, unrelated files, or temporary workflows.
- Residual physical-system and provider-backed evidence is recorded without claiming approval.
