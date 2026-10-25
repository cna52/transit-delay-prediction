from datetime import UTC, date, datetime, timedelta

import pytest

from transit_delay.datasets.labels import Labeler
from transit_delay.datasets.policy import LabelPolicy
from transit_delay.domain import StopEvent, TripInstanceKey, TripObservation
from transit_delay.features.builder import FeatureBuilder
from transit_delay.gtfs.realtime import RealtimeStopUpdate, RealtimeTripUpdate

NOW = datetime(2026, 8, 10, 18, 0, tzinfo=UTC)


def observation(source_at=NOW, delay=120):
    key = TripInstanceKey("v1", date(2026, 8, 10), "trip")
    stops = tuple(
        StopEvent(index, f"s{index}", NOW + timedelta(minutes=minutes))
        for index, minutes in [(1, -5), (2, 2), (3, 9), (4, 11), (5, 20)]
    )
    return TripObservation(key, "r", "099", 0, NOW, source_at, 1, delay, stops)


def test_target_is_chosen_using_persistence_horizon() -> None:
    row = FeatureBuilder().build(observation())
    assert row is not None
    assert row.target_stop_id == "s3"  # scheduled + 2m delay = 11m ahead
    assert row.horizon_seconds == 660
    assert row.hour == 11  # Feature time is America/Vancouver, not UTC.


def test_correlated_examples_are_cooled_down() -> None:
    builder = FeatureBuilder(cooldown_seconds=300)
    assert builder.build(observation()) is not None
    later = observation()
    later = TripObservation(
        later.key,
        later.route_id,
        later.route_short_name,
        later.direction_id,
        NOW + timedelta(minutes=2),
        NOW + timedelta(minutes=2),
        later.current_stop_sequence,
        later.current_delay_seconds,
        later.target_candidates,
    )
    assert builder.build(later) is None


def test_future_timestamp_is_rejected() -> None:
    with pytest.raises(ValueError, match="future information"):
        FeatureBuilder().build(observation(NOW + timedelta(seconds=1)))


def test_label_requires_explicit_feed_audit() -> None:
    row = FeatureBuilder().build(observation())
    assert row is not None
    event_time = row.scheduled_target_arrival + timedelta(minutes=4)
    update = RealtimeTripUpdate(
        "e",
        "trip",
        "r",
        0,
        "20260810",
        None,
        "SCHEDULED",
        None,
        event_time,
        None,
        (
            RealtimeStopUpdate(
                row.target_stop_sequence,
                row.target_stop_id,
                event_time,
                240,
                None,
                None,
                "SCHEDULED",
            ),
        ),
    )
    outcome = Labeler(False).resolve(row, update, event_time + timedelta(minutes=1))
    assert outcome.status == "audit_required"
    labelled = Labeler(True).resolve(row, update, event_time + timedelta(minutes=1))
    assert labelled.status == "labelled"
    assert labelled.label_minutes == 4


def test_reported_delay_state_policy_can_label_a_future_target_estimate() -> None:
    row = FeatureBuilder().build(observation())
    assert row is not None
    policy = LabelPolicy(
        "label-reported-v1",
        "reported_delay_state",
        "audit-hash",
        NOW.isoformat(),
    )
    available_at = row.as_of + timedelta(seconds=row.horizon_seconds)
    predicted_arrival = row.scheduled_target_arrival + timedelta(minutes=5)
    update = RealtimeTripUpdate(
        "e",
        "trip",
        "r",
        0,
        "20260810",
        None,
        "SCHEDULED",
        None,
        available_at,
        None,
        (
            RealtimeStopUpdate(
                row.target_stop_sequence,
                row.target_stop_id,
                predicted_arrival,
                300,
                None,
                None,
                "SCHEDULED",
            ),
        ),
    )
    outcome = Labeler(policy).resolve(row, update, available_at)
    assert outcome.status == "labelled"
    assert outcome.label_minutes == 5
    assert outcome.source == "reported_target_stop_delay_state"


def test_fixed_lag_policy_labels_a_reported_future_state() -> None:
    row = FeatureBuilder().build(observation())
    assert row is not None
    policy = LabelPolicy(
        "label-fixed-lag-v1",
        "reported_delay_state_fixed_lag",
        "audit-hash",
        NOW.isoformat(),
        label_lag_seconds=300,
        candidate_window_seconds=480,
        routes=("R5",),
        scope_report_sha256="scope-hash",
    )
    labeler = Labeler(policy)
    assert labeler.label_time(row) == row.as_of + timedelta(minutes=5)
    available_at = row.as_of + timedelta(minutes=8)
    forecast_arrival = row.scheduled_target_arrival + timedelta(minutes=3)
    update = RealtimeTripUpdate(
        "e",
        row.key.trip_id,
        "r",
        0,
        "20260810",
        None,
        "SCHEDULED",
        None,
        available_at,
        None,
        (
            RealtimeStopUpdate(
                row.target_stop_sequence,
                row.target_stop_id,
                forecast_arrival,
                180,
                None,
                None,
                "SCHEDULED",
            ),
        ),
    )
    outcome = labeler.resolve(row, update, available_at)
    assert outcome.status == "labelled"
    assert outcome.label_minutes == 3
    assert outcome.source == "reported_target_stop_delay_state"
