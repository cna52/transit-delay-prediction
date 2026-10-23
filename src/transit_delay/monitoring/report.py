from __future__ import annotations

import html
import json
from collections import Counter
from dataclasses import asdict, dataclass, is_dataclass
from datetime import datetime
from pathlib import Path
from statistics import mean
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class CollectionReport:
    date_from: str
    date_to: str
    attempts: int
    successes: int
    parse_or_fetch_failures: int
    success_rate: float
    unique_payloads: int
    duplicate_rate: float
    bytes_downloaded: int
    by_feed: dict[str, int]
    largest_gap_seconds: float | None
    service_days: int
    usable_service_days: int
    hourly_coverage: dict[str, int]


def collection_report(
    manifests: list[Path], timezone_name: str = "America/Vancouver"
) -> CollectionReport:
    records = [
        json.loads(line) for path in sorted(manifests) for line in path.read_text().splitlines()
    ]
    if not records:
        raise ValueError("no fetch records in reporting window")
    successes = [
        record for record in records if record.get("status_code") == 200 and not record.get("error")
    ]
    hashes = [record["payload_sha256"] for record in successes if record.get("payload_sha256")]
    timestamps = sorted(datetime.fromisoformat(record["requested_at"]) for record in records)
    gaps = [
        (right - left).total_seconds()
        for left, right in zip(timestamps, timestamps[1:], strict=False)
    ]
    timezone = ZoneInfo(timezone_name)
    successful_trip_updates = [
        datetime.fromisoformat(record["received_at"]).astimezone(timezone)
        for record in successes
        if record.get("feed_type") == "trip_updates" and record.get("received_at")
    ]
    hours_by_day: dict[str, set[int]] = {}
    hourly = Counter[str]()
    for timestamp in successful_trip_updates:
        day = timestamp.date().isoformat()
        hours_by_day.setdefault(day, set()).add(timestamp.hour)
        hourly[f"{timestamp.hour:02d}:00"] += 1
    return CollectionReport(
        timestamps[0].date().isoformat(),
        timestamps[-1].date().isoformat(),
        len(records),
        len(successes),
        len(records) - len(successes),
        len(successes) / len(records),
        len(set(hashes)),
        1 - len(set(hashes)) / len(hashes) if hashes else 0.0,
        sum(int(record.get("payload_bytes", 0)) for record in successes),
        dict(Counter(str(record["feed_type"]) for record in records)),
        max(gaps) if gaps else None,
        len(hours_by_day),
        sum(len(hours) >= 8 for hours in hours_by_day.values()),
        dict(sorted(hourly.items())),
    )


def prediction_report(
    prediction_log: Path, request_log: Path | None = None
) -> dict[str, object]:
    rows = (
        [json.loads(line) for line in prediction_log.read_text().splitlines() if line]
        if prediction_log.exists()
        else []
    )
    requests = (
        [json.loads(line) for line in request_log.read_text().splitlines() if line]
        if request_log is not None and request_log.exists()
        else []
    )
    labelled = [row for row in rows if row.get("label_minutes") is not None]
    absolute = [
        abs(float(row["prediction_minutes"]) - float(row["label_minutes"])) for row in labelled
    ]
    latencies = sorted(float(row["latency_ms"]) for row in requests if "latency_ms" in row)
    failures = [row for row in requests if int(row.get("status_code", 500)) >= 400]
    return {
        "predictions": len(rows),
        "requests": len(requests),
        "request_error_rate": len(failures) / len(requests) if requests else 0.0,
        "latency_ms": {
            "p50": _report_quantile(latencies, 0.5),
            "p95": _report_quantile(latencies, 0.95),
        },
        "labelled": len(labelled),
        "label_coverage": len(labelled) / len(rows) if rows else 0.0,
        "mae_minutes": mean(absolute) if absolute else None,
        "fallback_rate": sum(row.get("quality") != "normal" for row in rows) / len(rows)
        if rows
        else 0.0,
        "model_versions": dict(Counter(str(row.get("model_version")) for row in rows)),
        "data_modes": dict(Counter(str(row.get("data_mode", "unknown")) for row in rows)),
    }


def _report_quantile(values: list[float], quantile: float) -> float | None:
    if not values:
        return None
    return values[round((len(values) - 1) * quantile)]


def write_report(report: object, output: Path) -> None:
    value = asdict(report) if is_dataclass(report) and not isinstance(report, type) else report
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(value, indent=2, sort_keys=True, default=str))
    html_path = output.with_suffix(".html")
    html_path.write_text(
        "<!doctype html><meta charset='utf-8'><title>Transit delay report</title>"
        "<h1>Transit delay report</h1><pre>"
        + html.escape(json.dumps(value, indent=2, sort_keys=True, default=str))
        + "</pre>"
    )
