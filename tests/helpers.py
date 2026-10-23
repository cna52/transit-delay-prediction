from __future__ import annotations

import csv
import io
import zipfile
from pathlib import Path


def write_static_fixture(path: Path) -> None:
    tables = {
        "feed_info.txt": [
            [
                "feed_publisher_name",
                "feed_publisher_url",
                "feed_lang",
                "feed_start_date",
                "feed_end_date",
                "feed_version",
            ],
            ["TransLink", "https://translink.ca", "en", "20260101", "20261231", "fixture-v1"],
        ],
        "routes.txt": [
            ["route_id", "agency_id", "route_short_name", "route_long_name", "route_type"],
            ["r99", "TL", "099", "Broadway", "3"],
        ],
        "trips.txt": [
            ["route_id", "service_id", "trip_id", "trip_headsign", "direction_id"],
            ["r99", "daily", "trip-1", "UBC", "0"],
        ],
        "stops.txt": [
            ["stop_id", "stop_name", "stop_lat", "stop_lon"],
            ["s1", "Commercial–Broadway Station", "49.262", "-123.069"],
            ["s2", "Broadway at Main Street", "49.263", "-123.101"],
            ["s3", "Broadway at Cambie Street", "49.263", "-123.115"],
            ["s4", "UBC Exchange", "49.267", "-123.247"],
        ],
        "stop_times.txt": [
            ["trip_id", "arrival_time", "departure_time", "stop_id", "stop_sequence"],
            ["trip-1", "23:50:00", "23:50:00", "s1", "1"],
            ["trip-1", "24:05:00", "24:05:00", "s2", "2"],
            ["trip-1", "24:15:00", "24:15:00", "s3", "3"],
            ["trip-1", "24:25:00", "24:25:00", "s4", "4"],
        ],
        "calendar.txt": [
            [
                "service_id",
                "monday",
                "tuesday",
                "wednesday",
                "thursday",
                "friday",
                "saturday",
                "sunday",
                "start_date",
                "end_date",
            ],
            ["daily", "1", "1", "1", "1", "1", "1", "1", "20260101", "20261231"],
        ],
    }
    with zipfile.ZipFile(path, "w") as archive:
        for name, rows in tables.items():
            buffer = io.StringIO()
            csv.writer(buffer, lineterminator="\n").writerows(rows)
            archive.writestr(name, buffer.getvalue())
