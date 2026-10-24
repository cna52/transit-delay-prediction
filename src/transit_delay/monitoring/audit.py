from __future__ import annotations

import gzip
import json
from collections import Counter
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from transit_delay.domain import FeatureRow
from transit_delay.gtfs.realtime import ParsedFeed, parse_feed


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
    feature_list = list(features or [])
    relevant_days: dict[str, set[str]] = {}
    for feature in feature_list:
        relevant_days.setdefault(feature.key.trip_id, set()).add(
            feature.key.service_date.strftime("%Y%m%d")
        )
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
    snapshots = trips = stops = positions = 0
    freshness: list[float] = []
    trip_presence: Counter[str] = Counter()
    stop_presence: Counter[str] = Counter()
    position_presence: Counter[str] = Counter()
    relationships: Counter[str] = Counter()
    timelines: dict[str, list[tuple[datetime, Any]]] = {}
    position_timelines: dict[str, list[tuple[datetime, Any]]] = {}
    latest_trip_at: datetime | None = None
    for feed, received_at in feeds:
        snapshots += 1
        freshness.append(max(0.0, (received_at - feed.feed_timestamp).total_seconds()))
        if feed.trips and (latest_trip_at is None or received_at > latest_trip_at):
            latest_trip_at = received_at
        for trip in feed.trips:
            trips += 1
            relationships[trip.relationship] += 1
            trip_presence.update(
                name for name, getter in trip_fields.items() if getter(trip) is not None
            )
            for stop in trip.stops:
                stops += 1
                stop_presence.update(
                    name for name, getter in stop_fields.items() if getter(stop) is not None
                )
            if trip.trip_id in relevant_days and (
                not trip.start_date or trip.start_date in relevant_days[trip.trip_id]
            ):
                timelines.setdefault(trip.trip_id, []).append((received_at, trip))
        for position in feed.positions:
            positions += 1
            position_presence.update(
                name for name, getter in position_fields.items() if getter(position) is not None
            )
            if position.trip_id in relevant_days and (
                not position.start_date or position.start_date in relevant_days[position.trip_id]
            ):
                position_timelines.setdefault(position.trip_id, []).append((received_at, position))
    freshness.sort()
    return FeedAudit(
        snapshots,
        trips,
        positions,
        _presence_rates(trip_presence, trips, trip_fields),
        _presence_rates(stop_presence, stops, stop_fields),
        _presence_rates(position_presence, positions, position_fields),
        {
            "median": _quantile(freshness, 0.5),
            "p95": _quantile(freshness, 0.95),
            "max": max(freshness) if freshness else None,
        },
        dict(relationships),
        _label_semantics(timelines, position_timelines, latest_trip_at, feature_list),
    )


