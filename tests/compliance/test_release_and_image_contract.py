from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from scripts.lock_wheelhouse import lock_lines

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[2]


def test_hash_lock_is_generated_from_pip_report() -> None:
    report = {
        "install": [
            {
                "metadata": {"name": "local-home-devices-mcp", "version": "2.0.0"},
                "download_info": {"archive_info": {"hashes": {"sha256": "a" * 64}}},
            },
            {
                "metadata": {"name": "AnyIO", "version": "4.14.2"},
                "download_info": {"archive_info": {"hashes": {"sha256": "b" * 64}}},
            },
        ]
    }
    assert lock_lines(report) == [f"AnyIO==4.14.2 --hash=sha256:{'b' * 64}"]


def test_hash_lock_rejects_unverifiable_dependency() -> None:
    report = {
        "install": [
            {
                "metadata": {"name": "AnyIO", "version": "4.14.2"},
                "download_info": {"archive_info": {}},
            }
        ]
    }
    with pytest.raises(ValueError, match="no SHA-256"):
        lock_lines(report)


def test_container_installs_only_from_hash_locked_wheelhouse() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "--no-index" in dockerfile
    assert "--find-links=/tmp/wheelhouse" in dockerfile
    assert "--require-hashes" in dockerfile
    assert "--no-deps /tmp/package/*.whl" in dockerfile

    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "scripts/lock_wheelhouse.py" in workflow
    assert "pip download --require-hashes" in workflow
    assert "wheelhouse/" in workflow


def test_major_version_matches_breaking_contract() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert project["project"]["version"] == "2.0.0"


def test_release_uses_quarantine_digest_and_non_executing_publisher() -> None:
    workflow = (ROOT / ".github/workflows/publish.yml").read_text(encoding="utf-8")
    validate, publisher = workflow.split("\n  publish:\n", 1)
    assert "environment: release" in publisher
    assert "MCP_QUARANTINE_REGISTRY" in validate
    assert 'test "${QUARANTINE_REGISTRY,,}" != "ghcr.io"' in validate
    assert "docker load" in validate
    assert "Smoke-test exact quarantined registry digest" in validate
    assert "docker buildx imagetools create" in publisher
    assert "docker load" not in publisher
    assert "docker run" not in publisher
    assert "actions/checkout" not in publisher
    assert "docker build " not in publisher
