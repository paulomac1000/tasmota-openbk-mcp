#!/usr/bin/env python3
"""Local Home Devices MCP entrypoint.

Only official FastMCP stdio and Streamable HTTP transports are supported.
Legacy HTTP+SSE and the custom REST tool bridge were removed because they
created independent policy paths and incomplete MCP lifecycle behavior.
"""

from __future__ import annotations

import argparse
import json
import os
from typing import Sequence

from local_home_devices_mcp.composition import run
from local_home_devices_mcp.config import load_settings
from local_home_devices_mcp.mock_runtime import run_mock_self_test


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mock-self-test",
        action="store_true",
        help="run a deterministic zero-I/O policy and adapter smoke test",
    )
    args = parser.parse_args(argv)
    if args.mock_self_test:
        os.environ.setdefault("MCP_MOCK_MODE", "1")
        os.environ.setdefault("ENABLE_WRITE_OPERATIONS", "1")
        result = run_mock_self_test(load_settings())
        print(json.dumps(result, sort_keys=True))
        return 0 if result.get("success") else 1
    run(load_settings())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
