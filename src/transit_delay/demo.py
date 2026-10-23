from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from transit_delay.domain import FeatureRow, TripInstanceKey
from transit_delay.runtime import write_state


def seed_synthetic_demo(data_dir: Path, report_dir: Path) -> dict[str, object]:
    """Create deterministic, clearly marked synthetic inputs without licensed feed data."""
    as_of = datetime(2026, 1, 15, 17, 30, tzinfo=UTC)
    routes = ("099", "R4", "R5", "049")
    rows = []
    for index in range(16):
        route = routes[index % len(routes)]
        delay = (-60, 30, 120, 300, 480)[index % 5]
        key = TripInstanceKey("synthetic-v1", date(2026, 1, 15), f"demo-trip-{index}")
        identity = hashlib.sha256(f"{key.stable_id()}:{index}".encode()).hexdigest()[:24]
        destinations = ("UBC", "Joyce Station", "SFU", "Metrotown Station")
        stop_names = (
            "Broadway at Cambie Street",
            "Hastings at Commercial Drive",
            "49th Avenue at Main Street",
            "Broadway–City Hall Station",
        )
        row = FeatureRow(
            example_id=identity,
            as_of=as_of + timedelta(minutes=index),
            key=key,
            target_stop_sequence=20 + index,
            target_stop_id=f"demo-stop-{100 + index}",
            scheduled_target_arrival=as_of + timedelta(minutes=index + 12, seconds=delay),
            horizon_seconds=720,
            route_short_name=route,
            direction_id=index % 2,
            current_stop_sequence=12 + index,
            stops_to_target=8,
            current_delay_seconds=delay,
            delay_trend_seconds=30 if index % 3 else None,
            source_age_seconds=8,
            hour=9,
            minute=30 + index,
            weekday=3,
            target_stop_name=stop_names[index % len(stop_names)],
            trip_headsign=destinations[index % len(destinations)],
        )
        rows.append(row)
    snapshot = data_dir / "serving" / "latest_features.jsonl"
    snapshot.parent.mkdir(parents=True, exist_ok=True)
    snapshot.write_text(
        "\n".join(json.dumps(row.to_dict(), default=str) for row in rows) + "\n"
    )
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "collection.json").write_text(
        json.dumps(
            {
                "synthetic": True,
                "attempts": 96,
                "successes": 94,
                "success_rate": 94 / 96,
                "unique_payloads": 90,
                "duplicate_rate": 4 / 94,
                "largest_gap_seconds": 180,
                "bytes_downloaded": 0,
                "date_from": "2026-01-15",
                "date_to": "2026-01-15",
                "message": "Synthetic demonstration data; not production evidence.",
            },
            indent=2,
        )
    )
    (report_dir / "feed-audit.json").write_text(
        json.dumps(
            {
                "synthetic": True,
                "snapshots": 16,
                "trip_updates": 16,
                "vehicle_positions": 16,
                "freshness_seconds": {"median": 8, "p95": 12, "max": 15},
                "stop_field_presence": {"arrival_delay": 1.0, "stop_id": 1.0},
                "message": "Synthetic demonstration data; not production evidence.",
            },
            indent=2,
        )
    )
    write_state(data_dir / "state" / "collector.json", status="synthetic")
    write_state(data_dir / "state" / "worker.json", status="synthetic")
    return {
        "data_mode": "synthetic",
        "snapshot": str(snapshot),
        "observations": len(rows),
        "reports": str(report_dir),
    }
