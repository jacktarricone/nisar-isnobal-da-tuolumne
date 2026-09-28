# NISAR–iSnobal Tuolumne Data Assimilation Project Charter

**Version:** 0.3  
**Status:** Initial science, data, and repository design  
**Date:** 2026-09-25  
**Working title:** *Assimilating NISAR InSAR Snow Water Equivalent Change into iSnobal for Basin-Scale Snow Estimation and Forecasting*  
**Project:** NASA Terrestrial Hydrology Program — *NISAR for Global Snow Water Equivalent*  
**Study domain:** Tuolumne River Basin, California  
**Science lead:** Jack Tarricone  
**Modeling partner:** M3 Works  
**Primary upstream snow-InSAR software:** SnowIn  

---

## 1. Project purpose

This project will test whether NISAR L-band InSAR observations of snow water equivalent change (ΔSWE) can improve spatially distributed iSnobal snow-state estimation and forecast-relevant outputs in the Tuolumne River Basin.

The Tuolumne work is intended to complement, not duplicate, the Colorado/East River Basin NISAR first-look effort.

- **Colorado / ERB:** quantify NISAR retrieval performance, uncertainty, spatial support, and failure modes.
- **SnowIn:** provide a tested, reusable, xarray-native scientific layer for NISAR snow-InSAR retrievals, support, referencing, temporal accumulation, and provenance.
- **Tuolumne / iSnobal:** determine how imperfect NISAR ΔSWE observations should be assimilated into a physically based snow model, when they improve a snow analysis or forecast, and when they should instead be rejected or downweighted.

The primary scientific question is:

> **How can NISAR ΔSWE observations be incorporated into a physically based snow model so that they improve basin-scale snow-state estimation and forecast-relevant quantities without injecting retrieval errors into the model?**

The project should produce both a scientific evaluation and a practical **NISAR snow data-assimilation playbook**.

---

## 2. Relationship to the funded THP project

The funded THP proposal uses M3 Works/iSnobal to provide high-accuracy, spatially distributed SWE information for evaluation of L-band InSAR ΔSWE retrievals. The proposal explicitly connects InSAR uncertainty quantification to future assimilation of remotely sensed SWE information into land-surface and snow models.

The Tuolumne assimilation experiment is therefore best treated as a downstream application of the funded retrieval/validation work:

```text
NISAR retrieval
    ↓
retrieval uncertainty / support
    ↓
SnowIn standardized ΔSWE observations
    ↓
iSnobal assimilation experiment
    ↓
analysis and forecast impact
```

The formal THP retrieval and validation deliverables remain distinct from the assimilation experiment. The DA work should use the THP retrieval results rather than redefine them.

---

## 3. Scientific observation contract

### 3.1 NISAR observation

SnowIn will provide directed pairwise observations

\[
y_k(x) =
\Delta SWE_{\mathrm{NISAR}}
(x, t_{k-1}\rightarrow t_k)
\]

with the canonical definition

\[
\Delta SWE = SWE(t_k)-SWE(t_{k-1}).
\]

The corresponding model-equivalent observation is initially

\[
H_k[x] =
SWE_m(x,t_k)-SWE_m(x,t_{k-1}),
\]

and the innovation is

\[
d_k(x)=y_k(x)-H_k[x].
\]

NISAR ΔSWE remains the fundamental observation. The DA system should **not require conversion of NISAR to absolute SWE before assimilation**.

### 3.2 SnowIn conventions inherited by this project

The Tuolumne repository must consume SnowIn outputs without redefining their scientific meaning.

Required conventions include:

- `phase = phi_secondary - phi_reference`
- `dSWE = SWE_secondary - SWE_reference`
- directed edge: `reference_time -> secondary_time`
- pairwise dSWE is not absolute SWE
- missing pairwise support remains missing; it is never interpreted as zero change
- phase sign, units, wavelength, CRS, and geometry must be explicit
- correction layers are never silently applied
- support variables remain distinct rather than being collapsed into one undocumented quality mask
- resampling/reprojection is explicit and recorded

The Tuolumne project owns the observation operator and assimilation logic. SnowIn owns the reusable NISAR phase-to-ΔSWE science and data conventions.

---

## 4. iSnobal model-state contract

iSnobal represents a coupled snow state rather than SWE alone. Relevant state and diagnostic variables include:

- snow specific mass / SWE
- snow depth
- bulk density
- surface-layer temperature
- lower-layer temperature
- mean snow temperature
- cold content
- liquid-water mass and saturation
- layer masses and thicknesses
- melt
- surface water input / runoff from the snowpack

A NISAR ΔSWE innovation therefore does not uniquely specify how the complete model state should change.

### Fundamental DA constraint

> **Every assimilation method must produce a physically admissible iSnobal restart state.**

No method may silently adjust SWE while leaving depth, density, temperature, liquid water, layer structure, or cold content physically inconsistent.

State reconciliation is a scientific sensitivity experiment, not an implementation detail.

---

## 5. Primary hypotheses

### H1 — State-estimation value

Assimilating supported NISAR ΔSWE observations will reduce independently evaluated snow-state error relative to open-loop iSnobal.

### H2 — Observation scale

The most useful assimilation support may be coarser than individual NISAR pixels when retrieval errors contain spatially correlated noise, pair-level reference error, or residual atmospheric effects. Native-pixel assimilation and spatial superobservations will therefore produce measurably different results.

