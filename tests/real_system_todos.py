"""Real-system verification placeholders.

TODO(real-system-agent): Verify target identity revalidation against a device whose DHCP
address changes between authorization and I/O.

TODO(real-system-agent): Verify OTA expected-disconnect and unknown-outcome reconciliation
using signed firmware hosted on an operator allowlisted origin.

TODO(real-system-agent): Verify Hikvision gate authorization with a physical relay and prove
that an ambiguous timeout is never retried automatically.

TODO(real-system-agent): Verify Docker sidecar confinement once the privileged adapter is
split from the MCP process; the MCP container must not mount docker.sock directly.
"""
