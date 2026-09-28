#!/usr/bin/env python3
"""Refresh separate ASF CMR metadata inventories for NISAR GUNW maturities."""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

CMR_ROOT = "https://cmr.earthdata.nasa.gov/search"
CMR_ACCEPT = "application/vnd.nasa.cmr.umm_results+json; version=1.6"
USER_AGENT = "nisar-isnobal-da-tuolumne/0.1 (metadata inventory)"
PAGE_SIZE = 2000
START_DATE = "2025-10-01T00:00:00Z"
MATURITIES = {
    "BETA": "NISAR_L2_GUNW_BETA_V1",
    "PROVISIONAL": "NISAR_L2_GUNW_PROVISIONAL_V1",
}


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
    return value


def polygon_rings(geometry: dict[str, Any]) -> list[list[tuple[float, float]]]:
    """Return closed, counter-clockwise exterior rings for CMR polygon queries."""
    geometry_type = geometry.get("type")
    coordinates = geometry.get("coordinates", [])
    polygons = [coordinates] if geometry_type == "Polygon" else coordinates
    if geometry_type not in {"Polygon", "MultiPolygon"}:
        raise ValueError(
            f"ASO AOI must be Polygon or MultiPolygon, got {geometry_type!r}"
        )

    rings: list[list[tuple[float, float]]] = []
    for polygon in polygons:
        if not polygon:
            continue
        ring = [(float(point[0]), float(point[1])) for point in polygon[0]]
        if ring[0] != ring[-1]:
            ring.append(ring[0])
        signed_area = sum(
            x1 * y2 - x2 * y1
            for (x1, y1), (x2, y2) in zip(ring, ring[1:], strict=False)
        )
        if signed_area < 0:
            ring = list(reversed(ring))
        if len(ring) < 4:
            raise ValueError(
                "CMR query polygon must contain at least four closed points"
            )
        rings.append(ring)
    if not rings:
        raise ValueError("ASO AOI contains no polygon exterior rings")
    return rings


def read_aoi(path: Path) -> tuple[dict[str, Any], list[list[tuple[float, float]]]]:
    document = json.loads(path.read_text(encoding="utf-8"))
    features = document.get("features", [])
    if len(features) != 1:
        raise ValueError(f"Expected one AOI feature in {path}, found {len(features)}")
    geometry = features[0].get("geometry", {})
    return geometry, polygon_rings(geometry)


def decode_entries(document: dict[str, Any]) -> list[dict[str, Any]]:
    feed = document.get("feed", {})
    entries = feed.get("entry")
    if entries is None:
        entries = document.get("items", [])
    if not isinstance(entries, list):
        raise ValueError("Unexpected CMR UMM JSON response: no entry list")
    return entries


def request_page(
    endpoint: str,
    parameters: list[tuple[str, str]],
    search_after: str | None,
) -> tuple[dict[str, Any], str | None, dict[str, str]]:
    query = urlencode(parameters)
    request = Request(
        f"{CMR_ROOT}/{endpoint}?{query}",
        headers={
            "Accept": CMR_ACCEPT,
            "User-Agent": USER_AGENT,
            **({"CMR-Search-After": search_after} if search_after else {}),
        },
    )
    for attempt in range(5):
        try:
            with urlopen(request, timeout=120) as response:
                document = json.load(response)
                headers = {
                    "cmr_hits": response.headers.get("CMR-Hits", ""),
                    "cmr_request_id": response.headers.get("CMR-Request-Id", ""),
                    "cmr_search_after": response.headers.get("CMR-Search-After", ""),
                }
                return document, response.headers.get("CMR-Search-After"), headers
        except HTTPError as error:
            if error.code not in {429, 500, 502, 503, 504} or attempt == 4:
                raise
            time.sleep(2**attempt)
        except URLError:
            if attempt == 4:
                raise
            time.sleep(2**attempt)
    raise RuntimeError("CMR request retries exhausted")


