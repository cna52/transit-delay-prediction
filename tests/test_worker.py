import json
from datetime import UTC, datetime, timedelta

from tests.helpers import write_static_fixture
from tests.test_integration import realtime_payload
from transit_delay.config import Settings
from transit_delay.datasets.resolver import read_features
from transit_delay.gtfs.realtime import parse_feed
from transit_delay.gtfs.registry import StaticFeedRegistry
from transit_delay.ingestion.archive import ImmutableArchive
from transit_delay.monitoring.audit import audit_feeds
from transit_delay.monitoring.evidence import build_portfolio_summary
from transit_delay.worker import Worker, refresh_reports


def test_worker_builds_atomic_snapshot_heartbeat_and_reports(tmp_path) -> None:
    data = tmp_path / "data"
    reports = tmp_path / "reports"
    static = data / "raw/static/static.zip"
    static.parent.mkdir(parents=True)
    write_static_fixture(static)
    received = datetime(2026, 8, 11, 7, 2, tzinfo=UTC)
    registry = StaticFeedRegistry(data / "processed/static/registry.json")
    registry.register(static, received - timedelta(days=1))
    ImmutableArchive(data).store("trip_updates", realtime_payload(), received, received, 200, 5)
    settings = Settings(
        data_dir=data,
        artifact_dir=tmp_path / "artifacts",
        report_dir=reports,
        selected_routes=("099",),
    )

    Worker(settings).run_once(include_offline=False)
    snapshot = data / "serving/latest_features.jsonl"
    assert snapshot.exists()
    state = json.loads((data / "state/worker.json").read_text())
    assert state["status"] == "healthy"
    report = refresh_reports(settings)
    assert report["status"] == "complete"

    features = read_features(snapshot)
    audit = audit_feeds([(parse_feed(realtime_payload()), received)], features)
    assert audit.label_semantics is not None
    assert audit.label_semantics["examples_checked"] == 0
    assert audit.label_semantics["pending_examples"] == 1
    summary = build_portfolio_summary(data, reports)
    assert "Attempts / successes" in summary
    assert "no immutable dataset" in summary
