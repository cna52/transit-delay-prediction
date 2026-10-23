import json
from datetime import UTC, datetime, timedelta

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
