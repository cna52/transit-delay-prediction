from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from pathlib import Path

from transit_delay.gtfs.static import StaticCatalog


@dataclass(frozen=True)
class StaticFeedRecord:
    version: str
    sha256: str
    retrieved_at: str
    feed_start_date: str
    feed_end_date: str
    archive_path: str


class StaticFeedRegistry:
    def __init__(self, path: Path, timezone: str = "America/Vancouver"):
        self.path = path
        self.timezone = timezone
        self._catalogs: dict[str, StaticCatalog] = {}

    def records(self) -> list[StaticFeedRecord]:
        if not self.path.exists():
            return []
        value = json.loads(self.path.read_text())
        return [StaticFeedRecord(**item) for item in value.get("feeds", [])]

    def register(self, archive: Path, retrieved_at: datetime | None = None) -> StaticFeedRecord:
        catalog = StaticCatalog.from_zip(archive, self.timezone)
        if catalog.profile is None:  # pragma: no cover - guarded by catalog loader
            raise RuntimeError("static feed has no profile")
        record = StaticFeedRecord(
            catalog.version,
            catalog.profile.sha256,
            (retrieved_at or datetime.now(UTC)).isoformat(),
            catalog.profile.feed_start_date,
            catalog.profile.feed_end_date,
            str(archive),
        )
        by_hash = {item.sha256: item for item in self.records()}
        existing = by_hash.get(record.sha256)
        if existing is not None and existing.retrieved_at <= record.retrieved_at:
            record = existing
        by_hash[record.sha256] = record
        ordered = sorted(by_hash.values(), key=lambda item: item.retrieved_at)
        payload = {"feeds": [asdict(item) for item in ordered]}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, indent=2, sort_keys=True))
        temporary.replace(self.path)
        return record

    def select(self, service_date: date, as_of: datetime) -> StaticFeedRecord:
        candidates = []
        for record in self.records():
            start = datetime.strptime(record.feed_start_date, "%Y%m%d").date()
            end = datetime.strptime(record.feed_end_date, "%Y%m%d").date()
            retrieved = datetime.fromisoformat(record.retrieved_at)
            if start <= service_date <= end and retrieved <= as_of:
                candidates.append(record)
        if not candidates:
            raise LookupError(f"no point-in-time static feed covers {service_date}")
        return max(candidates, key=lambda item: item.retrieved_at)

    def catalog(self, record: StaticFeedRecord) -> StaticCatalog:
        if record.sha256 not in self._catalogs:
            self._catalogs[record.sha256] = StaticCatalog.from_zip(
                Path(record.archive_path), self.timezone
            )
        return self._catalogs[record.sha256]
