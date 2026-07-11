# Experiment Studio W1 (Skeleton) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up the `experiment-studio` webapp skeleton: library catalog accessors, FastAPI backend (health, catalog, labs endpoints) serving a hello SPA, Vite/React/Tailwind frontend shell, single Docker image, and CI jobs including GHCR image push on release.

**Architecture:** Spec `docs/superpowers/specs/2026-07-11-experiment-studio-webapp-design.md` (§4.4, §5, §6 govern W1). A new `webapp/` tree holds a PEP-621 backend package (`experiment_studio`, own venv, pip-managed — root poetry project untouched) and a Vite frontend. FastAPI serves `/api/*` plus the built SPA with a catch-all fallback. Lab access reuses `LabRegistry`/`LabClient` with injectable factories for testing.

**Tech Stack:** Python ≥3.11 / FastAPI / uvicorn / httpx (backend); Vite + React + TypeScript + Tailwind v4 + vitest (frontend); Docker multi-stage (node:22 → python:3.12-slim); GitHub Actions + GHCR.

## Global Constraints

- **Branch:** `feat/experiment-studio-1-skeleton` (already exists; spec committed as `0be6a57`). Commit after every task with conventional-commit messages (`feat:`/`ci:`/`docs:` — release-please consumes these).
- **Library gates** (root repo, ONLY for Task 1): `.venv/bin/python -m pytest`, `.venv/bin/python -m mypy`, `.venv/bin/python -m ruff check .`, and `awk 'length>100' src/lab_devices/experiment/*.py tests/test_experiment_*.py` must print nothing. Library source modules start with `from __future__ import annotations` after a one-line docstring citing the design §; test files are flat `tests/test_experiment_*.py` with NO future-import.
- **Backend gates** (run from `webapp/backend/`): `.venv/bin/python -m pytest`, `.venv/bin/python -m mypy`, `.venv/bin/python -m ruff check .`. Backend modules follow the same docstring + future-import convention; line length ≤ 100 enforced by ruff config.
- **Frontend gates** (run from `webapp/frontend/`): `npm run lint`, `npm test`, `npm run build`.
- **Image name (S3/S10):** `ghcr.io/bioexperiment-lab-devices/experiment-studio`. Single release stream (S9): image tagged `<version>` + `latest` on release.
- **No auth (S3).** SPA at `/`, API under `/api` (spec §6). Error envelope `{detail, code}`.
- Root `pyproject.toml` must NOT be modified (spec §5).

---

### Task 1: Library catalog accessors (`verb_catalog`, `expression_functions`)

**Files:**
- Create: `src/lab_devices/experiment/catalog.py`
- Modify: `src/lab_devices/experiment/__init__.py` (imports + `__all__`)
- Test: `tests/test_experiment_catalog.py`

**Interfaces:**
- Consumes: `lab_devices.experiment.registry._REGISTRY: dict[tuple[str, str], Trait]` (Trait fields: `measurement: bool`, `result_field: str | None`, `params: tuple[ParamSpec, ...]`; ParamSpec fields: `name: str`, `kind: str`, `required: bool`). `lab_devices.experiment.expr.STAT_FNS = frozenset({"last", "mean", "min", "max", "count"})`.
- Produces: `verb_catalog() -> dict[str, dict[str, VerbEntry]]` keyed device-type → verb, where `VerbEntry = {"kind": "command"|"measure", "params": [{"name": str, "type": str, "required": bool}], "result_field": str | None}` (note: ParamSpec.**kind** is exposed as JSON key **type** — that is the spec §4.4 contract). `expression_functions() -> dict[str, list[str]]` = `{"functions": ["count","last","max","mean","min"], "windows": ["all","last_n","duration"]}`. Both exported from `lab_devices.experiment`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_experiment_catalog.py`:

```python
"""Tests for the public verb/expression catalog accessors (webapp design §4.4)."""

import json

from lab_devices.experiment import expression_functions, verb_catalog


def test_catalog_covers_all_device_types():
    assert set(verb_catalog()) == {"pump", "valve", "densitometer"}


def test_dispense_entry_exact():
    dispense = verb_catalog()["pump"]["dispense"]
    assert dispense["kind"] == "command"
    assert dispense["result_field"] is None
    assert dispense["params"][0] == {"name": "volume_ml", "type": "number", "required": True}
    assert [p["name"] for p in dispense["params"]] == [
        "volume_ml",
        "speed_ml_min",
        "direction",
        "drop_suckback_ml",
    ]


def test_measure_verbs_marked_with_result_field():
    dens = verb_catalog()["densitometer"]
    assert dens["measure"]["kind"] == "measure"
    assert dens["measure"]["result_field"] == "absorbance"
    assert dens["measure_blank"]["kind"] == "measure"
    assert dens["measure_blank"]["result_field"] == "slope"
    assert dens["set_led"]["kind"] == "command"


def test_no_param_verb_has_empty_params():
    assert verb_catalog()["valve"]["stop"]["params"] == []


def test_expression_functions_sorted_and_windows():
    fns = expression_functions()
    assert fns["functions"] == ["count", "last", "max", "mean", "min"]
    assert fns["windows"] == ["all", "last_n", "duration"]


def test_catalog_is_json_serializable():
    json.dumps({"device_types": verb_catalog(), "expression": expression_functions()})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_experiment_catalog.py -q`
Expected: FAIL — `ImportError: cannot import name 'expression_functions'`

- [ ] **Step 3: Write the implementation**

Create `src/lab_devices/experiment/catalog.py`:

```python
"""Public verb/expression catalog for UI layers. See webapp design §4.4."""

from __future__ import annotations

from typing import TypedDict

from lab_devices.experiment.expr import STAT_FNS
from lab_devices.experiment.registry import _REGISTRY


class ParamEntry(TypedDict):
    name: str
    type: str
    required: bool


class VerbEntry(TypedDict):
    kind: str  # "measure" if the verb records a sample, else "command"
    params: list[ParamEntry]
    result_field: str | None


