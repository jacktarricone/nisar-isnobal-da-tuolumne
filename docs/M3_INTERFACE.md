# M3 Model Interface

**Status:** Proposed capabilities and questions from the charter; no interface, exchange format, or model adapter has been agreed or implemented.

## Boundary

The repository owns experiment definitions and exchange contracts, not the proprietary production iSnobal implementation (charter §15). Any future assimilation method must produce a physically admissible coupled restart state; changing SWE alone while leaving related state inconsistent is prohibited by the charter's model-state constraint (§4).

## Capabilities to resolve

The charter §16 proposes that the model-side exchange provide:

```text
model_grid
state(time)
restart_state(time)
forcing(time)
forecast_forcing(issue_time, lead)
run(start, end, restart_state)
```

Candidate state fields include SWE/specific mass, depth, density, surface and lower-layer temperatures, mean temperature if required, cold content, liquid water, and restart-required layer masses/depths. Candidate diagnostics include SWE, depth, density, melt, SWI, selected energy terms, and state-validity or model-failure flags. These lists are proposed minimums to discuss, not a finalized schema.

## Unresolved M3 questions

The charter §20 identifies the following questions; no answers are assumed here:

1. Which complete restart variables can M3 export and re-ingest at arbitrary analysis times?
2. Can state snapshots be archived at each NISAR acquisition epoch?
3. Are historical forecast forcings available as issued, or only retrospective/reanalysis forcings?
4. Which ASO state-update methods are used operationally, and what can be described publicly?
5. Can model input/output use a stable NetCDF, Zarr, or xarray-compatible exchange contract?
6. What grid and resolution does the production model use for Tuolumne?
7. Can controlled reruns avoid changing unrelated operational tuning?
8. Which state variables are mandatory for restart?
9. What is the current SWI diagnostic and its time aggregation?
10. Which model and forcing versions should be frozen for the manuscript baseline?

Question 3 determines whether a future study can support an operational-forecast claim or only retrospective state-estimation/free-evolution claims (charter §20).
