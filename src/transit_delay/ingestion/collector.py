from __future__ import annotations

import logging
import signal
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from transit_delay.ingestion.client import Endpoint, FeedClient
from transit_delay.runtime import write_state

LOGGER = logging.getLogger(__name__)


@dataclass
class ScheduledEndpoint:
    endpoint: Endpoint
    interval_seconds: int
    next_run: float = 0


class Collector:
    def __init__(
        self,
        client: FeedClient,
        endpoints: list[ScheduledEndpoint],
        state_path: Path | None = None,
    ):
        self.client = client
        self.endpoints = endpoints
        self.running = True
        self.state_path = state_path
        self.consecutive_failures = 0

    def stop(self, *_args: object) -> None:
        self.running = False

    def run_forever(self) -> None:
        signal.signal(signal.SIGTERM, self.stop)
        signal.signal(signal.SIGINT, self.stop)
        now = time.monotonic()
        for item in self.endpoints:
            item.next_run = now
        while self.running:
            now = time.monotonic()
            for item in self.endpoints:
                if now < item.next_run:
                    continue
                try:
                    record = self.client.fetch(item.endpoint)
                except RuntimeError as exc:
                    if self.state_path is not None:
                        write_state(
                            self.state_path,
                            status="quota_wait",
                            last_error=str(exc),
                            consecutive_failures=self.consecutive_failures,
                        )
                    item.next_run = now + 60
                    continue
                succeeded = record.status_code == 200 and record.error is None
                self.consecutive_failures = 0 if succeeded else self.consecutive_failures + 1
                if self.state_path is not None:
                    state_values: dict[str, object] = {
                        "status": "healthy" if succeeded else "degraded",
                        "last_attempt_at": record.received_at,
                        "last_feed_type": record.feed_type,
                        "last_status_code": record.status_code,
                        "last_error": record.error,
                        "consecutive_failures": self.consecutive_failures,
                    }
                    if succeeded:
                        state_values["last_success_at"] = record.received_at
                    write_state(
                        self.state_path,
                        **state_values,
                    )
                LOGGER.info(
                    "feed_fetch",
                    extra={
                        "feed_type": record.feed_type,
                        "fetch_id": record.fetch_id,
                        "status": record.status_code,
                        "error": record.error,
                        "at": datetime.now(UTC).isoformat(),
                    },
                )
                if record.status_code == 401:
                    self.running = False
                    if self.state_path is not None:
                        write_state(self.state_path, status="auth_error")
                backoff = 900 if record.status_code == 429 else item.interval_seconds
                item.next_run = max(item.next_run + backoff, now + 1)
            time.sleep(0.5)
