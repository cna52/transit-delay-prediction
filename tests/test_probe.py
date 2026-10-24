import json

import httpx

from transit_delay.config import Settings
from transit_delay.monitoring.probe import probe_once


def test_probe_requests_fresh_example_once_per_route(tmp_path) -> None:
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "example_id": "e1",
                            "trip_id": "t1",
                            "service_date": "2026-10-22",
                            "start_time": None,
                            "target_stop_id": "s1",
                            "as_of": "2026-10-23T06:00:00+00:00",
                            "freshness_seconds": 20,
                        }
                    ]
                },
            )
        assert json.loads(request.content)["target_stop_id"] == "s1"
        return httpx.Response(200, json={"example_id": "e1", "prediction_id": "p1"})

    settings = Settings(data_dir=tmp_path, selected_routes=("099",))
    with httpx.Client(transport=httpx.MockTransport(handler), base_url="http://api") as client:
        first = probe_once(settings, client)
        second = probe_once(settings, client)
    assert first.predictions == 1
    assert second.predictions == 0
    assert second.duplicates == 1
    assert len([request for request in requests if request.method == "POST"]) == 1
    attempts = (tmp_path / "logs/probe_attempts.jsonl").read_text().splitlines()
    assert [json.loads(line)["status"] for line in attempts] == ["predicted", "duplicate"]
