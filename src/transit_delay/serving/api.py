from __future__ import annotations

import json
import time
from collections.abc import Awaitable, Callable
from dataclasses import asdict
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Query, Request, Response
from pydantic import BaseModel, ConfigDict

from transit_delay.config import Settings
from transit_delay.models.artifacts import ArtifactStore
from transit_delay.monitoring.report import prediction_report
from transit_delay.runtime import read_state
from transit_delay.serving.log import PredictionLogger
from transit_delay.serving.predictor import Predictor
from transit_delay.serving.snapshot import SnapshotStore


class PredictionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    trip_id: str
    service_date: date
    start_time: str | None = None
    target_stop_id: str | None = None
    as_of: datetime | None = None


def _read_json(path: Path) -> dict[str, object] | None:
    try:
        value = json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    return value if isinstance(value, dict) else None


def _observation(row: dict[str, object], data_mode: str = "live") -> dict[str, object]:
    key_parts = str(row.get("key", "")).split("|")
    horizon_seconds = int(str(row.get("horizon_seconds", 0)))
    current_delay_seconds = int(str(row.get("current_delay_seconds", 0)))
    delay_trend = row.get("delay_trend_seconds")
    observed_at = datetime.fromisoformat(str(row.get("as_of")))
    if observed_at.tzinfo is None:
        observed_at = observed_at.replace(tzinfo=UTC)
    wall_age_seconds = (
        max(0, int((datetime.now(UTC) - observed_at).total_seconds()))
        if data_mode == "live"
        else 0
    )
    freshness_seconds = max(int(str(row.get("source_age_seconds", 0))), wall_age_seconds)
    return {
        "example_id": row.get("example_id"),
        "trip_id": key_parts[2] if len(key_parts) > 2 else None,
        "service_date": key_parts[1] if len(key_parts) > 1 else None,
        "start_time": key_parts[3] if len(key_parts) > 3 and key_parts[3] else None,
        "route": row.get("route_short_name"),
        "direction_id": row.get("direction_id"),
        "target_stop_id": row.get("target_stop_id"),
        "target_stop_name": row.get("target_stop_name"),
        "trip_headsign": row.get("trip_headsign"),
        "target_stop_sequence": row.get("target_stop_sequence"),
        "current_stop_sequence": row.get("current_stop_sequence"),
        "stops_to_target": row.get("stops_to_target"),
        "scheduled_target_arrival": row.get("scheduled_target_arrival"),
        "as_of": row.get("as_of"),
        "current_delay_minutes": round(current_delay_seconds / 60, 1),
        "horizon_minutes": round(horizon_seconds / 60, 1),
        "freshness_seconds": freshness_seconds,
        "delay_trend_minutes": (
            round(int(str(delay_trend)) / 60, 1) if delay_trend is not None else None
        ),
    }


