# NISAR–iSnobal Tuolumne Data Assimilation

This project will evaluate how NISAR L-band InSAR snow water equivalent change (ΔSWE) can contribute to iSnobal snow-state estimation and forecast-relevant outputs in the Tuolumne River Basin. It complements the Colorado / East River Basin retrieval-validation effort and relies on SnowIn for reusable NISAR snow-InSAR processing. See the [project charter](docs/PROJECT_CHARTER.md) for full scientific context.

## Project status

Stage 1 inventories, the resumable GUNW downloader, and raw-product validation are in place. The SnowIn xarray observation adapter validates already processed pairwise dSWE outputs. The two-frame retrieval baseline analyzes pairs ending on or before 2026-06-01 (16 T042/F069 and 15 T034/F021 pairs) and writes maps, tables, and figures under Git-ignored `data/derived/`. The later T042/F069 segment is excluded. A phase-reference sensitivity comparison applies equal-weight median, coherence-weighted mean, maximum-station, and minimum-station offsets to the same pairs and station support. The baseline remains a retrieval diagnostic, not independent validation or a production DA workflow. The adapter does not synthesize missing support or uncertainty, and the project does not implement assimilation or model-state updates. Planned experiments remain hypotheses, not results.

## Repository layout

- `src/nisar_isnobal_da/observations/` — Stage 2 SnowIn observation adapter.
- `tests/unit/` — package-import smoke test.
- `docs/` — project charter and operational contracts.
- `scripts/io/` — Stage 1 inventory, manifest, and raw-product validation commands.
- `scripts/analysis/` — reproducible Tuolumne pairwise retrieval and baseline figures.
- `data/inventories/` — ASO metadata and separate BETA/PROVISIONAL CMR snapshots.
- `data/manifests/` — external-data manifest built from the inventories.
- `.github/workflows/ci.yml` — Python 3.12 lint, format, and test checks.

## Development setup

Create the shared Conda environment from the repository root:

```bash
conda env create -f environment.yml
conda activate nisar-m3-da
```

The environment installs this checkout in editable mode, development and data-I/O
extras, the NISAR GUNW reader, and the analysis stack. SnowIn remains a separate
source checkout because its GitHub repository requires access that a fresh
anonymous environment build does not have. If you have that checkout, install its
GUNW/Dask extras after activation:

```bash
python -m pip install -e "/path/to/snowin[gunw,dask]"
```

To refresh an existing environment after the YAML changes, run
`conda env update -f environment.yml --prune`.

Run the configured checks from the repository root:

```bash
ruff check .
ruff format --check .
pytest
```

## Stage 1 data inventory

Install inventory-only dependencies with `python -m pip install -e ".[inventory]"`.
Refresh the three ASO package records and the footprint used for CMR search:

```bash
python scripts/io/inventory_aso.py \
  --aso-root "/Users/jtarrico/ch13_nisar_prelim/data/rasters/aso/ca/tuo"
python scripts/io/inventory_nisar.py
python scripts/io/build_external_manifest.py
```

`inventory_nisar.py` queries BETA and PROVISIONAL as separate CMR collections,
from 2025-10-01 through the query timestamp. It records catalog metadata only; it
does not download products. The resumable downloader consumes a saved inventory
and defaults to a dry run. Install its optional dependencies with
`python -m pip install -e ".[download]"`. Start the primary PROVISIONAL frame
set with:

```bash
python scripts/io/download_tuolumne_nisar.py --maturity PROVISIONAL --execute
```

For BETA, pass `--maturity BETA --inventory
data/inventories/tuolumne_nisar_beta.json`. BETA and PROVISIONAL are stored
separately. Downloaded files are checked against catalog byte counts and MD5,
then passed to the raw HDF5 validator. The downloader uses local Earthdata
credentials and does not place them in command arguments or repository files.

The validator can also be run directly on locally held products and matched to
one or more catalog snapshots:

```bash
python scripts/io/validate_nisar_gunw.py /path/to/product.h5 \
  --catalog-json data/inventories/tuolumne_nisar_beta.json \
  --catalog-json data/inventories/tuolumne_nisar_provisional_all.json
```

See [Data inventory workflow](docs/DATA_INVENTORY.md) for recorded fields and
known metadata limits. ASO source package terms must be checked before sharing
inventory details outside the authorized project workspace.

Refresh the daily CDEC SWE series for the eight inventoried Tuolumne stations
with sensor 3 (daily snow water content):