def verb_catalog() -> dict[str, dict[str, VerbEntry]]:
    """Device type -> verb -> UI-facing entry, derived from the private registry."""
    catalog: dict[str, dict[str, VerbEntry]] = {}
    for (device_type, verb), trait in _REGISTRY.items():
        catalog.setdefault(device_type, {})[verb] = VerbEntry(
            kind="measure" if trait.measurement else "command",
            params=[
                ParamEntry(name=p.name, type=p.kind, required=p.required)
                for p in trait.params
            ],
            result_field=trait.result_field,
        )
    return catalog


def expression_functions() -> dict[str, list[str]]:
    """Stat-function names and window forms the expression language accepts."""
    return {"functions": sorted(STAT_FNS), "windows": ["all", "last_n", "duration"]}
```

Modify `src/lab_devices/experiment/__init__.py`: add below the existing `analyze` import block:

```python
from lab_devices.experiment.catalog import (
    ParamEntry,
    VerbEntry,
    expression_functions,
    verb_catalog,
)
```

and add to `__all__` (keep the existing grouping style — append one line):

```python
    "ParamEntry", "VerbEntry", "expression_functions", "verb_catalog",
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_experiment_catalog.py -q`
Expected: 6 passed

- [ ] **Step 5: Run full library gates**

Run: `.venv/bin/python -m pytest -q && .venv/bin/python -m mypy && .venv/bin/python -m ruff check . && awk 'length>100' src/lab_devices/experiment/*.py tests/test_experiment_*.py`
Expected: full suite passes (534+6), mypy clean, ruff clean, awk prints nothing

- [ ] **Step 6: Commit**

```bash
git add src/lab_devices/experiment/catalog.py src/lab_devices/experiment/__init__.py tests/test_experiment_catalog.py
git commit -m "feat: public verb_catalog()/expression_functions() accessors (studio spec §4.4)"
```

---

### Task 2: Backend package, health endpoint, SPA static serving

**Files:**
- Create: `webapp/backend/pyproject.toml`
- Create: `webapp/backend/experiment_studio/__init__.py`
- Create: `webapp/backend/experiment_studio/config.py`
- Create: `webapp/backend/experiment_studio/app.py`
- Create: `webapp/backend/experiment_studio/api/__init__.py`
- Create: `webapp/backend/experiment_studio/api/health.py`
- Test: `webapp/backend/tests/conftest.py`, `webapp/backend/tests/test_health.py`, `webapp/backend/tests/test_spa.py`

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces: `create_app(settings: Settings | None = None) -> FastAPI` (module `experiment_studio.app`; `None` → `Settings.from_env()`); `Settings(static_dir: Path | None)` dataclass with classmethod `from_env()` reading `STUDIO_STATIC_DIR`; `GET /api/health` → `{"status": "ok", "library": <version>, "studio": <version>}`. Tasks 3–4 add routers to `create_app` and reuse the `client` fixture.

- [ ] **Step 1: Create the package layout and pyproject**

```bash
mkdir -p webapp/backend/experiment_studio/api webapp/backend/tests
```

Create `webapp/backend/pyproject.toml`:

```toml
[build-system]
requires = ["hatchling>=1.25"]
build-backend = "hatchling.build"

[project]
name = "experiment-studio"
version = "0.1.0"
description = "Web UI for building and running lab_devices experiments."
requires-python = ">=3.11"
dependencies = [
    "bioexperiment-lab-devices",
    "fastapi>=0.115",
    "uvicorn[standard]>=0.30",
]

[project.optional-dependencies]
dev = ["pytest>=8", "pytest-asyncio>=0.23", "mypy>=1.8", "ruff>=0.4", "httpx>=0.27"]

[tool.hatch.build.targets.wheel]
packages = ["experiment_studio"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]

[tool.mypy]
python_version = "3.11"
strict = true
files = ["experiment_studio"]

[tool.ruff]
line-length = 100
target-version = "py311"
```

Create `webapp/backend/experiment_studio/__init__.py` and `webapp/backend/experiment_studio/api/__init__.py`, both containing exactly:

```python
"""Experiment Studio backend. See webapp design §5."""
```

- [ ] **Step 2: Create the backend venv (library editable + package editable)**

```bash
cd webapp/backend
python3 -m venv .venv
.venv/bin/pip install --quiet --upgrade pip
.venv/bin/pip install --quiet -e ../.. -e '.[dev]'
.venv/bin/python -c "import lab_devices, fastapi; print('deps ok')"
```

Expected: `deps ok`. (`-e ../..` installs the root library via its poetry-core backend; pip supports PEP 660 editables for it.)

- [ ] **Step 3: Write the failing tests**

Create `webapp/backend/tests/conftest.py`:

```python
"""Shared fixtures: app factory + ASGI-transport client (no lifespan needed)."""

from collections.abc import AsyncIterator

import httpx
import pytest
from fastapi import FastAPI

from experiment_studio.app import create_app
from experiment_studio.config import Settings


@pytest.fixture
def app() -> FastAPI:
    return create_app(Settings(static_dir=None))


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://studio") as c:
        yield c
```

Create `webapp/backend/tests/test_health.py`:

```python
"""Health endpoint contract."""

import httpx


async def test_health_reports_ok_and_versions(client: httpx.AsyncClient) -> None:
    resp = await client.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["library"]
    assert body["studio"] == "0.1.0"
```

Create `webapp/backend/tests/test_spa.py`:

```python
"""SPA static serving: catch-all fallback, asset files, API 404s stay JSON."""

from pathlib import Path

import httpx

from experiment_studio.app import create_app
from experiment_studio.config import Settings


def _make_static(tmp_path: Path) -> Path:
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<html>experiment studio</html>")
    (tmp_path / "assets" / "app.js").write_text("console.log('studio')")
    return tmp_path


def _client(static_dir: Path | None) -> httpx.AsyncClient:
    app = create_app(Settings(static_dir=static_dir))
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://studio")


async def test_root_serves_index(tmp_path: Path) -> None:
    async with _client(_make_static(tmp_path)) as c:
        resp = await c.get("/")
        assert resp.status_code == 200
        assert "experiment studio" in resp.text


async def test_asset_file_served(tmp_path: Path) -> None:
    async with _client(_make_static(tmp_path)) as c:
        resp = await c.get("/assets/app.js")
        assert resp.status_code == 200
        assert "studio" in resp.text


async def test_client_route_falls_back_to_index(tmp_path: Path) -> None:
    async with _client(_make_static(tmp_path)) as c:
        resp = await c.get("/records")
        assert resp.status_code == 200
        assert "experiment studio" in resp.text


async def test_unknown_api_path_stays_json_404(tmp_path: Path) -> None:
    async with _client(_make_static(tmp_path)) as c:
        resp = await c.get("/api/nope")
        assert resp.status_code == 404
        assert resp.json()["detail"] == "Not Found"


async def test_traversal_falls_back_to_index(tmp_path: Path) -> None:
    async with _client(_make_static(tmp_path)) as c:
        resp = await c.get("/..%2fpyproject.toml")
        assert resp.status_code == 200
        assert "experiment studio" in resp.text


async def test_without_static_dir_root_is_404(tmp_path: Path) -> None:
    async with _client(None) as c:
        resp = await c.get("/")
        assert resp.status_code == 404
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `cd webapp/backend && .venv/bin/python -m pytest -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'experiment_studio.app'`

- [ ] **Step 5: Write the implementation**

Create `webapp/backend/experiment_studio/config.py`:

```python
"""Runtime settings resolved from environment variables. See webapp design §5."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    static_dir: Path | None = None

    @classmethod
    def from_env(cls) -> Settings:
        raw = os.environ.get("STUDIO_STATIC_DIR")
        if not raw:
            return cls(static_dir=None)
        static = Path(raw)
        return cls(static_dir=static if static.is_dir() else None)
```

Create `webapp/backend/experiment_studio/api/health.py`:

```python
"""Liveness + version endpoint. See webapp design §6."""

from __future__ import annotations

from importlib.metadata import version

from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
def health() -> dict[str, str]:
    return {
        "status": "ok",
        "library": version("bioexperiment-lab-devices"),
        "studio": version("experiment-studio"),
    }
```

Create `webapp/backend/experiment_studio/app.py`:

```python
"""FastAPI application factory: API routers + SPA static serving. See webapp design §5-6."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

from experiment_studio.api.health import router as health_router
from experiment_studio.config import Settings


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings if settings is not None else Settings.from_env()
    app = FastAPI(title="experiment-studio")
    app.include_router(health_router, prefix="/api")
    if settings.static_dir is not None:
        _mount_spa(app, settings.static_dir)
    return app


def _mount_spa(app: FastAPI, static_dir: Path) -> None:
    """Serve built frontend files; unknown non-API paths fall back to index.html."""
    root = static_dir.resolve()
    index = root / "index.html"

    @app.get("/{path:path}", include_in_schema=False)
    async def spa(path: str) -> FileResponse:
        if path.startswith("api/"):
            raise HTTPException(status_code=404)
        candidate = (root / path).resolve()
        if path and candidate.is_file() and candidate.is_relative_to(root):
            return FileResponse(candidate)
        return FileResponse(index)
```

(Route order matters: routers are included before the catch-all is registered, so `/api/*` always wins; the `api/` guard keeps unknown API paths as JSON 404s.)

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd webapp/backend && .venv/bin/python -m pytest -q`
Expected: 7 passed

- [ ] **Step 7: Run backend gates**

Run: `cd webapp/backend && .venv/bin/python -m mypy && .venv/bin/python -m ruff check .`
Expected: both clean

- [ ] **Step 8: Commit**

```bash
git add webapp/backend
git commit -m "feat(studio): backend package with health endpoint and SPA serving"
```

---

### Task 3: `/api/catalog` endpoint

**Files:**
- Create: `webapp/backend/experiment_studio/api/catalog.py`
- Modify: `webapp/backend/experiment_studio/app.py` (include router)
- Test: `webapp/backend/tests/test_catalog.py`

**Interfaces:**
- Consumes: `verb_catalog()` / `expression_functions()` from Task 1; `client` fixture from Task 2.
- Produces: `GET /api/catalog` → `{"device_types": <verb_catalog()>, "expression": <expression_functions()>}` — exactly the spec §4.4 payload the frontend palette consumes in W3.

- [ ] **Step 1: Write the failing test**

Create `webapp/backend/tests/test_catalog.py`:

```python
"""Catalog endpoint: thin serialization of the library accessors."""

import httpx


async def test_catalog_shape(client: httpx.AsyncClient) -> None:
    resp = await client.get("/api/catalog")
    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == {"device_types", "expression"}
    dispense = body["device_types"]["pump"]["dispense"]
    assert dispense["kind"] == "command"
    assert dispense["params"][0] == {"name": "volume_ml", "type": "number", "required": True}
    assert body["device_types"]["densitometer"]["measure"]["result_field"] == "absorbance"
    assert body["expression"]["functions"] == ["count", "last", "max", "mean", "min"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd webapp/backend && .venv/bin/python -m pytest tests/test_catalog.py -q`
Expected: FAIL — 404 (route not registered)

- [ ] **Step 3: Write the implementation**

Create `webapp/backend/experiment_studio/api/catalog.py`:

```python
"""Verb/expression catalog endpoint. See webapp design §4.4, §6."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from lab_devices.experiment import expression_functions, verb_catalog

router = APIRouter()


@router.get("/catalog")
def catalog() -> dict[str, Any]:
    return {"device_types": verb_catalog(), "expression": expression_functions()}
```

Modify `webapp/backend/experiment_studio/app.py` — add the import next to the health import and include the router directly after `health_router`:

```python
from experiment_studio.api.catalog import router as catalog_router
```

```python
    app.include_router(catalog_router, prefix="/api")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd webapp/backend && .venv/bin/python -m pytest -q`
Expected: 8 passed

- [ ] **Step 5: Gates + commit**

Run: `cd webapp/backend && .venv/bin/python -m mypy && .venv/bin/python -m ruff check .`
Expected: clean

```bash
git add webapp/backend/experiment_studio/api/catalog.py webapp/backend/experiment_studio/app.py webapp/backend/tests/test_catalog.py
git commit -m "feat(studio): /api/catalog from library verb/expression accessors"
```

---

### Task 4: Labs service + roster/devices/discover endpoints

**Files:**
- Create: `webapp/backend/experiment_studio/labs.py`
- Create: `webapp/backend/experiment_studio/api/labs.py`
- Modify: `webapp/backend/experiment_studio/app.py` (labs router, error handlers, lifespan)
- Test: `webapp/backend/tests/test_labs_api.py`

**Interfaces:**
- Consumes: `LabRegistry(url=..., http=...)` (`list_labs() -> list[str]`, `lookup(name) -> LabInfo(name, host, port)`, `is_online(name) -> bool`, `aclose()`); `LabClient(host, port, *, http=...)` (async context manager; `list_devices() -> list[DeviceInfo]`, `rediscover() -> list[DeviceInfo]`); `DeviceInfo` fields `id/type/port/connected/identify`; `Identify` fields `model/firmware_version`; exceptions from `lab_devices.errors`: `UnknownLabClient`, `LabOffline`, `ClientLookupEndpointUnreachable`, `ClientLookupEndpointError`, `DiscoveryInProgressError`, `JobInProgressError`, `DiscoveryFailedError`. Agent wire facts for fakes: `GET /api/v1/devices` and `POST /api/v1/discover` both return `{"devices": [...]}`; discover returns 409 `{"error": "discovery in progress"}` when busy.
- Produces: `LabsService(registry, *, client_factory=None, probe=None)` with `list_labs() -> list[dict]` (`{name, host, port, online}`), `devices(lab) -> list[dict]`, `discover(lab) -> list[dict]` (device dicts: `{id, type, port, connected, model, firmware}`), `aclose()`; FastAPI dependency `get_labs_service` (module `experiment_studio.api.labs`) that W4+ will reuse; routes `GET /api/labs`, `GET /api/labs/{lab}/devices`, `POST /api/labs/{lab}/discover`; app-level exception handlers mapping lab errors to `{detail, code}` envelopes (404 `unknown_lab`, 502 `lab_offline`/`roster_unreachable`/`roster_error`/`discovery_failed`/`lab_unreachable`, 409 `agent_busy`).

- [ ] **Step 1: Write the failing tests**

Create `webapp/backend/tests/test_labs_api.py`:

```python
"""Labs endpoints against MockTransport-backed registry and agent clients."""

from collections.abc import AsyncIterator

import httpx
import pytest
from fastapi import FastAPI

from lab_devices.client import LabClient
from lab_devices.discovery import LabInfo, LabRegistry

from experiment_studio.api.labs import get_labs_service
from experiment_studio.labs import LabsService

ROSTER = {
    "khamit_desktop": {"host": "127.0.0.1", "port": 8089},
    "protres_ksenios": {"host": "127.0.0.1", "port": 8081},
}
AGENT_DEVICES = {
    "devices": [
        {
            "id": "pump_1",
            "type": "pump",
            "port": "COM3",
            "connected": True,
            "identify": {"model": "P-100", "firmware_version": "2.1.0"},
        },
        {"id": "valve_2", "type": "valve", "port": "COM4", "connected": False},
    ]
}


def _registry() -> LabRegistry:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=ROSTER)

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return LabRegistry(url="http://siteapp:8000/api/clients/", http=http)


def _agent_factory(response_for: dict[str, httpx.Response | Exception]):
    """Map 'METHOD /path' -> canned response (or exception to raise)."""

    def factory(info: LabInfo) -> LabClient:
        def handler(request: httpx.Request) -> httpx.Response:
            key = f"{request.method} {request.url.path}"
            outcome = response_for.get(key)
            if outcome is None:
                return httpx.Response(404, json={})
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

        http = httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            base_url=f"http://{info.host}:{info.port}",
        )
        return LabClient(info.host, info.port, http=http)

    return factory


async def _probe_all_online(name: str) -> bool:
    return True


def _install(app: FastAPI, service: LabsService) -> None:
    app.dependency_overrides[get_labs_service] = lambda: service


@pytest.fixture
async def happy_service() -> AsyncIterator[LabsService]:
    service = LabsService(
        _registry(),
        client_factory=_agent_factory(
            {
                "GET /api/v1/devices": httpx.Response(200, json=AGENT_DEVICES),
                "POST /api/v1/discover": httpx.Response(200, json=AGENT_DEVICES),
            }
        ),
        probe=_probe_all_online,
    )
    yield service
    await service.aclose()


async def test_list_labs_with_online_flag(
    app: FastAPI, client: httpx.AsyncClient, happy_service: LabsService
) -> None:
    _install(app, happy_service)
    resp = await client.get("/api/labs")
    assert resp.status_code == 200
    labs = {lab["name"]: lab for lab in resp.json()}
    assert labs["khamit_desktop"] == {
        "name": "khamit_desktop",
        "host": "127.0.0.1",
        "port": 8089,
        "online": True,
    }
    assert set(labs) == {"khamit_desktop", "protres_ksenios"}


async def test_devices_serialization(
    app: FastAPI, client: httpx.AsyncClient, happy_service: LabsService
) -> None:
    _install(app, happy_service)
    resp = await client.get("/api/labs/khamit_desktop/devices")
    assert resp.status_code == 200
    pump, valve = resp.json()
    assert pump == {
        "id": "pump_1",
        "type": "pump",
        "port": "COM3",
        "connected": True,
        "model": "P-100",
        "firmware": "2.1.0",
    }
    assert valve["model"] is None and valve["firmware"] is None


async def test_discover_returns_devices(
    app: FastAPI, client: httpx.AsyncClient, happy_service: LabsService
) -> None:
    _install(app, happy_service)
    resp = await client.post("/api/labs/khamit_desktop/discover")
    assert resp.status_code == 200
    assert [d["id"] for d in resp.json()] == ["pump_1", "valve_2"]


async def test_unknown_lab_is_404(
    app: FastAPI, client: httpx.AsyncClient, happy_service: LabsService
) -> None:
    _install(app, happy_service)
    resp = await client.get("/api/labs/ghost/devices")
    assert resp.status_code == 404
    assert resp.json()["code"] == "unknown_lab"


async def test_agent_unreachable_is_502(app: FastAPI, client: httpx.AsyncClient) -> None:
    def factory(info: LabInfo) -> LabClient:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("boom", request=request)

        http = httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            base_url=f"http://{info.host}:{info.port}",
        )
        return LabClient(info.host, info.port, http=http)

    service = LabsService(_registry(), client_factory=factory, probe=_probe_all_online)
    _install(app, service)
    try:
        resp = await client.get("/api/labs/khamit_desktop/devices")
        assert resp.status_code == 502
        assert resp.json()["code"] == "lab_unreachable"
    finally:
        await service.aclose()


async def test_discover_busy_agent_is_409(app: FastAPI, client: httpx.AsyncClient) -> None:
    service = LabsService(
        _registry(),
        client_factory=_agent_factory(
            {
                "POST /api/v1/discover": httpx.Response(
                    409, json={"error": "discovery in progress"}
                )
            }
        ),
        probe=_probe_all_online,
    )
    _install(app, service)
    try:
        resp = await client.post("/api/labs/khamit_desktop/discover")
        assert resp.status_code == 409
        assert resp.json()["code"] == "agent_busy"
    finally:
        await service.aclose()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd webapp/backend && .venv/bin/python -m pytest tests/test_labs_api.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'experiment_studio.labs'`

- [ ] **Step 3: Write the service**

Create `webapp/backend/experiment_studio/labs.py`:

```python
"""Roster + per-lab device introspection over LabRegistry/LabClient. See webapp design §6."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from lab_devices.client import LabClient
from lab_devices.discovery import LabInfo, LabRegistry
from lab_devices.models.common import DeviceInfo

ClientFactory = Callable[[LabInfo], LabClient]
Probe = Callable[[str], Awaitable[bool]]


def device_json(device: DeviceInfo) -> dict[str, Any]:
    identify = device.identify
    return {
        "id": device.id,
        "type": device.type,
        "port": device.port,
        "connected": device.connected,
        "model": identify.model if identify is not None else None,
        "firmware": identify.firmware_version if identify is not None else None,
    }


def _default_client_factory(info: LabInfo) -> LabClient:
    return LabClient(info.host, info.port)


class LabsService:
    """Stateless per-request lab access; one LabClient per call, always closed."""

    def __init__(
        self,
        registry: LabRegistry,
        *,
        client_factory: ClientFactory | None = None,
        probe: Probe | None = None,
    ) -> None:
        self._registry = registry
        self._client_factory = client_factory or _default_client_factory
        self._probe = probe or registry.is_online

    async def list_labs(self) -> list[dict[str, Any]]:
        names = await self._registry.list_labs()
        online = await asyncio.gather(*(self._probe(name) for name in names))
        out: list[dict[str, Any]] = []
        for name, up in zip(names, online):
            info = await self._registry.lookup(name)
            out.append({"name": name, "host": info.host, "port": info.port, "online": up})
        return out

    async def devices(self, lab: str) -> list[dict[str, Any]]:
        info = await self._registry.lookup(lab)
        async with self._client_factory(info) as client:
            return [device_json(d) for d in await client.list_devices()]

    async def discover(self, lab: str) -> list[dict[str, Any]]:
        info = await self._registry.lookup(lab)
        async with self._client_factory(info) as client:
            return [device_json(d) for d in await client.rediscover()]

    async def aclose(self) -> None:
        await self._registry.aclose()
```

Create `webapp/backend/experiment_studio/api/labs.py`:

```python
"""Lab roster and device endpoints. See webapp design §6."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request

from lab_devices.discovery import LabRegistry

from experiment_studio.labs import LabsService

router = APIRouter()


def get_labs_service(request: Request) -> LabsService:
    """Lazily construct the real service on first use (tests override this dependency)."""
    service = getattr(request.app.state, "labs", None)
    if service is None:
        service = LabsService(LabRegistry())
        request.app.state.labs = service
    return service


@router.get("")
async def list_labs(service: LabsService = Depends(get_labs_service)) -> list[dict[str, Any]]:
    return await service.list_labs()


@router.get("/{lab}/devices")
async def lab_devices(
    lab: str, service: LabsService = Depends(get_labs_service)
) -> list[dict[str, Any]]:
    return await service.devices(lab)


@router.post("/{lab}/discover")
async def lab_discover(
    lab: str, service: LabsService = Depends(get_labs_service)
) -> list[dict[str, Any]]:
    return await service.discover(lab)
```

- [ ] **Step 4: Wire router, error handlers, and lifespan into the app**

Replace `webapp/backend/experiment_studio/app.py` with:

```python
"""FastAPI application factory: API routers, error mapping, SPA static serving.
See webapp design §5-6."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Coroutine
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse

from lab_devices import errors as lab_errors

from experiment_studio.api.catalog import router as catalog_router
from experiment_studio.api.health import router as health_router
from experiment_studio.api.labs import router as labs_router
from experiment_studio.config import Settings

# Spec §6: structured error envelope {detail, code}. Subclasses win over httpx.HTTPError
# because Starlette resolves handlers along the exception's MRO.
_ERROR_MAP: list[tuple[type[Exception], int, str]] = [
    (lab_errors.UnknownLabClient, 404, "unknown_lab"),
    (lab_errors.LabOffline, 502, "lab_offline"),
    (lab_errors.ClientLookupEndpointUnreachable, 502, "roster_unreachable"),
    (lab_errors.ClientLookupEndpointError, 502, "roster_error"),
    (lab_errors.DiscoveryInProgressError, 409, "agent_busy"),
    (lab_errors.JobInProgressError, 409, "agent_busy"),
    (lab_errors.DiscoveryFailedError, 502, "discovery_failed"),
    (httpx.HTTPError, 502, "lab_unreachable"),
]


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    yield
    labs = getattr(app.state, "labs", None)
    if labs is not None:
        await labs.aclose()


def _error_handler(
    status: int, code: str
) -> Callable[[Request, Exception], Coroutine[Any, Any, JSONResponse]]:
    async def handle(request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(status_code=status, content={"detail": str(exc), "code": code})

    return handle


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings if settings is not None else Settings.from_env()
    app = FastAPI(title="experiment-studio", lifespan=_lifespan)
    for exc_type, status, code in _ERROR_MAP:
        app.add_exception_handler(exc_type, _error_handler(status, code))
    app.include_router(health_router, prefix="/api")
    app.include_router(catalog_router, prefix="/api")
    app.include_router(labs_router, prefix="/api/labs")
    if settings.static_dir is not None:
        _mount_spa(app, settings.static_dir)
    return app


def _mount_spa(app: FastAPI, static_dir: Path) -> None:
    """Serve built frontend files; unknown non-API paths fall back to index.html."""
    root = static_dir.resolve()
    index = root / "index.html"

    @app.get("/{path:path}", include_in_schema=False)
    async def spa(path: str) -> FileResponse:
        if path.startswith("api/"):
            raise HTTPException(status_code=404)
        candidate = (root / path).resolve()
        if path and candidate.is_file() and candidate.is_relative_to(root):
            return FileResponse(candidate)
        return FileResponse(index)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd webapp/backend && .venv/bin/python -m pytest -q`
Expected: 14 passed

- [ ] **Step 6: Gates + commit**

Run: `cd webapp/backend && .venv/bin/python -m mypy && .venv/bin/python -m ruff check .`
Expected: clean

```bash
git add webapp/backend/experiment_studio webapp/backend/tests
git commit -m "feat(studio): labs roster/devices/discover endpoints with error mapping"
```

---

### Task 5: Frontend scaffold (Vite + React + TS + Tailwind + vitest, tab shell, health card)

**Files:**
- Create: `webapp/frontend/` (Vite `react-ts` template scaffold)
- Create: `webapp/frontend/src/api/client.ts`, `webapp/frontend/src/api/health.ts`, `webapp/frontend/src/api/health.test.ts`
- Create: `webapp/frontend/src/shell/TabShell.tsx`
- Modify: `webapp/frontend/vite.config.ts`, `webapp/frontend/src/App.tsx`, `webapp/frontend/src/main.tsx`, `webapp/frontend/src/index.css`, `webapp/frontend/index.html`, `webapp/frontend/package.json` (scripts)
- Delete: `webapp/frontend/src/App.css`, `webapp/frontend/src/assets/react.svg`, `webapp/frontend/public/vite.svg`

**Interfaces:**
- Consumes: `GET /api/health` from Task 2 (shape `{status, library, studio}`).
- Produces: the SPA that Task 6's Docker build compiles into `/app/static`; `TabShell` + tab placeholders that W3/W5 fill in; `getJson<T>` in `src/api/client.ts` as the fetch helper later increments build on. npm scripts: `dev`, `build`, `lint`, `test` (vitest run), `typecheck`.

- [ ] **Step 1: Scaffold the Vite app**

```bash
cd webapp
npm create vite@latest frontend -- --template react-ts
cd frontend
npm install
npm install tailwindcss @tailwindcss/vite
npm install -D vitest
npm pkg set scripts.test="vitest run" scripts.typecheck="tsc -b"
```

(If the template's generated file names differ slightly from those below, keep the template's tsconfig/eslint files as generated and only apply the explicit file contents that follow.)

- [ ] **Step 2: Replace config and entry files**

Replace `webapp/frontend/vite.config.ts`:

```ts
/// <reference types="vitest/config" />
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: { '/api': 'http://localhost:8000' },
  },
  test: {
    environment: 'node',
    include: ['src/**/*.test.ts'],
  },
})
```

Replace `webapp/frontend/src/index.css` with exactly:

```css
@import 'tailwindcss';
```

Replace `webapp/frontend/index.html`:

```html
<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Experiment Studio</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```

Replace `webapp/frontend/src/main.tsx`:

```tsx
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
```

Delete template cruft:

```bash
cd webapp/frontend
rm -f src/App.css src/assets/react.svg public/vite.svg
```

- [ ] **Step 3: Write the failing vitest test**

Create `webapp/frontend/src/api/health.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import { describeHealth } from './health'

