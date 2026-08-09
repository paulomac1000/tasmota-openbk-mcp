from __future__ import annotations

import os
from pathlib import Path

import pytest

from local_home_devices_mcp.artifacts import ArtifactError, ArtifactStore

pytestmark = pytest.mark.unit


def _store(tmp_path: Path) -> ArtifactStore:
    return ArtifactStore(
        tmp_path / "artifacts",
        max_artifact_bytes=100,
        max_store_bytes=200,
        retention_seconds=3600,
    )


def test_store_assigns_server_side_id_and_secure_mode(tmp_path: Path):
    store = _store(tmp_path)
    artifact = store.save(
        b"jpeg",
        "image/jpeg",
        owner_subject="alice",
        operation="snapshot",
    )
    assert artifact.artifact_id.startswith("art_")
    data_path = store.root / f"{artifact.artifact_id}.bin"
    assert data_path.parent == store.root
    assert artifact.sha256
    assert os.stat(data_path).st_mode & 0o777 == 0o600


def test_store_rejects_traversal_identifier(tmp_path: Path):
    store = _store(tmp_path)
    with pytest.raises(ArtifactError):
        store.read("../../etc/passwd", requester_subject="alice")


def test_store_rejects_large_payload(tmp_path: Path):
    store = _store(tmp_path)
    with pytest.raises(ArtifactError, match="exceeds"):
        store.save(
            b"x" * 101,
            "text/plain",
            owner_subject="alice",
            operation="test",
        )


def test_read_is_owner_bound(tmp_path: Path):
    store = _store(tmp_path)
    artifact = store.save(
        b"secret",
        "application/octet-stream",
        owner_subject="alice",
        operation="capture",
    )
    with pytest.raises(ArtifactError, match="owned"):
        store.read(artifact.artifact_id, requester_subject="bob")
    metadata, content = store.read(artifact.artifact_id, requester_subject="alice")
    assert metadata.artifact_id == artifact.artifact_id
    assert content == b"secret"


def test_store_rejects_symlink_root_component(tmp_path: Path) -> None:
    real = tmp_path / "real-artifacts"
    real.mkdir()
    linked = tmp_path / "linked-artifacts"
    linked.symlink_to(real, target_is_directory=True)
    with pytest.raises(ArtifactError, match="symlink component"):
        ArtifactStore(
            linked,
            max_artifact_bytes=100,
            max_store_bytes=200,
            retention_seconds=3600,
        )


def test_store_readiness_reports_accessible_root(tmp_path: Path) -> None:
    assert _store(tmp_path).readiness()["status"] == "ready"