```bash
python scripts/io/download_tuolumne_cdec.py \
  --start 2025-10-01 --end 2026-09-28
```

Raw and normalized station data are written under Git-ignored
`data/external/cdec/`. The normalized table preserves CDEC flags and leaves
non-numeric source values missing; it does not fill gaps or filter stations.
Use `--manifest-path data/inventories/<snapshot>.json` to retain a tracked
provenance snapshot for a later refresh.

## Two-frame retrieval baseline

The baseline script reuses SnowIn's GUNW phase normalization, product wavelength,
local incidence, dSWE calculation, and connected-path accumulation. For each
pair it forms an equal-weight median reference from eligible in-basin CDEC station
residuals. The analysis cutoff is 2026-06-01 inclusive, based on each pair's
secondary acquisition date; station context is clipped to the same date. The full
catalog snapshots remain available, while the analysis includes only pairs ending
by the cutoff (16 T042/F069 and 15 T034/F021). The later T042/F069 segment is
excluded. VIIRS snow masks are shown only as downstream support diagnostics; they
do not filter the retrieval. Each ASO SWE raster is preserved at source and also
area-averaged from its 50 m source grid to the shared 80 m NISAR grid for spatial
alignment. A separate ERB–GRL-style diagnostic compares ASO total SWE with the
nearest cumulative NISAR dSWE endpoint for each survey, frame, and reference
method, on common VIIRS snow support. That comparison is conditional on near-zero
SWE at the NISAR path start and is not absolute-SWE validation. Diverging dSWE
maps use red for negative values and blue for positive values.
The comparison also recalculates full pairwise dSWE rasters and connected
cumulative paths using the current equal-weight median, a coherence-weighted
mean, and the maximum and minimum eligible station residuals. It writes three
method comparison tables and two comparison figures, including endpoint maps.
An ERB–GRL-style downstream comparison evaluates each cumulative reference
method at all three ASO surveys on common VIIRS snow support. It is descriptive
and conditional on near-zero SWE at each NISAR path start.

After preparing the GUNW and NISAR COP30 DEM paths used on your system, run:

```bash
python scripts/analysis/tuolumne_retrieval_baseline.py \
  --gunw-root /path/to/provisional \
  --dem /path/to/tuolumne_four_tile_mosaic.tif \
  --aso-root /path/to/aso/ca/tuo
```

The script also requires the tracked CDEC/VIIRS inventories and the corresponding
local raw data. It writes NetCDF pair and cumulative fields, CSV summaries, a run
manifest, three ASO GeoTIFFs on the common NISAR grid, and ten PNG/PDF figure
pairs under `data/derived/tuolumne_retrieval_baseline/`. See the [baseline method
note](docs/TUOLUMNE_RETRIEVAL_BASELINE.md) for conventions, limitations, and the
current result summary.

After that baseline run, construct the ASO comparisons with:

```bash
python scripts/analysis/tuolumne_aso_reference_comparison.py
```

This writes 24 ASO/NISAR difference rasters, one shared-support raster for each
survey/frame, a 24-row metrics table, and four PNG/PDF figures beneath
`data/derived/tuolumne_retrieval_baseline/aso_reference_comparison/`.

## Project contracts

- [Scientific contract](docs/SCIENTIFIC_CONTRACT.md) — project purpose and hypotheses.
- [Experiment design](docs/EXPERIMENT_DESIGN.md) — planned comparisons and evaluation.
- [Data contracts](docs/DATA_CONTRACTS.md) — fixed observation conventions and data boundaries.
- [SnowIn observation adapter](docs/OBSERVATION_ADAPTER.md) — adapter inputs, validation, provenance, and DA readiness.
- [M3 interface](docs/M3_INTERFACE.md) — proposed model exchange and unresolved questions.
- [External data policy](docs/EXTERNAL_DATA_POLICY.md) — repository data and credential handling.
- [Tuolumne retrieval baseline](docs/TUOLUMNE_RETRIEVAL_BASELINE.md) — implemented two-frame retrieval and figure workflow.
- [Charter progress](docs/CHARTER_PROGRESS.md) — completed work, evidence limits, and open M3/research decisions.

These concise documents refer to the relevant sections of the [charter](docs/PROJECT_CHARTER.md), which remains the original project design record.

## Data and citation

Raw NISAR, ASO, terrain, and large model products are external to this repository. Do not commit them or credentials. See the external data policy before adding project data. Citation and license metadata remain to be established.