### H3 — Quality-aware assimilation

Assimilation that incorporates NISAR support and observation uncertainty will outperform equal-weight assimilation, especially for pairs affected by low coherence, phase-unwrapping problems, reference uncertainty, wet snow, forest cover, or difficult terrain.

### H4 — State-reconciliation sensitivity

Forecast evolution following assimilation will depend on how a ΔSWE innovation is reconciled with the coupled iSnobal snow state. Physically consistent updates should produce more stable subsequent trajectories than unconstrained SWE-only corrections.

### H5 — Forecast persistence

An improvement on the assimilation date will not necessarily imply an improved forecast. The persistence and decay of DA benefit with forecast lead time will help distinguish state error from forcing and model structural error.

### H6 — Increment assimilation

Assimilating the quantity directly observed by NISAR — pairwise ΔSWE — will be less dependent on absolute-state assumptions than first accumulating the NISAR sequence into an absolute SWE product. This should be tested where a defensible absolute-SWE comparison can be constructed.

---

## 6. Experiment matrix

The experiment should be staged. Do not begin with a full ensemble DA implementation.

| ID | Experiment | Main purpose |
| --- | --- | --- |
| `CTRL` | Open-loop iSnobal | Frozen no-NISAR baseline |
| `ASO-DA` | Existing/standard ASO-assisted iSnobal workflow | High-quality remote-sensing assimilation benchmark |
| `N0` | NISAR ΔSWE deterministic update | Establish whether NISAR contains useful corrective information |
| `N1` | Native versus aggregated NISAR support | Determine appropriate assimilation spatial scale |
| `N2` | Quality/uncertainty-aware update | Test observation weighting and rejection |
| `N3` | Pair-common/reference-error treatment | Separate common-mode from local observation error |
| `N4` | Alternative state-reconciliation methods | Determine how ΔSWE should modify coupled iSnobal state |
| `N5` | Ensemble/uncertainty-propagating DA | Propagate forcing/state uncertainty after simpler methods are understood |
| `OPS` | Retrospective operational replay | Evaluate forecast value using only information available at each historical issue time |

The sequence of questions is:

```text
Can NISAR correct the model?
        ↓
At what spatial scale?
        ↓
With what support and uncertainty treatment?
        ↓
How should the iSnobal state be reconciled?
        ↓
How should uncertainty propagate?
        ↓
Does the update improve a real forecast?
```

---

## 7. ASO Tuolumne data inventory

Three 2026 ASO survey packages are already available locally and should be treated as primary independent spatial evaluation datasets.

### Local source directories

```text
/Users/jtarrico/ch13_nisar_prelim/data/rasters/aso/ca/tuo/ASO_Tuolumne_2026Jan31-Feb01_AllData_and_Reports

/Users/jtarrico/ch13_nisar_prelim/data/rasters/aso/ca/tuo/ASO_Tuolumne_2026Feb27-28_SurveyData_and_Reports

/Users/jtarrico/ch13_nisar_prelim/data/rasters/aso/ca/tuo/ASO_Tuolumne_2026Apr06_SurveyData_and_Reports
```

### Survey dates and intended roles

| Survey | Dates | Initial study role |
| --- | --- | --- |
| ASO Tuolumne 1 | 2026-01-31 to 2026-02-01 | Primary early-season independent spatial endpoint for the currently available early-NISAR accumulation sequence; also model-state evaluation |
| ASO Tuolumne 2 | 2026-02-27 to 2026-02-28 | Independent mid-season model-state evaluation; future NISAR comparison if historical NISAR is reprocessed |
| ASO Tuolumne 3 | 2026-04-06 | Independent spring model-state / ablation evaluation; future NISAR comparison if historical NISAR is reprocessed |

### Required ASO inventory step

Do not assume exact filenames, units, CRS, nodata, or product version from directory names.

The first repository data task should recursively inventory each ASO package and record:

- exact SWE raster path
- snow-depth raster path if present
- survey start/end time
- product/provider version if available
- CRS
- transform
- resolution
- units from raster metadata or accompanying documentation
- nodata/fill convention
- spatial bounds
- checksum
- source package directory
- any uncertainty/quality layers
- relevant reports or metadata files

The Colorado GRL repository's `prepare_aso_swe.py` should guide the Tuolumne preparation workflow:

1. retain the source ASO raster unchanged;
2. construct a NISAR- or model-grid representation only for a declared comparison;
3. explicitly record resampling method;
4. verify source units before converting to millimetres SWE;
5. retain source-grid ASO for independent checks.

### ASO independence rule

ASO data used to tune the DA algorithm, observation-error model, aggregation scale, or state-update rule cannot simultaneously be described as independent validation for that same methodological decision.

Prefer to freeze assimilation choices using ERB/retrieval evidence, synthetic tests, or separate ASO information before reporting Tuolumne ASO as an evaluation target.

---

## 8. NISAR PROVISIONAL archive status and verified Tuolumne inventory

### 8.1 Important correction: PROVISIONAL now extends back into WY2026

The earlier statement that PROVISIONAL data begin only on 2026-06-17 is no longer an adequate description of the archive for this project.