describe('describeHealth', () => {
  it('reports checking while loading', () => {
    expect(describeHealth(null, null)).toBe('checking backend…')
  })
  it('prefers the error when present', () => {
    expect(describeHealth(null, 'boom')).toBe('backend unreachable: boom')
  })
  it('formats versions when healthy', () => {
    expect(
      describeHealth({ status: 'ok', library: '0.1.1', studio: '0.1.0' }, null),
    ).toBe('backend ok — engine 0.1.1, studio 0.1.0')
  })
})
```

Run: `cd webapp/frontend && npm test`
Expected: FAIL — cannot resolve `./health`

- [ ] **Step 4: Write the API client, health helper, shell, and App**

Create `webapp/frontend/src/api/client.ts`:

```ts
export interface Health {
  status: string
  library: string
  studio: string
}

export async function getJson<T>(path: string): Promise<T> {
  const resp = await fetch(path)
  if (!resp.ok) throw new Error(`${path}: HTTP ${resp.status}`)
  return (await resp.json()) as T
}

export const getHealth = () => getJson<Health>('/api/health')
```

Create `webapp/frontend/src/api/health.ts`:

```ts
import type { Health } from './client'

export function describeHealth(health: Health | null, error: string | null): string {
  if (error) return `backend unreachable: ${error}`
  if (!health) return 'checking backend…'
  return `backend ok — engine ${health.library}, studio ${health.studio}`
}
```

Create `webapp/frontend/src/shell/TabShell.tsx`:

```tsx
import type { ReactNode } from 'react'

