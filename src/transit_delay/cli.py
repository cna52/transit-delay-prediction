from __future__ import annotations

import json
import os
import subprocess
from collections import Counter
from collections.abc import Mapping
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import cast
from zoneinfo import ZoneInfo

import typer

from transit_delay.config import Settings, load_settings
from transit_delay.datasets.labels import Labeler
from transit_delay.datasets.policy import LabelPolicy, TargetType
from transit_delay.datasets.resolver import read_features, resolve_archived_labels
from transit_delay.datasets.store import DatasetStore
from transit_delay.demo import seed_synthetic_demo
from transit_delay.domain import FeatureRow, LabelOutcome
from transit_delay.features.builder import FeatureBuilder
from transit_delay.gtfs.static import StaticCatalog, archive_static_zip
from transit_delay.ingestion.archive import ImmutableArchive
from transit_delay.ingestion.client import Endpoint, FeedClient
from transit_delay.ingestion.collector import Collector, ScheduledEndpoint
from transit_delay.ingestion.quota import DailyQuota
from transit_delay.logging import configure_logging
from transit_delay.models.artifacts import ArtifactStore
from transit_delay.models.baselines import HistoricalMedianBaseline, PersistenceBaseline
from transit_delay.models.evaluation import (
    chronological_split,
    empirical_interval_report,
    evaluate,
    promotion_decision,
    rolling_origin_splits,
)
from transit_delay.models.training import train_lightgbm, train_ridge
from transit_delay.monitoring.audit import archived_feeds, audit_feeds, trip_timeline_samples
from transit_delay.monitoring.delayed import join_delayed_labels
from transit_delay.monitoring.evidence import build_portfolio_summary
from transit_delay.monitoring.report import collection_report, prediction_report, write_report
from transit_delay.pipeline import SnapshotProcessor, process_manifest
from transit_delay.worker import Worker, registry_for

app = typer.Typer(no_args_is_help=True, help="TransLink delay prediction operations")


@app.command("download-static")
def download_static(config: Path | None = None) -> None:
    """Download, content-address, and profile the current Static GTFS."""
    import httpx

    settings = load_settings(config)
    response = httpx.get(settings.static_url, timeout=60, follow_redirects=True)
    response.raise_for_status()
    path = archive_static_zip(response.content, settings.data_dir)
    catalog = StaticCatalog.from_zip(path, settings.timezone)
    registry_for(settings).register(path)
    profile = settings.data_dir / "processed" / "static" / catalog.version / "profile.json"
    catalog.write_profile(profile)
    typer.echo(json.dumps({"archive": str(path), "profile": str(profile)}, indent=2))


@app.command("collect")
def collect(config: Path | None = None, once: bool = False) -> None:
    """Collect quota-aware immutable realtime snapshots."""
    settings = load_settings(config)
    configure_logging(settings.log_level)
    if not settings.api_key:
        raise typer.BadParameter("TRANSLINK_API_KEY is required")
    client = FeedClient(
        settings.api_key,
        ImmutableArchive(settings.data_dir),
        DailyQuota(
            settings.data_dir / "state" / "quota.json",
            settings.daily_request_limit,
            settings.timezone,
        ),
    )
    endpoints = [
        ScheduledEndpoint(
            Endpoint("trip_updates", settings.trip_updates_url),
            settings.trip_updates_interval_seconds,
        ),
        ScheduledEndpoint(
            Endpoint("vehicle_positions", settings.vehicle_positions_url),
            settings.vehicle_positions_interval_seconds,
        ),
    ]
    if once:
        for endpoint in endpoints:
            typer.echo(json.dumps(asdict(client.fetch(endpoint.endpoint)), default=str))
        return
    Collector(client, endpoints, settings.data_dir / "state" / "collector.json").run_forever()


