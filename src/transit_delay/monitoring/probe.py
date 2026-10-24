from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx

from transit_delay.config import Settings
from transit_delay.serving.log import PredictionLogger


@dataclass(frozen=True)
class ProbeResult:
    routes_checked: int
    predictions: int
    stale_or_missing: int
    duplicates: int
    errors: int


def probe_once(settings: Settings, client: httpx.Client) -> ProbeResult:
    """Request one fresh, new prediction per route through the live API."""
    state_path = settings.data_dir / "state" / "serving-probe.json"
    try:
        state = json.loads(state_path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        state = {}
    last_ids = dict(state.get("last_example_by_route", {}))
    log = PredictionLogger(settings.data_dir / "logs" / "probe_attempts.jsonl")
    predictions = stale_or_missing = duplicates = errors = 0
    for route in settings.selected_routes:
        attempt: dict[str, Any] = {
            "at": datetime.now(UTC).isoformat(),
            "route": route,
            "status": "error",
        }
        try:
            response = client.get("/v1/observations", params={"route": route, "limit": 100})
            response.raise_for_status()
            items = response.json()["items"]
            fresh = [
                item
                for item in items
                if item.get("freshness_seconds") is not None
                and float(item["freshness_seconds"]) <= settings.max_feature_age_seconds
            ]
            if not fresh:
                stale_or_missing += 1
                attempt["status"] = "stale_or_missing"
                continue
            item = fresh[0]
            example_id = str(item["example_id"])
            attempt["example_id"] = example_id
            if last_ids.get(route) == example_id:
                duplicates += 1
                attempt["status"] = "duplicate"
                continue
            request = {
                "trip_id": item["trip_id"],
                "service_date": item["service_date"],
                "start_time": item.get("start_time"),
                "target_stop_id": item["target_stop_id"],
                "as_of": item["as_of"],
            }
            result = client.post("/v1/predictions", json=request)
            result.raise_for_status()
            body = result.json()
            if body.get("example_id") != example_id:
                raise ValueError("prediction resolved a different point-in-time example")
            predictions += 1
            last_ids[route] = example_id
            attempt["status"] = "predicted"
            attempt["prediction_id"] = body.get("prediction_id")
        except (httpx.HTTPError, KeyError, ValueError, TypeError) as exc:
            errors += 1
            attempt["error"] = f"{type(exc).__name__}: {exc}"
        finally:
            log.append(attempt)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = state_path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(
            {"last_example_by_route": last_ids, "updated_at": datetime.now(UTC).isoformat()},
            indent=2,
            sort_keys=True,
        )
    )
    temporary.replace(state_path)
    return ProbeResult(
        len(settings.selected_routes), predictions, stale_or_missing, duplicates, errors
    )
