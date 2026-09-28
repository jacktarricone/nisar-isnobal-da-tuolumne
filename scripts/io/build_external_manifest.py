#!/usr/bin/env python3
"""Combine ASO file metadata and ASF catalog metadata into a compact manifest."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

FIELDS = [
    "inventory_created_utc",
    "dataset",
    "provider",
    "product",
    "maturity",
    "version",
    "collection_version",
    "crid",
    "product_version",
    "identifier",
    "collection_concept_id",
    "granule_concept_id",
    "basin",
    "track_frame",
    "orbit_direction",
    "acquisition_start",
    "acquisition_end",
    "units",
    "crs",
    "resolution",
    "local_expected_path",
    "download_method",
    "persistent_identifier",
    "study_role",
    "independence_category",
    "checksum_algorithm",
    "checksum",
    "file_size_bytes",
    "source_metadata_uri",
    "notes",
]


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def attr_values(granule: dict[str, Any], name: str) -> list[str]:
    values = granule.get("additional_attributes", {}).get(name, [])
    return [str(value) for value in values]


def first_value(granule: dict[str, Any], name: str) -> str:
    values = attr_values(granule, name)
    return values[0] if values else ""


def pair_frame(granule: dict[str, Any]) -> str:
    track = first_value(granule, "TRACK_NUMBER")
    frame = first_value(granule, "FRAME_NUMBER")
    if not track.isdigit() or not frame.isdigit():
        return ""
    return f"T{int(track):03d}/F{int(frame):03d}"


def maturity_slug(value: str) -> str:
    return value.casefold()


def main_hdf5_file(granule: dict[str, Any]) -> dict[str, Any]:
    granule_stem = Path(str(granule.get("granule_ur", ""))).name
    return next(
        (
            item
            for item in granule.get("file_records", [])
            if str(item.get("Format", "")).upper() == "HDF5"
            and Path(str(item.get("Name", ""))).stem == granule_stem
        ),
        {},
    )


def nisar_manifest_rows(path: Path, document: dict[str, Any]) -> list[dict[str, str]]:
    maturity = str(document["maturity"])
    rows: list[dict[str, str]] = []
    for granule in document.get("granules", []):
        hdf5 = main_hdf5_file(granule)
        product_identifiers = granule.get("product_identifiers", [])
        crid = next(
            (
                str(item.get("Identifier", ""))
                for item in product_identifiers
                if item.get("IdentifierType", "").upper() == "CRID"
            ),
            "",
        )
        product_version = first_value(granule, "PRODUCT_VERSION")
        source_url = next(
            (
                str(item.get("URL", ""))
                for item in granule.get("related_urls", [])
                if item.get("Type", "").upper()
                in {"GET DATA", "GET DATA VIA DIRECT ACCESS"}
            ),
            "",
        )
        granule_name = str(hdf5.get("Name", granule.get("granule_ur", "")))
        frame = pair_frame(granule)
        lower = maturity_slug(maturity)
        local_path = (
            f"/Users/jtarrico/ch13_nisar_prelim/data/nisar/gunw/tuolumne/"
            f"{lower}/<track_frame>/{granule_name}"
        )
        reference_time = first_value(granule, "REFERENCE_ZERO_DOPPLER_START_TIME")
        secondary_time = first_value(granule, "SECONDARY_ZERO_DOPPLER_START_TIME")
        checksum = hdf5.get("Checksum", {})
        rows.append(
            {
                "inventory_created_utc": str(document["inventory_created_utc"]),
                "dataset": f"NISAR L2 GUNW {maturity}",
                "provider": "NASA ASF DAAC / CMR",
                "product": "NISAR L2 Geocoded Unwrapped Interferogram",
                "maturity": maturity,
                "version": product_version,
                "collection_version": str(granule.get("collection_version", "")),
                "crid": crid,
                "product_version": product_version,
                "identifier": str(granule.get("granule_ur", "")),
                "collection_concept_id": str(granule.get("collection_concept_id", "")),
                "granule_concept_id": str(granule.get("granule_concept_id", "")),
                "basin": "Tuolumne River Basin",
                "track_frame": frame,
                "orbit_direction": first_value(granule, "ASCENDING_DESCENDING"),
                "acquisition_start": reference_time,
                "acquisition_end": secondary_time,
                "units": "",
                "crs": "",
                "resolution": "",
                "local_expected_path": local_path,
                "download_method": (
                    "Not downloaded; URL recorded from current CMR metadata"
                ),
                "persistent_identifier": str(granule.get("granule_concept_id", "")),
                "study_role": "inventory_only; no retrieval role assigned",
                "independence_category": "",
                "checksum_algorithm": str(checksum.get("Algorithm", "")),
                "checksum": str(checksum.get("Value", "")),
                "file_size_bytes": str(hdf5.get("SizeInBytes", "")),
                "source_metadata_uri": source_url
                or f"https://cmr.earthdata.nasa.gov/search/concepts/"
                f"{granule.get('granule_concept_id', '')}.umm_json",
                "notes": (
                    "Checksum and size are CMR-reported, not locally verified."
                    if hdf5
                    else "CMR did not return an exact main-GUNW HDF5 file record."
                ),
            }
        )
    if document.get("granule_count") != len(rows):
        raise ValueError(f"Granule count mismatch in {path}")
    return rows


def aso_manifest_rows(path: Path) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    with path.open(newline="", encoding="utf-8") as stream:
        for item in csv.DictReader(stream):
            package = item["dataset"]
            raster_role = item["asset_role"]
            survey = f"{item['survey_start']} to {item['survey_end']}"
            rows.append(
                {
                    "inventory_created_utc": item["inventory_created_utc"],
                    "dataset": package,
                    "provider": item["provider"],
                    "product": raster_role,
                    "maturity": "",
                    "version": item["provider_product_version"],
                    "collection_version": "",
                    "crid": "",
                    "product_version": item["provider_product_version"],
                    "identifier": item["relative_path"],
                    "collection_concept_id": "",
                    "granule_concept_id": "",
                    "basin": "Tuolumne River Basin",
                    "track_frame": "",
                    "orbit_direction": "",
                    "acquisition_start": item["survey_start"],
                    "acquisition_end": item["survey_end"],
                    "units": item["units"],
                    "crs": item["crs"],
                    "resolution": item["resolution"],
                    "local_expected_path": str(
                        Path(item["source_package_dir"]) / item["relative_path"]
                    ),
                    "download_method": "Provided local source package",
                    "persistent_identifier": "",
                    "study_role": "inventory_only; package purpose is in charter",
                    "independence_category": "",
                    "checksum_algorithm": "SHA-256" if item["sha256"] else "",
                    "checksum": item["sha256"],
                    "file_size_bytes": item["file_size_bytes"],
                    "source_metadata_uri": "",
                    "notes": "; ".join(
                        part
                        for part in (
                            f"Survey {survey}",
                            item["asset_role_evidence"],
                            item["units_evidence"],
                        )
                        if part
                    ),
                }
            )
    return rows


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--aso-inventory",
        type=Path,
        default=Path("data/inventories/tuolumne_aso.csv"),
    )
    parser.add_argument(
        "--beta-inventory",
        type=Path,
        default=Path("data/inventories/tuolumne_nisar_beta.json"),
    )
    parser.add_argument(
        "--provisional-inventory",
        type=Path,
        default=Path("data/inventories/tuolumne_nisar_provisional_all.json"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/manifests/external_data_manifest.csv"),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    required = [args.aso_inventory, args.beta_inventory, args.provisional_inventory]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise SystemExit("Missing source inventory file(s):\n" + "\n".join(missing))
    rows = aso_manifest_rows(args.aso_inventory)
    for path in (args.beta_inventory, args.provisional_inventory):
        rows.extend(nisar_manifest_rows(path, load_json(path)))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    print(f"Wrote {len(rows)} external-data records to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
