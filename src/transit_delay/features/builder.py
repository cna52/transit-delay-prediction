from __future__ import annotations

import hashlib
from collections import defaultdict
from datetime import datetime
from zoneinfo import ZoneInfo

from transit_delay.domain import FeatureRow, TripObservation


class FeatureBuilder:
    def __init__(
        self,
        horizon_min_seconds: int = 600,
        horizon_max_seconds: int = 900,
        cooldown_seconds: int = 300,
        timezone_name: str = "America/Vancouver",
    ):
        self.horizon_min_seconds = horizon_min_seconds
        self.horizon_max_seconds = horizon_max_seconds
        self.cooldown_seconds = cooldown_seconds
        self.timezone = ZoneInfo(timezone_name)
        self._history: dict[str, list[tuple[datetime, int]]] = defaultdict(list)
        self._last_example: dict[str, datetime] = {}

    def build(self, observation: TripObservation) -> FeatureRow | None:
        if observation.source_timestamp > observation.observed_at:
            raise ValueError("source timestamp is after as_of; refusing future information")
        source_age = int((observation.observed_at - observation.source_timestamp).total_seconds())
        target = None
        target_horizon = None
        for candidate in sorted(
            observation.target_candidates, key=lambda event: event.stop_sequence
        ):
            if candidate.stop_sequence <= observation.current_stop_sequence:
                continue
            persistence_arrival = (
                candidate.scheduled_arrival.timestamp() + observation.current_delay_seconds
            )
            horizon = int(persistence_arrival - observation.observed_at.timestamp())
            if self.horizon_min_seconds <= horizon <= self.horizon_max_seconds:
                target = candidate
                target_horizon = horizon
                break
        if target is None or target_horizon is None:
            return None
        history = self._history[observation.key.stable_id()]
        prior_delays = [delay for seen_at, delay in history if seen_at <= observation.observed_at]
        trend = observation.current_delay_seconds - prior_delays[-1] if prior_delays else None
        history.append((observation.observed_at, observation.current_delay_seconds))
        last_example = self._last_example.get(observation.key.stable_id())
        if (
            last_example
            and (observation.observed_at - last_example).total_seconds() < self.cooldown_seconds
        ):
            return None
        self._last_example[observation.key.stable_id()] = observation.observed_at
        identity = "|".join(
            (
                observation.key.stable_id(),
                observation.observed_at.isoformat(),
                str(target.stop_sequence),
                "v1",
            )
        )
        example_id = hashlib.sha256(identity.encode()).hexdigest()[:24]
        local_as_of = observation.observed_at.astimezone(self.timezone)
        return FeatureRow(
            example_id=example_id,
            as_of=observation.observed_at,
            key=observation.key,
            target_stop_sequence=target.stop_sequence,
            target_stop_id=target.stop_id,
            scheduled_target_arrival=target.scheduled_arrival,
            horizon_seconds=target_horizon,
            route_short_name=observation.route_short_name,
            direction_id=observation.direction_id,
            current_stop_sequence=observation.current_stop_sequence,
            stops_to_target=target.stop_sequence - observation.current_stop_sequence,
            current_delay_seconds=observation.current_delay_seconds,
            delay_trend_seconds=trend,
            source_age_seconds=source_age,
            hour=local_as_of.hour,
            minute=local_as_of.minute,
            weekday=local_as_of.weekday(),
            target_stop_name=target.stop_name,
            trip_headsign=observation.trip_headsign,
        )