The current CMR directory for collection `NISAR_L2_GUNW_PROVISIONAL_V1` / concept ID `C2854335566-ASF` contains PROVISIONAL GUNWs dated in **2025 as well as 2026**. The archive directory currently shows 1,212 provisional GUNW granules in 2025 and tens of thousands in 2026. Public NISAR/ASF forum examples also document **P05023 PROVISIONAL GUNWs formed from December 2025, January 2026, and February 2026 acquisitions**.

This means the current archive contains supplemental/back-processed PROVISIONAL products that predate the original forward-processing start described in the July release documentation.

For this project:

> **Current archive holdings and per-granule metadata are the source of truth for availability. Do not impose a June 17, 2026 cutoff in search code.**

The ASF/NISAR documentation that still describes June 17 as the PROVISIONAL start should be retained as release-history context, but it must not be used to exclude earlier P05023 products that are now present in CMR/ASF.

### 8.2 Tuolumne PROVISIONAL collection used by this study

The relevant product collection is:

```text
Short name: NISAR_L2_GUNW_PROVISIONAL_V1
CMR concept ID: C2854335566-ASF
Product: NISAR L2 Geocoded Unwrapped Interferogram (GUNW)
Processing configuration: PR / standard production
CRID: P05023 for the verified WY2026 inventory
Frequency: A
Polarization: HH
Frame coverage: Full
Nominal posting: 80 m
Nominal pair type: nearest-neighbor interferogram, usually 12 d
```

The exact ASF inventory established for the Tuolumne domain contains **38 verified PROVISIONAL P05023 GUNWs through the early-July study window: 19 on T042/F069 and 19 on T034/F021**.

A separate August archive/download audit found **42 total Tuolumne PROVISIONAL products (21 per geometry)** after additional forward products became available. The exact post-July pair metadata should be regenerated from ASF in Stage 1 rather than reconstructed from cadence alone; the science table below therefore lists the 38 exact pairs whose dates and sequence numbers are already established.

The downloader must always search from `2025-10-01` through the query time so that additional late-summer, autumn, and future-season products are automatically added to the inventory.

### 8.3 T042/F069 descending — verified PROVISIONAL P05023 pairs

| Seq. | Track/frame | Orbit | Reference | Secondary | Δt | CRID | Pol. | ASO relationship |
| ---: | --- | --- | --- | --- | ---: | --- | --- | --- |
| 004 | T042/F069 | Descending | 2025-11-01 | 2025-11-13 | 12 d | P05023 | HH | — |
| 005 | T042/F069 | Descending | 2025-11-13 | 2025-11-25 | 12 d | P05023 | HH | — |
| 006 | T042/F069 | Descending | 2025-11-25 | 2025-12-07 | 12 d | P05023 | HH | — |
| 007 | T042/F069 | Descending | 2025-12-07 | 2025-12-19 | 12 d | P05023 | HH | — |
| 008 | T042/F069 | Descending | 2025-12-19 | 2025-12-31 | 12 d | P05023 | HH | — |
| 009 | T042/F069 | Descending | 2025-12-31 | 2026-01-12 | 12 d | P05023 | HH | — |
| 010 | T042/F069 | Descending | 2026-01-12 | 2026-01-24 | 12 d | P05023 | HH | ASO Jan31-Feb01: 7 d before |
| 011 | T042/F069 | Descending | 2026-01-24 | 2026-02-05 | 12 d | P05023 | HH | ASO Jan31-Feb01: brackets survey |
| 013 | T042/F069 | Descending | 2026-02-17 | 2026-03-01 | 12 d | P05023 | HH | ASO Feb27-28: brackets survey |
| 014 | T042/F069 | Descending | 2026-03-01 | 2026-03-13 | 12 d | P05023 | HH | ASO Feb27-28: 1 d after |
| 015 | T042/F069 | Descending | 2026-03-13 | 2026-03-25 | 12 d | P05023 | HH | — |
| 016 | T042/F069 | Descending | 2026-03-25 | 2026-04-06 | 12 d | P05023 | HH | ASO Apr06: exact/ending endpoint |
| 017 | T042/F069 | Descending | 2026-04-06 | 2026-04-18 | 12 d | P05023 | HH | ASO Apr06: starts at survey |
| 018 | T042/F069 | Descending | 2026-04-18 | 2026-04-30 | 12 d | P05023 | HH | — |
| 019 | T042/F069 | Descending | 2026-04-30 | 2026-05-12 | 12 d | P05023 | HH | — |
| 020 | T042/F069 | Descending | 2026-05-12 | 2026-05-24 | 12 d | P05023 | HH | — |
| 021 | T042/F069 | Descending | 2026-05-24 | 2026-06-05 | 12 d | P05023 | HH | — |
| 022 | T042/F069 | Descending | 2026-06-05 | 2026-06-17 | 12 d | P05023 | HH | — |
| 024 | T042/F069 | Descending | 2026-06-29 | 2026-07-11 | 12 d | P05023 | HH | — |

**Known gaps in this exact inventory:** sequence 012 (`2026-02-05 → 2026-02-17`) and sequence 023 (`2026-06-17 → 2026-06-29`) were not present in the verified 19-product inventory. These are missing edges, not zero ΔSWE.

### 8.4 T034/F021 ascending — verified PROVISIONAL P05023 pairs

