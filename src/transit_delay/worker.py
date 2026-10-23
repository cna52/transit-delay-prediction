from __future__ import annotations

import json
import os
import signal
import time
from collections import Counter
from collections.abc import Sequence
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from transit_delay.config import Settings
from transit_delay.datasets.labels import Labeler
from transit_delay.datasets.policy import LabelPolicy
from transit_delay.datasets.resolver import resolve_archived_labels
from transit_delay.datasets.store import DatasetStore
from transit_delay.domain import FeatureRow
from transit_delay.features.builder import FeatureBuilder
from transit_delay.gtfs.registry import StaticFeedRegistry
from transit_delay.gtfs.static import archive_static_zip
from transit_delay.monitoring.audit import archived_feeds, audit_feeds
from transit_delay.monitoring.delayed import join_delayed_labels
from transit_delay.monitoring.report import collection_report, prediction_report, write_report
from transit_delay.pipeline import ProcessingStats, process_manifest_with_registry
from transit_delay.runtime import write_state


def registry_for(settings: Settings) -> StaticFeedRegistry:
    return StaticFeedRegistry(
        settings.data_dir / "processed" / "static" / "registry.json", settings.timezone
    )


def bootstrap_registry(settings: Settings) -> StaticFeedRegistry:
    registry = registry_for(settings)
    known_paths = {Path(record.archive_path).resolve() for record in registry.records()}
    for archive in sorted((settings.data_dir / "raw" / "static").glob("*.zip")):
        if archive.resolve() not in known_paths:
            registry.register(archive, datetime.fromtimestamp(archive.stat().st_mtime, UTC))
    return registry


def refresh_static(settings: Settings) -> Path:
    import httpx

    response = httpx.get(settings.static_url, timeout=60, follow_redirects=True)
    response.raise_for_status()
    archive = archive_static_zip(response.content, settings.data_dir)
    registry = registry_for(settings)
    record = registry.register(archive)
    catalog = registry.catalog(record)
    profile = settings.data_dir / "processed" / "static" / catalog.version / "profile.json"
    catalog.write_profile(profile)
    return archive


def _manifests(settings: Settings, recent: bool = False) -> list[Path]:
    paths = sorted((settings.data_dir / "raw" / "manifests").glob("*.jsonl"))
    return paths[-2:] if recent else paths


def _write_features(path: Path, rows: Sequence[FeatureRow]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        "\n".join(json.dumps(row.to_dict(), default=str) for row in rows) + ("\n" if rows else "")
    )
    os.replace(temporary, path)


def build_features(settings: Settings, *, recent: bool) -> tuple[Path, ProcessingStats]:
    registry = bootstrap_registry(settings)
    if not registry.records():
        raise RuntimeError("no registered Static GTFS feed; run download-static first")
    rows, stats = process_manifest_with_registry(
        _manifests(settings, recent),
        registry,
        set(settings.selected_routes),
        FeatureBuilder(
            settings.target_horizon_min_seconds,
            settings.target_horizon_max_seconds,
            settings.example_cooldown_seconds,
            settings.timezone,
        ),
    )
    output = (
        settings.data_dir / "serving" / "latest_features.jsonl"
        if recent
        else settings.data_dir / "processed" / "features.jsonl"
    )
    _write_features(output, rows)
    return output, stats


def build_labels_and_dataset(settings: Settings, features_path: Path) -> dict[str, object]:
    from transit_delay.datasets.resolver import read_features

    policy_path = settings.data_dir / "state" / "label-policy.json"
    if not policy_path.exists():
        return {"status": "label_policy_pending"}
    policy = LabelPolicy.load(policy_path)
    rows = read_features(features_path)
    manifests = _manifests(settings)
    outcomes = resolve_archived_labels(
        rows, manifests, Labeler(policy), settings.label_wait_seconds
    )
    labels_path = settings.data_dir / "processed" / "labels.jsonl"
    labels_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = labels_path.with_suffix(".tmp")
    temporary.write_text(
        "\n".join(json.dumps(asdict(value), default=str) for value in outcomes)
        + ("\n" if outcomes else "")
    )
    os.replace(temporary, labels_path)
    source_hashes: list[str] = []
    for manifest in manifests:
        source_hashes.extend(
            value["payload_sha256"]
            for value in (json.loads(line) for line in manifest.read_text().splitlines())
            if value.get("payload_sha256")
        )
    dataset = DatasetStore(settings.data_dir).write(rows, outcomes, source_hashes, policy.version)
    prediction_log = settings.data_dir / "logs" / "predictions.jsonl"
    if prediction_log.exists():
        labelled_predictions = settings.data_dir / "monitoring" / "labelled_predictions.jsonl"
        join_delayed_labels(prediction_log, labels_path, labelled_predictions)
        write_report(
            prediction_report(
                labelled_predictions, settings.data_dir / "logs" / "api_requests.jsonl"
            ),
            settings.report_dir / "predictions.json",
        )
    return {
        "status": "complete",
        "label_counts": dict(Counter(row.status for row in outcomes)),
        "dataset_version": dataset.dataset_version,
        "labelled_count": dataset.labelled_count,
    }


