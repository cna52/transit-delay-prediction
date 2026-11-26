from __future__ import annotations

import html
import json
from collections import Counter
from dataclasses import asdict, dataclass, is_dataclass
from datetime import UTC, date, datetime
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
    usable_service_dates: tuple[str, ...]
    successes_by_feed: dict[str, int]
    largest_gap_by_feed_seconds: dict[str, float | None]
    expected_cadence_slots_by_feed: dict[str, int]
    attempted_cadence_fraction_by_feed: dict[str, float]
    compressed_storage_bytes_by_local_day: dict[str, int]
    projected_56_day_raw_bytes: int | None


def collection_report(
    manifests: list[Path],
    timezone_name: str = "America/Vancouver",
    feed_intervals_seconds: dict[str, int] | None = None,
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
    usable_dates = tuple(sorted(day for day, hours in hours_by_day.items() if len(hours) >= 8))
    gaps_by_feed: dict[str, float | None] = {}
    expected_slots: dict[str, int] = {}
    attempt_fractions: dict[str, float] = {}
    intervals = feed_intervals_seconds or {"trip_updates": 120, "vehicle_positions": 600}
    for feed_type in sorted({str(record["feed_type"]) for record in records}):
        requested = sorted(
            datetime.fromisoformat(record["requested_at"])
            for record in records
            if record["feed_type"] == feed_type
        )
        gaps_by_feed[feed_type] = max(
            (
                (right - left).total_seconds()
                for left, right in zip(requested, requested[1:], strict=False)
            ),
            default=None,
        )
        interval = intervals.get(feed_type)
        if interval and interval > 0 and requested:
            expected_slots[feed_type] = 1 + int(
                (requested[-1] - requested[0]).total_seconds() // interval
            )
            attempt_fractions[feed_type] = min(1.0, len(requested) / expected_slots[feed_type])
    storage_by_day: Counter[str] = Counter()
    seen_paths: set[str] = set()
    for record in successes:
        payload_path = record.get("payload_path")
        if not payload_path or payload_path in seen_paths:
            continue
        seen_paths.add(payload_path)
        path = Path(payload_path)
        if path.exists():
            local_date = datetime.fromisoformat(record["received_at"]).astimezone(timezone).date()
            storage_by_day[local_date.isoformat()] += path.stat().st_size
    today = datetime.now(timezone).date().isoformat()
    complete_usable = [day for day in usable_dates if day < today]
    projected_storage = (
        round(sum(storage_by_day[day] for day in complete_usable) / len(complete_usable) * 56)
        if len(complete_usable) >= 2
        else None
    )
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
        len(usable_dates),
        dict(sorted(hourly.items())),
        usable_dates,
        dict(Counter(str(record["feed_type"]) for record in successes)),
        gaps_by_feed,
        expected_slots,
        attempt_fractions,
        dict(sorted(storage_by_day.items())),
        projected_storage,
    )


