from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from transit_delay.domain import FeatureRow
from transit_delay.gtfs.realtime import ParsedFeed


@dataclass(frozen=True)
class FeedAudit:
    snapshots: int
    trip_updates: int
    vehicle_positions: int
    trip_field_presence: dict[str, float]
    stop_field_presence: dict[str, float]
    position_field_presence: dict[str, float]
    freshness_seconds: dict[str, float | None]
    relationships: dict[str, int]
    label_semantics: dict[str, object] | None = None


def audit_feeds(
    feeds: Iterable[tuple[ParsedFeed, datetime]],
    features: Iterable[FeatureRow] | None = None,
) -> FeedAudit:
    feed_list = list(feeds)
    trips = [trip for feed, _ in feed_list for trip in feed.trips]
    stops = [stop for trip in trips for stop in trip.stops]
    positions = [position for feed, _ in feed_list for position in feed.positions]
    trip_fields: dict[str, Callable[[Any], object]] = {
        "trip_id": lambda value: value.trip_id,
        "route_id": lambda value: value.route_id,
        "start_date": lambda value: value.start_date,
        "start_time": lambda value: value.start_time,
        "vehicle_id": lambda value: value.vehicle_id,
        "timestamp": lambda value: value.source_timestamp,
        "trip_delay": lambda value: value.trip_delay_seconds,
    }
    stop_fields: dict[str, Callable[[Any], object]] = {
        "stop_sequence": lambda value: value.stop_sequence,
        "stop_id": lambda value: value.stop_id,
        "arrival_time": lambda value: value.arrival_time,
        "arrival_delay": lambda value: value.arrival_delay_seconds,
        "departure_time": lambda value: value.departure_time,
        "departure_delay": lambda value: value.departure_delay_seconds,
    }
    position_fields: dict[str, Callable[[Any], object]] = {
        "trip_id": lambda value: value.trip_id,
        "vehicle_id": lambda value: value.vehicle_id,
        "timestamp": lambda value: value.source_timestamp,
        "latitude": lambda value: value.latitude,
        "speed": lambda value: value.speed_mps,
        "current_stop_sequence": lambda value: value.current_stop_sequence,
        "stop_id": lambda value: value.stop_id,
    }
    freshness = sorted(
        max(0.0, (received_at - feed.feed_timestamp).total_seconds())
        for feed, received_at in feed_list
    )
    return FeedAudit(
        len(feed_list),
        len(trips),
        len(positions),
        _presence(trips, trip_fields),
        _presence(stops, stop_fields),
        _presence(positions, position_fields),
        {
            "median": _quantile(freshness, 0.5),
            "p95": _quantile(freshness, 0.95),
            "max": max(freshness) if freshness else None,
        },
        dict(Counter(trip.relationship for trip in trips)),
        _label_semantics(feed_list, list(features or [])),
    )


def _label_semantics(
    feeds: list[tuple[ParsedFeed, datetime]], features: list[FeatureRow]
) -> dict[str, object] | None:
    if not features:
        return None
    timelines: dict[str, list[tuple[datetime, Any]]] = {}
    positions: dict[str, list[tuple[datetime, Any]]] = {}
    for feed, received_at in feeds:
        for update in feed.trips:
            if update.trip_id:
                timelines.setdefault(update.trip_id, []).append((received_at, update))
        for position in feed.positions:
            if position.trip_id:
                positions.setdefault(position.trip_id, []).append((received_at, position))
    for timeline_values in (*timelines.values(), *positions.values()):
        timeline_values.sort(key=lambda item: item[0])
    candidates = post_passage = retained = revised = position_confirmed = 0
    routes: dict[str, Counter[str]] = {}
    sampled_trip_ids: set[str] = set()
    for feature in features:
        sampled_trip_ids.add(feature.key.trip_id)
        target_values: list[tuple[datetime, datetime | None, int | None]] = []
        for received_at, update in timelines.get(feature.key.trip_id, []):
            if received_at < feature.scheduled_target_arrival:
                continue
            for stop in update.stops:
                if stop.stop_sequence == feature.target_stop_sequence or (
                    stop.stop_sequence is None and stop.stop_id == feature.target_stop_id
                ):
                    target_values.append(
                        (received_at, stop.arrival_time, stop.arrival_delay_seconds)
                    )
                    break
        route_counts = routes.setdefault(feature.route_short_name, Counter())
        route_counts["examples"] += 1
        if not target_values:
            continue
        candidates += 1
        route_counts["candidates"] += 1
        past_values = [
            value for value in target_values if value[1] and value[1] <= value[0]
        ]
        if past_values:
            post_passage += 1
            route_counts["post_passage"] += 1
        if len(past_values) >= 2:
            retained += 1
        delay_values = {value[2] for value in target_values if value[2] is not None}
        if len(delay_values) > 1:
            revised += 1
        if any(
            position.current_stop_sequence is not None
            and position.current_stop_sequence >= feature.target_stop_sequence
            and received_at >= feature.scheduled_target_arrival
            for received_at, position in positions.get(feature.key.trip_id, [])
        ):
            position_confirmed += 1
    total = len(features)
    return {
        "examples_checked": total,
        "trip_timelines": len(sampled_trip_ids),
        "candidate_labels": candidates,
        "candidate_coverage": candidates / total if total else 0.0,
        "post_passage_candidates": post_passage,
        "post_passage_retained_twice": retained,
        "revised_target_predictions": revised,
        "vehicle_position_confirmed": position_confirmed,
        "by_route": {
            route: {
                **dict(counts),
                "candidate_coverage": counts["candidates"] / counts["examples"],
            }
            for route, counts in routes.items()
        },
        "measured_arrival_automatically_approved": False,
        "decision": "manual_review_required",
    }


def _presence(values: list[Any], fields: dict[str, Callable[[Any], object]]) -> dict[str, float]:
    if not values:
        return {name: 0.0 for name in fields}
    return {
        name: sum(getter(value) is not None for value in values) / len(values)
        for name, getter in fields.items()
    }


def _quantile(values: list[float], quantile: float) -> float | None:
    if not values:
        return None
    return values[round((len(values) - 1) * quantile)]
