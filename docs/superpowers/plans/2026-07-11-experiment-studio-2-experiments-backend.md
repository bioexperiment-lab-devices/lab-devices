# Experiment Studio W2 — Experiments Backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** The experiments backend of Experiment Studio — SQLite data layer, experiment-document
CRUD, roles module (placeholder + real substitution), and stateless `POST /api/validate` with
doc-level checks mapped onto engine diagnostics.

**Architecture:** New modules `db.py` (aiosqlite + `PRAGMA user_version` migrations),
`roles.py` (pure dict-walking substitution + doc-level role checks), `docs_store.py`
(pydantic doc model, CRUD store, validation orchestration), and two routers
(`api/experiments.py`, `api/validate.py`) wired into the existing W1 FastAPI app. The engine
(`lab_devices.experiment`) is consumed as-is: role-named workflows are substituted to
placeholder device ids on a deep copy **before** `workflow_from_dict` (parse-time
`lookup(device, verb)` makes this load-bearing), then `validate()` diagnostics pass through
verbatim.

**Tech Stack:** Python 3.11+, FastAPI, pydantic v2, aiosqlite, pytest(-asyncio auto mode),
mypy --strict, ruff (line 100).

**Parent docs:** design spec `docs/superpowers/specs/2026-07-11-experiment-studio-webapp-design.md`
(§4, §5, §6, §8.1, §11, W2 row of §12).

## Global Constraints

- Work happens ONLY under `webapp/` + the two root files named in Task 1 (`.gitignore`,
  spec amendment in Task 5). The root library (`src/`, root `pyproject.toml`) is untouched.
- All gate commands run from `webapp/backend/` using **its own venv** (`webapp/backend/.venv`,
  NOT the root `.venv`). If missing: `python3 -m venv .venv && .venv/bin/pip install -e ../.. -e '.[dev]'`.
- Gates per task: `.venv/bin/python -m pytest -q` && `.venv/bin/python -m mypy`
  && `.venv/bin/python -m ruff check .` — all clean before every commit.
- Line length ≤ 100 EVERYWHERE (ruff's default select does not include E501 — check with
  `find experiment_studio tests -name '*.py' | xargs awk 'length>100'` → expect no output).
- Source modules start with `from __future__ import annotations` + a one-line docstring citing
  the design §. Test files: no future-import, plain asserts, pytest-asyncio auto mode (already
  configured — async test functions need no decorators).
- Structured API errors are `{detail, code}` via the existing `_ERROR_MAP` pattern in `app.py`.
- Engine names used here are all importable from `lab_devices.experiment` (verified):
  `workflow_from_dict`, `validate`, `verb_catalog`, `Diagnostic` (frozen dataclass:
  `category`, `path`, `message`), `ValidationError` (`.diagnostics` tuple),
  `WorkflowLoadError`, `ExpressionError`, `SCHEMA_VERSION == 1`.

## Settled decisions (this plan; kept out of the user's way per workflow prefs)

| # | Decision |
|---|---|
| P1 | Migration 1 creates ONLY `experiments`; `records`/`mappings` arrive with W4 as appended migrations (append-only list, `PRAGMA user_version` counts applied entries). |
| P2 | Doc-level diagnostics use `category: "roles"`. Role-definition issues get path `roles['<name>']`; an unknown role referenced by a block is reported at the referencing block's structural path (engine grammar, e.g. `blocks[0].children[1]`). |
| P3 | If any doc-level diagnostics exist, the engine parse/validate phase is skipped (substitution is unsound; engine output would duplicate or confuse). Response is still `{ok, diagnostics}`. |
| P4 | Engine parse failures (`WorkflowLoadError`, `ExpressionError` — load errors carry no structural path) map to ONE diagnostic `{category: "schema", path: "workflow", message: str(exc)}`. |
| P5 | Docs are stored pydantic-normalized (`model_dump_json()`): unknown extra keys dropped, `description` explicit `null`. Saving never runs semantic validation (spec §4.3: validation gates running, not saving) — only doc *shape* is enforced (422 via pydantic). |
| P6 | Duplicate names the copy `"<name> (copy)"`, then `"<name> (copy 2)"`, `"(copy 3)"`, … first free wins. |
| P7 | `experiments.name` column mirrors `doc.name`; UNIQUE constraint violation maps to 409 `name_conflict`. Unknown id → 404 `unknown_experiment`. |
| P8 | `GET /api/experiments` returns summaries (`id, name, description, created_at, updated_at`, no `doc`), ordered `updated_at DESC`. Full rows (`… + doc`) come from GET-by-id and all mutating endpoints. |
| P9 | `Settings.data_dir` code default stays `Path("/data")` (spec §5); the image pins `ENV STUDIO_DATA_DIR=/data`; dev README prefixes `STUDIO_DATA_DIR=data` (repo-ignored). |
| P10 | Lifespan connects the DB eagerly at startup (migrations at boot; W4's crash sweep hooks here later) and closes it on shutdown. `get_store` also lazily connects for lifespan-less contexts (httpx ASGITransport tests); test conftest closes any lazily-opened DB. |
| P11 | Timestamps are `datetime.now(UTC).isoformat()` strings; ids are `str(uuid.uuid4())`. |
| P12 | **Engine grammar correction:** the spec's §2(S4)/§9.3 window examples (`od[-5:]`, `od[30s]`) are not the engine grammar; the real forms are `mean(od, last=3)` / `mean(od, last=30s)` (verified: `od[-3:]` raises `ExpressionError`). Fixtures/tests use the real grammar; Task 5 amends the spec text (engine specs win per spec header). |

## File structure

```
webapp/backend/experiment_studio/
  db.py               # NEW  Database: aiosqlite connect + user_version migrations
  roles.py            # NEW  role checks, placeholder ids, dict-level substitution
  docs_store.py       # NEW  ExperimentDoc model, ExperimentsStore CRUD, validate_doc
  config.py           # MOD  + data_dir
  app.py              # MOD  + routers, error-map entries, db lifespan, app.state.settings
  api/experiments.py  # NEW  CRUD + duplicate router, get_store dependency
  api/validate.py     # NEW  POST /api/validate
webapp/backend/tests/
  conftest.py         # MOD  tmp data_dir + db teardown
  test_db.py          # NEW
  test_roles.py       # NEW
  test_docs_store.py  # NEW
  test_experiments_api.py  # NEW
  test_validate_api.py     # NEW
webapp/fixtures/      # NEW  golden doc-v1 fixtures (shared with W3 frontend tests)
  valid-od-growth.json
  invalid-roles.json
  invalid-workflow.json
webapp/backend/pyproject.toml  # MOD  + aiosqlite
webapp/Dockerfile              # MOD  + ENV STUDIO_DATA_DIR=/data
webapp/README.md               # MOD  dev run line + data dir note
.gitignore                     # MOD  + webapp/backend/data/
```

---

### Task 1: Data-dir setting + SQLite layer (`db.py`)

**Files:**
- Modify: `webapp/backend/experiment_studio/config.py`
- Create: `webapp/backend/experiment_studio/db.py`
- Modify: `webapp/backend/pyproject.toml` (aiosqlite dep)
- Modify: `webapp/Dockerfile`, `webapp/README.md`, `.gitignore`
- Test: `webapp/backend/tests/test_db.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `Settings(static_dir: Path | None = None, data_dir: Path = Path("/data"))` with
  `Settings.from_env()` reading `STUDIO_DATA_DIR`; `Database` with
  `async classmethod connect(path: Path) -> Database`, property `conn -> aiosqlite.Connection`,
  `async close() -> None`; module constant `MIGRATIONS: list[str]`.

- [ ] **Step 1: Add aiosqlite dependency and reinstall**

In `webapp/backend/pyproject.toml` extend `[project] dependencies`:

```toml
dependencies = [
    "bioexperiment-lab-devices",
    "fastapi>=0.115",
    "uvicorn[standard]>=0.30",
    "aiosqlite>=0.20",
]
```

Run: `cd webapp/backend && .venv/bin/pip install -e '.[dev]'`

- [ ] **Step 2: Write the failing tests**

Create `webapp/backend/tests/test_db.py`:

```python
"""Database migration behavior (design §8.1)."""

from pathlib import Path

from experiment_studio.db import MIGRATIONS, Database


async def test_connect_applies_migrations_and_sets_user_version(tmp_path: Path) -> None:
    db = await Database.connect(tmp_path / "studio.db")
    try:
        cur = await db.conn.execute("PRAGMA user_version")
        row = await cur.fetchone()
        assert row is not None and row[0] == len(MIGRATIONS)
        cur = await db.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='experiments'"
        )
        assert await cur.fetchone() is not None
    finally:
        await db.close()


