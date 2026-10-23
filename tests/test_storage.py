import gzip
from datetime import UTC, datetime

from transit_delay.ingestion.archive import ImmutableArchive
from transit_delay.ingestion.quota import DailyQuota


def test_archive_deduplicates_payload_but_records_every_fetch(tmp_path) -> None:
    archive = ImmutableArchive(tmp_path)
    now = datetime(2026, 8, 10, tzinfo=UTC)
    first = archive.store("trip_updates", b"abc", now, now, 200, 1)
    second = archive.store("trip_updates", b"abc", now, now, 200, 1)
    assert first.payload_path == second.payload_path
    with gzip.open(first.payload_path, "rb") as stream:
        assert stream.read() == b"abc"
    manifest = tmp_path / "raw/manifests/2026-08-10.jsonl"
    assert len(manifest.read_text().splitlines()) == 2


def test_quota_rolls_over_and_rejects_exhaustion(tmp_path) -> None:
    quota = DailyQuota(tmp_path / "quota.json", 1, "America/Vancouver")
    now = datetime(2026, 8, 10, 12, tzinfo=UTC)
    assert quota.consume(now).used == 1
    try:
        quota.consume(now)
    except RuntimeError:
        pass
    else:
        raise AssertionError("quota should be exhausted")
    assert quota.snapshot(datetime(2026, 8, 11, 12, tzinfo=UTC)).used == 0
