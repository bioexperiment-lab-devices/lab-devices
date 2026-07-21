# Manual Device Control Tab — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a manual device-control tab to Experiment Studio — device-type navigation, per-device custom names (server-persisted, propagated to the Labs roster and Run role-mapping), and the full per-type command surface run through a thin generic backend passthrough with fire+poll jobs. Rename the existing read-only Devices tab to "Labs".

**Architecture:** Backend stays true to the stateless per-request `LabsService`: a new generic command-passthrough endpoint and a job-status endpoint each open one `LabClient`, do one thing, and close. Custom names live in a new `device_names` SQLite table and are merged into the existing devices/discover payloads by one server-side join, so every consumer gets them for free. The frontend adds a device-type-navigated tab whose command controls are common per type; a frontend-owned catalog supplies UI metadata while the backend forwards any `cmd`. Delivered as two sequential PRs: **PR A** (backend contract + persistence), then **PR B** (frontend) off updated `main`.

**Tech Stack:** FastAPI + aiosqlite (backend); React + Zustand + Tailwind + lucide-react + vitest (frontend). Reference spec: `docs/superpowers/specs/2026-07-21-manual-device-control-tab-design.md`.

## Global Constraints

- **No changes to the root `lab_devices` library** (`src/`). Both PRs touch only `webapp/`.
- **Backend gates (all must pass):** from `webapp/backend/` — `.venv/bin/python -m pytest -q`, `.venv/bin/python -m mypy`, `.venv/bin/python -m ruff check .`.
- **Frontend gates (all must pass):** from `webapp/frontend/` — `npm run lint`, `npm test`, `npm run build`; plus `npm run capture` for any new coloured surface / control row (probe R4 sibling-height, R5 text-contrast).
- **Frontend control height:** every input/select/inline button at 24px via `controlClass()` / `inlineButtonClass()` from `src/ui/controls.ts`. Pass `width` as an option, never concatenate.
- **Frontend colour:** hue (blue/red/amber/emerald) reserved for state (selection/error/warning/valid). No baked-helper-class override by concatenation. Tailwind class names must be complete literals.
- **Frontend icons:** lucide-react only; icon-only actions via `IconButton` / `iconButtonClass()`. No raw glyph control characters.
- **Frontend text colours:** `text-caption` (slate-600) for meaning-carrying secondary text; `text-hint` (slate-500) only for incidental text on white (never on `bg-slate-100`).
- **Frontend tests:** vitest runs in node env — pure functions only, no component rendering. Components are verified by `npm run build` (tsc) + `npm run capture` (probe).
- **DB migrations are append-only** — never edit an existing entry in `db.py` `MIGRATIONS`; append and let `user_version` advance.
- **Error envelope:** backend errors are `{detail, code}` (design §6); the frontend `ApiError` reads `code`.

---

# PR A — Backend contract + persistence

Branch: `feat/devices-control-tab` (already holds the spec + this plan). All work under `webapp/backend/`. Run backend gates from that directory using `.venv/bin/python`.

### Task A1: `device_names` table + `DeviceNamesStore`

**Files:**
- Modify: `webapp/backend/../../src` — none. Modify `webapp/backend/experiment_studio/db.py` (append one migration to `MIGRATIONS`).
- Create: `webapp/backend/experiment_studio/device_names.py`
- Test: `webapp/backend/tests/test_device_names.py`

**Interfaces:**
- Produces: `DeviceNamesStore(db: Database)` with `async get_all(lab: str) -> dict[str, str]`, `async set(lab: str, device_id: str, name: str) -> None`, `async clear(lab: str, device_id: str) -> None`.

- [ ] **Step 1: Write the failing test**

Create `webapp/backend/tests/test_device_names.py`:

```python
"""DeviceNamesStore CRUD over a real migrated Database."""

from pathlib import Path

import pytest

from experiment_studio.db import Database
from experiment_studio.device_names import DeviceNamesStore


@pytest.fixture
async def store(tmp_path: Path):
    db = await Database.connect(tmp_path / "studio.db")
    yield DeviceNamesStore(db)
    await db.close()


async def test_set_then_get_all(store: DeviceNamesStore) -> None:
    await store.set("chisel", "pump_1", "Culture pump")
    await store.set("chisel", "pump_2", "Waste pump")
    assert await store.get_all("chisel") == {"pump_1": "Culture pump", "pump_2": "Waste pump"}


async def test_get_all_is_scoped_by_lab(store: DeviceNamesStore) -> None:
    await store.set("chisel", "pump_1", "A")
    await store.set("other", "pump_1", "B")
    assert await store.get_all("chisel") == {"pump_1": "A"}


async def test_set_is_upsert(store: DeviceNamesStore) -> None:
    await store.set("chisel", "pump_1", "First")
    await store.set("chisel", "pump_1", "Second")
    assert await store.get_all("chisel") == {"pump_1": "Second"}


async def test_clear_removes_row(store: DeviceNamesStore) -> None:
    await store.set("chisel", "pump_1", "A")
    await store.clear("chisel", "pump_1")
    assert await store.get_all("chisel") == {}


async def test_get_all_empty_lab_is_empty_dict(store: DeviceNamesStore) -> None:
    assert await store.get_all("nobody") == {}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_device_names.py -q`
Expected: FAIL — `ModuleNotFoundError: experiment_studio.device_names` (and no `device_names` table).

- [ ] **Step 3: Append the migration**

In `webapp/backend/experiment_studio/db.py`, append to the `MIGRATIONS` list (after the existing `mappings` entry, before the closing `]`):

```python
    """
    CREATE TABLE device_names (
        lab TEXT NOT NULL,
        device_id TEXT NOT NULL,
        name TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        PRIMARY KEY (lab, device_id)
    )
    """,
```

- [ ] **Step 4: Write the store**

Create `webapp/backend/experiment_studio/device_names.py`:

```python
"""Operator-chosen device names, keyed per-lab by device_id. See design §7."""

from __future__ import annotations

from datetime import UTC, datetime

from experiment_studio.db import Database


class DeviceNamesStore:
    """DB-backed name lookup. One store per request over the shared connection."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def get_all(self, lab: str) -> dict[str, str]:
        cur = await self._db.conn.execute(
            "SELECT device_id, name FROM device_names WHERE lab = ?", (lab,)
        )
        rows = await cur.fetchall()
        return {row["device_id"]: row["name"] for row in rows}

    async def set(self, lab: str, device_id: str, name: str) -> None:
        await self._db.conn.execute(
            "INSERT INTO device_names (lab, device_id, name, updated_at) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(lab, device_id) DO UPDATE SET "
            "name = excluded.name, updated_at = excluded.updated_at",
            (lab, device_id, name, datetime.now(UTC).isoformat()),
        )
        await self._db.conn.commit()

    async def clear(self, lab: str, device_id: str) -> None:
        await self._db.conn.execute(
            "DELETE FROM device_names WHERE lab = ? AND device_id = ?", (lab, device_id)
        )
        await self._db.conn.commit()
```

- [ ] **Step 5: Run tests + gates**

Run: `.venv/bin/python -m pytest tests/test_device_names.py tests/test_db.py -q && .venv/bin/python -m mypy && .venv/bin/python -m ruff check .`
Expected: PASS (new tests green, existing db tests unaffected, mypy + ruff clean).

- [ ] **Step 6: Commit**

```bash
git add webapp/backend/experiment_studio/db.py webapp/backend/experiment_studio/device_names.py webapp/backend/tests/test_device_names.py
git commit -m "feat(studio): device_names table + DeviceNamesStore"
```

---

### Task A2: name endpoint + name-merge into devices/discover payloads

**Files:**
- Modify: `webapp/backend/experiment_studio/api/labs.py`
- Test: `webapp/backend/tests/test_device_names_api.py`

