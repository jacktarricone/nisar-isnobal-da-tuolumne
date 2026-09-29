# Project Charter Progress

**Updated:** 2026-09-29

This status records implementation and evidence available in this checkout. It
does not treat charter hypotheses as findings. See the original [project
charter](PROJECT_CHARTER.md) and [retrieval baseline note](TUOLUMNE_RETRIEVAL_BASELINE.md).

## Implemented or evidenced

| Charter section | Current status |
| --- | --- |
| §§1–6, 15–17, 19, 21, 23–24 | Project purpose, hypotheses, experiment sequence, architecture, and roles remain design contracts. The M3 public-repository review is recorded in §15; no proprietary implementation is inferred. |
| §7 | Three ASO packages are inventoried. Source SWE rasters are preserved; a separate area-average representation is generated on the shared NISAR grid. It is spatial context, not an absolute-SWE validation result. |
| §§8–10 | Separate BETA and PROVISIONAL CMR snapshots, resumable NISAR downloader, and raw GUNW validator are present. The baseline filters the 48-product primary-frame inventory to 31 pairs ending by 2026-06-01 and compares four phase-reference aggregations on common support. Catalog metadata and local validation evidence remain distinct. |
| §11 | A representative saved SnowIn-normalized pair is routed through the project adapter. Support survives the NetCDF 0/1 flag encoding as boolean. DA readiness still fails correctly because uncertainty fields are absent. |
| §18 | The generated external-data manifest covers ASO and NISAR records plus the available CDEC, VIIRS, basin-boundary, and DEM records. The DEM distributor/download provenance is not in local metadata and is explicitly unresolved. |
| §22, deliverables 1–2 | Current NISAR pairs/maturities and per-pair spatial coverage are inventoried. Other first-paper deliverables require model outputs, independent validation, or research choices not yet available. |

The analysis products and figures are written beneath the Git-ignored
`data/derived/tuolumne_retrieval_baseline/`. The full 48-product inventory was
checked against one common EPSG:32610, 80 m grid; the current analysis includes
16 T042/F069 pairs and 15 T034/F021 pairs whose secondary acquisition date is on
or before 2026-06-01. This excludes the later T042/F069 segment. Raster
orientation follows the descending northing coordinates, and the basin raster
mask matches the boundary rasterization on each frame grid. Diverging dSWE maps
encode positive values as blue and negative values as red.
The reference sensitivity output contains four pairwise and cumulative raster
sets (124 rasters of each type), plus pair, station, and cumulative comparison
tables and two figures. It records station residuals and map changes versus the
median reference. The coherence-weighted mean produces much smaller map changes
than the max/min station-residual bounds; the comparison does not select a
preferred method or establish independent retrieval accuracy.

## Remaining research and partner decisions

| Charter section/stage | What remains and why |
| --- | --- |
| §§12–13; Stage 5 (`N1`–`N3`) | Observation-error parameters, spatial aggregation scales, and quality/rejection rules need experiments. The current baseline reports support and descriptive diagnostics only. |
| §14; deliverables 3–10 | No open-loop iSnobal states, controlled updates, restart runs, or forecast forcings are available here. State, free-evolution, and forecast evaluation therefore cannot be reported. |
| §§4, 16, 20; Stage 3 | M3 must resolve restart variables/format, model grid, arbitrary-time state export, forcing availability, SWI definition, model versions, and controlled reruns. Without these, a pointsnobal adapter cannot establish compatibility with production iSnobal restarts. |
| Stages 3–4, 6–7 | No deterministic update or state-reconciliation method is implemented. The charter requires a physically admissible coupled restart state, and choosing one without M3 state semantics and research evidence would invent a scientific method. Ensemble and forecast stages remain downstream. |
| §§7, 12, 14 | Station references calibrate the current retrieval and are not independent validation. The CDEC-derived phase offsets vary substantially by pair; investigate before claiming retrieval acceptance. ASO independence must be protected if it is later used to tune methods. |
| §18 | DEM source-tile names and technical metadata are recorded, but distributor, acquisition record, and redistribution terms were unavailable. Resolve provenance and sharing terms before external release. |
| §19 | Charter responsibilities are proposed; collaborator agreement is not documented. |

## Current interpretation

The baseline is a transferability diagnostic, not a completed scientific
evaluation. It stops at the June 1, 2026 cutoff because later acquisitions have
little measurable snow. Its 80 m grid harmonization fixes the plotting/alignment
error and supports aligned ASO context, but does not resolve the observation-error
model, station-reference variation, absolute-SWE initialization, or model-state
update. No values in this report establish H1–H6.

Next prerequisites are to review the station-reference diagnostics, resolve the
open M3 questions in [M3 Interface](M3_INTERFACE.md), and obtain model/restart and
forcing products before planning any state update. Research choices listed in
[Experiment Design](EXPERIMENT_DESIGN.md) remain open.
