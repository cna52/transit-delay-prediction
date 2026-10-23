from datetime import UTC, datetime, timedelta

from transit_delay.models.baselines import HistoricalMedianBaseline, PersistenceBaseline
from transit_delay.models.evaluation import (
    chronological_split,
    empirical_interval_report,
    metrics,
    promotion_decision,
)


def row(day, route="099", delay=120):
    observed = datetime(2026, 1, 1, 12, tzinfo=UTC) + timedelta(days=day)
    return {
        "key": f"v|{observed.date()}|trip-{day}|",
        "as_of": observed.isoformat(),
        "route_short_name": route,
        "direction_id": 0,
        "target_stop_id": "s",
        "hour": 12,
        "minute": 0,
        "current_delay_seconds": delay,
    }


def test_baselines() -> None:
    rows = [row(0), row(1)]
    assert PersistenceBaseline().predict(rows) == [2.0, 2.0]
    model = HistoricalMedianBaseline().fit(rows, [1.0, 3.0])
    assert model.predict_one(row(2)) == 2.0


def test_chronological_split_and_metrics() -> None:
    rows = [row(day) for day in range(20)]
    train, validation, test = chronological_split(rows, 3, 3)
    assert max(train) < min(validation) < min(test)
    result = metrics([1, 2], [2, 2])
    assert result.mae == 0.5
    assert result.bias == 0.5


def test_split_keeps_midnight_trip_in_its_service_day() -> None:
    rows = [row(day) for day in range(20)]
    crossing = dict(row(12))
    crossing["as_of"] = (datetime.fromisoformat(crossing["as_of"]) + timedelta(days=1)).isoformat()
    rows.append(crossing)
    train, validation, test = chronological_split(rows, 3, 3, purge_minutes=0)
    partitions = [set(train), set(validation), set(test)]
    assert any({12, 20} <= partition for partition in partitions)


def test_promotion_requires_trip_clustered_improvement() -> None:
    rows = [row(day) for day in range(20)]
    actual = [0.0] * len(rows)
    persistence = [2.0] * len(rows)
    candidate = [0.5] * len(rows)
    decision = promotion_decision(rows, actual, candidate, persistence, bootstrap_samples=200)
    assert decision.approved
    assert decision.confidence_interval_95[1] < 0


def test_interval_uses_validation_residuals_and_reports_test_coverage() -> None:
    report = empirical_interval_report(
        [float(x) for x in range(20)], [0.0] * 20, [1.0, 30.0], [0.0, 0.0]
    )
    assert report == {"q05": 0.0, "q95": 18.0, "test_coverage": 0.5}
