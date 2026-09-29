"""Compare reference-method cumulative dSWE with all Tuolumne ASO surveys.

This adapts the GRL–ERB endpoint evaluation: compare area-averaged ASO total
SWE with cumulative NISAR dSWE on common basin, finite-data, and VIIRS fSCA>0
support. The comparison is descriptive and conditional on near-zero SWE at each
NISAR path start; it is not an absolute-SWE validation.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import subprocess
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import numpy as np
import rasterio
import tuolumne_retrieval_baseline as retrieval
import xarray as xr

ROOT = retrieval.ROOT
DEFAULT_BASELINE_OUTPUT = retrieval.DEFAULT_OUTPUT
DEFAULT_OUTPUT = DEFAULT_BASELINE_OUTPUT / "aso_reference_comparison"
MAX_ENDPOINT_OFFSET_DAYS = 12
COMMON_SUPPORT_RULE = (
    "basin AND finite ASO AND finite cumulative dSWE for all four methods "
    "AND finite VIIRS fSCA > 0"
)
COMPARISON_CAVEAT = (
    "descriptive cross-quantity endpoint comparison; conditional on near-zero "
    "SWE at the NISAR path start; not independent validation"
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _midpoint_day(start: str, end: str) -> date:
    first, last = date.fromisoformat(start), date.fromisoformat(end)
    if last < first:
        raise ValueError(f"ASO survey end precedes start: {start}–{end}")
    return first + timedelta(days=(last - first).days // 2)


def _nearest_record(
    records: list[dict[str, Any]], target: date, field: str
) -> dict[str, Any]:
    return min(
        records,
        key=lambda row: (
            abs((date.fromisoformat(str(row[field])[:10]) - target).days),
            date.fromisoformat(str(row[field])[:10]),
        ),
    )


def _metric_summary(
    aso: np.ndarray,
    nisar: np.ndarray,
    common: np.ndarray,
    basin: np.ndarray,
    pixel_area_m2: float,
) -> dict[str, Any]:
    """Port the GRL–ERB endpoint metrics to the declared shared support."""
    aso_values = np.asarray(aso[common], dtype=float)
    nisar_values = np.asarray(nisar[common], dtype=float)
    difference = nisar_values - aso_values
    count = int(common.sum())
    basin_count = int(basin.sum())
    bias = float(np.mean(difference)) if count else float("nan")
    rmse = float(np.sqrt(np.mean(difference**2))) if count else float("nan")
    if count >= 2 and np.unique(aso_values).size >= 2:
        slope, intercept = np.polyfit(aso_values, nisar_values, 1)
        correlation = float(np.corrcoef(aso_values, nisar_values)[0, 1])
    else:
        slope = intercept = correlation = float("nan")
    return {
        "basin_pixel_count": basin_count,
        "common_support_pixel_count": count,
        "common_support_fraction_of_basin": (
            float(count / basin_count) if basin_count else float("nan")
        ),
        "common_support_area_km2": float(count * pixel_area_m2 / 1e6),
        "aso_mean_mm": float(np.mean(aso_values)) if count else float("nan"),
        "aso_median_mm": float(np.median(aso_values)) if count else float("nan"),
        "aso_sd_mm": float(np.std(aso_values)) if count else float("nan"),
        "aso_iqr_mm": (
            float(np.subtract(*np.percentile(aso_values, [75, 25])))
            if count
            else float("nan")
        ),
        "aso_p05_mm": float(np.percentile(aso_values, 5)) if count else float("nan"),
        "aso_p95_mm": float(np.percentile(aso_values, 95)) if count else float("nan"),
        "nisar_mean_cumulative_dswe_mm": (
            float(np.mean(nisar_values)) if count else float("nan")
        ),
        "bias_nisar_minus_aso_mm": bias,
        "mae_nisar_minus_aso_mm": (
            float(np.mean(np.abs(difference))) if count else float("nan")
        ),
        "rmse_nisar_minus_aso_mm": rmse,
        "ubrmse_nisar_minus_aso_mm": (
            float(np.sqrt(np.mean((difference - bias) ** 2))) if count else float("nan")
        ),
        "nrmse_by_aso_sd": (
            float(rmse / np.std(aso_values))
            if count and np.std(aso_values) > 0
            else float("nan")
        ),
        "median_nisar_minus_aso_mm": (
            float(np.median(difference)) if count else float("nan")
        ),
        "pearson_r": correlation,
        "regression_slope_nisar_on_aso": float(slope),
        "regression_intercept_mm": float(intercept),
        "aso_volume_on_common_support_m3": (
            float(np.sum(aso_values) * pixel_area_m2 / 1000.0)
            if count
            else float("nan")
        ),
        "nisar_cumulative_change_volume_on_common_support_m3": (
            float(np.sum(nisar_values) * pixel_area_m2 / 1000.0)
            if count
            else float("nan")
        ),
    }


def _write_difference_raster(
    path: Path,
    values: np.ndarray,
    profile: dict[str, Any],
    tags: dict[str, str],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    output_profile = profile.copy()
    output_profile.update(
        driver="GTiff",
        count=1,
        dtype="float32",
        nodata=np.nan,
        compress="deflate",
        predictor=3,
    )
    with rasterio.open(path, "w", **output_profile) as destination:
        destination.write(np.asarray(values, dtype="float32"), 1)
        destination.update_tags(**tags)


def _render_metric_figure(
    output_dir: Path,
    rows: list[dict[str, Any]],
    survey_labels: list[tuple[str, str]],
) -> str:
    metrics = (
        ("bias_nisar_minus_aso_mm", "Mean bias (mm)"),
        ("mae_nisar_minus_aso_mm", "MAE (mm)"),
        ("rmse_nisar_minus_aso_mm", "RMSE (mm)"),
    )
    fig, axes = plt.subplots(3, 2, figsize=(13, 10), sharex="col")
    x = np.arange(len(survey_labels))
    for column, frame in enumerate(retrieval.FRAME_NAMES):
        for row_index, (metric, ylabel) in enumerate(metrics):
            ax = axes[row_index, column]
            if row_index == 0:
                ax.set_title(frame)
            for method in retrieval.REFERENCE_METHODS:
                values = []
                for start, end in survey_labels:
                    match = next(
                        row
                        for row in rows
                        if row["frame"] == frame
                        and row["reference_method"] == method
                        and row["aso_survey_start"] == start
                        and row["aso_survey_end"] == end
                    )
                    values.append(float(match[metric]))
                ax.plot(
                    x,
                    values,
                    color=retrieval.REFERENCE_METHOD_COLORS[method],
                    marker="o",
                    linewidth=1.2,
                    markersize=4,
                    label=retrieval.REFERENCE_METHOD_LABELS[method],
                )
            if row_index == 0:
                ax.axhline(0, color="black", linewidth=0.6)
            ax.set_ylabel(ylabel)
            ax.grid(alpha=0.25)
            if row_index == len(metrics) - 1:
                ax.set_xticks(
                    x,
                    [
                        start[5:] if start == end else f"{start[5:]}–{end[5:]}"
                        for start, end in survey_labels
                    ],
                )
                ax.set_xlabel("ASO survey dates")
    handles, labels = axes[0, 0].get_legend_handles_labels()
    fig.legend(
        handles,
        labels,
        loc="upper center",
        ncol=4,
        frameon=False,
        bbox_to_anchor=(0.5, 0.965),
    )
    fig.suptitle(
        "Cumulative NISAR ΔSWE compared with ASO total SWE",
        y=0.995,
    )
    fig.text(
        0.5,
        0.012,
        "Nearest actual NISAR endpoint; no interpolation · "
        "nearest VIIRS fSCA > 0 support · "
        "descriptive, conditional on near-zero SWE at the NISAR path start",
        ha="center",
        fontsize=8,
    )
    fig.subplots_adjust(top=0.91, bottom=0.09, hspace=0.28, wspace=0.2)
    name = "fig11_aso_reference_method_metrics"
    retrieval._save_figure(fig, output_dir / "figures" / name)
    return name


def _render_difference_map(
    output_dir: Path,
    survey: dict[str, Any],
    maps: dict[tuple[str, str], dict[str, Any]],
    boundary_projected: Any,
) -> str:
    magnitudes = np.concatenate(
        [
            np.abs(item["difference"][item["common"]])
            for item in maps.values()
            if item["common"].any()
        ]
    )
    limit = max(float(np.percentile(magnitudes, 98)), 1.0)
    fig, axes = plt.subplots(2, 4, figsize=(16, 8.5), sharex=True, sharey=True)
    image = None
    for row_index, frame in enumerate(retrieval.FRAME_NAMES):
        for column_index, method in enumerate(retrieval.REFERENCE_METHODS):
            item = maps[(frame, method)]
            dataset = item["template"]
            values = np.where(item["common"], item["difference"], np.nan)
            image = retrieval._imshow(
                axes[row_index, column_index],
                values,
                dataset,
                cmap="RdBu",
                vmin=-limit,
                vmax=limit,
            )
            retrieval._projected_polygon(
                axes[row_index, column_index], boundary_projected, linewidth=0.5
            )
            lag = item["endpoint_offset_days"]
            lag_label = f"{lag:+d} d"
            axes[row_index, column_index].set_title(
                f"{retrieval.REFERENCE_METHOD_LABELS[method]}\n"
                f"NISAR {item['endpoint_date'][5:]} · {lag_label}"
            )
            axes[row_index, column_index].set_xticks([])
            axes[row_index, column_index].set_yticks([])
            if column_index == 0:
                axes[row_index, column_index].set_ylabel(frame)
    assert image is not None
    fig.suptitle(
        f"ASO {survey['survey_start']}–{survey['survey_end']} · "
        "NISAR cumulative ΔSWE − ASO total SWE · red negative, blue positive",
        y=0.98,
    )
    fig.subplots_adjust(
        left=0.04, right=0.87, top=0.85, bottom=0.06, wspace=0.08, hspace=0.18
    )
    colorbar_axis = fig.add_axes([0.90, 0.18, 0.018, 0.64])
    fig.colorbar(image, cax=colorbar_axis, label="NISAR ΔSWE − ASO SWE (mm)")
    fig.text(
        0.5,
        0.012,
        f"Common support: basin × finite ASO × finite NISAR × VIIRS fSCA > 0 "
        f"(VIIRS {survey['viirs_support_date']}); shared scale ±{limit:.0f} mm",
        ha="center",
        fontsize=8,
    )
    name = (
        f"fig{survey['figure_number']:02d}_aso_method_difference_"
        f"{survey['survey_start']}"
    )
    retrieval._save_figure(fig, output_dir / "figures" / name)
    return name


def build(baseline_output: Path, output_dir: Path) -> Path:
    baseline_manifest_path = baseline_output / "run_manifest.json"
    cumulative_table_path = (
        baseline_output / "tables" / "cumulative_reference_method_comparison.csv"
    )
    if not baseline_manifest_path.is_file() or not cumulative_table_path.is_file():
        raise FileNotFoundError(
            "run tuolumne_retrieval_baseline.py first to create the four method paths"
        )
    baseline_manifest = json.loads(baseline_manifest_path.read_text())
    if (
        baseline_manifest.get("analysis_end_date_inclusive")
        != retrieval.ANALYSIS_END_DATE
    ):
        raise ValueError(
            "baseline output cutoff does not match the current analysis cutoff"
        )

    cumulative_rows = list(csv.DictReader(cumulative_table_path.open(newline="")))
    aso_products = baseline_manifest["inputs"]["aso_products_on_nisar_grid"]
    if len(aso_products) != 3:
        raise ValueError(
            f"expected all three ASO SWE surveys; found {len(aso_products)}"
        )
    viirs_manifest_path = ROOT / baseline_manifest["inputs"]["viirs_manifest"]
    viirs_root = ROOT / baseline_manifest["inputs"]["viirs_root"]
    viirs_manifest = json.loads(viirs_manifest_path.read_text())
    viirs_files = {
        item["product_date"]: viirs_root / item["filename"]
        for item in viirs_manifest["products"]
    }

    common_grid_pair: dict[str, xr.Dataset] = {}
    for frame in retrieval.FRAME_NAMES:
        pair_candidates = sorted((baseline_output / "pairs" / frame).glob("*.nc"))
        if not pair_candidates:
            raise FileNotFoundError(f"no baseline pair raster for {frame}")
        with xr.open_dataset(pair_candidates[0], engine="h5netcdf") as opened:
            common_grid_pair[frame] = xr.Dataset(
                {"basin_mask": opened["basin_mask"].load()},
                coords={"x": opened.x.load(), "y": opened.y.load()},
            )

    # Cache one nearest-date VIIRS snow support per survey date.
    viirs_cache: dict[str, tuple[np.ndarray, np.ndarray, Path, int]] = {}
    surveys: list[dict[str, Any]] = []
    for survey_index, product in enumerate(
        sorted(aso_products, key=lambda row: row["survey_start"]), start=1
    ):
        target_date = _midpoint_day(product["survey_start"], product["survey_end"])
        viirs_choices = [
            {"product_date": day, "path": path}
            for day, path in viirs_files.items()
            if path.is_file()
        ]
        viirs_record = _nearest_record(viirs_choices, target_date, "product_date")
        viirs_date = str(viirs_record["product_date"])
        viirs_offset_days = (date.fromisoformat(viirs_date) - target_date).days
        if abs(viirs_offset_days) > MAX_ENDPOINT_OFFSET_DAYS:
            raise ValueError(
                f"nearest VIIRS date is too far from ASO survey: {viirs_date}"
            )
        if viirs_date not in viirs_cache:
            fsca, basin = retrieval._reproject_viirs(
                viirs_record["path"], common_grid_pair[retrieval.FRAME_NAMES[0]]
            )
            viirs_cache[viirs_date] = (
                fsca,
                basin,
                viirs_record["path"],
                viirs_offset_days,
            )
        surveys.append(
            {
                **product,
                "survey_midpoint_date": target_date.isoformat(),
                "viirs_support_date": viirs_date,
                "viirs_offset_days": viirs_offset_days,
                "viirs_path": str(viirs_record["path"]),
                "figure_number": survey_index + 11,
            }
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    figures: list[str] = []
    _, boundary_projected = retrieval._load_boundary()
    methods_by_endpoint = {
        (row["frame"], row["reference_method"], row["secondary_time"][:10]): row
        for row in cumulative_rows
    }
    endpoint_dates: dict[str, list[dict[str, Any]]] = {}
    for frame in retrieval.FRAME_NAMES:
        candidates = {
            row["secondary_time"][:10]: row
            for row in cumulative_rows
            if row["frame"] == frame and row["reference_method"] == "median"
        }
        endpoint_dates[frame] = [
            {"endpoint_date": day, "record": row} for day, row in candidates.items()
        ]

    for survey in surveys:
        target_date = date.fromisoformat(survey["survey_midpoint_date"])
        aso_path = Path(survey["target_path"])
        if not aso_path.is_file():
            raise FileNotFoundError(
                f"prepared ASO target raster is missing: {aso_path}"
            )
        with rasterio.open(aso_path) as aso_source:
            aso = aso_source.read(1, masked=True).filled(np.nan).astype("float32")
            raster_profile = aso_source.profile.copy()
            pixel_area_m2 = abs(
                aso_source.transform.a * aso_source.transform.e
                - aso_source.transform.b * aso_source.transform.d
            )
            if aso_source.crs is None or aso_source.crs.to_epsg() != 32610:
                raise ValueError(
                    f"ASO comparison grid CRS is not EPSG:32610: {aso_path}"
                )

        fsca, viirs_basin, viirs_path, _ = viirs_cache[survey["viirs_support_date"]]
        viirs_offset_days = survey["viirs_offset_days"]
        map_data: dict[tuple[str, str], dict[str, Any]] = {}
        for frame in retrieval.FRAME_NAMES:
            selected_endpoint = _nearest_record(
                endpoint_dates[frame], target_date, "endpoint_date"
            )
            endpoint_date = str(selected_endpoint["endpoint_date"])
            endpoint_offset_days = (
                date.fromisoformat(endpoint_date) - target_date
            ).days
            if abs(endpoint_offset_days) > MAX_ENDPOINT_OFFSET_DAYS:
                raise ValueError(
                    "nearest NISAR endpoint exceeds cadence limit: "
                    f"{frame}, {endpoint_date}"
                )

            method_data: dict[str, dict[str, Any]] = {}
            finite_all_methods = np.ones(aso.shape, dtype=bool)
            basin = np.asarray(common_grid_pair[frame]["basin_mask"].data, dtype=bool)
            if basin.shape != aso.shape or viirs_basin.shape != aso.shape:
                raise ValueError("ASO, VIIRS, and NISAR support grids do not match")
            if not np.array_equal(basin, viirs_basin):
                raise ValueError(
                    "VIIRS and ASO templates do not share the basin grid mask"
                )

            for method in retrieval.REFERENCE_METHODS:
                record = methods_by_endpoint.get((frame, method, endpoint_date))
                if record is None:
                    raise ValueError(
                        f"missing {method} cumulative endpoint for "
                        f"{frame} {endpoint_date}"
                    )
                cumulative_path = Path(record["cumulative_raster_path"])
                with xr.open_dataset(cumulative_path, engine="h5netcdf") as opened:
                    cumulative = opened.load()
                try:
                    nisar = np.asarray(
                        cumulative["cumulative_dswe_mm"].data, dtype="float32"
                    )
                    path_support = np.asarray(
                        cumulative["temporal_path_supported"].data, dtype=bool
                    )
                    raster_basin = np.asarray(cumulative["basin_mask"].data, dtype=bool)
                    if nisar.shape != aso.shape or not np.array_equal(
                        raster_basin, basin
                    ):
                        raise ValueError(
                            f"cumulative raster grid/mask mismatch: {cumulative_path}"
                        )
                    finite_all_methods &= path_support & np.isfinite(nisar)
                    method_data[method] = {
                        "nisar": nisar,
                        "record": record,
                        "template": xr.Dataset(
                            coords={"x": cumulative.x.load(), "y": cumulative.y.load()}
                        ),
                    }
                finally:
                    cumulative.close()

            common = (
                basin
                & np.isfinite(aso)
                & np.isfinite(fsca)
                & (fsca > 0.0)
                & finite_all_methods
            )
            if not common.any():
                raise ValueError(
                    "empty shared ASO comparison support for "
                    f"{survey['survey_start']} / {frame}"
                )
            comparison_key = f"{survey['survey_start']}_{survey['survey_end']}"
            support_path = (
                output_dir
                / "support"
                / comparison_key
                / frame
                / "common_viirs_snow_support.tif"
            )
            _write_difference_raster(
                support_path,
                np.where(common, 1.0, np.nan),
                {**raster_profile, "dtype": "float32", "nodata": np.nan},
                {
                    "quantity": "shared ASO and four-method comparison support",
                    "support_rule": (
                        "basin AND finite ASO AND finite all-method cumulative "
                        "dSWE AND finite VIIRS fSCA > 0"
                    ),
                    "aso_survey_start": survey["survey_start"],
                    "aso_survey_end": survey["survey_end"],
                    "viirs_product_date": survey["viirs_support_date"],
                },
            )

            for method in retrieval.REFERENCE_METHODS:
                item = method_data[method]
                nisar = item["nisar"]
                difference = nisar - aso
                masked_difference = np.where(common, difference, np.nan).astype(
                    "float32"
                )
                record = item["record"]
                raster_path = (
                    output_dir
                    / "difference"
                    / comparison_key
                    / method
                    / frame
                    / "nisar_cumulative_minus_aso_swe_mm.tif"
                )
                _write_difference_raster(
                    raster_path,
                    masked_difference,
                    raster_profile,
                    {
                        "quantity": "cumulative NISAR dSWE minus ASO total SWE",
                        "units": "mm",
                        "comparison_interpretation": (
                            "descriptive; cumulative dSWE treated as seasonal SWE "
                            "only under near-zero path-start assumption"
                        ),
                        "reference_method": method,
                        "aso_survey_start": survey["survey_start"],
                        "aso_survey_end": survey["survey_end"],
                        "aso_midpoint_date": survey["survey_midpoint_date"],
                        "nisar_frame": frame,
                        "nisar_reference_epoch": record["segment_start_time"],
                        "nisar_endpoint_time": record["secondary_time"],
                        "nisar_endpoint_offset_from_midpoint_days": str(
                            endpoint_offset_days
                        ),
                        "viirs_product_date": survey["viirs_support_date"],
                        "viirs_fsca_rule": "finite fSCA > 0",
                        "difference_sign": (
                            "NISAR minus ASO; positive means NISAR dSWE exceeds "
                            "ASO total SWE"
                        ),
                        "support_raster": str(support_path),
                    },
                )
                values = _metric_summary(aso, nisar, common, basin, pixel_area_m2)
                rows.append(
                    {
                        "aso_dataset": Path(survey["source_path"]).parent.name,
                        "aso_survey_start": survey["survey_start"],
                        "aso_survey_end": survey["survey_end"],
                        "aso_survey_midpoint_date": survey["survey_midpoint_date"],
                        "aso_source_path": survey["source_path"],
                        "aso_source_sha256": survey["source_sha256"],
                        "aso_target_path": str(aso_path),
                        "aso_resampling": survey["resampling"],
                        "frame": frame,
                        "reference_method": method,
                        "reference_method_label": retrieval.REFERENCE_METHOD_LABELS[
                            method
                        ],
                        "nisar_reference_epoch": record["segment_start_time"],
                        "nisar_endpoint_time": record["secondary_time"],
                        "nisar_endpoint_date": endpoint_date,
                        "nisar_endpoint_offset_from_aso_midpoint_days": (
                            endpoint_offset_days
                        ),
                        "viirs_support_date": survey["viirs_support_date"],
                        "viirs_offset_from_aso_midpoint_days": viirs_offset_days,
                        "viirs_source_path": str(viirs_path),
                        "viirs_source_sha256": _sha256(viirs_path),
                        "viirs_support_rule": "finite VIIRS fSCA > 0",
                        "common_support_rule": COMMON_SUPPORT_RULE,
                        "comparison_sign": "NISAR cumulative dSWE minus ASO total SWE",
                        "interpretation": COMPARISON_CAVEAT,
                        "comparison_raster_path": str(raster_path),
                        "common_support_raster_path": str(support_path),
                        **values,
                    }
                )
                map_data[(frame, method)] = {
                    "difference": difference,
                    "common": common,
                    "template": item["template"],
                    "endpoint_date": endpoint_date,
                    "endpoint_offset_days": endpoint_offset_days,
                }

        figures.append(
            _render_difference_map(
                output_dir,
                survey,
                map_data,
                boundary_projected,
            )
        )

    rows.sort(
        key=lambda row: (
            row["aso_survey_start"],
            retrieval.FRAME_NAMES.index(row["frame"]),
            retrieval.REFERENCE_METHODS.index(row["reference_method"]),
        )
    )
    retrieval._write_csv(
        output_dir / "tables" / "aso_reference_method_comparison.csv", rows
    )
    survey_labels = [
        (survey["survey_start"], survey["survey_end"]) for survey in surveys
    ]
    figures.insert(0, _render_metric_figure(output_dir, rows, survey_labels))

    git_head = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()
    manifest = {
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "git_head": git_head,
        "baseline_manifest_path": str(baseline_manifest_path),
        "baseline_manifest_sha256": _sha256(baseline_manifest_path),
        "method_comparison_table": str(
            output_dir / "tables" / "aso_reference_method_comparison.csv"
        ),
        "comparison_row_count": len(rows),
        "difference_raster_count": len(rows),
        "shared_support_raster_count": len(surveys) * len(retrieval.FRAME_NAMES),
        "figures": figures,
        "methods": list(retrieval.REFERENCE_METHODS),
        "aso_survey_count": len(surveys),
        "frames": list(retrieval.FRAME_NAMES),
        "endpoint_selection": (
            "nearest actual cumulative NISAR secondary date to the floor-calendar "
            "midpoint of each ASO survey; earlier date wins ties; no temporal "
            "interpolation; maximum allowed absolute offset is "
            f"{MAX_ENDPOINT_OFFSET_DAYS} days"
        ),
        "viirs_selection": (
            "nearest available VIIRS product date to each ASO survey midpoint; "
            "earlier date wins ties; "
            "finite fSCA > 0 defines snow support"
        ),
        "aso_resampling": (
            "pre-generated rasterio Resampling.average from verified source "
            "metres to mm on the common 80 m EPSG:32610 grid"
        ),
        "common_support": COMMON_SUPPORT_RULE,
        "metrics": (
            "GRL–ERB endpoint metrics: bias, MAE, RMSE, ubRMSE, normalized "
            "RMSE, median error, Pearson r, regression, coverage, and "
            "descriptive volumes"
        ),
        "quantity_caveat": (
            "ASO is total SWE; NISAR is segment-relative cumulative dSWE. "
            "Comparing them as seasonal SWE requires near-zero SWE at the "
            "segment start. Metrics are descriptive and not independent "
            "validation."
        ),
        "surveys": [
            {
                key: value
                for key, value in survey.items()
                if key not in {"path", "record"}
            }
            for survey in surveys
        ],
    }
    (output_dir / "aso_reference_comparison_manifest.json").write_text(
        json.dumps(manifest, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    return output_dir


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-output", type=Path, default=DEFAULT_BASELINE_OUTPUT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    output = build(
        args.baseline_output.expanduser().resolve(),
        args.output_dir.expanduser().resolve(),
    )
    print(f"ASO comparison rows: 24; output: {output}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
