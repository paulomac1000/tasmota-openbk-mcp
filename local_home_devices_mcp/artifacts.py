"""Confined artifact storage with opaque IDs, metadata, retention, and quotas."""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import secrets
import time
from collections.abc import Iterator
from dataclasses import asdict, dataclass
from pathlib import Path
from threading import RLock


class ArtifactError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ArtifactMetadata:
    artifact_id: str
    owner_subject: str
    target_id: str | None
    operation: str
    media_type: str
    size: int
    sha256: str
    created_at: float
    expires_at: float


def _reject_symlink_components(root: Path) -> None:
    absolute = root.absolute()
    current = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current /= part
        if current.is_symlink():
            raise ArtifactError(f"artifact root contains a symlink component: {current}")


class ArtifactStore:
    def __init__(
        self,
        root: Path,
        *,
        max_artifact_bytes: int,
        max_store_bytes: int,
        retention_seconds: int,
    ) -> None:
        _reject_symlink_components(root)
        self.root = root.resolve()
        self.max_artifact_bytes = max_artifact_bytes
        self.max_store_bytes = max_store_bytes
        self.retention_seconds = retention_seconds
        self._lock = RLock()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        with contextlib.suppress(OSError):
            os.chmod(self.root, 0o700)

    def readiness(self) -> dict[str, object]:
        try:
            metadata = self.root.stat()
        except OSError as exc:
            return {"status": "unavailable", "reason": type(exc).__name__}
        if not self.root.is_dir():
            return {"status": "unavailable", "reason": "root-is-not-directory"}
        if not os.access(self.root, os.R_OK | os.W_OK):
            return {"status": "unavailable", "reason": "root-is-not-readable-writable"}
        return {
            "status": "ready",
            "mode": oct(metadata.st_mode & 0o777),
            "root": str(self.root),
        }

    def _paths(self, artifact_id: str) -> tuple[Path, Path]:
        if not artifact_id.startswith("art_") or not artifact_id[4:].isalnum():
            raise ArtifactError("invalid artifact id")
        data = (self.root / f"{artifact_id}.bin").resolve()
        meta = (self.root / f"{artifact_id}.json").resolve()
        if not data.is_relative_to(self.root) or not meta.is_relative_to(self.root):
            raise ArtifactError("artifact escaped configured root")
        return data, meta

    def _current_size(self) -> int:
        return sum(path.stat().st_size for path in self.root.glob("art_*.bin") if path.is_file())

    def cleanup(self, now: float | None = None) -> int:
        now = time.time() if now is None else now
        removed = 0
        with self._lock:
            for meta_path in self.root.glob("art_*.json"):
                try:
                    payload = json.loads(meta_path.read_text(encoding="utf-8"))
                    if float(payload["expires_at"]) > now:
                        continue
                    data_path, expected_meta = self._paths(str(payload["artifact_id"]))
                    if expected_meta != meta_path.resolve():
                        continue
                    data_path.unlink(missing_ok=True)
                    meta_path.unlink(missing_ok=True)
                    removed += 1
                except (OSError, ValueError, KeyError, json.JSONDecodeError):
                    continue
        return removed

    def save(
        self,
        content: bytes,
        media_type: str,
        *,
        owner_subject: str,
        operation: str,
        target_id: str | None = None,
    ) -> ArtifactMetadata:
        if not isinstance(content, bytes):
            raise ArtifactError("artifact content must be bytes")
        if not content:
            raise ArtifactError("artifact content must not be empty")
        if len(content) > self.max_artifact_bytes:
            raise ArtifactError("artifact exceeds per-item limit")
        if not media_type or len(media_type) > 128:
            raise ArtifactError("invalid media type")
        if not owner_subject or len(owner_subject) > 256:
            raise ArtifactError("invalid artifact owner")
        if not operation or len(operation) > 128:
            raise ArtifactError("invalid artifact operation")
        now = time.time()
        with self._lock:
            self.cleanup(now)
            if self._current_size() + len(content) > self.max_store_bytes:
                raise ArtifactError("artifact store quota exceeded")
            artifact_id = f"art_{secrets.token_hex(16)}"
            data_path, meta_path = self._paths(artifact_id)
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
            if hasattr(os, "O_NOFOLLOW"):
                flags |= os.O_NOFOLLOW
            fd = os.open(data_path, flags, 0o600)
            try:
                with os.fdopen(fd, "wb", closefd=True) as handle:
                    handle.write(content)
                    handle.flush()
                    os.fsync(handle.fileno())
            except Exception:
                data_path.unlink(missing_ok=True)
                raise
            metadata = ArtifactMetadata(
                artifact_id=artifact_id,
                owner_subject=owner_subject,
                target_id=target_id,
                operation=operation,
                media_type=media_type,
                size=len(content),
                sha256=hashlib.sha256(content).hexdigest(),
                created_at=now,
                expires_at=now + self.retention_seconds,
            )
            meta_path.write_text(json.dumps(asdict(metadata), sort_keys=True), encoding="utf-8")
            with contextlib.suppress(OSError):
                os.chmod(meta_path, 0o600)
            return metadata

    def metadata(self, artifact_id: str) -> ArtifactMetadata:
        data_path, meta_path = self._paths(artifact_id)
        try:
            payload = json.loads(meta_path.read_text(encoding="utf-8"))
            metadata = ArtifactMetadata(**payload)
        except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ArtifactError("artifact not found") from exc
        if metadata.expires_at <= time.time():
            data_path.unlink(missing_ok=True)
            meta_path.unlink(missing_ok=True)
            raise ArtifactError("artifact expired")
        return metadata

    def read(
        self,
        artifact_id: str,
        *,
        requester_subject: str,
        allow_admin: bool = False,
    ) -> tuple[ArtifactMetadata, bytes]:
        metadata = self.metadata(artifact_id)
        if not allow_admin and metadata.owner_subject != requester_subject:
            raise ArtifactError("artifact is not owned by this principal")
        data_path, _ = self._paths(artifact_id)
        try:
            content = data_path.read_bytes()
        except OSError as exc:
            raise ArtifactError("artifact not found") from exc
        if len(content) != metadata.size or hashlib.sha256(content).hexdigest() != metadata.sha256:
            raise ArtifactError("artifact integrity check failed")
        return metadata, content

    def iter_metadata(self) -> Iterator[ArtifactMetadata]:
        self.cleanup()
        for path in sorted(self.root.glob("art_*.json")):
            artifact_id = path.stem
            try:
                yield self.metadata(artifact_id)
            except ArtifactError:
                continue
