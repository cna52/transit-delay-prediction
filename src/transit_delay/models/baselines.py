from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from statistics import median


class PersistenceBaseline:
    version = "persistence-v1"

    def predict_one(self, row: Mapping[str, object]) -> float:
        return float(str(row["current_delay_seconds"])) / 60.0

    def predict(self, rows: Iterable[Mapping[str, object]]) -> list[float]:
        return [self.predict_one(row) for row in rows]


class HistoricalMedianBaseline:
    version = "historical-median-v1"

    def __init__(self) -> None:
        self.levels: list[dict[tuple[object, ...], float]] = []
        self.global_median = 0.0

    @staticmethod
    def _keys(row: Mapping[str, object]) -> tuple[tuple[object, ...], ...]:
        bucket = int(str(row["hour"])) * 2 + int(str(row.get("minute", 0))) // 30
        return (
            (row["route_short_name"], row.get("direction_id"), row["target_stop_id"], bucket),
            (row["route_short_name"], row.get("direction_id"), bucket),
            (row["route_short_name"], bucket),
        )

    def fit(
        self, rows: list[Mapping[str, object]], labels: list[float]
    ) -> HistoricalMedianBaseline:
        buckets: list[dict[tuple[object, ...], list[float]]] = [defaultdict(list) for _ in range(3)]
        for row, label in zip(rows, labels, strict=True):
            for index, key in enumerate(self._keys(row)):
                buckets[index][key].append(float(label))
        self.levels = [{key: median(values) for key, values in level.items()} for level in buckets]
        self.global_median = median(labels) if labels else 0.0
        return self

    def predict_one(self, row: Mapping[str, object]) -> float:
        for level, key in zip(self.levels, self._keys(row), strict=True):
            if key in level:
                return level[key]
        return self.global_median

    def predict(self, rows: Iterable[Mapping[str, object]]) -> list[float]:
        return [self.predict_one(row) for row in rows]
