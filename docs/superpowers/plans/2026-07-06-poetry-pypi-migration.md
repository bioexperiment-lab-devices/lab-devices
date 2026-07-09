# Poetry Migration + PyPI Publish Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Migrate `lab-devices` from Hatchling to Poetry (keeping the PEP 621 `[project]` table), then publish it to PyPI after validating on TestPyPI.

**Architecture:** Swap the build backend to `poetry-core`, enrich `[project]` metadata for a good PyPI listing, add an MIT `LICENSE`, source `__version__` from installed metadata, then build with Poetry and upload with twine (which reads the user's existing `~/.pypirc`).

**Tech Stack:** Poetry 2.4.1, poetry-core, twine, httpx (runtime dep), pytest/mypy/ruff (dev), Python 3.11+.

## Global Constraints

- Keep the PEP 621 `[project]` table as the source of metadata and dependencies; use `[tool.poetry]` only for the src-layout package mapping.
- Build backend: `poetry-core>=2.0`, build-backend `poetry.core.masonry.api`.
- License: `MIT` (SPDX expression), with a `LICENSE` file, copyright `2026 khamitovdr`. Do NOT add a `License ::` classifier (PEP 639: the `license` field is the single source of truth).
- Author metadata: `khamitovdr <khamitov.personal@gmail.com>`.
- `requires-python = ">=3.11"`; runtime dep `httpx>=0.27` unchanged; dev deps unchanged.
- Do not change library behavior or public API. Existing gates must stay green: `pytest`, `mypy` (strict), `ruff check .`.
- Repo: `https://github.com/bioexperiment-lab-devices/lab-devices`.
- Tokens live in `~/.pypirc` (twine format); never print or echo them.

---

## File Structure

- `pyproject.toml` — Modify: backend swap + enriched `[project]` + `[tool.poetry]` packages; remove `[tool.hatch...]`.
- `LICENSE` — Create: MIT text.
- `src/lab_devices/__init__.py` — Modify: `__version__` from `importlib.metadata`.
- `tests/test_metadata.py` — Create: version-wiring test.
- `README.md` — Modify: Development section prefers `poetry install`.
- `poetry.lock` — Create: generated, committed.

---

### Task 1: Migrate `pyproject.toml` to Poetry + add LICENSE

**Files:**
- Modify: `pyproject.toml`
- Create: `LICENSE`

**Interfaces:**
- Consumes: nothing.
- Produces: a Poetry-managed, buildable package named `lab-devices` version `0.1.0`; `poetry build` emits sdist + wheel containing `lab_devices/` and `py.typed`.

- [ ] **Step 1: Create the LICENSE file**

Create `LICENSE` with standard MIT text:

```
MIT License

Copyright (c) 2026 khamitovdr

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

- [ ] **Step 2: Replace `pyproject.toml` with the Poetry version**

Overwrite `pyproject.toml` with:

```toml
[build-system]
requires = ["poetry-core>=2.0"]
build-backend = "poetry.core.masonry.api"

[project]
name = "lab-devices"
version = "0.1.0"
description = "Async Python library to discover and manage lab devices (pump, valve, densitometer)."
readme = "README.md"
license = "MIT"
license-files = ["LICENSE"]
authors = [{ name = "khamitovdr", email = "khamitov.personal@gmail.com" }]
requires-python = ">=3.11"
keywords = ["lab", "automation", "devices", "async", "httpx"]
classifiers = [
    "Development Status :: 3 - Alpha",
    "Intended Audience :: Science/Research",
    "Programming Language :: Python :: 3",
    "Programming Language :: Python :: 3.11",
    "Programming Language :: Python :: 3.12",
    "Programming Language :: Python :: 3.13",
    "Framework :: AsyncIO",
    "Typing :: Typed",
]
dependencies = ["httpx>=0.27"]

[project.optional-dependencies]
dev = ["pytest>=8", "pytest-asyncio>=0.23", "mypy>=1.8", "ruff>=0.4"]

[project.urls]
Homepage = "https://github.com/bioexperiment-lab-devices/lab-devices"
Repository = "https://github.com/bioexperiment-lab-devices/lab-devices"
Issues = "https://github.com/bioexperiment-lab-devices/lab-devices/issues"

[tool.poetry]
packages = [{ include = "lab_devices", from = "src" }]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]

