from datetime import date

from transit_delay.monitoring.feasibility import feasibility_gates


def test_feasibility_uses_only_complete_local_days_for_gates_and_routes() -> None:
    collection = {"usable_service_dates": ["2026-10-22", "2026-10-23"]}
    quality = {"strict_join_success_rate": 0.95}
    audit = {
        "label_semantics": {
            "examples_checked": 250,
            "pending_examples": 40,
            "candidate_labels": 196,
            "candidate_coverage": 196 / 250,
            "missing_candidate_reasons": {"no_trip_update_in_window": 20},
            "no_trip_update_poll_context": {"feed_poll_gap": 20},
            "missing_with_prior_target_value": 15,
            "by_local_date": {
                "2026-10-22": {"examples": 75, "candidates": 48},
                "2026-10-23": {"examples": 75, "candidates": 48},
                "2026-10-24": {"examples": 100, "candidates": 100},
            },
            "by_route_local_date": {
                day: {
                    "099": {"examples": 55, "candidates": 44},
                    "R4": {"examples": 20, "candidates": 4},
                }
                for day in ("2026-10-22", "2026-10-23")
            },
            "by_route": {
                "099": {"examples": 110, "candidate_coverage": 0.8},
                "R4": {"examples": 40, "candidate_coverage": 0.2},
            },
        }
    }
    report = feasibility_gates(collection, quality, audit, date(2026, 10, 24))
    assert report["status"] == "route_scope_review_required"
    assert report["route_candidates_for_replay"] == ["099"]
    assert report["gates"]["candidate_coverage_within_30m"] is False
    assert report["audited_complete_dates"] == ["2026-10-22", "2026-10-23"]
    assert report["gate_mature_examples"] == 150
    assert report["gate_candidate_coverage"] == 96 / 150
    assert report["candidate_coverage"] == 196 / 250
    assert report["candidate_coverage_when_feed_polled"] == 196 / 230

    collecting = feasibility_gates(collection, quality, audit, date(2026, 10, 23))
    assert collecting["status"] == "collecting"
    assert collecting["complete_usable_dates"] == ["2026-10-22"]

    missing_day = audit["label_semantics"]["by_local_date"].pop("2026-10-23")
    assert (
        feasibility_gates(collection, quality, audit, date(2026, 10, 24))["status"] == "collecting"
    )
    audit["label_semantics"]["by_local_date"]["2026-10-23"] = missing_day

    for day in ("2026-10-22", "2026-10-23"):
        audit["label_semantics"]["by_route_local_date"][day]["099"]["candidates"] = 22
    assert (
        feasibility_gates(collection, quality, audit, date(2026, 10, 24))["status"]
        == "dataset_limitation"
    )