| Seq. | Track/frame | Orbit | Reference | Secondary | Δt | CRID | Pol. | ASO relationship |
| ---: | --- | --- | --- | --- | ---: | --- | --- | --- |
| 006 | T034/F021 | Ascending | 2025-11-24 | 2025-12-06 | 12 d | P05023 | HH | — |
| 007 | T034/F021 | Ascending | 2025-12-06 | 2025-12-18 | 12 d | P05023 | HH | — |
| 008 | T034/F021 | Ascending | 2025-12-18 | 2025-12-30 | 12 d | P05023 | HH | — |
| 009 | T034/F021 | Ascending | 2025-12-30 | 2026-01-11 | 12 d | P05023 | HH | — |
| 010 | T034/F021 | Ascending | 2026-01-11 | 2026-01-23 | 12 d | P05023 | HH | ASO Jan31-Feb01: 8 d before |
| 011 | T034/F021 | Ascending | 2026-01-23 | 2026-02-04 | 12 d | P05023 | HH | ASO Jan31-Feb01: brackets survey |
| 012 | T034/F021 | Ascending | 2026-02-04 | 2026-02-16 | 12 d | P05023 | HH | ASO Jan31-Feb01: 3 d after |
| 013 | T034/F021 | Ascending | 2026-02-16 | 2026-02-28 | 12 d | P05023 | HH | ASO Feb27-28: exact/ending endpoint |
| 014 | T034/F021 | Ascending | 2026-02-28 | 2026-03-12 | 12 d | P05023 | HH | — |
| 015 | T034/F021 | Ascending | 2026-03-12 | 2026-03-24 | 12 d | P05023 | HH | — |
| 016 | T034/F021 | Ascending | 2026-03-24 | 2026-04-05 | 12 d | P05023 | HH | ASO Apr06: 1 d before |
| 017 | T034/F021 | Ascending | 2026-04-05 | 2026-04-17 | 12 d | P05023 | HH | ASO Apr06: brackets survey |
| 018 | T034/F021 | Ascending | 2026-04-17 | 2026-04-29 | 12 d | P05023 | HH | — |
| 019 | T034/F021 | Ascending | 2026-04-29 | 2026-05-11 | 12 d | P05023 | HH | — |
| 020 | T034/F021 | Ascending | 2026-05-11 | 2026-05-23 | 12 d | P05023 | HH | — |
| 021 | T034/F021 | Ascending | 2026-05-23 | 2026-06-04 | 12 d | P05023 | HH | — |
| 022 | T034/F021 | Ascending | 2026-06-04 | 2026-06-16 | 12 d | P05023 | HH | — |
| 023 | T034/F021 | Ascending | 2026-06-16 | 2026-06-28 | 12 d | P05023 | HH | — |
| 024 | T034/F021 | Ascending | 2026-06-28 | 2026-07-10 | 12 d | P05023 | HH | — |

T034/F021 is continuous from sequence 006 through 024 in the verified early-July inventory.

### 8.5 ASO–NISAR timing is substantially better than the previous charter implied

The back-processed PROVISIONAL archive makes all three ASO surveys scientifically useful for direct NISAR/iSnobal experiments.

#### ASO 2026-01-31 to 2026-02-01

Both geometries bracket the survey:

- T042/F069: `2026-01-24 → 2026-02-05`
- T034/F021: `2026-01-23 → 2026-02-04`

This is not an exact endpoint comparison. It is useful for testing interpolation/forecast-evolution behavior and for evaluating the model state between NISAR epochs.

#### ASO 2026-02-27 to 2026-02-28

This survey has an especially useful ascending comparison:

- T034/F021: `2026-02-16 → 2026-02-28` ends on the final survey date.
- T042/F069: `2026-02-17 → 2026-03-01` brackets the survey.

The T034/F021 pair is a strong candidate for direct pairwise ΔSWE / state-update evaluation.

#### ASO 2026-04-06

This survey has an especially useful descending comparison:

- T042/F069: `2026-03-25 → 2026-04-06` ends exactly on the ASO date.
- T034/F021: `2026-03-24 → 2026-04-05` ends one day before ASO.
- T034/F021: `2026-04-05 → 2026-04-17` begins one day before ASO.

This is likely the strongest ASO-constrained assimilation/evaluation window because one geometry has an exact endpoint and the second has a one-day timing offset.

### 8.6 Product-use categories

The repository inventory should classify each GUNW by scientific role rather than treating every product identically.

```text
core_da
    dry-snow / supported pairs used as DA observations

aso_endpoint
    pairs ending at or immediately adjacent to an ASO survey

aso_bracketing
    pairs whose interval contains an ASO survey

model_free_evolution
    pairs useful for assessing persistence after a DA update

melt_season
    spring pairs used to test wet-snow / ablation limitations

snow_free_reference
    late-season products useful for geometry, phase/reference, and pipeline tests

excluded
    unsupported products with explicit exclusion reason
```

A product remains in the inventory even if excluded from a particular DA experiment.

### 8.7 Archive-refresh rule

The exact catalog must be regenerated at the start of every major analysis milestone.

Search:

```text
collection: NISAR_L2_GUNW_PROVISIONAL_V1
concept ID: C2854335566-ASF
AOI: Tuolumne basin polygon / verified ASO footprint union
start: 2025-10-01
end: current query time
track/frame priority:
    T042/F069 descending
    T034/F021 ascending
```

