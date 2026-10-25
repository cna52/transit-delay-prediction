from __future__ import annotations

import gzip
import json
from bisect import bisect_left, bisect_right
from collections import Counter
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

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
    label_lag_seconds: int | None = None,
    candidate_window_seconds: int = 1800,
    timezone_name: str = "America/Vancouver",
) -> FeedAudit:
    if label_lag_seconds is not None and label_lag_seconds <= 0:
        raise ValueError("label lag must be positive")
    if candidate_window_seconds <= 0:
        raise ValueError("candidate window must be positive")
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
    trip_poll_times: list[datetime] = []
    for feed, received_at in feeds:
        snapshots += 1
        freshness.append(max(0.0, (received_at - feed.feed_timestamp).total_seconds()))
        if feed.trips and (latest_trip_at is None or received_at > latest_trip_at):
            latest_trip_at = received_at
        if feed.trips:
            trip_poll_times.append(received_at)
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
        _label_semantics(
            timelines,
            position_timelines,
            latest_trip_at,
            trip_poll_times,
            feature_list,
            label_lag_seconds,
            candidate_window_seconds,
            timezone_name,
        ),
    )


def _label_semantics(
    timelines: dict[str, list[tuple[datetime, Any]]],
    positions: dict[str, list[tuple[datetime, Any]]],
    latest_received_at: datetime | None,
    trip_poll_times: list[datetime],
    features: list[FeatureRow],
    label_lag_seconds: int | None,
    candidate_window_seconds: int,
    timezone_name: str,
) -> dict[str, object] | None:
    if not features:
        return None
    for timeline_values in (*timelines.values(), *positions.values()):
        timeline_values.sort(key=lambda item: item[0])
    trip_poll_times.sort()
    candidates = post_passage = retained = revised = position_confirmed = joint_confirmed = 0
    pending = 0
    routes: dict[str, Counter[str]] = {}
    service_dates: dict[str, Counter[str]] = {}
    missing_reasons: Counter[str] = Counter()
    missing_with_prior_target = 0
    no_trip_update_poll_context: Counter[str] = Counter()
    candidate_lags: list[float] = []
    local_dates: dict[str, Counter[str]] = {}
    routes_by_local_date: dict[str, dict[str, Counter[str]]] = {}
    timezone = ZoneInfo(timezone_name)
    sampled_trip_ids: set[str] = set()
    for feature in features:
        sampled_trip_ids.add(feature.key.trip_id)
        label_time = feature.as_of + timedelta(
            seconds=feature.horizon_seconds if label_lag_seconds is None else label_lag_seconds
        )
        deadline = label_time + timedelta(seconds=candidate_window_seconds)
        local_day = feature.as_of.astimezone(timezone).date().isoformat()
        group_counts = (
            routes.setdefault(feature.route_short_name, Counter()),
            service_dates.setdefault(feature.key.service_date.isoformat(), Counter()),
            local_dates.setdefault(local_day, Counter()),
            routes_by_local_date.setdefault(local_day, {}).setdefault(
                feature.route_short_name, Counter()
            ),
        )
        if latest_received_at is None or latest_received_at < deadline:
            pending += 1
            for counts in group_counts:
                counts["pending"] += 1
            continue
        target_values: list[tuple[datetime, datetime | None, int | None]] = []
        saw_trip_update = False
        saw_target_stop = False
        prior_target_value = False
        for received_at, update in timelines.get(feature.key.trip_id, []):
            if update.start_date and update.start_date != feature.key.service_date.strftime(
                "%Y%m%d"
            ):
                continue
            if feature.key.start_time and update.start_time != feature.key.start_time:
                continue
            if not (feature.as_of <= received_at <= deadline):
                continue
            in_window = received_at >= label_time
            if in_window:
                saw_trip_update = True
            for stop in update.stops:
                if stop.stop_sequence == feature.target_stop_sequence or (
                    stop.stop_sequence is None and stop.stop_id == feature.target_stop_id
                ):
                    has_value = (
                        stop.arrival_time is not None or stop.arrival_delay_seconds is not None
                    )
                    if in_window:
                        saw_target_stop = True
                    elif has_value:
                        prior_target_value = True
                    if in_window and has_value:
                        target_values.append(
                            (received_at, stop.arrival_time, stop.arrival_delay_seconds)
                        )
                    break
        for counts in group_counts:
            counts["examples"] += 1
        if not target_values:
            reason = (
                "no_trip_update_in_window"
                if not saw_trip_update
                else "target_stop_absent_in_window"
                if not saw_target_stop
                else "target_value_absent_in_window"
            )
            missing_reasons[reason] += 1
            for counts in group_counts:
                counts[reason] += 1
            if reason == "no_trip_update_in_window":
                polls = bisect_right(trip_poll_times, deadline) - bisect_left(
                    trip_poll_times, label_time
                )
                poll_context = "feed_poll_gap" if polls == 0 else "feed_polled_trip_absent"
                no_trip_update_poll_context[poll_context] += 1
                for counts in group_counts:
                    counts[poll_context] += 1
            if prior_target_value:
                missing_with_prior_target += 1
                for counts in group_counts:
                    counts["missing_with_prior_target"] += 1
            continue
        candidates += 1
        candidate_lags.append(
            (min(value[0] for value in target_values) - feature.as_of).total_seconds()
        )
        for counts in group_counts:
            counts["candidates"] += 1
        past_values = [value for value in target_values if value[1] and value[1] <= value[0]]
        if past_values:
            post_passage += 1
            for counts in group_counts:
                counts["post_passage"] += 1
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
    candidate_lags.sort()
    return {
        "examples_checked": total,
        "pending_examples": pending,
        "trip_timelines": len(sampled_trip_ids),
        "candidate_labels": candidates,
        "candidate_coverage": candidates / total if total else 0.0,
        "candidate_observation_lag_seconds": {
            "minimum": min(candidate_lags) if candidate_lags else None,
            "p50": _quantile(candidate_lags, 0.5),
            "p95": _quantile(candidate_lags, 0.95),
            "maximum": max(candidate_lags) if candidate_lags else None,
        },
        "label_lag_seconds": label_lag_seconds,
        "candidate_window_seconds": candidate_window_seconds,
        "missing_candidate_reasons": dict(missing_reasons),
        "missing_with_prior_target_value": missing_with_prior_target,
        "no_trip_update_poll_context": dict(no_trip_update_poll_context),
        "post_passage_candidates": post_passage,
        "post_passage_retained_twice": retained,
        "revised_target_predictions": revised,
        "vehicle_position_confirmed": position_confirmed,
        "retained_and_position_confirmed": joint_confirmed,
        "by_route": {
            route: {
                **dict(counts),
                "candidate_coverage": counts["candidates"] / counts["examples"]
                if counts["examples"]
                else 0.0,
            }
            for route, counts in routes.items()
        },
        "by_service_date": {
            day: {
                **dict(counts),
                "candidate_coverage": counts["candidates"] / counts["examples"]
                if counts["examples"]
                else 0.0,
            }
            for day, counts in service_dates.items()
        },
        "by_local_date": {
            day: {
                **dict(counts),
                "candidate_coverage": counts["candidates"] / counts["examples"]
                if counts["examples"]
                else 0.0,
            }
            for day, counts in local_dates.items()
        },
        "by_route_local_date": {
            day: {route: dict(counts) for route, counts in route_counts.items()}
            for day, route_counts in routes_by_local_date.items()
        },
        "measured_arrival_automatically_approved": False,
        "decision": "manual_review_required",
    }