export const TABS = ['Devices', 'Builder', 'Run', 'Records'] as const
export type Tab = (typeof TABS)[number]

export function TabShell(props: {
  active: Tab
  onSelect: (tab: Tab) => void
  statusLine: string
  children: ReactNode
}) {
  return (
    <div className="min-h-screen bg-slate-100 text-slate-900">
      <header className="border-b border-slate-200 bg-white px-6 py-3">
        <div className="flex items-baseline justify-between">
          <h1 className="text-lg font-semibold">Experiment Studio</h1>
          <span className="text-xs text-slate-500">{props.statusLine}</span>
        </div>
        <nav className="mt-3 flex gap-2">
          {TABS.map((tab, i) => (
            <button
              key={tab}
              onClick={() => props.onSelect(tab)}
              className={
                'rounded-full px-4 py-1.5 text-sm transition-colors ' +
                (tab === props.active
                  ? 'bg-slate-900 text-white'
                  : 'bg-slate-200 text-slate-600 hover:bg-slate-300')
              }
            >
              <span className="mr-1.5 font-mono text-xs opacity-60">{i + 1}</span>
              {tab}
            </button>
          ))}
        </nav>
      </header>
      <main className="p-6">{props.children}</main>
    </div>
  )
}
```

Replace `webapp/frontend/src/App.tsx`:

```tsx
import { useEffect, useState } from 'react'
import { getHealth, type Health } from './api/client'
import { describeHealth } from './api/health'
import { TabShell, type Tab } from './shell/TabShell'

