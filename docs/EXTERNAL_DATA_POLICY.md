# External Data Policy

**Status:** Repository handling policy derived from charter §§7–9 and 18. Stage 1 catalogs metadata only and does not download raw products.

## What belongs in Git

Raw NISAR, ASO, terrain, and large model products remain external. The repository may contain manifests, compact inventories and provenance, frozen configuration, tiny test fixtures, and appropriate final summary tables (charter §18). The existing `.gitignore` excludes raw/external/derived data directories, large scientific raster/container files, and generated outputs; do not override those exclusions to add source data.

Preserve source products unchanged. Record metadata, checksum, source location, product identity/maturity, units, CRS, resolution, processing choices, and study/independence role as applicable. Verify metadata rather than inferring it from filenames or directory names (charter §§7, 10, 18).

## Credentials and product provenance

Credentials must never be stored in repository files or committed command history. The charter suggests Earthdata Login `.netrc` or another standard ASF/earthaccess mechanism; keep credentials in the user's private environment (charter §9.6).

Keep BETA, PROVISIONAL, and future VALIDATED holdings and analysis outputs distinguishable. Do not silently replace one maturity or processing version with another. Archive counts in the charter are dated provenance snapshots: future availability must be established from current catalog metadata, not inferred from cadence or a fixed release-date cutoff (charter §8). Stage 1's separate CMR snapshots preserve the query time, collection concepts, full granule metadata, processing CRID, product version, and collection version.

ASO package materials include provider terms. Inventory files record metadata and checksums only; confirm the permitted scope for external sharing before publishing those records.
