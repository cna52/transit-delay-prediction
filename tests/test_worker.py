import json
from datetime import UTC, datetime, timedelta

from typer.testing import CliRunner

from tests.helpers import write_static_fixture
from tests.test_integration import realtime_payload
from transit_delay.cli import app
from transit_delay.config import Settings
from transit_delay.datasets.resolver import read_features
from transit_delay.gtfs.realtime import parse_feed
from transit_delay.gtfs.registry import StaticFeedRegistry
from transit_delay.ingestion.archive import ImmutableArchive
from transit_delay.monitoring.audit import audit_feeds
from transit_delay.monitoring.evidence import build_portfolio_summary
from transit_delay.worker import (
    Worker,
    build_features,
    offline_rebuild_due,
    refresh_reports,
    write_trip_review_packet,
)


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
    packet = write_trip_review_packet(
        settings,
        list((data / "raw/manifests").glob("*.jsonl")),
        features,
        {"audited_complete_dates": ["2026-08-10", "2026-08-11"]},
    )
    assert packet is not None
    packet_value = json.loads(packet.read_text())
    assert len(packet_value["audit_sha256"]) == 64
    assert packet_value["complete_usable_dates"] == ["2026-08-10", "2026-08-11"]
    assert (reports / "label-audits" / f"{packet_value['audit_sha256']}.json").exists()
    packet_bytes = packet.read_bytes()
    assert (
        write_trip_review_packet(
            settings,
            list((data / "raw/manifests").glob("*.jsonl")),
            features,
            {"audited_complete_dates": ["2026-08-10", "2026-08-11"]},
        )
        == packet
    )
    assert packet.read_bytes() == packet_bytes
    summary = build_portfolio_summary(data, reports)
    assert "Attempts / successes" in summary
    assert "no immutable dataset" in summary

    config = tmp_path / "scope.yaml"
    config.write_text(f"data_dir: {data}\nreport_dir: {reports}\nselected_routes: ['099']\n")
    scoped = CliRunner().invoke(app, ["route-scope-report", "099", "--config", str(config)])
    assert scoped.exit_code == 0, scoped.output
    scoped_report = json.loads((reports / "route-scopes/099.json").read_text())
    assert scoped_report["routes"] == ["099"]
    assert scoped_report["processing"]["joined"] >= 1
    short = CliRunner().invoke(
        app,
        [
            "route-scope-report",
            "099",
            "--config",
            str(config),
            "--min-horizon-seconds",
            "300",
            "--max-horizon-seconds",
            "600",
        ],
    )
    assert short.exit_code == 0, short.output
    short_report = json.loads((reports / "route-scopes/099-h300-600.json").read_text())
    assert short_report["horizon_seconds"] == {"minimum": 300, "maximum": 600}
    assert json.loads((reports / "route-scopes/099.json").read_text()) == scoped_report
    invalid = CliRunner().invoke(
        app,
        [
            "route-scope-report",
            "099",
            "--config",
            str(config),
            "--min-horizon-seconds",
            "600",
            "--max-horizon-seconds",
            "300",
        ],
    )
    assert invalid.exit_code != 0


def test_serving_replays_only_the_recent_window(tmp_path) -> None:
    data = tmp_path / "data"
    static = data / "raw/static/static.zip"
    static.parent.mkdir(parents=True)
    write_static_fixture(static)
    received = datetime(2026, 8, 11, 7, 2, tzinfo=UTC)
    StaticFeedRegistry(data / "processed/static/registry.json").register(
        static, received - timedelta(days=1)
    )
    archive = ImmutableArchive(data)
    for at in (received, received + timedelta(hours=2)):
        archive.store("trip_updates", realtime_payload(), at, at, 200, 5)
    settings = Settings(data_dir=data, selected_routes=("099",), serving_window_seconds=3600)
    _, recent = build_features(settings, recent=True)
    _, offline = build_features(settings, recent=False)
    assert recent.snapshots == 1
    assert offline.snapshots == 2


def test_offline_rebuild_runs_at_local_day_rollover() -> None:
    from datetime import date

    assert offline_rebuild_due(20, 100, date(2026, 10, 22), date(2026, 10, 23))
    assert not offline_rebuild_due(20, 100, date(2026, 10, 23), date(2026, 10, 23))
    assert offline_rebuild_due(101, 100, date(2026, 10, 23), date(2026, 10, 23))
