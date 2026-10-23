from __future__ import annotations

import math
import random
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import datetime
from statistics import mean, median


@dataclass(frozen=True)
class MetricSet:
    count: int
    mae: float
    median_absolute_error: float
    p90_absolute_error: float
    bias: float


@dataclass(frozen=True)
class EvaluationReport:
    model_name: str
    overall: MetricSet
    slices: dict[str, dict[str, MetricSet]]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class PromotionDecision:
    approved: bool
    candidate_trip_weighted_mae: float
    persistence_trip_weighted_mae: float
    mae_difference: float
    confidence_interval_95: tuple[float, float]
    route_regressions: dict[str, float]
    reasons: tuple[str, ...]


def empirical_interval_report(
    validation_actual: Sequence[float],
    validation_predicted: Sequence[float],
    test_actual: Sequence[float],
    test_predicted: Sequence[float],
) -> dict[str, float]:
    if (
        not validation_actual
        or not test_actual
        or (
            len(validation_actual) != len(validation_predicted)
            or len(test_actual) != len(test_predicted)
        )
    ):
        raise ValueError("interval report requires paired validation and test predictions")
    residuals = sorted(
        truth - prediction
        for truth, prediction in zip(validation_actual, validation_predicted, strict=True)
    )
    q05 = residuals[max(0, int(0.05 * (len(residuals) - 1)))]
    q95 = residuals[min(len(residuals) - 1, int(0.95 * (len(residuals) - 1)))]
    coverage = sum(
        prediction + q05 <= truth <= prediction + q95
        for truth, prediction in zip(test_actual, test_predicted, strict=True)
    ) / len(test_actual)
    return {"q05": q05, "q95": q95, "test_coverage": coverage}


def metrics(actual: Sequence[float], predicted: Sequence[float]) -> MetricSet:
    if len(actual) != len(predicted) or not actual:
        raise ValueError("metrics require equal, non-empty arrays")
    errors = [prediction - truth for truth, prediction in zip(actual, predicted, strict=True)]
    absolute = sorted(abs(error) for error in errors)
    p90_index = max(0, math.ceil(0.9 * len(absolute)) - 1)
    return MetricSet(
        len(errors),
        mean(absolute),
        median(absolute),
        absolute[p90_index],
        mean(errors),
    )


def evaluate(
    model_name: str,
    rows: list[Mapping[str, object]],
    actual: list[float],
    predicted: list[float],
) -> EvaluationReport:
    def horizon(row: Mapping[str, object]) -> str:
        seconds = int(str(row["horizon_seconds"]))
        return "10-12m" if seconds <= 720 else "12-15m"

    def freshness(row: Mapping[str, object]) -> str:
        age = int(str(row["source_age_seconds"]))
        if age <= 90:
            return "<=90s"
        if age <= 180:
            return "91-180s"
        if age <= 300:
            return "181-300s"
        return ">300s"

    def time_of_day(row: Mapping[str, object]) -> str:
        hour = int(str(row["hour"]))
        if 6 <= hour < 10:
            return "morning_peak"
        if 10 <= hour < 15:
            return "midday"
        if 15 <= hour < 19:
            return "afternoon_peak"
        return "evening_night"

    dimensions: dict[str, Callable[[Mapping[str, object]], str]] = {
        "route": lambda row: str(row["route_short_name"]),
        "horizon": horizon,
        "time_of_day": time_of_day,
        "freshness": freshness,
    }
    sliced: dict[str, dict[str, MetricSet]] = {}
    for dimension, key_fn in dimensions.items():
        groups: dict[str, list[int]] = {}
        for index, row in enumerate(rows):
            groups.setdefault(key_fn(row), []).append(index)
        sliced[dimension] = {
            key: metrics([actual[i] for i in indexes], [predicted[i] for i in indexes])
            for key, indexes in groups.items()
        }
    return EvaluationReport(model_name, metrics(actual, predicted), sliced)


def trip_weighted_mae(
    rows: Sequence[Mapping[str, object]], actual: Sequence[float], predicted: Sequence[float]
) -> float:
    grouped: dict[str, list[float]] = {}
    for row, truth, estimate in zip(rows, actual, predicted, strict=True):
        grouped.setdefault(str(row["key"]), []).append(abs(estimate - truth))
    if not grouped:
        raise ValueError("trip-weighted MAE requires at least one trip")
    return mean(mean(errors) for errors in grouped.values())


