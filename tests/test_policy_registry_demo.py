import hashlib
import json
from datetime import UTC, date, datetime, timedelta

import pytest
from typer.testing import CliRunner

from tests.helpers import write_static_fixture
from tests.test_integration import realtime_payload
from transit_delay.cli import app
from transit_delay.datasets.policy import LabelPolicy
from transit_delay.demo import seed_synthetic_demo
from transit_delay.features.builder import FeatureBuilder
from transit_delay.gtfs.realtime import parse_feed
from transit_delay.gtfs.registry import StaticFeedRegistry
from transit_delay.monitoring.evidence import build_portfolio_summary
from transit_delay.pipeline import RegistrySnapshotProcessor


def test_policy_is_bound_to_exact_audit(tmp_path) -> None:
    audit = tmp_path / "audit.json"
    audit.write_text(json.dumps({"candidate_coverage": 0.8}))
    policy = LabelPolicy.from_audit(audit)
    policy.verify_audit(audit)
    assert policy.audit_sha256 == hashlib.sha256(audit.read_bytes()).hexdigest()
    audit.write_text("{}")
    with pytest.raises(RuntimeError, match="checksum"):
        policy.verify_audit(audit)


def test_static_registry_selects_only_feed_available_at_as_of(tmp_path) -> None:
    archive = tmp_path / "static.zip"
    write_static_fixture(archive)
    registry = StaticFeedRegistry(tmp_path / "registry.json")
    retrieved = datetime(2026, 1, 2, tzinfo=UTC)
    record = registry.register(archive, retrieved)
    selected = registry.select(date(2026, 8, 10), retrieved + timedelta(days=1))
    assert selected.sha256 == record.sha256
    with pytest.raises(LookupError):
        registry.select(date(2026, 8, 10), retrieved - timedelta(seconds=1))


def test_missing_point_in_time_static_is_not_a_schedule_join_failure(tmp_path) -> None:
    archive = tmp_path / "static.zip"
    write_static_fixture(archive)
    registry = StaticFeedRegistry(tmp_path / "registry.json")
    registry.register(archive, datetime(2026, 8, 12, tzinfo=UTC))
    processor = RegistrySnapshotProcessor(registry, {"099"}, FeatureBuilder())

    rows, counts = processor.process(
        parse_feed(realtime_payload()), datetime(2026, 8, 11, 7, 2, tzinfo=UTC)
    )

    assert rows == []
    assert counts["static_unavailable"] == 1
    assert counts["join_failures"] == 0


def test_cli_archives_the_exact_audit_behind_a_label_policy(tmp_path) -> None:
    data = tmp_path / "data"
    reports = tmp_path / "reports"
    reports.mkdir()
    audit = reports / "feed-audit.json"
    audit.write_text(
        json.dumps(
            {
                "label_semantics": {
                    "examples_checked": 100,
                    "candidate_coverage": 0.8,
                    "by_service_date": {
                        "2026-08-10": {"examples": 50},
                        "2026-08-11": {"examples": 50},
                    },
                    "by_local_date": {
                        "2026-08-10": {"examples": 50, "candidates": 40},
                        "2026-08-11": {"examples": 50, "candidates": 40},
                    },
                    "post_passage_retained_twice": 0,
                    "vehicle_position_confirmed": 0,
                }
            }
        )
    )
    frozen_dir = reports / "label-audits"
    frozen_dir.mkdir()
    audit_digest = hashlib.sha256(audit.read_bytes()).hexdigest()
    (frozen_dir / f"{audit_digest}.json").write_bytes(audit.read_bytes())
    review = reports / "trip-timelines-reviewed.json"
    samples = [
        {
            "trip_key": f"v|2026-08-{10 + index // 5:02d}|trip-{index}|",
            "local_date": f"2026-08-{10 + index // 5:02d}",
            "route": "099",
            "review_status": "reviewed",
            "review_notes": "target updates inspected",
        }
        for index in range(10)
    ]
    review.write_text(json.dumps({"audit_sha256": audit_digest, "samples": samples}))
    (reports / "dataset-quality.json").write_text(
        json.dumps({"strict_join_success_rate": 0.95, "service_days": 2})
    )
    (reports / "collection.json").write_text(
        json.dumps({"usable_service_dates": ["2026-08-10", "2026-08-11"]})
    )
    config = tmp_path / "config.yaml"
    config.write_text(f"data_dir: {data}\nreport_dir: {reports}\n")

    result = CliRunner().invoke(
        app,
        [
            "create-label-policy",
            "--config",
            str(config),
            "--target-type",
            "reported_delay_state",
        ],
    )

    assert result.exit_code == 0, result.output
    policy = LabelPolicy.load(data / "state/label-policy.json")
    archived = data / "state/label-audits" / f"{policy.audit_sha256}.json"
    assert archived.read_bytes() == audit.read_bytes()
    review_archive = data / "state/label-reviews" / f"{policy.review_sha256}.json"
    assert review_archive.read_bytes() == review.read_bytes()
    policy.verify_archives(data)
    review_archive.write_text("{}")
    with pytest.raises(RuntimeError, match="review checksum"):
        policy.verify_archives(data)

    audit.write_text(
        json.dumps(
            {
                "label_semantics": {
                    "examples_checked": 100,
                    "candidate_coverage": 0.8,
                    "by_service_date": {
                        "2026-08-10": {"examples": 50},
                        "2026-08-11": {"examples": 50},
                    },
                    "by_local_date": {
                        "2026-08-10": {"examples": 50, "candidates": 40},
                        "2026-08-11": {"examples": 50, "candidates": 40},
                    },
                    "post_passage_retained_twice": 10,
                    "vehicle_position_confirmed": 10,
                    "retained_and_position_confirmed": 0,
                }
            }
        )
    )
    audit_digest = hashlib.sha256(audit.read_bytes()).hexdigest()
    (frozen_dir / f"{audit_digest}.json").write_bytes(audit.read_bytes())
    review.write_text(json.dumps({"audit_sha256": audit_digest, "samples": samples}))
    measured = CliRunner().invoke(
        app,
        [
            "create-label-policy",
            "--config",
            str(config),
            "--target-type",
            "measured_arrival",
        ],
    )
    assert measured.exit_code != 0
    assert "measured-arrival policy requires" in measured.output

    exploratory_value = json.loads(audit.read_text())
    exploratory_value["label_semantics"]["label_lag_seconds"] = 300
    exploratory_value["label_semantics"]["candidate_window_seconds"] = 480
    audit.write_text(json.dumps(exploratory_value))
    audit_digest = hashlib.sha256(audit.read_bytes()).hexdigest()
    (frozen_dir / f"{audit_digest}.json").write_bytes(audit.read_bytes())
    review.write_text(json.dumps({"audit_sha256": audit_digest, "samples": samples}))
    exploratory = CliRunner().invoke(app, ["create-label-policy", "--config", str(config)])
    assert exploratory.exit_code != 0
    assert "exploratory target cannot use the current label policy" in exploratory.output


