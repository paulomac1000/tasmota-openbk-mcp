#!/usr/bin/env python3
"""Export canonical active capability manifests for exact-schema validation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from local_home_devices_mcp.manifests import is_runtime_active, normalize_catalog


def _catalog(mock: bool):
    if mock:
        from local_home_devices_mcp.mock_runtime import MOCK_MANIFESTS

        return normalize_catalog(MOCK_MANIFESTS)
    from tools.constants import TOOL_MANIFESTS

    return normalize_catalog(TOOL_MANIFESTS)


def export(output: Path, *, mock: bool) -> list[Path]:
    output.mkdir(parents=True, exist_ok=True)
    if output.is_symlink():
        raise ValueError("output directory must not be a symlink")
    paths: list[Path] = []
    for capability_id, manifest in sorted(_catalog(mock).items()):
        if not is_runtime_active(manifest):
            continue
        path = output / f"{capability_id}.json"
        path.write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        paths.append(path)
    if not paths:
        raise RuntimeError("no active canonical capability manifests were exported")
    return paths


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--mock", action="store_true")
    args = parser.parse_args()
    paths = export(args.output, mock=args.mock)
    print(f"exported canonical capability manifests: {len(paths)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
