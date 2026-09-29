#!/usr/bin/env python3
"""Build a reproducible two-frame Tuolumne NISAR retrieval baseline."""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.metadata
import json
import math
import re
import subprocess
import sys
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import h5py
import matplotlib
import numpy as np
import rasterio
import snowin
import xarray as xr
from matplotlib import pyplot as plt
from matplotlib.colors import BoundaryNorm, ListedColormap
from matplotlib.patches import Patch
from matplotlib.ticker import FuncFormatter
from nisar_pytools import open_nisar
from nisar_pytools.utils.metadata import get_gunw
from pyproj import CRS, Transformer
from rasterio.enums import Resampling
from rasterio.features import geometry_mask
from rasterio.transform import Affine, from_bounds
from rasterio.warp import reproject
from shapely.geometry import Point, shape
from shapely.ops import transform as shapely_transform
from snowin.io.nisar_product import (
    NISAR_GUNW_SOURCE_PHASE_DEFINITION,
    compute_gunw_incidence,
    normalize_gunw_pair,
    read_gunw_wavelength_m,
)
from snowin.reference import reference_phase
from snowin.snow.dswe import compute_dswe
from snowin.temporal import accumulate_dswe

from nisar_isnobal_da.observations.snowin_adapter import adapt_snowin_observation