[tool.mypy]
python_version = "3.11"
strict = true
files = ["src/lab_devices"]

[tool.ruff]
line-length = 100
target-version = "py311"
```

- [ ] **Step 3: Validate the pyproject and install**

Run: `poetry check` then `poetry install`
Expected: `poetry check` reports `All set!` (warnings about the lockfile are fine before Task 3); `poetry install` completes and installs `lab-devices` in editable mode plus dev deps.

Fallback: if `poetry check`/build rejects `license = "MIT"` or `license-files` on this Poetry version, replace those two lines with `license = { text = "MIT" }` and re-run. Record the change in the commit message.

- [ ] **Step 4: Confirm the existing gates stay green**

Run: `poetry run pytest && poetry run mypy && poetry run ruff check .`
Expected: all pass (same as before migration).

- [ ] **Step 5: Build and check the artifacts**

Run: `poetry build && poetry run python -m zipfile -l dist/lab_devices-0.1.0-py3-none-any.whl`
Expected: `dist/` contains `lab_devices-0.1.0.tar.gz` and `lab_devices-0.1.0-py3-none-any.whl`; the wheel listing includes `lab_devices/py.typed`.
(If twine is available: `pipx run twine check dist/*` → PASSED for both.)

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml LICENSE
git commit -m "build: switch to poetry-core backend, add MIT license and PyPI metadata"
```

---

### Task 2: Source `__version__` from installed metadata

**Files:**
- Modify: `src/lab_devices/__init__.py`
- Test: `tests/test_metadata.py`

**Interfaces:**
- Consumes: the installed `lab-devices` distribution metadata (from Task 1's `poetry install`).
- Produces: `lab_devices.__version__` resolves to the installed version string (`"0.1.0"`), falling back to `"0.0.0.dev0"` only when the package is not installed.

- [ ] **Step 1: Write the failing test**

Create `tests/test_metadata.py`:

```python
from importlib.metadata import version

import lab_devices


def test_version_matches_installed_metadata():
    assert lab_devices.__version__ == version("lab-devices")


def test_version_is_not_uninstalled_fallback():
    assert lab_devices.__version__ != "0.0.0.dev0"
```

- [ ] **Step 2: Run test to verify it fails as expected**

Run: `poetry run pytest tests/test_metadata.py -v`
Expected: `test_version_matches_installed_metadata` FAILS — the hardcoded `"0.1.0"` happens to equal the metadata today, so if it already passes, that is acceptable; the meaningful assertion is that after Step 3 the value is *derived*, not hardcoded. Proceed to Step 3 regardless.

- [ ] **Step 3: Replace the hardcoded version**

In `src/lab_devices/__init__.py`, add to the top import block (after `from __future__ import annotations`):

```python
from importlib.metadata import PackageNotFoundError, version as _version
```

Then replace the line `__version__ = "0.1.0"` with:

```python
try:
    __version__ = _version("lab-devices")
except PackageNotFoundError:  # pragma: no cover - running from an uninstalled source tree
    __version__ = "0.0.0.dev0"
```

Leave `__all__` unchanged (keep `"__version__"` in it if already present).

- [ ] **Step 4: Run tests and gates**

Run: `poetry run pytest tests/test_metadata.py -v && poetry run mypy && poetry run ruff check .`
Expected: both metadata tests PASS; mypy and ruff clean.

- [ ] **Step 5: Commit**

```bash
git add src/lab_devices/__init__.py tests/test_metadata.py
git commit -m "refactor: derive __version__ from importlib.metadata"
```

---

### Task 3: Update README and commit the lockfile

**Files:**
- Modify: `README.md`
- Create: `poetry.lock`

**Interfaces:**
- Consumes: the finalized `pyproject.toml` from Task 1.
- Produces: committed `poetry.lock`; README dev instructions reference Poetry.

- [ ] **Step 1: Generate the lockfile**

Run: `poetry lock`
Expected: creates `poetry.lock` resolving `httpx` and the dev deps.

- [ ] **Step 2: Update the README Development section**

In `README.md`, replace the `## Install` command block and `## Development` section commands so Poetry is the primary path. Set the Install block to:

```
    poetry install         # installs runtime + dev deps
    # or, without Poetry:
    pip install -e ".[dev]"
```

And the Development commands to:

```
    poetry run pytest        # hermetic; no hardware needed
    poetry run mypy
    poetry run ruff check .
```

- [ ] **Step 3: Verify README commands work**

Run: `poetry run pytest -q`
Expected: full suite passes (confirms the documented command is correct).

- [ ] **Step 4: Commit**

```bash
git add README.md poetry.lock
git commit -m "docs: poetry-based dev workflow; add lockfile"
```

---

### Task 4: Publish to TestPyPI and verify

**Files:** none (operational). Uses `dist/` from Task 1 Step 5 — rebuild if any code changed since.

**Interfaces:**
- Consumes: built artifacts + `~/.pypirc` `[testpypi]` credentials.
- Produces: `lab-devices 0.1.0` live on test.pypi.org, install-verified.

- [ ] **Step 1: Rebuild fresh artifacts**

Run: `rm -rf dist && poetry build`
Expected: fresh `dist/lab_devices-0.1.0.tar.gz` and wheel.

- [ ] **Step 2: Check metadata**

Run: `pipx run twine check dist/*`
Expected: `PASSED` for both artifacts.

- [ ] **Step 3: Upload to TestPyPI**

Run: `pipx run twine upload --repository testpypi dist/*`
Expected: uploads succeed; prints the `https://test.pypi.org/project/lab-devices/0.1.0/` URL. (Reads credentials from `~/.pypirc`.)

- [ ] **Step 4: Verify a clean install from TestPyPI**

Run:
```bash
python3 -m venv /tmp/ld-verify && \
/tmp/ld-verify/bin/pip install --index-url https://test.pypi.org/simple/ \
  --extra-index-url https://pypi.org/simple/ lab-devices && \
/tmp/ld-verify/bin/python -c "import lab_devices; print(lab_devices.__version__)"
```
Expected: installs `lab-devices` (httpx pulled from real PyPI via extra-index) and prints `0.1.0`.

- [ ] **Step 5: Clean up the verify venv**

Run: `rm -rf /tmp/ld-verify`
Expected: removed. No commit (nothing changed in the repo).

---

### Task 5: Publish to real PyPI (gated)

**Files:** none (operational).

**Interfaces:**
- Consumes: TestPyPI verification from Task 4 + `~/.pypirc` `[pypi]` credentials.
- Produces: `lab-devices 0.1.0` live on pypi.org.

- [ ] **Step 1: HUMAN GATE — get explicit go-ahead**

Do not proceed without the user's explicit confirmation that TestPyPI looked correct and they want the irreversible real-PyPI upload. A published version cannot be overwritten or truly reused even if deleted.

- [ ] **Step 2: Upload to PyPI**

Run: `pipx run twine upload --repository pypi dist/*`
Expected: uploads succeed; prints the `https://pypi.org/project/lab-devices/0.1.0/` URL.

- [ ] **Step 3: Verify the live install**

Run:
```bash
python3 -m venv /tmp/ld-pypi && \
/tmp/ld-pypi/bin/pip install lab-devices && \
/tmp/ld-pypi/bin/python -c "import lab_devices; print(lab_devices.__version__)" && \
rm -rf /tmp/ld-pypi
```
Expected: installs from PyPI and prints `0.1.0`.

- [ ] **Step 4: Tag the release**

```bash
git tag -a v0.1.0 -m "lab-devices 0.1.0"
git push origin main --tags
```

---

## Self-Review

**Spec coverage:**
- Backend swap → Task 1. Enriched metadata → Task 1. LICENSE → Task 1. `[tool.poetry]` packages → Task 1. Remove hatch config → Task 1 (full overwrite). `__version__` via importlib → Task 2. Lockfile → Task 3. README → Task 3. Verification gates → Tasks 1–3. TestPyPI publish + verify → Task 4. Real PyPI gate + publish → Task 5. All spec sections covered.

**Placeholder scan:** No TBD/TODO; all code and commands are concrete.

**Type consistency:** `_version` alias and `PackageNotFoundError` used consistently in Task 2; distribution name `lab-devices` used consistently across metadata lookup, twine, and install commands; version `0.1.0` consistent across pyproject, tests, and publish steps.
