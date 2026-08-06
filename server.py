"""Command-line entrypoint for the policy-governed MCP server."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path


def _mock_self_test() -> int:
    from local_home_devices_mcp.config import load_settings
    from local_home_devices_mcp.mock_runtime import MOCK_MANIFESTS, MockTargetResolver
    from local_home_devices_mcp.policy import OperationGate, Principal

    settings = load_settings()
    resolver = MockTargetResolver()
    gate = OperationGate(settings, MOCK_MANIFESTS, target_resolver=resolver)
    principal = Principal("mock-self-test", frozenset({"devices:admin"}), "stdio")
    state = {"power": False, "brightness": 50}

    async def run_test() -> dict[str, object]:
        before = dict(state)
        after = await gate.invoke_async(
            "mock_set_power",
            lambda identifier, power: state.update(power=power)
            or {"identifier": identifier, **state},
            {"identifier": "dev_mock_light", "power": True},
            principal,
        )
        state["power"] = before["power"]
        return {
            "success": True,
            "io": "mocked",
            "before": before,
            "after": after,
            "restored": dict(state),
            "target_revalidations": resolver.revalidations,
        }

    print(json.dumps(asyncio.run(run_test()), sort_keys=True))
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
