# Scientific Contract

**Status:** Project framing and hypotheses from the charter; hypotheses are not findings.

## Purpose and scope

Evaluate whether NISAR L-band InSAR observations of snow water equivalent change (ΔSWE) can improve spatially distributed iSnobal snow-state estimates and forecast-relevant outputs in the Tuolumne River Basin, without injecting retrieval errors into the model. The intended result is a scientific evaluation and a practical NISAR snow data-assimilation playbook. See charter §§1–2 and §24.

The Tuolumne work is downstream of, and complementary to, the Colorado / East River Basin retrieval-validation work. It uses SnowIn's reusable retrieval and observation conventions; it does not redefine the funded THP retrieval and validation deliverables. The repository owns the experiment and observation/model exchange contracts, not M3's proprietary production model. See charter §§1–2 and §15.

## Project hypotheses

These are proposed claims to evaluate, not established conclusions. See charter §5.

- **H1 — State-estimation value:** Supported NISAR ΔSWE assimilation will reduce independently evaluated snow-state error relative to open-loop iSnobal.
- **H2 — Observation scale:** Native-pixel and spatially aggregated observations may produce different results where errors are spatially correlated.
- **H3 — Quality-aware assimilation:** Using observation support and uncertainty may outperform equal weighting, especially under retrieval failure modes described in the charter.
- **H4 — State reconciliation:** How an increment is reconciled with iSnobal's coupled state may affect subsequent model trajectories.
- **H5 — Forecast persistence:** Improvement at the analysis time may decay with lead time and does not by itself establish forecast benefit.
- **H6 — Increment assimilation:** Assimilating pairwise ΔSWE may rely less on absolute-state assumptions than accumulating it into absolute SWE, where a defensible comparison is available.

The experiment sequence, evaluation questions, and metrics are in [Experiment Design](EXPERIMENT_DESIGN.md). Observation sign, pair direction, and support conventions are fixed separately in [Data Contracts](DATA_CONTRACTS.md).
