from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import zipfile
from collections.abc import Iterator
from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from transit_delay.domain import StopEvent, TripInstanceKey
from transit_delay.gtfs.realtime import RealtimeTripUpdate
from transit_delay.gtfs.time import parse_gtfs_time


@dataclass(frozen=True)
class StaticTrip:
    trip_id: str
    route_id: str
    route_short_name: str
    service_id: str
    direction_id: int | None
    start_time: str
    stops: tuple[tuple[int, str, str, str | None], ...]  # sequence, stop_id, time, name
    headsign: str | None = None


@dataclass(frozen=True)
class StaticFeedProfile:
    feed_version: str
    feed_start_date: str
    feed_end_date: str
    sha256: str
    table_rows: dict[str, int]
    has_frequencies: bool


@dataclass(frozen=True)
class JoinFailure:
    reason: str
    trip_id: str | None


@dataclass(frozen=True)
class ResolvedTrip:
    key: TripInstanceKey
    trip: StaticTrip
    stop_events: tuple[StopEvent, ...]


class StaticCatalog:
    def __init__(self, timezone_name: str = "America/Vancouver"):
        self.timezone_name = timezone_name
        self.version = ""
        self.trips: dict[str, StaticTrip] = {}
        self.route_short_names: dict[str, str] = {}
        self.active_dates: dict[str, set[date]] = {}
        self.profile: StaticFeedProfile | None = None

    @classmethod
    def from_zip(cls, path: Path, timezone_name: str = "America/Vancouver") -> StaticCatalog:
        catalog = cls(timezone_name)
        payload = path.read_bytes()
        digest = hashlib.sha256(payload).hexdigest()
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            names = set(archive.namelist())
            required = {"routes.txt", "trips.txt", "stop_times.txt", "feed_info.txt"}
            missing = required - names
            if missing:
                raise ValueError(f"Static GTFS is missing required tables: {sorted(missing)}")
            feed_info = _rows(archive, "feed_info.txt")[0]
            catalog.version = feed_info.get("feed_version") or digest[:12]
            route_names = {
                row["route_id"]: row.get("route_short_name", "")
                for row in _rows(archive, "routes.txt")
            }
            catalog.route_short_names = route_names
            stop_names = (
                {
                    row["stop_id"]: row.get("stop_name") or None
                    for row in _rows(archive, "stops.txt")
                }
                if "stops.txt" in names
                else {}
            )
            stops_by_trip: dict[str, list[tuple[int, str, str, str | None]]] = {}
            table_rows: dict[str, int] = {}
            for name in names:
                if name.endswith(".txt"):
                    table_rows[name.removesuffix(".txt")] = _count_rows(archive, name)
            for row in _iter_rows(archive, "stop_times.txt"):
                arrival = row.get("arrival_time") or row.get("departure_time")
                if not arrival:
                    continue
                stops_by_trip.setdefault(row["trip_id"], []).append(
                    (
                        int(row["stop_sequence"]),
                        row["stop_id"],
                        arrival,
                        stop_names.get(row["stop_id"]),
                    )
                )
            for row in _iter_rows(archive, "trips.txt"):
                stops = tuple(sorted(stops_by_trip.get(row["trip_id"], [])))
                if not stops:
                    continue
                direction = row.get("direction_id", "")
                catalog.trips[row["trip_id"]] = StaticTrip(
                    trip_id=row["trip_id"],
                    route_id=row["route_id"],
                    route_short_name=route_names.get(row["route_id"], ""),
                    service_id=row["service_id"],
                    direction_id=int(direction) if direction != "" else None,
                    start_time=stops[0][2],
                    stops=stops,
                    headsign=row.get("trip_headsign") or None,
                )
            catalog.active_dates = _active_service_dates(archive)
            catalog.profile = StaticFeedProfile(
                catalog.version,
                feed_info.get("feed_start_date", ""),
                feed_info.get("feed_end_date", ""),
                digest,
                table_rows,
                "frequencies.txt" in names,
            )
        return catalog

    def resolve(
        self, update: RealtimeTripUpdate, received_at: datetime
    ) -> ResolvedTrip | JoinFailure:
        if update.relationship not in {"SCHEDULED", ""}:
            return JoinFailure(f"unsupported_relationship:{update.relationship}", update.trip_id)
        if not update.trip_id:
            return JoinFailure("missing_trip_id", None)
        trip = self.trips.get(update.trip_id)
        if not trip:
            return JoinFailure("unknown_trip_id", update.trip_id)
        if update.route_id and update.route_id != trip.route_id:
            return JoinFailure("route_id_mismatch", update.trip_id)
        service_date = (
            datetime.strptime(update.start_date, "%Y%m%d").date()
            if update.start_date
            else received_at.astimezone(ZoneInfo(self.timezone_name)).date()
        )
        if service_date not in self.active_dates.get(trip.service_id, set()):
            return JoinFailure("inactive_service_date", update.trip_id)
        key = TripInstanceKey(self.version, service_date, trip.trip_id, update.start_time)
        events = tuple(
            StopEvent(
                sequence,
                stop_id,
                parse_gtfs_time(service_date, arrival, self.timezone_name),
                stop_name=stop_name,
            )
            for sequence, stop_id, arrival, stop_name in trip.stops
        )
        return ResolvedTrip(key, trip, events)

    def write_profile(self, path: Path) -> None:
        if self.profile is None:
            raise RuntimeError("catalog has no loaded feed")
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(asdict(self.profile), indent=2, sort_keys=True))
        os.replace(temporary, path)


def archive_static_zip(payload: bytes, root: Path) -> Path:
    digest = hashlib.sha256(payload).hexdigest()
    target = root / "raw" / "static" / f"{digest}.zip"
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        temporary = target.with_suffix(".tmp")
        temporary.write_bytes(payload)
        os.replace(temporary, target)
    return target


def _iter_rows(archive: zipfile.ZipFile, name: str) -> Iterator[dict[str, str]]:
    with archive.open(name) as raw:
        text = io.TextIOWrapper(raw, encoding="utf-8-sig", newline="")
        yield from csv.DictReader(text)


def _rows(archive: zipfile.ZipFile, name: str) -> list[dict[str, str]]:
    return list(_iter_rows(archive, name))


def _count_rows(archive: zipfile.ZipFile, name: str) -> int:
    return sum(1 for _ in _iter_rows(archive, name))


def _active_service_dates(archive: zipfile.ZipFile) -> dict[str, set[date]]:
    from datetime import timedelta

    active: dict[str, set[date]] = {}
    names = set(archive.namelist())
    if "calendar.txt" in names:
        weekdays = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
        for row in _iter_rows(archive, "calendar.txt"):
            current = datetime.strptime(row["start_date"], "%Y%m%d").date()
            end = datetime.strptime(row["end_date"], "%Y%m%d").date()
            service_dates = active.setdefault(row["service_id"], set())
            while current <= end:
                if row[weekdays[current.weekday()]] == "1":
                    service_dates.add(current)
                current += timedelta(days=1)
    if "calendar_dates.txt" in names:
        for row in _iter_rows(archive, "calendar_dates.txt"):
            service_date = datetime.strptime(row["date"], "%Y%m%d").date()
            values = active.setdefault(row["service_id"], set())
            if row["exception_type"] == "1":
                values.add(service_date)
            elif row["exception_type"] == "2":
                values.discard(service_date)
    return active