**Interfaces:**
- Consumes: `DeviceNamesStore` (A1); `get_db` from `experiment_studio.api.deps`; existing `get_labs_service`.
- Produces: `PUT /api/labs/{lab}/devices/{device_id}/name` → `{"name": str | None}`; `GET /api/labs/{lab}/devices` and `POST /api/labs/{lab}/discover` payloads each gain a `name: str | None` field. Module-level helper `_merge_names(devices: list[dict], names: dict[str, str]) -> list[dict]`.

- [ ] **Step 1: Write the failing test**

Create `webapp/backend/tests/test_device_names_api.py`:

```python
"""Name endpoint + name-merge into the devices/discover payloads."""

import httpx
import pytest
from fastapi import FastAPI

from experiment_studio.labs import LabsService
from tests.test_labs_api import (
    AGENT_DEVICES,
    _agent_factory,
    _install,
    _probe_all_online,
    _registry,
)


@pytest.fixture
async def happy_service():
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


async def test_devices_have_null_name_by_default(
    app: FastAPI, client: httpx.AsyncClient, happy_service: LabsService
) -> None:
    _install(app, happy_service)
    resp = await client.get("/api/labs/khamit_desktop/devices")
    assert resp.status_code == 200
    assert all(d["name"] is None for d in resp.json())


async def test_put_name_then_devices_shows_it(
    app: FastAPI, client: httpx.AsyncClient, happy_service: LabsService
) -> None:
    _install(app, happy_service)
    put = await client.put(
        "/api/labs/khamit_desktop/devices/pump_1/name", json={"name": "Culture pump"}
    )
    assert put.status_code == 200
    assert put.json() == {"name": "Culture pump"}

    resp = await client.get("/api/labs/khamit_desktop/devices")
    by_id = {d["id"]: d for d in resp.json()}
    assert by_id["pump_1"]["name"] == "Culture pump"
    assert by_id["valve_2"]["name"] is None


async def test_discover_also_merges_names(
    app: FastAPI, client: httpx.AsyncClient, happy_service: LabsService
) -> None:
    _install(app, happy_service)
    await client.put(
        "/api/labs/khamit_desktop/devices/pump_1/name", json={"name": "Culture pump"}
    )
    resp = await client.post("/api/labs/khamit_desktop/discover")
    by_id = {d["id"]: d for d in resp.json()}
    assert by_id["pump_1"]["name"] == "Culture pump"


async def test_empty_name_clears(
    app: FastAPI, client: httpx.AsyncClient, happy_service: LabsService
) -> None:
    _install(app, happy_service)
    await client.put(
        "/api/labs/khamit_desktop/devices/pump_1/name", json={"name": "Culture pump"}
    )
    cleared = await client.put(
        "/api/labs/khamit_desktop/devices/pump_1/name", json={"name": "   "}
    )
    assert cleared.json() == {"name": None}
    resp = await client.get("/api/labs/khamit_desktop/devices")
    by_id = {d["id"]: d for d in resp.json()}
    assert by_id["pump_1"]["name"] is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_device_names_api.py -q`
Expected: FAIL — `name` key missing / PUT route 404.

- [ ] **Step 3: Implement route changes**

In `webapp/backend/experiment_studio/api/labs.py`:

Add imports at the top (with the others):

```python
from pydantic import BaseModel

from experiment_studio.api.deps import get_db
from experiment_studio.db import Database
from experiment_studio.device_names import DeviceNamesStore
```

Add a body model and the merge helper (module level, after `router = APIRouter()`):

```python
class NameBody(BaseModel):
    name: str


def _merge_names(devices: list[dict[str, Any]], names: dict[str, str]) -> list[dict[str, Any]]:
    for device in devices:
        device["name"] = names.get(device["id"])
    return devices
```

Replace the existing `lab_devices` and `lab_discover` handlers so they merge names, and add the PUT handler:

```python
@router.get("/{lab}/devices")
async def lab_devices(
    lab: str,
    service: LabsService = Depends(get_labs_service),
    db: Database = Depends(get_db),
) -> list[dict[str, Any]]:
    devices = await service.devices(lab)
    names = await DeviceNamesStore(db).get_all(lab)
    return _merge_names(devices, names)


@router.post("/{lab}/discover")
async def lab_discover(
    lab: str,
    service: LabsService = Depends(get_labs_service),
    manager: RunManager = Depends(get_run_manager),
    db: Database = Depends(get_db),
) -> list[dict[str, Any]]:
    active = manager.active()
    if active is not None and active.lab == lab:
        raise RunActiveError(active.run_id)  # §6: 409 while a run is active on that lab
    devices = await service.discover(lab)
    names = await DeviceNamesStore(db).get_all(lab)
    return _merge_names(devices, names)


@router.put("/{lab}/devices/{device_id}/name")
async def set_device_name(
    lab: str,
    device_id: str,
    body: NameBody,
    db: Database = Depends(get_db),
) -> dict[str, str | None]:
    store = DeviceNamesStore(db)
    name = body.name.strip()
    if name:
        await store.set(lab, device_id, name)
        return {"name": name}
    await store.clear(lab, device_id)
    return {"name": None}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_device_names_api.py tests/test_labs_api.py -q`
Expected: PASS. (The existing `test_devices_serialization` asserts an exact dict without `name`; update it: add `"name": None` to the expected `pump` dict in `tests/test_labs_api.py::test_devices_serialization`, and assert `valve["name"] is None`.)

- [ ] **Step 5: Run full backend gates**

Run: `.venv/bin/python -m pytest -q && .venv/bin/python -m mypy && .venv/bin/python -m ruff check .`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add webapp/backend/experiment_studio/api/labs.py webapp/backend/tests/test_device_names_api.py webapp/backend/tests/test_labs_api.py
git commit -m "feat(studio): device name endpoint + name-merge into devices/discover"
```

---

### Task A3: command passthrough endpoint + run-active guard

**Files:**
- Modify: `webapp/backend/experiment_studio/labs.py` (add `command`), `webapp/backend/experiment_studio/api/labs.py` (POST route + body model)
- Test: `webapp/backend/tests/test_device_command_api.py`

**Interfaces:**
- Consumes: `get_labs_service`, `get_run_manager`, `RunActiveError`.
- Produces: `LabsService.command(lab: str, device_id: str, cmd: str, params: dict | None) -> Any`; `POST /api/labs/{lab}/devices/{device_id}/command` body `{cmd: str, params: dict | None}` → `{"result": Any}`, guarded 409 `run_active` when a run is active on `lab`.

- [ ] **Step 1: Write the failing test**

Create `webapp/backend/tests/test_device_command_api.py`. The agent command endpoint is `POST /api/v1/devices/{id}/command`; a canned envelope uses `id: ""` (the transport accepts an empty echoed id).

```python
"""Generic device command passthrough + run-active guard."""

import httpx
import pytest
from fastapi import FastAPI

from experiment_studio.labs import LabsService
from tests.test_labs_api import _agent_factory, _install, _probe_all_online, _registry


def _ok(result: object) -> httpx.Response:
    return httpx.Response(200, json={"id": "", "status": "ok", "result": result})


@pytest.fixture
async def ping_service():
    service = LabsService(
        _registry(),
        client_factory=_agent_factory(
            {"POST /api/v1/devices/pump_1/command": _ok({"uptime_ms": 42133})}
        ),
        probe=_probe_all_online,
    )
    yield service
    await service.aclose()


async def test_command_returns_result(
    app: FastAPI, client: httpx.AsyncClient, ping_service: LabsService
) -> None:
    _install(app, ping_service)
    resp = await client.post(
        "/api/labs/khamit_desktop/devices/pump_1/command",
        json={"cmd": "ping", "params": None},
    )
    assert resp.status_code == 200
    assert resp.json() == {"result": {"uptime_ms": 42133}}


