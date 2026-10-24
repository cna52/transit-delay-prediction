import json
from datetime import UTC, date, datetime, timedelta

from transit_delay.monitoring.delayed import join_delayed_labels
from transit_delay.monitoring.report import collection_report, prediction_report


def test_collection_and_delayed_evaluation_are_reproducible(tmp_path) -> None:
    manifest = tmp_path / "manifest.jsonl"
    start = datetime(2026, 8, 10, tzinfo=UTC)
    records = [
        {
            "feed_type": "trip_updates",
            "requested_at": (start + timedelta(minutes=i * 2)).isoformat(),
            "status_code": 200,
            "error": None,
            "payload_sha256": "same",
            "payload_bytes": 100,
        }
        for i in range(2)
    ]
    manifest.write_text("\n".join(json.dumps(row) for row in records) + "\n")
    report = collection_report([manifest])
    assert report.success_rate == 1
    assert report.duplicate_rate == 0.5
    assert report.largest_gap_by_feed_seconds == {"trip_updates": 120.0}

    predictions = tmp_path / "predictions.jsonl"
    labels = tmp_path / "labels.jsonl"
    output = tmp_path / "joined.jsonl"
    predictions.write_text(
        json.dumps(
            {
                "prediction_id": "p1",
                "example_id": "e1",
                "prediction_minutes": 2,
                "quality": "normal",
                "model_version": "m1",
            }
        )
        + "\n"
    )
    labels.write_text(
        json.dumps(
            {
                "example_id": "e1",
                "status": "labelled",
                "label_minutes": 3,
                "available_at": start.isoformat(),
            }
        )
        + "\n"
    )
    first = join_delayed_labels(predictions, labels, output)
    second = join_delayed_labels(predictions, labels, output)
    assert first == second == {"predictions": 1, "labelled": 1, "pending": 0}
    assert prediction_report(output)["mae_minutes"] == 1


def test_prediction_report_can_lock_a_local_service_window(tmp_path) -> None:
    predictions = tmp_path / "predictions.jsonl"
    requests = tmp_path / "requests.jsonl"
    rows = [
        {
            "prediction_minutes": 2,
            "label_minutes": 3,
            "quality": "fallback",
            "fallback_reason": "no_promoted_model",
            "freshness_seconds": 40,
            "predicted_at": "2026-10-23T06:00:00+00:00",
        },
        {
            "prediction_minutes": 4,
            "label_minutes": None,
            "quality": "normal",
            "freshness_seconds": 60,
            "predicted_at": "2026-10-24T06:00:00+00:00",
        },
    ]
    predictions.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
    requests.write_text(
        "\n".join(
            json.dumps({"requested_at": row["predicted_at"], "latency_ms": 5, "status_code": 200})
            for row in rows
        )
        + "\n"
    )
    report = prediction_report(predictions, requests, date(2026, 10, 22), date(2026, 10, 22))
    assert report["predictions"] == report["requests"] == 1
    assert report["prediction_days"] == ["2026-10-22"]
    assert report["mae_minutes"] == 1
    assert report["fallback_reasons"] == {"no_promoted_model": 1}
    assert report["freshness_seconds"]["p95"] == 40


def test_collection_projects_storage_only_from_complete_usable_days(tmp_path) -> None:
    manifest = tmp_path / "manifest.jsonl"
    records = []
    for day in (10, 11):
        for hour in range(8):
            at = datetime(2026, 8, day, hour, tzinfo=UTC)
            payload = tmp_path / f"{day}-{hour}.gz"
            payload.write_bytes(b"x" * 10)
            records.append(
                {
                    "feed_type": "trip_updates",
                    "requested_at": at.isoformat(),
                    "received_at": at.isoformat(),
                    "status_code": 200,
                    "error": None,
                    "payload_sha256": payload.stem,
                    "payload_bytes": 100,
                    "payload_path": str(payload),
                }
            )
    manifest.write_text("\n".join(json.dumps(row) for row in records) + "\n")
    report = collection_report([manifest], "UTC")
    assert report.usable_service_days == 2
    assert report.projected_56_day_raw_bytes == 8 * 10 * 56