const PLACEHOLDERS: Record<Tab, string> = {
  Devices: 'Lab roster and device discovery arrive in increment W1/W3.',
  Builder: 'The visual experiment builder arrives in increment W3.',
  Run: 'Run controls, live chart, and prompts arrive in increment W5.',
  Records: 'Run records arrive in increment W5.',
}

export default function App() {
  const [tab, setTab] = useState<Tab>('Devices')
  const [health, setHealth] = useState<Health | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    getHealth()
      .then(setHealth)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)))
  }, [])

  return (
    <TabShell active={tab} onSelect={setTab} statusLine={describeHealth(health, error)}>
      <div className="rounded-lg border border-dashed border-slate-300 bg-white p-10 text-center text-slate-500">
        {PLACEHOLDERS[tab]}
      </div>
    </TabShell>
  )
}
```

- [ ] **Step 5: Run frontend gates**

Run: `cd webapp/frontend && npm test && npm run lint && npm run build`
Expected: 3 tests pass, lint clean, build emits `dist/` (contains `index.html` + `assets/`)

- [ ] **Step 6: Verify the backend serves the built SPA (manual smoke)**

```bash
cd webapp/backend
STUDIO_STATIC_DIR=../frontend/dist .venv/bin/python -m uvicorn --factory experiment_studio.app:create_app --port 8000 &
sleep 2
curl -fsS localhost:8000/api/health
curl -fsS localhost:8000/ | grep -i "experiment studio"
kill %1
```

Expected: health JSON + HTML containing the title.

- [ ] **Step 7: Commit**

```bash
git add webapp/frontend
git commit -m "feat(studio): frontend shell (Vite/React/Tailwind) with health status and tab stepper"
```

---

### Task 6: Docker image (multi-stage, single image)

**Files:**
- Create: `webapp/Dockerfile`
- Create: `.dockerignore` (repo root — build context is the repo root)

**Interfaces:**
- Consumes: root library package (poetry-core, installable via pip), `webapp/backend` package, `webapp/frontend` build.
- Produces: image serving UI + API + (later) WS on port 8000, run as `uvicorn --factory experiment_studio.app:create_app`; `STUDIO_STATIC_DIR=/app/static` baked in. Task 7's CI builds/pushes this exact file.

- [ ] **Step 1: Write the Dockerfile**

Create `webapp/Dockerfile`:

```dockerfile
# Build context is the REPO ROOT: docker build -f webapp/Dockerfile .
FROM node:22-alpine AS frontend
WORKDIR /build
COPY webapp/frontend/package.json webapp/frontend/package-lock.json ./
RUN npm ci
COPY webapp/frontend/ ./
RUN npm run build