def write_dataset_quality(
    settings: Settings, features_path: Path, stats: ProcessingStats
) -> dict[str, object]:
    from transit_delay.datasets.resolver import read_features

    rows = read_features(features_path)
    labels_path = settings.data_dir / "processed" / "labels.jsonl"
    label_counts: Counter[str] = Counter()
    policy_path = settings.data_dir / "state" / "label-policy.json"
    if not policy_path.exists():
        label_counts["label_policy_pending"] = len(rows)
    elif labels_path.exists():
        label_counts.update(
            str(json.loads(line).get("status"))
            for line in labels_path.read_text().splitlines()
            if line
        )
    service_dates = sorted({row.key.service_date.isoformat() for row in rows})
    raw_files = list((settings.data_dir / "raw").glob("**/*.gz"))
    raw_bytes = sum(path.stat().st_size for path in raw_files)
    manifest_days = len(_manifests(settings))
    report: dict[str, object] = {
        "generated_at": datetime.now(UTC).isoformat(),
        "processing": asdict(stats),
        "strict_join_success_rate": (
            stats.joined / (stats.joined + stats.join_failures)
            if stats.joined + stats.join_failures
            else None
        ),
        "feature_rows": len(rows),
        "unique_trip_instances": len({row.key.stable_id() for row in rows}),
        "service_date_from": service_dates[0] if service_dates else None,
        "service_date_to": service_dates[-1] if service_dates else None,
        "service_days": len(service_dates),
        "routes": dict(Counter(row.route_short_name for row in rows)),
        "hours_vancouver": dict(Counter(f"{row.hour:02d}:00" for row in rows)),
        "horizons": dict(
            Counter("10-12m" if row.horizon_seconds <= 720 else "12-15m" for row in rows)
        ),
        "label_statuses": dict(label_counts),
        "static_versions": sorted({row.key.static_version for row in rows}),
        "raw_storage_bytes": raw_bytes,
        "average_raw_bytes_per_manifest_day": raw_bytes / manifest_days if manifest_days else None,
    }
    write_report(report, settings.report_dir / "dataset-quality.json")
    return report


def refresh_reports(settings: Settings) -> dict[str, object]:
    manifests = _manifests(settings)
    if not manifests:
        return {"status": "no_manifests"}
    collection = collection_report(manifests, settings.timezone)
    write_report(collection, settings.report_dir / "collection.json")
    features_path = settings.data_dir / "processed" / "features.jsonl"
    features = []
    if features_path.exists():
        from transit_delay.datasets.resolver import read_features

        features = read_features(features_path)
    audit = audit_feeds(archived_feeds(manifests), features)
    write_report(audit, settings.report_dir / "feed-audit.json")
    return {"status": "complete", "collection": asdict(collection), "audit": asdict(audit)}


class Worker:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.running = True
        self.state_path = settings.data_dir / "state" / "worker.json"

    def stop(self, *_args: object) -> None:
        self.running = False

    def run_once(self, *, include_offline: bool = True, update_static: bool = False) -> None:
        started = datetime.now(UTC)
        write_state(self.state_path, status="running", last_started_at=started.isoformat())
        try:
            static_path = str(refresh_static(self.settings)) if update_static else None
            serving_path, serving_stats = build_features(self.settings, recent=True)
            result: dict[str, object] = {
                "serving_snapshot": str(serving_path),
                "serving_stats": asdict(serving_stats),
            }
            if include_offline:
                features_path, offline_stats = build_features(self.settings, recent=False)
                result["offline_stats"] = asdict(offline_stats)
                result["dataset"] = build_labels_and_dataset(self.settings, features_path)
                result["dataset_quality"] = write_dataset_quality(
                    self.settings, features_path, offline_stats
                )
                result["reports"] = refresh_reports(self.settings)
            write_state(
                self.state_path,
                status="healthy",
                last_success_at=datetime.now(UTC).isoformat(),
                last_error=None,
                static_archive=static_path,
                **result,
            )
        except Exception as exc:
            write_state(
                self.state_path,
                status="error",
                last_error=f"{type(exc).__name__}: {exc}",
                last_failure_at=datetime.now(UTC).isoformat(),
            )
            raise

    def run_forever(self) -> None:
        signal.signal(signal.SIGTERM, self.stop)
        signal.signal(signal.SIGINT, self.stop)
        next_serving = next_reports = next_offline = next_static = 0.0
        while self.running:
            now = time.monotonic()
            try:
                if now >= next_static:
                    refresh_static(self.settings)
                    next_static = now + self.settings.static_refresh_interval_seconds
                if now >= next_serving:
                    path, stats = build_features(self.settings, recent=True)
                    write_state(
                        self.state_path,
                        status="healthy",
                        last_serving_refresh_at=datetime.now(UTC).isoformat(),
                        serving_snapshot=str(path),
                        serving_stats=asdict(stats),
                        last_error=None,
                    )
                    next_serving = now + self.settings.serving_refresh_interval_seconds
                if now >= next_reports:
                    refresh_reports(self.settings)
                    next_reports = now + self.settings.reporting_interval_seconds
                if now >= next_offline:
                    features, stats = build_features(self.settings, recent=False)
                    dataset = build_labels_and_dataset(self.settings, features)
                    quality = write_dataset_quality(self.settings, features, stats)
                    write_state(
                        self.state_path,
                        status="healthy",
                        last_offline_rebuild_at=datetime.now(UTC).isoformat(),
                        offline_stats=asdict(stats),
                        dataset=dataset,
                        dataset_quality=quality,
                    )
                    next_offline = now + self.settings.offline_rebuild_interval_seconds
            except Exception as exc:
                write_state(
                    self.state_path,
                    status="error",
                    last_error=f"{type(exc).__name__}: {exc}",
                    last_failure_at=datetime.now(UTC).isoformat(),
                )
            time.sleep(1)
