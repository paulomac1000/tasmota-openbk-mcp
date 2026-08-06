"""Confined artifact storage for snapshots and downloaded device files."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
import secrets
from dataclasses import dataclass
from typing import BinaryIO


class ArtifactError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class Artifact:
    artifact_id: str
    path: Path
    media_type: str
    size_bytes: int
    sha256: str


class ArtifactStore:
    """Write-only-by-ID store that never accepts caller-provided paths."""

    def __init__(self, root: Path, max_bytes: int) -> None:
        self.root = root.resolve()
        self.max_bytes = max_bytes
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            os.chmod(self.root, 0o700)
        except OSError:
            pass

    def save_bytes(self, data: bytes, *, media_type: str, suffix: str) -> Artifact:
        if len(data) > self.max_bytes:
            raise ArtifactError(f"artifact exceeds {self.max_bytes} byte limit")
        if not suffix.startswith(".") or "/" in suffix or "\\" in suffix or len(suffix) > 12:
            raise ArtifactError("invalid artifact suffix")
        artifact_id = f"art_{secrets.token_urlsafe(18)}"
        final_path = self.root / f"{artifact_id}{suffix}"
        if final_path.parent != self.root:
            raise ArtifactError("artifact path escaped root")
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        fd = os.open(final_path, flags, 0o600)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
        except BaseException:
            final_path.unlink(missing_ok=True)
            raise
        digest = hashlib.sha256(data).hexdigest()
        return Artifact(artifact_id, final_path, media_type, len(data), digest)

    def open(self, artifact_id: str) -> BinaryIO:
        if not re.fullmatch(r"art_[A-Za-z0-9_-]{16,64}", artifact_id):
            raise ArtifactError("invalid artifact id")
        matches = list(self.root.glob(f"{artifact_id}.*"))
        if len(matches) != 1:
            raise ArtifactError("artifact not found or ambiguous")
        resolved = matches[0].resolve(strict=True)
        if resolved.parent != self.root:
            raise ArtifactError("artifact escaped root")
        return resolved.open("rb")