@app.command("build-features")
def build_features(static_zip: Path, config: Path | None = None) -> None:
    """Replay archived Trip Updates into a point-in-time serving snapshot."""
    settings = load_settings(config)
    catalog = StaticCatalog.from_zip(static_zip, settings.timezone)
    processor = SnapshotProcessor(
        catalog,
        set(settings.selected_routes),
        FeatureBuilder(
            settings.target_horizon_min_seconds,
            settings.target_horizon_max_seconds,
            settings.example_cooldown_seconds,
            settings.timezone,
        ),
    )
    manifests = list((settings.data_dir / "raw" / "manifests").glob("*.jsonl"))
    rows, stats = process_manifest(manifests, processor)
    output = settings.data_dir / "serving" / "latest_features.jsonl"
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(".tmp")
    temporary.write_text(
        "\n".join(json.dumps(row.to_dict(), default=str) for row in rows) + ("\n" if rows else "")
    )
    os.replace(temporary, output)
    typer.echo(json.dumps({"snapshot": str(output), "stats": asdict(stats)}, indent=2))


@app.command("build-labels")
def build_labels(
    features: Path,
    config: Path | None = None,
    policy: Path | None = None,
) -> None:
    """Resolve delayed labels using a checksummed, explicit label policy."""
    settings = load_settings(config)
    policy_path = policy or settings.data_dir / "state" / "label-policy.json"
    if not policy_path.exists():
        raise typer.BadParameter("create a label policy with create-label-policy first")
    label_policy = LabelPolicy.load(policy_path)
    rows = read_features(features)
    manifests = list((settings.data_dir / "raw" / "manifests").glob("*.jsonl"))
    outcomes = resolve_archived_labels(
        rows,
        manifests,
        Labeler(label_policy),
        settings.label_wait_seconds,
    )
    output = settings.data_dir / "processed" / "labels.jsonl"
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(".tmp")
    temporary.write_text(
        "\n".join(json.dumps(asdict(value), default=str) for value in outcomes)
        + ("\n" if outcomes else "")
    )
    os.replace(temporary, output)
    typer.echo(
        json.dumps(
            {
                "output": str(output),
                "counts": dict(Counter(row.status for row in outcomes)),
            },
            indent=2,
        )
    )


@app.command("create-label-policy")
def create_label_policy(
    config: Path | None = None,
    target_type: TargetType = "reported_delay_state",
    notes: str = "",
    reviewed_trip_timelines: int = 0,
) -> None:
    """Create a versioned policy bound to the current feed-audit report."""
    settings = load_settings(config)
    audit = settings.report_dir / "feed-audit.json"
    if not audit.exists():
        raise typer.BadParameter("run feed-audit before creating a label policy")
    audit_value = json.loads(audit.read_text())
    semantics = audit_value.get("label_semantics") or {}
    quality_path = settings.report_dir / "dataset-quality.json"
    collection_path = settings.report_dir / "collection.json"
    if not quality_path.exists() or not collection_path.exists():
        raise typer.BadParameter(
            "dataset-quality and collection reports are required before creating a label policy"
        )
    quality = json.loads(quality_path.read_text())
    collection = json.loads(collection_path.read_text())
    if float(quality.get("strict_join_success_rate") or 0) < 0.9:
        raise typer.BadParameter("strict Static join success rate must be at least 90%")
    today = datetime.now(UTC).astimezone(ZoneInfo(settings.timezone)).date().isoformat()
    complete_dates = [day for day in collection.get("usable_service_dates", []) if day < today]
    if len(complete_dates) < 2 or int(quality.get("service_days", 0)) < 2:
        raise typer.BadParameter("label audit requires at least two usable service days")
    if int(semantics.get("examples_checked", 0)) < 100:
        raise typer.BadParameter("label audit requires at least 100 eligible examples")
    if float(semantics.get("candidate_coverage", 0)) < 0.7:
        raise typer.BadParameter("candidate-label coverage must be at least 70%")
    if reviewed_trip_timelines < 10:
        raise typer.BadParameter(
            "review at least ten trip timelines before locking the label policy"
        )
    if target_type == "measured_arrival" and (
        int(semantics.get("post_passage_retained_twice", 0)) < 10
        or int(semantics.get("vehicle_position_confirmed", 0)) < 10
        or int(semantics.get("retained_and_position_confirmed", 0)) < 10
    ):
        raise typer.BadParameter(
            "measured-arrival policy requires 10 retained post-passage and vehicle-confirmed cases"
        )
    policy = LabelPolicy.from_audit(
        audit, target_type, f"{notes}; reviewed_trip_timelines={reviewed_trip_timelines}"
    )
    audit_archive = settings.data_dir / "state" / "label-audits" / f"{policy.audit_sha256}.json"
    audit_archive.parent.mkdir(parents=True, exist_ok=True)
    if not audit_archive.exists():
        audit_archive.write_bytes(audit.read_bytes())
    policy.verify_audit(audit_archive)
    output = settings.data_dir / "state" / "label-policy.json"
    policy.write(output)
    typer.echo(
        json.dumps(
            {"policy": str(output), "audit_artifact": str(audit_archive), **asdict(policy)},
            indent=2,
        )
    )


