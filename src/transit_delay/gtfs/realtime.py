from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any


@dataclass(frozen=True)
class RealtimeStopUpdate:
    stop_sequence: int | None
    stop_id: str | None
    arrival_time: datetime | None
    arrival_delay_seconds: int | None
    departure_time: datetime | None
    departure_delay_seconds: int | None
    relationship: str


@dataclass(frozen=True)
class RealtimeTripUpdate:
    entity_id: str
    trip_id: str | None
    route_id: str | None
    direction_id: int | None
    start_date: str | None
    start_time: str | None
    relationship: str
    vehicle_id: str | None
    source_timestamp: datetime | None
    trip_delay_seconds: int | None
    stops: tuple[RealtimeStopUpdate, ...]


@dataclass(frozen=True)
class RealtimePosition:
    entity_id: str
    trip_id: str | None
    route_id: str | None
    start_date: str | None
    vehicle_id: str | None
    source_timestamp: datetime | None
    latitude: float | None
    longitude: float | None
    speed_mps: float | None
    current_stop_sequence: int | None
    stop_id: str | None
    status: str


@dataclass(frozen=True)
class ParsedFeed:
    feed_timestamp: datetime
    feed_version: str | None
    trips: tuple[RealtimeTripUpdate, ...]
    positions: tuple[RealtimePosition, ...]


def _timestamp(value: int) -> datetime | None:
    return datetime.fromtimestamp(value, UTC) if value else None


def _has(message: Any, field: str) -> bool:
    """Check presence while tolerating bindings older than the latest GTFS schema."""
    descriptor = message.DESCRIPTOR
    if field not in descriptor.fields_by_name:
        return False
    return bool(message.HasField(field))


def parse_feed(payload: bytes) -> ParsedFeed:
    try:
        from google.transit import gtfs_realtime_pb2
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("gtfs-realtime-bindings is required to parse live feeds") from exc
    message = gtfs_realtime_pb2.FeedMessage()
    message.ParseFromString(payload)
    trips: list[RealtimeTripUpdate] = []
    positions: list[RealtimePosition] = []
    for entity in message.entity:
        if entity.HasField("trip_update"):
            update = entity.trip_update
            descriptor = update.trip
            stop_updates: list[RealtimeStopUpdate] = []
            for stop in update.stop_time_update:
                stop_updates.append(
                    RealtimeStopUpdate(
                        stop.stop_sequence if stop.HasField("stop_sequence") else None,
                        stop.stop_id if stop.HasField("stop_id") else None,
                        _timestamp(stop.arrival.time) if stop.HasField("arrival") else None,
                        stop.arrival.delay
                        if stop.HasField("arrival") and stop.arrival.HasField("delay")
                        else None,
                        _timestamp(stop.departure.time) if stop.HasField("departure") else None,
                        stop.departure.delay
                        if stop.HasField("departure") and stop.departure.HasField("delay")
                        else None,
                        gtfs_realtime_pb2.TripUpdate.StopTimeUpdate.ScheduleRelationship.Name(
                            stop.schedule_relationship
                        ),
                    )
                )
            trips.append(
                RealtimeTripUpdate(
                    entity.id,
                    descriptor.trip_id if descriptor.HasField("trip_id") else None,
                    descriptor.route_id if descriptor.HasField("route_id") else None,
                    descriptor.direction_id if descriptor.HasField("direction_id") else None,
                    descriptor.start_date if descriptor.HasField("start_date") else None,
                    descriptor.start_time if descriptor.HasField("start_time") else None,
                    gtfs_realtime_pb2.TripDescriptor.ScheduleRelationship.Name(
                        descriptor.schedule_relationship
                    ),
                    update.vehicle.id
                    if update.HasField("vehicle") and update.vehicle.HasField("id")
                    else None,
                    _timestamp(update.timestamp),
                    update.delay if update.HasField("delay") else None,
                    tuple(stop_updates),
                )
            )
        if entity.HasField("vehicle"):
            vehicle = entity.vehicle
            descriptor = vehicle.trip
            position = vehicle.position
            positions.append(
                RealtimePosition(
                    entity.id,
                    descriptor.trip_id if descriptor.HasField("trip_id") else None,
                    descriptor.route_id if descriptor.HasField("route_id") else None,
                    descriptor.start_date if descriptor.HasField("start_date") else None,
                    vehicle.vehicle.id
                    if vehicle.HasField("vehicle") and vehicle.vehicle.HasField("id")
                    else None,
                    _timestamp(vehicle.timestamp),
                    position.latitude if vehicle.HasField("position") else None,
                    position.longitude if vehicle.HasField("position") else None,
                    position.speed
                    if vehicle.HasField("position") and position.HasField("speed")
                    else None,
                    vehicle.current_stop_sequence
                    if vehicle.HasField("current_stop_sequence")
                    else None,
                    vehicle.stop_id if vehicle.HasField("stop_id") else None,
                    gtfs_realtime_pb2.VehiclePosition.VehicleStopStatus.Name(
                        vehicle.current_status
                    ),
                )
            )
    feed_ts = datetime.fromtimestamp(message.header.timestamp, UTC)
    feed_version = message.header.feed_version if _has(message.header, "feed_version") else None
    return ParsedFeed(feed_ts, feed_version, tuple(trips), tuple(positions))
