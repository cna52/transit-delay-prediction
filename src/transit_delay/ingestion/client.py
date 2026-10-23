from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from transit_delay.ingestion.archive import FetchRecord, ImmutableArchive
from transit_delay.ingestion.quota import DailyQuota


@dataclass(frozen=True)
class Endpoint:
    feed_type: str
    url: str


class FeedClient:
    def __init__(
        self,
        api_key: str,
        archive: ImmutableArchive,
        quota: DailyQuota,
        timeout_seconds: float = 20,
        transport: Callable[[str, dict[str, str], float], tuple[int, bytes]] | None = None,
    ):
        if not api_key:
            raise ValueError("TransLink API key is required")
        self._api_key = api_key
        self.archive = archive
        self.quota = quota
        self.timeout_seconds = timeout_seconds
        self.transport = transport or self._httpx_transport

    def fetch(self, endpoint: Endpoint) -> FetchRecord:
        started = datetime.now(UTC)
        monotonic = time.monotonic()
        self.quota.consume(started)
        try:
            status, body = self.transport(
                endpoint.url, {"apikey": self._api_key}, self.timeout_seconds
            )
            received = datetime.now(UTC)
            elapsed = int((time.monotonic() - monotonic) * 1000)
            if status != 200:
                return self.archive.store_failure(
                    endpoint.feed_type,
                    started,
                    received,
                    elapsed,
                    f"HTTP {status}",
                    status,
                )
            return self.archive.store(endpoint.feed_type, body, started, received, status, elapsed)
        except Exception as exc:
            received = datetime.now(UTC)
            safe_error = str(exc).replace(self._api_key, "[REDACTED]")
            return self.archive.store_failure(
                endpoint.feed_type,
                started,
                received,
                int((time.monotonic() - monotonic) * 1000),
                safe_error,
            )

    @staticmethod
    def _httpx_transport(url: str, params: dict[str, str], timeout: float) -> tuple[int, bytes]:
        try:
            import httpx
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("httpx is required for live collection") from exc
        response = httpx.get(url, params=params, timeout=timeout)
        return response.status_code, response.content