def _label_semantics(
    timelines: dict[str, list[tuple[datetime, Any]]],
    positions: dict[str, list[tuple[datetime, Any]]],
    latest_received_at: datetime | None,
    features: list[FeatureRow],
) -> dict[str, object] | None:
    if not features:
        return None
    for timeline_values in (*timelines.values(), *positions.values()):
        timeline_values.sort(key=lambda item: item[0])
    candidates = post_passage = retained = revised = position_confirmed = joint_confirmed = 0
    pending = 0
    routes: dict[str, Counter[str]] = {}
    sampled_trip_ids: set[str] = set()
    for feature in features:
        sampled_trip_ids.add(feature.key.trip_id)
        label_time = feature.as_of + timedelta(seconds=feature.horizon_seconds)
        deadline = label_time + timedelta(minutes=30)
        if latest_received_at is None or latest_received_at < deadline:
            pending += 1
            continue
        target_values: list[tuple[datetime, datetime | None, int | None]] = []
        for received_at, update in timelines.get(feature.key.trip_id, []):
            if update.start_date and update.start_date != feature.key.service_date.strftime(
                "%Y%m%d"
            ):
                continue
            if feature.key.start_time and update.start_time != feature.key.start_time:
                continue
            if not (label_time <= received_at <= deadline):
                continue
            for stop in update.stops:
                if stop.stop_sequence == feature.target_stop_sequence or (
                    stop.stop_sequence is None and stop.stop_id == feature.target_stop_id
                ):
                    if stop.arrival_time is not None or stop.arrival_delay_seconds is not None:
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
        past_values = [value for value in target_values if value[1] and value[1] <= value[0]]
        if past_values:
            post_passage += 1
            route_counts["post_passage"] += 1
        if len(past_values) >= 2:
            retained += 1
        delay_values = {value[2] for value in target_values if value[2] is not None}
        if len(delay_values) > 1:
            revised += 1
        position_passed = any(
            (
                not position.start_date
                or position.start_date == feature.key.service_date.strftime("%Y%m%d")
            )
            and position.current_stop_sequence is not None
            and position.current_stop_sequence >= feature.target_stop_sequence
            and feature.scheduled_target_arrival <= received_at <= deadline
            for received_at, position in positions.get(feature.key.trip_id, [])
        )
        if position_passed:
            position_confirmed += 1
        if len(past_values) >= 2 and position_passed:
            joint_confirmed += 1
    total = len(features) - pending
    return {
        "examples_checked": total,
        "pending_examples": pending,
        "trip_timelines": len(sampled_trip_ids),
        "candidate_labels": candidates,
        "candidate_coverage": candidates / total if total else 0.0,
        "post_passage_candidates": post_passage,
        "post_passage_retained_twice": retained,
        "revised_target_predictions": revised,
        "vehicle_position_confirmed": position_confirmed,
        "retained_and_position_confirmed": joint_confirmed,
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


def trip_timeline_samples(
    feeds: Iterable[tuple[ParsedFeed, datetime]],
    features: Iterable[FeatureRow],
    limit: int = 10,
) -> list[dict[str, object]]:
    """Retain route/day-balanced trip evidence for the required human review."""
    if limit < 1:
        raise ValueError("timeline sample limit must be positive")
    groups: dict[tuple[str, str], list[FeatureRow]] = {}
    seen: set[str] = set()
    for row in sorted(features, key=lambda value: value.as_of):
        key = row.key.stable_id()
        if key in seen:
            continue
        seen.add(key)
        groups.setdefault((row.key.service_date.isoformat(), row.route_short_name), []).append(row)
    chosen: list[FeatureRow] = []
    while len(chosen) < limit and any(groups.values()):
        for group in sorted(groups):
            if groups[group] and len(chosen) < limit:
                chosen.append(groups[group].pop(0))

    relevant_days: dict[str, set[str]] = {}
    for row in chosen:
        relevant_days.setdefault(row.key.trip_id, set()).add(
            row.key.service_date.strftime("%Y%m%d")
        )
    updates: dict[str, list[tuple[datetime, Any]]] = {}
    positions: dict[str, list[tuple[datetime, Any]]] = {}
    for feed, received_at in feeds:
        for update in feed.trips:
            if (
                update.trip_id
                and update.trip_id in relevant_days
                and (not update.start_date or update.start_date in relevant_days[update.trip_id])
            ):
                updates.setdefault(update.trip_id, []).append((received_at, update))
        for position in feed.positions:
            if (
                position.trip_id
                and position.trip_id in relevant_days
                and (
                    not position.start_date
                    or position.start_date in relevant_days[position.trip_id]
                )
            ):
                positions.setdefault(position.trip_id, []).append((received_at, position))

    samples: list[dict[str, object]] = []
    for row in chosen:
        service_date = row.key.service_date.strftime("%Y%m%d")
        label_time = row.as_of + timedelta(seconds=row.horizon_seconds)
        deadline = label_time + timedelta(minutes=30)
        trip_updates = [
            (received_at, update)
            for received_at, update in updates.get(row.key.trip_id, [])
            if (not update.start_date or update.start_date == service_date)
            and (not row.key.start_time or update.start_time == row.key.start_time)
            and row.as_of <= received_at <= deadline
        ]
        position_updates = [
            (received_at, position)
            for received_at, position in positions.get(row.key.trip_id, [])
            if (not position.start_date or position.start_date == service_date)
            and row.as_of <= received_at <= deadline
        ]
        target_history = []
        for received_at, update in trip_updates:
            for stop in update.stops:
                if stop.stop_sequence == row.target_stop_sequence or (
                    stop.stop_sequence is None and stop.stop_id == row.target_stop_id
                ):
                    target_history.append(
                        {
                            "received_at": received_at.isoformat(),
                            "arrival_time": stop.arrival_time.isoformat()
                            if stop.arrival_time
                            else None,
                            "arrival_delay_seconds": stop.arrival_delay_seconds,
                            "relationship": stop.relationship,
                            "within_candidate_window": label_time <= received_at <= deadline,
                            "post_passage": bool(
                                stop.arrival_time and stop.arrival_time <= received_at
                            ),
                        }
                    )
                    break
        samples.append(
            {
                "trip_key": row.key.stable_id(),
                "example_id": row.example_id,
                "route": row.route_short_name,
                "as_of": row.as_of.isoformat(),
                "feature_source_age_seconds": row.source_age_seconds,
                "scheduled_target_arrival": row.scheduled_target_arrival.isoformat(),
                "label_time": label_time.isoformat(),
                "candidate_deadline": deadline.isoformat(),
                "trip_update_count": len(trip_updates),
                "vehicle_position_count": len(position_updates),
                "cancelled_updates": sum(
                    update.relationship == "CANCELED" for _, update in trip_updates
                ),
                "position_passed_target": any(
                    position.current_stop_sequence is not None
                    and position.current_stop_sequence >= row.target_stop_sequence
                    for _, position in position_updates
                ),
                "position_history": [
                    {
                        "received_at": received_at.isoformat(),
                        "current_stop_sequence": position.current_stop_sequence,
                        "stop_id": position.stop_id,
                        "status": position.status,
                    }
                    for received_at, position in position_updates
                ],
                "target_history": target_history,
                "review_status": "pending",
                "review_notes": "",
            }
        )
    return samples


def archived_feeds(manifests: Iterable[Path]) -> Iterator[tuple[ParsedFeed, datetime]]:
    """Parse one archived snapshot at a time to bound audit memory use."""
    for manifest in sorted(manifests):
        for line in manifest.read_text().splitlines():
            record = json.loads(line)
            if not record.get("payload_path"):
                continue
            try:
                with gzip.open(record["payload_path"], "rb") as stream:
                    feed = parse_feed(stream.read())
                yield feed, datetime.fromisoformat(record["received_at"])
            except Exception:
                continue


def _presence_rates(
    counts: Counter[str], total: int, fields: dict[str, Callable[[Any], object]]
) -> dict[str, float]:
    return {name: counts[name] / total if total else 0.0 for name in fields}


def _quantile(values: list[float], quantile: float) -> float | None:
    if not values:
        return None
    return values[round((len(values) - 1) * quantile)]
