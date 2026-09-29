# Stage 1 Inventory and Download Workflow

This document describes the Stage 1 inventory and raw-product workflow. It
follows charter §§7–10 and §18. It does not choose retrieval inputs, quality
thresholds, correction layers, resampling, or assimilation roles.

## Inventory outputs

- `data/inventories/tuolumne_aso.csv` records every file in the three chartered
  ASO packages, including file path, size, SHA-256, raster CRS, transform,
  resolution, dimensions, nodata, bounds, tags, and source evidence for units.
- `data/inventories/tuolumne_aso_aoi.geojson` is the union of the source SWE
  rasters' rectangular footprints transformed to EPSG:4326. It is a catalog
  search geometry, not a basin boundary.
- `data/inventories/tuolumne_basin_boundary.geojson` is the supplied Tuolumne
  basin polygon, copied from the prior local project and checksummed in its JSON
  sidecar. It is distinct from the ASO-footprint CMR search geometry.
- `data/inventories/tuolumne_cdec_station_metadata.csv` records the eight
  station locations used for the basin station series. Its sidecar documents
  source provenance; the prior workflow's `use_for_reference` role flag is
  intentionally not carried forward as a Tuolumne selection rule.
- `data/inventories/tuolumne_dem_processing.json` records the local Modified
  Copernicus DEM mosaic checksum, grid, height reference, and source tile names
  copied from GeoTIFF tags. Distributor and original download details are not
  available in local metadata.
- `data/inventories/tuolumne_nisar_beta.json` and
  `data/inventories/tuolumne_nisar_provisional_all.json` are independent CMR
  snapshots. Each records query time, temporal bounds, all matching collection
  versions, granule metadata, CMR-provided file checksums/sizes, and catalog
  links. The query begins `2025-10-01` and ends at its recorded UTC timestamp.
- `data/inventories/tuolumne_nisar_provisional_primary_frames.json` is a metadata
  subset for T042/F069 and T034/F021 when CMR explicitly supplies track and frame
  attributes. It retains the same maturity and version fields as the full
  PROVISIONAL snapshot.
- `data/manifests/external_data_manifest.csv` combines ASO and NISAR catalog
  records with available CDEC, VIIRS, basin-boundary, and DEM records. CMR
  checksums for NISAR are provider-reported, not local verification; CDEC and
  VIIRS rows record local SHA-256 values. DEM distributor/download provenance
  remains unresolved.

Refresh ASO metadata and the spatial search geometry first, then query CMR and
rebuild the manifest. Refresh CDEC daily SWE independently with the station
script:

```bash
python scripts/io/inventory_aso.py \
  --aso-root "/Users/jtarrico/ch13_nisar_prelim/data/rasters/aso/ca/tuo"
python scripts/io/inventory_nisar.py
python scripts/io/build_external_manifest.py
python scripts/io/download_tuolumne_cdec.py \
  --start 2025-10-01 --end 2026-09-28
```

CMR is queried separately by the BETA and PROVISIONAL collection short names.
Collection version, granule identifier, CRID, product version, maturity, and
acquisition metadata are preserved; distinct products are not deduplicated by
logical pair. The primary-frame subset uses only explicit CMR track/frame fields,
not granule-name parsing. The query geometry covers the ASO raster footprints,
not a hand-drawn basin polygon.

## Raw GUNW validation

`scripts/io/validate_nisar_gunw.py` is read-only. It records file size and local
SHA-256/MD5, HDF5 groups/datasets, dataset dimensions and types, fill values,
metadata attributes, projection metadata, and available correction-layer paths.
It checks for `unwrappedPhase`, `coherenceMagnitude`, and
`connectedComponents` in the GUNW unwrapped-interferogram grids and checks their
dimensions. It does not read image pixels. With `--catalog-json`, it matches the
exact catalog HDF5 filename, records maturity and product identifiers, compares
local size/checksum to CMR metadata, and checks reference-before-secondary time
ordering.

```bash
python scripts/io/validate_nisar_gunw.py /path/to/product.h5 \
  --catalog-json data/inventories/tuolumne_nisar_beta.json \
  --catalog-json data/inventories/tuolumne_nisar_provisional_all.json \
  --output validation-report.json
```

