import json
from datetime import UTC, datetime

from fastapi.testclient import TestClient

from transit_delay.config import Settings
from transit_delay.serving.api import create_app


def test_api_serves_explicit_persistence_fallback(tmp_path) -> None:
    snapshot = tmp_path / "features.jsonl"
    as_of = datetime(2026, 8, 10, 18, 0, tzinfo=UTC)
    row = {
        "example_id": "example-1",
        "key": "v1|2026-08-10|trip-1|",
        "as_of": as_of.isoformat(),
        "target_stop_id": "s3",
        "target_stop_name": "Broadway at Cambie Street",
        "trip_headsign": "UBC",
        "feature_schema_version": "v1",
        "current_delay_seconds": 120,
        "source_age_seconds": 10,
    }
    snapshot.write_text(json.dumps(row) + "\n")
    settings = Settings(data_dir=tmp_path, artifact_dir=tmp_path / "artifacts")
    client = TestClient(create_app(settings, snapshot))
    assert client.get("/healthz").status_code == 200
    response = client.post(
        "/v1/predictions",
        json={
            "trip_id": "trip-1",
            "service_date": "2026-08-10",
            "as_of": as_of.isoformat(),
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["prediction_minutes"] == 2.0
    assert body["quality"] == "fallback"
    assert body["fallback_reason"] == "no_promoted_model"
    assert body["data_mode"] == "live"
    assert (tmp_path / "logs/predictions.jsonl").exists()
    metrics = client.get("/v1/metrics/predictions").json()
    assert metrics["requests"] == 1
    assert metrics["latency_ms"]["p95"] is not None


def test_api_exposes_frontend_observation_and_operational_contracts(tmp_path) -> None:
    snapshot = tmp_path / "features.jsonl"
    report_dir = tmp_path / "reports"
    report_dir.mkdir()
    as_of = datetime(2026, 8, 10, 18, 0, tzinfo=UTC)
    row = {
        "example_id": "example-1",
        "key": "v1|2026-08-10|trip-1|",
        "as_of": as_of.isoformat(),
        "route_short_name": "R4",
        "direction_id": 1,
        "target_stop_id": "s3",
        "target_stop_sequence": 14,
        "target_stop_name": "Broadway at Cambie Street",
        "trip_headsign": "UBC",
        "current_stop_sequence": 8,
        "stops_to_target": 6,
        "scheduled_target_arrival": as_of.isoformat(),
        "horizon_seconds": 720,
        "feature_schema_version": "v1",
        "current_delay_seconds": 120,
        "delay_trend_seconds": 30,
        "source_age_seconds": 10,
    }
    snapshot.write_text(json.dumps(row) + "\n")
    (report_dir / "collection.json").write_text(
        json.dumps({"attempts": 10, "successes": 9, "success_rate": 0.9})
    )
    settings = Settings(
        data_dir=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        report_dir=report_dir,
    )
    client = TestClient(create_app(settings, snapshot))

    observations = client.get("/v1/observations?route=R4").json()
    assert observations["count"] == 1
    assert observations["items"][0]["current_delay_minutes"] == 2.0
    assert observations["items"][0]["horizon_minutes"] == 12.0
    assert observations["items"][0]["target_stop_name"] == "Broadway at Cambie Street"
    assert observations["items"][0]["trip_headsign"] == "UBC"
    assert client.get("/v1/observations/example-1").status_code == 200
    assert client.get("/v1/observations/missing").status_code == 404
    assert client.get("/v1/metrics/collection").json()["status"] == "available"
    assert client.get("/v1/metrics/evaluation").json()["status"] == "pending"
    system = client.get("/v1/system").json()
    assert system["observation_count"] == 1
    assert system["api_status"] == "healthy"
    assert system["data_status"] == "stale"


def test_api_serves_built_frontend_when_present(tmp_path) -> None:
    frontend = tmp_path / "frontend"
    (frontend / "assets").mkdir(parents=True)
    (frontend / "index.html").write_text("<!doctype html><title>OnTime</title>")
    (frontend / "assets" / "app.js").write_text("console.log('ok')")
    settings = Settings(
        data_dir=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        frontend_dir=frontend,
    )
    client = TestClient(create_app(settings, tmp_path / "missing.jsonl"))

    assert "OnTime" in client.get("/").text
    assert client.get("/assets/app.js").status_code == 200