def test_synthetic_demo_is_deterministic_and_explicit(tmp_path) -> None:
    data = tmp_path / "data"
    reports = tmp_path / "reports"
    first = seed_synthetic_demo(data, reports)
    content = (data / "serving/latest_features.jsonl").read_text()
    second = seed_synthetic_demo(data, reports)
    assert first["data_mode"] == second["data_mode"] == "synthetic"
    assert (data / "serving/latest_features.jsonl").read_text() == content
    assert json.loads((reports / "collection.json").read_text())["synthetic"] is True
    summary = build_portfolio_summary(data, reports)
    assert "Evidence mode: synthetic/replay" in summary
    assert "Résumé eligible: no; completion gates remain pending" in summary


def test_fixed_lag_policy_requires_matching_route_audit_and_review(tmp_path) -> None:
    data = tmp_path / "data"
    reports = tmp_path / "reports"
    frozen = reports / "label-audits"
    frozen.mkdir(parents=True)
    audit_value = {
        "label_semantics": {
            "label_lag_seconds": 300,
            "candidate_window_seconds": 480,
            "examples_checked": 100,
            "candidate_coverage": 0.8,
            "by_local_date": {
                "2026-08-10": {"examples": 50, "candidates": 40},
                "2026-08-11": {"examples": 50, "candidates": 40},
            },
        }
    }
    audit_payload = json.dumps(audit_value, sort_keys=True)
    digest = hashlib.sha256(audit_payload.encode()).hexdigest()
    (frozen / f"{digest}.json").write_text(audit_payload)
    review = reports / "review.json"
    review.write_text(
        json.dumps(
            {
                "audit_sha256": digest,
                "routes": ["R5"],
                "label_lag_seconds": 300,
                "candidate_window_seconds": 480,
                "samples": [
                    {
                        "trip_key": f"v|2026-08-{10 + index // 5:02d}|trip-{index}|",
                        "local_date": f"2026-08-{10 + index // 5:02d}",
                        "route": "R5",
                        "review_status": "reviewed",
                        "review_notes": "future target estimate and vehicle position inspected",
                    }
                    for index in range(10)
                ],
            }
        )
    )
    scope = reports / "scope.json"
    scope.write_text(
        json.dumps(
            {
                "routes": ["R5"],
                "quality": {"strict_join_success_rate": 0.99},
                "audit": audit_value,
            }
        )
    )
    (reports / "dataset-quality.json").write_text(
        json.dumps({"strict_join_success_rate": 0.95, "service_days": 2})
    )
    (reports / "collection.json").write_text(
        json.dumps({"usable_service_dates": ["2026-08-10", "2026-08-11"]})
    )
    config = tmp_path / "config.yaml"
    config.write_text(f"data_dir: {data}\nreport_dir: {reports}\nselected_routes: ['R5']\n")
    command = [
        "create-label-policy",
        "--config",
        str(config),
        "--target-type",
        "reported_delay_state_fixed_lag",
        "--review",
        str(review),
        "--scope-report",
        str(scope),
    ]
    result = CliRunner().invoke(app, command)
    assert result.exit_code == 0, result.output
    policy = LabelPolicy.load(data / "state/label-policy.json")
    assert policy.routes == ("R5",)
    assert policy.label_lag_seconds == 300
    assert policy.candidate_window_seconds == 480
    policy.verify_archives(data)
    scoped_archive = data / "state/route-scopes" / f"{policy.scope_report_sha256}.json"
    scoped_archive.write_text("{}")
    with pytest.raises(RuntimeError, match="route-scope checksum"):
        policy.verify_archives(data)
