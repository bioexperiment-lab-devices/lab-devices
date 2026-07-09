# Design: CI + release-please + PyPI trusted publishing

**Date:** 2026-07-09
**Status:** Approved (design)

## Goal

Add GitHub Actions automation to `bioexperiment-lab-devices`: run the test gates on
every push/PR, automate version bumps + changelog via release-please, and publish new
releases to PyPI using OIDC trusted publishing (no long-lived token).

## Context

- Repo: `github.com/bioexperiment-lab-devices/lab-devices`. No `.github/` yet.
- Commits already follow Conventional Commits (`feat:`, `fix:`, `docs:`, `build:`,
  `refactor:`, `test:`, with scopes) — release-please can parse them.
- Distribution name `bioexperiment-lab-devices`; import package `lab_devices`.
- Version lives ONLY in `pyproject.toml [project].version` (currently `0.1.0`);
  `__version__` is derived at runtime from `importlib.metadata`, so release-please only
  needs to bump the one pyproject field. No `CHANGELOG.md` yet.
- Build backend: `poetry-core`; local Poetry 2.4.1. Dev deps are a PEP 621 extra
  (`.[dev]`), installed via `poetry install --all-extras`.
- `0.1.0` was already published to PyPI via twine; this automation governs `0.1.1+`.

## Decisions

- **Single workflow, gated publish job** (not two separate workflows).
- **CI matrix Python 3.11 / 3.12 / 3.13 / 3.14**; add the `3.14` classifier to pyproject
  so declared metadata matches what CI proves.
- release-please uses `GITHUB_TOKEN` (not a PAT); accept that the release PR itself does
  not trigger CI (it only bumps version + changelog).
- GitHub Environment name for publishing: `pypi`.

## Components

### 1. `.github/workflows/ci.yml`

- **Triggers:** `push` and `pull_request`.
- **Concurrency:** group by workflow + ref, `cancel-in-progress: true`.
- **Job `test`:** `runs-on: ubuntu-latest`, `strategy.matrix.python-version: ["3.11", "3.12", "3.13", "3.14"]`, `fail-fast: false`.
  - Steps: `actions/checkout@v4` → `pipx install poetry` → `actions/setup-python@v5`
    with the matrix version → `poetry install --all-extras` → `poetry run pytest` →
    `poetry run mypy` → `poetry run ruff check .`.

### 2. `.github/workflows/release-please.yml`

- **Trigger:** `push` to `main`.
- **Top-level `permissions`:** minimal; jobs elevate what they need.
- **Job `release-please`:**
  - `permissions: contents: write, pull-requests: write`.
  - Uses `googleapis/release-please-action@v4` with `token: ${{ secrets.GITHUB_TOKEN }}`,
    config-file `release-please-config.json`, manifest-file `.release-please-manifest.json`.
  - Exposes outputs `release_created` and `tag_name`.
- **Job `publish`:**
  - `needs: release-please`; `if: ${{ needs.release-please.outputs.release_created == 'true' }}`.
  - `runs-on: ubuntu-latest`; `environment: pypi`; `permissions: id-token: write`.
  - Steps: `actions/checkout@v4` → `pipx install poetry` → `actions/setup-python@v5`
    (single version, e.g. 3.12) → `poetry build` → `pypa/gh-action-pypi-publish@release/v1`
    (no `password:` — OIDC). Uploads `dist/*`.

### 3. release-please config files

- `release-please-config.json`:
  ```json
  {
    "$schema": "https://raw.githubusercontent.com/googleapis/release-please/main/schemas/config.json",
    "packages": { ".": { "release-type": "python" } }
  }
  ```
- `.release-please-manifest.json`:
  ```json
  { ".": "0.1.0" }
  ```
  The manifest states the current published version so the next `feat:` → `0.2.0` and the
  next `fix:` → `0.1.1`.

### 4. `pyproject.toml`

- Add `"Programming Language :: Python :: 3.14"` to `classifiers`.

### 5. `README.md`

- Add CI status and PyPI version badges near the top.

## PyPI prerequisite (user, interactive)

Before the first automated release, register the trusted publisher on pypi.org for the
`bioexperiment-lab-devices` project → *Settings → Publishing → Add a GitHub publisher*:

| Field | Value |
|-------|-------|
| Owner | `bioexperiment-lab-devices` |
| Repository name | `lab-devices` |
| Workflow name | `release-please.yml` |
| Environment name | `pypi` |

Without this, the `publish` job fails at upload. The GitHub Environment `pypi` is created
by referencing it in the workflow (optionally add protection rules later).

## Verification

- **CI:** opening the implementation PR runs `ci.yml` across all four Python versions —
  they must go green. This is the primary end-to-end check of this work.
- **release-please:** validated structurally (config + manifest well-formed, workflow
  parses). First real exercise is the next merged `feat:`/`fix:` commit, which should make
  release-please open a release PR bumping the version + writing `CHANGELOG.md`.
- **Trusted publishing:** cannot be fully dry-run (OIDC needs a real release). Correctness
  rests on the four registration values above matching the workflow.

## Out of scope

- Publishing a new version as part of this work (no code changes warranting a release).
- Signing/attestations beyond what `gh-action-pypi-publish` provides by default.
- CI caching optimization, PAT-based release PRs, branch protection rules.