def promotion_decision(
    rows: Sequence[Mapping[str, object]],
    actual: Sequence[float],
    candidate: Sequence[float],
    persistence: Sequence[float],
    *,
    bootstrap_samples: int = 2000,
    minimum_route_examples: int = 100,
    maximum_route_regression: float = 0.1,
    seed: int = 42,
) -> PromotionDecision:
    if not (len(rows) == len(actual) == len(candidate) == len(persistence)) or not rows:
        raise ValueError("promotion comparison requires equal, non-empty inputs")
    candidate_mae = trip_weighted_mae(rows, actual, candidate)
    persistence_mae = trip_weighted_mae(rows, actual, persistence)
    grouped: dict[str, list[float]] = {}
    for row, truth, estimate, baseline in zip(rows, actual, candidate, persistence, strict=True):
        grouped.setdefault(str(row["key"]), []).append(
            abs(estimate - truth) - abs(baseline - truth)
        )
    trip_differences = [mean(values) for values in grouped.values()]
    generator = random.Random(seed)
    bootstrapped = sorted(
        mean(generator.choice(trip_differences) for _ in trip_differences)
        for _ in range(bootstrap_samples)
    )
    lower = bootstrapped[max(0, int(0.025 * (bootstrap_samples - 1)))]
    upper = bootstrapped[min(bootstrap_samples - 1, int(0.975 * (bootstrap_samples - 1)))]
    route_indexes: dict[str, list[int]] = {}
    for index, row in enumerate(rows):
        route_indexes.setdefault(str(row["route_short_name"]), []).append(index)
    regressions: dict[str, float] = {}
    for route, indexes in route_indexes.items():
        if len(indexes) < minimum_route_examples:
            continue
        candidate_route = metrics([actual[i] for i in indexes], [candidate[i] for i in indexes]).mae
        persistence_route = metrics(
            [actual[i] for i in indexes], [persistence[i] for i in indexes]
        ).mae
        regressions[route] = (
            (candidate_route - persistence_route) / persistence_route
            if persistence_route > 0
            else 0.0
        )
    reasons = []
    if candidate_mae >= persistence_mae:
        reasons.append("candidate_trip_weighted_mae_not_lower")
    if upper >= 0:
        reasons.append("paired_bootstrap_interval_includes_no_improvement")
    if any(value > maximum_route_regression for value in regressions.values()):
        reasons.append("eligible_route_regressed_more_than_10_percent")
    return PromotionDecision(
        not reasons,
        candidate_mae,
        persistence_mae,
        candidate_mae - persistence_mae,
        (lower, upper),
        regressions,
        tuple(reasons),
    )


def chronological_split(
    rows: list[Mapping[str, object]],
    validation_days: int = 7,
    test_days: int = 7,
    purge_minutes: int = 30,
) -> tuple[list[int], list[int], list[int]]:
    if validation_days < 1 or test_days < 1:
        raise ValueError("validation and test windows must be positive")
    parsed = [datetime.fromisoformat(str(row["as_of"])) for row in rows]
    service_days = [datetime.fromisoformat(str(row["key"]).split("|")[1]).date() for row in rows]
    days = sorted(set(service_days))
    if len(days) < validation_days + test_days + 1:
        raise ValueError("not enough service days for requested chronological split")
    test_dates = set(days[-test_days:])
    validation_dates = set(days[-(test_days + validation_days) : -test_days])
    validation_boundary = min(
        value for value, day in zip(parsed, service_days, strict=True) if day in validation_dates
    )
    test_boundary = min(
        value for value, day in zip(parsed, service_days, strict=True) if day in test_dates
    )
    groups: dict[str, set[str]] = {}
    for row, day in zip(rows, service_days, strict=True):
        groups.setdefault(str(row["key"]), set()).add(day.isoformat())
    crossing = {key for key, group_days in groups.items() if len(group_days) > 1}
    # A trip crossing midnight is assigned by its first observation, never split.
    group_assignment: dict[str, str] = {}
    for key in crossing:
        earliest = min(groups[key])
        day = datetime.fromisoformat(earliest).date()
        group_assignment[key] = (
            "test" if day in test_dates else "validation" if day in validation_dates else "train"
        )
    output: tuple[list[int], list[int], list[int]] = ([], [], [])
    for index, (row, value, day) in enumerate(zip(rows, parsed, service_days, strict=True)):
        if any(
            abs((value - boundary).total_seconds()) <= purge_minutes * 60
            for boundary in (validation_boundary, test_boundary)
        ):
            continue
        assignment = group_assignment.get(str(row["key"]))
        if assignment is None:
            assignment = (
                "test"
                if day in test_dates
                else "validation"
                if day in validation_dates
                else "train"
            )
        output[{"train": 0, "validation": 1, "test": 2}[assignment]].append(index)
    return output


def rolling_origin_splits(
    rows: list[Mapping[str, object]], minimum_train_days: int = 14, test_days: int = 7
) -> Iterable[tuple[list[int], list[int]]]:
    dates = [datetime.fromisoformat(str(row["key"]).split("|")[1]).date() for row in rows]
    unique = sorted(set(dates))
    for boundary in range(minimum_train_days, len(unique), test_days):
        train_dates = set(unique[:boundary])
        test_dates_set = set(unique[boundary : boundary + test_days])
        if not test_dates_set:
            break
        yield (
            [index for index, day in enumerate(dates) if day in train_dates],
            [index for index, day in enumerate(dates) if day in test_dates_set],
        )
