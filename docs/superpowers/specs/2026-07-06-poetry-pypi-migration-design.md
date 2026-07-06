# Design: Migrate `lab-devices` to Poetry and publish to PyPI

**Date:** 2026-07-06
**Status:** Approved (design)

## Goal

Switch the `lab-devices` package's build tooling from Hatchling to Poetry (2.4.1),
and publish it to PyPI — validating on TestPyPI first.

## Decisions

- **Format:** Keep the PEP 621 `[project]` table. Poetry 2.x supports it natively, so
  metadata and dependencies stay standard; Poetry is used as the build backend +
  dependency/publish tooling. Minimal churn.
- **Publish scope:** TestPyPI first, then real PyPI, with an explicit confirmation gate
  before the irreversible real-PyPI upload.
- **License:** MIT. Add a `LICENSE` file (copyright 2026 khamitovdr).
- **Author metadata:** `khamitovdr <khamitov.personal@gmail.com>` (git identity; email
  will be publicly visible on PyPI).
- **Version source:** `src/lab_devices/__init__.py` will read `__version__` from
  `importlib.metadata` instead of hardcoding it, eliminating duplication with
  `[project].version`.
- **Accounts:** User has both a PyPI account+token and a TestPyPI account+token
  (TestPyPI is a separate registration).

## Changes

### 1. `pyproject.toml`

**Build system** — replace Hatchling:

```toml
[build-system]
requires = ["poetry-core>=2.0"]
build-backend = "poetry.core.masonry.api"
```

**`[project]` table** — keep existing fields, enrich for PyPI:
- `readme = "README.md"`
- `license = "MIT"` (SPDX expression, PEP 639)
- `license-files = ["LICENSE"]`
- `authors = [{ name = "khamitovdr", email = "khamitov.personal@gmail.com" }]`
- `keywords = ["lab", "automation", "devices", "async", "httpx"]`
- `classifiers`: Development Status :: 3 - Alpha; Intended Audience :: Science/Research;
  Programming Language :: Python :: 3 / 3.11 / 3.12 / 3.13; Framework :: AsyncIO;
  Typing :: Typed. (Omit the `License ::` classifier — the SPDX `license` field is the
  modern, non-conflicting source of truth under PEP 639.)
- `dependencies` and `[project.optional-dependencies].dev` unchanged.

**`[project.urls]`** — new:
- Homepage / Repository / Issues → `https://github.com/bioexperiment-lab-devices/lab-devices`

**`[tool.poetry]`** — new, only the src-layout package mapping Poetry needs:

```toml
[tool.poetry]
packages = [{ include = "lab_devices", from = "src" }]
```

**Remove** the `[tool.hatch.build.targets.wheel]` section. Keep
`[tool.pytest.ini_options]`, `[tool.mypy]`, `[tool.ruff]` unchanged.

### 2. `LICENSE`

Standard MIT license text, copyright `2026 khamitovdr`.

### 3. `src/lab_devices/__init__.py`

Replace `__version__ = "0.1.0"` with a lookup:

```python
from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("lab-devices")
except PackageNotFoundError:  # not installed (e.g. running from a source tree)
    __version__ = "0.0.0.dev0"
```

Keep `__version__` in `__all__` if it is currently exported.

### 4. `poetry.lock`

Generate via `poetry lock` and commit it for reproducible dev environments.

### 5. `README.md`

Update the Development section to prefer `poetry install`. Note the editable
`pip install -e ".[dev]"` path still works.

## Verification

1. `poetry install` succeeds.
2. Existing gates stay green: `poetry run pytest`, `poetry run mypy`, `poetry run ruff check .`.
3. `python -c "import lab_devices; print(lab_devices.__version__)"` prints `0.1.0`
   after install (proving the importlib lookup resolves).
4. `poetry build` produces sdist + wheel; wheel contains `lab_devices/py.typed` and
   correct metadata (name, version, license, README as long description).

## Publish workflow

Tokens are secrets — the user runs the `poetry config pypi-token.*` commands themselves
(via the `!` prefix or env vars) so tokens never appear in the assistant transcript.

1. `poetry config repositories.testpypi https://test.pypi.org/legacy/`
2. User configures TestPyPI token.
3. `poetry publish -r testpypi` (build artifacts already present, or `poetry publish --build -r testpypi`).
4. Verify clean install from TestPyPI in a throwaway venv:
   `pip install --index-url https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple/ lab-devices`
   then import and check `__version__`.
5. **Gate:** explicit user go-ahead.
6. User configures PyPI token; `poetry publish` to real PyPI.
7. Confirm the package page renders at `https://pypi.org/project/lab-devices/`.

## Out of scope

- CI/CD automation of releases (GitHub Actions / trusted publishing).
- Version bumping beyond the current 0.1.0.
- Any change to library behavior or public API.