ROOT = Path(__file__).resolve().parents[2]
FRAME_NAMES = ("T042_F069", "T034_F021")
NISAR_INVENTORY = (
    ROOT / "data/inventories/tuolumne_nisar_provisional_primary_frames.json"
)
BOUNDARY_PATH = ROOT / "data/inventories/tuolumne_basin_boundary.geojson"
STATION_METADATA = ROOT / "data/inventories/tuolumne_cdec_station_metadata.csv"
STATION_DAILY = (
    ROOT / "data/external/cdec/tuolumne/2025-10-01_to_2026-09-28/"
    "cdec_tuolumne_swe_daily_cm.csv"
)
VIIRS_ROOT = ROOT / "data/external/viirs/tuolumne/vj110a1f_v002/raw"
VIIRS_MANIFEST = ROOT / "data/inventories/tuolumne_viirs_2025-11-01_to_2026-09-21.json"
ASO_INVENTORY = ROOT / "data/inventories/tuolumne_aso.csv"
DEFAULT_DEM = ROOT / "data/external/dem/nisar_cop30/tuolumne_four_tile_mosaic.tif"
DEFAULT_OUTPUT = ROOT / "data/derived/tuolumne_retrieval_baseline"
VIIRS_FIELD = "HDFEOS/GRIDS/VIIRS_Grid_IMG_2D/Data Fields/CGF_NDSI_Snow_Cover"
VIIRS_FILL = 255
VIIRS_SCALE = 0.01
VIIRS_FSCA_INTERCEPT = -0.01
VIIRS_FSCA_SLOPE = 1.45
VIIRS_THRESHOLD = 0.50
GRID_CRS = "EPSG:32610"
ANALYSIS_END_DATE = "2026-06-01"
REFERENCE_METHODS = (
    "median",
    "coherence_weighted_mean",
    "max_station",
    "min_station",
)
REFERENCE_METHOD_LABELS = {
    "median": "Equal-weight median",
    "coherence_weighted_mean": "Coherence-weighted mean",
    "max_station": "Maximum station residual",
    "min_station": "Minimum station residual",
}
REFERENCE_METHOD_COLORS = {
    "median": "#3b528b",
    "coherence_weighted_mean": "#21918c",
    "max_station": "#e07a1f",
    "min_station": "#cc4778",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _software_provenance() -> dict[str, Any]:
    packages = (
        "nisar-isnobal-da-tuolumne",
        "snowin",
        "nisar-pytools",
        "numpy",
        "xarray",
        "rasterio",
        "h5py",
        "h5netcdf",
        "matplotlib",
    )
    versions: dict[str, str | None] = {}
    for package in packages:
        try:
            versions[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            versions[package] = None

    checkout = Path(snowin.__file__).resolve().parents[2]
    try:
        commit = subprocess.run(
            ["git", "-C", str(checkout), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        dirty = bool(
            subprocess.run(
                ["git", "-C", str(checkout), "status", "--porcelain"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
        )
    except (OSError, subprocess.CalledProcessError):
        commit, dirty = None, None
    return {
        "python": sys.version.split()[0],
        "packages": versions,
        "snowin_checkout_commit": commit,
        "snowin_checkout_dirty": dirty,
    }


def _safe_attr(value: Any) -> Any:
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, bool):
        return str(value).lower()
    if value is None:
        return ""
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, sort_keys=True, default=str)
    if isinstance(value, (str, int, float)):
        return value
    return str(value)


def _safe_dataset(dataset: xr.Dataset) -> xr.Dataset:
    result = dataset.copy(deep=False)
    result.attrs = {key: _safe_attr(value) for key, value in dataset.attrs.items()}
    for name in result.variables:
        result[name].attrs = {
            key: (
                np.asarray(value, dtype=np.uint8)
                if key == "flag_values"
                else _safe_attr(value)
            )
            for key, value in dataset[name].attrs.items()
            if key != "_FillValue"
        }
        result[name].encoding = {}
        if result[name].dtype.kind == "b":
            result[name] = result[name].astype("uint8")
    return result


def _write_netcdf(dataset: xr.Dataset, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    safe = _safe_dataset(dataset)
    encoding: dict[str, dict[str, Any]] = {}
    for name, variable in safe.data_vars.items():
        encoding[name] = {}
        if variable.ndim:
            encoding[name].update({"zlib": True, "complevel": 3, "shuffle": True})
        if variable.dtype.kind in "iu":
            encoding[name]["_FillValue"] = None
    safe.to_netcdf(temporary, engine="h5netcdf", encoding=encoding)
    temporary.replace(destination)


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    keys: list[str] = []
    for row in rows:
        for key in row:
            if key not in keys:
                keys.append(key)
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=keys, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _load_boundary() -> tuple[Any, Any]:
    collection = json.loads(BOUNDARY_PATH.read_text(encoding="utf-8"))
    feature = collection["features"][0]
    geometry = shape(feature["geometry"])
    to_grid = Transformer.from_crs("EPSG:4326", GRID_CRS, always_xy=True)
    projected = shapely_transform(to_grid.transform, geometry)
    return geometry, projected


def _load_stations() -> tuple[
    list[dict[str, str]], dict[str, dict[str, dict[str, str]]]
]:
    stations = _read_csv(STATION_METADATA)
    daily: dict[str, dict[str, dict[str, str]]] = defaultdict(dict)
    for row in _read_csv(STATION_DAILY):
        if row["date"] <= ANALYSIS_END_DATE:
            daily[row["station_id"]][row["date"]] = row
    return stations, daily


def _load_catalog() -> dict[str, dict[str, Any]]:
    inventory = json.loads(NISAR_INVENTORY.read_text(encoding="utf-8"))
    result: dict[str, dict[str, Any]] = {}
    for granule in inventory["granules"]:
        for item in granule["file_records"]:
            name = item.get("Name", "")
            if name.endswith(".h5") and not name.endswith("_QA_STATS.h5"):
                result[name] = {
                    "granule_concept_id": granule["granule_concept_id"],
                    "collection_concept_id": granule["collection_concept_id"],
                    "granule_ur": granule["granule_ur"],
                    "maturity": granule["maturity"],
                    "collection_version": granule["collection_version"],
                    "checksum_md5": item.get("Checksum", {}).get("Value"),
                    "size_bytes": item.get("SizeInBytes"),
                    "acquisition_end": granule.get("acquisition_end"),
                }
    return result


def _products(
    gunw_root: Path, catalog: dict[str, dict[str, Any]], frames: list[str]
) -> dict[str, list[Path]]:
    output: dict[str, list[Path]] = {}
    for frame in frames:
        if frame == "T042_F069":
            frame_marker = "_042_D_069_"
        elif frame == "T034_F021":
            frame_marker = "_034_A_021_"
        else:
            raise ValueError(f"unsupported frame: {frame}")
        # Track, orbit direction, and frame together identify the catalog path.
        inventory_names = {name for name in catalog if frame_marker in name}
        expected = {
            name
            for name in inventory_names
            if catalog[name]["acquisition_end"][:10] <= ANALYSIS_END_DATE
        }
        frame_dir = gunw_root / frame
        found = {
            path.name: path
            for path in frame_dir.glob("*.h5")
            if not path.name.endswith("_QA_STATS.h5")
        }
        missing = sorted(expected - found.keys())
        unknown = sorted(found.keys() - inventory_names)
        if missing or unknown:
            raise FileNotFoundError(
                f"{frame} products differ from the tracked inventory: "
                f"missing_through_cutoff={len(missing)}, unknown={len(unknown)}"
            )
        output[frame] = sorted(
            (found[name] for name in expected), key=lambda path: path.name
        )
    return output


def _window_sample(
    phase: np.ndarray,
    coherence: np.ndarray,
    row: int,
    col: int,
    *,
    radius: int = 2,
) -> dict[str, Any]:
    if row < 0 or col < 0 or row >= phase.shape[0] or col >= phase.shape[1]:
        return {
            "eligible": False,
            "reason": "outside_footprint",
            "phase_median_rad": np.nan,
            "coherence_median": np.nan,
            "pixel_count": 0,
        }
    r0, r1 = max(0, row - radius), min(phase.shape[0], row + radius + 1)
    c0, c1 = max(0, col - radius), min(phase.shape[1], col + radius + 1)
    phase_window = phase[r0:r1, c0:c1]
    coherence_window = coherence[r0:r1, c0:c1]
    keep = (
        np.isfinite(phase_window)
        & np.isfinite(coherence_window)
        & (coherence_window > 0)
    )
    phase_values = phase_window[keep]
    coherence_values = coherence_window[keep]
    eligible = bool(phase_values.size)
    return {
        "eligible": eligible,
        "reason": "eligible" if eligible else "no_finite_phase_and_coherence",
        "phase_median_rad": float(np.median(phase_values)) if eligible else np.nan,
        "coherence_median": float(np.median(coherence_values)) if eligible else np.nan,
        "pixel_count": int(phase_values.size),
    }


def _timestamp_date(value: str) -> str:
    if not isinstance(value, str) or len(value) < 10:
        raise ValueError(f"SnowIn returned an invalid UTC timestamp: {value!r}")
    return value[:10]


def _station_reference(
    pair: xr.Dataset,
    station_rows: list[dict[str, str]],
    daily: dict[str, dict[str, dict[str, str]]],
    boundary: Any,
    *,
    x: np.ndarray,
    y: np.ndarray,
) -> tuple[float, list[dict[str, Any]]]:
    to_grid = Transformer.from_crs("EPSG:4326", GRID_CRS, always_xy=True)
    reference_date = _timestamp_date(str(pair.attrs["reference_time"]))
    secondary_date = _timestamp_date(str(pair.attrs["secondary_time"]))
    wavelength = float(pair.attrs["wavelength_m"])
    phase = np.asarray(pair["phase"].data, dtype=float)
    coherence = np.asarray(pair["coherence"].data, dtype=float)
    incidence = np.asarray(pair["incidence_angle"].data, dtype=float)
    rows: list[dict[str, Any]] = []
    for station in station_rows:
        station_id = station["station_id"]
        lon, lat = float(station["lon"]), float(station["lat"])
        sx, sy = to_grid.transform(lon, lat)
        inside = bool(boundary.covers(Point(sx, sy)))
        col = (
            int(np.abs(x - sx).argmin()) if x.size and x.min() <= sx <= x.max() else -1
        )
        row = (
            int(np.abs(y - sy).argmin()) if y.size and y.min() <= sy <= y.max() else -1
        )
        sample = _window_sample(phase, coherence, row, col)
        center_angle = float(incidence[row, col]) if row >= 0 and col >= 0 else np.nan
        ref_row = daily.get(station_id, {}).get(reference_date)
        sec_row = daily.get(station_id, {}).get(secondary_date)
        try:
            ref_cm = (
                float(ref_row["swe_cm"]) if ref_row and ref_row["swe_cm"] else np.nan
            )
            sec_cm = (
                float(sec_row["swe_cm"]) if sec_row and sec_row["swe_cm"] else np.nan
            )
        except (KeyError, TypeError, ValueError):
            ref_cm = sec_cm = np.nan
        delta_mm = (
            10.0 * (sec_cm - ref_cm)
            if np.isfinite(ref_cm) and np.isfinite(sec_cm)
            else np.nan
        )
        geometry_ok = bool(
            np.isfinite(center_angle) and 0.0 < center_angle < math.pi / 2.0
        )
        eligible = (
            inside and np.isfinite(delta_mm) and sample["eligible"] and geometry_ok
        )
        if not inside:
            reason = "station outside basin polygon"
        elif not np.isfinite(delta_mm):
            reason = "missing exact-date CDEC SWE at one or both acquisitions"
        elif not sample["eligible"]:
            reason = sample["reason"]
        elif not geometry_ok:
            reason = "local incidence missing or outside (0, pi/2)"
        else:
            reason = "eligible"
        expected_phase = residual = np.nan
        if eligible:
            phase_per_mm = (
                2.0 * math.pi * (1.59 + center_angle**2.5) / wavelength / 1000.0
            )
            expected_phase = delta_mm * phase_per_mm
            residual = sample["phase_median_rad"] - expected_phase
        rows.append(
            {
                "station_id": station_id,
                "station_name": station.get("station_name", ""),
                "reference_date": reference_date,
                "secondary_date": secondary_date,
                "reference_swe_cm": ref_cm,
                "secondary_swe_cm": sec_cm,
                "delta_swe_mm": delta_mm,
                "phase_median_native_5x5_rad": sample["phase_median_rad"],
                "coherence_median_native_5x5": sample["coherence_median"],
                "native_window_valid_pixel_count": sample["pixel_count"],
                "incidence_angle_center_rad": center_angle,
                "expected_phase_secondary_minus_reference_rad": expected_phase,
                "residual_rad": residual,
                "eligible": eligible,
                "reason": reason,
                "reference_data_flag": ref_row.get("data_flag", "") if ref_row else "",
                "secondary_data_flag": sec_row.get("data_flag", "") if sec_row else "",
            }
        )
    eligible_residuals = [row["residual_rad"] for row in rows if row["eligible"]]
    if not eligible_residuals:
        raise RuntimeError(
            f"No eligible station residuals for {reference_date} to {secondary_date}"
        )
    return float(np.median(eligible_residuals)), rows


def _reference_method_offsets(
    station_reference_rows: list[dict[str, Any]],
) -> dict[str, float]:
    eligible = [
        row
        for row in station_reference_rows
        if row["eligible"] and np.isfinite(row["residual_rad"])
    ]
    if not eligible:
        raise ValueError("cannot compare reference methods without eligible stations")
    residuals = np.asarray([row["residual_rad"] for row in eligible], dtype=float)
    coherences = np.asarray(
        [row["coherence_median_native_5x5"] for row in eligible], dtype=float
    )
    if not np.isfinite(coherences).all() or np.any(coherences <= 0.0):
        raise ValueError(
            "eligible station coherence weights must be finite and positive"
        )
    total_coherence = float(coherences.sum())
    return {
        "median": float(np.median(residuals)),
        "coherence_weighted_mean": float(
            np.sum(coherences * residuals) / total_coherence
        ),
        "max_station": float(np.max(residuals)),
        "min_station": float(np.min(residuals)),
    }


def _reference_method_comparison(
    pair_path: Path, frame: str, output_dir: Path
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Write four pairwise dSWE rasters using identical input support."""
    with xr.open_dataset(pair_path, engine="h5netcdf") as opened:
        pair = opened.load()
    try:
        station_reference_rows = json.loads(
            pair.attrs.get("station_reference_rows_json", "[]")
        )
        offsets = _reference_method_offsets(station_reference_rows)
        reference_time = str(pair.attrs["reference_time"])
        secondary_time = str(pair.attrs["secondary_time"])
        source_granule_id = str(pair.attrs["source_granule_id"])
        wavelength = float(pair.attrs["wavelength_m"])
        basin = np.asarray(pair["basin_mask"].data, dtype=bool)
        median_values = np.asarray(pair["dswe"].data, dtype=float) * 1000.0
        valid_baseline = basin & np.isfinite(median_values)
        x = pair.x
        y = pair.y
        edge_rows: list[dict[str, Any]] = []
        for method in REFERENCE_METHODS:
            offset = offsets[method]
            method_dswe = (
                np.asarray(
                    compute_dswe(
                        pair["phase"] - offset,
                        pair["incidence_angle"],
                        wavelength_m=wavelength,
                    ).data,
                    dtype=float,
                )
                * 1000.0
            )
            valid = valid_baseline & np.isfinite(method_dswe)
            values = method_dswe[valid]
            shifts = method_dswe[valid] - median_values[valid]
            method_pair_path = (
                output_dir
                / "reference_sensitivity"
                / "pairs"
                / method
                / frame
                / f"{pair_path.stem}.nc"
            )
            method_pair = xr.Dataset(
                {
                    "dswe": (
                        ("y", "x"),
                        np.where(valid, method_dswe / 1000.0, np.nan).astype("float32"),
                    ),
                },
                coords={"x": x, "y": y},
                attrs={
                    "frame": frame,
                    "source_granule_id": source_granule_id,
                    "reference_time": reference_time,
                    "secondary_time": secondary_time,
                    "temporal_edge": "reference_to_secondary",
                    "reference_method": method,
                    "reference_method_label": REFERENCE_METHOD_LABELS[method],
                    "reference_offset_rad": offset,
                    "quantity": "pairwise_dSWE",
                    "absolute_swe": "false",
                },
            )
            method_pair["pairwise_supported"] = xr.DataArray(
                valid.astype(bool), dims=("y", "x"), coords={"y": y, "x": x}
            )
            method_pair["dswe"].attrs.update(
                {
                    "units": "m",
                    "quantity": "pairwise_dSWE",
                    "phase_difference_definition": "secondary_minus_reference",
                    "reference_method": method,
                    "reference_offset_rad": offset,
                }
            )
            method_pair["pairwise_supported"].attrs["meaning"] = (
                "finite pairwise dSWE support inside the basin mask"
            )
            method_pair["basin_mask"] = xr.DataArray(
                basin.astype("uint8"), dims=("y", "x"), coords={"y": y, "x": x}
            )
            _write_netcdf(method_pair, method_pair_path)
            method_pair.close()
            edge_rows.append(
                {
                    "frame": frame,
                    "source_granule_id": source_granule_id,
                    "reference_time": reference_time,
                    "secondary_time": secondary_time,
                    "reference_method": method,
                    "reference_method_label": REFERENCE_METHOD_LABELS[method],
                    "reference_offset_rad": offset,
                    "offset_shift_from_median_rad": offset - offsets["median"],
                    "pairwise_raster_path": str(method_pair_path),
                    "eligible_station_count": len(
                        [row for row in station_reference_rows if row["eligible"]]
                    ),
                    "pairwise_coverage_fraction": float(values.size / basin.sum()),
                    "pairwise_dswe_median_mm": float(np.median(values))
                    if values.size
                    else np.nan,
                    "pairwise_dswe_p25_mm": float(np.percentile(values, 25))
                    if values.size
                    else np.nan,
                    "pairwise_dswe_p75_mm": float(np.percentile(values, 75))
                    if values.size
                    else np.nan,
                    "median_dswe_shift_from_median_mm": float(np.median(shifts))
                    if shifts.size
                    else np.nan,
                    "mean_absolute_dswe_shift_from_median_mm": float(
                        np.mean(np.abs(shifts))
                    )
                    if shifts.size
                    else np.nan,
                    "p95_absolute_dswe_shift_from_median_mm": float(
                        np.percentile(np.abs(shifts), 95)
                    )
                    if shifts.size
                    else np.nan,
                }
            )

        station_rows: list[dict[str, Any]] = []
        for row in station_reference_rows:
            residual = float(row["residual_rad"])
            incidence = float(row["incidence_angle_center_rad"])
            sensitivity = (
                2.0 * math.pi * (1.59 + incidence**2.5) / wavelength / 1000.0
                if np.isfinite(incidence) and incidence > 0.0
                else np.nan
            )
            station_result = {
                "frame": frame,
                "source_granule_id": source_granule_id,
                "reference_time": reference_time,
                "secondary_time": secondary_time,
                "station_id": row["station_id"],
                "station_name": row["station_name"],
                "eligible": row["eligible"],
                "eligibility_reason": row["reason"],
                "coherence_weight": row["coherence_median_native_5x5"],
                "station_phase_residual_before_reference_rad": residual,
            }
            for method in REFERENCE_METHODS:
                method_residual = residual - offsets[method]
                station_result[f"reference_offset_{method}_rad"] = offsets[method]
                station_result[f"station_residual_after_{method}_rad"] = (
                    method_residual if row["eligible"] else np.nan
                )
                station_result[f"station_residual_after_{method}_mm"] = (
                    method_residual / sensitivity
                    if row["eligible"] and np.isfinite(sensitivity) and sensitivity > 0
                    else np.nan
                )
            station_rows.append(station_result)
        return edge_rows, station_rows
    finally:
        pair.close()


def _mask_for_pair(pair: xr.Dataset, boundary: Any) -> np.ndarray:
    x = np.asarray(pair.x.data, dtype=float)
    y = np.asarray(pair.y.data, dtype=float)
    dx, dy = float(np.median(np.diff(x))), float(np.median(np.diff(y)))
    transform = Affine(dx, 0.0, x[0] - dx / 2.0, 0.0, dy, y[0] - dy / 2.0)
    return geometry_mask(
        [boundary.__geo_interface__],
        out_shape=(y.size, x.size),
        transform=transform,
        invert=True,
        all_touched=False,
    )


def _open_nisar_pair(
    path: Path,
    boundary: Any,
    dem_path: Path,
) -> xr.Dataset:
    """Read DataArray-based nisar_pytools output into SnowIn's pair contract.

    SnowIn's current ``open_gunw`` expects ``get_gunw`` to return a Dataset,
    while nisar_pytools 0.5.0 returns a DataArray. This adapter uses the
    upstream arrays directly and delegates phase normalization, metadata
    validation, and dSWE science to SnowIn.
    """
    tree = open_nisar(path, chunks="auto")
    try:
        raw_phase = get_gunw(
            tree,
            variable="unwrappedPhase",
            polarization="HH",
            layer="unwrappedInterferogram",
            frequency="frequencyA",
            valid_mask=False,
        )
        coherence = get_gunw(
            tree,
            variable="coherenceMagnitude",
            polarization="HH",
            layer="unwrappedInterferogram",
            frequency="frequencyA",
            valid_mask=False,
        ).rename("coherence")
        components = get_gunw(
            tree,
            variable="connectedComponents",
            polarization="HH",
            layer="unwrappedInterferogram",
            frequency="frequencyA",
            valid_mask=False,
        ).rename("connected_component")
        projection = raw_phase.coords.get("projection")
        if projection is None or not projection.attrs.get("crs_wkt"):
            raise ValueError(f"GUNW projection metadata is missing in {path.name}")
        spatial_attrs = dict(projection.attrs)
        epsg = CRS.from_wkt(spatial_attrs["crs_wkt"]).to_epsg()
        if epsg is None:
            raise ValueError(f"GUNW WKT does not resolve to EPSG in {path.name}")
        spatial_attrs["epsg_code"] = epsg
        spatial_ref = xr.DataArray(
            projection.data, attrs=spatial_attrs, name="spatial_ref"
        )

        def clean_projection(variable: xr.DataArray) -> xr.DataArray:
            if "projection" in variable.coords:
                return variable.reset_coords("projection", drop=True)
            return variable

        raw_phase = clean_projection(raw_phase)
        coherence = clean_projection(coherence)
        components = clean_projection(components)
        x_values = np.asarray(raw_phase.x.data, dtype=float)
        y_values = np.asarray(raw_phase.y.data, dtype=float)
        minx, miny, maxx, maxy = boundary.bounds
        x_indices = np.flatnonzero(
            (x_values >= minx - 5000) & (x_values <= maxx + 5000)
        )
        y_indices = np.flatnonzero(
            (y_values >= miny - 5000) & (y_values <= maxy + 5000)
        )
        if not x_indices.size or not y_indices.size:
            raise RuntimeError(f"basin boundary does not intersect {path.name}")
        y_slice = slice(int(y_indices[0]), int(y_indices[-1]) + 1)
        x_slice = slice(int(x_indices[0]), int(x_indices[-1]) + 1)
        raw_crop = raw_phase.isel(y=y_slice, x=x_slice)
        coherence_crop = coherence.isel(y=y_slice, x=x_slice)
        components_crop = components.isel(y=y_slice, x=x_slice)
        target = xr.Dataset(
            {"phase": raw_crop},
            coords={"spatial_ref": spatial_ref},
            attrs={"source_granule_id": path.stem},
        )
        incidence = compute_gunw_incidence(
            path,
            target,
            dem_source="nisar_cop30",
            nisar_cop30_dem=dem_path,
            require_vertical_datum_match=True,
            chunks=None,
            geometry_chunks=256,
            progress=False,
        ).load()
        with h5py.File(path, "r") as source:
            identification = source["/science/LSAR/identification"]

            def metadata_text(name: str) -> str:
                value = identification[name][()]
                if isinstance(value, bytes):
                    value = value.decode()
                return f"{str(value)}Z"

            reference_time = metadata_text("referenceZeroDopplerStartTime")
            secondary_time = metadata_text("secondaryZeroDopplerStartTime")
        pair = normalize_gunw_pair(
            raw_crop,
            incidence,
            wavelength_m=read_gunw_wavelength_m(path),
            reference_time=reference_time,
            secondary_time=secondary_time,
            source_phase_difference_definition=NISAR_GUNW_SOURCE_PHASE_DEFINITION,
            spatial_ref=spatial_ref,
            source_granule_id=path.stem,
            additional_variables={
                "coherence": coherence_crop,
                "connected_component": components_crop,
            },
            provenance={
                "source_reader": (
                    "nisar_pytools DataArray reader + SnowIn pair normalizer"
                ),
                "correction_layers_applied": False,
            },
        )
        pair.attrs["spatial_subset"] = "native GUNW grid within 5 km of basin bounds"
        pair.load()
        return pair
    finally:
        tree.close()


def _process_product(
    path: Path,
    frame: str,
    product_info: dict[str, Any],
    *,
    dem_path: Path,
    stations: list[dict[str, str]],
    daily: dict[str, dict[str, dict[str, str]]],
    boundary: Any,
    output_dir: Path,
    force: bool,
) -> tuple[Path, dict[str, Any], list[dict[str, Any]]]:
    destination = output_dir / "pairs" / frame / f"{path.stem}.nc"
    if destination.exists() and not force:
        with xr.open_dataset(destination, engine="h5netcdf") as saved:
            if saved.attrs.get("source_granule_id") != path.stem:
                raise RuntimeError(
                    f"stale pair output has a different source: {destination}"
                )
        with xr.open_dataset(destination, engine="h5netcdf") as saved:
            summary = _edge_summary(saved, frame, path.name)
            ref_rows = json.loads(saved.attrs.get("station_reference_rows_json", "[]"))
        return destination, summary, ref_rows

    print(f"[{frame}] opening {path.name}", flush=True)
    pair = _open_nisar_pair(path, boundary, dem_path)

    x = np.asarray(pair.x.data, dtype=float)
    y = np.asarray(pair.y.data, dtype=float)
    if not np.isclose(abs(np.median(np.diff(x))), 80.0) or not np.isclose(
        abs(np.median(np.diff(y))), 80.0
    ):
        raise RuntimeError(f"unexpected 80 m GUNW grid spacing in {path.name}")
    basin_mask = _mask_for_pair(pair, boundary)
    offset, reference_rows = _station_reference(
        pair, stations, daily, boundary, x=x, y=y
    )
    referenced = reference_phase(pair, method="manual_offset", offset_rad=offset)
    dswe = compute_dswe(
        referenced["phase_referenced"],
        referenced["incidence_angle"],
        wavelength_m=float(pair.attrs["wavelength_m"]),
    )
    dswe = dswe.where(
        xr.DataArray(basin_mask, dims=("y", "x"), coords={"y": y, "x": x})
    )
    dswe.attrs.update(
        {
            "grid_mapping": "spatial_ref",
            "aoi_mask": BOUNDARY_PATH.name,
            "reference_aggregation_method": (
                "median eligible in-basin station residuals (equal weight)"
            ),
        }
    )
    referenced["dswe"] = dswe
    referenced["pairwise_supported"] = np.isfinite(dswe)
    referenced["basin_mask"] = xr.DataArray(
        basin_mask.astype("uint8"), dims=("y", "x"), coords={"y": y, "x": x}
    )
    for coordinate in ("x", "y"):
        referenced[coordinate].attrs.setdefault("units", "m")
    with h5py.File(path, "r") as source:
        ident = source["/science/LSAR/identification"]

        def text_scalar(name: str) -> str:
            value = ident[name][()]
            return value.decode() if isinstance(value, bytes) else str(value)

        release_id = text_scalar("compositeReleaseId")
        product_version = text_scalar("productVersion")
        spec_version = text_scalar("productSpecificationVersion")
    eligible = [row for row in reference_rows if row["eligible"]]
    referenced.attrs.update(
        {
            "source_granule_id": path.stem,
            "processing_maturity": product_info["maturity"],
            "processing_crid": release_id,
            "processing_product_version": product_version,
            "processing_specification_version": spec_version,
            "processing_collection_version": product_info["collection_version"],
            "granule_concept_id": product_info["granule_concept_id"],
            "collection_concept_id": product_info["collection_concept_id"],
            "retrieval_method": (
                "SnowIn Leinss dSWE with per-product wavelength and local incidence"
            ),
            "reference_method": "manual_offset",
            "reference_aggregation_method": (
                "median eligible in-basin station residuals (equal weight)"
            ),
            "reference_offset_rad": offset,
            "reference_station_count": len(eligible),
            "reference_station_ids": [row["station_id"] for row in eligible],
            "station_reference_rows_json": reference_rows,
            "basin_boundary_source": BOUNDARY_PATH.name,
            "dem_sha256": _sha256(dem_path),
            "source_product_size_bytes": path.stat().st_size,
            "source_catalog_md5": product_info["checksum_md5"],
            "correction_layers_applied": False,
            "coherence_threshold_applied": False,
            "connected_component_mask_applied": False,
            "temporal_accumulation_policy": (
                "contiguous segments; missing support propagates"
            ),
        }
    )
    referenced["pairwise_supported"].attrs.update(
        {
            "long_name": "finite pairwise dSWE support inside the basin mask",
            "flag_values": np.array([0, 1], dtype=np.uint8),
            "flag_meanings": "unsupported supported",
        }
    )
    observation = adapt_snowin_observation(
        referenced,
        processing_maturity=str(product_info["maturity"]),
        processing_crid=release_id,
        processing_product_version=product_version,
        processing_collection_version=str(product_info["collection_version"]),
    )
    _write_netcdf(observation, destination)
    with xr.open_dataset(destination, engine="h5netcdf") as saved:
        summary = _edge_summary(saved, frame, path.name)
    print(
        f"[{frame}] wrote {destination.name}; {len(eligible)} eligible stations; "
        f"offset={offset:+.5f} rad",
        flush=True,
    )
    return destination, summary, reference_rows


def _edge_summary(dataset: xr.Dataset, frame: str, filename: str) -> dict[str, Any]:
    dswe = np.asarray(dataset["dswe"].data, dtype=float) * 1000.0
    incidence = np.asarray(dataset["incidence_angle"].data, dtype=float)
    basin = np.asarray(dataset["basin_mask"].data, dtype=bool)
    finite_dswe = dswe[basin & np.isfinite(dswe)]
    finite_angle = incidence[basin & np.isfinite(incidence)]
    return {
        "frame": frame,
        "source_granule_id": filename.removesuffix(".h5"),
        "reference_time": dataset.attrs["reference_time"],
        "secondary_time": dataset.attrs["secondary_time"],
        "wavelength_m": float(dataset.attrs["wavelength_m"]),
        "phase_source_definition": dataset.attrs.get(
            "source_phase_difference_definition"
        ),
        "phase_transform": dataset.attrs.get("phase_transform"),
        "phase_reference_method": dataset.attrs.get("reference_aggregation_method"),
        "reference_offset_rad": float(dataset.attrs["reference_offset_rad"]),
        "eligible_station_count": int(dataset.attrs["reference_station_count"]),
        "eligible_station_ids": dataset.attrs["reference_station_ids"],
        "basin_pixel_count": int(basin.sum()),
        "pairwise_valid_pixel_count": int(finite_dswe.size),
        "pairwise_coverage_fraction": float(finite_dswe.size / basin.sum()),
        "pairwise_dswe_median_mm": float(np.median(finite_dswe))
        if finite_dswe.size
        else np.nan,
        "pairwise_dswe_p25_mm": float(np.percentile(finite_dswe, 25))
        if finite_dswe.size
        else np.nan,
        "pairwise_dswe_p75_mm": float(np.percentile(finite_dswe, 75))
        if finite_dswe.size
        else np.nan,
        "local_incidence_median_deg": float(np.degrees(np.median(finite_angle)))
        if finite_angle.size
        else np.nan,
        "local_incidence_p10_deg": float(np.degrees(np.percentile(finite_angle, 10)))
        if finite_angle.size
        else np.nan,
        "local_incidence_p90_deg": float(np.degrees(np.percentile(finite_angle, 90)))
        if finite_angle.size
        else np.nan,
    }


def _cumulative_paths(
    frame: str,
    pair_paths: list[Path],
    output_dir: Path,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    records: list[tuple[Path, str, str]] = []
    for path in pair_paths:
        with xr.open_dataset(path, engine="h5netcdf") as pair:
            records.append(
                (
                    path,
                    str(pair.attrs["reference_time"]),
                    str(pair.attrs["secondary_time"]),
                )
            )
    records.sort(key=lambda item: item[1])
    segments: list[list[tuple[Path, str, str]]] = []
    for record in records:
        if not segments or record[1] != segments[-1][-1][2]:
            segments.append([])
        segments[-1].append(record)

    summary: list[dict[str, Any]] = []
    segment_notes: list[dict[str, Any]] = []
    for segment_number, segment in enumerate(segments, start=1):
        anchor = segment[0][1]
        print(
            f"[{frame}] accumulating segment {segment_number} from {anchor}",
            flush=True,
        )
        opened_edges: list[xr.Dataset] = []
        try:
            for pair_path, _, _ in segment:
                pair = xr.open_dataset(pair_path, engine="h5netcdf")
                pair["pairwise_supported"] = pair["pairwise_supported"].astype(bool)
                opened_edges.append(pair)
            cumulative_path = accumulate_dswe(
                opened_edges,
                dswe_variable="dswe",
                initial_time=anchor,
            )
            template = opened_edges[0]
            mask = np.asarray(template["basin_mask"].data, dtype=bool)
            for index, (pair_path, reference_time, secondary_time) in enumerate(
                segment
            ):
                cumulative = (
                    np.asarray(
                        cumulative_path["cumulative_dswe"].isel(time=index).data,
                        dtype=np.float32,
                    )
                    * 1000.0
                )
                support = np.asarray(
                    cumulative_path["temporal_path_supported"].isel(time=index).data,
                    dtype=bool,
                )
                out = xr.Dataset(
                    {
                        "cumulative_dswe_mm": (("y", "x"), cumulative),
                        "temporal_path_supported": (
                            ("y", "x"),
                            support.astype("uint8"),
                        ),
                        "basin_mask": template["basin_mask"],
                    },
                    coords={"x": template.x, "y": template.y},
                    attrs={
                        "frame": frame,
                        "segment_number": segment_number,
                        "segment_start_time": anchor,
                        "reference_time": reference_time,
                        "secondary_time": secondary_time,
                        "source_pair": pair_path.name,
                        "quantity": "cumulative_dSWE_within_connected_temporal_segment",
                        "units": "mm",
                        "absolute_swe": "false",
                        "accumulator": "snowin.temporal.accumulate_dswe",
                    },
                )
                out["cumulative_dswe_mm"].attrs.update(
                    {"units": "mm", "quantity": "cumulative_dSWE"}
                )
                out["temporal_path_supported"].attrs["meaning"] = (
                    "all edges since segment start supported"
                )
                cum_path = (
                    output_dir
                    / "cumulative"
                    / frame
                    / f"segment{segment_number:02d}_{pair_path.stem}.nc"
                )
                _write_netcdf(out, cum_path)
                values = cumulative[mask & np.isfinite(cumulative)]
                summary.append(
                    {
                        "frame": frame,
                        "segment_number": segment_number,
                        "segment_start_time": anchor,
                        "reference_time": reference_time,
                        "secondary_time": secondary_time,
                        "cumulative_dswe_path": str(cum_path),
                        "basin_pixel_count": int(mask.sum()),
                        "cumulative_supported_pixel_count": int(values.size),
                        "cumulative_coverage_fraction": float(values.size / mask.sum()),
                        "cumulative_dswe_median_mm": float(np.median(values))
                        if values.size
                        else np.nan,
                        "cumulative_dswe_p25_mm": float(np.percentile(values, 25))
                        if values.size
                        else np.nan,
                        "cumulative_dswe_p75_mm": float(np.percentile(values, 75))
                        if values.size
                        else np.nan,
                    }
                )
        finally:
            for pair in opened_edges:
                pair.close()
        segment_notes.append(
            {
                "frame": frame,
                "segment_number": segment_number,
                "segment_start_time": anchor,
                "segment_end_time": segment[-1][2],
                "edge_count": len(segment),
                "contiguous": True,
            }
        )
    return summary, segment_notes


def _cumulative_reference_method_paths(
    reference_rows: list[dict[str, Any]],
    baseline_cumulative_rows: list[dict[str, Any]],
    output_dir: Path,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Accumulate each reference method and compare every endpoint to median."""
    baseline_paths = {
        (row["frame"], row["secondary_time"]): Path(row["cumulative_dswe_path"])
        for row in baseline_cumulative_rows
    }
    summary_rows: list[dict[str, Any]] = []
    segment_notes: list[dict[str, Any]] = []
    for method in REFERENCE_METHODS:
        for frame in FRAME_NAMES:
            records = sorted(
                (
                    row
                    for row in reference_rows
                    if row["reference_method"] == method and row["frame"] == frame
                ),
                key=lambda row: row["reference_time"],
            )
            segments: list[list[dict[str, Any]]] = []
            for record in records:
                if (
                    not segments
                    or record["reference_time"] != segments[-1][-1]["secondary_time"]
                ):
                    segments.append([])
                segments[-1].append(record)

            for segment_number, segment in enumerate(segments, start=1):
                anchor = segment[0]["reference_time"]
                opened_edges: list[xr.Dataset] = []
                try:
                    for record in segment:
                        pair = xr.open_dataset(
                            record["pairwise_raster_path"], engine="h5netcdf"
                        ).load()
                        pair["pairwise_supported"] = pair["pairwise_supported"].astype(
                            bool
                        )
                        opened_edges.append(pair)
                    cumulative = accumulate_dswe(
                        opened_edges,
                        dswe_variable="dswe",
                        initial_time=anchor,
                    )
                    template = opened_edges[0]
                    basin = np.asarray(template["basin_mask"].data, dtype=bool)
                    for index, record in enumerate(segment):
                        cumulative_mm = (
                            np.asarray(
                                cumulative["cumulative_dswe"].isel(time=index).data,
                                dtype=np.float32,
                            )
                            * 1000.0
                        )
                        support = np.asarray(
                            cumulative["temporal_path_supported"].isel(time=index).data,
                            dtype=bool,
                        )
                        output_path = (
                            output_dir
                            / "reference_sensitivity"
                            / "cumulative"
                            / method
                            / frame
                            / (
                                f"segment{segment_number:02d}_"
                                f"{Path(record['pairwise_raster_path']).stem}.nc"
                            )
                        )
                        result = xr.Dataset(
                            {
                                "cumulative_dswe_mm": (
                                    ("y", "x"),
                                    cumulative_mm,
                                ),
                                "temporal_path_supported": (
                                    ("y", "x"),
                                    support.astype("uint8"),
                                ),
                                "basin_mask": template["basin_mask"],
                            },
                            coords={"x": template.x, "y": template.y},
                            attrs={
                                "frame": frame,
                                "reference_method": method,
                                "segment_number": segment_number,
                                "segment_start_time": anchor,
                                "reference_time": record["reference_time"],
                                "secondary_time": record["secondary_time"],
                                "source_pair": Path(
                                    record["pairwise_raster_path"]
                                ).name,
                                "quantity": (
                                    "cumulative_dSWE_within_connected_temporal_segment"
                                ),
                                "units": "mm",
                                "absolute_swe": "false",
                                "accumulator": "snowin.temporal.accumulate_dswe",
                            },
                        )
                        result["cumulative_dswe_mm"].attrs.update(
                            {"units": "mm", "quantity": "cumulative_dSWE"}
                        )
                        result["temporal_path_supported"].attrs["meaning"] = (
                            "all edges since segment start supported"
                        )
                        _write_netcdf(result, output_path)
                        result.close()

                        valid = basin & support & np.isfinite(cumulative_mm)
                        values = cumulative_mm[valid]
                        baseline_path = baseline_paths[
                            (frame, record["secondary_time"])
                        ]
                        with xr.open_dataset(
                            baseline_path, engine="h5netcdf"
                        ) as baseline_opened:
                            baseline = baseline_opened.load()
                        try:
                            baseline_values = np.asarray(
                                baseline["cumulative_dswe_mm"].data, dtype=float
                            )
                            baseline_support = np.asarray(
                                baseline["temporal_path_supported"].data, dtype=bool
                            )
                            common = (
                                basin
                                & support
                                & baseline_support
                                & np.isfinite(cumulative_mm)
                                & np.isfinite(baseline_values)
                            )
                            shifts = cumulative_mm[common] - baseline_values[common]
                        finally:
                            baseline.close()
                        summary_rows.append(
                            {
                                "frame": frame,
                                "source_granule_id": record["source_granule_id"],
                                "reference_method": method,
                                "reference_method_label": REFERENCE_METHOD_LABELS[
                                    method
                                ],
                                "segment_number": segment_number,
                                "segment_start_time": anchor,
                                "reference_time": record["reference_time"],
                                "secondary_time": record["secondary_time"],
                                "cumulative_raster_path": str(output_path),
                                "basin_pixel_count": int(basin.sum()),
                                "cumulative_supported_pixel_count": int(values.size),
                                "cumulative_coverage_fraction": float(
                                    values.size / basin.sum()
                                ),
                                "cumulative_dswe_median_mm": float(np.median(values))
                                if values.size
                                else np.nan,
                                "cumulative_dswe_p25_mm": float(
                                    np.percentile(values, 25)
                                )
                                if values.size
                                else np.nan,
                                "cumulative_dswe_p75_mm": float(
                                    np.percentile(values, 75)
                                )
                                if values.size
                                else np.nan,
                                "median_cumulative_shift_from_median_mm": float(
                                    np.median(shifts)
                                )
                                if shifts.size
                                else np.nan,
                                "mean_absolute_cumulative_shift_from_median_mm": float(
                                    np.mean(np.abs(shifts))
                                )
                                if shifts.size
                                else np.nan,
                                "p95_absolute_cumulative_shift_from_median_mm": float(
                                    np.percentile(np.abs(shifts), 95)
                                )
                                if shifts.size
                                else np.nan,
                            }
                        )
                finally:
                    for pair in opened_edges:
                        pair.close()
                segment_notes.append(
                    {
                        "frame": frame,
                        "reference_method": method,
                        "segment_number": segment_number,
                        "segment_start_time": anchor,
                        "segment_end_time": segment[-1]["secondary_time"],
                        "edge_count": len(segment),
                        "contiguous": True,
                    }
                )
    return summary_rows, segment_notes


def _viirs_scene(path: Path) -> tuple[np.ndarray, Any, str]:
    with h5py.File(path, "r") as source:
        raw = source[VIIRS_FIELD][...]
        attrs = source[VIIRS_FIELD].attrs
        fill = int(np.asarray(attrs.get("_FillValue", VIIRS_FILL)).reshape(-1)[0])
        metadata = source["HDFEOS INFORMATION/StructMetadata.0"][()].decode(
            errors="replace"
        )
    upper = re.search(r"UpperLeftPointMtrs=\(([^)]+)\)", metadata)
    lower = re.search(r"LowerRightMtrs=\(([^)]+)\)", metadata)
    if not upper or not lower:
        raise ValueError(f"missing HDF-EOS sinusoidal bounds: {path}")
    ul = tuple(float(value) for value in upper.group(1).split(","))
    lr = tuple(float(value) for value in lower.group(1).split(","))
    ndsi = raw.astype("float32") * VIIRS_SCALE
    valid = (raw != fill) & (ndsi >= 0.0) & (ndsi <= 1.0)
    fsca = np.full(raw.shape, np.nan, dtype="float32")
    fsca[valid] = VIIRS_FSCA_INTERCEPT + VIIRS_FSCA_SLOPE * ndsi[valid]
    transform = from_bounds(ul[0], lr[1], lr[0], ul[1], raw.shape[1], raw.shape[0])
    date_match = re.search(r"\.A(\d{7})\.", path.name)
    if not date_match:
        raise ValueError(f"cannot parse VIIRS product date: {path.name}")
    year, day_of_year = int(date_match.group(1)[:4]), int(date_match.group(1)[4:])
    scene_date = (
        datetime(year, 1, 1, tzinfo=UTC)
        .date()
        .fromordinal(
            datetime(year, 1, 1, tzinfo=UTC).date().toordinal() + day_of_year - 1
        )
        .isoformat()
    )
    return fsca, transform, scene_date


def _reproject_viirs(path: Path, pair: xr.Dataset) -> tuple[np.ndarray, np.ndarray]:
    fsca_source, source_transform, _ = _viirs_scene(path)
    x = np.asarray(pair.x.data, dtype=float)
    y = np.asarray(pair.y.data, dtype=float)
    dx, dy = float(np.median(np.diff(x))), float(np.median(np.diff(y)))
    target_transform = Affine(dx, 0.0, x[0] - dx / 2.0, 0.0, dy, y[0] - dy / 2.0)
    target = np.full((y.size, x.size), np.nan, dtype="float32")
    reproject(
        fsca_source,
        target,
        src_transform=source_transform,
        src_crs="+proj=sinu +R=6371007.181 +lon_0=0 +units=m +no_defs",
        src_nodata=np.nan,
        dst_transform=target_transform,
        dst_crs=GRID_CRS,
        dst_nodata=np.nan,
        resampling=Resampling.bilinear,
    )
    return target, np.asarray(pair["basin_mask"].data, dtype=bool)


def _viirs_products(
    pair_paths: dict[str, list[Path]], output_dir: Path
) -> tuple[
    list[dict[str, Any]],
    dict[str, tuple[np.ndarray, np.ndarray, xr.Dataset, str]],
]:
    manifest = json.loads(VIIRS_MANIFEST.read_text(encoding="utf-8"))
    files = {
        item["product_date"]: VIIRS_ROOT / item["filename"]
        for item in manifest["products"]
    }
    summaries: list[dict[str, Any]] = []
    display: dict[str, tuple[np.ndarray, np.ndarray, xr.Dataset, str]] = {}
    display_dates = {"T042_F069": "2026-04-06", "T034_F021": "2026-04-05"}
    for frame, paths in pair_paths.items():
        dates: set[str] = set()
        templates: dict[str, Path] = {}
        for path in paths:
            with xr.open_dataset(path, engine="h5netcdf") as pair:
                for key in ("reference_time", "secondary_time"):
                    day = _timestamp_date(str(pair.attrs[key]))
                    dates.add(day)
                    templates.setdefault(day, path)
        for day in sorted(dates):
            if day not in files or not files[day].is_file():
                raise FileNotFoundError(
                    f"VIIRS VJ110A1F is missing for NISAR date {day}"
                )
            with xr.open_dataset(templates[day], engine="h5netcdf") as pair:
                fsca, basin = _reproject_viirs(files[day], pair)
                finite = basin & np.isfinite(fsca)
                any_snow = finite & (fsca > 0.0)
                strict_snow = finite & (fsca >= VIIRS_THRESHOLD)
                n_basin, n_finite = int(basin.sum()), int(finite.sum())
                values = fsca[finite]
                summaries.append(
                    {
                        "frame": frame,
                        "product_date": day,
                        "granule": files[day].name,
                        "basin_pixel_count": n_basin,
                        "finite_fsca_pixel_count": n_finite,
                        "valid_fsca_coverage_fraction": float(n_finite / n_basin),
                        "fsca_gt0_pixel_count": int(any_snow.sum()),
                        "fsca_gt0_fraction_of_finite": float(any_snow.sum() / n_finite)
                        if n_finite
                        else np.nan,
                        "fsca_ge_0_50_pixel_count": int(strict_snow.sum()),
                        "fsca_ge_0_50_fraction_of_finite": float(
                            strict_snow.sum() / n_finite
                        )
                        if n_finite
                        else np.nan,
                        "median_fsca": float(np.median(values))
                        if values.size
                        else np.nan,
                        "mask_role": "evaluation diagnostic; retrieval unchanged",
                    }
                )
                if day == display_dates[frame]:
                    display[frame] = (fsca.copy(), basin.copy(), pair.load(), day)
    _write_csv(output_dir / "tables/viirs_mask_coverage.csv", summaries)
    return summaries, display


def _projected_polygon(
    ax: Any, geometry: Any, *, color: str = "black", linewidth: float = 1.0
) -> None:
    polygons = list(geometry.geoms) if hasattr(geometry, "geoms") else [geometry]
    for polygon in polygons:
        x, y = polygon.exterior.xy
        ax.plot(x, y, color=color, linewidth=linewidth)


def _extent(x: np.ndarray, y: np.ndarray) -> tuple[float, float, float, float]:
    dx = abs(float(np.median(np.diff(x)))) / 2.0
    dy = abs(float(np.median(np.diff(y)))) / 2.0
    return (
        float(x.min() - dx),
        float(x.max() + dx),
        float(y.min() - dy),
        float(y.max() + dy),
    )


def _imshow(ax: Any, values: np.ndarray, dataset: xr.Dataset, **kwargs: Any) -> Any:
    x, y = np.asarray(dataset.x.data), np.asarray(dataset.y.data)
    image = np.asarray(values)
    if y.size > 1 and y[0] > y[-1]:
        image = np.flip(image, axis=-2)
    if x.size > 1 and x[0] > x[-1]:
        image = np.flip(image, axis=-1)
    return ax.imshow(
        image,
        extent=_extent(x, y),
        origin="lower",
        interpolation="nearest",
        **kwargs,
    )


def _save_figure(fig: Any, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(destination.with_suffix(".png"), dpi=220, bbox_inches="tight")
    fig.savefig(destination.with_suffix(".pdf"), bbox_inches="tight")
    plt.close(fig)


def _verify_common_nisar_grid(
    pair_paths: dict[str, list[Path]],
) -> Path:
    paths = [path for frame_paths in pair_paths.values() for path in frame_paths]
    if not paths:
        raise ValueError("no pair products available to define the NISAR grid")
    template_path = paths[0]
    with xr.open_dataset(template_path, engine="h5netcdf") as template:
        template_crs = CRS.from_wkt(template.spatial_ref.attrs["crs_wkt"])
        template_x = np.asarray(template.x.data)
        template_y = np.asarray(template.y.data)
    if template_crs != CRS.from_user_input(GRID_CRS):
        raise ValueError(
            f"expected NISAR analysis CRS {GRID_CRS}, found {template_crs}"
        )
    for path in paths[1:]:
        with xr.open_dataset(path, engine="h5netcdf") as current:
            current_crs = CRS.from_wkt(current.spatial_ref.attrs["crs_wkt"])
            if (
                current_crs != template_crs
                or not np.array_equal(current.x.data, template_x)
                or not np.array_equal(current.y.data, template_y)
            ):
                raise ValueError(f"NISAR pair is not on the common grid: {path}")
    return template_path


def _prepare_aso_on_nisar_grid(
    aso_inventory: Path,
    aso_root: Path | None,
    template_path: Path,
    output_dir: Path,
) -> list[dict[str, Any]]:
    """Area-average source ASO SWE rasters onto the common NISAR grid."""
    with xr.open_dataset(template_path, engine="h5netcdf") as template:
        x = np.asarray(template.x.data, dtype=float)
        y = np.asarray(template.y.data, dtype=float)
        spatial_ref = template.spatial_ref.attrs
        target_crs = CRS.from_wkt(spatial_ref["crs_wkt"])
    dx, dy = float(np.median(np.diff(x))), float(np.median(np.diff(y)))
    if not np.isclose(abs(dx), 80.0) or not np.isclose(abs(dy), 80.0):
        raise ValueError("ASO target must be the delivered 80 m NISAR grid")
    target_transform = Affine(dx, 0.0, x[0] - dx / 2.0, 0.0, dy, y[0] - dy / 2.0)
    target_shape = (y.size, x.size)
    target_epsg = target_crs.to_epsg()
    if target_epsg is None:
        raise ValueError("NISAR target CRS does not resolve to an EPSG code")
    products: list[dict[str, Any]] = []
    rows = [
        row for row in _read_csv(aso_inventory) if row["asset_role"] == "swe_raster"
    ]
    for row in rows:
        if row["units"] != "m":
            raise ValueError(
                f"ASO SWE units are not verified as metres: {row['relative_path']}"
            )
        package = Path(row["source_package_dir"])
        source_path = (
            aso_root / package.name / row["relative_path"]
            if aso_root is not None
            else package / row["relative_path"]
        )
        if not source_path.is_file():
            continue
        with rasterio.open(source_path) as source:
            if source.crs is None:
                raise ValueError(f"ASO raster has no CRS: {source_path}")
            source_m = source.read(1, masked=True).filled(np.nan).astype("float32")
            source_metadata = {
                "crs": str(source.crs),
                "transform": list(source.transform),
                "shape": list(source.shape),
                "nodata": (
                    float(source.nodata)
                    if source.nodata is not None and np.isfinite(source.nodata)
                    else None
                ),
                "resolution": list(source.res),
            }
            values_m = np.full(target_shape, np.nan, dtype="float32")
            reproject(
                source=source_m,
                destination=values_m,
                src_transform=source.transform,
                src_crs=source.crs,
                src_nodata=np.nan,
                dst_transform=target_transform,
                dst_crs=target_crs,
                dst_nodata=np.nan,
                resampling=Resampling.average,
            )
        values_mm = values_m * np.float32(1000.0)
        destination = (
            output_dir
            / "aso_on_nisar_grid"
            / f"{source_path.stem}_epsg{target_epsg}_80m_mm.tif"
        )
        destination.parent.mkdir(parents=True, exist_ok=True)
        profile = {
            "driver": "GTiff",
            "height": target_shape[0],
            "width": target_shape[1],
            "count": 1,
            "dtype": "float32",
            "crs": target_crs,
            "transform": target_transform,
            "nodata": np.nan,
            "compress": "deflate",
            "predictor": 3,
        }
        with rasterio.open(destination, "w", **profile) as output:
            output.write(values_mm, 1)
            output.update_tags(
                source_path=str(source_path),
                source_sha256=_sha256(source_path),
                source_units="m SWE",
                output_units="mm SWE",
                source_crs=source_metadata["crs"],
                source_transform=json.dumps(source_metadata["transform"]),
                source_shape=json.dumps(source_metadata["shape"]),
                target_grid="NISAR delivered common 80 m grid",
                target_crs=target_crs.to_string(),
                target_transform=json.dumps(list(target_transform)),
                target_shape=json.dumps(target_shape),
                resampling="rasterio average (area-weighted continuous SWE)",
            )
        with rasterio.open(destination) as check:
            if (
                check.shape != target_shape
                or check.crs != target_crs
                or check.transform != target_transform
            ):
                raise ValueError(f"ASO output grid verification failed: {destination}")
        products.append(
            {
                "survey_start": row["survey_start"],
                "survey_end": row["survey_end"],
                "provider_product_version": row["provider_product_version"],
                "source_path": str(source_path),
                "source_sha256": _sha256(source_path),
                "source_metadata": source_metadata,
                "target_path": str(destination),
                "target_epsg": target_epsg,
                "target_crs": target_crs.to_string(),
                "target_transform": list(target_transform),
                "target_shape": list(target_shape),
                "target_resolution_m": [abs(dx), abs(dy)],
                "resampling": "rasterio average (area-weighted continuous SWE)",
                "source_units": "m SWE",
                "target_units": "mm SWE",
                "values_mm": values_mm,
            }
        )
    if len(products) != len(rows):
        raise FileNotFoundError(
            f"Prepared {len(products)} of {len(rows)} inventoried ASO SWE rasters; "
            "check --aso-root and source package availability"
        )
    return products


def _render_figures(
    output_dir: Path,
    frame_pairs: dict[str, list[Path]],
    edge_rows: list[dict[str, Any]],
    cumulative_rows: list[dict[str, Any]],
    segments: list[dict[str, Any]],
    station_rows: list[dict[str, Any]],
    station_daily: dict[str, dict[str, dict[str, str]]],
    viirs_display: dict[str, tuple[np.ndarray, np.ndarray, xr.Dataset, str]],
    boundary_geo: Any,
    boundary_projected: Any,
    aso_products: list[dict[str, Any]],
) -> list[str]:
    matplotlib.rcParams.update(
        {"font.size": 9, "axes.titlesize": 10, "figure.titlesize": 13}
    )
    figure_dir = output_dir / "figures"
    figure_dir.mkdir(parents=True, exist_ok=True)
    to_grid = Transformer.from_crs("EPSG:4326", GRID_CRS, always_xy=True)
    station_xy = {
        row["station_id"]: to_grid.transform(float(row["lon"]), float(row["lat"]))
        for row in station_rows
    }
    written: list[str] = []

    # Figure 1: basin, CDEC network, and the full available station record.
    fig, axes = plt.subplots(
        1, 2, figsize=(12, 5.4), gridspec_kw={"width_ratios": [1, 1.4]}
    )
    ax = axes[0]
    _projected_polygon(ax, boundary_projected, linewidth=1.4)
    colors = plt.get_cmap("tab10")
    station_label_offsets = {"DAN": (5, -11), "TES": (5, 7)}
    for index, row in enumerate(station_rows):
        sx, sy = station_xy[row["station_id"]]
        ax.scatter(
            sx,
            sy,
            s=26,
            color=colors(index),
            edgecolor="white",
            linewidth=0.5,
            zorder=3,
        )
        ax.annotate(
            row["station_id"],
            (sx, sy),
            xytext=station_label_offsets.get(row["station_id"], (3, 3)),
            textcoords="offset points",
            fontsize=7,
        )
    ax.set_title("Tuolumne basin and CDEC stations")
    ax.set_xlabel("Easting (m), EPSG:32610")
    ax.set_ylabel("Northing (m), EPSG:32610")
    ax.set_aspect("equal")
    ax.grid(alpha=0.2)
    ax = axes[1]
    for index, row in enumerate(station_rows):
        station_id = row["station_id"]
        dates, values = [], []
        for day, record in sorted(station_daily.get(station_id, {}).items()):
            try:
                value = float(record["swe_cm"])
            except (TypeError, ValueError):
                continue
            dates.append(np.datetime64(day))
            values.append(value)
        if dates:
            ax.plot(dates, values, color=colors(index), linewidth=0.9, label=station_id)
    ax.set_title(f"Daily station SWE through {ANALYSIS_END_DATE} (source cm)")
    ax.set_xlabel("Date")
    ax.set_ylabel("CDEC SWE (cm)")
    ax.grid(alpha=0.25)
    ax.legend(ncol=2, fontsize=7)
    fig.suptitle("Tuolumne retrieval baseline: domain and reference observations")
    _save_figure(fig, figure_dir / "fig01_domain_and_station_observations")
    written.append("fig01_domain_and_station_observations")

    # Figure 2: cumulative dSWE by connected temporal segment plus station context.
    fig, axes = plt.subplots(2, 1, figsize=(11, 8), sharex=False)
    for frame in FRAME_NAMES:
        rows = [row for row in cumulative_rows if row["frame"] == frame]
        for seg in sorted({row["segment_number"] for row in rows}):
            series = [row for row in rows if row["segment_number"] == seg]
            times = [np.datetime64(row["secondary_time"][:10]) for row in series]
            median = np.array(
                [row["cumulative_dswe_median_mm"] for row in series], dtype=float
            )
            p25 = np.array(
                [row["cumulative_dswe_p25_mm"] for row in series], dtype=float
            )
            p75 = np.array(
                [row["cumulative_dswe_p75_mm"] for row in series], dtype=float
            )
            label = (
                f"{frame} · segment {seg} "
                f"(start {series[0]['segment_start_time'][:10]})"
            )
            axes[0].plot(
                times, median, marker="o", markersize=3, linewidth=1.2, label=label
            )
            axes[0].fill_between(times, p25, p75, alpha=0.15)
    axes[0].axhline(0.0, color="black", linewidth=0.6)
    axes[0].set_title("Basin pixel distribution of cumulative pairwise ΔSWE")
    axes[0].set_ylabel("Cumulative ΔSWE (mm; segment-relative)")
    axes[0].legend(fontsize=7, ncol=2)
    axes[0].grid(alpha=0.25)
    station_ids = [row["station_id"] for row in station_rows]
    station_dates = sorted({day for series in station_daily.values() for day in series})
    available_dates, available_medians, station_counts = [], [], []
    for day in station_dates:
        values = []
        for station_id in station_ids:
            item = station_daily.get(station_id, {}).get(day)
            try:
                values.append(
                    float(item["swe_cm"]) if item and item["swe_cm"] else np.nan
                )
            except (TypeError, ValueError):
                values.append(np.nan)
        finite = np.asarray(values, dtype=float)
        finite = finite[np.isfinite(finite)]
        if finite.size:
            available_dates.append(np.datetime64(day))
            available_medians.append(float(np.median(finite)))
            station_counts.append(int(finite.size))
    axes[1].plot(available_dates, available_medians, color="black", linewidth=1.2)
    axes[1].fill_between(
        available_dates, 0, available_medians, color="steelblue", alpha=0.16
    )
    axes[1].set_title("Median available station SWE (context; variable station count)")
    axes[1].set_ylabel("Median CDEC SWE (cm)")
    axes[1].set_xlabel(
        "NISAR secondary acquisition date / daily station observation date"
    )
    axes[1].grid(alpha=0.25)
    fig.suptitle(f"Strict path accumulation through {ANALYSIS_END_DATE}")
    _save_figure(fig, figure_dir / "fig02_seasonal_cumulative_dswe")
    written.append("fig02_seasonal_cumulative_dswe")

    # Figure 3: first-edge diagnostic maps, one row per available path.
    first_pairs: dict[str, xr.Dataset] = {}
    for frame in FRAME_NAMES:
        path = sorted(frame_pairs[frame])[0]
        first_pairs[frame] = xr.open_dataset(path, engine="h5netcdf")
    dvals = np.concatenate(
        [
            np.abs(
                np.asarray(ds["dswe"].data, dtype=float)[
                    np.asarray(ds["basin_mask"].data, dtype=bool)
                ]
            )
            * 1000.0
            for ds in first_pairs.values()
        ]
    )
    dvals = dvals[np.isfinite(dvals)]
    dlimit = max(float(np.percentile(dvals, 98)) if dvals.size else 1.0, 1.0)
    fig, axes = plt.subplots(2, 4, figsize=(16, 8.5))
    titles = (
        "Pairwise ΔSWE (mm)",
        "Coherence",
        "Local incidence (degrees)",
        "Connected-component status",
    )
    for row_index, frame in enumerate(FRAME_NAMES):
        ds = first_pairs[frame]
        basin = np.asarray(ds["basin_mask"].data, dtype=bool)
        fields = [
            np.where(basin, np.asarray(ds["dswe"].data, dtype=float) * 1000.0, np.nan),
            np.where(basin, np.asarray(ds["coherence"].data, dtype=float), np.nan),
            np.where(
                basin,
                np.degrees(np.asarray(ds["incidence_angle"].data, dtype=float)),
                np.nan,
            ),
        ]
        components = np.asarray(ds["connected_component"].data)
        fill = ds["connected_component"].attrs.get("_FillValue", 65535)
        component_class = np.where(
            ~np.isfinite(components) | (components == fill),
            2,
            np.where(components > 0, 1, 0),
        ).astype(float)
        fields.append(np.where(basin, component_class, np.nan))
        cmaps = ("RdBu", "viridis", "cividis", "Set2")
        vmins = (-dlimit, 0.0, 0.0, -0.5)
        vmaxs = (dlimit, 1.0, 90.0, 2.5)
        for col_index, ax in enumerate(axes[row_index]):
            image = _imshow(
                ax,
                fields[col_index],
                ds,
                cmap=cmaps[col_index],
                vmin=vmins[col_index],
                vmax=vmaxs[col_index],
            )
            _projected_polygon(ax, boundary_projected, color="black", linewidth=0.6)
            if row_index == 0:
                ax.set_title(titles[col_index])
            ax.set_xticks([])
            ax.set_yticks([])
            if col_index == 0:
                ax.set_ylabel(
                    f"{frame}\n{str(ds.attrs['reference_time'])[:10]} → "
                    f"{str(ds.attrs['secondary_time'])[:10]}"
                )
            colorbar = fig.colorbar(image, ax=ax, fraction=0.045, pad=0.02)
            if col_index == 0:
                colorbar.set_label("Pairwise ΔSWE (mm)")
    fig.suptitle(
        "Pairwise ΔSWE: red negative, blue positive; component labels are not a mask"
    )
    _save_figure(fig, figure_dir / "fig03_pairwise_retrieval_diagnostics")
    written.append("fig03_pairwise_retrieval_diagnostics")
    for ds in first_pairs.values():
        ds.close()

    # Figure 4: latest cumulative segment for each path, kept as dSWE.
    endpoint_records = []
    for frame in FRAME_NAMES:
        frame_rows = [row for row in cumulative_rows if row["frame"] == frame]
        endpoint_records.append(max(frame_rows, key=lambda row: row["secondary_time"]))
    endpoint_data: list[tuple[np.ndarray, np.ndarray, xr.Dataset]] = []
    for record in endpoint_records:
        ds = xr.open_dataset(
            ROOT / record["cumulative_dswe_path"], engine="h5netcdf"
        ).load()
        values = np.asarray(ds["cumulative_dswe_mm"].data, dtype=float)
        valid = np.asarray(ds["basin_mask"].data, dtype=bool) & np.isfinite(values)
        endpoint_data.append((values, valid, ds))
    endpoint_values = np.concatenate(
        [np.abs(arr[mask]) for arr, mask, _ in endpoint_data if mask.any()]
    )
    endpoint_limit = max(float(np.percentile(endpoint_values, 98)), 1.0)
    fig, axes = plt.subplots(1, 2, figsize=(12, 5.5))
    for ax, record, (values, valid, ds) in zip(
        axes, endpoint_records, endpoint_data, strict=True
    ):
        image = _imshow(
            ax,
            np.where(valid, values, np.nan),
            ds,
            cmap="RdBu",
            vmin=-endpoint_limit,
            vmax=endpoint_limit,
        )
        _projected_polygon(ax, boundary_projected, linewidth=0.8)
        ax.set_title(
            f"{record['frame']} · endpoint {record['secondary_time'][:10]}\n"
            f"segment begins {record['segment_start_time'][:10]}"
        )
        ax.set_xticks([])
        ax.set_yticks([])
        fig.colorbar(
            image,
            ax=ax,
            label="Cumulative ΔSWE (mm)",
        )
    fig.suptitle(
        "Latest connected segment per frame; red negative, blue positive; "
        "not absolute SWE"
    )
    _save_figure(fig, figure_dir / "fig04_latest_cumulative_dswe_maps")
    written.append("fig04_latest_cumulative_dswe_maps")
    for _, _, ds in endpoint_data:
        ds.close()

    # Figure 5: continuous VIIRS fSCA and two explicitly separate downstream masks.
    if len(viirs_display) == 2:
        fig, axes = plt.subplots(2, 3, figsize=(13, 8))
        mask_cmap = ListedColormap(("#d9d9d9", "#2b83ba", "#737373"))
        mask_norm = BoundaryNorm((-0.5, 0.5, 1.5, 2.5), mask_cmap.N)
        titles = (
            "VIIRS fSCA (bilinear to NISAR grid)",
            "Downstream mask: fSCA > 0",
            "Sensitivity: fSCA ≥ 0.50",
        )
        for row_index, frame in enumerate(FRAME_NAMES):
            fsca, basin, template, viirs_date = viirs_display[frame]
            valid = basin & np.isfinite(fsca)
            fields = [
                np.where(basin, fsca, np.nan),
                np.where(valid, (fsca > 0.0).astype(float), np.nan),
                np.where(valid, (fsca >= VIIRS_THRESHOLD).astype(float), np.nan),
            ]
            for col_index, ax in enumerate(axes[row_index]):
                if col_index == 0:
                    image = _imshow(
                        ax,
                        fields[col_index],
                        template,
                        cmap="viridis",
                        vmin=0.0,
                        vmax=1.0,
                    )
                else:
                    image = _imshow(
                        ax,
                        np.where(basin, np.where(valid, fields[col_index], 2), np.nan),
                        template,
                        cmap=mask_cmap,
                        norm=mask_norm,
                    )
                _projected_polygon(ax, boundary_projected, linewidth=0.6)
                if row_index == 0:
                    ax.set_title(titles[col_index])
                ax.set_xticks([])
                ax.set_yticks([])
                if col_index == 0:
                    ax.set_ylabel(f"{frame}\nVIIRS {viirs_date}")
                if col_index == 0:
                    fig.colorbar(image, ax=ax, fraction=0.045, pad=0.02)
            template.close()
        fig.legend(
            handles=[
                Patch(facecolor="#d9d9d9", label="Threshold not met"),
                Patch(facecolor="#2b83ba", label="Included by mask"),
                Patch(facecolor="#737373", label="No valid fSCA"),
            ],
            loc="lower center",
            ncol=3,
            fontsize=8,
            frameon=False,
        )
        fig.subplots_adjust(bottom=0.13)
        fig.suptitle(
            "VJ110A1F on the NISAR endpoint nearest ASO April 6; "
            "evaluation masks, not retrieval filters"
        )
        _save_figure(fig, figure_dir / "fig05_viirs_fsca_and_mask_sensitivity")
        written.append("fig05_viirs_fsca_and_mask_sensitivity")

    # Figure 6: per-edge local-incidence distribution in the basin.
    fig, ax = plt.subplots(figsize=(11, 4.8))
    for frame in FRAME_NAMES:
        rows = sorted(
            (row for row in edge_rows if row["frame"] == frame),
            key=lambda row: row["secondary_time"],
        )
        dates = [np.datetime64(row["secondary_time"][:10]) for row in rows]
        med = [row["local_incidence_median_deg"] for row in rows]
        p10 = [row["local_incidence_p10_deg"] for row in rows]
        p90 = [row["local_incidence_p90_deg"] for row in rows]
        ax.plot(dates, med, marker=".", linewidth=1.0, label=frame)
        ax.fill_between(dates, p10, p90, alpha=0.15)
    ax.set_title("SnowIn local incidence derived from each GUNW LOS and COP30 DEM")
    ax.set_ylabel("Incidence angle (degrees; basin median and 10th–90th percentiles)")
    ax.set_xlabel("Secondary acquisition date")
    ax.grid(alpha=0.25)
    ax.legend()
    _save_figure(fig, figure_dir / "fig06_local_incidence_by_pair")
    written.append("fig06_local_incidence_by_pair")

    # Figure 7: residuals used for per-pair unweighted median station reference.
    fig, axes = plt.subplots(
        2,
        1,
        figsize=(13.5, 8),
        sharex=True,
        gridspec_kw={"height_ratios": [2.3, 1]},
    )
    fig.subplots_adjust(right=0.77)
    station_colors = {
        row["station_id"]: colors(i) for i, row in enumerate(station_rows)
    }
    for frame in FRAME_NAMES:
        rows = [row for row in edge_rows if row["frame"] == frame]
        rows.sort(key=lambda row: row["secondary_time"])
        dates = [np.datetime64(row["secondary_time"][:10]) for row in rows]
        medians = [row["reference_offset_rad"] for row in rows]
        counts = [row["eligible_station_count"] for row in rows]
        axes[0].plot(
            dates,
            medians,
            marker="o",
            markersize=2.5,
            linewidth=1.0,
            label=f"{frame} median offset",
        )
        axes[1].plot(
            dates, counts, marker="o", markersize=2.5, linewidth=0.9, label=frame
        )
    # Station residual dots are reconstructed from the pair manifests written below.
    reference_rows_all = []
    for frame in FRAME_NAMES:
        for path in frame_pairs[frame]:
            with xr.open_dataset(path, engine="h5netcdf") as pair:
                reference_rows_all.extend(
                    json.loads(pair.attrs.get("station_reference_rows_json", "[]"))
                )
    for station_id, color in station_colors.items():
        observations = [
            row
            for row in reference_rows_all
            if row["station_id"] == station_id and row["eligible"]
        ]
        if observations:
            axes[0].scatter(
                [np.datetime64(row["secondary_date"]) for row in observations],
                [row["residual_rad"] for row in observations],
                s=9,
                color=color,
                alpha=0.55,
                label=f"{station_id} residual",
            )
    axes[0].set_ylabel("Station phase residual / median offset (rad)")
    axes[0].set_title(
        "Equal-weight station residuals and per-edge median phase reference"
    )
    axes[0].grid(alpha=0.25)
    axes[0].legend(
        fontsize=6,
        loc="center left",
        bbox_to_anchor=(1.01, 0.5),
        borderaxespad=0,
    )
    axes[1].set_ylabel("Eligible stations")
    axes[1].set_xlabel("Secondary acquisition date")
    axes[1].set_ylim(bottom=0)
    axes[1].grid(alpha=0.25)
    _save_figure(fig, figure_dir / "fig07_station_phase_reference_diagnostics")
    written.append("fig07_station_phase_reference_diagnostics")

    # Figure 8: ASO SWE on the exact common 80 m NISAR grid.
    if aso_products:
        fig, axes = plt.subplots(
            1,
            len(aso_products),
            figsize=(16.5, 5.4),
            sharex=True,
            sharey=True,
        )
        if len(aso_products) == 1:
            axes = [axes]
        aso_maxes = [
            float(np.nanmax(product["values_mm"]))
            for product in aso_products
            if np.isfinite(product["values_mm"]).any()
        ]
        if not aso_maxes:
            raise ValueError("ASO target grids contain no finite SWE values")
        aso_max = max(aso_maxes)
        template_path = next(path for paths in frame_pairs.values() for path in paths)
        coordinate_formatter = FuncFormatter(lambda value, _: f"{value / 1000:.0f}")
        with xr.open_dataset(template_path, engine="h5netcdf") as template:
            x, y = np.asarray(template.x.data), np.asarray(template.y.data)
            xmin, xmax, ymin, ymax = _extent(x, y)
            for index, (ax, product) in enumerate(zip(axes, aso_products, strict=True)):
                image = _imshow(
                    ax,
                    product["values_mm"],
                    template,
                    cmap="viridis",
                    vmin=0.0,
                    vmax=aso_max,
                )
                _projected_polygon(ax, boundary_projected, linewidth=0.7)
                ax.set_title(
                    f"ASO SWE · {product['survey_start']}–{product['survey_end']}\n"
                    f"{product['provider_product_version']}"
                )
                ax.set_xticks(np.linspace(xmin, xmax, 4))
                ax.set_yticks(np.linspace(ymin, ymax, 4))
                ax.xaxis.set_major_formatter(coordinate_formatter)
                ax.yaxis.set_major_formatter(coordinate_formatter)
                ax.tick_params(labelsize=7)
                ax.set_xlabel("Easting (km)")
                if index == 0:
                    ax.set_ylabel("Northing (km)")
                else:
                    ax.set_yticklabels([])
        fig.subplots_adjust(left=0.07, right=0.89, bottom=0.15, top=0.82, wspace=0.08)
        fig.colorbar(image, ax=axes, label="SWE (mm)", shrink=0.83, pad=0.025)
        fig.suptitle(
            "ASO SWE area-averaged to the common 80 m NISAR grid (EPSG:32610); "
            "separate from cumulative NISAR ΔSWE"
        )
        _save_figure(fig, figure_dir / "fig08_aso_swe_source_context")
        written.append("fig08_aso_swe_source_context")
    return written


def _render_reference_method_figure(
    output_dir: Path,
    edge_rows: list[dict[str, Any]],
    station_rows: list[dict[str, Any]],
    stations: list[dict[str, str]],
) -> str:
    """Plot method offsets, pairwise dSWE shifts, and station residuals."""
    figure_dir = output_dir / "figures"
    figure_dir.mkdir(parents=True, exist_ok=True)
    fig, axes = plt.subplots(3, 2, figsize=(15, 12))
    for column, frame in enumerate(FRAME_NAMES):
        frame_edges = sorted(
            (row for row in edge_rows if row["frame"] == frame),
            key=lambda row: row["secondary_time"],
        )
        for method in REFERENCE_METHODS:
            rows = [row for row in frame_edges if row["reference_method"] == method]
            dates = [np.datetime64(row["secondary_time"][:10]) for row in rows]
            color = REFERENCE_METHOD_COLORS[method]
            axes[0, column].plot(
                dates,
                [row["reference_offset_rad"] for row in rows],
                marker="o",
                markersize=2.5,
                linewidth=1.0,
                color=color,
                label=REFERENCE_METHOD_LABELS[method],
            )
            axes[1, column].plot(
                dates,
                [row["median_dswe_shift_from_median_mm"] for row in rows],
                marker="o",
                markersize=2.5,
                linewidth=1.0,
                color=color,
                label=REFERENCE_METHOD_LABELS[method],
            )

        axes[0, column].set_title(f"{frame} · phase reference offset by pair")
        axes[0, column].set_ylabel("Reference offset (rad)")
        axes[0, column].grid(alpha=0.25)
        axes[1, column].axhline(0.0, color="black", linewidth=0.6)
        axes[1, column].set_title(f"{frame} · basin median dSWE shift from median")
        axes[1, column].set_ylabel("Median pairwise dSWE shift (mm)")
        axes[1, column].set_xlabel("Secondary acquisition date")
        axes[1, column].grid(alpha=0.25)

        frame_station_rows = [
            row for row in station_rows if row["frame"] == frame and row["eligible"]
        ]
        station_ids = [row["station_id"] for row in stations]
        box_values: list[list[float]] = []
        box_positions: list[float] = []
        box_methods: list[str] = []
        for station_index, station_id in enumerate(station_ids):
            for method_index, method in enumerate(REFERENCE_METHODS):
                values = [
                    float(row[f"station_residual_after_{method}_mm"])
                    for row in frame_station_rows
                    if row["station_id"] == station_id
                    and np.isfinite(row[f"station_residual_after_{method}_mm"])
                ]
                if values:
                    box_values.append(values)
                    box_positions.append(
                        station_index
                        + (method_index - (len(REFERENCE_METHODS) - 1) / 2) * 0.18
                    )
                    box_methods.append(method)
        if box_values:
            boxes = axes[2, column].boxplot(
                box_values,
                positions=box_positions,
                widths=0.15,
                patch_artist=True,
                showfliers=False,
                manage_ticks=False,
                medianprops={"color": "black", "linewidth": 0.7},
                whiskerprops={"linewidth": 0.7},
                capprops={"linewidth": 0.7},
            )
            for box, method in zip(boxes["boxes"], box_methods, strict=True):
                box.set_facecolor(REFERENCE_METHOD_COLORS[method])
                box.set_alpha(0.55)
                box.set_edgecolor(REFERENCE_METHOD_COLORS[method])
        axes[2, column].axhline(0.0, color="black", linewidth=0.6)
        axes[2, column].set_title(f"{frame} · station residual after reference")
        axes[2, column].set_ylabel("SWE-equivalent residual (mm)")
        axes[2, column].set_xticks(range(len(station_ids)), labels=station_ids)
        axes[2, column].set_xlim(-0.5, len(station_ids) - 0.5)
        axes[2, column].grid(axis="y", alpha=0.25)
        axes[2, column].set_xlabel("CDEC station")

    legend_handles = [
        Patch(
            facecolor=REFERENCE_METHOD_COLORS[method],
            alpha=0.65,
            label=REFERENCE_METHOD_LABELS[method],
        )
        for method in REFERENCE_METHODS
    ]
    fig.legend(
        handles=legend_handles,
        loc="upper center",
        ncol=4,
        frameon=False,
        bbox_to_anchor=(0.5, 0.965),
    )
    fig.suptitle(f"Phase reference sensitivity through {ANALYSIS_END_DATE}", y=0.995)
    fig.subplots_adjust(top=0.91, bottom=0.07, hspace=0.42, wspace=0.19)
    name = "fig09_phase_reference_method_comparison"
    _save_figure(fig, figure_dir / name)
    return name


def _render_reference_method_endpoint_maps(
    output_dir: Path,
    cumulative_rows: list[dict[str, Any]],
    boundary_projected: Any,
) -> str:
    """Render common-scale endpoint maps for both frames and all methods."""
    endpoint_records = []
    for frame in FRAME_NAMES:
        for method in REFERENCE_METHODS:
            candidates = [
                row
                for row in cumulative_rows
                if row["frame"] == frame and row["reference_method"] == method
            ]
            endpoint_records.append(
                max(candidates, key=lambda row: row["secondary_time"])
            )

    endpoint_data: dict[tuple[str, str], tuple[np.ndarray, np.ndarray, xr.Dataset]] = {}
    for record in endpoint_records:
        with xr.open_dataset(
            record["cumulative_raster_path"], engine="h5netcdf"
        ) as opened:
            ds = opened.load()
        values = np.asarray(ds["cumulative_dswe_mm"].data, dtype=float)
        valid = np.asarray(ds["basin_mask"].data, dtype=bool) & np.isfinite(values)
        endpoint_data[(record["frame"], record["reference_method"])] = (
            values,
            valid,
            ds,
        )

    magnitudes = np.concatenate(
        [
            np.abs(values[valid])
            for values, valid, _ in endpoint_data.values()
            if valid.any()
        ]
    )
    limit = max(float(np.percentile(magnitudes, 98)), 1.0)
    fig, axes = plt.subplots(2, 4, figsize=(16, 8.5), sharex=True, sharey=True)
    image = None
    for row_index, frame in enumerate(FRAME_NAMES):
        for column_index, method in enumerate(REFERENCE_METHODS):
            record = next(
                row
                for row in endpoint_records
                if row["frame"] == frame and row["reference_method"] == method
            )
            values, valid, ds = endpoint_data[(frame, method)]
            ax = axes[row_index, column_index]
            image = _imshow(
                ax,
                np.where(valid, values, np.nan),
                ds,
                cmap="RdBu",
                vmin=-limit,
                vmax=limit,
            )
            _projected_polygon(ax, boundary_projected, linewidth=0.55)
            ax.set_title(
                f"{REFERENCE_METHOD_LABELS[method]}\n"
                f"endpoint {record['secondary_time'][:10]}"
            )
            ax.set_xticks([])
            ax.set_yticks([])
            if column_index == 0:
                ax.set_ylabel(frame)

    assert image is not None
    fig.suptitle(
        "June 1 cutoff · red negative, blue positive · "
        "segment-relative cumulative ΔSWE",
        y=0.98,
    )
    fig.subplots_adjust(
        left=0.04, right=0.87, top=0.86, bottom=0.06, wspace=0.08, hspace=0.3
    )
    colorbar_axis = fig.add_axes([0.90, 0.18, 0.018, 0.64])
    fig.colorbar(image, cax=colorbar_axis, label="Cumulative ΔSWE (mm)")
    name = "fig10_reference_method_endpoint_maps"
    _save_figure(fig, output_dir / "figures" / name)
    for _, _, ds in endpoint_data.values():
        ds.close()
    return name


def _prune_unselected_outputs(
    output_dir: Path,
    frames: list[str],
    pair_paths: dict[str, list[Path]],
    cumulative_rows: list[dict[str, Any]],
    reference_method_rows: list[dict[str, Any]],
    cumulative_method_rows: list[dict[str, Any]],
) -> None:
    """Remove stale generated pair and cumulative files outside this run."""
    for frame in frames:
        selected_pairs = {path.resolve() for path in pair_paths[frame]}
        pair_dir = output_dir / "pairs" / frame
        if pair_dir.is_dir():
            for path in pair_dir.glob("*.nc"):
                if path.resolve() not in selected_pairs:
                    path.unlink()

        selected_cumulative = {
            Path(row["cumulative_dswe_path"]).resolve()
            for row in cumulative_rows
            if row["frame"] == frame
        }
        cumulative_dir = output_dir / "cumulative" / frame
        if cumulative_dir.is_dir():
            for path in cumulative_dir.rglob("*.nc"):
                if path.resolve() not in selected_cumulative:
                    path.unlink()

        for method in REFERENCE_METHODS:
            method_pair_paths = {
                Path(row["pairwise_raster_path"]).resolve()
                for row in reference_method_rows
                if row["frame"] == frame and row["reference_method"] == method
            }
            method_pair_dir = (
                output_dir / "reference_sensitivity" / "pairs" / method / frame
            )
            if method_pair_dir.is_dir():
                for path in method_pair_dir.glob("*.nc"):
                    if path.resolve() not in method_pair_paths:
                        path.unlink()

            method_cumulative_paths = {
                Path(row["cumulative_raster_path"]).resolve()
                for row in cumulative_method_rows
                if row["frame"] == frame and row["reference_method"] == method
            }
            method_cumulative_dir = (
                output_dir / "reference_sensitivity" / "cumulative" / method / frame
            )
            if method_cumulative_dir.is_dir():
                for path in method_cumulative_dir.rglob("*.nc"):
                    if path.resolve() not in method_cumulative_paths:
                        path.unlink()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--gunw-root",
        type=Path,
        required=True,
        help="Directory containing T042_F069/ and T034_F021/ GUNW files",
    )
    parser.add_argument("--dem", type=Path, default=DEFAULT_DEM)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--frames", nargs="+", choices=FRAME_NAMES, default=list(FRAME_NAMES)
    )
    parser.add_argument(
        "--aso-root",
        type=Path,
        help=(
            "Optional root containing the package directories listed in the inventory"
        ),
    )
    parser.add_argument(
        "--force", action="store_true", help="Recompute existing pair products"
    )
    args = parser.parse_args()

    gunw_root = args.gunw_root.expanduser().resolve()
    dem_path = args.dem.expanduser().resolve()
    output_dir = args.output_dir.expanduser().resolve()
    if not dem_path.is_file():
        raise FileNotFoundError(f"NISAR COP30 DEM is missing: {dem_path}")
    if not STATION_DAILY.is_file():
        raise FileNotFoundError(f"CDEC daily source is missing: {STATION_DAILY}")
    if not VIIRS_MANIFEST.is_file():
        raise FileNotFoundError(f"VIIRS manifest is missing: {VIIRS_MANIFEST}")

    _, boundary_projected = _load_boundary()
    boundary_geo = shape(
        json.loads(BOUNDARY_PATH.read_text(encoding="utf-8"))["features"][0]["geometry"]
    )
    stations, daily = _load_stations()
    catalog = _load_catalog()
    products = _products(gunw_root, catalog, args.frames)
    output_dir.mkdir(parents=True, exist_ok=True)
    edge_rows: list[dict[str, Any]] = []
    station_reference_rows: list[dict[str, Any]] = []
    pair_paths: dict[str, list[Path]] = {}
    for frame in args.frames:
        pair_paths[frame] = []
        for path in products[frame]:
            info = catalog[path.name]
            if path.stat().st_size != info["size_bytes"]:
                raise ValueError(f"local file size disagrees with CMR for {path.name}")
            result, summary, reference_rows = _process_product(
                path,
                frame,
                info,
                dem_path=dem_path,
                stations=stations,
                daily=daily,
                boundary=boundary_projected,
                output_dir=output_dir,
                force=args.force,
            )
            pair_paths[frame].append(result)
            edge_rows.append(summary)
            for row in reference_rows:
                station_reference_rows.append(
                    {"frame": frame, "source_granule_id": path.stem, **row}
                )
    edge_rows.sort(key=lambda row: (row["frame"], row["reference_time"]))
    _write_csv(output_dir / "tables/pairwise_edge_summary.csv", edge_rows)
    _write_csv(output_dir / "tables/station_reference_rows.csv", station_reference_rows)

    reference_method_rows: list[dict[str, Any]] = []
    station_method_rows: list[dict[str, Any]] = []
    for frame, paths in pair_paths.items():
        for pair_path in paths:
            edge_comparison, station_comparison = _reference_method_comparison(
                pair_path, frame, output_dir
            )
            reference_method_rows.extend(edge_comparison)
            station_method_rows.extend(station_comparison)
    reference_method_rows.sort(
        key=lambda row: (
            row["frame"],
            row["reference_time"],
            REFERENCE_METHODS.index(row["reference_method"]),
        )
    )
    station_method_rows.sort(
        key=lambda row: (row["frame"], row["reference_time"], row["station_id"])
    )
    _write_csv(
        output_dir / "tables/reference_method_comparison.csv",
        reference_method_rows,
    )
    _write_csv(
        output_dir / "tables/station_reference_method_comparison.csv",
        station_method_rows,
    )

    cumulative_rows: list[dict[str, Any]] = []
    segments: list[dict[str, Any]] = []
    for frame, paths in pair_paths.items():
        summary, notes = _cumulative_paths(frame, paths, output_dir)
        cumulative_rows.extend(summary)
        segments.extend(notes)
    _write_csv(output_dir / "tables/cumulative_path_summary.csv", cumulative_rows)
    cumulative_method_rows, reference_method_segments = (
        _cumulative_reference_method_paths(
            reference_method_rows,
            cumulative_rows,
            output_dir,
        )
    )
    _write_csv(
        output_dir / "tables/cumulative_reference_method_comparison.csv",
        cumulative_method_rows,
    )
    viirs_summaries, viirs_display = _viirs_products(pair_paths, output_dir)
    common_grid_template = _verify_common_nisar_grid(pair_paths)
    aso_products = _prepare_aso_on_nisar_grid(
        ASO_INVENTORY,
        args.aso_root.expanduser().resolve() if args.aso_root else None,
        common_grid_template,
        output_dir,
    )
    aso_grid_rows = []
    for product in aso_products:
        row = {key: value for key, value in product.items() if key != "values_mm"}
        row["source_metadata"] = json.dumps(row["source_metadata"], sort_keys=True)
        for key in ("target_transform", "target_shape", "target_resolution_m"):
            row[key] = json.dumps(row[key])
        aso_grid_rows.append(row)
    _write_csv(output_dir / "tables/aso_grid_preparation.csv", aso_grid_rows)

    figure_names = _render_figures(
        output_dir,
        pair_paths,
        edge_rows,
        cumulative_rows,
        segments,
        stations,
        daily,
        viirs_display,
        boundary_geo,
        boundary_projected,
        aso_products,
    )
    figure_names.append(
        _render_reference_method_figure(
            output_dir,
            reference_method_rows,
            station_method_rows,
            stations,
        )
    )
    figure_names.append(
        _render_reference_method_endpoint_maps(
            output_dir,
            cumulative_method_rows,
            boundary_projected,
        )
    )
    manifest = {
        "generated_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "frames": args.frames,
        "analysis_end_date_inclusive": ANALYSIS_END_DATE,
        "software": _software_provenance(),
        "inputs": {
            "nisar_inventory": str(NISAR_INVENTORY.relative_to(ROOT)),
            "gunw_root": str(gunw_root),
            "boundary": str(BOUNDARY_PATH.relative_to(ROOT)),
            "station_metadata": str(STATION_METADATA.relative_to(ROOT)),
            "station_daily_csv": str(STATION_DAILY.relative_to(ROOT)),
            "station_daily_sha256": _sha256(STATION_DAILY),
            "viirs_manifest": str(VIIRS_MANIFEST.relative_to(ROOT)),
            "viirs_root": str(VIIRS_ROOT.relative_to(ROOT)),
            "dem": str(dem_path),
            "dem_sha256": _sha256(dem_path),
            "aso_inventory": str(ASO_INVENTORY.relative_to(ROOT)),
            "aso_products_on_nisar_grid": [
                {key: value for key, value in product.items() if key != "values_mm"}
                for product in aso_products
            ],
        },
        "conventions": {
            "phase": (
                "SnowIn canonical secondary_minus_reference; GUNW source sign "
                "is normalized by SnowIn"
            ),
            "pairwise_quantity": "dSWE = secondary SWE minus reference SWE",
            "retrieval": (
                "SnowIn Leinss; product wavelength; NISAR COP30 local incidence"
            ),
            "station_reference": (
                "Native 5x5 phase/coherence medians; coherence > 0; exact-date CDEC; "
                "equal-weight median of eligible basin-station residuals"
            ),
            "reference_method_comparison": {
                "median": "equal-weight median of eligible station phase residuals",
                "coherence_weighted_mean": (
                    "sum(coherence × station phase residual) / sum(coherence); "
                    "coherence is the median of the eligible native 5x5 station window"
                ),
                "max_station": "maximum eligible station phase residual",
                "min_station": "minimum eligible station phase residual",
                "support": "same eligible station set for all four methods",
            },
            "support": (
                "Finite phase and valid geometry; no coherence or component mask; "
                "basin polygon masks output dSWE"
            ),
            "temporal_path": (
                "Contiguous segments; segment-specific reference epoch; missing "
                "pixels propagate; gaps are not bridged; pair secondary dates "
                f"are limited through {ANALYSIS_END_DATE}"
            ),
            "corrections": "No GUNW correction layers applied",
            "viirs": (
                "VJ110A1F V002 h08v05; NDSI scale 0.01; fSCA=-0.01+1.45*NDSI; "
                "invalid values missing; bilinear reprojection "
                "before masks >0 and >=0.50"
            ),
            "viirs_mask_role": "Evaluation diagnostic; not applied to retrieval",
            "aso": (
                "Source SWE in metres area-averaged with rasterio Resampling.average "
                "from source grids to the common 80 m NISAR grid; converted to mm; "
                "source rasters preserved; no ASO-total-SWE versus NISAR-cumulative-"
                "dSWE accuracy metrics"
            ),
        },
        "temporal_segments": segments,
        "reference_method_temporal_segments": reference_method_segments,
        "pair_count": len(edge_rows),
        "cumulative_endpoint_count": len(cumulative_rows),
        "reference_method_count": len(REFERENCE_METHODS),
        "reference_method_pair_count": len(reference_method_rows),
        "reference_method_cumulative_endpoint_count": len(cumulative_method_rows),
        "viirs_reprojected_frame_date_count": len(viirs_summaries),
        "figures": figure_names,
        "limitations": [
            (
                "Cumulative NISAR ΔSWE is relative to each segment start, "
                "not absolute SWE"
            ),
            (
                "Analysis stops on 2026-06-01; later T042/F069 and T034/F021 "
                "acquisitions, including the post-gap T042 segment, are excluded"
            ),
            (
                "ASO is prepared on the common grid for spatial context; no "
                "absolute-SWE initialization was selected for comparison to "
                "cumulative dSWE."
            ),
            (
                "Reference-station residuals calibrate retrievals; they are not "
                "independent validation"
            ),
            "Spatial pixels are dependent; summaries are descriptive.",
        ],
    }
    (output_dir / "run_manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    _prune_unselected_outputs(
        output_dir,
        args.frames,
        pair_paths,
        cumulative_rows,
        reference_method_rows,
        cumulative_method_rows,
    )
    print(
        f"Pair products: {len(edge_rows)}; figures: {len(figure_names)}; "
        f"output: {output_dir}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