Do not hard-code the 38- or 42-product count. Those are provenance snapshots, not expected final archive sizes.

The resulting manifest must retain exact zero-Doppler timestamps and full granule IDs so that dates derived from nominal cadence are never substituted for actual product metadata.
## 9. NISAR download and inventory plan

The Colorado GRL first-look repository provides the template for this workflow:

- `scripts/nisar_firstlook/io/download_colorado_provisional.py`
- `scripts/nisar_firstlook/io/inventory_gunw.py`
- `data/external_data_manifest.csv`
- `nisar_firstlook/DATA_INVENTORY.md`

The Tuolumne repository should adapt the logic rather than copy Colorado-specific scientific assumptions.

### 9.1 Planned download script

Create:

```text
scripts/io/download_tuolumne_nisar.py
```

The script should:

1. discover the exact ASO SWE raster(s) inside the three local Tuolumne packages;
2. transform each ASO raster extent to EPSG:4326;
3. build the geographic union of the ASO footprints;
4. query ASF for all NISAR L2 GUNW products intersecting the Tuolumne AOI;
5. explicitly query maturity (`PROVISIONAL` or `BETA`) rather than inferring it from filenames;
6. retain acquisition/reference times, track, frame, orbit direction, CRID/product version, polarization, file size, concept ID, and URL;
7. inventory before download;
8. deduplicate exact granules without collapsing distinct processing versions;
9. download resumably;
10. verify downloaded byte count;
11. verify each file opens as HDF5 and satisfies the GUNW layer contract;
12. write a machine-readable inventory;
13. never commit raw GUNWs to Git.

### 9.2 PROVISIONAL search

The PROVISIONAL query must **not** use 2026-06-17 as a lower temporal bound. Supplemental/back-processed P05023 products now extend into the 2025–2026 snow season.

Primary query:

```text
dataset/platform: NISAR
collection: NISAR_L2_GUNW_PROVISIONAL_V1
CMR concept ID: C2854335566-ASF
processing level: GUNW
production configuration: PR
maturity: PROVISIONAL
start: 2025-10-01
end: current query time
AOI: Tuolumne basin polygon or verified union of ASO raster footprints
```

The script should first perform an unrestricted Tuolumne AOI inventory, then identify the two primary geometries:

```text
T042/F069 descending
T034/F021 ascending
```

Retain every returned product version and CRID in the raw inventory. For the current WY2026 analysis, P05023 is the verified science-processing CRID, but future higher-CRID or VALIDATED replacements must not be silently discarded.

The repository should write both:

```text
data/inventories/tuolumne_nisar_provisional_all.json
data/inventories/tuolumne_nisar_provisional_primary_frames.json
```

The first preserves all AOI-intersecting provisional products. The second is the science-facing inventory for the primary T042/F069 and T034/F021 paths.
### 9.3 BETA companion inventory

Create a separate inventory for the early snow season:

```text
data/inventories/tuolumne_nisar_beta.json
```

Search the BETA archive over the same AOI for the available 2025-10 through 2026-01 release period.

BETA and PROVISIONAL must remain separate in:

- directory structure
- manifests
- analysis configuration
- figures
- reported metrics

Any cross-maturity analysis must be explicitly labeled.

### 9.4 Future validated-reprocessing inventory

When the validated historical reprocessing becomes available:

1. rerun the ASF search from scratch;
2. store a new inventory;
3. map validated products to previous logical pair edges;
4. compare product metadata and phase behavior against BETA;
5. rebuild SnowIn pair datasets;
6. rerun all downstream DA experiments from the frozen configuration.

Do not overwrite the BETA inventory or derived outputs.

### 9.5 Planned local data layout

Raw data remain outside Git:

```text
/Users/jtarrico/ch13_nisar_prelim/data/
├── rasters/
│   └── aso/
│       └── ca/
│           └── tuo/
│               ├── ASO_Tuolumne_2026Jan31-Feb01_AllData_and_Reports/
│               ├── ASO_Tuolumne_2026Feb27-28_SurveyData_and_Reports/
│               └── ASO_Tuolumne_2026Apr06_SurveyData_and_Reports/
└── nisar/
    └── gunw/
        └── tuolumne/
            ├── beta/
            │   └── <track_frame>/
            ├── provisional/
            │   └── <track_frame>/
            └── validated/
                └── <track_frame>/
```

The repository itself should contain only manifests, compact metadata, configurations, and small fixtures.

### 9.6 Planned CLI

After implementation, the preferred pattern is:

```bash
python scripts/io/download_tuolumne_nisar.py \
  --aso-root "/Users/jtarrico/ch13_nisar_prelim/data/rasters/aso/ca/tuo" \
  --maturity PROVISIONAL \
  --start 2026-06-17 \
  --download-root "/Users/jtarrico/ch13_nisar_prelim/data/nisar/gunw/tuolumne/provisional" \
  --inventory-output "data/inventories/tuolumne_nisar_provisional.json"
```

and separately:

```bash
python scripts/io/download_tuolumne_nisar.py \
  --aso-root "/Users/jtarrico/ch13_nisar_prelim/data/rasters/aso/ca/tuo" \
  --maturity BETA \
  --download-root "/Users/jtarrico/ch13_nisar_prelim/data/nisar/gunw/tuolumne/beta" \
  --inventory-output "data/inventories/tuolumne_nisar_beta.json"
```

