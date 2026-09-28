#!/usr/bin/env python3
"""Inventory the three chartered ASO Tuolumne packages without changing source data."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import mimetypes
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import rasterio
from rasterio.warp import transform_geom
from shapely.geometry import Polygon, mapping, shape
from shapely.ops import unary_union

SURVEYS = {
    "ASO_Tuolumne_2026Jan31-Feb01_AllData_and_Reports": (
        "2026-01-31",
        "2026-02-01",
    ),
    "ASO_Tuolumne_2026Feb27-28_SurveyData_and_Reports": (
        "2026-02-27",
        "2026-02-28",
    ),
    "ASO_Tuolumne_2026Apr06_SurveyData_and_Reports": (
        "2026-04-06",
        "2026-04-06",
    ),
}

FIELDS = [
    "inventory_created_utc",
    "dataset",
    "provider",
    "provider_product_version",
    "survey_start",
    "survey_end",
    "source_package_dir",
    "relative_path",
    "file_name",
    "file_type",
    "asset_role",
    "asset_role_evidence",
    "file_size_bytes",
    "sha256",
    "units",
    "units_evidence",
    "crs",
    "transform",
    "resolution",
    "width",
    "height",
    "band_count",
    "dtypes",
    "nodata",
    "bounds",
    "raster_tags",
    "band_tags",
    "raster_error",
    "sidecar_files",
    "related_text_reports",
]


def json_cell(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def sha256_file(path: Path, block_size: int = 8 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(block_size), b""):
            digest.update(block)
    return digest.hexdigest()


def survey_dates(package: Path) -> tuple[str, str]:
    for package_name, dates in SURVEYS.items():
        if package.name == package_name:
            return dates
    raise ValueError(f"Unrecognized ASO package directory: {package}")


def read_text_evidence(package: Path) -> dict[str, dict[str, str]]:
    evidence: dict[str, dict[str, str]] = {}
    for report in package.rglob("*.txt"):
        content = report.read_text(encoding="utf-8", errors="replace")
        file_reference = re.search(
            r"^\s*SWE File Used:\s*(.+?)\s*$", content, re.IGNORECASE | re.MULTILINE
        )
        unit = re.search(
            r"^\s*mean\s+swe\s*\(([^)]+)\)\s*:",
            content,
            re.IGNORECASE | re.MULTILINE,
        )
        depth_unit = re.search(
            r"^\s*mean\s+depth\s*\(([^)]+)\)\s*:",
            content,
            re.IGNORECASE | re.MULTILINE,
        )
        if not file_reference:
            continue
        source_name = Path(file_reference.group(1).strip()).name
        source_stem = Path(source_name).stem
        version = re.search(r"USCATE\d{8}v\d+", file_reference.group(1))
        item = evidence.setdefault(
            source_stem,
            {
                "report": "",
                "source_reference": file_reference.group(1).strip(),
                "units": "",
                "unit_report": "",
                "depth_units": "",
                "depth_unit_report": "",
                "version": "",
            },
        )
        if unit:
            item["units"] = unit.group(1).strip()
            item["unit_report"] = report.relative_to(package).as_posix()
        if depth_unit:
            item["depth_units"] = depth_unit.group(1).strip()
            item["depth_unit_report"] = report.relative_to(package).as_posix()
        if version:
            item["version"] = version.group(0)
        if report.suffix.lower() == ".txt" and "_swe_report" in report.name:
            item["report"] = report.relative_to(package).as_posix()
    return evidence


def identify_asset(
    path: Path, report_evidence: dict[str, dict[str, str]]
) -> tuple[str, str]:
    if path.suffix.lower() in {".tif", ".tiff"}:
        if path.stem in report_evidence:
            return "swe_raster", "matched SWE File Used entry in package text report"
        name = path.stem.lower()
        if "snowdepth" in name or "snow_depth" in name:
            return "snow_depth_raster_candidate", "filename label"
        if "uncertainty" in name or "quality" in name or "_qa" in name:
            return "quality_or_uncertainty_candidate", "filename label"
        if "albedo" in name:
            return "albedo_raster", "filename label"
        return "raster_unclassified", "no product role verified"
    if path.suffix.lower() == ".pdf":
        return "report_pdf", "file extension"
    if path.suffix.lower() == ".txt":
        return "report_text", "file extension"
    if path.suffix.lower() == ".csv":
        return "summary_table", "file extension"
    if path.name.endswith(".aux.xml"):
        return "raster_sidecar", "GDAL auxiliary XML filename"
    return "other_file", "file extension or package inventory"


def raster_metadata(path: Path) -> dict[str, Any]:
    with rasterio.open(path) as dataset:
        tags = dataset.tags()
        band_tags = [dataset.tags(index) for index in range(1, dataset.count + 1)]
        units = list(dataset.units or ())
        tag_units = next(
            (
                value
                for key, value in tags.items()
                if key.lower() in {"units", "unittype"}
            ),
            "",
        )
        return {
            "crs": dataset.crs.to_string() if dataset.crs else "",
            "transform": list(dataset.transform),
            "resolution": list(dataset.res),
            "width": dataset.width,
            "height": dataset.height,
            "band_count": dataset.count,
            "dtypes": list(dataset.dtypes),
            "nodata": "NaN"
            if isinstance(dataset.nodata, float) and math.isnan(dataset.nodata)
            else dataset.nodata,
            "bounds": list(dataset.bounds),
            "raster_tags": tags,
            "band_tags": band_tags,
            "raster_units": units,
            "tag_units": tag_units,
        }


def raster_footprint(path: Path) -> dict[str, Any]:
    with rasterio.open(path) as dataset:
        if not dataset.crs:
            raise ValueError(f"SWE raster has no CRS: {path}")
        bounds = dataset.bounds
        polygon = Polygon(
            [
                (bounds.left, bounds.bottom),
                (bounds.right, bounds.bottom),
                (bounds.right, bounds.top),
                (bounds.left, bounds.top),
                (bounds.left, bounds.bottom),
            ]
        )
        return transform_geom(
            dataset.crs,
            "EPSG:4326",
            mapping(polygon),
            precision=10,
        )


def inventory_package(
    package: Path, created: str
) -> tuple[list[dict[str, str]], list[Path]]:
    start, end = survey_dates(package)
    report_evidence = read_text_evidence(package)
    package_version = next(
        (item["version"] for item in report_evidence.values() if item["version"]), ""
    )
    package_depth_unit = next(
        (item for item in report_evidence.values() if item["depth_units"]), {}
    )
    files = sorted(path for path in package.rglob("*") if path.is_file())
    rows: list[dict[str, str]] = []
    swe_rasters: list[Path] = []
    report_paths = [
        path.relative_to(package).as_posix()
        for path in files
        if path.suffix.lower() in {".txt", ".pdf"}
    ]

    for index, path in enumerate(files, start=1):
        role, role_evidence = identify_asset(path, report_evidence)
        report = report_evidence.get(path.stem, {})
        if role == "swe_raster":
            swe_rasters.append(path)
        row: dict[str, str] = {
            "inventory_created_utc": created,
            "dataset": package.name,
            "provider": "Airborne Snow Observatories, Inc. (ASO)",
            "provider_product_version": package_version,
            "survey_start": start,
            "survey_end": end,
            "source_package_dir": str(package.resolve()),
            "relative_path": path.relative_to(package).as_posix(),
            "file_name": path.name,
            "file_type": mimetypes.guess_type(path.name)[0] or path.suffix.lower(),
            "asset_role": role,
            "asset_role_evidence": role_evidence,
            "file_size_bytes": str(path.stat().st_size),
            "sha256": "",
            "units": "",
            "units_evidence": "",
            "crs": "",
            "transform": "",
            "resolution": "",
            "width": "",
            "height": "",
            "band_count": "",
            "dtypes": "",
            "nodata": "",
            "bounds": "",
            "raster_tags": "",
            "band_tags": "",
            "raster_error": "",
            "sidecar_files": "",
            "related_text_reports": json_cell(report_paths),
        }
        if path.suffix.lower() in {".tif", ".tiff"}:
            try:
                metadata = raster_metadata(path)
                for field in (
                    "crs",
                    "transform",
                    "resolution",
                    "width",
                    "height",
                    "band_count",
                    "dtypes",
                    "nodata",
                    "bounds",
                    "raster_tags",
                    "band_tags",
                ):
                    row[field] = (
                        json_cell(metadata[field])
                        if isinstance(metadata[field], (list, dict))
                        else str(metadata[field])
                    )
                raster_units = [unit for unit in metadata["raster_units"] if unit]
                if raster_units:
                    row["units"] = json_cell(raster_units)
                    row["units_evidence"] = "GeoTIFF band unit metadata"
                elif metadata["tag_units"]:
                    row["units"] = str(metadata["tag_units"])
                    row["units_evidence"] = "GeoTIFF dataset unit tag"
                elif report.get("units"):
                    row["units"] = report["units"]
                    row["units_evidence"] = (
                        f"mean SWE unit in {report['unit_report']}; "
                        "the report identifies this raster as SWE input"
                    )
                elif role == "snow_depth_raster_candidate" and package_depth_unit:
                    row["units_evidence"] = (
                        f"package report gives mean depth in "
                        f"{package_depth_unit['depth_units']} "
                        f"({package_depth_unit['depth_unit_report']}); "
                        "exact raster linkage is not stated"
                    )
                sidecar = Path(f"{path}.aux.xml")
                row["sidecar_files"] = json_cell(
                    [sidecar.name] if sidecar.is_file() else []
                )
            except (
                Exception
            ) as error:  # Keep the inventory row if a raster is unreadable.
                row["raster_error"] = f"{type(error).__name__}: {error}"
        if index == 1 or index % 10 == 0 or path.stat().st_size >= 50_000_000:
            print(
                f"{package.name}: hashing file {index}/{len(files)} ({path.name})",
                file=sys.stderr,
                flush=True,
            )
        row["sha256"] = sha256_file(path)
        rows.append(row)

    if len(swe_rasters) != 1:
        raise ValueError(
            f"Expected one SWE raster corroborated by a package report in {package}; "
            f"found {len(swe_rasters)}. Review the text report and raster inventory."
        )
    return rows, swe_rasters


def write_aoi(swe_rasters: list[Path], path: Path, created: str) -> None:
    geometries = [shape(raster_footprint(raster)) for raster in swe_rasters]
    union = unary_union(geometries)
    if union.is_empty or union.geom_type not in {"Polygon", "MultiPolygon"}:
        raise ValueError(
            f"ASO SWE raster footprint union is not polygonal: {union.geom_type}"
        )
    document = {
        "type": "FeatureCollection",
        "name": "tuolumne_aso_swe_footprint_union",
        "properties": {
            "created_utc": created,
            "source": "union of source SWE GeoTIFF rectangular bounds",
            "source_rasters": [str(raster.resolve()) for raster in swe_rasters],
            "crs": "EPSG:4326",
        },
        "features": [
            {
                "type": "Feature",
                "properties": {},
                "geometry": mapping(union),
            }
        ],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--aso-root",
        required=True,
        type=Path,
        help="Directory containing the three ASO Tuolumne source packages.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/inventories/tuolumne_aso.csv"),
    )
    parser.add_argument(
        "--aoi-output",
        type=Path,
        default=Path("data/inventories/tuolumne_aso_aoi.geojson"),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = args.aso_root.expanduser().resolve()
    if not root.is_dir():
        raise SystemExit(f"ASO root is not a directory: {root}")
    packages = [root / name for name in SURVEYS]
    missing = [str(package) for package in packages if not package.is_dir()]
    if missing:
        raise SystemExit("Missing chartered ASO package(s):\n" + "\n".join(missing))

    created = datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
    all_rows: list[dict[str, str]] = []
    swe_rasters: list[Path] = []
    for package in packages:
        rows, rasters = inventory_package(package, created)
        all_rows.extend(rows)
        swe_rasters.extend(rasters)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(all_rows)
    write_aoi(swe_rasters, args.aoi_output, created)

    print(f"Wrote {len(all_rows)} file records to {args.output}")
    print(f"Wrote ASO SWE footprint union to {args.aoi_output}")
    for package in packages:
        count = sum(row["dataset"] == package.name for row in all_rows)
        print(f"{package.name}: {count} files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
