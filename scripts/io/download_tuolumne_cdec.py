#!/usr/bin/env python3
"""Download and normalize daily CDEC SWE observations for Tuolumne stations."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import urllib.parse
import urllib.request
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_STATIONS = REPO_ROOT / "data/inventories/tuolumne_cdec_station_metadata.csv"
DEFAULT_OUTPUT_ROOT = REPO_ROOT / "data/external/cdec/tuolumne"
ENDPOINT = "https://cdec.water.ca.gov/dynamicapp/req/CSVDataServlet"
RAW_FIELDS = {
    "STATION_ID",
    "DURATION",
    "SENSOR_NUMBER",
    "DATE TIME",
    "OBS DATE",
    "VALUE",
    "DATA_FLAG",
    "UNITS",
}


def sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _read_station_metadata(path: Path) -> dict[str, dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        required = {"station_id", "station_name"}
        if not required.issubset(reader.fieldnames or []):
            raise ValueError(f"station metadata must include {sorted(required)}")
        stations = {
            row["station_id"].strip(): {
                key: (value or "").strip() for key, value in row.items()
            }
            for row in reader
        }
    if not stations or any(not station_id for station_id in stations):
        raise ValueError("station metadata contains no usable station IDs")
    return stations


def _query_url(station_ids: list[str], start: date, end: date) -> str:
    query = urllib.parse.urlencode(
        {
            "Stations": ",".join(station_ids),
            "SensorNums": "3",
            "dur_code": "D",
            "Start": start.isoformat(),
            "End": end.isoformat(),
        }
    )
    return f"{ENDPOINT}?{query}"


def _fetch(url: str) -> bytes:
    request = urllib.request.Request(
        url,
        headers={"Accept": "text/csv", "User-Agent": "nisar-m3-da/0.1"},
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        payload = response.read()
    if not payload:
        raise ValueError("CDEC returned an empty response")
    return payload


def _normalize(
    raw_payload: bytes, station_metadata: dict[str, dict[str, str]]
) -> tuple[list[dict[str, str]], dict[str, dict[str, Any]]]:
    text = raw_payload.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    if not RAW_FIELDS.issubset(reader.fieldnames or []):
        raise ValueError("CDEC response did not contain the expected daily CSV fields")

    normalized: list[dict[str, str]] = []
    stats = {
        station_id: {
            "returned_rows": 0,
            "numeric_rows": 0,
            "non_numeric_value_rows": 0,
            "flagged_rows": 0,
            "first_reported_date": None,
            "last_reported_date": None,
            "first_numeric_date": None,
            "last_numeric_date": None,
        }
        for station_id in station_metadata
    }

    for source_row in reader:
        station_id = source_row["STATION_ID"].strip()
        if station_id not in station_metadata:
            raise ValueError(f"CDEC returned unexpected station {station_id!r}")
        if source_row["DURATION"].strip().upper() != "D":
            raise ValueError("CDEC returned a non-daily row")
        if source_row["SENSOR_NUMBER"].strip() != "3":
            raise ValueError("CDEC returned a sensor other than daily SWE sensor 3")
        units = source_row["UNITS"].strip()
        if units.upper() != "INCHES":
            raise ValueError(f"CDEC SWE units changed unexpectedly: {units!r}")

        record_date = datetime.strptime(
            source_row["DATE TIME"].strip(), "%Y%m%d %H%M"
        ).date()
        record_date_text = record_date.isoformat()
        station = station_metadata[station_id]
        stat = stats[station_id]
        stat["returned_rows"] += 1
        stat["first_reported_date"] = stat["first_reported_date"] or record_date_text
        stat["last_reported_date"] = record_date_text

        source_value = source_row["VALUE"].strip()
        try:
            inches = Decimal(source_value)
        except InvalidOperation:
            inches = None
        if inches is None or not inches.is_finite():
            stat["non_numeric_value_rows"] += 1
            swe_cm = ""
        else:
            # CDEC's daily SWE sensor 3 CSV reports INCHES; retain the source
            # value and apply the exact unit factor used by the existing project
            # table. No missing values are filled and no flags are filtered.
            swe_cm = format((inches * Decimal("2.54")).normalize(), "f")
            stat["numeric_rows"] += 1
            stat["first_numeric_date"] = stat["first_numeric_date"] or record_date_text
            stat["last_numeric_date"] = record_date_text

        flag = source_row["DATA_FLAG"]
        if flag.strip():
            stat["flagged_rows"] += 1
        normalized.append(
            {
                "date": record_date_text,
                "observation_datetime": source_row["DATE TIME"].strip(),
                "obs_date": source_row["OBS DATE"].strip(),
                "value": source_row["VALUE"].strip(),
                "data_flag": flag,
                "units": source_row["UNITS"].strip(),
                "swe_cm": swe_cm,
                "station_id": station_id,
                "station_name": station["station_name"],
                "network": station.get("network", "CDEC"),
                "sensor_num": "3",
                "elev_ft": station.get("elev_ft", ""),
                "elev_m": station.get("elev_m", ""),
                "lat": station.get("lat", ""),
                "lon": station.get("lon", ""),
            }
        )

    normalized.sort(key=lambda row: (row["station_id"], row["date"]))
    return normalized, stats


def _write_csv(path: Path, rows: list[dict[str, str]]) -> bytes:
    fields = [
        "date",
        "observation_datetime",
        "obs_date",
        "value",
        "data_flag",
        "units",
        "swe_cm",
        "station_id",
        "station_name",
        "network",
        "sensor_num",
        "elev_ft",
        "elev_m",
        "lat",
        "lon",
    ]
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    return path.read_bytes()


def _repo_relative(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return str(path.resolve())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", default="2025-10-01", help="first date, YYYY-MM-DD")
    parser.add_argument(
        "--end", default=date.today().isoformat(), help="last date, YYYY-MM-DD"
    )
    parser.add_argument("--station-metadata", type=Path, default=DEFAULT_STATIONS)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument(
        "--raw-csv",
        type=Path,
        help="normalize a previously saved CDEC response instead of making a request",
    )
    parser.add_argument(
        "--manifest-path",
        type=Path,
        help="write the provenance JSON here; default is download_manifest.json",
    )
    args = parser.parse_args()

    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end)
    if end < start:
        parser.error("--end must be on or after --start")

    station_metadata = _read_station_metadata(args.station_metadata)
    station_ids = list(station_metadata)
    output_dir = args.output_dir or (
        DEFAULT_OUTPUT_ROOT / f"{start.isoformat()}_to_{end.isoformat()}"
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    raw_path = output_dir / "cdec_swe_daily_raw.csv"
    normalized_path = output_dir / "cdec_tuolumne_swe_daily_cm.csv"
    manifest_path = args.manifest_path or output_dir / "download_manifest.json"

    query_url = _query_url(station_ids, start, end)
    raw_payload = args.raw_csv.read_bytes() if args.raw_csv else _fetch(query_url)
    raw_path.write_bytes(raw_payload)
    normalized_rows, station_stats = _normalize(raw_payload, station_metadata)
    normalized_payload = _write_csv(normalized_path, normalized_rows)

    manifest = {
        "schema_version": 1,
        "downloaded_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "provider": "California Department of Water Resources, CDEC",
        "endpoint": ENDPOINT,
        "query_url": query_url,
        "query": {
            "station_ids": station_ids,
            "start_date_inclusive": start.isoformat(),
            "end_date_inclusive": end.isoformat(),
            "duration": "D",
            "sensor_number": 3,
            "sensor_type": "SNOW WC",
        },
        "station_metadata_path": _repo_relative(args.station_metadata),
        "station_metadata_sha256": sha256(args.station_metadata.read_bytes()),
        "raw_csv_path": _repo_relative(raw_path),
        "raw_csv_sha256": sha256(raw_payload),
        "raw_csv_bytes": len(raw_payload),
        "normalized_csv_path": _repo_relative(normalized_path),
        "normalized_csv_sha256": sha256(normalized_payload),
        "normalized_rows": len(normalized_rows),
        "normalization": {
            "source_units": "INCHES as reported by CDEC",
            "output_units": "cm",
            "conversion": "source value multiplied by 2.54",
            "missing_values": "non-numeric source values remain blank; no filling",
            "data_flags": "preserved; no flag-based filtering",
        },
        "per_station": station_stats,
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    print(
        f"Saved {len(normalized_rows)} rows for {len(station_ids)} requested stations"
    )
    for station_id, stat in station_stats.items():
        print(
            f"{station_id}: {stat['returned_rows']} rows, "
            f"{stat['numeric_rows']} numeric, "
            f"last reported={stat['last_reported_date']}, "
            f"last numeric={stat['last_numeric_date']}"
        )
    print(f"Raw: {raw_path}")
    print(f"Normalized: {normalized_path}")
    print(f"Manifest: {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
