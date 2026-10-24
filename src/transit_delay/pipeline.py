from __future__ import annotations

import gzip
import json
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol

from transit_delay.domain import FeatureRow, StopEvent, TripObservation
from transit_delay.features.builder import FeatureBuilder
from transit_delay.gtfs.realtime import ParsedFeed, RealtimeTripUpdate, parse_feed
from transit_delay.gtfs.registry import StaticFeedRegistry
from transit_delay.gtfs.static import JoinFailure, StaticCatalog


@dataclass(frozen=True)
class ProcessingStats:
    snapshots: int = 0
    trip_updates: int = 0
    selected_route_updates: int = 0
    joined: int = 0
    examples: int = 0
    parse_failures: int = 0
    join_failures: int = 0
    static_unavailable: int = 0


class FeedProcessor(Protocol):
    def process(
        self, feed: ParsedFeed, received_at: datetime
    ) -> tuple[list[FeatureRow], dict[str, int]]: ...


class SnapshotProcessor:
    def __init__(
        self,
        catalog: StaticCatalog,
        selected_routes: set[str],
        feature_builder: FeatureBuilder,
    ):
        self.catalog = catalog
        self.selected_routes = selected_routes
        self.feature_builder = feature_builder

    def process(
        self, feed: ParsedFeed, received_at: datetime
    ) -> tuple[list[FeatureRow], dict[str, int]]:
        examples: list[FeatureRow] = []
        counts = {"updates": 0, "selected": 0, "joined": 0, "join_failures": 0}
        for update in feed.trips:
            counts["updates"] += 1
            resolved = self.catalog.resolve(update, received_at)
            if isinstance(resolved, JoinFailure):
                route_short_name = self.catalog.route_short_names.get(update.route_id or "")
                if route_short_name not in self.selected_routes:
                    continue
                counts["selected"] += 1
                counts["join_failures"] += 1
                continue
            if resolved.trip.route_short_name not in self.selected_routes:
                continue
            counts["selected"] += 1
            counts["joined"] += 1
            delay = _current_delay(update, resolved.stop_events, received_at)
            if delay is None:
                continue
            current_sequence = _current_sequence(resolved.stop_events, received_at, delay)
            source_timestamp = update.source_timestamp or feed.feed_timestamp
            observation = TripObservation(
                resolved.key,
                resolved.trip.route_id,
                resolved.trip.route_short_name,
                resolved.trip.direction_id,
                received_at,
                source_timestamp,
                current_sequence,
                delay,
                resolved.stop_events,
                vehicle_id=update.vehicle_id,
                trip_headsign=resolved.trip.headsign,
            )
            example = self.feature_builder.build(observation)
            if example:
                examples.append(example)
        return examples, counts


def process_manifest(
    manifest_paths: Iterable[Path], processor: SnapshotProcessor, since: datetime | None = None
) -> tuple[list[FeatureRow], ProcessingStats]:
    return _process_manifest(manifest_paths, lambda _received_at: processor, since)


def process_manifest_with_registry(
    manifest_paths: Iterable[Path],
    registry: StaticFeedRegistry,
    selected_routes: set[str],
    feature_builder: FeatureBuilder,
    since: datetime | None = None,
) -> tuple[list[FeatureRow], ProcessingStats]:
    routed = RegistrySnapshotProcessor(registry, selected_routes, feature_builder)
    return _process_manifest(manifest_paths, lambda _received_at: routed, since)


