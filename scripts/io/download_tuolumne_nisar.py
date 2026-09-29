#!/usr/bin/env python3
"""Resume and validate selected GUNW files from a saved CMR inventory."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import requests
from asf_search import ASFSession

REPO_ROOT = Path(__file__).resolve().parents[2]
VALIDATOR = REPO_ROOT / "scripts" / "io" / "validate_nisar_gunw.py"
DEFAULT_DATA_ROOT = Path("/Users/jtarrico/ch13_nisar_prelim/data/nisar/gunw/tuolumne")
DEFAULT_INVENTORIES = {
    "BETA": REPO_ROOT / "data/inventories/tuolumne_nisar_beta.json",
    "PROVISIONAL": REPO_ROOT
    / "data/inventories/tuolumne_nisar_provisional_primary_frames.json",
}
CONTENT_RANGE_RE = re.compile(r"bytes (\d+)-(\d+)/(\d+|\*)")
RETRY_LIMIT = 5
CHUNK_BYTES = 1024 * 1024


class DownloadError(RuntimeError):
    """Raised when a catalogued product cannot be safely downloaded."""


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise DownloadError(f"catalog field {field!r} is missing or invalid")
    return value


def _track_frame(record: dict[str, Any]) -> str:
    def value_for(name: str) -> str | None:
        for item in record.get(name, []):
            if item.get("values"):
                value = str(item["values"][0])
                if value.isdigit():
                    return value
        return None

    track = value_for("track_attributes")
    frame = value_for("frame_attributes")
    if track is None or frame is None:
        return "unresolved_track_frame"
    return f"T{int(track):03d}_F{int(frame):03d}"


def _product_file(record: dict[str, Any]) -> dict[str, Any]:
    granule_id = _text(record.get("granule_ur"), "granule_ur")
    filename = f"{granule_id}.h5"
    matches = [
        item for item in record.get("file_records", []) if item.get("Name") == filename
    ]
    if len(matches) != 1:
        raise DownloadError(
            f"expected one primary GUNW asset named {filename!r}, found {len(matches)}"
        )
    asset = matches[0]
    size = asset.get("SizeInBytes")
    if isinstance(size, bool) or not isinstance(size, int) or size <= 0:
        raise DownloadError(f"catalog size is missing or invalid for {filename}")
    checksum = asset.get("Checksum") or {}
    algorithm = str(checksum.get("Algorithm", "")).upper().replace("-", "")
    checksum_value = str(checksum.get("Value", "")).lower()
    if algorithm != "MD5" or not re.fullmatch(r"[0-9a-f]{32}", checksum_value):
        raise DownloadError(f"catalog MD5 is missing or invalid for {filename}")

    urls = {
        item.get("URL")
        for item in record.get("related_urls", [])
        if item.get("Type") == "GET DATA"
        and isinstance(item.get("URL"), str)
        and Path(urlsplit(item["URL"]).path).name == filename
        and urlsplit(item["URL"]).scheme == "https"
        and urlsplit(item["URL"]).hostname == "nisar.asf.earthdatacloud.nasa.gov"
    }
    if len(urls) != 1:
        raise DownloadError(
            f"expected one HTTPS ASF data URL for {filename}, found {len(urls)}"
        )
    return {
        "filename": filename,
        "url": next(iter(urls)),
        "size_bytes": size,
        "checksum_algorithm": algorithm,
        "checksum": checksum_value,
    }


def load_products(
    path: Path, maturity: str
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    inventory = json.loads(path.read_text(encoding="utf-8"))
    if inventory.get("maturity") != maturity:
        raise DownloadError(
            f"inventory maturity {inventory.get('maturity')!r} does not match "
            f"requested maturity {maturity!r}"
        )
    records = inventory.get("granules")
    if not isinstance(records, list):
        raise DownloadError(f"inventory {path} has no granules list")

    products = []
    seen: set[str] = set()
    for record in records:
        asset = _product_file(record)
        product_id = _text(record.get("granule_ur"), "granule_ur")
        if product_id in seen:
            raise DownloadError(f"duplicate exact granule record: {product_id}")
        seen.add(product_id)
        products.append(
            {
                "granule_id": product_id,
                "maturity": maturity,
                "track_frame": _track_frame(record),
                "crid": next(
                    (
                        item.get("Identifier")
                        for item in record.get("product_identifiers", [])
                        if item.get("IdentifierType", "").upper() == "CRID"
                    ),
                    "",
                ),
                "collection_version": record.get("collection_version", ""),
                **asset,
                "catalog_record": record,
            }
        )
    return inventory, products


def _md5(path: Path) -> str:
    digest = hashlib.md5(usedforsecurity=False)
    with path.open("rb") as stream:
        while chunk := stream.read(CHUNK_BYTES):
            digest.update(chunk)
    return digest.hexdigest()


def _existing_state(product: dict[str, Any], destination: Path) -> tuple[str, int]:
    expected_size = product["size_bytes"]
    expected_md5 = product["checksum"]
    partial = destination.with_name(destination.name + ".part")
    if destination.exists():
        actual_size = destination.stat().st_size
        if actual_size != expected_size or _md5(destination) != expected_md5:
            raise DownloadError(
                f"existing file does not match CMR size/checksum: {destination}"
            )
        return "complete", 0
    if partial.exists():
        partial_size = partial.stat().st_size
        if partial_size > expected_size:
            raise DownloadError(f"partial file exceeds CMR size: {partial}")
        if partial_size == expected_size:
            if _md5(partial) != expected_md5:
                raise DownloadError(
                    f"complete partial file does not match CMR MD5: {partial}"
                )
            partial.replace(destination)
            return "complete", 0
        return "pending", expected_size - partial_size
    return "pending", expected_size


def _download_one(
    product: dict[str, Any], destination: Path, session: ASFSession
) -> dict[str, Any]:
    destination.parent.mkdir(parents=True, exist_ok=True)
    state, remaining = _existing_state(product, destination)
    partial = destination.with_name(destination.name + ".part")
    if state == "complete":
        print(f"Verified existing {destination.name}", flush=True)
    else:
        print(
            f"Downloading {destination.name} ({remaining:,} bytes remaining)",
            flush=True,
        )
        last_error: Exception | None = None
        for attempt in range(1, RETRY_LIMIT + 1):
            offset = partial.stat().st_size if partial.exists() else 0
            if offset > product["size_bytes"]:
                raise DownloadError(f"partial file exceeds CMR size: {partial}")
            headers = {"Range": f"bytes={offset}-"} if offset else {}
            response = None
            try:
                response = session.get(
                    product["url"],
                    headers=headers,
                    stream=True,
                    timeout=(60, 300),
                )
                response.raise_for_status()
                append = offset > 0 and response.status_code == 206
                if append:
                    content_range = CONTENT_RANGE_RE.fullmatch(
                        response.headers.get("Content-Range", "")
                    )
                    if content_range is None or int(content_range.group(1)) != offset:
                        raise DownloadError(
                            f"server returned an invalid range for {destination.name}"
                        )
                mode = "ab" if append else "wb"
                with partial.open(mode) as stream:
                    for chunk in response.iter_content(chunk_size=CHUNK_BYTES):
                        if chunk:
                            stream.write(chunk)
                actual_size = partial.stat().st_size
                if actual_size > product["size_bytes"]:
                    raise DownloadError(
                        f"download exceeds CMR size for {destination.name}"
                    )
                if actual_size < product["size_bytes"]:
                    raise DownloadError(
                        f"download stopped at {actual_size:,} of "
                        f"{product['size_bytes']:,} bytes for {destination.name}"
                    )
                actual_md5 = _md5(partial)
                if actual_md5 != product["checksum"]:
                    raise DownloadError(
                        f"downloaded MD5 differs from CMR for {destination.name}"
                    )
                partial.replace(destination)
                break
            except requests.RequestException as error:
                last_error = error
                if attempt == RETRY_LIMIT:
                    raise DownloadError(
                        f"request failed for {destination.name}: {error}"
                    ) from error
                time.sleep(min(5 * attempt, 30))
            except DownloadError as error:
                last_error = error
                if attempt == RETRY_LIMIT:
                    raise
                time.sleep(min(5 * attempt, 30))
            finally:
                if response is not None:
                    response.close()
        if not destination.is_file():
            raise DownloadError(f"download did not complete: {last_error}")

    validation_report = destination.with_name(destination.name + ".validation.json")
    validation = subprocess.run(
        [
            sys.executable,
            str(VALIDATOR),
            str(destination),
            "--catalog-json",
            str(product["inventory_path"]),
            "--output",
            str(validation_report),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    return {
        "granule_id": product["granule_id"],
        "maturity": product["maturity"],
        "track_frame": product["track_frame"],
        "crid": product["crid"],
        "collection_version": product["collection_version"],
        "path": str(destination),
        "size_bytes": destination.stat().st_size,
        "cmr_checksum_algorithm": product["checksum_algorithm"],
        "cmr_checksum": product["checksum"],
        "local_md5": _md5(destination),
        "validation_report": str(validation_report),
        "raw_contract_valid": validation.returncode == 0,
        "validation_stderr": validation.stderr[-2000:],
    }


def _nearest_existing(path: Path) -> Path:
    current = path
    while not current.exists() and current != current.parent:
        current = current.parent
    return current


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--maturity", required=True, choices=("BETA", "PROVISIONAL"))
    parser.add_argument("--inventory", type=Path, help="Saved CMR JSON inventory.")
    parser.add_argument(
        "--download-root",
        type=Path,
        help="Maturity-specific directory for raw products and reports.",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=2,
        help="Concurrent product downloads (default: 2).",
    )
    parser.add_argument("--max-products", type=int, help="Limit a pilot run.")
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Perform downloads; without this flag, print a dry-run plan.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.workers < 1:
        raise DownloadError("--workers must be at least one")
    if args.max_products is not None and args.max_products < 1:
        raise DownloadError("--max-products must be at least one")

    inventory_path = (args.inventory or DEFAULT_INVENTORIES[args.maturity]).expanduser()
    inventory_path = inventory_path.resolve()
    inventory, products = load_products(inventory_path, args.maturity)
    for product in products:
        product["inventory_path"] = inventory_path
    if args.max_products is not None:
        products = products[: args.max_products]
    if not products:
        raise DownloadError("selected inventory contains no GUNW products")

    root = args.download_root or DEFAULT_DATA_ROOT / args.maturity.lower()
    root = root.expanduser().resolve()
    destinations = {
        product["granule_id"]: root / product["track_frame"] / product["filename"]
        for product in products
    }
    needed = 0
    for product in products:
        _, remaining = _existing_state(product, destinations[product["granule_id"]])
        needed += remaining

    free_bytes = shutil.disk_usage(_nearest_existing(root)).free
    total_bytes = sum(product["size_bytes"] for product in products)
    print(
        json.dumps(
            {
                "maturity": args.maturity,
                "inventory": str(inventory_path),
                "inventory_created_utc": inventory.get("inventory_created_utc"),
                "inventory_role": inventory.get("inventory_role", "AOI inventory"),
                "products_selected": len(products),
                "catalog_bytes_selected": total_bytes,
                "bytes_remaining_to_download": needed,
                "free_bytes_at_target": free_bytes,
                "download_root": str(root),
                "mode": "download" if args.execute else "dry_run",
            },
            indent=2,
            sort_keys=True,
        )
    )
    if not args.execute:
        return 0
    if free_bytes < needed:
        raise DownloadError(
            f"target has {free_bytes:,} free bytes but selected downloads need "
            f"{needed:,} bytes"
        )

    session = ASFSession()
    results = []
    failures = []
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {
            executor.submit(
                _download_one,
                product,
                destinations[product["granule_id"]],
                session,
            ): product
            for product in products
        }
        for future in as_completed(futures):
            product = futures[future]
            try:
                results.append(future.result())
            except Exception as error:
                failures.append(
                    {
                        "granule_id": product["granule_id"],
                        "error": f"{type(error).__name__}: {error}",
                    }
                )

    report = {
        "schema_version": 1,
        "created_utc": datetime.now(UTC)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z"),
        "maturity": args.maturity,
        "source_inventory": str(inventory_path),
        "source_inventory_created_utc": inventory.get("inventory_created_utc"),
        "results": sorted(results, key=lambda item: item["granule_id"]),
        "failures": failures,
    }
    root.mkdir(parents=True, exist_ok=True)
    manifest_path = root / "download_manifest.json"
    manifest_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"Wrote download report to {manifest_path}", flush=True)
    return (
        1 if failures or any(not item["raw_contract_valid"] for item in results) else 0
    )


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (DownloadError, OSError, ValueError, json.JSONDecodeError) as error:
        print(f"Download plan failed: {type(error).__name__}: {error}", file=sys.stderr)
        raise SystemExit(1) from error
