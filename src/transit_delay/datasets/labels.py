from __future__ import annotations

from datetime import datetime, timedelta

from transit_delay.datasets.policy import LabelPolicy
from transit_delay.domain import FeatureRow, LabelOutcome
from transit_delay.gtfs.realtime import RealtimeTripUpdate


class Labeler:
    """Resolve a label after the target event without silently calling forecasts actuals."""

    def __init__(self, policy: LabelPolicy | bool | None = None):
        # Boolean support keeps the original unit-level API compatible. Production
        # commands require a checksummed LabelPolicy file.
        self.policy = policy if isinstance(policy, LabelPolicy) else None
        self.audited_past_updates_are_measured = bool(policy) if isinstance(policy, bool) else False

    @property
    def target_type(self) -> str:
        if self.policy is not None:
            return self.policy.target_type
        return "measured_arrival" if self.audited_past_updates_are_measured else "audit_required"

    def label_time(self, example: FeatureRow) -> datetime:
        if self.target_type == "reported_delay_state_fixed_lag":
            if self.policy is None or self.policy.label_lag_seconds is None:
                raise ValueError("fixed-lag label requires an approved policy")
            return example.as_of + timedelta(seconds=self.policy.label_lag_seconds)
        if self.target_type == "reported_delay_state":
            return example.as_of + timedelta(seconds=example.horizon_seconds)
        return example.scheduled_target_arrival

    def resolve(
        self,
        example: FeatureRow,
        later_update: RealtimeTripUpdate | None,
        available_at: datetime,
    ) -> LabelOutcome:
        if available_at <= example.as_of:
            raise ValueError("labels must be resolved strictly after example as_of")
        if later_update is None:
            return LabelOutcome(
                example.example_id, "censored", None, None, available_at, reason="missing_update"
            )
        if later_update.relationship == "CANCELED":
            return LabelOutcome(
                example.example_id, "invalid", None, None, available_at, reason="cancelled"
            )
        matching = [
            update
            for update in later_update.stops
            if update.stop_sequence == example.target_stop_sequence
            or (
                update.stop_sequence is None
                and update.stop_id is not None
                and update.stop_id == example.target_stop_id
            )
        ]
        if len(matching) != 1:
            return LabelOutcome(
                example.example_id,
                "censored",
                None,
                None,
                available_at,
                reason="target_stop_missing_or_ambiguous",
            )
        stop = matching[0]
        if stop.relationship == "SKIPPED":
            return LabelOutcome(
                example.example_id, "invalid", None, None, available_at, reason="skipped"
            )
        if self.target_type == "audit_required":
            return LabelOutcome(
                example.example_id,
                "audit_required",
                None,
                stop.arrival_time,
                available_at,
                source="past_stop_update_candidate",
                reason="producer_semantics_not_verified",
            )
        event_time = stop.arrival_time
        if event_time is None and stop.arrival_delay_seconds is not None:
            delay_seconds = stop.arrival_delay_seconds
            event_time = example.scheduled_target_arrival + timedelta(seconds=delay_seconds)
        elif event_time is not None:
            delay_seconds = int((event_time - example.scheduled_target_arrival).total_seconds())
        else:
            return LabelOutcome(
                example.example_id, "censored", None, None, available_at, reason="no_arrival_value"
            )
        if self.target_type == "measured_arrival" and event_time > available_at:
            return LabelOutcome(
                example.example_id,
                "censored",
                None,
                event_time,
                available_at,
                reason="arrival_still_in_future",
            )
        source = (
            "reported_target_stop_delay_state"
            if self.target_type in {"reported_delay_state", "reported_delay_state_fixed_lag"}
            else "audited_past_stop_update"
        )
        return LabelOutcome(
            example.example_id,
            "labelled",
            delay_seconds / 60.0,
            event_time,
            available_at,
            source=source,
        )
