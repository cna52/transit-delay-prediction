from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime
from typing import Any


@dataclass(frozen=True)
class TripInstanceKey:
    static_version: str
    service_date: date
    trip_id: str
    start_time: str | None = None

    def stable_id(self) -> str:
        return "|".join(
            (
                self.static_version,
                self.service_date.isoformat(),
                self.trip_id,
                self.start_time or "",
            )
        )


@dataclass(frozen=True)
class StopEvent:
    stop_sequence: int
    stop_id: str
    scheduled_arrival: datetime
    arrival_time: datetime | None = None
    arrival_delay_seconds: int | None = None
    relationship: str = "SCHEDULED"
    stop_name: str | None = None


@dataclass(frozen=True)
class TripObservation:
    key: TripInstanceKey
    route_id: str
    route_short_name: str
    direction_id: int | None
    observed_at: datetime
    source_timestamp: datetime
    current_stop_sequence: int
    current_delay_seconds: int
    target_candidates: tuple[StopEvent, ...]
    vehicle_id: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    speed_mps: float | None = None
    trip_headsign: str | None = None


@dataclass(frozen=True)
class FeatureRow:
    example_id: str
    as_of: datetime
    key: TripInstanceKey
    target_stop_sequence: int
    target_stop_id: str
    scheduled_target_arrival: datetime
    horizon_seconds: int
    route_short_name: str
    direction_id: int | None
    current_stop_sequence: int
    stops_to_target: int
    current_delay_seconds: int
    delay_trend_seconds: int | None
    source_age_seconds: int
    hour: int
    minute: int
    weekday: int
    feature_schema_version: str = "v1"
    target_stop_name: str | None = None
    trip_headsign: str | None = None

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["key"] = self.key.stable_id()
        return value


@dataclass(frozen=True)
class LabelOutcome:
    example_id: str
    status: str
    label_minutes: float | None
    event_time: datetime | None
    available_at: datetime
    source: str | None = None
    reason: str | None = None


@dataclass(frozen=True)
class PredictionResult:
    prediction_minutes: float | None
    lower_minutes: float | None
    upper_minutes: float | None
    model_version: str
    feature_schema_version: str
    quality: str
    observation_timestamp: datetime | None
    freshness_seconds: int | None
    fallback_reason: str | None = None
