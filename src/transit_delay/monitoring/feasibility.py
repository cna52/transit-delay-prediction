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
    by_local_date = semantics.get("by_local_date") or {}
    audited_complete_dates = sorted(
        day
        for day, values in by_local_date.items()
        if day in complete_dates and int(values.get("examples") or 0) > 0
    )
    gate_examples = sum(
        int(by_local_date[day].get("examples") or 0) for day in audited_complete_dates
    )
    gate_candidates = sum(
        int(by_local_date[day].get("candidates") or 0) for day in audited_complete_dates
    )
    gate_coverage = gate_candidates / gate_examples if gate_examples else None
    gate_routes: dict[str, dict[str, int | float]] = {}
    by_route_local_date = semantics.get("by_route_local_date") or {}
    for day in audited_complete_dates:
        for route, values in by_route_local_date.get(day, {}).items():
            counts = gate_routes.setdefault(route, {"examples": 0, "candidates": 0})
            counts["examples"] += int(values.get("examples") or 0)
            counts["candidates"] += int(values.get("candidates") or 0)
    for counts in gate_routes.values():
        examples_for_route = counts["examples"]
        counts["candidate_coverage"] = (
            counts["candidates"] / examples_for_route if examples_for_route else 0.0
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
        "one_hundred_mature_examples": gate_examples >= 100,
        "strict_unique_static_joins": join_rate >= 0.9,
        "candidate_coverage_within_30m": gate_coverage is not None and gate_coverage >= 0.7,
    }
    route_candidates = sorted(
        route
        for route, values in gate_routes.items()
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
        "gate_mature_examples": gate_examples,
        "gate_candidate_labels": gate_candidates,
        "gate_candidate_coverage": gate_coverage,
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
        "by_local_date": by_local_date,
        "gate_by_route": gate_routes,
    }