No GUNW was downloaded during the original Stage 1 inventory milestone. Since
then the validator has been run on the selected PROVISIONAL product batch and a
real T042/F069 GUNW has also been read in the SnowIn pilot. Metadata absent from
CMR remains blank or is reported as unresolved; this workflow does not infer
product CRS, raster resolution, or wavelength from nominal product descriptions.

## Resumable download

`scripts/io/download_tuolumne_nisar.py` consumes a saved maturity-specific CMR
inventory. Without `--execute`, it reports the selected product count, total
CMR-reported bytes, available target space, and the destination without
transferring data. The default PROVISIONAL inventory is the charter's primary
T042/F069 and T034/F021 subset; choose the full AOI inventory explicitly with
`--inventory data/inventories/tuolumne_nisar_provisional_all.json`. BETA uses
its separate catalog. `--max-products 1` supports a one-product initial run.

The transfer keeps resumable `.part` files, verifies final size and CMR MD5,
then runs the raw GUNW validator. The main granule HDF5 is downloaded; the
separate QA statistics sidecar is not treated as a GUNW. Completed products,
checksums, validation report paths, and failures are recorded in a local
`download_manifest.json` under the maturity-specific download root. Raw products
and reports remain outside Git. Configure Earthdata Login in the local
`.netrc`; never put credentials in command-line arguments or repository files.

## Daily CDEC station SWE

`scripts/io/download_tuolumne_cdec.py` requests CDEC daily sensor 3 for all
eight station IDs in the tracked station metadata table. The 2026-09-28 snapshot
queries 2025-10-01 through 2026-09-28 inclusive. Seven stations returned 363
daily records each; TES returned no rows. Non-numeric values such as CDEC's
`---` sentinel remain blank in `swe_cm`, and source flags are retained without
filtering. Numeric source values reported in inches are converted to centimetres
by multiplying by 2.54, matching the existing project series. No temporal
interpolation or zero filling is performed.

The raw response and normalized table are stored under the ignored
`data/external/cdec/tuolumne/` directory. The tracked inventory snapshot
`data/inventories/tuolumne_cdec_2025-10-01_to_2026-09-28.json` records endpoint,
query bounds, checksums, row coverage, and each station's last numeric date.
This is an observation inventory, not a reference-station selection policy.

## VIIRS daily snow cover

`data/inventories/tuolumne_viirs_2025-11-01_to_2026-09-21.json` records the
NASA NSIDC VJ110A1F version 002 h08v05 granules selected for the unique endpoint
dates in the two NISAR frame catalogs, including CMR identity/revision, URLs,
local sizes, and SHA-256 checksums. The inventory selects 51 products for 51
unique dates. Raw HDF5 files are under the ignored
`data/external/viirs/tuolumne/vj110a1f_v002/raw/` directory.

Refresh the catalog and download missing files with Earthdata Login credentials
available through `earthaccess`:

```bash
python scripts/io/download_tuolumne_viirs.py
```

The retrieval baseline converts scaled NDSI to fSCA, bilinearly reprojects the
continuous field to each 80 m NISAR grid, then reports fSCA > 0 and fSCA ≥ 0.50
coverage as separate downstream evaluation diagnostics. These masks do not filter
the NISAR retrieval; no VIIRS QA filter is applied in this baseline. See
[Tuolumne Retrieval Baseline](TUOLUMNE_RETRIEVAL_BASELINE.md).

## Current ASO metadata limits

The three basin SWE rasters are identified by package reports that name the
exact SWE input and report mean SWE units. Snow-depth rasters expose no unit in
their raster metadata; accompanying package reports report mean depth in metres
but do not link that value to each exact depth raster, so the inventory leaves
their `units` field blank and records that evidence separately. No raster was
identified by a filename or GeoTIFF tag as an uncertainty or quality layer;
albedo rasters remain labeled as albedo, not quality. ASO package terms include
restrictions, so obtain provider clearance before sharing inventory details
outside the authorized project context.

## Source documentation

- [NASA CMR Search API](https://cmr.earthdata.nasa.gov/search/site/docs/search/api.html)
  documents collection-constrained granule search, spatial/temporal filters, and
  search-after pagination.
- [ASF NISAR GUNW guide](https://nisar-docs.asf.alaska.edu/gunw/) describes the
  GUNW layers inventoried by the raw-product validator.
- [California Snow Data](https://www.lab.data.ca.gov/dataset/california-snow-data)
  is the California Department of Water Resources CDEC dataset guide; it
  identifies sensor 3 as raw daily snow water equivalent.
