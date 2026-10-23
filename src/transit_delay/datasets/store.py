from __future__ import annotations

import hashlib
import json
import os
from collections import Counter
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from transit_delay.domain import FeatureRow, LabelOutcome


@dataclass(frozen=True)
class DatasetManifest:
    dataset_version: str
    created_at: str
    feature_schema_version: str
    label_policy_version: str
    row_count: int
    labelled_count: int
    source_hashes: tuple[str, ...]
    content_sha256: str
    static_versions: tuple[str, ...]
    service_date_from: str | None
    service_date_to: str | None
    unique_trip_instances: int
    label_status_counts: dict[str, int]


class DatasetStore:
    def __init__(self, root: Path):
        self.root = root

    def write(
        self,
        features: Iterable[FeatureRow],
        labels: Iterable[LabelOutcome],
        source_hashes: Iterable[str],
        label_policy_version: str,
    ) -> DatasetManifest:
        rows = sorted((row.to_dict() for row in features), key=lambda row: row["example_id"])
        labels_by_id = {label.example_id: asdict(label) for label in labels}
        combined = []
        for row in rows:
            label = labels_by_id.get(row["example_id"])
            combined.append({**row, "label": label})
        canonical = (
            "\n".join(json.dumps(row, sort_keys=True, default=str) for row in combined) + "\n"
        )
        digest = hashlib.sha256(canonical.encode()).hexdigest()
        version = f"ds-{digest[:12]}"
        keys = [str(row["key"]).split("|") for row in rows]
        service_dates = sorted({parts[1] for parts in keys if len(parts) > 1})
        status_counts = Counter(str(value.get("status")) for value in labels_by_id.values())
        directory = self.root / "processed" / "datasets" / version
        directory.mkdir(parents=True, exist_ok=True)
        data_path = directory / "rows.jsonl"
        temporary = data_path.with_suffix(".tmp")
        temporary.write_text(canonical)
        os.replace(temporary, data_path)
        manifest = DatasetManifest(
            version,
            datetime.now(UTC).isoformat(),
            rows[0]["feature_schema_version"] if rows else "v1",
            label_policy_version,
            len(rows),
            sum(1 for value in labels_by_id.values() if value["status"] == "labelled"),
            tuple(sorted(source_hashes)),
            digest,
            tuple(sorted({parts[0] for parts in keys if parts})),
            service_dates[0] if service_dates else None,
            service_dates[-1] if service_dates else None,
            len({str(row["key"]) for row in rows}),
            dict(status_counts),
        )
        manifest_path = directory / "manifest.json"
        manifest_path.write_text(json.dumps(asdict(manifest), indent=2, sort_keys=True))
        self._write_analytical_copy(directory, combined, manifest)
        return manifest

    def _write_analytical_copy(
        self, directory: Path, rows: list[dict[str, object]], manifest: DatasetManifest
    ) -> None:
        import duckdb
        import polars as pl

        flattened = []
        for row in rows:
            label = row.pop("label", None)
            label_values = label if isinstance(label, dict) else {}
            flattened.append(
                {
                    **row,
                    "label_status": label_values.get("status"),
                    "label_minutes": label_values.get("label_minutes"),
                    "label_available_at": label_values.get("available_at"),
                }
            )
        pl.DataFrame(flattened).write_parquet(directory / "rows.parquet", compression="zstd")
        catalog_path = self.root / "processed" / "catalog.duckdb"
        connection = duckdb.connect(str(catalog_path))
        try:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS dataset_versions (
                    dataset_version VARCHAR PRIMARY KEY,
                    created_at TIMESTAMPTZ,
                    feature_schema_version VARCHAR,
                    label_policy_version VARCHAR,
                    row_count BIGINT,
                    labelled_count BIGINT,
                    content_sha256 VARCHAR,
                    parquet_path VARCHAR
                )
                """
            )
            for name, definition in (
                ("static_versions", "VARCHAR"),
                ("service_date_from", "DATE"),
                ("service_date_to", "DATE"),
                ("unique_trip_instances", "BIGINT"),
                ("label_status_counts", "VARCHAR"),
            ):
                connection.execute(
                    f"ALTER TABLE dataset_versions ADD COLUMN IF NOT EXISTS {name} {definition}"
                )
            connection.execute(
                """
                INSERT OR REPLACE INTO dataset_versions (
                    dataset_version, created_at, feature_schema_version, label_policy_version,
                    row_count, labelled_count, content_sha256, parquet_path, static_versions,
                    service_date_from, service_date_to, unique_trip_instances, label_status_counts
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    manifest.dataset_version,
                    manifest.created_at,
                    manifest.feature_schema_version,
                    manifest.label_policy_version,
                    manifest.row_count,
                    manifest.labelled_count,
                    manifest.content_sha256,
                    str(directory / "rows.parquet"),
                    json.dumps(manifest.static_versions),
                    manifest.service_date_from,
                    manifest.service_date_to,
                    manifest.unique_trip_instances,
                    json.dumps(manifest.label_status_counts, sort_keys=True),
                ],
            )
            # Views follow the latest immutable Parquet version, with its exact path
            # recorded in dataset_versions for reproducibility.
            parquet_path = str(directory / "rows.parquet").replace("'", "''")
            connection.execute(
                f"CREATE OR REPLACE VIEW latest_dataset_rows AS "
                f"SELECT * FROM read_parquet('{parquet_path}')"
            )
            connection.execute(
                """
                CREATE OR REPLACE VIEW dataset_coverage AS
                SELECT split_part(key, '|', 2) AS service_date,
                       route_short_name,
                       count(*) AS eligible_examples,
                       count(*) FILTER (WHERE label_status = 'labelled') AS labelled_examples,
                       round(count(*) FILTER (WHERE label_status = 'labelled')::DOUBLE
                             / nullif(count(*), 0), 4) AS label_coverage
                FROM latest_dataset_rows
                GROUP BY 1, 2
                """
            )
            connection.execute(
                """
                CREATE OR REPLACE VIEW dataset_label_quality AS
                SELECT split_part(key, '|', 2) AS service_date,
                       route_short_name, coalesce(label_status, 'missing') AS label_status,
                       count(*) AS examples,
                       count(*) FILTER (WHERE label_minutes IS NOT NULL) AS numeric_labels,
                       min(label_available_at) AS first_available_at,
                       max(label_available_at) AS last_available_at
                FROM latest_dataset_rows
                GROUP BY 1, 2, 3
                """
            )
        finally:
            connection.close()
