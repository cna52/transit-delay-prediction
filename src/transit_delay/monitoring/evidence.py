from __future__ import annotations

import json
from pathlib import Path


def build_portfolio_summary(data_dir: Path, report_dir: Path) -> str:
    collection = _read(report_dir / "collection.json")
    evaluation = _read(report_dir / "evaluation.json")
    predictions = _read(report_dir / "predictions.json")
    manifests = sorted((data_dir / "processed" / "datasets").glob("*/manifest.json"))
    dataset = _read(manifests[-1]) if manifests else None
    policy_version = str(dataset.get("label_policy_version", "")) if dataset else ""
    eligible_dataset = bool(
        dataset
        and int(str(dataset.get("labelled_count", 0))) > 0
        and not policy_version.startswith("audit-required")
    )
    synthetic = bool(collection and collection.get("synthetic"))
    evidence_mode = "synthetic/replay (development only)" if synthetic else "live"
    promotion_value = evaluation.get("promotion", {}) if evaluation else {}
    promotion = promotion_value if isinstance(promotion_value, dict) else {}
    resume_eligible = bool(eligible_dataset and promotion.get("approved") and not synthetic)
    lines = [
        "# Generated portfolio evidence",
        "",
        "> Generated from local artifacts. Missing evidence remains explicitly pending.",
        "",
        f"- Evidence mode: {evidence_mode}",
        "- Résumé eligible: yes, after manual review"
        if resume_eligible
        else "- Résumé eligible: no; completion gates remain pending",
        "",
        "## Collection",
        "",
    ]
    if collection:
        lines.extend(
            [
                f"- Reporting period: {collection.get('date_from')} to {collection.get('date_to')}",
                "- Attempts / successes: "
                f"{collection.get('attempts')} / {collection.get('successes')}",
                f"- Success rate: {_percent(collection.get('success_rate'))}",
                f"- Unique payloads: {collection.get('unique_payloads')}",
                f"- Largest observed gap: {collection.get('largest_gap_seconds')} seconds",
            ]
        )
        if not eligible_dataset:
            lines.append(
                "- Status: non-trainable historical artifact; approved policy and labels pending"
            )
    else:
        lines.append("- Pending: no collection report exists.")
    lines.extend(["", "## Dataset", ""])
    if dataset:
        lines.extend(
            [
                f"- Version: {dataset.get('dataset_version')}",
                f"- Rows / labelled: {dataset.get('row_count')} / {dataset.get('labelled_count')}",
                f"- Label policy: {dataset.get('label_policy_version')}",
            ]
        )
    else:
        lines.append("- Pending: no immutable dataset exists.")
    lines.extend(["", "## Offline evaluation", ""])
    if evaluation:
        lines.append(f"- Promotion approved: {promotion.get('approved', False)}")
        reports_value = evaluation.get("reports", [])
        reports = reports_value if isinstance(reports_value, list) else []
        for report_value in reports:
            report = report_value if isinstance(report_value, dict) else {}
            overall_value = report.get("overall", {})
            overall = overall_value if isinstance(overall_value, dict) else {}
            lines.append(
                f"- {report.get('model_name')}: MAE {overall.get('mae')} minutes "
                f"across {overall.get('count')} examples"
            )
    else:
        lines.append("- Pending: no locked chronological evaluation exists.")
    lines.extend(["", "## Online behaviour", ""])
    if predictions:
        latency_value = predictions.get("latency_ms", {})
        latency = latency_value if isinstance(latency_value, dict) else {}
        lines.extend(
            [
                f"- Prediction requests: {predictions.get('requests')}",
                f"- Labelled predictions: {predictions.get('labelled')}",
                f"- Delayed MAE: {predictions.get('mae_minutes')} minutes",
                f"- Fallback rate: {_percent(predictions.get('fallback_rate'))}",
                f"- p95 API latency: {latency.get('p95')} ms",
            ]
        )
    else:
        lines.append("- Pending: no prediction monitoring report exists.")
    lines.extend(
        [
            "",
            "Synthetic or replay-mode values must not be copied into a résumé as "
            "production evidence.",
            "",
        ]
    )
    return "\n".join(lines)


def _read(path: Path) -> dict[str, object] | None:
    try:
        value = json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    return value if isinstance(value, dict) else None


def _percent(value: object) -> str:
    return "pending" if value is None else f"{float(str(value)) * 100:.1f}%"
