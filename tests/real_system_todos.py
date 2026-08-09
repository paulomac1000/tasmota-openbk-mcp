"""Physical-system verification that must be rerun on the exact final 2.0.0 artifact.

TODO(real-system-agent): Deploy the exact CI-produced 2.0.0 image by immutable digest and
rerun official-client list/info/wifi/power reads against representative OpenBK, Tasmota,
Tuya, OpenHASP, and Hikvision devices. Record exact image digest, device classes, and results.

TODO(real-system-agent): Verify `/ready` transitions on the real deployment when the device
registry is valid, deliberately unavailable/empty, and restored. Confirm orchestration does
not report `ready` while mandatory target-registry access is unavailable.

TODO(real-system-agent): Verify target identity revalidation against a device whose DHCP
address changes between authorization and I/O. The authorized stable identity must not move
silently to another address/device.

TODO(real-system-agent): Verify OTA expected-disconnect and unknown-outcome reconciliation
using signed firmware hosted on an operator allowlisted origin. Do not auto-retry ambiguous
mutation outcomes.

TODO(real-system-agent): Verify Hikvision gate authorization with a physical relay and prove
that an ambiguous timeout is never retried automatically.

TODO(real-system-agent): Verify machine-readable HTTP/stdio error codes on real failure paths,
especially DEADLINE_EXCEEDED versus UNKNOWN_OUTCOME, target disappearance, and authorization.

TODO(real-system-agent): Verify Docker sidecar confinement once the privileged adapter is split
from the MCP process; the MCP container must not mount docker.sock directly.

TODO(release-owner): Configure an isolated quarantine registry on a domain other than ghcr.io,
with scoped write and separate read-only credentials, then execute a disposable 2.0.0 release
rehearsal proving quarantine digest == promoted GHCR digest and that the protected publisher
never checks out, loads, builds, or executes the candidate image/source.

TODO(acceptance-owner): Produce provider-backed adoption evidence with an immutable verifier
outside the assessed tree and obtain an independent review bound to the same exact final SHA.
"""
