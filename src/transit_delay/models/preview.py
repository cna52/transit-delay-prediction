from __future__ import annotations

import hashlib
import json
import subprocess
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from transit_delay.datasets.policy import LabelPolicy
from transit_delay.models.baselines import HistoricalMedianBaseline, PersistenceBaseline
from transit_delay.models.evaluation import evaluate, promotion_decision
from transit_delay.models.training import train_lightgbm, train_ridge


def _local_date(row: Mapping[str, Any], timezone: ZoneInfo) -> str:
    return datetime.fromisoformat(str(row["as_of"])).astimezone(timezone).date().isoformat()


def preview_split(
    records: list[dict[str, Any]],
    train_dates: set[str],
    validation_dates: set[str],
    timezone_name: str,
    purge_minutes: int = 30,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], float]:
    """Separate past training from validation, preserving trips across local midnight."""
    timezone = ZoneInfo(timezone_name)
    chosen = [
        row for row in records if _local_date(row, timezone) in train_dates | validation_dates
    ]
    if not chosen or not any(_local_date(row, timezone) in validation_dates for row in chosen):
        raise ValueError("preview requires examples on the selected validation dates")
    first_day: dict[str, str] = {}
    for row in chosen:
        day = _local_date(row, timezone)
        key = str(row["key"])
        first_day[key] = min(day, first_day.get(key, day))
    boundary = min(
        datetime.fromisoformat(str(row["as_of"]))
        for row in chosen
        if _local_date(row, timezone) in validation_dates
    )
    validation_all = [row for row in chosen if _local_date(row, timezone) in validation_dates]
    missing_rate = sum(
        not isinstance(row.get("label"), dict) or row["label"].get("status") != "labelled"
        for row in validation_all
    ) / len(validation_all)
    train: list[dict[str, Any]] = []
    validation: list[dict[str, Any]] = []
    for row in chosen:
        observed = datetime.fromisoformat(str(row["as_of"]))
        if abs((observed - boundary).total_seconds()) <= purge_minutes * 60:
            continue
        label = row.get("label")
        if not isinstance(label, dict) or label.get("status") != "labelled":
            continue
        if int(row["source_age_seconds"]) < 0:
            raise ValueError("feature source is newer than the prediction time")
        key_day = first_day[str(row["key"])]
        if key_day in train_dates:
            if datetime.fromisoformat(str(label["available_at"])) >= boundary:
                continue
            train.append(row)
        elif key_day in validation_dates:
            validation.append(row)
    if not train or not validation:
        raise ValueError("preview split has an empty labelled partition")
    if {str(row["key"]) for row in train} & {str(row["key"]) for row in validation}:
        raise ValueError("trip instance crosses preview partitions")
    return train, validation, missing_rate


def preview_validation(
    dataset: Path,
    data_dir: Path,
    report_dir: Path,
    timezone_name: str,
    *,
    minimum_train_days: int = 7,
    validation_days: int = 7,
    strong_model: bool = False,
) -> dict[str, object]:
    """Score historical validation dates without reading the final seven-day test."""
    if minimum_train_days < 1 or validation_days < 1:
        raise ValueError("preview training and validation windows must be positive")
    policy = LabelPolicy.load(data_dir / "state" / "label-policy.json")
    policy.verify_archives(data_dir)
    manifest = json.loads((dataset.parent / "manifest.json").read_text())
    digest = hashlib.sha256(dataset.read_bytes()).hexdigest()
    if digest != manifest.get("content_sha256"):
        raise ValueError("preview dataset checksum does not match its manifest")
    if manifest.get("label_policy_version") != policy.version:
        raise ValueError("preview dataset label policy does not match the approved policy")
    feasibility = json.loads((report_dir / "feasibility.json").read_text())
    complete = [str(day) for day in feasibility["audited_complete_dates"]]
    # The locked 28-day test begins after the first 21 complete service days.
    preview_dates = complete[:21]
    if len(preview_dates) < minimum_train_days + validation_days:
        raise ValueError("not enough complete usable days for preliminary validation")
    train_dates = set(preview_dates[:-validation_days])
    validation_dates = set(preview_dates[-validation_days:])
    records = [json.loads(line) for line in dataset.read_text().splitlines() if line]
    train, validation, missing_rate = preview_split(
        records, train_dates, validation_dates, timezone_name
    )

    def rows(values: list[dict[str, Any]]) -> list[Mapping[str, object]]:
        return [{key: value for key, value in row.items() if key != "label"} for row in values]

    def labels(values: list[dict[str, Any]]) -> list[float]:
        return [float(row["label"]["label_minutes"]) for row in values]

    training_rows, validation_rows = rows(train), rows(validation)
    training_labels, validation_labels = labels(train), labels(validation)
    persistence = PersistenceBaseline().predict(validation_rows)
    historical = (
        HistoricalMedianBaseline().fit(training_rows, training_labels).predict(validation_rows)
    )
    ridge = train_ridge(training_rows, training_labels)
    candidate_models = [ridge]
    if strong_model:
        candidate_models.append(train_lightgbm(training_rows, training_labels))
    predictions = {
        "persistence": persistence,
        "historical_median": historical,
        **{model.name: model.predict(validation_rows) for model in candidate_models},
    }
    reports = {
        name: evaluate(name, validation_rows, validation_labels, predicted).to_dict()
        for name, predicted in predictions.items()
    }
    comparisons: dict[str, object] = {}
    for model in candidate_models:
        diagnostic = promotion_decision(
            validation_rows,
            validation_labels,
            predictions[model.name],
            persistence,
        )
        comparisons[model.name] = {
            "trip_weighted_mae_difference_vs_persistence": diagnostic.mae_difference,
            "trip_clustered_95pct_interval": diagnostic.confidence_interval_95,
            "route_regressions": diagnostic.route_regressions,
        }
    return {
        "evidence_type": "exploratory_validation_only",
        "generated_at": datetime.now(UTC).isoformat(),
        "git_sha": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        "dataset_version": manifest["dataset_version"],
        "dataset_sha256": digest,
        "label_policy_version": policy.version,
        "train_dates": sorted(train_dates),
        "validation_dates": sorted(validation_dates),
        "training_labelled_examples": len(train),
        "validation_labelled_examples": len(validation),
        "validation_missing_label_rate": missing_rate,
        "reports": reports,
        "paired_comparisons": comparisons,
        "note": "Exploratory validation only; no model artifact, promotion, or locked test score.",
    }
