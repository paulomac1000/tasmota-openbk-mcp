#!/usr/bin/env python3
"""Create a hash-locked runtime requirements file from a pip install report."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

_LOCAL_PROJECT = "local-home-devices-mcp"
_NORMALIZE = re.compile(r"[-_.]+")


def normalize_name(name: str) -> str:
    return _NORMALIZE.sub("-", name).lower()


def lock_lines(report: dict[str, Any]) -> list[str]:
    resolved: dict[str, tuple[str, str, str]] = {}
    for item in report.get("install", []):
        metadata = item.get("metadata") or {}
        name = str(metadata.get("name", "")).strip()
        version = str(metadata.get("version", "")).strip()
        if not name or not version:
            raise ValueError("pip report entry is missing package name or version")
        normalized = normalize_name(name)
        if normalized == _LOCAL_PROJECT:
            continue
        archive = (item.get("download_info") or {}).get("archive_info") or {}
        hashes = archive.get("hashes") or {}
        digest = hashes.get("sha256")
        if not digest:
            legacy_hash = str(archive.get("hash", ""))
            if legacy_hash.startswith("sha256="):
                digest = legacy_hash.removeprefix("sha256=")
        if not digest or not re.fullmatch(r"[0-9a-fA-F]{64}", str(digest)):
            raise ValueError(f"{name}=={version} has no SHA-256 in pip report")
        candidate = (name, version, str(digest).lower())
        previous = resolved.get(normalized)
        if previous is not None and previous != candidate:
            raise ValueError(f"conflicting resolutions for {name}")
        resolved[normalized] = candidate
    if not resolved:
        raise ValueError("pip report did not contain runtime dependencies")
    return [
        f"{name}=={version} --hash=sha256:{digest}"
        for _normalized, (name, version, digest) in sorted(resolved.items())
    ]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("report", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    report = json.loads(args.report.read_text(encoding="utf-8"))
    args.output.write_text("\n".join(lock_lines(report)) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
