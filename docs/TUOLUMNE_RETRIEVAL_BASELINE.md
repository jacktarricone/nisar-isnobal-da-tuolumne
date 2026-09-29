# Tuolumne Retrieval Baseline

**Status:** Implemented retrieval diagnostics; not independent validation or data
assimilation. The workflow follows fixed observation conventions in charter §3,
the retrieval and reference scope in §§7 and 10–11, and the staged evaluation in
§22. Its hypotheses remain those in charter §5.

## Fixed conventions and baseline choices

The retrieval uses the directed SnowIn pair convention, `phase = secondary −
reference` and `dSWE = SWE_secondary − SWE_reference`. It keeps pairwise ΔSWE
distinct from absolute SWE, preserves missing support, and does not apply GUNW
correction layers. These are charter conventions, not findings from this run.

The implemented baseline processes the 24 available PROVISIONAL pairs for each
frame (48 total): descending T042/F069 and ascending T034/F021. SnowIn normalizes
the GUNW phase, reads the product wavelength, calculates local incidence with the
same-product NISAR COP30 DEM, and computes pairwise dSWE. For each edge, the
reference is the unweighted median of eligible in-basin station residuals. Station
phase and coherence are sampled as separate medians over the native 5 × 5 pixel
window; finite phase and coherence greater than zero are required. CDEC SWE must
be present on both exact acquisition dates. The basin polygon limits the output
dSWE map; there is no coherence threshold or connected-component mask.

All 48 products were verified to share the exact EPSG:32610 grid at 80 m spacing
(939 × 1657 cells). Raster maps respect the NISAR arrays' north-to-south row order.
VIIRS fSCA is bilinearly reprojected to that grid. CDEC stations remain point
observations and their coordinates are transformed to EPSG:32610 for sampling.

SnowIn accumulates only strictly connected temporal paths. Missing pixel support
propagates, and gaps begin separately anchored segments. The T042/F069 path has
18 edges through 2026-06-17, then a gap before a 6-edge segment from 2026-06-29
through 2026-09-21. T034/F021 has 24 connected edges from 2025-11-24 through
2026-09-20. The endpoint basin medians are +89.60 mm for the latest T042 segment
and −51.87 mm for T034. Both are segment-relative cumulative ΔSWE, not absolute
SWE or accuracy estimates.

Each saved pair is passed through `adapt_snowin_observation`. The adapter maps
the NetCDF-encoded `pairwise_supported` 0/1 flag to a boolean
`observation_support`; binary flag metadata are checked and values outside 0/1
are rejected. `validate_da_observation` still reports the products as incomplete
for DA because pair-common and local uncertainty fields are not available.

## Evaluation context

VJ110A1F V002 h08v05 daily NDSI is scaled by 0.01 and converted with the borrowed
ERB mapping `fSCA = -0.01 + 1.45 × NDSI`, then bilinearly reprojected to the NISAR
grid. The fSCA > 0 mask and fSCA ≥ 0.50 sensitivity mask are evaluation diagnostics
only; neither changes retrieval values. No VIIRS QA filter is applied.

The three ASO SWE sources are retained unchanged. Each verified-metre, 50 m
EPSG:32611 raster is reprojected with Rasterio `Resampling.average` to the exact
common 80 m EPSG:32610 NISAR grid, then converted from metres to millimetres.
This follows the charter's ASO preparation requirements (§7) and the ERB
area-average precedent; source and destination transforms, CRS, shape, units,
resampling, and source checksum are recorded. Derived GeoTIFFs are written under
`data/derived/tuolumne_retrieval_baseline/aso_on_nisar_grid/`. Figure 8 shows
these aligned layers with a shared colour scale. This spatial alignment does not
resolve absolute-SWE initialization: there is no pixelwise accuracy comparison to
cumulative ΔSWE.

The station residuals set the phase reference and therefore are calibration data,
not independent validation. Pairwise coverage is 0.99796–0.99988. Per-edge median
phase offsets range from −20.624 to +27.104 rad for T042 and −13.168 to +7.874 rad
for T034. These are descriptive diagnostics; review their variation before
treating the baseline retrieval as scientifically accepted. Spatial pixel
summaries are descriptive because pixels are dependent.

## Reproduction and outputs

Run `scripts/analysis/tuolumne_retrieval_baseline.py` as shown in the README after
installing the `nisar-m3-da` environment and an accessible SnowIn checkout. It
expects the tracked CDEC, VIIRS, and ASO inventories plus local GUNW, DEM, station,
VIIRS, and ASO files. The run manifest records input paths/checksums and processing
choices, Python/package versions, and the SnowIn checkout commit/dirty status.
NetCDF fields, CSV summaries, and eight figure pairs are written beneath the
ignored `data/derived/tuolumne_retrieval_baseline/` directory.

The local reader adapter bridges an upstream API mismatch: nisar_pytools 0.5.0
returns a DataArray from `get_gunw`, while SnowIn's current `open_gunw` expects a
Dataset. The script passes those arrays through SnowIn's public normalization and
science functions. This compatibility issue should be revisited when either
dependency changes.

## Unresolved decisions

- Absolute-SWE initialization and a defensible ASO comparison.
- Independent validation of the station-referenced retrieval.
- Observation uncertainty, quality thresholds, and spatial aggregation.
- M3 restart format, state reconciliation, forcing availability, and forecast
  replay; resolve these before model-state updates.
- Whether the observed phase-reference offset variation reflects retrieval
  behavior that needs a separate scientific investigation.
