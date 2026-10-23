import json

from transit_delay.ingestion.archive import ImmutableArchive
from transit_delay.ingestion.client import Endpoint, FeedClient
from transit_delay.ingestion.collector import Collector, ScheduledEndpoint
from transit_delay.ingestion.quota import DailyQuota


def test_collector_stops_and_records_auth_heartbeat_on_401(tmp_path, monkeypatch) -> None:
    client = FeedClient(
        "secret",
        ImmutableArchive(tmp_path),
        DailyQuota(tmp_path / "state/quota.json", 5, "America/Vancouver"),
        transport=lambda _url, _params, _timeout: (401, b"unauthorized"),
    )
    state = tmp_path / "state/collector.json"
    collector = Collector(
        client,
        [ScheduledEndpoint(Endpoint("trip_updates", "https://example.invalid"), 100)],
        state,
    )
    monkeypatch.setattr("transit_delay.ingestion.collector.time.sleep", lambda _seconds: None)

    collector.run_forever()

    assert collector.running is False
    heartbeat = json.loads(state.read_text())
    assert heartbeat["status"] == "auth_error"
    manifest = next((tmp_path / "raw/manifests").glob("*.jsonl"))
    record = json.loads(manifest.read_text())
    assert record["status_code"] == 401
    assert record["payload_path"] is None