@app.command("build-dataset")
def build_dataset(features: Path, labels: Path, config: Path | None = None) -> None:
    """Write deterministic JSONL, Parquet, and DuckDB dataset lineage."""
    settings = load_settings(config)
    feature_rows = read_features(features)
    label_rows = []
    for line in labels.read_text().splitlines():
        value = json.loads(line)
        label_rows.append(
            LabelOutcome(
                value["example_id"],
                value["status"],
                value.get("label_minutes"),
                datetime.fromisoformat(value["event_time"]) if value.get("event_time") else None,
                datetime.fromisoformat(value["available_at"]),
                value.get("source"),
                value.get("reason"),
            )
        )
    source_hashes: list[str] = []
    for manifest in (settings.data_dir / "raw" / "manifests").glob("*.jsonl"):
        source_hashes.extend(
            value["payload_sha256"]
            for value in (json.loads(line) for line in manifest.read_text().splitlines())
            if value.get("payload_sha256")
        )
    policy_path = settings.data_dir / "state" / "label-policy.json"
    policy_version = LabelPolicy.load(policy_path).version if policy_path.exists() else "missing"
    result = DatasetStore(settings.data_dir).write(
        feature_rows, label_rows, source_hashes, policy_version
    )
    typer.echo(json.dumps(asdict(result), indent=2))


@app.command("collection-report")
def report_collection(config: Path | None = None) -> None:
    settings = load_settings(config)
    manifests = list((settings.data_dir / "raw" / "manifests").glob("*.jsonl"))
    report = collection_report(manifests, settings.timezone)
    output = settings.report_dir / "collection.json"
    write_report(report, output)
    typer.echo(str(output))


@app.command("feed-audit")
def feed_audit(config: Path | None = None) -> None:
    """Report actual optional-field presence and freshness from archived live feeds."""
    settings = load_settings(config)
    feeds = archived_feeds((settings.data_dir / "raw" / "manifests").glob("*.jsonl"))
    features = _audit_features(settings)
    report = audit_feeds(feeds, features)
    output = settings.report_dir / "feed-audit.json"
    write_report(report, output)
    typer.echo(str(output))


def _audit_features(settings: Settings) -> list[FeatureRow]:
    features_path = settings.data_dir / "processed" / "features.jsonl"
    if not features_path.exists():
        features_path = settings.data_dir / "serving" / "latest_features.jsonl"
    return read_features(features_path) if features_path.exists() else []


@app.command("trip-timelines")
def trip_timelines(config: Path | None = None, limit: int = 10) -> None:
    """Retain route/day-balanced timeline samples for manual feed review."""
    settings = load_settings(config)
    samples = trip_timeline_samples(
        archived_feeds((settings.data_dir / "raw" / "manifests").glob("*.jsonl")),
        _audit_features(settings),
        limit,
    )
    output = settings.report_dir / "trip-timelines.json"
    write_report({"sample_count": len(samples), "samples": samples}, output)
    typer.echo(str(output))


@app.command("delayed-report")
def delayed_report(
    labels: Path, config: Path | None = None, predictions: Path | None = None
) -> None:
    """Idempotently attach matured labels to prediction logs."""
    settings = load_settings(config)
    source = predictions or settings.data_dir / "logs" / "predictions.jsonl"
    output = settings.data_dir / "monitoring" / "labelled_predictions.jsonl"
    counts = join_delayed_labels(source, labels, output)
    typer.echo(json.dumps({"output": str(output), **counts}, indent=2))


