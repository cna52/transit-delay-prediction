from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path


def write_state(path: Path, **values: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    current: dict[str, object] = {}
    if path.exists():
        try:
            parsed = json.loads(path.read_text())
            if isinstance(parsed, dict):
                current = parsed
        except (json.JSONDecodeError, OSError):
            pass
    current.update(values)
    current["updated_at"] = datetime.now(UTC).isoformat()
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(current, indent=2, sort_keys=True, default=str))
    temporary.replace(path)


def read_state(path: Path) -> dict[str, object] | None:
    try:
        value = json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    return value if isinstance(value, dict) else None
