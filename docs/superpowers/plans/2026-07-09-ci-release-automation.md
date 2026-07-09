# CI + Release Automation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add GitHub Actions for test CI, automated version bumps + changelog (release-please), and OIDC trusted publishing to PyPI.

**Architecture:** Three additions — `ci.yml` (test matrix on push/PR), a `release-please.yml` with two jobs (release-please maintains a release PR / cuts releases; a gated publish job builds with Poetry and uploads via OIDC), and the release-please config+manifest that track the current version. No application code changes.

**Tech Stack:** GitHub Actions, `googleapis/release-please-action@v4` (`release-type: python`), `pypa/gh-action-pypi-publish@release/v1` (trusted publishing), Poetry, Python 3.11–3.14.

## Global Constraints

- These are config/YAML/JSON files — no application code changes. Existing local gates (`poetry run pytest`, `mypy`, `ruff`) must remain green but are not the deliverable; the deliverable is valid, correct workflow/config files.
- Distribution name is `bioexperiment-lab-devices`; import package stays `lab_devices`. Version lives ONLY in `pyproject.toml [project].version` (currently `0.1.0`).
- Repo slug: `bioexperiment-lab-devices/lab-devices`.
- Single release+publish workflow file, exact filename `release-please.yml` (this name is registered as the PyPI trusted publisher — do not rename it).
- Publish job GitHub Environment name: exactly `pypi`.
- CI Python matrix: exactly `["3.11", "3.12", "3.13", "3.14"]`.
- release-please uses `${{ secrets.GITHUB_TOKEN }}` (no PAT).
- Pin action major versions as written (`@v4`, `@v5`, `@release/v1`).
- YAML indentation is 2 spaces; files end with a trailing newline.

---

## File Structure

- `.github/workflows/ci.yml` — Create: test matrix (pytest/mypy/ruff) on push + PR.
- `.github/workflows/release-please.yml` — Create: release-please job + gated OIDC publish job.
- `release-please-config.json` — Create: release-please package config.
- `.release-please-manifest.json` — Create: current version manifest (`0.1.0`).
- `pyproject.toml` — Modify: add the `Python :: 3.14` classifier.
- `README.md` — Modify: add CI + PyPI badges.

**Validation tooling:** JSON via `python3 -m json.tool` (stdlib). Workflow YAML via `actionlint` (install once with `brew install actionlint`; Homebrew is at `/opt/homebrew`). If `actionlint` cannot be installed, fall back to a YAML parse: `pipx run --spec pyyaml python -c "..."` is unreliable, so instead use `python3 -c "import yaml,sys; yaml.safe_load(open(sys.argv[1]))"` only if `python3 -c "import yaml"` succeeds; otherwise note that syntax will be verified by the live PR run.

---

### Task 1: CI test workflow + 3.14 classifier

**Files:**
- Create: `.github/workflows/ci.yml`
- Modify: `pyproject.toml` (classifiers list)

**Interfaces:**
- Consumes: existing `poetry.lock`, `[project.optional-dependencies].dev`, and tool configs in `pyproject.toml`.
- Produces: a CI workflow that will run live on the implementation PR across Python 3.11–3.14.

- [ ] **Step 1: Create `.github/workflows/ci.yml`**

```yaml
name: CI

on:
  push:
  pull_request:

concurrency:
  group: ci-${{ github.ref }}
  cancel-in-progress: true

jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      fail-fast: false
      matrix:
        python-version: ["3.11", "3.12", "3.13", "3.14"]
    steps:
      - uses: actions/checkout@v4
      - name: Install Poetry
        run: pipx install poetry
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python-version }}
          cache: poetry
      - name: Install dependencies
        run: poetry install --all-extras
      - name: Run tests
        run: poetry run pytest
      - name: Type check
        run: poetry run mypy
      - name: Lint
        run: poetry run ruff check .
```

- [ ] **Step 2: Add the 3.14 classifier**

In `pyproject.toml`, in the `classifiers = [ ... ]` list, add this line immediately after the `"Programming Language :: Python :: 3.13",` entry:

```toml
    "Programming Language :: Python :: 3.14",
```

- [ ] **Step 3: Validate the workflow YAML and pyproject**

Run: `command -v actionlint >/dev/null || brew install actionlint; actionlint .github/workflows/ci.yml`
Expected: no output (no lint errors). If `brew install` is unavailable, instead confirm YAML parses (see Validation tooling note) and rely on the live PR run.

