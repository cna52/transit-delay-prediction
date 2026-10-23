from datetime import UTC, date, datetime

from transit_delay.datasets.store import DatasetStore
from transit_delay.domain import FeatureRow, LabelOutcome, TripInstanceKey


def test_dataset_content_version_is_deterministic(tmp_path) -> None:
    row = FeatureRow(
        "e1",
        datetime(2026, 8, 10, 18, tzinfo=UTC),
        TripInstanceKey("v1", date(2026, 8, 10), "trip"),
        3,
        "s3",
        datetime(2026, 8, 10, 18, 12, tzinfo=UTC),
        720,
        "099",
        0,
        1,
        2,
        120,
        10,
        20,
        18,
        0,
        0,
    )
    label = LabelOutcome(
        "e1",
        "labelled",
        3.0,
        datetime(2026, 8, 10, 18, 15, tzinfo=UTC),
        datetime(2026, 8, 10, 18, 16, tzinfo=UTC),
        "audited_past_stop_update",
    )
    store = DatasetStore(tmp_path)
    first = store.write([row], [label], ["source-a"], "label-v1")
    second = store.write([row], [label], ["source-a"], "label-v1")
    assert first.dataset_version == second.dataset_version
    assert first.content_sha256 == second.content_sha256
    assert first.static_versions == ("v1",)
    assert first.service_date_from == "2026-08-10"
    assert first.unique_trip_instances == 1
    assert first.label_status_counts == {"labelled": 1}