Authentication should use an Earthdata Login `.netrc` or another standard ASF/earthaccess mechanism. Credentials must never appear in repository files or command history committed to Git.

---

## 10. NISAR raw-product validation

Every GUNW used by the project must pass a raw-input contract before SnowIn processing.

At minimum record and verify:

- granule ID
- maturity
- CRID / software version
- reference acquisition time
- secondary acquisition time
- chronological edge orientation
- track
- frame
- ascending/descending
- polarization
- product CRS
- map grid and spacing
- product dimensions
- wavelength metadata
- unwrapped phase layer
- coherence layer
- connected-components layer
- ionospheric phase/uncertainty if present
- tropospheric layers if present
- product mask/fill conventions
- file checksum
- file size

For standard co-polarized GUNW products, expect approximately 80 m posting, but verify actual metadata rather than hard-coding it.

Run inventory validation before any retrieval:

```text
raw HDF5
   ↓
raw contract validation
   ↓
SnowIn normalization
   ↓
retrieval / reference / support
```

---

## 11. SnowIn processing boundary

The Tuolumne repository should depend on SnowIn rather than duplicate the Colorado retrieval implementation.

For each NISAR pair, SnowIn should produce a normalized xarray Dataset carrying at least:

```text
phase
incidence_angle
coherence
connected_component
reference_time
secondary_time
wavelength_m
source_granule_id
source phase convention
phase transform
CRS / spatial_ref
```

After reference and retrieval:

```text
dswe
phase_referenced
reference support
pairwise support
snow-state support
correction provenance
reference provenance
```

For DA use, construct a downstream observation dataset containing:

```text
dswe
dswe_uncertainty
reference_time
secondary_time
observation_support
pair_common_uncertainty
local_uncertainty
source_granule_id
processing_maturity
processing_crid
retrieval_method
reference_method
```

The DA repository should not directly interpret raw NISAR HDF5 group paths.

---

## 12. Observation-error model

A useful initial NISAR error representation is:

\[
\epsilon_k(x)=b_k+\epsilon'_k(x)
\]

where:

- \(b_k\) is pair-level/common-mode uncertainty associated with phase referencing, residual atmospheric effects, or other pair-wide errors;
- \(\epsilon'_k(x)\) is local retrieval uncertainty.

Candidate predictors of local uncertainty include:

- coherence
- connected-component behavior
- phase gradients / unwrap diagnostics
- local incidence geometry
- terrain
- canopy / forest cover
- wet-snow evidence
- atmospheric/ionospheric correction uncertainty
- spatial distance to reference support

ERB should inform these relationships where possible. Tuolumne should test whether they transfer rather than freely retuning them against Tuolumne ASO.

---

## 13. Spatial-support experiment

Do not simply resample NISAR to the model grid and assume every model cell has an independent observation.

Instead define the observation operator at a declared support:

```text
iSnobal model cells
      ↓ H()
NISAR observation support
      ↓
innovation
      ↓
state update
```

Candidate experiments:

- native GUNW support
- approximately 3 × 3 GUNW-pixel superobservations
- approximately 5 × 5 GUNW-pixel superobservations
- elevation-band aggregation
- terrain-informed aggregation if scientifically justified

The exact scales should be chosen after examining spatial residual covariance, not before.

---

## 14. Evaluation strategy

Evaluation should distinguish three questions.

### Analysis-state evaluation

How much does the state improve immediately after assimilation?

### Free-evolution evaluation

How long does the improvement persist if the model is run forward without another observation update?

### Forecast evaluation

Does an assimilated state improve a forecast initialized at that time?

Primary metrics should include:

- spatial RMSE
- MAE
- bias
- correlation
- regression slope
- basin SWE volume
- elevation-stratified error
- spatial-support fraction
- snow disappearance timing
- melt timing
- SWI
- forecast skill as a function of lead time

Accuracy and retained coverage must be reported together.

---

## 15. M3 Works public GitHub review and implications

The M3 Works public organization currently exposes ten repositories.

| Repository | Relevance to this project |
| --- | --- |
| `M3Works/pointsnobal` | **High** — open Python/C Snobal implementation; exposes snow state, restart concepts, melt, and SWI |
| `M3Works/metloom` | **High** — standardized CDEC, SNOTEL, USGS, MesoWest, NWS, and other observed-data access |
| `M3Works/inicheck` | **Moderate/high reference** — configuration validation and legacy SMRF/iSnobal configuration contracts, including HRRR and restart concepts |
| `M3Works/metevents` | **Moderate** — precipitation/storm event identification; useful later for event-stratified DA analysis |
| `M3Works/insitupy` | **Moderate/optional** — standardized parsing of in-situ profile data |
| `M3Works/pyPRMS` | **Future** — potential downstream hydrologic-model connection |
| `M3Works/powder_bot` | Low direct science relevance; useful as an operational visualization reference |
| `M3Works/metloom-tutorial` | Documentation/examples only |
| `M3Works/staged-recipes` | Packaging only |
| `M3Works/.github` | Important organizational description of the operational iSnobal framework |

### Architectural consequence

The public repositories do **not** expose M3's complete operational distributed iSnobal system. M3 describes its operational model as a custom, cloud-native implementation used across western U.S. basins. The funded THP proposal also treats M3's modeling framework as proprietary while allowing model outputs and project-derived products to be published.

Therefore:

> **The Tuolumne repository owns the experiment and scientific contracts, not the production model implementation.**

`pointsnobal` should be used for transparent state-update tests and simplified physical regression tests. The M3 production model should satisfy a stable external interface.

---

## 16. M3 model interface

Create:

```text
docs/M3_INTERFACE.md
```

Minimum model-side capabilities to resolve with M3:

```text
model_grid
state(time)
restart_state(time)
forcing(time)
forecast_forcing(issue_time, lead)
run(start, end, restart_state)
```

Minimum state variables:

```text
SWE / specific mass
snow depth
density
surface-layer temperature
lower-layer temperature
mean snow temperature if required
cold content
liquid water
layer masses / depths as required by restart
```

Minimum returned diagnostics:

```text
SWE
depth
density
melt
SWI
selected energy terms
state validity / model failure flags
```

How M3 creates those internally is outside the open Tuolumne repository.

---

## 17. Software architecture

Repository:

```text
jacktarricone/nisar-isnobal-da-tuolumne
```

Proposed structure:

```text
nisar-isnobal-da-tuolumne/
├── .github/
│   └── workflows/
├── AGENTS.md
├── README.md
├── CITATION.cff
├── pyproject.toml
│
├── config/
│   ├── experiments/
│   ├── domains/
│   └── frozen/
│
├── data/
│   ├── inventories/
│   │   ├── tuolumne_aso.csv
│   │   ├── tuolumne_nisar_beta.json
│   │   └── tuolumne_nisar_provisional.json
│   ├── manifests/
│   │   └── external_data_manifest.csv
│   └── fixtures/
│
├── docs/
│   ├── PROJECT_CHARTER.md
│   ├── SCIENTIFIC_CONTRACT.md
│   ├── DATA_CONTRACTS.md
│   ├── DATA_ACQUISITION.md
│   ├── EXPERIMENT_DESIGN.md
│   ├── M3_INTERFACE.md
│   ├── OBSERVATION_ERROR.md
│   ├── STATE_UPDATE.md
│   └── REPRODUCIBILITY.md
│
├── src/
│   └── nisar_isnobal_da/
│       ├── observations/
│       ├── model/
│       ├── assimilation/
│       ├── uncertainty/
│       ├── evaluation/
│       ├── experiments/
│       └── io/
│
├── scripts/
│   ├── io/
│   │   ├── inventory_aso.py
│   │   ├── download_tuolumne_nisar.py
│   │   └── validate_nisar_inventory.py
│   ├── prepare_observations.py
│   ├── run_experiment.py
│   ├── evaluate_experiment.py
│   └── build_evidence.py
│
└── tests/
    ├── unit/
    ├── invariants/
    ├── integration/
    └── fixtures/
```

---

## 18. External data manifest

Mirror the good parts of the Colorado GRL `external_data_manifest.csv`.

Recommended columns:

```text
dataset
provider
product
version
identifier
basin
track_frame
acquisition_start
acquisition_end
units
crs
resolution
local_expected_path
download_method
persistent_identifier
study_role
independence_category
checksum
notes
```

Raw NISAR, ASO, terrain, and large model products remain external.

The repository contains only:

- manifests
- inventories
- compact provenance
- frozen configuration
- tiny test fixtures
- final manuscript-supporting summary tables where appropriate

---

## 19. Collaborator responsibilities

### Jack / NASA–UMD — science lead

- overall science design
- NISAR data inventory and SnowIn interface
- retrieval uncertainty and support
- observation operator
- ERB-to-Tuolumne transfer of uncertainty/QC rules
- independent evaluation
- repository architecture and reproducibility
- manuscript leadership

### M3 Works — modeling lead

- operational Tuolumne iSnobal configuration
- forcing and model-state products
- restart-state contract
- feasibility of state-update methods
- historical/forecast forcing availability
- operational replay design
- interpretation of model physics and SWI
- assessment of which DA methods could realistically translate into operations

### Carrie Vuyovich / THP PI

- programmatic/scientific oversight
- THP scope alignment
- NASA relevance and product interpretation

### ASO / other collaborators as appropriate

- ASO product interpretation
- lidar/SWE uncertainty
- review of historical Tuolumne direct-insertion practices
- independent review of DA design where relevant

Responsibilities remain proposed until agreed with collaborators.

---

## 20. Immediate technical questions for M3

Resolve before implementing the DA algorithm:

1. Which complete iSnobal restart variables can M3 export and re-ingest at arbitrary analysis times?
2. Can state snapshots be archived at every NISAR acquisition epoch?
3. Are historical forecast forcings available **as they were issued**, or only retrospective/reanalysis forcing?
4. What ASO state-update methods are currently used operationally, and which parts can be described publicly?
5. Can M3 provide model input/output through a stable NetCDF/Zarr/xarray-compatible exchange contract?
6. What grid/resolution is used for the Tuolumne production model?
7. Can the model be rerun repeatedly for controlled DA experiments without changing unrelated operational tuning?
8. Which SWE, depth, density, thermal, layer, and liquid-water variables are mandatory for restart?
9. What diagnostic constitutes SWI in the current production framework and at what time aggregation?
10. What model/forcing versions should be frozen for the manuscript baseline?

Question 3 determines whether the first paper can defensibly make an **operational forecast** claim rather than a retrospective state-estimation/free-evolution claim.

---

## 21. Initial Codex development stages

### Stage 0 — Repository foundation

Create:

- package skeleton
- CI
- Ruff/pytest
- `AGENTS.md`
- project charter
- data/science/model contracts
- external-data policy
- no assimilation science yet

### Stage 1 — Data inventory

Implement:

- ASO recursive inventory
- ASO metadata validation
- ASF NISAR BETA inventory
- ASF NISAR PROVISIONAL inventory
- resumable GUNW downloader
- GUNW raw-contract validation
- external data manifest

This stage should make **zero scientific retrieval choices**.

### Stage 2 — SnowIn observation adapter

Implement the boundary:

```text
raw GUNW
  -> SnowIn normalized pair
  -> reference/corrections/retrieval
  -> DA-ready observation Dataset
```

No model update yet.

### Stage 3 — iSnobal model interface

Implement:

- synthetic model-state fixture
- `pointsnobal` test adapter
- abstract M3 exchange contract
- state validator
- restart-state validator

### Stage 4 — Deterministic DA

Implement `N0` only.

Tests must include:

- zero innovation leaves state unchanged
- positive/negative innovations conserve intended mass change
- no negative SWE/depth
- density remains physical
- layer/state invariants hold
- missing NISAR support does not update model state
- unsupported observation pixels never become zero-change observations

### Stage 5 — Spatial support and uncertainty

Implement `N1`–`N3`.

### Stage 6 — State reconciliation

Implement and compare `N4`.

### Stage 7 — Ensemble / forecast experiments

Only after deterministic behavior is scientifically understood.

---

## 22. First scientific deliverables

The first complete analysis should be able to answer:

1. What NISAR pairs and maturity levels actually exist over Tuolumne?
2. What fraction of the basin is supported for each pair?
3. How does open-loop iSnobal ΔSWE compare to NISAR ΔSWE?
4. How does the spatial residual covariance change with terrain, coherence, canopy, and snow state?
5. Does a simple NISAR update improve independent ASO/state evaluation?
6. How sensitive is improvement to spatial support?
7. How long does an update persist?
8. Which state-reconciliation method avoids unphysical or rapidly unstable model response?
9. Does NISAR assimilation improve SWI or forecast-relevant timing?
10. Under what conditions should an operational system reject the NISAR observation?

---

## 23. Source and implementation references

### Project repositories

- SnowIn: https://github.com/snowin-org/snowin
- Colorado NISAR first-look: https://github.com/jacktarricone/nisar-grl-colorado-firstlook/tree/development
- M3 Works organization: https://github.com/M3Works
- PointSnobal: https://github.com/M3Works/pointsnobal
- Metloom: https://github.com/M3Works/metloom
- Metevents: https://github.com/M3Works/metevents
- Inicheck: https://github.com/M3Works/inicheck

### NISAR archive documentation

### Current archive verification

- CMR collection directory for NISAR PROVISIONAL GUNW: https://cmr.earthdata.nasa.gov/virtual-directory/collections/C2854335566-ASF
- CMR temporal directory showing 2025 and 2026 provisional holdings: https://cmr.earthdata.nasa.gov/virtual-directory/collections/C2854335566-ASF/temporal
- NISAR/ASF provisional known-issues page: https://nisar-docs.asf.alaska.edu/provisional-known-issues/
- NISAR/ASF Earthaccess collection short names: https://nisar-docs.asf.alaska.edu/earthaccess/
- Example Earthdata Forum discussion containing P05023 GUNWs from Dec 2025–Feb 2026: https://forum.earthdata.nasa.gov/viewtopic.php?t=8133


- ASF NISAR availability overview: https://nisar-docs.asf.alaska.edu/availability-overview/
- ASF provisional known issues: https://nisar-docs.asf.alaska.edu/provisional-known-issues/
- ASF NISAR search/download guide: https://nisar-docs.asf.alaska.edu/asf-search/
- ASF GUNW product overview: https://nisar-docs.asf.alaska.edu/gunw/
- ASF direct S3 access: https://nisar-docs.asf.alaska.edu/aws-s3-access/

### Scientific references that anchor project design

- Marks et al. (1999), spatially distributed iSnobal energy-balance model.
- Hedrick et al. (2018), direct insertion of ASO-derived snow depth into iSnobal in the Tuolumne.
- Tarricone et al. (2026), review of InSAR for seasonal snow monitoring.
- THP24 proposal: *NISAR for global snow water equivalent: Evaluating L-band InSAR for basin scale snow monitoring by leveraging airborne lidar, modeling, and the SnowEx campaigns.*

---

## 24. Scope statement

The first Tuolumne paper should not be designed to show only that assimilation decreases one SWE error metric.

Its stronger target is:

> **Establish when NISAR ΔSWE adds useful information to a physically based operational snow model, how that information should be spatially and statistically represented, how the model state should be updated, and whether the resulting benefit persists into snowmelt and forecast-relevant quantities.**

That scope is scientifically complementary to the ERB retrieval-validation work and produces a pathway from NISAR measurement performance to hydrologic decision value.
