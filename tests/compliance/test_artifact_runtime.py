from __future__ import annotations

import os
from pathlib import Path

import pytest

from local_home_devices_mcp.artifacts import ArtifactError, ArtifactStore

pytestmark = pytest.mark.unit


def store(tmp_path: Path, *, retention: int = 3600) -> ArtifactStore:
    return ArtifactStore(
        tmp_path / "artifacts",
        max_artifact_bytes=64,
        max_store_bytes=128,
        retention_seconds=retention,
    )


def test_artifact_roundtrip_is_integrity_checked(tmp_path: Path):
    artifacts = store(tmp_path)
    meta = artifacts.save(
        b"payload",
        "application/octet-stream",
        owner_subject="alice",
        operation="test",
    )
    actual, content = artifacts.read(meta.artifact_id, requester_subject="alice")
    assert content == b"payload"
    assert actual.sha256 == meta.sha256
    assert not str((tmp_path / "artifacts").resolve()) in meta.artifact_id
    if os.name == "posix":
        mode = (tmp_path / "artifacts" / f"{meta.artifact_id}.bin").stat().st_mode
        assert oct(mode & 0o777) == "0o600"


def test_artifact_limits_and_invalid_ids(tmp_path: Path):
    artifacts = store(tmp_path)
    with pytest.raises(ArtifactError, match="per-item"):
        artifacts.save(
            b"x" * 65,
            "application/octet-stream",
            owner_subject="alice",
            operation="test",
        )
    with pytest.raises(ArtifactError, match="invalid artifact id"):
        artifacts.read("../../etc/passwd", requester_subject="alice")


def test_expired_artifact_is_removed(tmp_path: Path):
    artifacts = store(tmp_path, retention=1)
    meta = artifacts.save(
        b"payload",
        "application/octet-stream",
        owner_subject="alice",
        operation="test",
    )
    assert artifacts.cleanup(meta.expires_at + 1) == 1
    with pytest.raises(ArtifactError):
        artifacts.read(meta.artifact_id, requester_subject="alice")


def test_artifact_is_principal_bound(tmp_path: Path):
    artifacts = store(tmp_path)
    meta = artifacts.save(
        b"payload",
        "application/octet-stream",
        owner_subject="alice",
        operation="capture",
    )
    with pytest.raises(ArtifactError, match="owned"):
        artifacts.read(meta.artifact_id, requester_subject="bob")
    metadata, content = artifacts.read(
        meta.artifact_id,
        requester_subject="admin",
        allow_admin=True,
    )
    assert metadata.owner_subject == "alice"
    assert content == b"payload"


def test_artifact_validation_quota_and_integrity_failures(tmp_path: Path):
    artifacts = store(tmp_path)
    invalid = [
        ("not-bytes", "application/octet-stream", "alice", "test"),
        (b"", "application/octet-stream", "alice", "test"),
        (b"x", "", "alice", "test"),
        (b"x", "application/octet-stream", "", "test"),
        (b"x", "application/octet-stream", "alice", ""),
    ]
    for content, media_type, owner, operation in invalid:
        with pytest.raises(ArtifactError):
            artifacts.save(  # type: ignore[arg-type]
                content,
                media_type,
                owner_subject=owner,
                operation=operation,
            )

    first = artifacts.save(
        b"a" * 64,
        "application/octet-stream",
        owner_subject="alice",
        operation="test",
    )
    artifacts.save(
        b"b" * 64,
        "application/octet-stream",
        owner_subject="alice",
        operation="test",
    )
    with pytest.raises(ArtifactError, match="quota"):
        artifacts.save(
            b"c",
            "application/octet-stream",
            owner_subject="alice",
            operation="test",
        )

    data_path = tmp_path / "artifacts" / f"{first.artifact_id}.bin"
    data_path.write_bytes(b"tampered")
    with pytest.raises(ArtifactError, match="integrity"):
        artifacts.read(first.artifact_id, requester_subject="alice")


def test_artifact_metadata_iteration_and_corrupt_metadata(tmp_path: Path):
    artifacts = store(tmp_path)
    saved = artifacts.save(
        b"payload",
        "text/plain",
        owner_subject="alice",
        operation="export",
        target_id="dev_123",
    )
    assert [item.artifact_id for item in artifacts.iter_metadata()] == [saved.artifact_id]

    metadata_path = tmp_path / "artifacts" / f"{saved.artifact_id}.json"
    metadata_path.write_text("not json", encoding="utf-8")
    with pytest.raises(ArtifactError, match="not found"):
        artifacts.metadata(saved.artifact_id)
    assert list(artifacts.iter_metadata()) == []