async def test_reconnect_is_idempotent(tmp_path: Path) -> None:
    first = await Database.connect(tmp_path / "studio.db")
    await first.close()
    second = await Database.connect(tmp_path / "studio.db")  # would raise if CREATE re-ran
    try:
        cur = await second.conn.execute("PRAGMA user_version")
        row = await cur.fetchone()
        assert row is not None and row[0] == len(MIGRATIONS)
    finally:
        await second.close()


async def test_connect_creates_parent_directory(tmp_path: Path) -> None:
    db = await Database.connect(tmp_path / "nested" / "dir" / "studio.db")
    try:
        assert (tmp_path / "nested" / "dir" / "studio.db").exists()
    finally:
        await db.close()
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd webapp/backend && .venv/bin/python -m pytest tests/test_db.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'experiment_studio.db'`

- [ ] **Step 4: Implement `db.py` and the settings change**

Create `webapp/backend/experiment_studio/db.py`:

```python
"""aiosqlite connection with hand-rolled PRAGMA user_version migrations. See design §8.1."""

from __future__ import annotations

from pathlib import Path

import aiosqlite

# Append-only: user_version counts applied entries. W4 appends records/mappings tables.
MIGRATIONS: list[str] = [
    """
    CREATE TABLE experiments (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL UNIQUE,
        doc TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
]


class Database:
    """One aiosqlite connection; aiosqlite already serializes statements onto its thread."""

    def __init__(self, conn: aiosqlite.Connection) -> None:
        self._conn = conn

    @property
    def conn(self) -> aiosqlite.Connection:
        return self._conn

    @classmethod
    async def connect(cls, path: Path) -> Database:
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = await aiosqlite.connect(path)
        conn.row_factory = aiosqlite.Row
        db = cls(conn)
        await db._migrate()
        return db

    async def _migrate(self) -> None:
        cur = await self._conn.execute("PRAGMA user_version")
        row = await cur.fetchone()
        version = int(row[0]) if row is not None else 0
        for i, statement in enumerate(MIGRATIONS[version:], start=version + 1):
            await self._conn.execute(statement)
            await self._conn.execute(f"PRAGMA user_version = {i}")
            await self._conn.commit()

    async def close(self) -> None:
        await self._conn.close()
```

Replace `webapp/backend/experiment_studio/config.py` with:

```python
"""Runtime settings resolved from environment variables. See webapp design §5."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    static_dir: Path | None = None
    data_dir: Path = Path("/data")

    @classmethod
    def from_env(cls) -> Settings:
        raw = os.environ.get("STUDIO_STATIC_DIR")
        static = Path(raw) if raw else None
        if static is not None and not static.is_dir():
            static = None
        return cls(
            static_dir=static,
            data_dir=Path(os.environ.get("STUDIO_DATA_DIR") or "/data"),
        )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd webapp/backend && .venv/bin/python -m pytest tests/test_db.py -q`
Expected: 3 passed

- [ ] **Step 6: Deployment/dev plumbing**

In `webapp/Dockerfile`, after the `ENV STUDIO_STATIC_DIR=/app/static` line add:

```dockerfile
ENV STUDIO_DATA_DIR=/data
```

In `webapp/README.md`, replace the uvicorn dev line with:

```
    STUDIO_DATA_DIR=data .venv/bin/python -m uvicorn --factory experiment_studio.app:create_app --reload
```

and add below the dev-setup block: `SQLite + run artifacts land in $STUDIO_DATA_DIR (default /data; use a repo-ignored ./data in dev).`

In root `.gitignore` append:

```
webapp/backend/data/
```

- [ ] **Step 7: Full gates**

Run from `webapp/backend`: `.venv/bin/python -m pytest -q && .venv/bin/python -m mypy && .venv/bin/python -m ruff check . && find experiment_studio tests -name '*.py' | xargs awk 'length>100'`
Expected: all tests pass, mypy clean, ruff clean, awk prints nothing

- [ ] **Step 8: Commit**

```bash
git add webapp/backend/experiment_studio/db.py webapp/backend/experiment_studio/config.py \
  webapp/backend/tests/test_db.py webapp/backend/pyproject.toml webapp/Dockerfile \
  webapp/README.md .gitignore
git commit -m "feat(studio): sqlite data layer with user_version migrations"
```

---

### Task 2: Roles module — checks, placeholders, substitution

**Files:**
- Create: `webapp/backend/experiment_studio/roles.py`
- Test: `webapp/backend/tests/test_roles.py`

**Interfaces:**
- Consumes: nothing from other tasks (pure functions over plain dicts).
- Produces (used by Task 5's `validate_doc`, and by W4's RunManager for real substitution):
  - `ROLE_NAME_RE: re.Pattern[str]` — `[a-z][a-z0-9_]*` fullmatch
  - `role_diagnostics(roles: dict[str, str], device_types: set[str]) -> list[dict[str, str]]`
    — `roles` maps role name → device type; returns `{category, path, message}` dicts
  - `placeholder_ids(roles: dict[str, str]) -> dict[str, str]` — role → `f"{type}_{i}"`,
    i counting per type in insertion order
  - `substitute(workflow: dict[str, Any], mapping: dict[str, str]) -> tuple[dict[str, Any], list[dict[str, str]]]`
    — deep-copied workflow with `device` fields swapped; diagnostics for unknown roles

- [ ] **Step 1: Write the failing tests**

Create `webapp/backend/tests/test_roles.py`:

```python
"""Role checks + placeholder/real substitution (design §4.2-4.3)."""

from typing import Any

from experiment_studio.roles import placeholder_ids, role_diagnostics, substitute


def test_placeholder_ids_count_per_type_in_insertion_order() -> None:
    roles = {"feed": "pump", "od": "densitometer", "waste": "pump"}
    assert placeholder_ids(roles) == {
        "feed": "pump_0",
        "od": "densitometer_0",
        "waste": "pump_1",
    }


def test_role_diagnostics_name_shape_and_unknown_type() -> None:
    diags = role_diagnostics({"Feed_Pump": "pump", "mixer": "stirrer"}, {"pump"})
    assert diags == [
        {
            "category": "roles",
            "path": "roles['Feed_Pump']",
            "message": "role name 'Feed_Pump' must match [a-z][a-z0-9_]*",
        },
        {
            "category": "roles",
            "path": "roles['mixer']",
            "message": "unknown device type 'stirrer'",
        },
    ]


def test_role_diagnostics_clean() -> None:
    assert role_diagnostics({"feed_pump": "pump"}, {"pump"}) == []


def _workflow() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "streams": {"od": {"units": "AU"}},
        "groups": {
            "wash": {"body": [{"command": {"device": "feed", "verb": "stop"}}]},
        },
        "blocks": [
            {"serial": {"children": [
                {"command": {"device": "feed", "verb": "dispense",
                             "params": {"volume_ml": 5}}},
                {"loop": {"count": 2, "body": [
                    {"measure": {"device": "od", "verb": "measure", "into": "od"}},
                ]}},
                {"branch": {"if": "x > 1", "then": [
                    {"command": {"device": "feed", "verb": "stop"}},
                ], "else": [
                    {"parallel": {"children": [
                        {"command": {"device": "feed", "verb": "stop"}},
                        {"wait": {"duration": "5s"}},
                    ]}},
                ]}},
            ]}},
        ],
    }


