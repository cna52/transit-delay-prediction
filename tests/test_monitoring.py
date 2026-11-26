import json
from datetime import UTC, date, datetime, timedelta

from typer.testing import CliRunner

from transit_delay.cli import app
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
    sparse = collection_report([manifest], feed_intervals_seconds={"trip_updates": 60})
    assert sparse.expected_cadence_slots_by_feed == {"trip_updates": 3}
    assert sparse.attempted_cadence_fraction_by_feed == {"trip_updates": 2 / 3}

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


def test_prediction_report_reconciles_daily_and_route_serving_evidence(tmp_path) -> None:
    predictions = tmp_path / "predictions.jsonl"
    requests = tmp_path / "requests.jsonl"
    at = "2026-10-22T17:00:00-07:00"
    predictions.write_text(
        "\n".join(
            json.dumps(row)
            for row in [
                {
                    "predicted_at": at,
                    "prediction_minutes": 3,
                    "label_minutes": 2,
                    "label_status": "labelled",
                    "model_version": "model-ridge",
                    "route": "R5",
                    "freshness_seconds": 90,
                    "quality": "normal",
                },
                {
                    "predicted_at": at,
                    "prediction_minutes": 2,
                    "label_minutes": None,
                    "label_status": "censored",
                    "model_version": "persistence-v1",
                    "route": "R5",
                    "freshness_seconds": 180,
                    "quality": "fallback",
                    "fallback_reason": "stale_features",
                },
            ]
        )
        + "\n"
    )
    requests.write_text(
        json.dumps(
            {
                "requested_at": at,
                "status_code": 503,
                "latency_ms": 12,
                "route": "R5",
            }
        )
        + "\n"
    )

    report = prediction_report(predictions, requests, date(2026, 10, 22), date(2026, 10, 22))

    assert report["request_errors"] == 1
    assert report["bias_minutes"] == 1
    assert report["matured_labels"] == 1
    assert report["censored_labels"] == 1
    assert report["stale_input_fallbacks"] == 1
    assert report["daily"]["2026-10-22"]["freshness_seconds"] == {"p50": 90.0, "p95": 180.0}
    assert report["routes"]["R5"]["model_versions"] == {"model-ridge": 1, "persistence-v1": 1}
    assert report["routes"]["R5"]["request_errors"] == 1


def test_prediction_report_can_filter_exact_timestamp_window(tmp_path) -> None:
    predictions = tmp_path / "predictions.jsonl"
    requests = tmp_path / "requests.jsonl"
    timestamps = [
        "2026-11-26T00:42:32.668267+00:00",
        "2026-11-26T00:42:32.668268+00:00",
        "2026-12-03T00:42:32.668268+00:00",
        "2026-12-03T00:42:32.668269+00:00",
    ]
    predictions.write_text(
        "\n".join(
            json.dumps({"predicted_at": timestamp, "prediction_minutes": 1})
            for timestamp in timestamps
        )
        + "\n"
    )
    requests.write_text(
        "\n".join(
            json.dumps({"requested_at": timestamp, "status_code": 200}) for timestamp in timestamps
        )
        + "\n"
    )

    report = prediction_report(
        predictions,
        requests,
        start_at=datetime.fromisoformat(timestamps[1]),
        end_at=datetime.fromisoformat(timestamps[2]),
    )

    assert report["predictions"] == report["requests"] == 2
    assert report["window_start_at"] == timestamps[1]
    assert report["window_end_at"] == timestamps[2]


def test_prediction_report_refreshes_join_for_latest_predictions(tmp_path) -> None:
    data = tmp_path / "data"
    reports = tmp_path / "reports"
    (data / "logs").mkdir(parents=True)
    (data / "processed").mkdir(parents=True)
    (data / "monitoring").mkdir(parents=True)
    config = tmp_path / "config.yaml"
    config.write_text(f"data_dir: {data}\nreport_dir: {reports}\ntimezone: UTC\n")
    (data / "logs/predictions.jsonl").write_text(
        json.dumps(
            {
                "prediction_id": "new-prediction",
                "example_id": "new-example",
                "predicted_at": "2026-11-26T00:42:32+00:00",
                "prediction_minutes": 2,
                "model_version": "model-ridge",
            }
        )
        + "\n"
    )
    (data / "processed/labels.jsonl").write_text(
        json.dumps(
            {
                "example_id": "new-example",
                "status": "pending",
                "label_minutes": None,
                "available_at": "2026-11-26T00:42:32+00:00",
            }
        )
        + "\n"
    )
    (data / "monitoring/labelled_predictions.jsonl").write_text(
        json.dumps(
            {
                "prediction_id": "old-prediction",
                "example_id": "old-example",
                "predicted_at": "2026-11-25T00:00:00+00:00",
                "label_status": "pending",
            }
        )
        + "\n"
    )

    result = CliRunner().invoke(
        app,
        [
            "prediction-report",
            "--config",
            str(config),
            "--start-at",
            "2026-11-26T00:42:32+00:00",
            "--end-at",
            "2026-12-03T00:42:32+00:00",
        ],
    )

    assert result.exit_code == 0, result.output
    report_path = reports / "predictions-20261126T004232+0000-20261203T004232+0000.json"
    report = json.loads(report_path.read_text())
    assert report["predictions"] == 1
    assert report["missing_or_pending_labels"] == 1


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
