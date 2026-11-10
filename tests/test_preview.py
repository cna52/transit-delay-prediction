from datetime import UTC, datetime, timedelta

from transit_delay.models.preview import preview_split


def _record(day: int, trip: str, hour: int = 12) -> dict[str, object]:
    observed = datetime(2026, 10, 23, hour, tzinfo=UTC) + timedelta(days=day)
    return {
        "key": f"v|{observed.date()}|{trip}|",
        "as_of": observed.isoformat(),
        "source_age_seconds": 10,
        "label": {
            "status": "labelled",
            "label_minutes": 1.0,
            "available_at": (observed + timedelta(minutes=10)).isoformat(),
        },
    }


def test_preview_split_keeps_trips_intact_and_excludes_late_training_labels() -> None:
    records = [_record(day, f"trip-{day}") for day in range(5)]
    crossing = _record(2, "crossing", 23)
    after_midnight = dict(crossing)
    after_midnight["as_of"] = (
        datetime.fromisoformat(str(crossing["as_of"])) + timedelta(hours=2)
    ).isoformat()
    after_midnight["label"] = {
        "status": "labelled",
        "label_minutes": 1.0,
        "available_at": (
            datetime.fromisoformat(str(after_midnight["as_of"])) + timedelta(minutes=10)
        ).isoformat(),
    }
    late = _record(2, "late", 23)
    late["label"] = {
        "status": "labelled",
        "label_minutes": 1.0,
        "available_at": datetime(2026, 10, 26, 12, tzinfo=UTC).isoformat(),
    }
    records.extend([crossing, after_midnight, late])
    train, validation, missing_rate = preview_split(
        records,
        {"2026-10-23", "2026-10-24", "2026-10-25"},
        {"2026-10-26", "2026-10-27"},
        "UTC",
    )
    train_keys = {str(row["key"]) for row in train}
    validation_keys = {str(row["key"]) for row in validation}
    assert train_keys.isdisjoint(validation_keys)
    assert str(crossing["key"]) in train_keys
    assert str(late["key"]) not in train_keys
    assert len(validation) == 2
    assert missing_rate == 0.0
