from __future__ import annotations

import gzip
import json
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

from transit_delay.datasets.labels import Labeler
from transit_delay.domain import FeatureRow, LabelOutcome, TripInstanceKey
from transit_delay.gtfs.realtime import RealtimeTripUpdate, parse_feed


def resolve_archived_labels(
    features: list[FeatureRow],
    manifests: list[Path],
    labeler: Labeler,
    wait_seconds: int = 1800,
) -> list[LabelOutcome]:
    timelines: dict[str, list[tuple[datetime, RealtimeTripUpdate]]] = defaultdict(list)
    for manifest in sorted(manifests):
        for line in manifest.read_text().splitlines():
            record = json.loads(line)
            if record.get("feed_type") != "trip_updates" or not record.get("payload_path"):
                continue
            received_at = datetime.fromisoformat(record["received_at"])
            try:
                with gzip.open(record["payload_path"], "rb") as stream:
                    parsed = parse_feed(stream.read())
            except Exception:
                continue
            for update in parsed.trips:
                if update.trip_id:
                    timelines[update.trip_id].append((received_at, update))
    for values in timelines.values():
        values.sort(key=lambda item: item[0])

    outcomes = []
    for feature in features:
        label_time = labeler.label_time(feature)
        deadline = label_time + timedelta(seconds=wait_seconds)
        outcome = None
        for available_at, update in timelines.get(feature.key.trip_id, []):
            if available_at <= feature.as_of or available_at < label_time:
                continue
            if available_at > deadline:
                break
            if update.start_date and update.start_date != feature.key.service_date.strftime(
                "%Y%m%d"
            ):
                continue
            if feature.key.start_time and update.start_time != feature.key.start_time:
                continue
            candidate = labeler.resolve(feature, update, available_at)
            if candidate.status in {"labelled", "invalid", "audit_required"}:
                outcome = candidate
                break
        outcomes.append(
            outcome or labeler.resolve(feature, None, max(deadline, datetime.now(deadline.tzinfo)))
        )
    return outcomes


def read_features(path: Path) -> list[FeatureRow]:
    rows = []
    for line in path.read_text().splitlines():
        value = json.loads(line)
        version, service_date, trip_id, start_time = str(value["key"]).split("|", 3)
        rows.append(
            FeatureRow(
                example_id=value["example_id"],
                as_of=datetime.fromisoformat(value["as_of"]),
                key=TripInstanceKey(
                    version,
                    datetime.fromisoformat(service_date).date(),
                    trip_id,
                    start_time or None,
                ),
                target_stop_sequence=int(value["target_stop_sequence"]),
                target_stop_id=value["target_stop_id"],
                scheduled_target_arrival=datetime.fromisoformat(value["scheduled_target_arrival"]),
                horizon_seconds=int(value["horizon_seconds"]),
                route_short_name=value["route_short_name"],
                direction_id=value.get("direction_id"),
                current_stop_sequence=int(value["current_stop_sequence"]),
                stops_to_target=int(value["stops_to_target"]),
                current_delay_seconds=int(value["current_delay_seconds"]),
                delay_trend_seconds=value.get("delay_trend_seconds"),
                source_age_seconds=int(value["source_age_seconds"]),
                hour=int(value["hour"]),
                minute=int(value["minute"]),
                weekday=int(value["weekday"]),
                feature_schema_version=value.get("feature_schema_version", "v1"),
                target_stop_name=value.get("target_stop_name"),
                trip_headsign=value.get("trip_headsign"),
            )
        )
    return rows
