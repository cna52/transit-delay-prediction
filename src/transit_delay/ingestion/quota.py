from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class QuotaSnapshot:
    service_day: str
    used: int
    limit: int


class DailyQuota:
    """Crash-safe single-process daily request counter."""

    def __init__(self, path: Path, limit: int, timezone_name: str):
        self.path = path
        self.limit = limit
        self.timezone = ZoneInfo(timezone_name)

    def snapshot(self, now: datetime) -> QuotaSnapshot:
        today = now.astimezone(self.timezone).date().isoformat()
        state = self._read()
        raw_used = state.get("used", 0) if state.get("service_day") == today else 0
        used = int(raw_used) if isinstance(raw_used, (str, int)) else 0
        return QuotaSnapshot(today, used, self.limit)

    def consume(self, now: datetime) -> QuotaSnapshot:
        current = self.snapshot(now)
        if current.used >= current.limit:
            raise RuntimeError(f"daily request quota exhausted for {current.service_day}")
        updated = QuotaSnapshot(current.service_day, current.used + 1, current.limit)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(updated.__dict__, sort_keys=True))
        os.replace(temporary, self.path)
        return updated

    def _read(self) -> dict[str, object]:
        if not self.path.exists():
            return {}
        value = json.loads(self.path.read_text())
        return value if isinstance(value, dict) else {}
