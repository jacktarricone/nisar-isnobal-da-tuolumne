#!/usr/bin/env python3
"""Read-only structural validator for local NISAR GUNW HDF5 products."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import h5py

GUNW_GRID_ROOT = "/science/LSAR/GUNW/grids"
REQUIRED_LAYERS = ("unwrappedPhase", "coherenceMagnitude", "connectedComponents")


def json_value(value: Any) -> Any:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if hasattr(value, "tolist"):
        return json_value(value.tolist())
    if hasattr(value, "item"):
        return json_value(value.item())
    if isinstance(value, dict):
        return {str(key): json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_value(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        if math.isnan(value):
            return "NaN"
        return "Infinity" if value > 0 else "-Infinity"
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def file_checksums(path: Path) -> dict[str, str]:
    digests = {"sha256": hashlib.sha256(), "md5": hashlib.md5(usedforsecurity=False)}
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            for digest in digests.values():
                digest.update(block)
    return {name: digest.hexdigest() for name, digest in digests.items()}


def object_attributes(obj: h5py.Group | h5py.Dataset) -> dict[str, Any]:
    return {key: json_value(value) for key, value in obj.attrs.items()}


def dataset_record(path: str, dataset: h5py.Dataset) -> dict[str, Any]:
    return {
        "path": path,
        "shape": list(dataset.shape),
        "dtype": str(dataset.dtype),
        "chunks": list(dataset.chunks) if dataset.chunks else None,
        "compression": dataset.compression,
        "fill_value": json_value(dataset.fillvalue),
        "attributes": object_attributes(dataset),
    }


def load_catalog_records(paths: list[Path]) -> dict[str, dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    for catalog_path in paths:
        document = json.loads(catalog_path.read_text(encoding="utf-8"))
        for record in document.get("granules", []):
            for file_record in record.get("file_records", []):
                name = file_record.get("Name")
                granule_stem = Path(str(record.get("granule_ur", ""))).name
                if (
                    name
                    and file_record.get("Format", "").upper() == "HDF5"
                    and Path(str(name)).stem == granule_stem
                ):
                    records[str(name)] = record
    return records


def catalog_summary(record: dict[str, Any]) -> dict[str, Any]:
    attributes = record.get("additional_attributes", {})
    return {
        "maturity": record.get("maturity", ""),
        "collection_short_name": record.get("collection_short_name", ""),
        "collection_version": record.get("collection_version", ""),
        "collection_concept_id": record.get("collection_concept_id", ""),
        "granule_concept_id": record.get("granule_concept_id", ""),
        "granule_ur": record.get("granule_ur", ""),
        "track": attributes.get("TRACK_NUMBER", []),
        "frame": attributes.get("FRAME_NUMBER", []),
        "orbit_direction": attributes.get("ASCENDING_DESCENDING", []),
        "polarization": attributes.get("FREQUENCY_A_POLARIZATION", []),
        "reference_zero_doppler": {
            name: values
            for name, values in attributes.items()
            if name.startswith("REFERENCE_ZERO_DOPPLER_")
        },
        "secondary_zero_doppler": {
            name: values
            for name, values in attributes.items()
            if name.startswith("SECONDARY_ZERO_DOPPLER_")
        },
        "crid_identifiers": [
            item
            for item in record.get("product_identifiers", [])
            if item.get("IdentifierType", "").upper() == "CRID"
        ],
        "product_version": attributes.get("PRODUCT_VERSION", []),
        "hdf5_files": record.get("file_records", []),
        "related_urls": record.get("related_urls", []),
        "raw_cmr_metadata": record.get("raw_cmr_metadata", {}),
    }


def inspect_product(
    path: Path, catalog_record: dict[str, Any] | None = None
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "schema_version": 1,
        "validated_utc": datetime.now(UTC)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z"),
        "path": str(path.resolve()),
        "granule_id_from_filename": path.name,
        "file_size_bytes": path.stat().st_size,
        "sha256": "",
        "checksums": {},
        "catalog_match": catalog_record is not None,
        "catalog_metadata": catalog_summary(catalog_record) if catalog_record else {},
        "is_hdf5": False,
        "valid": False,
        "errors": [],
        "warnings": [],
        "root_attributes": {},
        "datasets": [],
        "groups": [],
        "unwrapped_grids": [],
        "projection_metadata": [],
        "product_metadata_values": [],
        "acquisition_and_processing_metadata": {},
        "optional_correction_layers": [],
        "validation_basis": {
            "required_layers": list(REQUIRED_LAYERS),
            "specification_group": GUNW_GRID_ROOT,
            "pixel_values_read": False,
        },
    }
    result["checksums"] = file_checksums(path)
    result["sha256"] = result["checksums"]["sha256"]
    if catalog_record:
        main_file = next(
            (
                item
                for item in catalog_record.get("file_records", [])
                if item.get("Format", "").upper() == "HDF5"
                and Path(str(item.get("Name", ""))).stem
                == Path(str(catalog_record.get("granule_ur", ""))).name
            ),
            {},
        )
        expected_size = main_file.get("SizeInBytes")
        if expected_size is not None and int(expected_size) != path.stat().st_size:
            result["errors"].append(
                f"Local file size {path.stat().st_size} differs from CMR size "
                f"{expected_size}"
            )
        expected_checksum = main_file.get("Checksum", {})
        algorithm = str(expected_checksum.get("Algorithm", "")).casefold()
        expected_value = str(expected_checksum.get("Value", "")).casefold()
        if algorithm in result["checksums"] and expected_value:
            result["catalog_checksum_match"] = (
                result["checksums"][algorithm].casefold() == expected_value
            )
            if not result["catalog_checksum_match"]:
                result["errors"].append(
                    f"Local {algorithm} checksum does not match CMR metadata"
                )
        else:
            result["warnings"].append(
                "CMR checksum absent or uses an algorithm not computed by this "
                "validator"
            )
    else:
        result["warnings"].append(
            "No matching CMR inventory record; external maturity/version metadata "
            "unavailable"
        )
    try:
        with h5py.File(path, "r") as handle:
            result["is_hdf5"] = True
            result["root_attributes"] = object_attributes(handle)
            group_paths: list[str] = []
            metadata_attributes: dict[str, Any] = {}
            projection_paths: list[str] = []
            optional_paths: list[str] = []
            metadata_values: list[dict[str, Any]] = []

            def visit(name: str, obj: h5py.Group | h5py.Dataset) -> None:
                full_path = f"/{name}"
                if isinstance(obj, h5py.Dataset):
                    result["datasets"].append(dataset_record(full_path, obj))
                    path_lower = full_path.casefold()
                    scalar_metadata_tokens = (
                        "wavelength",
                        "epsg",
                        "projection",
                        "coordinatereference",
                        "referencedatetime",
                        "secondarydatetime",
                        "zerodoppler",
                        "rangepixelspacing",
                        "xcoordinatespacing",
                        "ycoordinatespacing",
                        "tracknumber",
                        "framenumber",
                        "productversion",
                    )
                    if obj.size <= 100 and any(
                        token in path_lower for token in scalar_metadata_tokens
                    ):
                        metadata_values.append(
                            {"path": full_path, "value": json_value(obj[()])}
                        )
                elif isinstance(obj, h5py.Group):
                    group_paths.append(full_path)
                attrs = object_attributes(obj)
                if attrs:
                    metadata_attributes[full_path] = attrs
                if (
                    isinstance(obj, h5py.Dataset)
                    and obj.name.rsplit("/", 1)[-1] == "projection"
                ):
                    projection_paths.append(full_path)
                if isinstance(obj, h5py.Dataset) and any(
                    token in full_path.casefold()
                    for token in ("ionosphere", "troposphere", "solidearthtides")
                ):
                    optional_paths.append(full_path)

            handle.visititems(visit)
            result["groups"] = group_paths
            result["product_metadata_values"] = metadata_values
            result["projection_metadata"] = [
                {
                    "path": projection_path,
                    "attributes": metadata_attributes.get(projection_path, {}),
                    "value": (
                        json_value(handle[projection_path][()])
                        if handle[projection_path].size <= 100
                        else "not read: dataset contains more than 100 values"
                    ),
                }
                for projection_path in projection_paths
            ]
            result["acquisition_and_processing_metadata"] = {
                object_path: attributes
                for object_path, attributes in metadata_attributes.items()
                if any(
                    token in (object_path + " " + " ".join(attributes)).casefold()
                    for token in (
                        "reference",
                        "secondary",
                        "acquisition",
                        "zerodoppler",
                        "track",
                        "frame",
                        "orbit",
                        "polarization",
                        "wavelength",
                        "crid",
                        "processing",
                        "maturity",
                    )
                )
            }
            result["optional_correction_layers"] = sorted(optional_paths)

            if GUNW_GRID_ROOT not in handle:
                result["errors"].append(f"Missing expected grid group {GUNW_GRID_ROOT}")
            else:
                grids = handle[GUNW_GRID_ROOT]
                for frequency_name in sorted(grids.keys()):
                    frequency = grids[frequency_name]
                    group_name = "unwrappedInterferogram"
                    if (
                        not isinstance(frequency, h5py.Group)
                        or group_name not in frequency
                    ):
                        continue
                    unwrapped = frequency[group_name]
                    for polarization in sorted(unwrapped.keys()):
                        pol_group = unwrapped[polarization]
                        if not isinstance(pol_group, h5py.Group):
                            continue
                        present = [
                            name
                            for name in REQUIRED_LAYERS
                            if name in pol_group
                            and isinstance(pol_group[name], h5py.Dataset)
                        ]
                        if not present:
                            continue
                        layer_records = {
                            name: dataset_record(pol_group[name].name, pol_group[name])
                            for name in present
                        }
                        missing = [
                            name
                            for name in REQUIRED_LAYERS
                            if name not in layer_records
                        ]
                        errors = [
                            f"Missing required layer {name} in {pol_group.name}"
                            for name in missing
                        ]
                        shapes = {
                            name: record["shape"]
                            for name, record in layer_records.items()
                        }
                        if len({tuple(shape) for shape in shapes.values()}) > 1:
                            errors.append(
                                f"Core layer dimensions disagree in {pol_group.name}"
                            )
                        result["unwrapped_grids"].append(
                            {
                                "frequency": frequency_name,
                                "polarization": polarization,
                                "group_path": pol_group.name,
                                "layers": layer_records,
                                "layer_shapes": shapes,
                                "errors": errors,
                            }
                        )
                        result["errors"].extend(errors)
                if not result["unwrapped_grids"]:
                    result["errors"].append(
                        "No frequency/unwrappedInterferogram/polarization grid with "
                        "core layers found"
                    )
            if not result["projection_metadata"]:
                result["warnings"].append(
                    "No dataset named projection was found; CRS must be checked "
                    "against product metadata"
                )
            if catalog_record:
                attributes = catalog_record.get("additional_attributes", {})
                expected_metadata = {
                    "maturity": bool(catalog_record.get("maturity")),
                    "collection_version": bool(
                        catalog_record.get("collection_version")
                    ),
                    "track": bool(attributes.get("TRACK_NUMBER")),
                    "frame": bool(attributes.get("FRAME_NUMBER")),
                    "orbit_direction": bool(attributes.get("ASCENDING_DESCENDING")),
                    "polarization": bool(attributes.get("FREQUENCY_A_POLARIZATION")),
                    "crid": any(
                        item.get("IdentifierType", "").upper() == "CRID"
                        for item in catalog_record.get("product_identifiers", [])
                    ),
                    "product_version": bool(attributes.get("PRODUCT_VERSION")),
                    "reference_zero_doppler": bool(
                        attributes.get("REFERENCE_ZERO_DOPPLER_START_TIME")
                        and attributes.get("REFERENCE_ZERO_DOPPLER_END_TIME")
                    ),
                    "secondary_zero_doppler": bool(
                        attributes.get("SECONDARY_ZERO_DOPPLER_START_TIME")
                        and attributes.get("SECONDARY_ZERO_DOPPLER_END_TIME")
                    ),
                }
                result["catalog_metadata_checks"] = expected_metadata
                missing_metadata = [
                    name for name, present in expected_metadata.items() if not present
                ]
                if missing_metadata:
                    result["warnings"].append(
                        "CMR record lacks expected identifying metadata: "
                        + ", ".join(missing_metadata)
                    )
                zero_doppler = catalog_record.get("additional_attributes", {})
                reference_time = next(
                    iter(zero_doppler.get("REFERENCE_ZERO_DOPPLER_START_TIME", [])),
                    "",
                )
                secondary_time = next(
                    iter(zero_doppler.get("SECONDARY_ZERO_DOPPLER_START_TIME", [])),
                    "",
                )
                result["chronological_pair_metadata"] = {
                    "reference_start": reference_time,
                    "secondary_start": secondary_time,
                    "chronological": None,
                }
                try:
                    reference_dt = datetime.fromisoformat(
                        str(reference_time).replace("Z", "+00:00")
                    )
                    secondary_dt = datetime.fromisoformat(
                        str(secondary_time).replace("Z", "+00:00")
                    )
                    chronological = reference_dt < secondary_dt
                    result["chronological_pair_metadata"]["chronological"] = (
                        chronological
                    )
                    if not chronological:
                        result["errors"].append(
                            "CMR reference acquisition is not earlier than secondary "
                            "acquisition"
                        )
                except ValueError:
                    result["warnings"].append(
                        "Could not parse reference/secondary zero-Doppler start times"
                    )
            result["valid"] = not result["errors"]
    except OSError as error:
        result["errors"].append(
            f"HDF5 open/validation error: {type(error).__name__}: {error}"
        )
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "products", nargs="+", type=Path, help="Local GUNW HDF5 file(s)."
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Write the JSON report here; defaults to stdout.",
    )
    parser.add_argument(
        "--catalog-json",
        action="append",
        type=Path,
        default=[],
        help="CMR inventory JSON (repeat for separate maturity inventories).",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    catalog_records = load_catalog_records(args.catalog_json)
    reports = []
    for path in args.products:
        if not path.is_file():
            reports.append(
                {
                    "path": str(path),
                    "valid": False,
                    "errors": ["Input path is not a file"],
                }
            )
            continue
        print(f"Validating {path}", file=sys.stderr, flush=True)
        reports.append(inspect_product(path, catalog_records.get(path.name)))

    document = {
        "schema_version": 1,
        "reports": reports,
        "valid": bool(reports)
        and all(report.get("valid", False) for report in reports),
    }
    rendered = json.dumps(document, indent=2, sort_keys=True, allow_nan=False) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
        print(f"Wrote validation report to {args.output}", file=sys.stderr)
    else:
        print(rendered, end="")
    return 0 if document["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
