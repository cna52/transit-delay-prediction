from __future__ import annotations

import json
import os
from pathlib import Path


def join_delayed_labels(predictions: Path, labels: Path, output: Path) -> dict[str, int]:
    """Idempotently join prediction and label JSONL files by prediction/example identity."""
    prediction_rows = [json.loads(line) for line in predictions.read_text().splitlines() if line]
    label_rows = [json.loads(line) for line in labels.read_text().splitlines() if line]
    labels_by_id = {str(row["example_id"]): row for row in label_rows}
    joined: dict[str, dict[str, object]] = {}
    for prediction in prediction_rows:
        prediction_id = str(prediction["prediction_id"])
        example_id = str(prediction["example_id"])
        label = labels_by_id.get(example_id)
        joined[prediction_id] = {
            **prediction,
            "label_status": label.get("status") if label else "pending",
            "label_minutes": label.get("label_minutes") if label else None,
            "label_available_at": label.get("available_at") if label else None,
        }
    canonical = "\n".join(json.dumps(joined[key], sort_keys=True) for key in sorted(joined))
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(".tmp")
    temporary.write_text(canonical + ("\n" if canonical else ""))
    os.replace(temporary, output)
    return {
        "predictions": len(joined),
        "labelled": sum(row["label_status"] == "labelled" for row in joined.values()),
        "pending": sum(row["label_status"] == "pending" for row in joined.values()),
    }
