from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo


def parse_gtfs_time(service_date: date, value: str, timezone_name: str) -> datetime:
    hours, minutes, seconds = (int(part) for part in value.split(":"))
    if hours < 0 or minutes not in range(60) or seconds not in range(60):
        raise ValueError(f"invalid GTFS time: {value}")
    local_midnight = datetime.combine(service_date, datetime.min.time(), ZoneInfo(timezone_name))
    return (local_midnight + timedelta(hours=hours, minutes=minutes, seconds=seconds)).astimezone(
        UTC
    )