async def test_command_forwards_params(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    seen: dict[str, object] = {}

    def factory(info):
        def handler(request: httpx.Request) -> httpx.Response:
            import json

            seen.update(json.loads(request.content))
            return httpx.Response(200, json={"id": "", "status": "ok", "result": {"job_id": "j1"}})

        http = httpx.AsyncClient(
            transport=httpx.MockTransport(handler), base_url=f"http://{info.host}:{info.port}"
        )
        from lab_devices.client import LabClient

        return LabClient(info.host, info.port, http=http)

    service = LabsService(_registry(), client_factory=factory, probe=_probe_all_online)
    _install(app, service)
    try:
        resp = await client.post(
            "/api/labs/khamit_desktop/devices/pump_1/command",
            json={"cmd": "dispense", "params": {"volume_ml": 10, "direction": "forward"}},
        )
        assert resp.status_code == 200
        assert resp.json() == {"result": {"job_id": "j1"}}
        assert seen["cmd"] == "dispense"
        assert seen["params"] == {"volume_ml": 10, "direction": "forward"}
    finally:
        await service.aclose()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_device_command_api.py -q`
Expected: FAIL — route 404.

- [ ] **Step 3: Add `LabsService.command`**

In `webapp/backend/experiment_studio/labs.py`, add a method to `LabsService`:

```python
    async def command(
        self, lab: str, device_id: str, cmd: str, params: dict[str, Any] | None
    ) -> Any:
        info = await self._registry.lookup(lab)
        async with self._client_factory(info) as client:
            return await client.device(device_id).command(cmd, params)
```

- [ ] **Step 4: Add the POST route**

In `webapp/backend/experiment_studio/api/labs.py`, add a body model (near `NameBody`):

```python
class CommandBody(BaseModel):
    cmd: str
    params: dict[str, Any] | None = None
```

And the route:

```python
@router.post("/{lab}/devices/{device_id}/command")
async def device_command(
    lab: str,
    device_id: str,
    body: CommandBody,
    service: LabsService = Depends(get_labs_service),
    manager: RunManager = Depends(get_run_manager),
) -> dict[str, Any]:
    active = manager.active()
    if active is not None and active.lab == lab:
        raise RunActiveError(active.run_id)  # §6: manual control locked during a run
    result = await service.command(lab, device_id, body.cmd, body.params)
    return {"result": result}
```

- [ ] **Step 5: Add the run-active guard test**

Append to `tests/test_device_command_api.py`. The `api` fixture (conftest) provides a real `RunManager` over a FakeLab; use the run-support helpers to start a run and assert 409. Model this on `tests/test_runs_api.py` — inspect it for the exact "start a run" helper, then:

```python
async def test_command_blocked_during_active_run(api) -> None:
    # api.fake is a FakeLab; start a minimal run on its lab, then attempt a manual command.
    # Follow tests/test_runs_api.py for the concrete start-run call and the lab name
    # (runsupport.default_fake). Once a run is active on that lab:
    resp = await api.client.post(
        f"/api/labs/{RUN_LAB}/devices/pump_1/command",
        json={"cmd": "ping", "params": None},
    )
    assert resp.status_code == 409
    assert resp.json()["code"] == "run_active"
```

Read `tests/test_runs_api.py` and `tests/runsupport.py` to fill `RUN_LAB` and the start-run call concretely (do not leave the placeholder). If wiring a full run in this test proves heavy, an equivalent unit test is acceptable: override `get_run_manager` with a stub whose `active()` returns `SimpleNamespace(lab=RUN_LAB, run_id="r1")` and assert the 409 — the guard logic is what's under test.

- [ ] **Step 6: Run tests + gates**

Run: `.venv/bin/python -m pytest tests/test_device_command_api.py -q && .venv/bin/python -m mypy && .venv/bin/python -m ruff check .`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add webapp/backend/experiment_studio/labs.py webapp/backend/experiment_studio/api/labs.py webapp/backend/tests/test_device_command_api.py
git commit -m "feat(studio): device command passthrough endpoint with run-active guard"
```

---

### Task A4: job-status endpoint

**Files:**
- Modify: `webapp/backend/experiment_studio/labs.py` (add `get_job`), `webapp/backend/experiment_studio/api/labs.py` (GET route)
- Test: `webapp/backend/tests/test_device_command_api.py` (append)

**Interfaces:**
- Produces: `LabsService.get_job(lab, device_id, job_id) -> Any`; `GET /api/labs/{lab}/devices/{device_id}/jobs/{job_id}` → `{"result": Any}`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_device_command_api.py`:

```python
async def test_job_status_returns_result(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    service = LabsService(
        _registry(),
        client_factory=_agent_factory(
            {
                "POST /api/v1/devices/densitometer_1/command": _ok(
                    {"job_id": "j9", "status": "succeeded", "result": {"od": 0.42}}
                )
            }
        ),
        probe=_probe_all_online,
    )
    _install(app, service)
    try:
        resp = await client.get(
            "/api/labs/khamit_desktop/devices/densitometer_1/jobs/j9"
        )
        assert resp.status_code == 200
        assert resp.json()["result"]["status"] == "succeeded"
    finally:
        await service.aclose()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_device_command_api.py::test_job_status_returns_result -q`
Expected: FAIL — route 404.

- [ ] **Step 3: Add `LabsService.get_job`**

In `labs.py`:

```python
    async def get_job(self, lab: str, device_id: str, job_id: str) -> Any:
        info = await self._registry.lookup(lab)
        async with self._client_factory(info) as client:
            return await client.device(device_id).command("get_job", {"job_id": job_id})
```

- [ ] **Step 4: Add the GET route**

In `api/labs.py`:

```python
@router.get("/{lab}/devices/{device_id}/jobs/{job_id}")
async def device_job(
    lab: str,
    device_id: str,
    job_id: str,
    service: LabsService = Depends(get_labs_service),
) -> dict[str, Any]:
    result = await service.get_job(lab, device_id, job_id)
    return {"result": result}
```

- [ ] **Step 5: Run tests + gates**

Run: `.venv/bin/python -m pytest tests/test_device_command_api.py -q && .venv/bin/python -m mypy && .venv/bin/python -m ruff check .`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add webapp/backend/experiment_studio/labs.py webapp/backend/experiment_studio/api/labs.py webapp/backend/tests/test_device_command_api.py
git commit -m "feat(studio): device job-status endpoint"
```

---

### Task A5: meaningful error codes for command failures

**Files:**
- Modify: `webapp/backend/experiment_studio/app.py` (`_ERROR_MAP`)
- Test: `webapp/backend/tests/test_device_command_api.py` (append)

**Interfaces:**
- Produces: command-time lab errors map to distinct `{code, status}` (see spec §6.4).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_device_command_api.py`. An error envelope is `{"id":"","status":"error","error":{...}}`; the exact `error` object shape is mapped by `lab_devices.errors.map_command_error`. Read `src/lab_devices/errors.py` for the discriminator (e.g. an `error`/`code` field) and craft the body that yields `BusyError` and `InvalidParamsError`:

```python
async def test_busy_command_is_409_agent_busy(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    busy = httpx.Response(
        200, json={"id": "", "status": "error", "error": BUSY_ERROR_OBJ}
    )
    service = LabsService(
        _registry(),
        client_factory=_agent_factory({"POST /api/v1/devices/pump_1/command": busy}),
        probe=_probe_all_online,
    )
    _install(app, service)
    try:
        resp = await client.post(
            "/api/labs/khamit_desktop/devices/pump_1/command",
            json={"cmd": "dispense", "params": {"volume_ml": 10}},
        )
        assert resp.status_code == 409
        assert resp.json()["code"] == "agent_busy"
    finally:
        await service.aclose()
```

Define `BUSY_ERROR_OBJ` (and an `INVALID_PARAMS_ERROR_OBJ`) at module top from what `map_command_error` requires; add a parallel `test_invalid_params_command_is_422`.

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_device_command_api.py -k "busy or invalid_params" -q`
Expected: FAIL — currently 502 `lab_error`.

- [ ] **Step 3: Extend `_ERROR_MAP`**

In `webapp/backend/experiment_studio/app.py`, add these tuples to `_ERROR_MAP` **before** the `(lab_errors.LabError, 502, "lab_error")` catch-all:

```python
    (lab_errors.InvalidParamsError, 422, "invalid_params"),
    (lab_errors.InvalidRequestError, 422, "invalid_params"),
    (lab_errors.UnknownCommandError, 400, "unknown_command"),
    (lab_errors.UnknownDeviceError, 404, "unknown_device"),
    (lab_errors.BusyError, 409, "agent_busy"),
    (lab_errors.NotCalibratedError, 409, "not_ready"),
    (lab_errors.NotHomedError, 409, "not_ready"),
    (lab_errors.DeviceUnreachableError, 502, "device_unreachable"),
```

(`JobInProgressError` already maps to 409 `agent_busy`.) Handler registration is the existing `for exc_type, status, code in _ERROR_MAP: app.add_exception_handler(...)` loop; siblings need no ordering beyond preceding the catch-all.

- [ ] **Step 4: Run tests + full gates**

Run: `.venv/bin/python -m pytest -q && .venv/bin/python -m mypy && .venv/bin/python -m ruff check .`
Expected: PASS (all backend tests).

- [ ] **Step 5: Commit**

```bash
git add webapp/backend/experiment_studio/app.py webapp/backend/tests/test_device_command_api.py
git commit -m "feat(studio): meaningful HTTP codes for device command errors"
```

---

### Task A6: PR A — open, CI, merge

- [ ] **Step 1:** Run the full backend gate once more from `webapp/backend/`: `.venv/bin/python -m pytest -q && .venv/bin/python -m mypy && .venv/bin/python -m ruff check .`
- [ ] **Step 2:** Push `feat/devices-control-tab` and open a PR titled `feat(studio): manual device control — backend contract + persistence`. Body: summary + "Part 1 of 2 (spec §10). Frontend follows in a second PR." List the endpoints and the new table.
- [ ] **Step 3:** Wait for CI (all jobs: `test`, `webapp-backend`, `webapp-frontend`, `webapp-image`). The frontend is untouched, so `webapp-frontend` stays green.
- [ ] **Step 4:** On green, merge (squash). Delete the remote branch.

---

# PR B — Frontend

Branch: `feat/devices-control-tab-ui`, created off updated `main` **after PR A merges** (so `LabDevice.name` is real in the API). All work under `webapp/frontend/`. Run frontend gates from that directory.

**File structure (created/modified):**
- Create: `src/devices/catalog.ts`, `src/devices/catalog.test.ts`, `src/devices/buildPayload.ts`, `src/devices/buildPayload.test.ts`, `src/devices/jobStatus.ts`, `src/devices/jobStatus.test.ts`, `src/devices/deviceLabel.ts`, `src/devices/deviceLabel.test.ts`, `src/api/deviceControl.ts`, `src/stores/deviceControlStore.ts`, `src/devices/DevicesTab.tsx`, `src/devices/TypeNav.tsx`, `src/devices/DeviceList.tsx`, `src/devices/NameEditor.tsx`, `src/devices/CommandPanel.tsx`, `src/devices/ParamForm.tsx`, `src/devices/ActivityLog.tsx`.
- Move/rename: `src/devices/DevicesTab.tsx` (old read-only) → `src/labs/LabsTab.tsx` (component `LabsTab`).
- Modify: `src/shell/tabs.ts`, `src/shell/tabs.test.ts`, `src/App.tsx`, `src/shell/urlState.test.ts`, `src/run/PreflightPanel.tsx`, `src/types/labs.ts`, `src/api/labs.ts`, `src/run/preflight.ts` (label helper if roles list device options there).

### Task B1: `LabDevice.name` + API wrappers

**Files:**
- Modify: `src/types/labs.ts`, `src/api/labs.ts`
- Create: `src/api/deviceControl.ts`

**Interfaces:**
- Produces: `LabDevice.name: string | null`; `setDeviceName(lab, id, name) => Promise<{name: string|null}>`; `runCommand(lab, id, cmd, params) => Promise<{result: unknown}>`; `pollJob(lab, id, jobId) => Promise<{result: unknown}>`.

- [ ] **Step 1:** Add `name: string | null` to the `LabDevice` interface in `src/types/labs.ts`.

- [ ] **Step 2:** In `src/api/labs.ts`, add:

```ts
export const setDeviceName = (lab: string, id: string, name: string) =>
  putJson<{ name: string | null }>(
    `/api/labs/${encodeURIComponent(lab)}/devices/${encodeURIComponent(id)}/name`,
    { name },
  )
```

(add `putJson` to the existing import from `./client`).

- [ ] **Step 3:** Create `src/api/deviceControl.ts`:

```ts
import { getJson, postJson } from './client'

export interface CommandResult {
  result: unknown
}

export const runCommand = (
  lab: string,
  id: string,
  cmd: string,
  params: Record<string, unknown> | null,
) =>
  postJson<CommandResult>(
    `/api/labs/${encodeURIComponent(lab)}/devices/${encodeURIComponent(id)}/command`,
    { cmd, params },
  )

export const pollJob = (lab: string, id: string, jobId: string) =>
  getJson<CommandResult>(
    `/api/labs/${encodeURIComponent(lab)}/devices/${encodeURIComponent(id)}/jobs/${encodeURIComponent(jobId)}`,
  )
```

- [ ] **Step 4:** `npm run build` (tsc) to confirm types compile. Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/types/labs.ts src/api/labs.ts src/api/deviceControl.ts
git commit -m "feat(studio): LabDevice.name + device-control API wrappers"
```

---

### Task B2: command catalog + integrity tests

**Files:**
- Create: `src/devices/catalog.ts`, `src/devices/catalog.test.ts`

**Interfaces:**
- Produces: `ParamKind`, `ParamDef`, `CommandDef`, `DeviceType`, `CATALOG: Record<DeviceType, CommandDef[]>`, `LOCATE: Record<DeviceType, { cmd: string; params: Record<string, unknown> }>`, `commandsFor(type: string): CommandDef[]`.

- [ ] **Step 1: Write the failing test**

Create `src/devices/catalog.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import { CATALOG, LOCATE, commandsFor, type CommandDef } from './catalog'

const all: CommandDef[] = Object.values(CATALOG).flat()

describe('catalog integrity', () => {
  it('every device type has the universal info commands', () => {
    for (const cmds of Object.values(CATALOG)) {
      const names = cmds.map((c) => c.cmd)
      expect(names).toEqual(expect.arrayContaining(['ping', 'identify', 'status']))
    }
  })

  it('every param has a valid kind and enum params list options', () => {
    for (const cmd of all) {
      for (const p of cmd.params) {
        expect(['number', 'int', 'enum', 'bool']).toContain(p.kind)
        if (p.kind === 'enum') expect(p.options && p.options.length > 0).toBe(true)
      }
    }
  })

  it('every command has a non-empty label and known category', () => {
    for (const cmd of all) {
      expect(cmd.label.length).toBeGreaterThan(0)
      expect(['info', 'measure', 'actuate', 'cal-config']).toContain(cmd.category)
    }
  })

  it('locate presets reference a real command of that type', () => {
    for (const [type, locate] of Object.entries(LOCATE)) {
      const cmds = CATALOG[type as keyof typeof CATALOG].map((c) => c.cmd)
      expect(cmds).toContain(locate.cmd)
    }
  })

  it('commandsFor returns [] for an unknown type', () => {
    expect(commandsFor('spectrometer')).toEqual([])
  })
})
```

- [ ] **Step 2: Run to verify it fails**

Run: `npx vitest run src/devices/catalog.test.ts`
Expected: FAIL — module not found.

- [ ] **Step 3: Write the catalog**

Create `src/devices/catalog.ts`. Include the universal info commands plus the full per-type surface from `src/lab_devices/devices/*.py` (spec §5). Concretely:

```ts
export type ParamKind = 'number' | 'int' | 'enum' | 'bool'

export interface ParamDef {
  name: string
  label: string
  kind: ParamKind
  unit?: string
  default?: number | string | boolean
  min?: number
  max?: number
  options?: string[]
  required?: boolean
}

export interface CommandDef {
  cmd: string
  label: string
  category: 'info' | 'measure' | 'actuate' | 'cal-config'
  isJob: boolean
  params: ParamDef[]
}

export type DeviceType = 'pump' | 'valve' | 'densitometer'

const UNIVERSAL: CommandDef[] = [
  { cmd: 'ping', label: 'Ping', category: 'info', isJob: false, params: [] },
  { cmd: 'identify', label: 'Identify', category: 'info', isJob: false, params: [] },
  { cmd: 'status', label: 'Status', category: 'info', isJob: false, params: [] },
]

const DIRECTION: ParamDef = {
  name: 'direction', label: 'direction', kind: 'enum',
  options: ['forward', 'reverse'], default: 'forward', required: true,
}

export const CATALOG: Record<DeviceType, CommandDef[]> = {
  pump: [
    ...UNIVERSAL,
    { cmd: 'get_calibration', label: 'Get calibration', category: 'measure', isJob: false, params: [] },
    { cmd: 'dispense', label: 'Dispense', category: 'actuate', isJob: true, params: [
      { name: 'volume_ml', label: 'volume', kind: 'number', unit: 'ml', default: 1, min: 0, required: true },
      { name: 'speed_ml_min', label: 'speed', kind: 'number', unit: 'ml/min', min: 0 },
      DIRECTION,
      { name: 'drop_suckback_ml', label: 'suckback', kind: 'number', unit: 'ml', min: 0 },
    ] },
    { cmd: 'rotate', label: 'Rotate', category: 'actuate', isJob: false, params: [
      DIRECTION,
      { name: 'speed_ml_min', label: 'speed', kind: 'number', unit: 'ml/min', default: 1, min: 0, required: true },
    ] },
    { cmd: 'rotate_raw', label: 'Rotate (raw)', category: 'actuate', isJob: false, params: [
      DIRECTION,
      { name: 'speed_pct', label: 'speed', kind: 'number', unit: '%', default: 10, min: 0, max: 100, required: true },
    ] },
    { cmd: 'pause', label: 'Pause', category: 'actuate', isJob: false, params: [] },
    { cmd: 'resume', label: 'Resume', category: 'actuate', isJob: false, params: [] },
    { cmd: 'start_calibration', label: 'Start calibration', category: 'cal-config', isJob: true, params: [
      { name: 'speed_pct', label: 'speed', kind: 'number', unit: '%', min: 0, max: 100 },
    ] },
    { cmd: 'set_calibration', label: 'Set calibration', category: 'cal-config', isJob: false, params: [
      { name: 'job_id', label: 'job id', kind: 'enum', options: [] }, // free text — see note below
      { name: 'measured_volume_ml', label: 'measured volume', kind: 'number', unit: 'ml', min: 0 },
      { name: 'ml_per_step', label: 'ml/step', kind: 'number', unit: 'ml' },
    ] },
  ],
  valve: [
    ...UNIVERSAL,
    { cmd: 'home', label: 'Home', category: 'actuate', isJob: false, params: [
      { name: 'position', label: 'position', kind: 'int', default: 1, min: 1, required: true },
    ] },
    { cmd: 'set_position', label: 'Set position', category: 'actuate', isJob: true, params: [
      { name: 'position', label: 'position', kind: 'int', default: 1, min: 1, required: true },
      { name: 'rotation', label: 'rotation', kind: 'enum', options: ['cw', 'ccw', 'shortest'] },
    ] },
    { cmd: 'configure', label: 'Configure', category: 'cal-config', isJob: false, params: [
      { name: 'default_rotation', label: 'default rotation', kind: 'enum', options: ['cw', 'ccw', 'shortest'] },
      { name: 'hold_torque', label: 'hold torque', kind: 'bool' },
    ] },
  ],
  densitometer: [
    ...UNIVERSAL,
    { cmd: 'measure', label: 'Measure', category: 'measure', isJob: true, params: [
      { name: 'include_raw', label: 'include raw', kind: 'bool' },
    ] },
    { cmd: 'measure_blank', label: 'Measure blank', category: 'measure', isJob: true, params: [] },
    { cmd: 'get_readings', label: 'Get readings', category: 'measure', isJob: false, params: [
      { name: 'since_seq', label: 'since seq', kind: 'int', min: 0 },
      { name: 'limit', label: 'limit', kind: 'int', min: 1 },
    ] },
    { cmd: 'start_monitoring', label: 'Start monitoring', category: 'actuate', isJob: false, params: [
      { name: 'interval_s', label: 'interval', kind: 'number', unit: 's', min: 0 },
    ] },
    { cmd: 'stop_monitoring', label: 'Stop monitoring', category: 'actuate', isJob: false, params: [] },
    { cmd: 'read_raw', label: 'Read raw', category: 'measure', isJob: true, params: [
      { name: 'level', label: 'LED level', kind: 'int', min: 0, max: 255 },
    ] },
    { cmd: 'set_led', label: 'Set LED', category: 'actuate', isJob: false, params: [
      { name: 'level', label: 'level', kind: 'int', default: 128, min: 0, max: 255, required: true },
    ] },
    { cmd: 'set_thermostat', label: 'Set thermostat', category: 'cal-config', isJob: false, params: [
      { name: 'enabled', label: 'enabled', kind: 'bool', default: true, required: true },
      { name: 'target_c', label: 'target', kind: 'number', unit: '°C' },
    ] },
    { cmd: 'set_tube_correction', label: 'Set tube correction', category: 'cal-config', isJob: false, params: [
      { name: 'factor', label: 'factor', kind: 'number', default: 1, required: true },
    ] },
    { cmd: 'calibrate_tube', label: 'Calibrate tube', category: 'cal-config', isJob: false, params: [
      { name: 'reference_absorbance', label: 'reference absorbance', kind: 'number', default: 0, required: true },
    ] },
  ],
}

export const LOCATE: Record<DeviceType, { cmd: string; params: Record<string, unknown> }> = {
  pump: { cmd: 'dispense', params: { volume_ml: 0.2, direction: 'forward' } },
  valve: { cmd: 'set_position', params: { position: 1 } },
  densitometer: { cmd: 'measure', params: {} },
}

export const commandsFor = (type: string): CommandDef[] =>
  (CATALOG as Record<string, CommandDef[]>)[type] ?? []
```

**Note on `job_id`/free-text params:** `set_calibration`'s `job_id` is a free-text string, not an enum. Add a `'text'` kind to `ParamKind` if a text input is needed — OR drop `job_id` from the manual form (calibration-from-job is an advanced workflow; the two numeric fields cover the common case). Simplest per YAGNI: **remove the `job_id` param** and keep `measured_volume_ml` / `ml_per_step`. Update the test's enum-options rule accordingly (it already passes once `job_id` is gone). If keeping free text, extend `ParamKind` with `'text'` and handle it in `buildPayload` (B3) and `ParamForm` (B8).

- [ ] **Step 4: Run to verify it passes**

Run: `npx vitest run src/devices/catalog.test.ts`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/devices/catalog.ts src/devices/catalog.test.ts
git commit -m "feat(studio): device command catalog (frontend metadata)"
```

---

### Task B3: `buildPayload` — form values → wire params

**Files:**
- Create: `src/devices/buildPayload.ts`, `src/devices/buildPayload.test.ts`

**Interfaces:**
- Produces: `buildPayload(params: ParamDef[], values: Record<string, string>): Record<string, unknown> | null`. Returns the wire object with optional-empty fields omitted and numbers/bools coerced; returns `null` when a required field is empty or a number is unparseable (the form blocks Run).

- [ ] **Step 1: Write the failing test**

Create `src/devices/buildPayload.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import { buildPayload } from './buildPayload'
import type { ParamDef } from './catalog'

const p = (o: Partial<ParamDef> & { name: string; kind: ParamDef['kind'] }): ParamDef => ({
  label: o.name, ...o,
})

describe('buildPayload', () => {
  it('omits optional empty fields, coerces numbers', () => {
    const params = [
      p({ name: 'volume_ml', kind: 'number', required: true }),
      p({ name: 'speed_ml_min', kind: 'number' }),
      p({ name: 'direction', kind: 'enum', options: ['forward'], required: true }),
    ]
    expect(buildPayload(params, { volume_ml: '10', speed_ml_min: '', direction: 'forward' })).toEqual({
      volume_ml: 10,
      direction: 'forward',
    })
  })

  it('coerces int and bool', () => {
    const params = [p({ name: 'position', kind: 'int' }), p({ name: 'enabled', kind: 'bool' })]
    expect(buildPayload(params, { position: '3', enabled: 'true' })).toEqual({ position: 3, enabled: true })
  })

  it('returns null when a required field is empty', () => {
    const params = [p({ name: 'volume_ml', kind: 'number', required: true })]
    expect(buildPayload(params, { volume_ml: '' })).toBeNull()
  })

  it('returns null when a number is unparseable', () => {
    const params = [p({ name: 'volume_ml', kind: 'number', required: true })]
    expect(buildPayload(params, { volume_ml: 'abc' })).toBeNull()
  })

  it('empty params → empty object', () => {
    expect(buildPayload([], {})).toEqual({})
  })
})
```

- [ ] **Step 2: Run to verify it fails.** Run: `npx vitest run src/devices/buildPayload.test.ts` — FAIL (module missing).

- [ ] **Step 3: Implement**

Create `src/devices/buildPayload.ts`:

```ts
import type { ParamDef } from './catalog'

export function buildPayload(
  params: ParamDef[],
  values: Record<string, string>,
): Record<string, unknown> | null {
  const out: Record<string, unknown> = {}
  for (const p of params) {
    const raw = (values[p.name] ?? '').trim()
    if (raw === '') {
      if (p.required) return null
      continue
    }
    if (p.kind === 'number' || p.kind === 'int') {
      const n = Number(raw)
      if (!Number.isFinite(n)) return null
      out[p.name] = p.kind === 'int' ? Math.trunc(n) : n
    } else if (p.kind === 'bool') {
      out[p.name] = raw === 'true'
    } else {
      out[p.name] = raw
    }
  }
  return out
}
```

- [ ] **Step 4: Run to verify it passes.** Run: `npx vitest run src/devices/buildPayload.test.ts` — PASS.

- [ ] **Step 5: Commit**

```bash
git add src/devices/buildPayload.ts src/devices/buildPayload.test.ts
git commit -m "feat(studio): buildPayload — form values to wire params"
```

---

### Task B4: `jobStatus` — classify a raw job dict

**Files:**
- Create: `src/devices/jobStatus.ts`, `src/devices/jobStatus.test.ts`

**Interfaces:**
- Produces: `classifyJob(result: unknown): { phase: 'running' | 'succeeded' | 'failed' | 'cancelled' | 'unknown'; progress: number | null; jobId: string | null; done: boolean }`. Reads `status`/`state`, `progress`, `job_id`/`id` leniently from the raw agent job dict.

- [ ] **Step 1: Write the failing test**

Create `src/devices/jobStatus.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import { classifyJob } from './jobStatus'

describe('classifyJob', () => {
  it('reads a running job with progress', () => {
    expect(classifyJob({ job_id: 'j1', status: 'running', progress: 0.4 })).toEqual({
      phase: 'running', progress: 0.4, jobId: 'j1', done: false,
    })
  })

  it('marks succeeded/failed/cancelled as done', () => {
    expect(classifyJob({ status: 'succeeded' }).done).toBe(true)
    expect(classifyJob({ status: 'failed' }).done).toBe(true)
    expect(classifyJob({ status: 'cancelled' }).done).toBe(true)
  })

  it('unknown shape is unknown+not-done with null progress', () => {
    expect(classifyJob({})).toEqual({ phase: 'unknown', progress: null, jobId: null, done: false })
    expect(classifyJob(null)).toEqual({ phase: 'unknown', progress: null, jobId: null, done: false })
  })

  it('accepts state as an alias for status and id for job_id', () => {
    const c = classifyJob({ id: 'j2', state: 'running' })
    expect(c.jobId).toBe('j2')
    expect(c.phase).toBe('running')
  })
})
```

- [ ] **Step 2: Run to verify it fails.** `npx vitest run src/devices/jobStatus.test.ts` — FAIL.

- [ ] **Step 3: Implement**

Create `src/devices/jobStatus.ts`:

```ts
export type JobPhase = 'running' | 'succeeded' | 'failed' | 'cancelled' | 'unknown'

export interface JobClass {
  phase: JobPhase
  progress: number | null
  jobId: string | null
  done: boolean
}

const TERMINAL: JobPhase[] = ['succeeded', 'failed', 'cancelled']

export function classifyJob(result: unknown): JobClass {
  const r = (result ?? {}) as Record<string, unknown>
  const rawStatus = typeof r.status === 'string' ? r.status : typeof r.state === 'string' ? r.state : null
  const phase: JobPhase =
    rawStatus === 'running' || rawStatus === 'pending' ? 'running'
    : rawStatus === 'succeeded' || rawStatus === 'ok' || rawStatus === 'done' ? 'succeeded'
    : rawStatus === 'failed' || rawStatus === 'error' ? 'failed'
    : rawStatus === 'cancelled' || rawStatus === 'canceled' ? 'cancelled'
    : 'unknown'
  const progress = typeof r.progress === 'number' ? r.progress : null
  const jobId = typeof r.job_id === 'string' ? r.job_id : typeof r.id === 'string' ? r.id : null
  return { phase, progress, jobId, done: TERMINAL.includes(phase) }
}
```

- [ ] **Step 4: Run to verify it passes.** `npx vitest run src/devices/jobStatus.test.ts` — PASS.

- [ ] **Step 5: Commit**

```bash
git add src/devices/jobStatus.ts src/devices/jobStatus.test.ts
git commit -m "feat(studio): classifyJob — lenient job-status reader"
```

---

### Task B5: `deviceLabel` — name-aware option/label text

**Files:**
- Create: `src/devices/deviceLabel.ts`, `src/devices/deviceLabel.test.ts`

**Interfaces:**
- Produces: `deviceLabel(d: { id: string; name: string | null }): string` → `"<name> — <id>"` when named, else `id`.

- [ ] **Step 1: Write the failing test**

Create `src/devices/deviceLabel.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import { deviceLabel } from './deviceLabel'

describe('deviceLabel', () => {
  it('uses "name — id" when named', () => {
    expect(deviceLabel({ id: 'pump_1', name: 'Culture pump' })).toBe('Culture pump — pump_1')
  })
  it('falls back to the bare id', () => {
    expect(deviceLabel({ id: 'pump_1', name: null })).toBe('pump_1')
    expect(deviceLabel({ id: 'pump_1', name: '' })).toBe('pump_1')
  })
})
```

- [ ] **Step 2: Run to verify it fails.** FAIL.

- [ ] **Step 3: Implement** `src/devices/deviceLabel.ts`:

```ts
export const deviceLabel = (d: { id: string; name: string | null }): string =>
  d.name ? `${d.name} — ${d.id}` : d.id
```

- [ ] **Step 4: Run to verify it passes.** PASS.

- [ ] **Step 5: Commit**

```bash
git add src/devices/deviceLabel.ts src/devices/deviceLabel.test.ts
git commit -m "feat(studio): deviceLabel — name-aware device label"
```

---

### Task B6: rename Devices → Labs (tab + roster Name column + Run propagation)

**Files:**
- Move: `src/devices/DevicesTab.tsx` → `src/labs/LabsTab.tsx` (component `DevicesTab` → `LabsTab`)
- Modify: `src/shell/tabs.ts`, `src/shell/tabs.test.ts`, `src/App.tsx`, `src/shell/urlState.test.ts`, `src/run/PreflightPanel.tsx`

**Interfaces:**
- Consumes: `deviceLabel` (B5), `LabDevice.name` (B1).
- Produces: `TABS = ['Builder', 'Labs', 'Devices', 'Run', 'Records']`; `LabsTab` component; Run dropdown shows names.

- [ ] **Step 1: Update the tab test first (it will fail)**

In `src/shell/tabs.test.ts:8`, change the expectation to:

```ts
expect([...TABS]).toEqual(['Builder', 'Labs', 'Devices', 'Run', 'Records'])
```

Run: `npx vitest run src/shell/tabs.test.ts` — FAIL (still the old array).

- [ ] **Step 2: Update `tabs.ts`**

In `src/shell/tabs.ts`:

```ts
export const TABS = ['Builder', 'Labs', 'Devices', 'Run', 'Records'] as const
```

and extend `LAB_SCOPED` to the exhaustive record:

```ts
const LAB_SCOPED: Record<Tab, boolean> = {
  Builder: false,
  Labs: false,
  Devices: false,
  Run: true,
  Records: false,
}
```

Update the module doc comment: `Labs` is the picker (pill redundant — it names the lab in its own heading); the new `Devices` control tab is `false` for the same reason (its header bar carries an inline lab switcher), per the documented "does the pill tell the user something the body doesn't?" test.

Run: `npx vitest run src/shell/tabs.test.ts` — PASS.

- [ ] **Step 3: Move the read-only tab to `labs/LabsTab.tsx`**

Create `src/labs/LabsTab.tsx` with the exact contents of the current `src/devices/DevicesTab.tsx`, renaming the component `export function DevicesTab()` → `export function LabsTab()`. Add a **Name** column to the device table: a `<th>Name</th>` after `id`, and a `<td>` per row rendering `d.name ?? '—'` (`text-caption` when present, `text-hint` dash when null). Keep the read-only nature — naming/editing lives in the new Devices tab, this column is display-only. Delete `src/devices/DevicesTab.tsx` (it is replaced in Task B8).

- [ ] **Step 4: Update `App.tsx`**

- Replace `import { DevicesTab } from './devices/DevicesTab'` region: add `import { LabsTab } from './labs/LabsTab'` (keep a `DevicesTab` import — it will point at the NEW control tab created in B8; until B8 lands, temporarily import `LabsTab` for both or stub — but since tasks land in order, create a minimal `src/devices/DevicesTab.tsx` placeholder in this task that renders `null`, replaced in B8).
- In the render block, add `{tab === 'Labs' && <LabsTab />}` and keep `{tab === 'Devices' && <DevicesTab />}`.

Placeholder for `src/devices/DevicesTab.tsx` (this task only; B8 replaces it):

```tsx
export function DevicesTab() {
  return null
}
```

- [ ] **Step 5: Update `PreflightPanel.tsx`**

- Line ~98: `setTab('Devices')` → `setTab('Labs')`, button text `Go to Devices` → `Go to Labs`.
- Role-mapping dropdown option: import `deviceLabel` and render `{deviceLabel(d)}` instead of `{d.id}` for each option (`src/run/PreflightPanel.tsx` option map, ~line 173). If `src/run/preflight.ts`'s `buildMappingRows` exposes device options as bare objects with `id`, ensure they carry `name` (they come from `LabDevice`, which now has `name`).

- [ ] **Step 6: Update `urlState.test.ts`**

Add a case asserting `#/labs` → `{ tab: 'Labs' }` alongside the existing `#/devices` → `{ tab: 'Devices' }` (both slugs are auto-derived from `TABS`, so this just documents the new slug).

- [ ] **Step 7: Gates + capture**

Run: `npm run lint && npm test && npm run build`
Expected: PASS. Then `npm run capture` and confirm the Labs roster's new Name column raises no R4/R5 findings.

- [ ] **Step 8: Commit**

```bash
git add src/shell/tabs.ts src/shell/tabs.test.ts src/labs/LabsTab.tsx src/devices/DevicesTab.tsx src/App.tsx src/run/PreflightPanel.tsx src/shell/urlState.test.ts
git commit -m "feat(studio): rename Devices tab to Labs, add Name column + Run name propagation"
```

---

### Task B7: `deviceControlStore` — selection, command run, job poll, activity log

**Files:**
- Create: `src/stores/deviceControlStore.ts`

**Interfaces:**
- Consumes: `runCommand`, `pollJob` (B1); `classifyJob` (B4); `LOCATE` (B2).
- Produces: a Zustand store with `selectedId: string | null`, `activity: ActivityEntry[]`, `busy: boolean`, and actions `select(id)`, `run(lab, id, cmd, params, isJob)`, `stop(lab, id)`, `locate(lab, device)`, `clearActivity()`. `ActivityEntry = { at: string; device: string; cmd: string; state: 'started'|'running'|'ok'|'error'; detail: string; progress: number | null }`.

- [ ] **Step 1:** Create the store. It is mostly async wiring (not unit-tested here — the pure logic it depends on is already covered by B3/B4). Key behaviors:
  - `run(...)`: append a `started` entry; `await runCommand(...)`; if `isJob`, read `jobId` via `classifyJob(res.result)`, then poll `pollJob` on a ~1s loop (`setTimeout`), updating a `running` entry with `progress` until `classifyJob(...).done`, then finalize `ok`/`error`; else finalize `ok` immediately with a compact `detail` (e.g. `JSON` of the result, truncated). On thrown `ApiError`, finalize `error` with `code + message`.
  - Only one poll loop at a time: keep a monotonically increasing `pollGen`; a superseding `run`/`stop` bumps it and stale ticks return early.
  - `stop(lab, id)`: `await runCommand(lab, id, 'stop', null)`, append an entry; bump `pollGen`.
  - `locate(lab, device)`: look up `LOCATE[device.type]`; `run(lab, device.id, locate.cmd, locate.params, isJobForThatCmd)` — resolve `isJob` from the catalog entry.
  - `busy` guards double-submits (disable Run while a command is in flight for the selected device).

```ts
import { create } from 'zustand'
import { ApiError } from '../api/client'
import { pollJob, runCommand } from '../api/deviceControl'
import { CATALOG, LOCATE, type DeviceType } from './../devices/catalog'
import { classifyJob } from './../devices/jobStatus'

export interface ActivityEntry {
  at: string
  device: string
  cmd: string
  state: 'started' | 'running' | 'ok' | 'error'
  detail: string
  progress: number | null
}

interface DeviceControlState {
  selectedId: string | null
  activity: ActivityEntry[]
  busy: boolean
  select: (id: string | null) => void
  run: (lab: string, id: string, cmd: string, params: Record<string, unknown> | null, isJob: boolean) => Promise<void>
  stop: (lab: string, id: string) => Promise<void>
  clearActivity: () => void
}

// NOTE: timestamps come from Date at call time in the browser (this store never runs under
// the workflow sandbox). Use `new Date().toISOString()` for `at`.
```

Implement the store body with the poll loop as described. Truncate result detail to ~200 chars. `clearActivity` resets to `[]`.

- [ ] **Step 2:** `npm run build` — PASS (types compile).

- [ ] **Step 3: Commit**

```bash
git add src/stores/deviceControlStore.ts
git commit -m "feat(studio): deviceControlStore — command run + job poll + activity log"
```

---

### Task B8: the Devices control tab UI

**Files:**
- Replace: `src/devices/DevicesTab.tsx` (the B6 placeholder)
- Create: `src/devices/TypeNav.tsx`, `src/devices/DeviceList.tsx`, `src/devices/NameEditor.tsx`, `src/devices/CommandPanel.tsx`, `src/devices/ParamForm.tsx`, `src/devices/ActivityLog.tsx`

**Interfaces:**
- Consumes: `useLabsStore` (lab + devices), `useRunStore` (phase/lab for the lock), `deviceControlStore` (B7), `catalog`/`buildPayload` (B2/B3), `setDeviceName` (B1), `deviceLabel` (B5), `controlClass`/`inlineButtonClass` (`src/ui/controls.ts`), `IconButton` + lucide icons.

- [ ] **Step 1: `DevicesTab.tsx`** — composition + header + lock:
  - On mount: `useLabsStore.getState().refreshLabs()`; if a lab is selected, `refreshDevices()`; and if `useRunStore.getState().phase === 'unknown'`, call `useRunStore.getState().attach()` so the lock signal is accurate.
  - Header bar: a compact lab `<select>` bound to `useLabsStore` `selected`/`selectLab` (built with `controlClass()`), an online dot, a Refresh `IconButton`.
  - Lock: `const locked = useRunStore((s) => s.phase === 'active' && s.lab === lab)`. When `locked`, render an amber banner ("A run is active on {lab} — manual control is locked.") and render the body with `pointer-events-none opacity-50`.
  - Body: left `<TypeNav/>`, right `<DeviceList/>` + `<CommandPanel/>` + `<ActivityLog/>`.
  - Empty states: no lab → dashed "Pick a lab" card (mirror LabsTab's copy); lab but no devices of any type → hint.

- [ ] **Step 2: `TypeNav.tsx`** — derive types present: `const types = [...new Set((devices ?? []).map((d) => d.type))]`; render one button per type with a count; selected type is local state lifted to `DevicesTab`. Use state hue (blue) for the selected type button, slate for the rest.

- [ ] **Step 3: `DeviceList.tsx`** — for the selected type, list devices: a radio (`name="device-target"`) bound to `deviceControlStore.selectedId`/`select`, the `id` (font-mono), a `<NameEditor/>`, connection badge (reuse LabsTab's connected/disconnected pill classes), and a **Locate** `inlineButtonClass()` button calling `deviceControlStore.locate(lab, device)`.

- [ ] **Step 4: `NameEditor.tsx`** — inline editable name. Display the name (or a "name…" hint) with an edit `IconButton` (lucide `Pencil`). In edit mode: a `controlClass()` text input, Save (`Check`) / Cancel (`X`) `IconButton`s; Save calls `setDeviceName(lab, id, value)` then `useLabsStore.getState().refreshDevices()` to re-pull the merged name. Optimistic is unnecessary — the refresh is cheap. Errors surface inline (`text-red-600`).

- [ ] **Step 5: `CommandPanel.tsx`** — for the selected device (from `deviceControlStore.selectedId` resolved against `devices`): a header with the device label + an always-visible **Stop** button (`inlineButtonClass()`, red state hue) calling `deviceControlStore.stop(lab, id)`. Below, commands grouped by category (Info / Measure / Actuate / Cal-Config) from `commandsFor(device.type)`, each a button. Selecting a command (local state) with params reveals `<ParamForm/>`; a no-param command shows a single **Run** button. Run is disabled while `deviceControlStore.busy`.

- [ ] **Step 6: `ParamForm.tsx`** — render one control per `ParamDef` via `controlClass()`: `number`/`int` → `<input type="text" inputMode="decimal">` (keep it a text input so `buildPayload` owns coercion), `enum` → `<select>` of `options`, `bool` → `<select>` of true/false. Track values in a `Record<string,string>`; seed from `default`. On **Run**: `const payload = buildPayload(cmd.params, values)`; if `null`, show "fill required fields" and keep Run disabled; else `deviceControlStore.run(lab, id, cmd.cmd, payload, cmd.isJob)`. Show each param's `unit` as a suffix label. Widths via `controlClass({ width: 'w-28' })` — never concatenated.

- [ ] **Step 7: `ActivityLog.tsx`** — render `deviceControlStore.activity` newest-first: timestamp (`text-hint`), device (font-mono), cmd, and a state chip (`started`/`running` blue, `ok` emerald, `error` red) + `detail`; show `progress` as `Math.round(progress*100)%` when present. A "Clear" `inlineButtonClass()` button calls `clearActivity()`. Empty state: `text-hint` "No commands run yet."

- [ ] **Step 8: Gates + capture**

Run: `npm run lint && npm test && npm run build`
Expected: PASS. Then `npm run capture`. Fix any R4 (sibling-height) or R5 (contrast) findings on the new panels — heights must all come from `controlClass()`/`inlineButtonClass()`; state chips must clear 4.5:1. Re-run capture until clean.

- [ ] **Step 9: Commit**

```bash
git add src/devices/
git commit -m "feat(studio): manual device control tab UI"
```

---

### Task B9: PR B — full gates, open, CI, merge

- [ ] **Step 1:** From `webapp/frontend/`: `npm run lint && npm test && npm run build && npm run capture`. All green; capture clean.
- [ ] **Step 2:** Manually sanity-check the dev server if convenient (`npm run dev`) — pick a lab, name a device, run `ping`, run a job command, hit Stop. (Optional; not a gate.)
- [ ] **Step 3:** Push `feat/devices-control-tab-ui`, open a PR titled `feat(studio): manual device control tab (UI)`. Body: summary + "Part 2 of 2 (spec §10). Backend merged in <PR A #>."
- [ ] **Step 4:** Wait for CI (all jobs). On green, merge (squash). Delete the remote branch.

---

## Self-Review

**Spec coverage:**
- §3 tabs/placement → B6 (rename, TABS, LAB_SCOPED, App, PreflightPanel, urlState).
- §4 layout/interaction → B8 (all subcomponents), header lock in B8/§8 uses runStore.
- §5 catalog → B2; param forms → B8 ParamForm; buildPayload omit-empty → B3.
- §6 backend command/job/stop/guard/errors → A3, A4, A5.
- §7 naming store/endpoint/propagation → A1, A2 (+ B1 type, B6 roster column & Run label).
- §8 execution model (fire+poll, stop, lock) → B7 store + B8 tab.
- §9 testing → each task's TDD steps + capture gates.
- §10 two sequential PRs → A6, B9.

**Placeholder scan:** One deliberate "fill concretely from test_runs_api.py" note in A3 Step 5 (the run-active test's start-run call) — flagged with an acceptable stub fallback, not left blank. B2 Step 3 resolves the `job_id`/free-text question explicitly (drop it). No other TBDs.

**Type consistency:** `LabDevice.name: string | null` (B1) is consumed by `deviceLabel` (B5), LabsTab column (B6), Run dropdown (B6). `CommandDef.isJob` (B2) drives `deviceControlStore.run(..., isJob)` (B7) and the poll decision (B4 `classifyJob`). `buildPayload` returns `Record<string,unknown> | null` (B3), consumed by ParamForm (B8) and passed as `params` to `runCommand` (B1). Backend `{"result": ...}` (A3/A4) matches `CommandResult.result` (B1). Names consistent across tasks.