def test_substitute_walks_every_container_kind() -> None:
    mapping = {"feed": "pump_0", "od": "densitometer_0"}
    out, diags = substitute(_workflow(), mapping)
    assert diags == []
    serial = out["blocks"][0]["serial"]["children"]
    assert serial[0]["command"]["device"] == "pump_0"
    assert serial[1]["loop"]["body"][0]["measure"]["device"] == "densitometer_0"
    assert serial[2]["branch"]["then"][0]["command"]["device"] == "pump_0"
    par = serial[2]["branch"]["else"][0]["parallel"]["children"]
    assert par[0]["command"]["device"] == "pump_0"
    assert out["groups"]["wash"]["body"][0]["command"]["device"] == "pump_0"


def test_substitute_does_not_mutate_input() -> None:
    original = _workflow()
    substitute(original, {"feed": "pump_0", "od": "densitometer_0"})
    assert original["blocks"][0]["serial"]["children"][0]["command"]["device"] == "feed"


def test_substitute_reports_unknown_role_at_block_path() -> None:
    wf = {
        "schema_version": 1,
        "blocks": [
            {"serial": {"children": [
                {"wait": {"duration": "1s"}},
                {"command": {"device": "ghost", "verb": "stop"}},
            ]}},
        ],
        "groups": {"wash": {"body": [{"measure": {"device": "phantom", "into": "od"}}]}},
    }
    out, diags = substitute(wf, {})
    assert diags == [
        {
            "category": "roles",
            "path": "blocks[0].children[1]",
            "message": "block references unknown role 'ghost'",
        },
        {
            "category": "roles",
            "path": "groups['wash'].body[0]",
            "message": "block references unknown role 'phantom'",
        },
    ]
    assert out["blocks"][0]["serial"]["children"][1]["command"]["device"] == "ghost"


def test_substitute_skips_malformed_nodes_without_crashing() -> None:
    wf = {
        "schema_version": 1,
        "blocks": [
            "not-a-dict",
            {"command": {"device": "feed", "verb": "stop"}, "serial": {"children": []}},
            {"command": "not-an-object"},
            {"command": {"device": 42, "verb": "stop"}},
        ],
    }
    out, diags = substitute(wf, {"feed": "pump_0"})
    assert diags == []  # malformed shapes are the engine loader's job to report
    assert out["blocks"][0] == "not-a-dict"
    assert out["blocks"][3]["command"]["device"] == 42
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd webapp/backend && .venv/bin/python -m pytest tests/test_roles.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'experiment_studio.roles'`

- [ ] **Step 3: Implement `roles.py`**

Create `webapp/backend/experiment_studio/roles.py`:

```python
"""Role -> device-id substitution and doc-level role checks. See webapp design §4.2-4.3."""

from __future__ import annotations

import copy
import re
from typing import Any

ROLE_NAME_RE = re.compile(r"[a-z][a-z0-9_]*\Z")

# Mirrors the engine serializer: block dict = one type key + optional timing keys.
_TIMING_KEYS = ("label", "gap_after", "start_offset")
_DEVICE_BLOCKS = ("command", "measure")
_CHILD_LISTS: dict[str, tuple[str, ...]] = {
    "serial": ("children",),
    "parallel": ("children",),
    "loop": ("body",),
    "branch": ("then", "else"),
}


def _diag(category: str, path: str, message: str) -> dict[str, str]:
    return {"category": category, "path": path, "message": message}


def role_diagnostics(roles: dict[str, str], device_types: set[str]) -> list[dict[str, str]]:
    """Doc-level checks the engine cannot see (§4.3): role-name shape + catalog types."""
    out: list[dict[str, str]] = []
    for name, dtype in roles.items():
        path = f"roles[{name!r}]"
        if not ROLE_NAME_RE.fullmatch(name):
            out.append(_diag("roles", path, f"role name {name!r} must match [a-z][a-z0-9_]*"))
        if dtype not in device_types:
            out.append(_diag("roles", path, f"unknown device type {dtype!r}"))
    return out


