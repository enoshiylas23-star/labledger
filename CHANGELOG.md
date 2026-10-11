# Changelog

All notable changes to LabLedger are documented here. The format is loosely
based on [Keep a Changelog](https://keepachangelog.com/), and the project aims
to follow [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- Open-source project scaffolding: MIT license, contributing guide, code of
  conduct, changelog, CI workflow, Dockerfile and `.env.example`.
- `tests/` — a dependency-free `unittest` suite that drives the app through
  Flask's test client against a throwaway database.
- JSON API: `GET /healthz`, `GET /api/uvvis` (list) and
  `GET /api/uvvis/<id>` (full machine-readable measurement, including the
  hash-chain tail and links to the HTML / print / CSV views).
- `LABLEDGER_DB` environment variable to relocate the SQLite database.

## [0.2.0]

### Added
- **UV-Vis console rebuilt as a five-tab workspace** (Parameters · Baseline
  setting · System calibration · Quantitation · Active peak pick).
- Quantitation controls: calibration type, weighting (`none` / `1/x` / `1/x²`),
  zero-intercept option, peak height *or* area, report units (`µM` / `mg/L` /
  `ppm`), replicates and unknown count — with a deterministic **live preview**
  before anything is stored.
- **System calibration library** with sparklines, equations, standards and
  one-click *Use in run* / delete.
- **Active peak re-analysis** on saved runs: re-scale absorbances across peaks
  (ε-ratio), refit the working curve and rebuild the chart, without ever
  altering the original PASS/FAIL judgment — the change is appended to the
  hash-chained log.
- Standalone **print report** (`/uvvis/m/<id>/print`) with signature lines and
  the chain-tail hash.

### Fixed
- Endpoint / auto-zero baselines in quantitative mode are derived from a blank
  run, restoring linearity (recovery ≈100%, R² ≥ 0.9995 across all
  weighting × measurement combinations).

## [0.1.0]

- Initial prototype: ledger of published runs, guided record form, cross-lab
  shared ledger, UV-Vis simulator with model-integrity loop, instrument bridge,
  AI analyst and per-project/per-researcher/per-company review bots.
