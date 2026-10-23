import json
import subprocess
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from typer.testing import CliRunner

from transit_delay.cli import app
from transit_delay.domain import FeatureRow, TripInstanceKey
from transit_delay.gtfs.realtime import ParsedFeed, RealtimeStopUpdate, RealtimeTripUpdate
from transit_delay.monitoring.audit import audit_feeds


def test_audit_candidate_must_arrive_within_30_minutes() -> None:
    target = datetime(2026, 8, 10, 18, 12, tzinfo=UTC)
    feature = FeatureRow(
        "e1",
        target - timedelta(minutes=12),
        TripInstanceKey("v1", date(2026, 8, 10), "t1"),
        3,
        "s3",
        target,
        720,
        "099",
        0,
        1,
        2,
        120,
        None,
        20,
        18,
        0,
        0,
    )
    stop = RealtimeStopUpdate(3, "s3", target, 120, None, None, "SCHEDULED")
    trip = RealtimeTripUpdate(
        "e",
        "t1",
        "r",
        0,
        "20260810",
        None,
        "SCHEDULED",
        None,
        target,
        None,
        (stop,),
    )
    within = target + timedelta(minutes=29)
    too_late = target + timedelta(minutes=31)
    feed = ParsedFeed(target, None, (trip,), ())
    assert audit_feeds([(feed, within)], [feature]).label_semantics["candidate_labels"] == 1
    assert audit_feeds([(feed, too_late)], [feature]).label_semantics["candidate_labels"] == 0


def test_locked_train_rejects_short_window(tmp_path) -> None:
    reports = tmp_path / "reports"
    reports.mkdir()
    (reports / "collection.json").write_text(json.dumps({"usable_service_dates": ["2026-08-10"]}))
    dataset = tmp_path / "rows.jsonl"
    dataset.write_text(json.dumps({"key": "v1|2026-08-10|t1|"}) + "\n")
    config = tmp_path / "config.yaml"
    config.write_text(f"report_dir: {reports}\n")
    result = CliRunner().invoke(app, ["train", str(dataset), "--config", str(config)])
    assert result.exit_code != 0
    assert "28 complete usable" in result.output


def test_git_excludes_secrets_raw_data_and_frontend_build() -> None:
    root = Path(__file__).resolve().parents[1]
    paths = [
        ".env",
        "data/evidence-2026-10-22/raw/feed.pb",
        "artifacts/model.pkl",
        "frontend/node_modules/package/index.js",
        "frontend/dist/index.html",
    ]
    assert all(
        subprocess.run(["git", "check-ignore", "--quiet", path], cwd=root, check=False).returncode
        == 0
        for path in paths
    )
