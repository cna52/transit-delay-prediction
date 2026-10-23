from __future__ import annotations

import json
import os
from pathlib import Path


class PredictionLogger:
    def __init__(self, path: Path):
        self.path = path

    def append(self, value: dict[str, object]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(self.path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
        try:
            os.write(descriptor, (json.dumps(value, sort_keys=True, default=str) + "\n").encode())
        finally:
            os.close(descriptor)
