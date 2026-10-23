from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path


class SnapshotStore:
    def __init__(self, path: Path):
        self.path = path
        self._mtime = -1.0
        self._rows: list[dict[str, object]] = []

    def refresh(self) -> None:
        mtime = self.path.stat().st_mtime
        if mtime == self._mtime:
            return
        self._rows = [json.loads(line) for line in self.path.read_text().splitlines() if line]
        self._mtime = mtime

    def find(
        self,
        trip_id: str,
        service_date: str,
        start_time: str | None = None,
        target_stop_id: str | None = None,
        as_of: datetime | None = None,
    ) -> Mapping[str, object] | None:
        self.refresh()
        matches = []
        for row in self._rows:
            key_parts = str(row["key"]).split("|")
            if len(key_parts) < 4 or key_parts[1] != service_date or key_parts[2] != trip_id:
                continue
            if start_time and key_parts[3] != start_time:
                continue
            if target_stop_id and row["target_stop_id"] != target_stop_id:
                continue
            observed = datetime.fromisoformat(str(row["as_of"]))
            if as_of and observed > as_of:
                continue
            matches.append((observed, row))
        return max(matches, default=(None, None), key=lambda item: item[0])[1]

    def all(self) -> list[dict[str, object]]:
        self.refresh()
        return list(self._rows)

    def get(self, example_id: str) -> Mapping[str, object] | None:
        self.refresh()
        return next(
            (row for row in self._rows if str(row.get("example_id")) == example_id),
            None,
        )
