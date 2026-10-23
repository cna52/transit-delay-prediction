import pytest

from transit_delay.config import Settings


def test_default_schedule_fits_quota() -> None:
    settings = Settings()
    settings.validate()
    requests = 86400 // settings.trip_updates_interval_seconds
    requests += 86400 // settings.vehicle_positions_interval_seconds
    assert requests == 864


def test_rejects_schedule_over_quota() -> None:
    with pytest.raises(ValueError, match="polling schedule"):
        Settings(trip_updates_interval_seconds=30).validate()
