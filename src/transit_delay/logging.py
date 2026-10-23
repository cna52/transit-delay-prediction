from __future__ import annotations

import json
import logging
import re
from datetime import UTC, datetime

API_KEY_PATTERN = re.compile(r"(?i)(apikey=)[^&\s\"']+")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        message = API_KEY_PATTERN.sub(r"\1[REDACTED]", record.getMessage())
        base = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": message,
        }
        for key in ("feed_type", "fetch_id", "status", "error"):
            if hasattr(record, key):
                value = getattr(record, key)
                base[key] = (
                    API_KEY_PATTERN.sub(r"\1[REDACTED]", value) if isinstance(value, str) else value
                )
        return json.dumps(base, sort_keys=True, default=str)


def configure_logging(level: str) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    logging.basicConfig(level=level, handlers=[handler], force=True)
    # httpx/httpcore INFO messages include the complete query URL. TransLink authenticates via
    # an `apikey` query parameter, so suppress these third-party request logs unconditionally.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