FROM python:3.12-slim
WORKDIR /app
# Library first (its own layer), then the backend package.
COPY pyproject.toml poetry.lock README.md LICENSE ./library/
COPY src ./library/src
RUN pip install --no-cache-dir ./library
COPY webapp/backend ./backend
RUN pip install --no-cache-dir ./backend
COPY --from=frontend /build/dist /app/static
ENV STUDIO_STATIC_DIR=/app/static
EXPOSE 8000
CMD ["uvicorn", "--factory", "experiment_studio.app:create_app", "--host", "0.0.0.0", "--port", "8000"]
```

Create `.dockerignore` at the repo root:

```
.git
.venv
**/.venv
**/node_modules
**/dist
**/__pycache__
**/.pytest_cache
**/.mypy_cache
**/.ruff_cache
docs
tests
```

(`**/dist` keeps any locally built frontend out of the context; the image builds its own in stage 1. `tests/` excluded — the image never runs the suite.)

- [ ] **Step 2: Build and smoke-test locally (skip if docker is unavailable — the Task 7 CI job covers it)**

```bash
cd /Users/khamit/lab-devices
docker build -f webapp/Dockerfile -t experiment-studio:dev .
docker run -d --rm -p 8000:8000 --name studio-smoke experiment-studio:dev
sleep 3
curl -fsS localhost:8000/api/health
curl -fsS localhost:8000/ | grep -i "experiment studio"
curl -fsS localhost:8000/api/catalog | head -c 120
docker rm -f studio-smoke
```

Expected: health JSON with `"status":"ok"`, HTML title, catalog JSON prefix.

- [ ] **Step 3: Commit**

```bash
git add webapp/Dockerfile .dockerignore
git commit -m "feat(studio): single-image Dockerfile (frontend build + fastapi runtime)"
```

---

### Task 7: CI jobs, GHCR release push, docs, gitignore

**Files:**
- Modify: `.github/workflows/ci.yml` (append three jobs; existing `test` job untouched)
- Modify: `.github/workflows/release-please.yml` (append `image` job; existing jobs untouched)
- Modify: `.gitignore` (append `node_modules/`)
- Create: `webapp/README.md`

**Interfaces:**
- Consumes: Tasks 1–6 artifacts (backend package + gates, frontend scripts, Dockerfile), existing `release-please` job outputs `release_created` / `tag_name`.
- Produces: PR checks `webapp-backend`, `webapp-frontend`, `webapp-image`; release-time push of `ghcr.io/bioexperiment-lab-devices/experiment-studio:{<version>,latest}`.

- [ ] **Step 1: Append webapp jobs to `.github/workflows/ci.yml`**

Add after the existing `test` job (same indentation level, inside `jobs:`):

```yaml
  webapp-backend:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: pip
          cache-dependency-path: webapp/backend/pyproject.toml
      - name: Install backend (library + package, editable)
        run: python -m pip install -e . -e "webapp/backend[dev]"
      - name: Run tests
        working-directory: webapp/backend
        run: python -m pytest -q
      - name: Type check
        working-directory: webapp/backend
        run: python -m mypy
      - name: Lint
        working-directory: webapp/backend
        run: python -m ruff check .

  webapp-frontend:
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: webapp/frontend
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: "22"
          cache: npm
          cache-dependency-path: webapp/frontend/package-lock.json
      - run: npm ci
      - run: npm run lint
      - run: npm test
      - run: npm run build

  webapp-image:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Build image
        run: docker build -f webapp/Dockerfile -t experiment-studio:ci .
      - name: Smoke test
        run: |
          docker run -d --rm -p 8000:8000 --name studio experiment-studio:ci
          for i in $(seq 1 20); do
            curl -fsS localhost:8000/api/health && break || sleep 1
          done
          curl -fsS localhost:8000/api/health | grep -o '"status":"ok"'
          curl -fsS localhost:8000/ | grep -qi "experiment studio"
          docker rm -f studio
