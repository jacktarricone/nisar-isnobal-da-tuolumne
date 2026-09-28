# Data Contracts

**Status:** Requirements derived from the charter. Stage 2 implements only the documented SnowIn observation boundary; it defines no retrieval algorithm.

## Fixed observation conventions

The project consumes SnowIn observation meaning without redefining it (charter §3):

- `phase = phi_secondary - phi_reference`.
- `dSWE = SWE_secondary - SWE_reference`.
- A pair is directed `reference_time -> secondary_time`; pairwise ΔSWE is not absolute SWE.
- Missing pairwise support remains missing and is never interpreted as zero change.
- Phase sign, units, wavelength, CRS, and geometry must be explicit.
- Correction layers must not be silently applied. Distinct support variables must not be collapsed into an undocumented quality mask.
- Resampling or reprojection must be explicit and recorded.

## Data-boundary requirements

Raw GUNW inputs must be validated before SnowIn processing. The charter §10 defines the raw metadata and layer inventory, including granule and processing identity, pair times and orientation, geometry, grid and dimensions, wavelength, phase/coherence/connected-component layers, applicable correction layers, mask/fill convention, checksum, and file size.

The intended processing boundary is raw GUNW → validated input → SnowIn-normalized pair → retrieval/reference/support → project observation. The Tuolumne package consumes already processed SnowIn xarray output and must not interpret raw HDF5 group paths directly. The Stage 2 adapter validates and preserves metadata and values; it does not run retrieval, reference, correction, resampling, or uncertainty calculations. Its operational interface is documented in [SnowIn Observation Adapter](OBSERVATION_ADAPTER.md), derived from charter §11.

The charter's DA observation fields include dSWE uncertainty, pair-common uncertainty, local uncertainty, and observation support. The adapter passes through supplied fields and aliases `pairwise_supported` to `observation_support` without merging support layers. Missing fields remain absent; a dataset missing any required DA field is not DA-ready. No zero, all-valid mask, or uncertainty estimate is synthesized.

ASO rasters must retain their source files and metadata. Units, CRS, nodata, product version, and resampling must be verified and recorded rather than inferred from directory names. An ASO dataset used to tune a methodological choice cannot also be called independent validation of that same choice (charter §7).

## Inventory and provenance

The charter §18 recommends recording provider/product/version, identifier, acquisition times, units, CRS, resolution, expected local path, download method, persistent identifier, study role, independence category, checksum, and notes. Stage 1 records these where source metadata supports them and leaves unsupported values blank. BETA and PROVISIONAL inventories are separate; collection version, product version, CRID, maturity, granule ID, and query timestamp remain explicit (charter §§8–10).

ASO raster units are taken from raster metadata or a report that identifies the exact raster. Package-level unit evidence without an exact file link is recorded as evidence only, not assigned as a raster unit. Spatial inventory and catalog filtering do not establish retrieval suitability, quality thresholds, correction choices, or assimilation use.
