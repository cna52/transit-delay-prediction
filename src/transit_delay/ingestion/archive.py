from __future__ import annotations

import gzip
import hashlib
import json
import os
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path


@dataclass(frozen=True)
class FetchRecord:
    fetch_id: str
    feed_type: str
    requested_at: str
    received_at: str
    status_code: int | None
    payload_sha256: str | None
    payload_path: str | None
    payload_bytes: int
    elapsed_ms: int
    error: str | None = None
    feed_timestamp: int | None = None


class ImmutableArchive:
    def __init__(self, root: Path):
        self.root = root

    def store(
        self,
        feed_type: str,
        payload: bytes,
        requested_at: datetime,
        received_at: datetime,
        status_code: int,
        elapsed_ms: int,
        feed_timestamp: int | None = None,
    ) -> FetchRecord:
        digest = hashlib.sha256(payload).hexdigest()
        day = received_at.astimezone(UTC).strftime("%Y-%m-%d")
        payload_dir = self.root / "raw" / feed_type / day / "payloads"
        payload_dir.mkdir(parents=True, exist_ok=True)
        payload_path = payload_dir / f"{digest}.pb.gz"
        if not payload_path.exists():
            temporary = payload_path.with_suffix(f".tmp-{uuid.uuid4().hex}")
            with (
                temporary.open("wb") as raw,
                gzip.GzipFile(fileobj=raw, mode="wb", compresslevel=6, mtime=0) as stream,
            ):
                stream.write(payload)
            os.replace(temporary, payload_path)
        record = FetchRecord(
            fetch_id=uuid.uuid4().hex,
            feed_type=feed_type,
            requested_at=requested_at.isoformat(),
            received_at=received_at.isoformat(),
            status_code=status_code,
            payload_sha256=digest,
            payload_path=str(payload_path),
            payload_bytes=len(payload),
            elapsed_ms=elapsed_ms,
            feed_timestamp=feed_timestamp,
        )
        self._append_manifest(day, record)
        return record

    def store_failure(
        self,
        feed_type: str,
        requested_at: datetime,
        received_at: datetime,
        elapsed_ms: int,
        error: str,
        status_code: int | None = None,
    ) -> FetchRecord:
        record = FetchRecord(
            fetch_id=uuid.uuid4().hex,
            feed_type=feed_type,
            requested_at=requested_at.isoformat(),
            received_at=received_at.isoformat(),
            status_code=status_code,
            payload_sha256=None,
            payload_path=None,
            payload_bytes=0,
            elapsed_ms=elapsed_ms,
            error=error,
        )
        day = received_at.astimezone(UTC).strftime("%Y-%m-%d")
        self._append_manifest(day, record)
        return record

    def _append_manifest(self, day: str, record: FetchRecord) -> None:
        manifest = self.root / "raw" / "manifests" / f"{day}.jsonl"
        manifest.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(asdict(record), sort_keys=True) + "\n"
        descriptor = os.open(manifest, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
        try:
            os.write(descriptor, line.encode())
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