```

(All three jobs run on every PR — the repo is small and this avoids required-check gymnastics with path filters.)

- [ ] **Step 2: Append the image-push job to `.github/workflows/release-please.yml`**

Add after the existing `publish` job:

```yaml
  image:
    needs: release-please
    if: ${{ needs.release-please.outputs.release_created == 'true' }}
    runs-on: ubuntu-latest
    permissions:
      contents: read
      packages: write
    steps:
      - uses: actions/checkout@v4
      - name: Log in to GHCR
        uses: docker/login-action@v3
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}
      - name: Compute version tag
        id: meta
        env:
          TAG: ${{ needs.release-please.outputs.tag_name }}
        run: echo "version=${TAG#v}" >> "$GITHUB_OUTPUT"
      - name: Build and push
        uses: docker/build-push-action@v6
        with:
          context: .
          file: webapp/Dockerfile
          push: true
          tags: |
            ghcr.io/bioexperiment-lab-devices/experiment-studio:${{ steps.meta.outputs.version }}
            ghcr.io/bioexperiment-lab-devices/experiment-studio:latest
```

- [ ] **Step 3: Update `.gitignore` and write `webapp/README.md`**

Append to `.gitignore`:

```
node_modules/
```

Create `webapp/README.md`:

```markdown
# Experiment Studio