def prediction_report(
    prediction_log: Path,
    request_log: Path | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    timezone_name: str = "America/Vancouver",
    start_at: datetime | None = None,
    end_at: datetime | None = None,
) -> dict[str, object]:
    if start_date and end_date and start_date > end_date:
        raise ValueError("monitoring start date must not exceed end date")
    if start_at and end_at and start_at > end_at:
        raise ValueError("monitoring start timestamp must not exceed end timestamp")
    if any(value and value.tzinfo is None for value in (start_at, end_at)):
        raise ValueError("monitoring timestamps must include a timezone")
    timezone = ZoneInfo(timezone_name)

    def local_day(row: dict[str, object], field: str) -> str | None:
        value = row.get(field)
        if not value:
            return None
        return datetime.fromisoformat(str(value)).astimezone(timezone).date().isoformat()

    def included(row: dict[str, object], field: str) -> bool:
        raw_timestamp = row.get(field)
        if start_at or end_at:
            if not raw_timestamp:
                return False
            timestamp = datetime.fromisoformat(str(raw_timestamp))
            if timestamp.tzinfo is None:
                timestamp = timestamp.replace(tzinfo=UTC)
            if start_at and timestamp < start_at:
                return False
            if end_at and timestamp > end_at:
                return False
        if start_date is None and end_date is None:
            return bool(raw_timestamp) if start_at or end_at else True
        day = local_day(row, field)
        return bool(
            day
            and (start_date is None or day >= start_date.isoformat())
            and (end_date is None or day <= end_date.isoformat())
        )

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
    rows = [row for row in rows if included(row, "predicted_at")]
    requests = [row for row in requests if included(row, "requested_at")]
    labelled = [row for row in rows if row.get("label_minutes") is not None]
    label_statuses = Counter(
        str(
            row.get(
                "label_status", "labelled" if row.get("label_minutes") is not None else "missing"
            )
        )
        for row in rows
    )
    absolute = [
        abs(float(row["prediction_minutes"]) - float(row["label_minutes"]))
        for row in labelled
        if row.get("prediction_minutes") is not None
    ]
    latencies = sorted(float(row["latency_ms"]) for row in requests if "latency_ms" in row)
    freshness = sorted(
        float(row["freshness_seconds"]) for row in rows if row.get("freshness_seconds") is not None
    )
    failures = [row for row in requests if int(row.get("status_code", 500)) >= 400]
    prediction_days = sorted({day for row in rows if (day := local_day(row, "predicted_at"))})

    def slice_metrics(
        prediction_rows: list[dict[str, object]], request_rows: list[dict[str, object]]
    ) -> dict[str, object]:
        slice_labelled = [row for row in prediction_rows if row.get("label_minutes") is not None]
        errors = [row for row in request_rows if int(row.get("status_code", 500)) >= 400]
        slice_latency = sorted(
            float(row["latency_ms"]) for row in request_rows if "latency_ms" in row
        )
        slice_freshness = sorted(
            float(row["freshness_seconds"])
            for row in prediction_rows
            if row.get("freshness_seconds") is not None
        )
        slice_statuses = Counter(
            str(
                row.get(
                    "label_status",
                    "labelled" if row.get("label_minutes") is not None else "missing",
                )
            )
            for row in prediction_rows
        )
        slice_fallbacks = Counter(
            str(row.get("fallback_reason")) for row in prediction_rows if row.get("fallback_reason")
        )
        versions = Counter(str(row.get("model_version")) for row in prediction_rows)
        residuals = [
            float(row["prediction_minutes"]) - float(row["label_minutes"])
            for row in slice_labelled
            if row.get("prediction_minutes") is not None
        ]
        return {
            "predictions": len(prediction_rows),
            "requests": len(request_rows),
            "request_errors": len(errors),
            "request_error_rate": len(errors) / len(request_rows) if request_rows else 0.0,
            "latency_ms": {
                "p50": _report_quantile(slice_latency, 0.5),
                "p95": _report_quantile(slice_latency, 0.95),
            },
            "freshness_seconds": {
                "p50": _report_quantile(slice_freshness, 0.5),
                "p95": _report_quantile(slice_freshness, 0.95),
            },
            "model_versions": dict(versions),
            "fallback_counts": dict(slice_fallbacks),
            "stale_input_fallbacks": slice_fallbacks.get("stale_features", 0),
            "label_status_counts": dict(slice_statuses),
            "matured_labels": slice_statuses.get("labelled", 0),
            "missing_or_pending_labels": slice_statuses.get("pending", 0)
            + slice_statuses.get("missing", 0),
            "censored_labels": slice_statuses.get("censored", 0),
            "mae_minutes": mean(abs(value) for value in residuals) if residuals else None,
            "bias_minutes": mean(residuals) if residuals else None,
        }

    requests_by_day: dict[str, list[dict[str, object]]] = {}
    for request in requests:
        day = local_day(request, "requested_at")
        if day:
            requests_by_day.setdefault(day, []).append(request)
    predictions_by_day: dict[str, list[dict[str, object]]] = {}
    predictions_by_route: dict[str, list[dict[str, object]]] = {}
    requests_by_route: dict[str, list[dict[str, object]]] = {}
    for request in requests:
        route = request.get("route")
        if route is not None:
            requests_by_route.setdefault(str(route), []).append(request)
    for row in rows:
        day = local_day(row, "predicted_at")
        if day:
            predictions_by_day.setdefault(day, []).append(row)
        route = row.get("route")
        if route is not None:
            predictions_by_route.setdefault(str(route), []).append(row)
    daily = {
        day: slice_metrics(predictions_by_day.get(day, []), requests_by_day.get(day, []))
        for day in sorted(set(predictions_by_day) | set(requests_by_day))
    }
    route_names = set(predictions_by_route) | set(requests_by_route)
    routes = {
        route: slice_metrics(predictions_by_route.get(route, []), requests_by_route.get(route, []))
        for route in sorted(route_names)
    }
    return {
        "window_start": start_date.isoformat() if start_date else None,
        "window_end": end_date.isoformat() if end_date else None,
        "window_start_at": start_at.isoformat() if start_at else None,
        "window_end_at": end_at.isoformat() if end_at else None,
        "prediction_days": prediction_days,
        "observed_prediction_days": len(prediction_days),
        "predictions": len(rows),
        "requests": len(requests),
        "request_errors": len(failures),
        "request_error_rate": len(failures) / len(requests) if requests else 0.0,
        "latency_ms": {
            "p50": _report_quantile(latencies, 0.5),
            "p95": _report_quantile(latencies, 0.95),
        },
        "labelled": len(labelled),
        "label_status_counts": dict(label_statuses),
        "matured_labels": label_statuses.get("labelled", len(labelled)),
        "missing_or_pending_labels": label_statuses.get("pending", 0)
        + label_statuses.get("missing", 0),
        "censored_labels": label_statuses.get("censored", 0),
        "label_coverage": len(labelled) / len(rows) if rows else 0.0,
        "missing_label_rate": 1 - len(labelled) / len(rows) if rows else 0.0,
        "mae_minutes": mean(absolute) if absolute else None,
        "bias_minutes": mean(
            float(row["prediction_minutes"]) - float(row["label_minutes"])
            for row in labelled
            if row.get("prediction_minutes") is not None
        )
        if any(row.get("prediction_minutes") is not None for row in labelled)
        else None,
        "fallback_rate": sum(row.get("quality") != "normal" for row in rows) / len(rows)
        if rows
        else 0.0,
        "model_versions": dict(Counter(str(row.get("model_version")) for row in rows)),
        "data_modes": dict(Counter(str(row.get("data_mode", "unknown")) for row in rows)),
        "fallback_reasons": dict(
            Counter(str(row.get("fallback_reason")) for row in rows if row.get("fallback_reason"))
        ),
        "fallback_counts": dict(
            Counter(str(row.get("fallback_reason")) for row in rows if row.get("fallback_reason"))
        ),
        "stale_input_fallbacks": sum(
            row.get("fallback_reason") == "stale_features" for row in rows
        ),
        "daily": daily,
        "routes": routes,
        "freshness_seconds": {
            "p50": _report_quantile(freshness, 0.5),
            "p95": _report_quantile(freshness, 0.95),
        },
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
