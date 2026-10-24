from __future__ import annotations

from datetime import date
from typing import Any


def feasibility_gates(
    collection: dict[str, Any], quality: dict[str, Any], audit: dict[str, Any], today: date
) -> dict[str, object]:
    """Summarize the two-day policy gates without treating pending labels as failures."""
    semantics = audit.get("label_semantics") or {}
    complete_dates = sorted(
        day for day in collection.get("usable_service_dates", []) if day < today.isoformat()
    )
    audited_complete_dates = sorted(
        day
        for day, values in (semantics.get("by_service_date") or {}).items()
        if day in complete_dates and int(values.get("examples") or 0) > 0
    )
    examples = int(semantics.get("examples_checked") or 0)
    coverage = float(semantics.get("candidate_coverage") or 0)
    candidates = int(semantics.get("candidate_labels") or 0)
    missing_reasons = semantics.get("missing_candidate_reasons") or {}
    poll_context = semantics.get("no_trip_update_poll_context") or {}
    windows_with_poll = examples - int(poll_context.get("feed_poll_gap") or 0)
    join_rate = float(quality.get("strict_join_success_rate") or 0)
    gates = {
        "two_complete_usable_days": len(audited_complete_dates) >= 2,
        "one_hundred_mature_examples": examples >= 100,
        "strict_unique_static_joins": join_rate >= 0.9,
        "candidate_coverage_within_30m": coverage >= 0.7,
    }
    route_candidates = sorted(
        route
        for route, values in (semantics.get("by_route") or {}).items()
        if int(values.get("examples") or 0) >= 100
        and float(values.get("candidate_coverage") or 0) >= 0.7
    )
    if all(gates.values()):
        status = "manual_review_required"
    elif not gates["two_complete_usable_days"] or not gates["one_hundred_mature_examples"]:
        status = "collecting"
    elif not gates["strict_unique_static_joins"]:
        status = "static_join_failure"
    elif route_candidates:
        status = "route_scope_review_required"
    else:
        status = "dataset_limitation"
    return {
        "status": status,
        "gates": gates,
        "complete_usable_dates": complete_dates,
        "audited_complete_dates": audited_complete_dates,
        "mature_examples": examples,
        "pending_examples": int(semantics.get("pending_examples") or 0),
        "candidate_coverage": coverage,
        "candidate_coverage_when_feed_polled": candidates / windows_with_poll
        if windows_with_poll > 0
        else None,
        "missing_candidate_reasons": missing_reasons,
        "no_trip_update_poll_context": poll_context,
        "missing_with_prior_target_value": int(
            semantics.get("missing_with_prior_target_value") or 0
        ),
        "strict_join_success_rate": join_rate,
        "route_candidates_for_replay": route_candidates,
        "by_route": semantics.get("by_route") or {},
        "by_service_date": semantics.get("by_service_date") or {},
    }