def create_app(settings: Settings, snapshot_path: Path | None = None) -> Any:
    path = snapshot_path or settings.data_dir / "serving" / "latest_features.jsonl"
    snapshots = SnapshotStore(path)
    artifact_store = ArtifactStore(settings.artifact_dir)
    model = manifest = None
    load_error = None
    try:
        model, manifest = artifact_store.load_champion()
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        load_error = str(exc)
    predictor = Predictor(model, manifest, settings.max_feature_age_seconds)
    prediction_logger = PredictionLogger(settings.data_dir / "logs" / "predictions.jsonl")
    request_logger = PredictionLogger(settings.data_dir / "logs" / "api_requests.jsonl")
    app = FastAPI(title="TransLink Delay Prediction", version="1.0.0")

    @app.middleware("http")
    async def request_telemetry(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        started = time.perf_counter()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        finally:
            if request.url.path == "/v1/predictions":
                request_logger.append(
                    {
                        "request_id": request.headers.get("x-request-id", uuid4().hex),
                        "requested_at": datetime.now(UTC).isoformat(),
                        "path": request.url.path,
                        "status_code": status_code,
                        "latency_ms": round((time.perf_counter() - started) * 1000, 3),
                        "data_mode": settings.data_mode,
                    }
                )

    @app.get("/healthz")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz")
    def ready() -> dict[str, object]:
        if not path.exists():
            raise HTTPException(status_code=503, detail="feature snapshot unavailable")
        return {"status": "ready", "model_loaded": model is not None, "model_error": load_error}

    @app.get("/v1/model")
    def model_info() -> dict[str, object]:
        return {
            "model_version": manifest.model_version if manifest else "persistence-v1",
            "feature_schema_version": manifest.feature_schema_version if manifest else "v1",
            "supported_routes": list(settings.selected_routes),
            "training_dataset": manifest.dataset_version if manifest else None,
        }

    @app.get("/v1/observations")
    def observations(
        route: str | None = None,
        limit: int = Query(default=100, ge=1, le=500),
    ) -> dict[str, object]:
        if not path.exists():
            return {"items": [], "count": 0, "generated_at": datetime.now(UTC)}
        rows = snapshots.all()
        if route:
            rows = [row for row in rows if str(row.get("route_short_name")) == route]
        rows.sort(key=lambda row: str(row.get("as_of", "")), reverse=True)
        items = [_observation(row, settings.data_mode) for row in rows[:limit]]
        return {"items": items, "count": len(items), "generated_at": datetime.now(UTC)}

    @app.get("/v1/observations/{example_id}")
    def observation(example_id: str) -> dict[str, object]:
        if not path.exists():
            raise HTTPException(status_code=404, detail="feature snapshot unavailable")
        row = snapshots.get(example_id)
        if row is None:
            raise HTTPException(status_code=404, detail="observation not found")
        return _observation(dict(row), settings.data_mode)

    @app.post("/v1/predictions")
    def predict(request: PredictionRequest) -> dict[str, object]:
        row = snapshots.find(
            request.trip_id,
            request.service_date.isoformat(),
            request.start_time,
            request.target_stop_id,
            request.as_of,
        )
        if row is None:
            raise HTTPException(
                status_code=404, detail="supported point-in-time observation not found"
            )
        reference_now = (
            datetime.fromisoformat(str(row["as_of"]))
            if settings.data_mode in {"replay", "synthetic"}
            else None
        )
        result = predictor.predict(row, now=reference_now)
        response = {
            "prediction_id": uuid4().hex,
            "example_id": row["example_id"],
            "trip_instance": row["key"],
            "target_stop_id": row["target_stop_id"],
            "data_mode": settings.data_mode,
            **asdict(result),
        }
        prediction_logger.append(response)
        return response

    @app.get("/v1/metrics/collection")
    def collection_metrics() -> dict[str, object]:
        report = _read_json(settings.report_dir / "collection.json")
        if report is None:
            return {
                "status": "pending",
                "message": "Run collection-report after collecting realtime snapshots.",
            }
        return {"status": "available", **report}

    @app.get("/v1/metrics/evaluation")
    def evaluation_metrics() -> dict[str, object]:
        report = _read_json(settings.report_dir / "evaluation.json")
        if report is None:
            return {
                "status": "pending",
                "message": "Evaluation appears after audited labels and chronological training.",
            }
        return {"status": "available", **report}

    @app.get("/v1/metrics/predictions")
    def prediction_metrics() -> dict[str, object]:
        labelled = settings.data_dir / "monitoring" / "labelled_predictions.jsonl"
        source = labelled if labelled.exists() else settings.data_dir / "logs" / "predictions.jsonl"
        report = prediction_report(
            source, settings.data_dir / "logs" / "api_requests.jsonl"
        )
        return {"status": "available" if report["requests"] else "pending", **report}

    @app.get("/v1/system")
    def system_info() -> dict[str, object]:
        rows = snapshots.all() if path.exists() else []
        row_count = len(rows)
        collector = read_state(settings.data_dir / "state" / "collector.json")
        worker = read_state(settings.data_dir / "state" / "worker.json")
        snapshot_time = max(
            (datetime.fromisoformat(str(row["as_of"])) for row in rows), default=None
        )
        snapshot_age = (
            max(0, int((datetime.now(UTC) - snapshot_time).total_seconds()))
            if snapshot_time is not None
            else None
        )
        if settings.data_mode != "live":
            data_status = settings.data_mode
        elif snapshot_age is None:
            data_status = "missing"
        elif snapshot_age > settings.max_feature_age_seconds:
            data_status = "stale"
        else:
            data_status = "live"
        collector_status = str(collector.get("status", "missing")) if collector else "missing"
        worker_status = str(worker.get("status", "missing")) if worker else "missing"
        overall = (
            "ready"
            if data_status in {"live", "replay", "synthetic"}
            and (settings.data_mode != "live" or collector_status == "healthy")
            else "degraded"
        )
        return {
            "status": overall,
            "api_status": "healthy",
            "collector_status": collector_status,
            "worker_status": worker_status,
            "data_status": data_status,
            "data_mode": settings.data_mode,
            "snapshot_age_seconds": snapshot_age,
            "latest_observation_at": snapshot_time,
            "snapshot_available": path.exists(),
            "observation_count": row_count,
            "model_loaded": model is not None,
            "model_error": load_error,
            "model_version": manifest.model_version if manifest else "persistence-v1",
            "selected_routes": list(settings.selected_routes),
            "collection": _read_json(settings.report_dir / "collection.json"),
            "feed_audit": _read_json(settings.report_dir / "feed-audit.json"),
            "collector": collector,
            "worker": worker,
            "checked_at": datetime.now(UTC),
        }

    return app
