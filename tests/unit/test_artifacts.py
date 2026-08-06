from __future__ import annotations

import os

import pytest

from local_home_devices_mcp.artifacts import ArtifactError, ArtifactStore

pytestmark = pytest.mark.unit


def test_store_assigns_server_side_id_and_secure_mode(tmp_path):
    store = ArtifactStore(tmp_path / "artifacts", max_bytes=100)
    artifact = store.save_bytes(b"jpeg", media_type="image/jpeg", suffix=".jpg")
    assert artifact.artifact_id.startswith("art_")
    assert artifact.path.parent == store.root
    assert artifact.sha256
    assert os.stat(artifact.path).st_mode & 0o777 == 0o600


def test_store_rejects_traversal_suffix(tmp_path):
    store = ArtifactStore(tmp_path / "artifacts", max_bytes=100)
    with pytest.raises(ArtifactError):
        store.save_bytes(b"x", media_type="text/plain", suffix="/../../x")


def test_store_rejects_large_payload(tmp_path):
    store = ArtifactStore(tmp_path / "artifacts", max_bytes=3)
    with pytest.raises(ArtifactError, match="exceeds"):
        store.save_bytes(b"four", media_type="text/plain", suffix=".txt")


def test_open_accepts_only_artifact_id(tmp_path):
    store = ArtifactStore(tmp_path / "artifacts", max_bytes=100)
    with pytest.raises(ArtifactError):
        store.open("../../etc/passwd")


def test_open_rejects_glob_metacharacters(tmp_path):
    store = ArtifactStore(tmp_path / "artifacts", max_bytes=100)
    with pytest.raises(ArtifactError):
        store.open("art_*________________")
