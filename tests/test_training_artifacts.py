from datetime import UTC, datetime, timedelta

from transit_delay.models.artifacts import ArtifactStore
from transit_delay.models.training import train_ridge


def training_rows(count=20):
    rows = []
    labels = []
    start = datetime(2026, 7, 1, 8, tzinfo=UTC)
    for index in range(count):
        delay = index * 15
        observed = start + timedelta(days=index)
        rows.append(
            {
                "key": f"v|{observed.date()}|trip-{index}|",
                "as_of": observed.isoformat(),
                "route_short_name": "099" if index % 2 else "R4",
                "direction_id": index % 2,
                "target_stop_id": f"s{index % 3}",
                "weekday": observed.weekday(),
                "horizon_seconds": 600 + index,
                "current_stop_sequence": 4,
                "stops_to_target": 3,
                "current_delay_seconds": delay,
                "delay_trend_seconds": 5,
                "source_age_seconds": 20,
                "hour": observed.hour,
                "minute": observed.minute,
            }
        )
        labels.append(delay / 60 + 0.5)
    return rows, labels


def test_train_save_promote_and_checksum_load(tmp_path) -> None:
    rows, labels = training_rows()
    model = train_ridge(rows, labels)
    predictions = model.predict(rows[:2])
    assert len(predictions) == 2
    store = ArtifactStore(tmp_path)
    manifest = store.save(model, "dataset-test", {"q05": -1, "q95": 1})
    store.promote(manifest.model_version)
    loaded, loaded_manifest = store.load_champion()
    assert loaded_manifest.model_sha256 == manifest.model_sha256
    assert loaded.predict(rows[:1]) == model.predict(rows[:1])