Run: `poetry check`
Expected: `All set!` (classifier addition keeps pyproject valid).

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/ci.yml pyproject.toml
git commit -m "ci: add test matrix workflow (py3.11-3.14) and 3.14 classifier"
```

---

### Task 2: release-please + OIDC publish

**Files:**
- Create: `release-please-config.json`
- Create: `.release-please-manifest.json`
- Create: `.github/workflows/release-please.yml`

**Interfaces:**
- Consumes: `pyproject.toml [project].version = "0.1.0"` (release-please bumps it); the PyPI trusted-publisher registration (owner `bioexperiment-lab-devices`, repo `lab-devices`, workflow `release-please.yml`, environment `pypi`).
- Produces: on push to `main`, a maintained release PR; on its merge, a GitHub Release + `vX.Y.Z` tag and an OIDC publish of `dist/*` to PyPI.

- [ ] **Step 1: Create `release-please-config.json`**

```json
{
  "$schema": "https://raw.githubusercontent.com/googleapis/release-please/main/schemas/config.json",
  "packages": {
    ".": {
      "release-type": "python"
    }
  }
}
```

- [ ] **Step 2: Create `.release-please-manifest.json`**

```json
{
  ".": "0.1.0"
}
```

- [ ] **Step 3: Create `.github/workflows/release-please.yml`**

```yaml
name: release-please

on:
  push:
    branches:
      - main

permissions: {}

jobs:
  release-please:
    runs-on: ubuntu-latest
    permissions:
      contents: write
      pull-requests: write
    outputs:
      release_created: ${{ steps.release.outputs.release_created }}
      tag_name: ${{ steps.release.outputs.tag_name }}
    steps:
      - uses: googleapis/release-please-action@v4
        id: release
        with:
          token: ${{ secrets.GITHUB_TOKEN }}
          config-file: release-please-config.json
          manifest-file: .release-please-manifest.json

  publish:
    needs: release-please
    if: ${{ needs.release-please.outputs.release_created == 'true' }}
    runs-on: ubuntu-latest
    environment: pypi
    permissions:
      id-token: write
    steps:
      - uses: actions/checkout@v4
      - name: Install Poetry
        run: pipx install poetry
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - name: Build distributions
        run: poetry build
      - name: Publish to PyPI
        uses: pypa/gh-action-pypi-publish@release/v1
```

- [ ] **Step 4: Validate JSON and workflow YAML**

Run: `python3 -m json.tool < release-please-config.json >/dev/null && python3 -m json.tool < .release-please-manifest.json >/dev/null && echo "JSON OK"`
Expected: `JSON OK`.

Run: `command -v actionlint >/dev/null || brew install actionlint; actionlint .github/workflows/release-please.yml`
Expected: no output (no lint errors). If actionlint is unavailable, confirm YAML parses per the Validation tooling note and rely on the live run.

- [ ] **Step 5: Commit**

```bash
git add release-please-config.json .release-please-manifest.json .github/workflows/release-please.yml
git commit -m "ci: add release-please + OIDC trusted publishing to PyPI"
```

---

### Task 3: README badges

**Files:**
- Modify: `README.md`

**Interfaces:**
- Consumes: the CI workflow name (`CI`) and the PyPI project `bioexperiment-lab-devices`.
- Produces: build-status and PyPI-version badges on the README (which is also the PyPI long description).

- [ ] **Step 1: Add badges under the title**

In `README.md`, immediately after the first line (`# lab_devices`) and its following blank line, insert these two badge lines followed by a blank line, so they sit above the "Async Python library…" description:

```markdown
[![CI](https://github.com/bioexperiment-lab-devices/lab-devices/actions/workflows/ci.yml/badge.svg)](https://github.com/bioexperiment-lab-devices/lab-devices/actions/workflows/ci.yml)
[![PyPI version](https://img.shields.io/pypi/v/bioexperiment-lab-devices.svg)](https://pypi.org/project/bioexperiment-lab-devices/)
```

- [ ] **Step 2: Validate README still renders as valid package metadata**

Run: `poetry build && pipx run twine check dist/*`
Expected: `PASSED` for both artifacts (confirms the README long-description still passes PyPI's checks with the badge markup).

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: add CI and PyPI badges to README"
```

---

## Self-Review

**Spec coverage:**
- `ci.yml` matrix 3.11–3.14 + 3.14 classifier → Task 1. ✅
- release-please config + manifest → Task 2 Steps 1–2. ✅
- Single `release-please.yml`, release job (GITHUB_TOKEN) + gated publish job (environment `pypi`, `id-token: write`, OIDC, no password) → Task 2 Step 3. ✅
- README badges → Task 3. ✅
- PyPI trusted-publisher registration → operational prerequisite documented in the spec; called out in Task 2 Interfaces. It is a user/interactive step on pypi.org (not a repo file), so it has no code task; the controller must remind the user before the first release.

**Placeholder scan:** No TBD/TODO; every file's full content is given verbatim.

**Type/consistency check:** Workflow filename `release-please.yml`, environment `pypi`, matrix `["3.11","3.12","3.13","3.14"]`, manifest version `0.1.0`, repo slug `bioexperiment-lab-devices/lab-devices`, and distribution name `bioexperiment-lab-devices` are used consistently across all tasks and match the Global Constraints. The publish job intentionally omits a `password:` input so `gh-action-pypi-publish` uses OIDC.

**Note for executor:** all implementation happens on a feature branch off `main`; opening the PR runs `ci.yml` live across the four Python versions — that green run is the primary acceptance check. Do not merge until CI is green. Remind the user to register the PyPI trusted publisher before the first automated release is merged.
