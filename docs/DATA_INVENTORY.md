# Stage 1 Data Inventory

This document describes the metadata-only Stage 1 workflow. It follows charter
§§7–10 and §18. It does not choose retrieval inputs, quality thresholds,
correction layers, resampling, or assimilation roles.

## Inventory outputs

- `data/inventories/tuolumne_aso.csv` records every file in the three chartered
  ASO packages, including file path, size, SHA-256, raster CRS, transform,
  resolution, dimensions, nodata, bounds, tags, and source evidence for units.
- `data/inventories/tuolumne_aso_aoi.geojson` is the union of the source SWE
  rasters' rectangular footprints transformed to EPSG:4326. It is a catalog
  search geometry, not a basin boundary.
- `data/inventories/tuolumne_nisar_beta.json` and
  `data/inventories/tuolumne_nisar_provisional_all.json` are independent CMR
  snapshots. Each records query time, temporal bounds, all matching collection
  versions, granule metadata, CMR-provided file checksums/sizes, and catalog
  links. The query begins `2025-10-01` and ends at its recorded UTC timestamp.
- `data/inventories/tuolumne_nisar_provisional_primary_frames.json` is a metadata
  subset for T042/F069 and T034/F021 when CMR explicitly supplies track and frame
  attributes. It retains the same maturity and version fields as the full
  PROVISIONAL snapshot.
- `data/manifests/external_data_manifest.csv` combines ASO file records and both
  NISAR catalog snapshots. A CMR checksum in this manifest is provider-reported
  and is not a local checksum until a file is validated.

Refresh ASO metadata and the spatial search geometry first, then query CMR and
rebuild the manifest:

```bash
python scripts/io/inventory_aso.py \
  --aso-root "/Users/jtarrico/ch13_nisar_prelim/data/rasters/aso/ca/tuo"
python scripts/io/inventory_nisar.py
python scripts/io/build_external_manifest.py
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

No GUNW was downloaded for Stage 1, so the validator is not yet exercised
against a real product. Metadata absent from CMR remains blank or is reported as
unresolved; this workflow does not infer product CRS, raster resolution, or
wavelength from nominal product descriptions.

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
