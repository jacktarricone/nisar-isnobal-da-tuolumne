# NISAR–iSnobal Tuolumne Data Assimilation

This project will evaluate how NISAR L-band InSAR snow water equivalent change (ΔSWE) can contribute to iSnobal snow-state estimation and forecast-relevant outputs in the Tuolumne River Basin. It complements the Colorado / East River Basin retrieval-validation effort and relies on SnowIn for reusable NISAR snow-InSAR processing. See the [project charter](docs/PROJECT_CHARTER.md) for full scientific context.

## Project status

The repository is at Stage 2: Stage 1 inventories and read-only GUNW validation are in place, and a SnowIn xarray boundary validates and preserves already processed pairwise dSWE outputs. The adapter does not synthesize missing support or uncertainty, so a complete DA-ready observation still requires those contract fields. It does not implement retrievals, data acquisition, assimilation, or model-state updates. Experiments in the documentation are plans, not results.

## Repository layout

- `src/nisar_isnobal_da/observations/` — Stage 2 SnowIn observation adapter.
- `tests/unit/` — package-import smoke test.
- `docs/` — project charter and operational contracts.
- `scripts/io/` — Stage 1 inventory, manifest, and raw-product validation commands.
- `data/inventories/` — ASO metadata and separate BETA/PROVISIONAL CMR snapshots.
- `data/manifests/` — external-data manifest built from the inventories.
- `.github/workflows/ci.yml` — Python 3.12 lint, format, and test checks.

## Development setup

Use Python 3.12:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
```

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
does not download products. The HDF5 validator can be run on locally held products
and matched to one or more catalog snapshots:

```bash
python scripts/io/validate_nisar_gunw.py /path/to/product.h5 \
  --catalog-json data/inventories/tuolumne_nisar_beta.json \
  --catalog-json data/inventories/tuolumne_nisar_provisional_all.json
```

See [Data inventory workflow](docs/DATA_INVENTORY.md) for recorded fields and
known metadata limits. ASO source package terms must be checked before sharing
inventory details outside the authorized project workspace.

## Project contracts

- [Scientific contract](docs/SCIENTIFIC_CONTRACT.md) — project purpose and hypotheses.
- [Experiment design](docs/EXPERIMENT_DESIGN.md) — planned comparisons and evaluation.
- [Data contracts](docs/DATA_CONTRACTS.md) — fixed observation conventions and data boundaries.
- [SnowIn observation adapter](docs/OBSERVATION_ADAPTER.md) — adapter inputs, validation, provenance, and DA readiness.
- [M3 interface](docs/M3_INTERFACE.md) — proposed model exchange and unresolved questions.
- [External data policy](docs/EXTERNAL_DATA_POLICY.md) — repository data and credential handling.

These concise documents refer to the relevant sections of the [charter](docs/PROJECT_CHARTER.md), which remains the original project design record.

## Data and citation

Raw NISAR, ASO, terrain, and large model products are external to this repository. Do not commit them or credentials. See the external data policy before adding project data. Citation and license metadata remain to be established.
