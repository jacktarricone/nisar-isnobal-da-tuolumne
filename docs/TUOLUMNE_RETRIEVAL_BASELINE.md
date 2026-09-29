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

The full primary-frame inventory contains 48 PROVISIONAL pairs: descending
T042/F069 and ascending T034/F021. Analysis is limited to pairs whose secondary
acquisition date is on or before 2026-06-01, inclusive. This selects 16 T042/F069
pairs and 15 T034/F021 pairs; the later T042/F069 segment is excluded. Station
context is clipped to the same date. SnowIn normalizes the GUNW phase, reads the
product wavelength, calculates local incidence with the same-product NISAR COP30
DEM, and computes pairwise dSWE. For each included edge, the reference is the
unweighted median of eligible in-basin station residuals. Station phase and
coherence are sampled as separate medians over the native 5 × 5 pixel window;
finite phase and coherence greater than zero are required. CDEC SWE must be
present on both exact acquisition dates. The basin polygon limits the output
dSWE map; there is no coherence threshold or connected-component mask.

All 48 inventory products were verified to share the exact EPSG:32610 grid at 80 m
spacing (939 × 1657 cells); only the 31 pairs inside the analysis window are
included in the current run. Raster maps respect the NISAR arrays' north-to-south
row order. VIIRS fSCA is bilinearly reprojected to that grid. CDEC stations remain
point observations and their coordinates are transformed to EPSG:32610 for
sampling.

SnowIn accumulates only strictly connected temporal paths. Missing pixel support
propagates, and gaps are not bridged. Through the cutoff, T042/F069 has one
16-edge connected path from 2025-11-01 through 2026-05-24; T034/F021 has one
15-edge connected path from 2025-11-24 through 2026-05-23. The endpoint basin
medians are +80.10 mm for T042/F069 and +8.20 mm for T034/F021. Both are
segment-relative cumulative ΔSWE, not absolute SWE or accuracy estimates. Pairs
after the cutoff, including the later T042/F069 segment, are omitted from the
tables, figures, and generated pair/cumulative files.

## Phase-reference sensitivity comparison

The equal-weight median remains the baseline reference. The run now compares it
with three offsets for each included pair, all using the same eligible station
set and exact-date CDEC residuals:

- **Coherence-weighted mean:** `sum(c_i × r_i) / sum(c_i)`, where `r_i` is the
  station phase residual and `c_i` is the median coherence in that station's
  eligible native 5 × 5 sample. This follows the coherence-weighted GRL–ERB
  reference formulation.
- **Maximum station:** the largest eligible station phase residual.
- **Minimum station:** the smallest eligible station phase residual.

Coherence is a weight for the station calibration estimate; it is not a raster
support threshold. The max/min cases are sensitivity bounds, not candidate
preferred references. `reference_method_comparison.csv` has one row per pair and
method, with the offset, basin dSWE distribution, and dSWE shifts relative to the
median-referenced pair on common support. `station_reference_method_comparison.csv`
has one row per pair and station, with the four shared offsets and that station's
four post-reference residuals in radians and station-sensitivity SWE-equivalent
millimetres. Ineligible station-method residuals remain missing.

The run writes a full pairwise dSWE NetCDF raster for every method and pair under
`reference_sensitivity/pairs/{method}/{frame}/` (124 rasters total). It then
accumulates each method along the same connected temporal paths and writes 124
cumulative rasters under `reference_sensitivity/cumulative/{method}/{frame}/`.
`cumulative_reference_method_comparison.csv` summarizes every cumulative
endpoint. The median pairwise rasters match the baseline rasters exactly; the
comparison recomputes dSWE from the cached normalized phase and geometry grids
for each scalar reference offset.

Figure 9 plots the four offsets by pair, the basin-median pairwise dSWE shift
relative to the median reference, and per-station SWE-equivalent residual
distributions. Figure 10 maps the latest cumulative endpoint for all four
methods and both frames, using a shared signed color scale. The mean of each
pair's basin-pixel mean absolute dSWE shift from the median reference is:

| Frame | Coherence-weighted mean | Maximum station | Minimum station |
| --- | ---: | ---: | ---: |
| T042/F069 | 10.3 mm per pair | 93.9 mm per pair | 61.8 mm per pair |
| T034/F021 | 8.8 mm per pair | 78.5 mm per pair | 70.3 mm per pair |

At the latest cumulative endpoint, the basin median is +80.10 mm for the
median reference, −45.75 mm / +18.23 mm for the coherence-weighted mean,
−1453.55 mm / −1169.31 mm for the maximum station, and +1067.98 mm / +1072.60
mm for the minimum station (T042/F069 / T034/F021). These large max/min shifts
show the sensitivity bounds' scale; they are not plausible snow estimates or
independent validation. This is not a direct ERB-versus-Tuolumne comparison
because the station pool and data differ.

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
phase offsets range from −12.653 to +22.195 rad for T042 and −13.168 to +7.874 rad
for T034. These are descriptive diagnostics; review their variation before
treating the baseline retrieval as scientifically accepted. Spatial pixel
summaries are descriptive because pixels are dependent. Diverging dSWE maps use
red for negative values and blue for positive values.

## Reproduction and outputs

Run `scripts/analysis/tuolumne_retrieval_baseline.py` as shown in the README after
installing the `nisar-m3-da` environment and an accessible SnowIn checkout. The
script applies the 2026-06-01 inclusive cutoff. It expects the tracked CDEC, VIIRS,
and ASO inventories plus local GUNW, DEM, station, VIIRS, and ASO files. The run
manifest records the cutoff, input paths/checksums and processing choices,
Python/package versions, and the SnowIn checkout commit/dirty status. NetCDF
fields, CSV summaries, and ten figure pairs are written beneath the ignored
`data/derived/tuolumne_retrieval_baseline/` directory, including the four-method
pairwise and cumulative rasters; stale post-cutoff pair and cumulative files are
removed from the active output directories.

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
