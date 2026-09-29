#!/usr/bin/env python3
"""Download VIIRS daily snow tiles matching the NISAR acquisition dates."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import earthaccess
import requests
from earthaccess.results import DataGranule

REPO_ROOT = Path(__file__).resolve().parents[2]
NISAR_INVENTORY = (
    REPO_ROOT / "data/inventories/tuolumne_nisar_provisional_primary_frames.json"
)
DEFAULT_OUTPUT_DIR = REPO_ROOT / "data/external/viirs/tuolumne/vj110a1f_v002/raw"
CMR_COLLECTION_ID = "C3173454072-NSIDC_CPRD"
CMR_ENDPOINT = "https://cmr.earthdata.nasa.gov/search/granules.umm_json"
PRODUCER_ID_PATTERN = "VJ110A1F.A*.h08v05.002*"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _repo_relative(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return str(path.resolve())


def _nisar_endpoint_dates(path: Path) -> set[str]:
    inventory = json.loads(path.read_text(encoding="utf-8"))
    dates: set[str] = set()
    for record in inventory.get("granules", []):
        for key in ("acquisition_start", "acquisition_end"):
            value = record.get(key)
            if not isinstance(value, str) or len(value) < 10:
                raise ValueError(f"NISAR inventory record is missing {key}")
            dates.add(value[:10])
    if not dates:
        raise ValueError("NISAR inventory contains no acquisition dates")
    return dates


def _query_cmr(dates: set[str]) -> list[dict[str, Any]]:
    start = f"{min(dates)}T00:00:00Z"
    end = f"{max(dates)}T23:59:59Z"
    params = {
        "collection_concept_id": CMR_COLLECTION_ID,
        "producer_granule_id[]": PRODUCER_ID_PATTERN,
        "options[producer_granule_id][pattern]": "true",
        "temporal[]": f"{start},{end}",
        "page_size": 2000,
    }
    response: requests.Response | None = None
    for attempt in range(4):
        response = requests.get(CMR_ENDPOINT, params=params, timeout=120)
        if response.status_code not in {429, 502, 503, 504}:
            break
        time.sleep(2 * (attempt + 1))
    assert response is not None
    response.raise_for_status()
    return response.json().get("items", [])


def _date_for_granule(item: dict[str, Any]) -> str:
    temporal = item.get("umm", {}).get("TemporalExtent", {}).get("RangeDateTime", {})
    start = temporal.get("BeginningDateTime")
    if not isinstance(start, str) or len(start) < 10:
        raise ValueError("CMR granule is missing its beginning date")
    return start[:10]


def _h5_url(granule: DataGranule) -> str:
    candidates = [
        link
        for link in granule.data_links()
        if urlsplit(link).path.lower().endswith(".h5")
    ]
    if len(candidates) != 1:
        raise ValueError(
            f"expected one HDF5 URL for {granule['meta']['native-id']}, "
            f"found {len(candidates)}"
        )
    return candidates[0]


def _record_for_date(
    selected: dict[str, tuple[DataGranule, str]],
    superseded: list[dict[str, str]],
    day: str,
    item: dict[str, Any],
) -> None:
    granule = DataGranule(item, cloud_hosted=False)
    url = _h5_url(granule)
    current = selected.get(day)
    if current is None:
        selected[day] = (granule, url)
        return

    current_granule, current_url = current
    current_revision = current_granule["meta"].get("revision-date", "")
    new_revision = granule["meta"].get("revision-date", "")
    if not current_revision or not new_revision or current_revision == new_revision:
        raise ValueError(f"CMR has ambiguous duplicate VIIRS granules for {day}")
    if new_revision > current_revision:
        selected[day] = (granule, url)
        superseded.append(
            {
                "product_date": day,
                "superseded_granule_concept_id": current_granule["meta"]["concept-id"],
                "superseded_revision_date": current_revision,
                "superseded_url": current_url,
                "selected_granule_concept_id": granule["meta"]["concept-id"],
                "selected_revision_date": new_revision,
                "selected_url": url,
                "selection_rule": (
                    "later CMR revision-date for the same date, tile, and version"
                ),
            }
        )
    else:
        superseded.append(
            {
                "product_date": day,
                "superseded_granule_concept_id": granule["meta"]["concept-id"],
                "superseded_revision_date": new_revision,
                "superseded_url": url,
                "selected_granule_concept_id": current_granule["meta"]["concept-id"],
                "selected_revision_date": current_revision,
                "selected_url": current_url,
                "selection_rule": (
                    "later CMR revision-date for the same date, tile, and version"
                ),
            }
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--nisar-inventory", type=Path, default=NISAR_INVENTORY)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--manifest-path", type=Path)
    args = parser.parse_args()

    nisar_dates = _nisar_endpoint_dates(args.nisar_inventory)
    cmr_items = _query_cmr(nisar_dates)
    selected: dict[str, tuple[DataGranule, str]] = {}
    superseded: list[dict[str, str]] = []
    for item in cmr_items:
        day = _date_for_granule(item)
        if day in nisar_dates:
            _record_for_date(selected, superseded, day, item)
    missing_dates = sorted(nisar_dates - selected.keys())
    if missing_dates:
        raise RuntimeError(f"CMR has no VJ110A1F h08v05 products for {missing_dates}")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    already_present = {
        day: (granule, url)
        for day, (granule, url) in selected.items()
        if (args.output_dir / Path(urlsplit(url).path).name).is_file()
    }
    pending = [
        granule for day, (granule, _) in selected.items() if day not in already_present
    ]
    if pending:
        auth = earthaccess.login(strategy="netrc", persist=False)
        if not auth.authenticated:
            raise RuntimeError("Earthdata Login credentials are not available")
        downloaded = earthaccess.download(pending, str(args.output_dir))
        if not downloaded:
            raise RuntimeError("earthaccess did not download any VIIRS files")

    products: list[dict[str, Any]] = []
    for day, (granule, url) in sorted(selected.items()):
        filename = Path(urlsplit(url).path).name
        path = args.output_dir / filename
        if not path.is_file():
            raise RuntimeError(f"downloaded VIIRS file is missing: {path}")
        products.append(
            {
                "product_date": day,
                "collection_concept_id": granule["meta"]["collection-concept-id"],
                "granule_concept_id": granule["meta"]["concept-id"],
                "granule_native_id": granule["meta"]["native-id"],
                "cmr_revision_date": granule["meta"].get("revision-date"),
                "producer_granule_id": granule["umm"].get("GranuleUR"),
                "filename": filename,
                "source_url": url,
                "local_path": _repo_relative(path),
                "local_size_bytes": path.stat().st_size,
                "local_sha256": _sha256(path),
                "already_present_before_run": day in already_present,
            }
        )

    manifest = {
        "schema_version": 1,
        "generated_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "provider": "NASA NSIDC DAAC via CMR and earthaccess",
        "cmr_collection_concept_id": CMR_COLLECTION_ID,
        "product": "VIIRS/JPSS1 CGF Snow Cover Daily L3 Global 375m SIN Grid V002",
        "short_name": "VJ110A1F",
        "version": "002",
        "tile": "h08v05",
        "nisar_inventory": args.nisar_inventory.relative_to(REPO_ROOT).as_posix(),
        "nisar_endpoint_dates": sorted(nisar_dates),
        "cmr_results_in_date_range": len(cmr_items),
        "selected_product_count": len(products),
        "duplicate_record_policy": (
            "For duplicate product dates, tile, and collection version, select "
            "the CMR record with the latest revision-date and report the other."
        ),
        "superseded_cmr_records": superseded,
        "products": products,
    }
    manifest_path = args.manifest_path or args.output_dir / "download_manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    print(f"VIIRS products selected: {len(products)} for {len(nisar_dates)} dates")
    print(f"Already present: {len(already_present)}; downloaded: {len(pending)}")
    print(f"Raw products: {args.output_dir}")
    print(f"Manifest: {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
