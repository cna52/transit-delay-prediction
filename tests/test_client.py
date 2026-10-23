from transit_delay.ingestion.archive import ImmutableArchive
from transit_delay.ingestion.client import Endpoint, FeedClient
from transit_delay.ingestion.quota import DailyQuota


def test_client_redacts_key_and_records_failure(tmp_path) -> None:
    secret = "super-secret-key"

    def failing_transport(url, params, timeout):
        raise RuntimeError(f"request containing {params['apikey']} failed")

    client = FeedClient(
        secret,
        ImmutableArchive(tmp_path),
        DailyQuota(tmp_path / "quota.json", 5, "America/Vancouver"),
        transport=failing_transport,
    )
    record = client.fetch(Endpoint("trip_updates", "https://example.invalid"))
    assert record.error is not None
    assert secret not in record.error
    assert "[REDACTED]" in record.error
