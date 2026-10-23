from datetime import UTC, date, datetime

from tests.helpers import write_static_fixture
from transit_delay.gtfs.realtime import RealtimeTripUpdate
from transit_delay.gtfs.static import ResolvedTrip, StaticCatalog
from transit_delay.gtfs.time import parse_gtfs_time


def update(**changes):
    values = dict(
        entity_id="e1",
        trip_id="trip-1",
        route_id="r99",
        direction_id=0,
        start_date="20260810",
        start_time=None,
        relationship="SCHEDULED",
        vehicle_id="vehicle-1",
        source_timestamp=datetime(2026, 8, 11, 7, 0, tzinfo=UTC),
        trip_delay_seconds=120,
        stops=(),
    )
    values.update(changes)
    return RealtimeTripUpdate(**values)


def test_gtfs_time_over_24_hours() -> None:
    parsed = parse_gtfs_time(date(2026, 8, 10), "24:15:00", "America/Vancouver")
    assert parsed == datetime(2026, 8, 11, 7, 15, tzinfo=UTC)


def test_versioned_static_join(tmp_path) -> None:
    path = tmp_path / "static.zip"
    write_static_fixture(path)
    catalog = StaticCatalog.from_zip(path)
    result = catalog.resolve(update(), datetime(2026, 8, 11, 7, 0, tzinfo=UTC))
    assert isinstance(result, ResolvedTrip)
    assert result.key.static_version == "fixture-v1"
    assert result.trip.route_short_name == "099"
    assert result.stop_events[-1].scheduled_arrival.hour == 7


def test_rejects_cancelled_trip(tmp_path) -> None:
    path = tmp_path / "static.zip"
    write_static_fixture(path)
    result = StaticCatalog.from_zip(path).resolve(
        update(relationship="CANCELED"), datetime(2026, 8, 11, 7, 0, tzinfo=UTC)
    )
    assert result.reason.startswith("unsupported_relationship")
