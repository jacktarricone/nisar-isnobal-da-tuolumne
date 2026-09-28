# Repository Guidelines

## Project Structure & Module Organization

See `docs/PROJECT_CHARTER.md` for the project design and `docs/` for its concise operational contracts. The Python package uses the `src/nisar_isnobal_da/` layout; the current package is only a scaffold. The initial smoke test is under `tests/unit/`. Future code may add focused modules, scripts, configurations, and tests as their project stages begin. Store only manifests, inventories, compact provenance, frozen configuration, and small fixtures in Git; raw and derived datasets belong outside version control (`data/raw/`, `data/external/`, and `data/derived/` are ignored).

## Build, Test, and Development Commands

Use Python 3.12. From the repository root, create and activate an environment with `python3.12 -m venv .venv` and `source .venv/bin/activate`, then install the development package with `python -m pip install -e ".[dev]"`. Run `ruff check .`, `ruff format --check .`, and `pytest`. Use `git status --short` to review changes and `rg --files` to inspect project content.

## Coding Style & Naming Conventions

Use Python for package and workflow code. Follow standard Python naming: `snake_case` for modules, functions, and variables; `PascalCase` for classes; descriptive experiment IDs such as `N0` and `ASO-DA` as defined in the charter. Ruff enforces the configured E, F, and I rules and formatting. Keep scientific choices explicit in configuration and provenance. Future modules should follow the planned boundaries: observations, model, assimilation, uncertainty, evaluation, experiments, and I/O.

## Scientific and Data Contracts

Preserve the charter’s observation meaning: `dSWE = SWE(secondary) - SWE(reference)`, with directed reference-to-secondary pairs. Missing support is missing data, never zero change. Record units, CRS, resampling, processing maturity, and provenance. Do not silently apply correction layers or reinterpret raw GUNW paths in the assimilation layer. Every state update must yield a physically admissible coupled iSnobal restart state; do not change SWE while leaving related state inconsistent.

## Testing Guidelines

Put tests under the corresponding `tests/` subdirectory and use `test_*.py` names. The current package-import smoke test checks scaffolding only. As scientific code is added, cover its stated invariants as well as outputs; keep fixtures small and synthetic, and never commit large scientific data products.

## Commit & Pull Request Guidelines

The Git history currently contains only the initial charter commit, so no established message convention can be inferred. Write concise, imperative commit subjects (for example, `Add ASO inventory schema`). Pull requests should explain the scientific or workflow change, identify affected contracts/configuration, summarize validation performed, and link relevant issues or evidence.