def cmr_search(
    endpoint: str, parameters: list[tuple[str, str]]
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    entries: list[dict[str, Any]] = []
    pages: list[dict[str, str]] = []
    search_after = None
    seen_headers: set[str] = set()
    while True:
        document, next_search_after, headers = request_page(
            endpoint, parameters, search_after
        )
        page_entries = decode_entries(document)
        entries.extend(page_entries)
        pages.append({key: value for key, value in headers.items() if value})
        if not page_entries or not next_search_after:
            break
        if next_search_after in seen_headers:
            raise RuntimeError(
                "CMR repeated a search-after token; stopping to avoid a loop"
            )
        seen_headers.add(next_search_after)
        search_after = next_search_after
    return entries, pages


def collection_parameters(short_name: str) -> list[tuple[str, str]]:
    return [
        ("short_name", short_name),
        ("page_size", str(PAGE_SIZE)),
        ("sort_key[]", "short_name"),
    ]


def granule_parameters(
    collection_id: str,
    start: str,
    end: str,
    rings: list[list[tuple[float, float]]],
) -> list[tuple[str, str]]:
    parameters = [
        ("collection_concept_id", collection_id),
        ("temporal", f"{start},{end}"),
        ("page_size", str(PAGE_SIZE)),
        ("sort_key[]", "start_date"),
    ]
    for ring in rings:
        polygon = ",".join(
            f"{longitude:.10f},{latitude:.10f}" for longitude, latitude in ring
        )
        parameters.append(("polygon[]", polygon))
    if len(rings) > 1:
        parameters.append(("options[polygon][or]", "true"))
    return parameters


def collection_id(collection: dict[str, Any]) -> str:
    return str(collection.get("meta", {}).get("concept-id", ""))


def additional_attributes(granule: dict[str, Any]) -> dict[str, list[Any]]:
    attributes: dict[str, list[Any]] = {}
    for item in granule.get("AdditionalAttributes", []):
        name = str(item.get("Name", ""))
        values = item.get("Values", [])
        if not isinstance(values, list):
            values = [values]
        if name:
            attributes[name] = values
    return attributes


def matching_attribute_values(
    attributes: dict[str, list[Any]], tokens: tuple[str, ...]
) -> list[dict[str, Any]]:
    return [
        {"name": name, "values": values}
        for name, values in attributes.items()
        if any(token in name.casefold() for token in tokens)
    ]


def date_extent(granule: dict[str, Any]) -> tuple[str, str]:
    extent = granule.get("TemporalExtent", {})
    interval = extent.get("RangeDateTime", {})
    if interval:
        return (
            str(interval.get("BeginningDateTime", "")),
            str(interval.get("EndingDateTime", "")),
        )
    value = extent.get("SingleDateTime", "")
    return str(value), str(value)


def normalize_granule(
    maturity: str,
    collection: dict[str, Any],
    granule: dict[str, Any],
) -> dict[str, Any]:
    umm = granule.get("umm", granule)
    metadata = granule.get("meta", {})
    attributes = additional_attributes(umm)
    begin, end = date_extent(umm)
    data_granule = umm.get("DataGranule", {})
    reference = umm.get("CollectionReference", {})
    archive_files = data_granule.get("ArchiveAndDistributionInformation", [])
    hdf5_files = [
        item for item in archive_files if str(item.get("Format", "")).upper() == "HDF5"
    ]
    identifiers = data_granule.get("Identifiers", [])
    return {
        "maturity": maturity,
        "collection_short_name": reference.get("ShortName", ""),
        "collection_version": reference.get("Version", ""),
        "collection_concept_id": collection_id(collection),
        "granule_ur": umm.get("GranuleUR", ""),
        "granule_concept_id": metadata.get("concept-id", ""),
        "granule_revision_id": metadata.get("revision-id", ""),
        "acquisition_start": begin,
        "acquisition_end": end,
        "file_records": hdf5_files,
        "product_identifiers": identifiers,
        "track_attributes": matching_attribute_values(attributes, ("track",)),
        "frame_attributes": matching_attribute_values(attributes, ("frame",)),
        "orbit_direction_attributes": matching_attribute_values(
            attributes, ("orbit direction", "orbit_direction", "direction")
        ),
        "polarization_attributes": matching_attribute_values(
            attributes, ("polarization", "polaris")
        ),
        "crid_attributes": matching_attribute_values(attributes, ("crid",)),
        "product_version_attributes": matching_attribute_values(
            attributes, ("product version", "processing version", "software version")
        ),
        "zero_doppler_attributes": matching_attribute_values(
            attributes, ("zero_doppler", "zero doppler")
        ),
        "additional_attributes": attributes,
        "related_urls": umm.get("RelatedUrls", []),
        "raw_cmr_metadata": metadata,
        "raw_umm": umm,
    }


def scalar_attribute_values(items: list[dict[str, Any]]) -> list[str]:
    return [str(value) for item in items for value in item.get("values", [])]


def numeric_identifier(values: list[str]) -> set[int]:
    numbers: set[int] = set()
    for value in values:
        match = re.fullmatch(r"[A-Za-z]*0*(\d+)", value.strip())
        if match:
            numbers.add(int(match.group(1)))
    return numbers


def is_primary_frame(record: dict[str, Any]) -> bool:
    track_values = scalar_attribute_values(record["track_attributes"])
    frame_values = scalar_attribute_values(record["frame_attributes"])
    tracks = numeric_identifier(track_values)
    frames = numeric_identifier(frame_values)
    return (42 in tracks and 69 in frames) or (34 in tracks and 21 in frames)


def inventory_maturity(
    maturity: str,
    short_name: str,
    aoi: dict[str, Any],
    rings: list[list[tuple[float, float]]],
    start: str,
    end: str,
    queried_at: str,
) -> dict[str, Any]:
    collections, collection_pages = cmr_search(
        "collections.umm_json", collection_parameters(short_name)
    )
    if not collections:
        raise RuntimeError(f"CMR returned no collection for {short_name}")
    collection_records: list[dict[str, Any]] = []
    granule_records: list[dict[str, Any]] = []
    granule_pages: dict[str, list[dict[str, str]]] = {}
    granule_queries: dict[str, list[tuple[str, str]]] = {}
    for collection in collections:
        concept = collection_id(collection)
        if not concept:
            raise RuntimeError(
                f"CMR collection response lacked concept ID: {short_name}"
            )
        collection_records.append(collection)
        parameters = granule_parameters(concept, start, end, rings)
        granule_queries[concept] = parameters
        granules, page_headers = cmr_search("granules.umm_json", parameters)
        granule_pages[concept] = page_headers
        granule_records.extend(
            normalize_granule(maturity, collection, granule) for granule in granules
        )
    return {
        "schema_version": 1,
        "inventory_created_utc": queried_at,
        "catalog": "NASA Common Metadata Repository (CMR), ASF DAAC collections",
        "maturity": maturity,
        "requested_short_name": short_name,
        "query": {
            "collection_short_name": short_name,
            "collection_search_endpoint": "collections.umm_json",
            "collection_search_parameters": collection_parameters(short_name),
            "granule_search_endpoint": "granules.umm_json",
            "granule_search_parameters_by_collection_concept_id": granule_queries,
            "temporal_start_inclusive": start,
            "temporal_end_inclusive": end,
            "aoi_source": "ASO SWE raster-footprint union",
            "aoi_geometry": aoi,
            "polygon_query_note": (
                "CMR receives each exterior ring; polygon holes, if any, are omitted."
            ),
            "data_downloaded": False,
        },
        "collection_search_pages": collection_pages,
        "granule_search_pages_by_collection_concept_id": granule_pages,
        "collections": collection_records,
        "granule_count": len(granule_records),
        "granules": granule_records,
    }


def write_json(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rendered = json.dumps(
        json_value(document), indent=2, sort_keys=True, allow_nan=False
    )
    path.write_text(rendered + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--aoi",
        type=Path,
        default=Path("data/inventories/tuolumne_aso_aoi.geojson"),
    )
    parser.add_argument("--start", default=START_DATE)
    parser.add_argument(
        "--end",
        help="Inclusive UTC query end; defaults to the current UTC timestamp.",
    )
    parser.add_argument(
        "--beta-output",
        type=Path,
        default=Path("data/inventories/tuolumne_nisar_beta.json"),
    )
    parser.add_argument(
        "--provisional-output",
        type=Path,
        default=Path("data/inventories/tuolumne_nisar_provisional_all.json"),
    )
    parser.add_argument(
        "--primary-output",
        type=Path,
        default=Path("data/inventories/tuolumne_nisar_provisional_primary_frames.json"),
    )
    parser.add_argument(
        "--maturity",
        choices=("BETA", "PROVISIONAL", "BOTH"),
        default="BOTH",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    aoi_path = args.aoi.expanduser().resolve()
    if not aoi_path.is_file():
        raise SystemExit(f"ASO AOI file not found: {aoi_path}")
    queried_at = datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
    end = args.end or queried_at
    geometry, rings = read_aoi(aoi_path)
    selected = ("BETA", "PROVISIONAL") if args.maturity == "BOTH" else (args.maturity,)

    if "BETA" in selected:
        beta = inventory_maturity(
            "BETA", MATURITIES["BETA"], geometry, rings, args.start, end, queried_at
        )
        write_json(args.beta_output, beta)
        print(f"BETA: {beta['granule_count']} granules -> {args.beta_output}")
    if "PROVISIONAL" in selected:
        provisional = inventory_maturity(
            "PROVISIONAL",
            MATURITIES["PROVISIONAL"],
            geometry,
            rings,
            args.start,
            end,
            queried_at,
        )
        write_json(args.provisional_output, provisional)
        primary = {
            **provisional,
            "inventory_role": "primary-frame metadata subset",
            "selection_rule": (
                "CMR additional-attribute metadata explicitly identifies track/frame "
                "T042/F069 or T034/F021; no granule-name parsing is used."
            ),
            "granules": [
                record for record in provisional["granules"] if is_primary_frame(record)
            ],
        }
        primary["granule_count"] = len(primary["granules"])
        write_json(args.primary_output, primary)
        print(
            f"PROVISIONAL: {provisional['granule_count']} granules -> "
            f"{args.provisional_output}"
        )
        print(
            f"Primary-frame metadata subset: {primary['granule_count']} -> "
            f"{args.primary_output}"
        )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (HTTPError, URLError, OSError, RuntimeError, ValueError) as error:
        print(f"Inventory failed: {type(error).__name__}: {error}", file=sys.stderr)
        raise SystemExit(1) from error