def trip_timeline_samples(
    feeds: Iterable[tuple[ParsedFeed, datetime]],
    features: Iterable[FeatureRow],
    limit: int = 10,
    service_dates: set[str] | None = None,
    local_dates: set[str] | None = None,
    timezone_name: str = "America/Vancouver",
    label_lag_seconds: int | None = None,
    candidate_window_seconds: int = 1800,
) -> list[dict[str, object]]:
    """Retain route/day-balanced trip evidence for the required human review."""
    if limit < 1:
        raise ValueError("timeline sample limit must be positive")
    if label_lag_seconds is not None and label_lag_seconds <= 0:
        raise ValueError("label lag must be positive")
    if candidate_window_seconds <= 0:
        raise ValueError("candidate window must be positive")
    groups: dict[tuple[str, str], list[FeatureRow]] = {}
    seen: set[str] = set()
    timezone = ZoneInfo(timezone_name)
    for row in sorted(features, key=lambda value: value.as_of):
        if service_dates is not None and row.key.service_date.isoformat() not in service_dates:
            continue
        local_day = row.as_of.astimezone(timezone).date().isoformat()
        if local_dates is not None and local_day not in local_dates:
            continue
        key = row.key.stable_id()
        if key in seen:
            continue
        seen.add(key)
        groups.setdefault((local_day, row.route_short_name), []).append(row)
    if groups:
        quota = max(1, (limit + len(groups) - 1) // len(groups))
        for group, rows in groups.items():
            selected_indices = {
                min(len(rows) - 1, (2 * index + 1) * len(rows) // (2 * quota))
                for index in range(min(quota, len(rows)))
            }
            spread = [rows[index] for index in sorted(selected_indices)]
            groups[group] = spread + [
                row for index, row in enumerate(rows) if index not in selected_indices
            ]
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
        label_time = row.as_of + timedelta(
            seconds=row.horizon_seconds if label_lag_seconds is None else label_lag_seconds
        )
        deadline = label_time + timedelta(seconds=candidate_window_seconds)
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
                "local_date": row.as_of.astimezone(timezone).date().isoformat(),
                "as_of": row.as_of.isoformat(),
                "feature_source_age_seconds": row.source_age_seconds,
                "scheduled_target_arrival": row.scheduled_target_arrival.isoformat(),
                "label_time": label_time.isoformat(),
                "candidate_deadline": deadline.isoformat(),
                "label_lag_seconds": label_lag_seconds,
                "candidate_window_seconds": candidate_window_seconds,
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