def placeholder_ids(roles: dict[str, str]) -> dict[str, str]:
    """Role -> distinct placeholder id whose engine-derived type is the role type (§4.3)."""
    counters: dict[str, int] = {}
    out: dict[str, str] = {}
    for name, dtype in roles.items():
        i = counters.get(dtype, 0)
        counters[dtype] = i + 1
        out[name] = f"{dtype}_{i}"
    return out


def substitute(
    workflow: dict[str, Any], mapping: dict[str, str]
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """Deep-copied workflow with every block's `device` role swapped for mapping[role].

    Serves both placeholder substitution (§4.3) and real run substitution (§7.1). Unknown
    roles yield diagnostics at engine-grammar structural paths; malformed nodes are left
    untouched for `workflow_from_dict` to report.
    """
    out = copy.deepcopy(workflow)
    diags: list[dict[str, str]] = []
    blocks = out.get("blocks")
    if isinstance(blocks, list):
        _walk(blocks, "blocks", mapping, diags)
    groups = out.get("groups")
    if isinstance(groups, dict):
        for name, group in groups.items():
            if isinstance(group, dict) and isinstance(group.get("body"), list):
                _walk(group["body"], f"groups[{name!r}].body", mapping, diags)
    return out, diags


def _walk(
    blocks: list[Any], prefix: str, mapping: dict[str, str], diags: list[dict[str, str]]
) -> None:
    for i, block in enumerate(blocks):
        path = f"{prefix}[{i}]"
        if not isinstance(block, dict):
            continue
        type_keys = [k for k in block if k not in _TIMING_KEYS]
        if len(type_keys) != 1:
            continue
        key = type_keys[0]
        body = block[key]
        if not isinstance(body, dict):
            continue
        if key in _DEVICE_BLOCKS:
            device = body.get("device")
            if isinstance(device, str):
                if device in mapping:
                    body["device"] = mapping[device]
                else:
                    diags.append(
                        _diag("roles", path, f"block references unknown role {device!r}")
                    )
        for child_key in _CHILD_LISTS.get(key, ()):
            children = body.get(child_key)
            if isinstance(children, list):
                _walk(children, f"{path}.{child_key}", mapping, diags)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd webapp/backend && .venv/bin/python -m pytest tests/test_roles.py -q`
Expected: 7 passed

- [ ] **Step 5: Full gates**

Run from `webapp/backend`: `.venv/bin/python -m pytest -q && .venv/bin/python -m mypy && .venv/bin/python -m ruff check . && find experiment_studio tests -name '*.py' | xargs awk 'length>100'`
Expected: all clean

- [ ] **Step 6: Commit**

```bash
git add webapp/backend/experiment_studio/roles.py webapp/backend/tests/test_roles.py
git commit -m "feat(studio): roles module with placeholder substitution and doc-level checks"
```

---

### Task 3: Experiment document model + CRUD store

**Files:**
- Create: `webapp/backend/experiment_studio/docs_store.py`
- Test: `webapp/backend/tests/test_docs_store.py`

**Interfaces:**
- Consumes: `Database` from Task 1 (`experiment_studio.db`).
- Produces (used by Task 4's router and Task 5's validate):
  - `class RoleDef(BaseModel)`: `type: str`
  - `class ExperimentDoc(BaseModel)`: `doc_version: Literal[1]`, `name: str` (min_length 1),
    `description: str | None = None`, `roles: dict[str, RoleDef] = {}`,
    `workflow: dict[str, Any]`
  - `class UnknownExperimentError(Exception)`, `class NameConflictError(Exception)`
  - `class ExperimentsStore`: `__init__(db: Database)`;
    `async list() -> list[dict[str, Any]]` (summaries, P8);
    `async create(doc: ExperimentDoc) -> dict[str, Any]` (full row);
    `async get(experiment_id: str) -> dict[str, Any]`;
    `async replace(experiment_id: str, doc: ExperimentDoc) -> dict[str, Any]`;
    `async delete(experiment_id: str) -> None`;
    `async duplicate(experiment_id: str) -> dict[str, Any]`.
  - Full-row dict shape: `{id, name, description, created_at, updated_at, doc}` where `doc`
    is the parsed stored JSON; summary = same minus `doc`.

- [ ] **Step 1: Write the failing tests**

Create `webapp/backend/tests/test_docs_store.py`:

```python
"""ExperimentsStore CRUD semantics (design §6, §8.1)."""

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest

from experiment_studio.db import Database
from experiment_studio.docs_store import (
    ExperimentDoc,
    ExperimentsStore,
    NameConflictError,
    UnknownExperimentError,
)


@pytest.fixture
async def store(tmp_path: Path) -> AsyncIterator[ExperimentsStore]:
    db = await Database.connect(tmp_path / "studio.db")
    yield ExperimentsStore(db)
    await db.close()


def make_doc(name: str = "OD growth curve", **overrides: Any) -> ExperimentDoc:
    payload: dict[str, Any] = {
        "doc_version": 1,
        "name": name,
        "description": "demo",
        "roles": {"feed_pump": {"type": "pump"}},
        "workflow": {"schema_version": 1, "blocks": []},
    }
    payload.update(overrides)
    return ExperimentDoc.model_validate(payload)


async def test_create_get_roundtrip(store: ExperimentsStore) -> None:
    created = await store.create(make_doc())
    assert created["name"] == "OD growth curve"
    assert created["doc"]["roles"] == {"feed_pump": {"type": "pump"}}
    assert created["created_at"] == created["updated_at"]
    fetched = await store.get(created["id"])
    assert fetched == created


async def test_list_returns_summaries_newest_updated_first(store: ExperimentsStore) -> None:
    a = await store.create(make_doc("A"))
    await store.create(make_doc("B"))
    await store.replace(a["id"], make_doc("A", description="bumped"))
    listed = await store.list()
    assert [e["name"] for e in listed] == ["A", "B"]
    assert all("doc" not in e for e in listed)
    assert listed[0]["description"] == "bumped"


async def test_create_duplicate_name_conflicts(store: ExperimentsStore) -> None:
    await store.create(make_doc("X"))
    with pytest.raises(NameConflictError):
        await store.create(make_doc("X"))


async def test_replace_updates_doc_and_name(store: ExperimentsStore) -> None:
    created = await store.create(make_doc("old"))
    replaced = await store.replace(created["id"], make_doc("new"))
    assert replaced["name"] == "new"
    assert replaced["created_at"] == created["created_at"]
    assert replaced["updated_at"] >= created["updated_at"]
    assert replaced["doc"]["name"] == "new"


async def test_replace_rename_onto_existing_conflicts(store: ExperimentsStore) -> None:
    await store.create(make_doc("taken"))
    other = await store.create(make_doc("mine"))
    with pytest.raises(NameConflictError):
        await store.replace(other["id"], make_doc("taken"))


async def test_unknown_ids_raise(store: ExperimentsStore) -> None:
    with pytest.raises(UnknownExperimentError):
        await store.get("nope")
    with pytest.raises(UnknownExperimentError):
        await store.replace("nope", make_doc())
    with pytest.raises(UnknownExperimentError):
        await store.delete("nope")
    with pytest.raises(UnknownExperimentError):
        await store.duplicate("nope")


async def test_delete_removes_row(store: ExperimentsStore) -> None:
    created = await store.create(make_doc())
    await store.delete(created["id"])
    with pytest.raises(UnknownExperimentError):
        await store.get(created["id"])


async def test_duplicate_suffixes_name(store: ExperimentsStore) -> None:
    src = await store.create(make_doc("X"))
    first = await store.duplicate(src["id"])
    second = await store.duplicate(src["id"])
    assert first["name"] == "X (copy)"
    assert second["name"] == "X (copy 2)"
    assert first["doc"]["name"] == "X (copy)"
    assert first["doc"]["workflow"] == src["doc"]["workflow"]
    assert first["id"] != src["id"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd webapp/backend && .venv/bin/python -m pytest tests/test_docs_store.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'experiment_studio.docs_store'`

- [ ] **Step 3: Implement `docs_store.py`**

Create `webapp/backend/experiment_studio/docs_store.py`:

```python
"""Experiment doc model, CRUD store, and validation orchestration. See design §4, §6, §8.1."""

from __future__ import annotations

import itertools
import json
import sqlite3
import uuid
from datetime import UTC, datetime
from typing import Any, Literal

import aiosqlite
from pydantic import BaseModel, Field

from experiment_studio.db import Database


class RoleDef(BaseModel):
    type: str


class ExperimentDoc(BaseModel):
    """Saved unit (§4.1): wraps the engine workflow JSON; `device` fields hold role names."""

    doc_version: Literal[1]
    name: str = Field(min_length=1)
    description: str | None = None
    roles: dict[str, RoleDef] = Field(default_factory=dict)
    workflow: dict[str, Any]


class UnknownExperimentError(Exception):
    """No experiment row with the requested id."""


class NameConflictError(Exception):
    """Experiment names are unique (§8.1); the requested name is taken."""


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _summary(row: aiosqlite.Row) -> dict[str, Any]:
    doc = json.loads(row["doc"])
    return {
        "id": row["id"],
        "name": row["name"],
        "description": doc.get("description"),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _full(row: aiosqlite.Row) -> dict[str, Any]:
    out = _summary(row)
    out["doc"] = json.loads(row["doc"])
    return out


class ExperimentsStore:
    """CRUD over the experiments table; raises domain errors mapped to HTTP in app.py."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def list(self) -> list[dict[str, Any]]:
        cur = await self._db.conn.execute(
            "SELECT id, name, doc, created_at, updated_at FROM experiments"
            " ORDER BY updated_at DESC"
        )
        return [_summary(row) for row in await cur.fetchall()]

    async def create(self, doc: ExperimentDoc) -> dict[str, Any]:
        row_id = str(uuid.uuid4())
        now = _now()
        try:
            await self._db.conn.execute(
                "INSERT INTO experiments (id, name, doc, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?)",
                (row_id, doc.name, doc.model_dump_json(), now, now),
            )
        except sqlite3.IntegrityError:
            raise NameConflictError(f"experiment name {doc.name!r} already exists") from None
        await self._db.conn.commit()
        return await self.get(row_id)

    async def get(self, experiment_id: str) -> dict[str, Any]:
        cur = await self._db.conn.execute(
            "SELECT id, name, doc, created_at, updated_at FROM experiments WHERE id = ?",
            (experiment_id,),
        )
        row = await cur.fetchone()
        if row is None:
            raise UnknownExperimentError(f"no experiment {experiment_id!r}")
        return _full(row)

    async def replace(self, experiment_id: str, doc: ExperimentDoc) -> dict[str, Any]:
        try:
            cur = await self._db.conn.execute(
                "UPDATE experiments SET name = ?, doc = ?, updated_at = ? WHERE id = ?",
                (doc.name, doc.model_dump_json(), _now(), experiment_id),
            )
        except sqlite3.IntegrityError:
            raise NameConflictError(f"experiment name {doc.name!r} already exists") from None
        if cur.rowcount == 0:
            raise UnknownExperimentError(f"no experiment {experiment_id!r}")
        await self._db.conn.commit()
        return await self.get(experiment_id)

    async def delete(self, experiment_id: str) -> None:
        cur = await self._db.conn.execute(
            "DELETE FROM experiments WHERE id = ?", (experiment_id,)
        )
        if cur.rowcount == 0:
            raise UnknownExperimentError(f"no experiment {experiment_id!r}")
        await self._db.conn.commit()

    async def duplicate(self, experiment_id: str) -> dict[str, Any]:
        source = await self.get(experiment_id)
        doc = ExperimentDoc.model_validate(source["doc"])
        for n in itertools.count(1):
            candidate = f"{doc.name} (copy)" if n == 1 else f"{doc.name} (copy {n})"
            try:
                return await self.create(doc.model_copy(update={"name": candidate}))
            except NameConflictError:
                continue
        raise AssertionError("unreachable")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd webapp/backend && .venv/bin/python -m pytest tests/test_docs_store.py -q`
Expected: 9 passed

- [ ] **Step 5: Full gates**

Run from `webapp/backend`: `.venv/bin/python -m pytest -q && .venv/bin/python -m mypy && .venv/bin/python -m ruff check . && find experiment_studio tests -name '*.py' | xargs awk 'length>100'`
Expected: all clean

- [ ] **Step 6: Commit**

```bash
git add webapp/backend/experiment_studio/docs_store.py webapp/backend/tests/test_docs_store.py
git commit -m "feat(studio): experiment doc model and CRUD store"
```

---

### Task 4: Experiments CRUD API + app wiring

**Files:**
- Create: `webapp/backend/experiment_studio/api/experiments.py`
- Modify: `webapp/backend/experiment_studio/app.py`
- Modify: `webapp/backend/tests/conftest.py`
- Test: `webapp/backend/tests/test_experiments_api.py`

**Interfaces:**
- Consumes: `ExperimentDoc`, `ExperimentsStore`, `UnknownExperimentError`, `NameConflictError`
  (Task 3); `Database` (Task 1); `Settings.data_dir` (Task 1).
- Produces: router mounted at `/api/experiments`; `get_store(request) -> ExperimentsStore`
  dependency (lazily opens `settings.data_dir / "studio.db"`, cached on `app.state.db`);
  `app.state.settings` set in `create_app`; lifespan opens/closes the DB (P10).

- [ ] **Step 1: Write the failing tests**

Create `webapp/backend/tests/test_experiments_api.py`:

```python
"""Experiments CRUD endpoints at the ASGI level (design §6)."""

from typing import Any

import httpx


def doc_payload(name: str = "OD growth curve", **overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "doc_version": 1,
        "name": name,
        "description": None,
        "roles": {"feed_pump": {"type": "pump"}},
        "workflow": {"schema_version": 1, "blocks": []},
    }
    payload.update(overrides)
    return payload


async def test_crud_roundtrip(client: httpx.AsyncClient) -> None:
    created = await client.post("/api/experiments", json=doc_payload())
    assert created.status_code == 201
    body = created.json()
    exp_id = body["id"]
    assert body["name"] == "OD growth curve"
    assert body["doc"]["workflow"] == {"schema_version": 1, "blocks": []}

    listed = await client.get("/api/experiments")
    assert listed.status_code == 200
    assert [e["name"] for e in listed.json()] == ["OD growth curve"]
    assert "doc" not in listed.json()[0]

    fetched = await client.get(f"/api/experiments/{exp_id}")
    assert fetched.status_code == 200
    assert fetched.json() == body

    replaced = await client.put(
        f"/api/experiments/{exp_id}", json=doc_payload("renamed", description="v2")
    )
    assert replaced.status_code == 200
    assert replaced.json()["name"] == "renamed"
    assert replaced.json()["description"] == "v2"

    deleted = await client.delete(f"/api/experiments/{exp_id}")
    assert deleted.status_code == 204
    assert (await client.get(f"/api/experiments/{exp_id}")).status_code == 404


async def test_name_conflict_is_409(client: httpx.AsyncClient) -> None:
    assert (await client.post("/api/experiments", json=doc_payload("X"))).status_code == 201
    conflict = await client.post("/api/experiments", json=doc_payload("X"))
    assert conflict.status_code == 409
    assert conflict.json()["code"] == "name_conflict"

    other = await client.post("/api/experiments", json=doc_payload("Y"))
    put = await client.put(
        f"/api/experiments/{other.json()['id']}", json=doc_payload("X")
    )
    assert put.status_code == 409
    assert put.json()["code"] == "name_conflict"


async def test_unknown_experiment_is_404(client: httpx.AsyncClient) -> None:
    for resp in (
        await client.get("/api/experiments/ghost"),
        await client.put("/api/experiments/ghost", json=doc_payload()),
        await client.delete("/api/experiments/ghost"),
        await client.post("/api/experiments/ghost/duplicate"),
    ):
        assert resp.status_code == 404
        assert resp.json()["code"] == "unknown_experiment"


async def test_duplicate_suffixes_name(client: httpx.AsyncClient) -> None:
    src = await client.post("/api/experiments", json=doc_payload("X"))
    first = await client.post(f"/api/experiments/{src.json()['id']}/duplicate")
    second = await client.post(f"/api/experiments/{src.json()['id']}/duplicate")
    assert first.status_code == 201 and second.status_code == 201
    assert first.json()["name"] == "X (copy)"
    assert second.json()["name"] == "X (copy 2)"


async def test_malformed_doc_is_422(client: httpx.AsyncClient) -> None:
    for bad in (
        doc_payload(doc_version=2),
        doc_payload(name=""),
        {k: v for k, v in doc_payload().items() if k != "workflow"},
    ):
        resp = await client.post("/api/experiments", json=bad)
        assert resp.status_code == 422
```

Update `webapp/backend/tests/conftest.py` to (whole file):

```python
"""Shared fixtures: app factory + ASGI-transport client (no lifespan needed)."""

from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

from experiment_studio.app import create_app
from experiment_studio.config import Settings


@pytest.fixture
def app(tmp_path: Path) -> FastAPI:
    return create_app(Settings(static_dir=None, data_dir=tmp_path))


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://studio") as c:
        yield c
    db = getattr(app.state, "db", None)
    if db is not None:
        await db.close()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd webapp/backend && .venv/bin/python -m pytest tests/test_experiments_api.py -q`
Expected: FAIL — 404s everywhere (router not mounted) / import error

- [ ] **Step 3: Implement the router**

Create `webapp/backend/experiment_studio/api/experiments.py`:

```python
"""Experiment document CRUD endpoints. See webapp design §6."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request

from experiment_studio.db import Database
from experiment_studio.docs_store import ExperimentDoc, ExperimentsStore

router = APIRouter()


async def get_store(request: Request) -> ExperimentsStore:
    """Lazily open the database on first use; lifespan startup pre-populates app.state.db."""
    db = getattr(request.app.state, "db", None)
    if db is None:
        settings = request.app.state.settings
        db = await Database.connect(settings.data_dir / "studio.db")
        request.app.state.db = db
    return ExperimentsStore(db)


@router.get("")
async def list_experiments(
    store: ExperimentsStore = Depends(get_store),
) -> list[dict[str, Any]]:
    return await store.list()


@router.post("", status_code=201)
async def create_experiment(
    doc: ExperimentDoc, store: ExperimentsStore = Depends(get_store)
) -> dict[str, Any]:
    return await store.create(doc)


@router.get("/{experiment_id}")
async def get_experiment(
    experiment_id: str, store: ExperimentsStore = Depends(get_store)
) -> dict[str, Any]:
    return await store.get(experiment_id)


@router.put("/{experiment_id}")
async def replace_experiment(
    experiment_id: str, doc: ExperimentDoc, store: ExperimentsStore = Depends(get_store)
) -> dict[str, Any]:
    return await store.replace(experiment_id, doc)


@router.delete("/{experiment_id}", status_code=204)
async def delete_experiment(
    experiment_id: str, store: ExperimentsStore = Depends(get_store)
) -> None:
    await store.delete(experiment_id)


@router.post("/{experiment_id}/duplicate", status_code=201)
async def duplicate_experiment(
    experiment_id: str, store: ExperimentsStore = Depends(get_store)
) -> dict[str, Any]:
    return await store.duplicate(experiment_id)
```

- [ ] **Step 4: Wire into `app.py`**

In `webapp/backend/experiment_studio/app.py`:

Add imports:

```python
from experiment_studio.api.experiments import router as experiments_router
from experiment_studio.db import Database
from experiment_studio.docs_store import NameConflictError, UnknownExperimentError
```

Prepend two entries to `_ERROR_MAP` (studio domain errors first, library errors unchanged):

```python
_ERROR_MAP: list[tuple[type[Exception], int, str]] = [
    (UnknownExperimentError, 404, "unknown_experiment"),
    (NameConflictError, 409, "name_conflict"),
    (lab_errors.UnknownLabClient, 404, "unknown_lab"),
    # ... rest unchanged ...
]
```

Replace `_lifespan` with:

```python
@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = app.state.settings
    app.state.db = await Database.connect(settings.data_dir / "studio.db")
    yield
    db = getattr(app.state, "db", None)
    if db is not None:
        await db.close()
    labs = getattr(app.state, "labs", None)
    if labs is not None:
        await labs.aclose()
```

In `create_app`, after constructing `app` add `app.state.settings = settings`, and mount the
router alongside the existing ones:

```python
    app.state.settings = settings
    ...
    app.include_router(experiments_router, prefix="/api/experiments")
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd webapp/backend && .venv/bin/python -m pytest tests/test_experiments_api.py -q`
Expected: 5 passed

- [ ] **Step 6: Full gates**

Run from `webapp/backend`: `.venv/bin/python -m pytest -q && .venv/bin/python -m mypy && .venv/bin/python -m ruff check . && find experiment_studio tests -name '*.py' | xargs awk 'length>100'`
Expected: all clean (existing W1 tests must still pass — conftest change is additive)

- [ ] **Step 7: Commit**

```bash
git add webapp/backend/experiment_studio/api/experiments.py \
  webapp/backend/experiment_studio/app.py webapp/backend/tests/conftest.py \
  webapp/backend/tests/test_experiments_api.py
git commit -m "feat(studio): experiments CRUD API with db lifecycle wiring"
```

---

### Task 5: `/api/validate` + golden fixtures + spec grammar amendment

**Files:**
- Modify: `webapp/backend/experiment_studio/docs_store.py` (append `validate_doc`)
- Create: `webapp/backend/experiment_studio/api/validate.py`
- Modify: `webapp/backend/experiment_studio/app.py` (mount router)
- Create: `webapp/fixtures/valid-od-growth.json`, `webapp/fixtures/invalid-roles.json`,
  `webapp/fixtures/invalid-workflow.json`
- Modify: `docs/superpowers/specs/2026-07-11-experiment-studio-webapp-design.md` (P12)
- Test: `webapp/backend/tests/test_validate_api.py`

**Interfaces:**
- Consumes: `role_diagnostics`, `placeholder_ids`, `substitute` (Task 2); `ExperimentDoc`
  (Task 3); engine: `workflow_from_dict`, `validate`, `verb_catalog`, `ValidationError`,
  `WorkflowLoadError`, `ExpressionError`.
- Produces: `validate_doc(doc: ExperimentDoc) -> list[dict[str, str]]` in `docs_store.py`;
  `POST /api/validate` → `{ok: bool, diagnostics: [{category, path, message}]}`.

- [ ] **Step 1: Create the golden fixtures**

All three verified against the real engine (2026-07-11). Create `webapp/fixtures/valid-od-growth.json`:

```json
{
  "doc_version": 1,
  "name": "OD growth curve",
  "description": "Feed once, then measure OD every 30 s until mean of last 3 crosses 0.6.",
  "roles": {
    "feed_pump": {"type": "pump"},
    "od_meter": {"type": "densitometer"}
  },
  "workflow": {
    "schema_version": 1,
    "metadata": {"name": "OD growth curve"},
    "persistence": {"default": "in_memory", "format": "jsonl"},
    "streams": {"od": {"units": "AU"}},
    "blocks": [
      {"serial": {"children": [
        {"command": {"device": "feed_pump", "verb": "dispense", "params": {"volume_ml": 5}}},
        {"loop": {
          "until": "mean(od, last=3) > 0.6",
          "check": "after",
          "pace": "30s",
          "body": [
            {"measure": {"device": "od_meter", "verb": "measure", "into": "od"}},
            {"wait": {"duration": "5s"}}
          ]
        }}
      ]}}
    ]
  }
}
```

Create `webapp/fixtures/invalid-roles.json` (doc-level diagnostics only):

```json
{
  "doc_version": 1,
  "name": "Broken roles",
  "description": null,
  "roles": {
    "Feed_Pump": {"type": "pump"},
    "mixer": {"type": "stirrer"}
  },
  "workflow": {
    "schema_version": 1,
    "blocks": [
      {"command": {"device": "ghost_pump", "verb": "stop"}}
    ]
  }
}
```

Create `webapp/fixtures/invalid-workflow.json` (doc-level clean; engine diagnostics):

```json
{
  "doc_version": 1,
  "name": "Broken workflow",
  "description": null,
  "roles": {
    "feed_pump": {"type": "pump"},
    "od_meter": {"type": "densitometer"}
  },
  "workflow": {
    "schema_version": 1,
    "blocks": [
      {"serial": {"children": [
        {"command": {"device": "feed_pump", "verb": "dispense"}},
        {"measure": {"device": "od_meter", "verb": "measure", "into": "od"}}
      ]}}
    ]
  }
}
```

- [ ] **Step 2: Write the failing tests**

Create `webapp/backend/tests/test_validate_api.py`:

```python
"""POST /api/validate: doc-level checks + placeholder substitution + engine diagnostics
mapping (design §4.3), against the golden fixtures in webapp/fixtures/."""

import json
from pathlib import Path
from typing import Any

import httpx

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"


def load_fixture(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / name).read_text())


async def test_valid_doc_is_clean(client: httpx.AsyncClient) -> None:
    resp = await client.post("/api/validate", json=load_fixture("valid-od-growth.json"))
    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "diagnostics": []}


async def test_doc_level_diagnostics(client: httpx.AsyncClient) -> None:
    resp = await client.post("/api/validate", json=load_fixture("invalid-roles.json"))
    assert resp.status_code == 200
    assert resp.json() == {
        "ok": False,
        "diagnostics": [
            {
                "category": "roles",
                "path": "roles['Feed_Pump']",
                "message": "role name 'Feed_Pump' must match [a-z][a-z0-9_]*",
            },
            {
                "category": "roles",
                "path": "roles['mixer']",
                "message": "unknown device type 'stirrer'",
            },
            {
                "category": "roles",
                "path": "blocks[0]",
                "message": "block references unknown role 'ghost_pump'",
            },
        ],
    }


async def test_engine_diagnostics_pass_through_with_structural_paths(
    client: httpx.AsyncClient,
) -> None:
    resp = await client.post("/api/validate", json=load_fixture("invalid-workflow.json"))
    assert resp.status_code == 200
    assert resp.json() == {
        "ok": False,
        "diagnostics": [
            {
                "category": "params",
                "path": "blocks[0].children[0]",
                "message": "missing required param 'volume_ml' for verb 'dispense'",
            },
            {
                "category": "declaration",
                "path": "blocks[0].children[1]",
                "message": "measure writes undeclared stream 'od'",
            },
        ],
    }


def _doc(workflow: dict[str, Any], roles: dict[str, Any]) -> dict[str, Any]:
    return {
        "doc_version": 1,
        "name": "t",
        "description": None,
        "roles": roles,
        "workflow": workflow,
    }


async def test_unsupported_schema_version_is_schema_diagnostic(
    client: httpx.AsyncClient,
) -> None:
    resp = await client.post(
        "/api/validate", json=_doc({"schema_version": 2, "blocks": []}, {})
    )
    assert resp.json() == {
        "ok": False,
        "diagnostics": [
            {
                "category": "schema",
                "path": "workflow",
                "message": "unsupported schema_version 2; expected 1",
            }
        ],
    }


async def test_bad_expression_grammar_is_schema_diagnostic(client: httpx.AsyncClient) -> None:
    workflow = {
        "schema_version": 1,
        "streams": {"od": {"units": "AU"}},
        "blocks": [
            {"loop": {
                "until": "mean(od[-3:]) > 0.6",
                "body": [{"wait": {"duration": "1s"}}],
            }},
        ],
    }
    resp = await client.post("/api/validate", json=_doc(workflow, {}))
    body = resp.json()
    assert body["ok"] is False
    assert len(body["diagnostics"]) == 1
    diag = body["diagnostics"][0]
    assert diag["category"] == "schema" and diag["path"] == "workflow"
    assert "unexpected character" in diag["message"]


def _parallel_stop(device_a: str, device_b: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "blocks": [
            {"parallel": {"children": [
                {"command": {"device": device_a, "verb": "stop"}},
                {"command": {"device": device_b, "verb": "stop"}},
            ]}},
        ],
    }


async def test_distinct_roles_of_same_type_get_distinct_placeholders(
    client: httpx.AsyncClient,
) -> None:
    roles = {"feed": {"type": "pump"}, "waste": {"type": "pump"}}
    resp = await client.post(
        "/api/validate", json=_doc(_parallel_stop("feed", "waste"), roles)
    )
    assert resp.json() == {"ok": True, "diagnostics": []}


async def test_same_role_in_parallel_lanes_hits_engine_affinity_check(
    client: httpx.AsyncClient,
) -> None:
    roles = {"feed": {"type": "pump"}}
    resp = await client.post(
        "/api/validate", json=_doc(_parallel_stop("feed", "feed"), roles)
    )
    body = resp.json()
    assert body["ok"] is False
    assert [d["category"] for d in body["diagnostics"]] == ["affinity"]
    assert body["diagnostics"][0]["path"] == "blocks[0]"


async def test_malformed_doc_is_422(client: httpx.AsyncClient) -> None:
    resp = await client.post("/api/validate", json={"doc_version": 1, "name": "x"})
    assert resp.status_code == 422
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd webapp/backend && .venv/bin/python -m pytest tests/test_validate_api.py -q`
Expected: FAIL — all endpoints 404 (router not mounted)

- [ ] **Step 4: Implement `validate_doc` + router**

Append to `webapp/backend/experiment_studio/docs_store.py` (and extend its imports):

```python
from lab_devices.experiment import (
    ExpressionError,
    ValidationError,
    WorkflowLoadError,
    validate,
    verb_catalog,
    workflow_from_dict,
)

from experiment_studio import roles as roles_mod
```

```python
def validate_doc(doc: ExperimentDoc) -> list[dict[str, str]]:
    """§4.3: doc-level role checks, placeholder substitution, engine parse + validate."""
    role_types = {name: role.type for name, role in doc.roles.items()}
    diags = roles_mod.role_diagnostics(role_types, set(verb_catalog()))
    substituted, ref_diags = roles_mod.substitute(
        doc.workflow, roles_mod.placeholder_ids(role_types)
    )
    diags += ref_diags
    if diags:
        return diags  # substitution unsound; engine output would duplicate (plan P3)
    try:
        workflow = workflow_from_dict(substituted)
    except (WorkflowLoadError, ExpressionError) as exc:
        return [{"category": "schema", "path": "workflow", "message": str(exc)}]
    try:
        validate(workflow)
    except ValidationError as exc:
        return [
            {"category": d.category, "path": d.path, "message": d.message}
            for d in exc.diagnostics
        ]
    return []
```

Create `webapp/backend/experiment_studio/api/validate.py`:

```python
"""Stateless draft-validation endpoint. See webapp design §4.3, §6."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from experiment_studio.docs_store import ExperimentDoc, validate_doc

router = APIRouter()


@router.post("/validate")
def validate_document(doc: ExperimentDoc) -> dict[str, Any]:
    diagnostics = validate_doc(doc)
    return {"ok": not diagnostics, "diagnostics": diagnostics}
```

In `app.py`: `from experiment_studio.api.validate import router as validate_router` and
`app.include_router(validate_router, prefix="/api")` next to the other routers.

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd webapp/backend && .venv/bin/python -m pytest tests/test_validate_api.py -q`
Expected: 9 passed

- [ ] **Step 6: Amend the spec's expression examples (P12)**

In `docs/superpowers/specs/2026-07-11-experiment-studio-webapp-design.md`:
- §2 row S4: replace `` `mean(od[-5:]) > 0.6` `` with `` `mean(od, last=5) > 0.6` ``.
- §9.3 expression-fields paragraph: replace ``window syntax (`od[-5:]`, `od[30s]`)`` with
  ``window syntax (`mean(od, last=5)`, `mean(od, last=30s)`)``.
- Add one line to §9.3 after that sentence: `(Amended 2026-07-11 during W2: the original
  bracket-window examples were not the engine grammar; engine specs win.)`

- [ ] **Step 7: Full gates**

Run from `webapp/backend`: `.venv/bin/python -m pytest -q && .venv/bin/python -m mypy && .venv/bin/python -m ruff check . && find experiment_studio tests -name '*.py' | xargs awk 'length>100'`
Expected: all clean

- [ ] **Step 8: Commit**

```bash
git add webapp/backend/experiment_studio/docs_store.py \
  webapp/backend/experiment_studio/api/validate.py webapp/backend/experiment_studio/app.py \
  webapp/backend/tests/test_validate_api.py webapp/fixtures/ \
  docs/superpowers/specs/2026-07-11-experiment-studio-webapp-design.md
git commit -m "feat(studio): /api/validate with placeholder substitution and golden fixtures"
```

---

## Final verification (before PR)

- [ ] From `webapp/backend`: `.venv/bin/python -m pytest -q` (full suite),
  `.venv/bin/python -m mypy`, `.venv/bin/python -m ruff check .`,
  `find experiment_studio tests -name '*.py' | xargs awk 'length>100'` (no output).
- [ ] Root library untouched: `git diff main --stat -- src/ pyproject.toml poetry.lock` is empty.
- [ ] Frontend untouched (CI webapp-frontend job will trivially pass).
- [ ] Docker image still builds: `docker build -f webapp/Dockerfile .` (skip if daemon
  unavailable — CI's webapp-image job covers it).
- [ ] Requesting-code-review + PR per superpowers:finishing-a-development-branch.
