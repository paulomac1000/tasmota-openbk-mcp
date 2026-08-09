"""Command-line entrypoint for the policy-governed MCP server."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path


def _mock_self_test() -> int:
    from local_home_devices_mcp.config import load_settings
    from local_home_devices_mcp.mock_runtime import run_mock_self_test

    result = run_mock_self_test(load_settings())
    print(json.dumps(result, sort_keys=True))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mock-self-test", action="store_true")
    args = parser.parse_args()
    if args.mock_self_test:
        os.environ.setdefault("MCP_MOCK_MODE", "1")
        os.environ.setdefault("ENABLE_WRITE_OPERATIONS", "1")
        os.environ.setdefault("MCP_ARTIFACT_ROOT", str(Path("data/test-artifacts").resolve()))
        return _mock_self_test()
    from local_home_devices_mcp.composition import run

    run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