Web UI for building and running `lab_devices` experiments. Design spec:
`docs/superpowers/specs/2026-07-11-experiment-studio-webapp-design.md`.

## Dev setup

Backend (own venv; root poetry venv is separate):

    cd webapp/backend
    python3 -m venv .venv
    .venv/bin/pip install -e ../.. -e '.[dev]'
    .venv/bin/python -m uvicorn --factory experiment_studio.app:create_app --reload

Frontend (proxies /api to :8000):

    cd webapp/frontend
    npm install
    npm run dev

## Gates

- Backend: `.venv/bin/python -m pytest && .venv/bin/python -m mypy && .venv/bin/python -m ruff check .`
- Frontend: `npm run lint && npm test && npm run build`

## Image

    docker build -f webapp/Dockerfile -t experiment-studio:dev .
    docker run --rm -p 8000:8000 experiment-studio:dev

Published on release as `ghcr.io/bioexperiment-lab-devices/experiment-studio:{version,latest}`.
```

- [ ] **Step 4: Validate workflow YAML**

Run: `.venv/bin/python -c "import yaml,sys; [yaml.safe_load(open(f)) for f in ['.github/workflows/ci.yml','.github/workflows/release-please.yml']]; print('yaml ok')"`
Expected: `yaml ok` (if PyYAML is missing in the root venv, use `python3 -c` with any interpreter that has it, or `npx --yes yaml-lint <files>`)

- [ ] **Step 5: Commit and push; verify CI**

```bash
git add .github/workflows/ci.yml .github/workflows/release-please.yml .gitignore webapp/README.md
git commit -m "ci: webapp backend/frontend/image jobs + GHCR push on release"
git push -u origin feat/experiment-studio-1-skeleton
gh pr create --title "feat: experiment-studio W1 skeleton" --body "Implements W1 of docs/superpowers/specs/2026-07-11-experiment-studio-webapp-design.md: library catalog accessors, FastAPI backend (health/catalog/labs) serving the SPA shell, Dockerfile, CI + GHCR release push."
gh pr checks --watch
```

Expected: all four checks green (`test`, `webapp-backend`, `webapp-frontend`, `webapp-image`).