class RegistrySnapshotProcessor:
    def __init__(
        self,
        registry: StaticFeedRegistry,
        selected_routes: set[str],
        feature_builder: FeatureBuilder,
    ):
        self.registry = registry
        self.selected_routes = selected_routes
        self.feature_builder = feature_builder
        self.processors: dict[str, SnapshotProcessor] = {}

    def process(
        self, feed: ParsedFeed, received_at: datetime
    ) -> tuple[list[FeatureRow], dict[str, int]]:
        examples: list[FeatureRow] = []
        totals = {
            "updates": 0,
            "selected": 0,
            "joined": 0,
            "join_failures": 0,
            "static_unavailable": 0,
        }
        for update in feed.trips:
            service_date = (
                datetime.strptime(update.start_date, "%Y%m%d").date()
                if update.start_date
                else received_at.astimezone(self.feature_builder.timezone).date()
            )
            try:
                record = self.registry.select(service_date, received_at)
            except LookupError:
                totals["updates"] += 1
                totals["static_unavailable"] += 1
                continue
            if record.sha256 not in self.processors:
                self.processors[record.sha256] = SnapshotProcessor(
                    self.registry.catalog(record), self.selected_routes, self.feature_builder
                )
            one_feed = ParsedFeed(feed.feed_timestamp, feed.feed_version, (update,), ())
            new_examples, counts = self.processors[record.sha256].process(one_feed, received_at)
            examples.extend(new_examples)
            for key, value in counts.items():
                totals[key] += value
        return examples, totals


def _process_manifest(
    manifest_paths: Iterable[Path],
    processor_for: Callable[[datetime], FeedProcessor],
    since: datetime | None = None,
) -> tuple[list[FeatureRow], ProcessingStats]:
    rows: list[FeatureRow] = []
    values = asdict(ProcessingStats())
    seen_examples: set[str] = set()
    for manifest_path in sorted(manifest_paths):
        for line in manifest_path.read_text().splitlines():
            record = json.loads(line)
            if record["feed_type"] != "trip_updates" or not record.get("payload_path"):
                continue
            received_at = datetime.fromisoformat(record["received_at"])
            if since is not None and received_at < since:
                continue
            values["snapshots"] += 1
            try:
                with gzip.open(record["payload_path"], "rb") as stream:
                    feed = parse_feed(stream.read())
            except Exception:
                values["parse_failures"] += 1
                continue
            try:
                processor = processor_for(received_at)
            except LookupError:
                values["trip_updates"] += len(feed.trips)
                values["static_unavailable"] += len(feed.trips)
                continue
            examples, counts = processor.process(feed, received_at)
            values["trip_updates"] += counts["updates"]
            values["selected_route_updates"] += counts["selected"]
            values["joined"] += counts["joined"]
            values["join_failures"] += counts["join_failures"]
            values["static_unavailable"] += counts.get("static_unavailable", 0)
            for example in examples:
                if example.example_id not in seen_examples:
                    rows.append(example)
                    seen_examples.add(example.example_id)
                    values["examples"] += 1
    return rows, ProcessingStats(**values)


def _current_delay(
    update: RealtimeTripUpdate, stop_events: tuple[StopEvent, ...], as_of: datetime
) -> int | None:
    if update.trip_delay_seconds is not None:
        return update.trip_delay_seconds
    schedule_by_sequence = {event.stop_sequence: event.scheduled_arrival for event in stop_events}
    candidates: list[tuple[int, int]] = []
    for stop in update.stops:
        if stop.stop_sequence is None:
            continue
        scheduled = schedule_by_sequence.get(stop.stop_sequence)
        if scheduled is None:
            continue
        delay = stop.arrival_delay_seconds
        predicted = stop.arrival_time
        if delay is None and predicted is not None:
            delay = int((predicted - scheduled).total_seconds())
        if delay is not None and scheduled.timestamp() + delay <= as_of.timestamp() + 120:
            candidates.append((stop.stop_sequence, delay))
    return max(candidates)[1] if candidates else None


def _current_sequence(
    stop_events: tuple[StopEvent, ...], as_of: datetime, delay_seconds: int
) -> int:
    passed = [
        event.stop_sequence
        for event in stop_events
        if event.scheduled_arrival.timestamp() + delay_seconds <= as_of.timestamp()
    ]
    return int(max(passed) if passed else min(event.stop_sequence for event in stop_events))
