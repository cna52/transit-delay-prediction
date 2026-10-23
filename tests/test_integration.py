from datetime import UTC, datetime

from google.transit import gtfs_realtime_pb2

from tests.helpers import write_static_fixture
from transit_delay.features.builder import FeatureBuilder
from transit_delay.gtfs.realtime import parse_feed
from transit_delay.gtfs.static import StaticCatalog
from transit_delay.pipeline import SnapshotProcessor


def realtime_payload() -> bytes:
    feed = gtfs_realtime_pb2.FeedMessage()
    feed.header.gtfs_realtime_version = "2.0"
    feed.header.incrementality = gtfs_realtime_pb2.FeedHeader.FULL_DATASET
    feed.header.timestamp = int(datetime(2026, 8, 11, 7, 2, tzinfo=UTC).timestamp())
    entity = feed.entity.add()
    entity.id = "entity-1"
    update = entity.trip_update
    update.trip.trip_id = "trip-1"
    update.trip.route_id = "r99"
    update.trip.start_date = "20260810"
    update.trip.schedule_relationship = gtfs_realtime_pb2.TripDescriptor.SCHEDULED
    update.timestamp = feed.header.timestamp
    update.delay = 120
    update.vehicle.id = "vehicle-1"
    stop = update.stop_time_update.add()
    stop.stop_sequence = 2
    stop.stop_id = "s2"
    stop.arrival.delay = 120
    return feed.SerializeToString()


def test_parse_join_and_build_future_example(tmp_path) -> None:
    static_path = tmp_path / "static.zip"
    write_static_fixture(static_path)
    feed = parse_feed(realtime_payload())
    assert feed.feed_version is None  # installed v1 bindings predate optional feed_version
    assert feed.trips[0].trip_delay_seconds == 120
    processor = SnapshotProcessor(StaticCatalog.from_zip(static_path), {"099"}, FeatureBuilder())
    rows, counts = processor.process(feed, datetime(2026, 8, 11, 7, 2, tzinfo=UTC))
    assert counts["joined"] == 1
    assert len(rows) == 1
    assert rows[0].target_stop_id == "s3"
    assert rows[0].target_stop_name == "Broadway at Cambie Street"
    assert rows[0].trip_headsign == "UBC"
    assert rows[0].horizon_seconds == 900


def test_join_quality_counts_only_selected_routes_and_schedule_resolution(tmp_path) -> None:
    static_path = tmp_path / "static.zip"
    write_static_fixture(static_path)
    message = gtfs_realtime_pb2.FeedMessage()
    message.ParseFromString(realtime_payload())
    message.entity[0].trip_update.trip.trip_id = "unknown-trip"
    feed = parse_feed(message.SerializeToString())
    processor = SnapshotProcessor(StaticCatalog.from_zip(static_path), {"099"}, FeatureBuilder())

    rows, counts = processor.process(feed, datetime(2026, 8, 11, 7, 2, tzinfo=UTC))

    assert rows == []
    assert counts["selected"] == 1
    assert counts["joined"] == 0
    assert counts["join_failures"] == 1
