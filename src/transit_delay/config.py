from __future__ import annotations

import os
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Settings:
    timezone: str = "America/Vancouver"
    selected_routes: tuple[str, ...] = ("099", "R4", "R5", "049")
    trip_updates_interval_seconds: int = 120
    vehicle_positions_interval_seconds: int = 600
    daily_request_limit: int = 900
    target_horizon_min_seconds: int = 600
    target_horizon_max_seconds: int = 900
    example_cooldown_seconds: int = 300
    max_feature_age_seconds: int = 300
    label_wait_seconds: int = 1800
    serving_refresh_interval_seconds: int = 900
    reporting_interval_seconds: int = 3600
    offline_rebuild_interval_seconds: int = 86400
    static_refresh_interval_seconds: int = 86400
    static_url: str = "https://gtfs-static.translink.ca/gtfs/google_transit.zip"
    trip_updates_url: str = "https://gtfsapi.translink.ca/v3/gtfsrealtime"
    vehicle_positions_url: str = "https://gtfsapi.translink.ca/v3/gtfsposition"
    data_dir: Path = Path("data")
    artifact_dir: Path = Path("artifacts")
    report_dir: Path = Path("reports/generated")
    frontend_dir: Path = Path("frontend/dist")
    data_mode: str = "live"
    log_level: str = "INFO"
    api_key: str | None = None

    def validate(self) -> None:
        if self.daily_request_limit > 1000:
            raise ValueError("daily_request_limit must not exceed TransLink's 1,000 request cap")
        scheduled = 86400 // self.trip_updates_interval_seconds
        scheduled += 86400 // self.vehicle_positions_interval_seconds
        if scheduled > self.daily_request_limit:
            raise ValueError(
                f"polling schedule needs {scheduled} requests/day, over configured limit"
            )
        if self.target_horizon_min_seconds >= self.target_horizon_max_seconds:
            raise ValueError("target horizon minimum must be below maximum")
        if self.data_mode not in {"live", "replay", "synthetic"}:
            raise ValueError("data_mode must be live, replay, or synthetic")


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        import yaml
    except ImportError as exc:  # pragma: no cover - dependency guard
        raise RuntimeError("Install project dependencies to read YAML configuration") from exc
    raw = yaml.safe_load(path.read_text()) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"configuration must be a mapping: {path}")
    return raw


def load_settings(config_path: str | Path | None = None) -> Settings:
    base = _read_yaml(Path("configs/base.yaml"))
    selected_value = config_path if config_path is not None else os.getenv("TRANSIT_CONFIG")
    selected = Path(selected_value or "configs/local.yaml")
    values = {**base, **_read_yaml(selected)}
    values["api_key"] = os.getenv("TRANSLINK_API_KEY")
    allowed = {field.name for field in fields(Settings)}
    unknown = set(values) - allowed
    if unknown:
        raise ValueError(f"unknown configuration keys: {sorted(unknown)}")
    if "selected_routes" in values:
        values["selected_routes"] = tuple(str(v) for v in values["selected_routes"])
    for key in ("data_dir", "artifact_dir", "report_dir", "frontend_dir"):
        if key in values:
            values[key] = Path(values[key])
    settings = Settings(**values)
    settings.validate()
    return settings
