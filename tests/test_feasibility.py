from datetime import date

from transit_delay.monitoring.feasibility import feasibility_gates


def test_feasibility_routes_only_after_complete_days_and_mature_examples() -> None:
    collection = {"usable_service_dates": ["2026-10-22", "2026-10-23"]}
    quality = {"strict_join_success_rate": 0.95}
    audit = {
        "label_semantics": {
            "examples_checked": 150,
            "pending_examples": 40,
            "candidate_labels": 75,
            "candidate_coverage": 0.5,
            "missing_candidate_reasons": {"no_trip_update_in_window": 20},
            "no_trip_update_poll_context": {"feed_poll_gap": 20},
            "missing_with_prior_target_value": 15,
            "by_service_date": {
                "2026-10-22": {"examples": 75},
                "2026-10-23": {"examples": 75},
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
    assert report["candidate_coverage_when_feed_polled"] == 75 / 130
    assert report["missing_candidate_reasons"] == {"no_trip_update_in_window": 20}

    collecting = feasibility_gates(collection, quality, audit, date(2026, 10, 23))
    assert collecting["status"] == "collecting"
    assert collecting["complete_usable_dates"] == ["2026-10-22"]

    missing_day = audit["label_semantics"]["by_service_date"].pop("2026-10-23")
    assert (
        feasibility_gates(collection, quality, audit, date(2026, 10, 24))["status"] == "collecting"
    )
    audit["label_semantics"]["by_service_date"]["2026-10-23"] = missing_day

    audit["label_semantics"]["by_route"]["099"]["candidate_coverage"] = 0.4
    assert (
        feasibility_gates(collection, quality, audit, date(2026, 10, 24))["status"]
        == "dataset_limitation"
    )