@app.command("prediction-report")
def report_predictions(config: Path | None = None) -> None:
    settings = load_settings(config)
    labelled = settings.data_dir / "monitoring" / "labelled_predictions.jsonl"
    source = labelled if labelled.exists() else settings.data_dir / "logs" / "predictions.jsonl"
    report = prediction_report(source, settings.data_dir / "logs" / "api_requests.jsonl")
    output = settings.report_dir / "predictions.json"
    write_report(report, output)
    typer.echo(str(output))


@app.command("evidence-report")
def evidence_report(config: Path | None = None) -> None:
    settings = load_settings(config)
    output = settings.report_dir / "portfolio-summary.md"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(build_portfolio_summary(settings.data_dir, settings.report_dir))
    typer.echo(str(output))


@app.command("train")
def train(dataset: Path, config: Path | None = None, strong_model: bool = False) -> None:
    """Train and compare a model against chronological baselines."""
    settings = load_settings(config)
    records = [json.loads(line) for line in dataset.read_text().splitlines() if line]
    collection_path = settings.report_dir / "collection.json"
    if not collection_path.exists():
        raise typer.BadParameter("collection report is required before locked evaluation")
    collection = json.loads(collection_path.read_text())
    today = datetime.now(UTC).astimezone(ZoneInfo(settings.timezone)).date().isoformat()
    usable_dates = {day for day in collection.get("usable_service_dates", []) if day < today}
    records = [row for row in records if str(row["key"]).split("|")[1] in usable_dates]
    labelled_dates = {
        str(row["key"]).split("|")[1]
        for row in records
        if isinstance(row.get("label"), dict) and row["label"].get("status") == "labelled"
    }
    if len(usable_dates & labelled_dates) < 28:
        raise typer.BadParameter(
            "locked evaluation requires 28 complete usable dataset service days"
        )
    missing_label_rate = (
        sum(
            not isinstance(row.get("label"), dict) or row["label"].get("status") != "labelled"
            for row in records
        )
        / len(records)
        if records
        else 1.0
    )
    records = [
        row
        for row in records
        if isinstance(row.get("label"), dict) and row["label"].get("status") == "labelled"
    ]
    rows = cast(
        list[Mapping[str, object]],
        [{key: value for key, value in row.items() if key != "label"} for row in records],
    )
    labels = [float(row["label"]["label_minutes"]) for row in records]
    train_i, validation_i, test_i = chronological_split(rows)
    if not all((train_i, validation_i, test_i)):
        raise typer.BadParameter("chronological split has an empty partition")
    training_rows = [rows[index] for index in train_i]
    training_labels = [labels[index] for index in train_i]
    validation_rows = [rows[index] for index in validation_i]
    validation_labels = [labels[index] for index in validation_i]
    test_rows = [rows[index] for index in test_i]
    test_labels = [labels[index] for index in test_i]
    candidate_models = [train_ridge(training_rows, training_labels)]
    if strong_model:
        candidate_models.append(train_lightgbm(training_rows, training_labels))
    validation_reports = [
        evaluate(model.name, validation_rows, validation_labels, model.predict(validation_rows))
        for model in candidate_models
    ]
    selected_index = min(
        range(len(candidate_models)), key=lambda index: validation_reports[index].overall.mae
    )
    selected_name = candidate_models[selected_index].name
    pretest_indexes = sorted(train_i + validation_i)
    pretest_rows = [rows[index] for index in pretest_indexes]
    pretest_labels = [labels[index] for index in pretest_indexes]
    model = (
        train_lightgbm(pretest_rows, pretest_labels)
        if selected_name.startswith("lightgbm")
        else train_ridge(pretest_rows, pretest_labels)
    )
    persistence = PersistenceBaseline()
    historical = HistoricalMedianBaseline().fit(pretest_rows, pretest_labels)
    persistence_predictions = persistence.predict(test_rows)
    model_predictions = model.predict(test_rows)
    reports = [
        evaluate("persistence", test_rows, test_labels, persistence_predictions),
        evaluate("historical", test_rows, test_labels, historical.predict(test_rows)),
        evaluate(model.name, test_rows, test_labels, model_predictions),
    ]
    promotion = promotion_decision(
        test_rows, test_labels, model_predictions, persistence_predictions
    )
    rolling_reports = []
    for fold, (fold_train, fold_test) in enumerate(rolling_origin_splits(pretest_rows), start=1):
        fold_train_rows = [pretest_rows[index] for index in fold_train]
        fold_train_labels = [pretest_labels[index] for index in fold_train]
        fold_test_rows = [pretest_rows[index] for index in fold_test]
        fold_test_labels = [pretest_labels[index] for index in fold_test]
        fold_model = (
            train_lightgbm(fold_train_rows, fold_train_labels)
            if selected_name.startswith("lightgbm")
            else train_ridge(fold_train_rows, fold_train_labels)
        )
        rolling_reports.append(
            {
                "fold": fold,
                "persistence": evaluate(
                    "persistence",
                    fold_test_rows,
                    fold_test_labels,
                    persistence.predict(fold_test_rows),
                ).to_dict(),
                "model": evaluate(
                    fold_model.name,
                    fold_test_rows,
                    fold_test_labels,
                    fold_model.predict(fold_test_rows),
                ).to_dict(),
            }
        )
    selected_validation_model = candidate_models[selected_index]
    validation_predictions = selected_validation_model.predict(validation_rows)
    interval = empirical_interval_report(
        validation_labels, validation_predictions, test_labels, model_predictions
    )
    split_dates = {
        name: sorted({str(rows[index]["key"]).split("|")[1] for index in indexes})
        for name, indexes in (("train", train_i), ("validation", validation_i), ("test", test_i))
    }
    git_sha = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    manifest_data = json.loads((dataset.parent / "manifest.json").read_text())
    artifact_store = ArtifactStore(settings.artifact_dir)
    manifest = artifact_store.save(
        model, manifest_data["dataset_version"], {"q05": interval["q05"], "q95": interval["q95"]}
    )
    output = settings.report_dir / "evaluation.json"
    write_report(
        {
            "artifact": asdict(manifest),
            "selection": {
                "selected_model": selected_name,
                "validation_reports": [report.to_dict() for report in validation_reports],
            },
            "reports": [report.to_dict() for report in reports],
            "rolling_backtests": rolling_reports,
            "split_dates": split_dates,
            "git_sha": git_sha,
            "missing_label_rate": missing_label_rate,
            "interval_90": interval,
            "promotion": asdict(promotion),
        },
        output,
    )
    typer.echo(json.dumps({"artifact": manifest.model_version, "report": str(output)}, indent=2))


