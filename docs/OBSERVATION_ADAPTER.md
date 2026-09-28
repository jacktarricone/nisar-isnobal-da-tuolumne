# SnowIn Observation Adapter

**Status:** Stage 2 boundary implemented; complete DA readiness requires all charter fields. Retrieval choices and model-state updates remain out of scope.

## Input and output

`nisar_isnobal_da.observations.adapt_snowin_observation()` accepts an
already processed SnowIn `xarray.Dataset` containing pairwise `dswe`. It
returns a shallow, xarray-native Dataset with the same scientific variables,
coordinates, and values, plus explicit catalog processing identity:
`processing_maturity`, `processing_crid`, `processing_product_version`, and
`processing_collection_version`. These fields remain separate. SnowIn is not a
runtime dependency; the adapter accepts its xarray contract and does not read
raw GUNW files.

SnowIn returns dSWE as an `xarray.DataArray`; attach it to the processed pair
before adapting:

```python
observation = adapt_snowin_observation(
    pair.assign(dswe=dswe),
    processing_maturity="PROVISIONAL",
    processing_crid="P05023",
    processing_product_version="<catalog value>",
    processing_collection_version="<catalog value>",
)
```

The adapter requires canonical phase meaning, directed pair metadata, UTC
acquisition times, wavelength, source phase convention and transform, source
granule ID, `dswe` units/quantity/retrieval method, and explicit grid mapping
and CRS metadata. The reference method must be present in the input provenance
or supplied explicitly. Validation does not compare the acquisition times or
change phase or dSWE values.

If `pairwise_supported` is present, the adapter preserves it and exposes the
same layer as `observation_support`; it does not combine it with other support
layers. Supplied uncertainty variables are passed through unchanged, without
assuming their spatial shape. Absent support and uncertainty remain absent.
The current SnowIn pairwise dSWE output
does not itself provide the charter's three uncertainty fields;
`validate_da_observation()` reports them (and any other missing §11 fields)
without manufacturing values. A SnowIn result therefore may be a valid
project-boundary observation while still being incomplete for DA.

## Decision boundaries

- **Fixed conventions:** phase and dSWE use secondary-minus-reference; the
  temporal edge is reference-to-secondary; pairwise dSWE is not absolute SWE;
  missing support is not zero. See charter §§3 and 11.
- **Project hypotheses:** H1–H6 remain hypotheses, not adapter behavior or
  results. See charter §5 and [Scientific Contract](SCIENTIFIC_CONTRACT.md).
- **Planned experiments:** CTRL, ASO-DA, N0–N5, and OPS remain plans. See
  charter §6 and [Experiment Design](EXPERIMENT_DESIGN.md).
- **Unresolved M3 interface:** restart-state completeness, state snapshots,
  forcing availability, grid, and restart variables remain open. See charter
  §§16 and 20 and [M3 Interface](M3_INTERFACE.md).
- **Future research decisions:** retrieval method selection, observation
  uncertainty construction, support policies, and all model-state update
  methods remain outside this adapter. No M3 state update is implemented.
