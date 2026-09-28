# Experiment Design

**Status:** Planned research comparisons only. No experiment or assimilation method is implemented by this document.

## Planned experiment sequence

The IDs and purposes below follow charter §6. The sequence is staged; the charter explicitly advises against starting with a full ensemble implementation.

| ID | Planned comparison | Question |
| --- | --- | --- |
| `CTRL` | Open-loop iSnobal | What is the frozen no-NISAR baseline? |
| `ASO-DA` | Existing or standard ASO-assisted workflow | What is the remote-sensing assimilation benchmark? |
| `N0` | Deterministic NISAR ΔSWE update | Does NISAR contain useful corrective information? |
| `N1` | Native versus aggregated support | What spatial scale is useful? |
| `N2` | Quality- or uncertainty-aware update | How should support and uncertainty affect use? |
| `N3` | Pair-common/reference-error treatment | How should common-mode and local error be distinguished? |
| `N4` | Alternative state-reconciliation methods | How should a ΔSWE increment affect the coupled state? |
| `N5` | Ensemble / uncertainty-propagating DA | How does uncertainty propagate after simpler methods are understood? |
| `OPS` | Retrospective operational replay | Does an update add forecast value using information available at issue time? |

## Evaluation plan

Keep three questions distinct (charter §14):

1. **Analysis state:** Does the state improve immediately after an update?
2. **Free evolution:** How long does an improvement persist without another update?
3. **Forecast:** Does an assimilated state improve a forecast initialized at that time?

The charter lists spatial RMSE, MAE, bias, correlation, regression slope, basin SWE volume, elevation-stratified error, spatial-support fraction, snow disappearance and melt timing, SWI, and forecast skill by lead time as candidate metrics. Report accuracy together with retained coverage. First-analysis questions are listed in charter §22.

## Future research decisions

The charter leaves these open for later evidence and collaborator input; this document does not choose among them:

- Spatial support and aggregation scales (charter §13).
- Observation-error representation and predictors (charter §12).
- Pair-common error treatment and quality-based weighting or rejection (charter §§5–6, 12).
- Physically admissible state-reconciliation methods (charter §§4–5).
- Whether historical forecast forcings are available as issued, which affects operational-forecast claims (charter §20).
- How to preserve independent evaluation when ASO information is used to tune methods (charter §7).