@app.command("promote")
def promote(model_version: str, config: Path | None = None) -> None:
    settings = load_settings(config)
    report_path = settings.report_dir / "evaluation.json"
    if not report_path.exists():
        raise typer.BadParameter("evaluation report is required before promotion")
    report = json.loads(report_path.read_text())
    artifact = report.get("artifact", {})
    promotion = report.get("promotion", {})
    if artifact.get("model_version") != model_version:
        raise typer.BadParameter("model version does not match the evaluated artifact")
    if not promotion.get("approved"):
        reasons = ", ".join(promotion.get("reasons", [])) or "promotion gate failed"
        raise typer.BadParameter(f"candidate cannot be promoted: {reasons}")
    ArtifactStore(settings.artifact_dir).promote(model_version)
    typer.echo(model_version)


@app.command("serve")
def serve(config: Path | None = None, host: str = "0.0.0.0", port: int = 8000) -> None:
    import uvicorn

    from transit_delay.serving.api import create_app

    uvicorn.run(create_app(load_settings(config)), host=host, port=port)


@app.command("worker")
def worker(config: Path | None = None, once: bool = False, refresh_static: bool = False) -> None:
    """Refresh serving data, labels, datasets, and reports without external orchestration."""
    settings = load_settings(config)
    configure_logging(settings.log_level)
    service = Worker(settings)
    if once:
        service.run_once(update_static=refresh_static)
        return
    service.run_forever()


@app.command("seed-demo")
def seed_demo(config: Path = Path("configs/replay.yaml")) -> None:
    """Generate deterministic synthetic replay data; never use it as model evidence."""
    settings = load_settings(config)
    result = seed_synthetic_demo(settings.data_dir, settings.report_dir)
    typer.echo(json.dumps(result, indent=2))


if __name__ == "__main__":
    app()
