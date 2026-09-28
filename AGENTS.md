# Repository Guidelines

## Project Structure & Module Organization

This repository is at its foundation stage. See `docs/PROJECT_CHARTER.md` for project design; no application package or tests exist yet. The planned layout is `src/nisar_isnobal_da/` for Python modules, `scripts/` for workflows, `config/` for experiment settings, and `tests/` for unit, invariant, and integration checks. Keep design and data contracts in `docs/`. Store only manifests, inventories, compact provenance, frozen configuration, and small fixtures in Git; raw and derived datasets belong outside version control (`data/raw/`, `data/external/`, and `data/derived/` are ignored).

## Build, Test, and Development Commands

There is no build configuration or runnable test suite yet. Use `git status --short` to review changes and `rg --files` to inspect project content. As the Python scaffold is added, follow the charter’s planned tools: `pytest` for tests and `ruff check .` for linting. Document exact setup and run commands when configuration exists.

## Coding Style & Naming Conventions

Use Python for new package and workflow code. Follow standard Python naming: `snake_case` for modules, functions, and variables; `PascalCase` for classes; descriptive experiment IDs such as `N0` and `ASO-DA` as defined in the charter. Keep scientific choices explicit in configuration and provenance. Prefer small, focused modules aligned with the planned boundaries: observations, model, assimilation, uncertainty, evaluation, experiments, and I/O.

## Scientific and Data Contracts

Preserve the charter’s observation meaning: `dSWE = SWE(secondary) - SWE(reference)`, with directed reference-to-secondary pairs. Missing support is missing data, never zero change. Record units, CRS, resampling, processing maturity, and provenance. Do not silently apply correction layers or reinterpret raw GUNW paths in the assimilation layer. Every state update must yield a physically admissible coupled iSnobal restart state; do not change SWE while leaving related state inconsistent.

## Testing Guidelines

When tests are introduced, put them under the corresponding `tests/` subdirectory and use `test_*.py` names. Cover invariants as well as outputs, especially missing-support handling, mass changes, and physical restart-state validity. Keep fixtures small and synthetic; never commit large scientific data products.

## Commit & Pull Request Guidelines

The Git history currently contains only the initial charter commit, so no established message convention can be inferred. Write concise, imperative commit subjects (for example, `Add ASO inventory schema`). Pull requests should explain the scientific or workflow change, identify affected contracts/configuration, summarize validation performed, and link relevant issues or evidence.
