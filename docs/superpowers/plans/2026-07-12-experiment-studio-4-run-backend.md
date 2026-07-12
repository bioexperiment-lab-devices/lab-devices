# Experiment Studio W4 — Run Backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps
> use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The run backend of Experiment Studio (design §7–§8): RunManager (one in-process
run per app instance), TeeRunLogSink feeding a WebSocket with `?since=N` replay,
WebInputProvider for mid-run operator prompts, records store + artifact directories +
zip download + artifact readers, crash sweep — plus the W1/W2 carry-forwards (atomic
migrations, store rollback hygiene, guarded lifespan that eagerly constructs services).

**Architecture:** The engine (`lab_devices.experiment`) runs in-process; the webapp never
re-implements its semantics. `POST /api/runs` preflights the role→device mapping against
a fresh lab roster, substitutes roles with real device ids (`roles.substitute` already
supports this), forces `persistence={disk,csv}` on the run copy so the engine's own
CsvStreamSinks write `<stream>.csv`, and constructs `ExperimentRun` — whose synchronous
construction-time `validate()` IS the real-mapping re-validation the W2 review demanded.
A wrapper task awaits `execute()`, then (in `finally`, after `task.uncancel()`) writes
`run_log.jsonl` + `report.json`, finalizes the record row, and broadcasts the terminal
status. All live data flows through one buffer: the tee's message list, where
`seq == list index` (events and status messages share the counter), so WS replay is a
list slice.

**Tech Stack:** Python 3.11+, FastAPI, aiosqlite, the engine's public API
(`ExperimentRun`, `RunOptions`, `RunEvent`, `InputRequest`) plus two submodule imports
(`run_event_to_dict` from `lab_devices.experiment.persist`, `validate_input_value` from
`lab_devices.experiment.inputs`). Tests: pytest(-asyncio auto), the engine's `FakeLab`
(repo-root `tests/fakelab.py`, imported via a sys.path bootstrap), `httpx-ws` (new dev
dep) for ASGI-level WebSocket tests. Frontend untouched.

## Global Constraints

- **Working directory for all commands:** `webapp/backend/` (its own pip venv at
  `webapp/backend/.venv`; the root poetry venv is a different environment).
- **Gates (run all before claiming a task done):** `.venv/bin/python -m pytest -q`,
  `.venv/bin/python -m mypy` (strict, covers `experiment_studio/` only),
  `.venv/bin/python -m ruff check .` (line length 100).
- **Do not touch:** `src/` (engine library — W4 has zero engine changes), root
  `pyproject.toml`, `webapp/frontend/`, `webapp/fixtures/` (read-only golden contract).
- **Engine semantics win** (spec preamble): statuses are the engine's four strings
  `completed|failed|aborted|cancelled` plus webapp-only `interrupted`; timestamps are the
  engine's monotonic clock (`RunOptions.clock.now()`); the engine has NO
  clock_origin/started_at — RunManager captures those itself.
- **Verified engine facts** (smoke-tested 2026-07-12, do not re-derive): `"1ms"` wait
  durations validate; an unused `operator_input` binding validates cleanly; with
  `log_sink` injected the engine builds no disk run log even when `persistence.default`
  is `"disk"`; `execute()` raises `RunAbortedError` on abort with `report.status ==
  "aborted"` and the wrapper task's `task.cancelled()` is False after catching;
  `RunOptions(job_poll_interval=0.005, job_poll_max=0.01)` makes FakeLab jobs finish in
  milliseconds.
- **Error envelope:** every non-2xx body is `{detail, code}`; run-specific errors extend
  it additively (`active_run_id`, `diagnostics`, `record_id`) — never replace it.
- **Commit messages:** `feat(studio): <what>` / `fix(studio): <what>` /
  `test(studio): <what>`, ending with the
  `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>` trailer.
- **Branch:** `feat/experiment-studio-4-run-backend` off `main`.

---

### Task 1: Storage hygiene — records/mappings migrations, atomic migrate, rollback hygiene, from_env test

**Files:**
- Modify: `webapp/backend/experiment_studio/db.py`
- Modify: `webapp/backend/experiment_studio/docs_store.py` (rollback lines only)
- Test: `webapp/backend/tests/test_db.py` (extend), `webapp/backend/tests/test_docs_store.py` (extend), `webapp/backend/tests/test_config.py` (new)

**Interfaces:**
- Consumes: existing `Database`, `MIGRATIONS`, `ExperimentsStore`, `Settings`.
- Produces: `records` and `mappings` tables (design §8.1) that Task 2's `RecordsStore`
  queries; `MIGRATIONS` has exactly 3 entries; migrations are atomic (DDL + version bump
  commit or roll back together); a failed `Database.connect` closes its connection.

- [ ] **Step 1: Write the failing tests**

Append to `webapp/backend/tests/test_db.py` (it already imports `Database`; add
`import sqlite3`, `import pytest`, and `from experiment_studio import db as db_module`
if missing):

```python
async def test_w4_tables_exist(tmp_path: Path) -> None:
    db = await Database.connect(tmp_path / "studio.db")
    cur = await db.conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    names = {row["name"] for row in await cur.fetchall()}
    assert {"experiments", "records", "mappings"} <= names
    cur = await db.conn.execute("PRAGMA user_version")
    row = await cur.fetchone()
    assert row is not None and row[0] == len(db_module.MIGRATIONS) == 3
    await db.close()


async def test_failed_migration_is_atomic(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """W2 carry-forward: DDL and the user_version bump commit together — a broken
    migration must leave neither the table nor the bump behind (no boot loop)."""
    good = db_module.MIGRATIONS[0]
    monkeypatch.setattr(db_module, "MIGRATIONS", [good, "CREATE TABLE broken ("])
    with pytest.raises(sqlite3.OperationalError):
        await Database.connect(tmp_path / "studio.db")
    raw = sqlite3.connect(tmp_path / "studio.db")
    try:
        assert raw.execute("PRAGMA user_version").fetchone()[0] == 1
        tables = {r[0] for r in raw.execute("SELECT name FROM sqlite_master")}
        assert "broken" not in tables
    finally:
        raw.close()
    # boot recovers once the migration list is fixed
    monkeypatch.setattr(
        db_module, "MIGRATIONS", [good, "CREATE TABLE fixed (id TEXT PRIMARY KEY)"]
    )
    db = await Database.connect(tmp_path / "studio.db")
    cur = await db.conn.execute("PRAGMA user_version")
    row = await cur.fetchone()
    assert row is not None and row[0] == 2
    await db.close()
```

Append to `webapp/backend/tests/test_docs_store.py` (add imports it lacks:
`from experiment_studio.db import Database`):

```python
async def test_name_conflict_rolls_back_transaction(tmp_path: Path) -> None:
    """W2 carry-forward: a failed INSERT/UPDATE must not leave the connection in an
    open transaction."""
    db = await Database.connect(tmp_path / "studio.db")
    store = ExperimentsStore(db)
    doc = ExperimentDoc(doc_version=1, name="A", workflow={"schema_version": 1})
    created = await store.create(doc)
    with pytest.raises(NameConflictError):
        await store.create(doc)
    assert not db.conn.in_transaction
    other = await store.create(doc.model_copy(update={"name": "B"}))
    with pytest.raises(NameConflictError):
        await store.replace(other["id"], doc)  # rename B -> A collides
    assert not db.conn.in_transaction
    with pytest.raises(UnknownExperimentError):
        await store.delete("nope")
    assert not db.conn.in_transaction
    assert created["name"] == "A"
    await db.close()
```

(If `test_docs_store.py` does not already import `pytest`, `ExperimentDoc`,
`NameConflictError`, `UnknownExperimentError`, add those imports.)

Create `webapp/backend/tests/test_config.py`:

```python
"""Settings.from_env coverage (W2 carry-forward)."""

from pathlib import Path

import pytest

from experiment_studio.config import Settings


def test_from_env_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("STUDIO_STATIC_DIR", raising=False)
    monkeypatch.delenv("STUDIO_DATA_DIR", raising=False)
    settings = Settings.from_env()
    assert settings.static_dir is None
    assert settings.data_dir == Path("/data")


def test_from_env_reads_vars(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    static = tmp_path / "static"
    static.mkdir()
    monkeypatch.setenv("STUDIO_STATIC_DIR", str(static))
    monkeypatch.setenv("STUDIO_DATA_DIR", str(tmp_path / "data"))
    settings = Settings.from_env()
    assert settings.static_dir == static
    assert settings.data_dir == tmp_path / "data"


def test_from_env_nulls_missing_static_dir(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("STUDIO_STATIC_DIR", str(tmp_path / "absent"))
    assert Settings.from_env().static_dir is None
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_db.py tests/test_docs_store.py tests/test_config.py -q`
Expected: `test_w4_tables_exist` FAILS (missing tables), `test_failed_migration_is_atomic`
FAILS (partial state persists / connection leak), rollback test FAILS
(`in_transaction` is True). The config tests may already PASS (they cover existing
behavior) — that is fine.

- [ ] **Step 3: Implement**

In `webapp/backend/experiment_studio/db.py`, append two entries to `MIGRATIONS`
(append-only — never edit entry 1):

```python
    """
    CREATE TABLE records (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        experiment_id TEXT,
        experiment_name TEXT NOT NULL,
        lab TEXT NOT NULL,
        role_mapping TEXT NOT NULL,
        status TEXT NOT NULL,
        started_at TEXT NOT NULL,
        ended_at TEXT,
        dir TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE mappings (
        experiment_id TEXT NOT NULL,
        lab TEXT NOT NULL,
        role TEXT NOT NULL,
        device_id TEXT NOT NULL,
        PRIMARY KEY (experiment_id, lab, role)
    )
    """,
```

Replace `Database.connect` and `_migrate` bodies:

```python
    @classmethod
    async def connect(cls, path: Path) -> Database:
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = await aiosqlite.connect(path)
        conn.row_factory = aiosqlite.Row
        db = cls(conn)
        try:
            await db._migrate()
        except BaseException:
            await conn.close()
            raise
        return db

    async def _migrate(self) -> None:
        cur = await self._conn.execute("PRAGMA user_version")
        row = await cur.fetchone()
        version = int(row[0]) if row is not None else 0
        for i, statement in enumerate(MIGRATIONS[version:], start=version + 1):
            # DDL + version bump commit together: a crash between them would re-run
            # the DDL on next boot and fail forever (W2 repro).
            await self._conn.execute("BEGIN")
            try:
                await self._conn.execute(statement)
                await self._conn.execute(f"PRAGMA user_version = {i}")
                await self._conn.commit()
            except BaseException:
                await self._conn.rollback()
                raise
```

In `webapp/backend/experiment_studio/docs_store.py`, add rollbacks before raising:

- `create`: inside `except sqlite3.IntegrityError:` add `await self._db.conn.rollback()`
  as the first statement of the handler.
- `replace`: same in its `except sqlite3.IntegrityError:` handler, and in the
  `if cur.rowcount == 0:` branch add `await self._db.conn.rollback()` before the raise.
- `delete`: in the `if cur.rowcount == 0:` branch add `await self._db.conn.rollback()`
  before the raise.

- [ ] **Step 4: Run the full backend suite + gates**

Run: `.venv/bin/python -m pytest -q && .venv/bin/python -m mypy && .venv/bin/python -m ruff check .`
Expected: all PASS (existing 47 tests + new ones), mypy/ruff clean.

- [ ] **Step 5: Commit**

```bash
git add webapp/backend/experiment_studio/db.py webapp/backend/experiment_studio/docs_store.py webapp/backend/tests/test_db.py webapp/backend/tests/test_docs_store.py webapp/backend/tests/test_config.py
git commit -m "feat(studio): records/mappings tables, atomic migrations, store rollback hygiene"
```

---

### Task 2: Records store, crash sweep, artifact readers, zip

**Files:**
- Create: `webapp/backend/experiment_studio/records.py`
- Test: `webapp/backend/tests/test_records.py`

**Interfaces:**
- Consumes: `Database` (Task 1's `records`/`mappings` tables);
  `safe_stream_filename` and `PersistenceError` from the engine.
- Produces (used by Tasks 4–7):
  - `class UnknownRecordError(Exception)`
  - `class RecordsStore:`
    - `__init__(self, db: Database, data_dir: Path) -> None`
    - `async create(*, record_id: str, name: str, experiment_id: str | None, experiment_name: str, lab: str, role_mapping: dict[str, str], started_at: str, dir: str) -> dict[str, Any]` — inserts with `status="running"`, `ended_at=NULL`
    - `async list(self) -> list[dict[str, Any]]` — `ORDER BY started_at DESC`
    - `async get(self, record_id: str) -> dict[str, Any]` — raises `UnknownRecordError`
    - `async rename(self, record_id: str, name: str) -> dict[str, Any]`
    - `async finalize(self, record_id: str, *, status: str, ended_at: str) -> None`
    - `async delete(self, record_id: str) -> None` — row + artifact dir
    - `async sweep_interrupted(self) -> int` — `running` → `interrupted` (§7.6)
    - `async save_mapping(self, experiment_id: str, lab: str, role_mapping: dict[str, str]) -> None`
    - `def artifact_dir(self, record: dict[str, Any]) -> Path`
  - Module functions: `read_events(artifact_dir: Path) -> list[dict[str, Any]]`,
    `read_streams(artifact_dir: Path) -> dict[str, dict[str, Any]]`,
    `build_zip(artifact_dir: Path) -> bytes`
- Record dict shape (row JSON): `{id, name, experiment_id, experiment_name, lab,
  role_mapping (parsed dict), status, started_at, ended_at, dir}`.

- [ ] **Step 1: Write the failing tests**

Create `webapp/backend/tests/test_records.py`:

```python
"""RecordsStore CRUD + sweep + mappings + artifact readers + zip. See design §8."""

import io
import json
import zipfile
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from experiment_studio.db import Database
from experiment_studio.records import (
    RecordsStore,
    UnknownRecordError,
    build_zip,
    read_events,
    read_streams,
)


@pytest.fixture
async def db(tmp_path: Path) -> AsyncIterator[Database]:
    database = await Database.connect(tmp_path / "studio.db")
    yield database
    await database.close()


@pytest.fixture
def store(db: Database, tmp_path: Path) -> RecordsStore:
    return RecordsStore(db, tmp_path)


async def _create(store: RecordsStore, record_id: str, *, started_at: str) -> dict:
    return await store.create(
        record_id=record_id,
        name=f"Rec {record_id}",
        experiment_id="e1",
        experiment_name="Exp",
        lab="lab_a",
        role_mapping={"feed": "pump_1"},
        started_at=started_at,
        dir=f"runs/{record_id}",
    )


async def test_create_get_roundtrip(store: RecordsStore) -> None:
    created = await _create(store, "r1", started_at="2026-07-12T10:00:00+00:00")
    assert created["status"] == "running"
    assert created["ended_at"] is None
    assert created["role_mapping"] == {"feed": "pump_1"}
    assert created["dir"] == "runs/r1"
    assert (await store.get("r1")) == created


async def test_get_unknown_raises(store: RecordsStore) -> None:
    with pytest.raises(UnknownRecordError):
        await store.get("nope")


async def test_list_orders_by_started_at_desc(store: RecordsStore) -> None:
    await _create(store, "old", started_at="2026-07-12T09:00:00+00:00")
    await _create(store, "new", started_at="2026-07-12T11:00:00+00:00")
    assert [r["id"] for r in await store.list()] == ["new", "old"]


async def test_rename(store: RecordsStore) -> None:
    await _create(store, "r1", started_at="2026-07-12T10:00:00+00:00")
    renamed = await store.rename("r1", "First growth run")
    assert renamed["name"] == "First growth run"
    with pytest.raises(UnknownRecordError):
        await store.rename("nope", "x")


async def test_finalize(store: RecordsStore) -> None:
    await _create(store, "r1", started_at="2026-07-12T10:00:00+00:00")
    await store.finalize("r1", status="completed", ended_at="2026-07-12T10:05:00+00:00")
    record = await store.get("r1")
    assert record["status"] == "completed"
    assert record["ended_at"] == "2026-07-12T10:05:00+00:00"


async def test_delete_removes_row_and_dir(store: RecordsStore, tmp_path: Path) -> None:
    await _create(store, "r1", started_at="2026-07-12T10:00:00+00:00")
    art = tmp_path / "runs/r1"
    art.mkdir(parents=True)
    (art / "report.json").write_text("{}")
    await store.delete("r1")
    assert not art.exists()
    with pytest.raises(UnknownRecordError):
        await store.get("r1")


async def test_delete_survives_missing_dir(store: RecordsStore) -> None:
    await _create(store, "r1", started_at="2026-07-12T10:00:00+00:00")
    await store.delete("r1")  # dir never created — must not raise
    with pytest.raises(UnknownRecordError):
        await store.delete("r1")


async def test_sweep_interrupted(store: RecordsStore) -> None:
    await _create(store, "r1", started_at="2026-07-12T10:00:00+00:00")
    await _create(store, "r2", started_at="2026-07-12T10:01:00+00:00")
    await store.finalize("r2", status="completed", ended_at="2026-07-12T10:02:00+00:00")
    assert await store.sweep_interrupted() == 1
    assert (await store.get("r1"))["status"] == "interrupted"
    assert (await store.get("r1"))["ended_at"] is not None
    assert (await store.get("r2"))["status"] == "completed"
    assert await store.sweep_interrupted() == 0


async def test_save_mapping_upserts(store: RecordsStore, db: Database) -> None:
    await store.save_mapping("e1", "lab_a", {"feed": "pump_1", "meter": "densitometer_1"})
    await store.save_mapping("e1", "lab_a", {"feed": "pump_2"})
    cur = await db.conn.execute(
        "SELECT role, device_id FROM mappings WHERE experiment_id='e1' AND lab='lab_a'"
        " ORDER BY role"
    )
    rows = [(r["role"], r["device_id"]) for r in await cur.fetchall()]
    assert rows == [("feed", "pump_2"), ("meter", "densitometer_1")]


# ---- artifact readers ----


def _make_artifacts(root: Path) -> Path:
    art = root / "runs/rX"
    art.mkdir(parents=True)
    (art / "run_log.jsonl").write_text(
        '{"timestamp": 1.0, "kind": "run_started", "block_id": null, "data": {}}\n'
        '{"timestamp": 2.0, "kind": "run_finished", "block_id": null,'
        ' "data": {"status": "completed"}}\n'
    )
    (art / "workflow.json").write_text(
        json.dumps({"streams": {"od": {"units": "AU"}, "ghost": {"units": "x"}}})
    )
    (art / "od.csv").write_text("timestamp,value\n1.5,0.5\n2.5,0.75\n")
    (art / "report.json").write_text(json.dumps({"status": "completed"}))
    return art


def test_read_events(tmp_path: Path) -> None:
    art = _make_artifacts(tmp_path)
    events = read_events(art)
    assert [e["kind"] for e in events] == ["run_started", "run_finished"]
    assert events[1]["data"] == {"status": "completed"}


def test_read_events_missing_file(tmp_path: Path) -> None:
    assert read_events(tmp_path) == []


def test_read_streams(tmp_path: Path) -> None:
    art = _make_artifacts(tmp_path)
    streams = read_streams(art)
    assert set(streams) == {"od"}  # 'ghost' declared but no CSV -> skipped
    assert streams["od"] == {"t": [1.5, 2.5], "v": [0.5, 0.75], "units": "AU"}


def test_read_streams_no_workflow(tmp_path: Path) -> None:
    assert read_streams(tmp_path) == {}


def test_build_zip(tmp_path: Path) -> None:
    art = _make_artifacts(tmp_path)
    payload = build_zip(art)
    with zipfile.ZipFile(io.BytesIO(payload)) as zf:
        names = set(zf.namelist())
        assert names == {"run_log.jsonl", "workflow.json", "od.csv", "report.json"}
        assert b"timestamp,value" in zf.read("od.csv")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_records.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'experiment_studio.records'`.

- [ ] **Step 3: Implement `records.py`**

Create `webapp/backend/experiment_studio/records.py`:

```python
"""Run records: rows, artifact directory readers, zip download. See design §8."""

from __future__ import annotations

import csv
import io
import json
import shutil
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import aiosqlite

from lab_devices.experiment import PersistenceError
from lab_devices.experiment.persist import safe_stream_filename

from experiment_studio.db import Database


class UnknownRecordError(Exception):
    """No record row with the requested id."""


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _row_json(row: aiosqlite.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "name": row["name"],
        "experiment_id": row["experiment_id"],
        "experiment_name": row["experiment_name"],
        "lab": row["lab"],
        "role_mapping": json.loads(row["role_mapping"]),
        "status": row["status"],
        "started_at": row["started_at"],
        "ended_at": row["ended_at"],
        "dir": row["dir"],
    }


_COLUMNS = (
    "id, name, experiment_id, experiment_name, lab, role_mapping, status,"
    " started_at, ended_at, dir"
)


class RecordsStore:
    """CRUD over records rows and their artifact dirs under data_dir (§8.1–8.2)."""

    def __init__(self, db: Database, data_dir: Path) -> None:
        self._db = db
        self._data_dir = data_dir

    def artifact_dir(self, record: dict[str, Any]) -> Path:
        return self._data_dir / record["dir"]

    async def create(
        self,
        *,
        record_id: str,
        name: str,
        experiment_id: str | None,
        experiment_name: str,
        lab: str,
        role_mapping: dict[str, str],
        started_at: str,
        dir: str,
    ) -> dict[str, Any]:
        await self._db.conn.execute(
            f"INSERT INTO records ({_COLUMNS})"
            " VALUES (?, ?, ?, ?, ?, ?, 'running', ?, NULL, ?)",
            (
                record_id,
                name,
                experiment_id,
                experiment_name,
                lab,
                json.dumps(role_mapping),
                started_at,
                dir,
            ),
        )
        await self._db.conn.commit()
        return await self.get(record_id)

    async def list(self) -> list[dict[str, Any]]:
        cur = await self._db.conn.execute(
            f"SELECT {_COLUMNS} FROM records ORDER BY started_at DESC"
        )
        return [_row_json(row) for row in await cur.fetchall()]

    async def get(self, record_id: str) -> dict[str, Any]:
        cur = await self._db.conn.execute(
            f"SELECT {_COLUMNS} FROM records WHERE id = ?", (record_id,)
        )
        row = await cur.fetchone()
        if row is None:
            raise UnknownRecordError(f"no record {record_id!r}")
        return _row_json(row)

    async def rename(self, record_id: str, name: str) -> dict[str, Any]:
        cur = await self._db.conn.execute(
            "UPDATE records SET name = ? WHERE id = ?", (name, record_id)
        )
        if cur.rowcount == 0:
            await self._db.conn.rollback()
            raise UnknownRecordError(f"no record {record_id!r}")
        await self._db.conn.commit()
        return await self.get(record_id)

    async def finalize(self, record_id: str, *, status: str, ended_at: str) -> None:
        await self._db.conn.execute(
            "UPDATE records SET status = ?, ended_at = ? WHERE id = ?",
            (status, ended_at, record_id),
        )
        await self._db.conn.commit()

    async def delete(self, record_id: str) -> None:
        record = await self.get(record_id)
        await self._db.conn.execute("DELETE FROM records WHERE id = ?", (record_id,))
        await self._db.conn.commit()
        target = (self._data_dir / record["dir"]).resolve()
        if target.is_relative_to(self._data_dir.resolve()) and target.is_dir():
            shutil.rmtree(target, ignore_errors=True)

    async def sweep_interrupted(self) -> int:
        """§7.6: any row still 'running' at boot was orphaned by a crash."""
        cur = await self._db.conn.execute(
            "UPDATE records SET status = 'interrupted', ended_at = ?"
            " WHERE status = 'running'",
            (_now(),),
        )
        await self._db.conn.commit()
        return cur.rowcount

    async def save_mapping(
        self, experiment_id: str | None, lab: str, role_mapping: dict[str, str]
    ) -> None:
        """S2 mapping memory: remember the last device per (experiment, lab, role)."""
        if experiment_id is None:
            return
        for role, device_id in role_mapping.items():
            await self._db.conn.execute(
                "INSERT OR REPLACE INTO mappings (experiment_id, lab, role, device_id)"
                " VALUES (?, ?, ?, ?)",
                (experiment_id, lab, role, device_id),
            )
        await self._db.conn.commit()


# ---- artifact readers (§6: /records/{id}/events, /records/{id}/streams, download) ----


def read_events(artifact_dir: Path) -> list[dict[str, Any]]:
    """Parsed run_log.jsonl; [] when absent (interrupted runs have no log — S7)."""
    path = artifact_dir / "run_log.jsonl"
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def read_streams(artifact_dir: Path) -> dict[str, dict[str, Any]]:
    """Stream series from the engine-written CSVs, keyed by declared stream name."""
    workflow_path = artifact_dir / "workflow.json"
    if not workflow_path.is_file():
        return {}
    declared = json.loads(workflow_path.read_text()).get("streams") or {}
    out: dict[str, dict[str, Any]] = {}
    for name, decl in declared.items():
        try:
            filename = safe_stream_filename(name)
        except PersistenceError:
            continue  # the engine refused this name at run time too
        path = artifact_dir / f"{filename}.csv"
        if not path.is_file():
            continue
        t: list[float] = []
        v: list[float] = []
        with path.open(newline="") as fh:
            reader = csv.reader(fh)
            next(reader, None)  # header
            for row in reader:
                if len(row) < 2:
                    continue
                t.append(float(row[0]))
                v.append(float(row[1]))
        units = decl.get("units") if isinstance(decl, dict) else None
        out[name] = {"t": t, "v": v, "units": units}
    return out


def build_zip(artifact_dir: Path) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(artifact_dir.rglob("*")):
            if path.is_file():
                zf.write(path, path.relative_to(artifact_dir).as_posix())
    return buffer.getvalue()
```

Note: `safe_stream_filename` is imported from `lab_devices.experiment.persist` (not
re-exported at package root); `PersistenceError` IS exported at the root.

- [ ] **Step 4: Run tests + gates**

Run: `.venv/bin/python -m pytest tests/test_records.py -q && .venv/bin/python -m pytest -q && .venv/bin/python -m mypy && .venv/bin/python -m ruff check .`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add webapp/backend/experiment_studio/records.py webapp/backend/tests/test_records.py
git commit -m "feat(studio): records store with crash sweep, artifact readers, zip builder"
```

---

### Task 3: TeeRunLogSink + WebInputProvider

**Files:**
- Create: `webapp/backend/experiment_studio/sinks.py`
- Create: `webapp/backend/experiment_studio/inputs.py`
- Test: `webapp/backend/tests/test_sinks.py`, `webapp/backend/tests/test_inputs.py`

**Interfaces:**
- Consumes: `RunEvent`, `BindingValue`, `InputRequest` from `lab_devices.experiment`;
  `run_event_to_dict` from `lab_devices.experiment.persist`; `validate_input_value` from
  `lab_devices.experiment.inputs`.
- Produces (used by Tasks 4–7):
  - `class TeeRunLogSink:` — `messages: list[dict[str, Any]]` (public), `closed: bool`,
    `last_seq: int` property (−1 when empty), `emit(event: RunEvent) -> None` (sync,
    never raises), `append_status(status: str) -> None`, `close() -> None`,
    `events() -> list[dict[str, Any]]` (envelope-stripped event dicts for
    run_log.jsonl), `stream(since: int) -> AsyncIterator[dict[str, Any]]`.
    **Invariant: `seq == index in messages`** — event and status messages share one
    contiguous counter, so `?since=N` replay is `messages[N+1:]`.
  - `class NoPendingInputError(Exception)`
  - `class WebInputProvider:` — `pending: InputRequest | None` property,
    `async request(request: InputRequest) -> BindingValue` (engine-side),
    `submit(value: BindingValue) -> BindingValue` (HTTP-side; raises
    `NoPendingInputError` → 409 or the engine's `EvaluationError` → 422, in which case
    the request stays pending).

- [ ] **Step 1: Write the failing tests**

Create `webapp/backend/tests/test_sinks.py`:

```python
"""TeeRunLogSink: seq invariant, replay stream, close semantics. See design §7.3, §7.5."""

import asyncio
from typing import Any

from lab_devices.experiment import RunEvent

from experiment_studio.sinks import TeeRunLogSink


def _event(kind: str, ts: float = 1.0) -> RunEvent:
    return RunEvent(ts, kind, "blocks[0]", {"k": "v"})


def test_emit_appends_event_messages_with_contiguous_seq() -> None:
    tee = TeeRunLogSink()
    assert tee.last_seq == -1
    tee.emit(_event("run_started"))
    tee.append_status("running")
    tee.emit(_event("block_started", 2.0))
    assert [m["seq"] for m in tee.messages] == [0, 1, 2]
    assert tee.messages[0] == {
        "type": "event",
        "seq": 0,
        "timestamp": 1.0,
        "kind": "run_started",
        "block_id": "blocks[0]",
        "data": {"k": "v"},
    }
    assert tee.messages[1] == {"type": "status", "seq": 1, "status": "running"}
    assert tee.last_seq == 2


def test_events_strips_envelope_and_skips_status() -> None:
    tee = TeeRunLogSink()
    tee.emit(_event("run_started"))
    tee.append_status("running")
    tee.emit(_event("run_finished", 3.0))
    events = tee.events()
    assert [e["kind"] for e in events] == ["run_started", "run_finished"]
    assert all("seq" not in e and "type" not in e for e in events)


async def _collect(tee: TeeRunLogSink, since: int) -> list[dict[str, Any]]:
    return [message async for message in tee.stream(since)]


async def test_stream_replays_then_follows_live_until_close() -> None:
    tee = TeeRunLogSink()
    tee.emit(_event("run_started"))
    tee.emit(_event("block_started"))
    task = asyncio.create_task(_collect(tee, since=0))
    await asyncio.sleep(0)  # let the consumer drain the replay and park
    tee.emit(_event("block_finished"))
    tee.append_status("completed")
    tee.close()
    messages = await asyncio.wait_for(task, 5)
    assert [m["seq"] for m in messages] == [1, 2, 3]
    assert messages[-1] == {"type": "status", "seq": 3, "status": "completed"}


async def test_stream_since_beyond_end_waits_for_new_messages() -> None:
    tee = TeeRunLogSink()
    tee.emit(_event("run_started"))
    task = asyncio.create_task(_collect(tee, since=0))
    await asyncio.sleep(0)
    tee.close()
    assert await asyncio.wait_for(task, 5) == []


async def test_two_consumers_both_receive_everything() -> None:
    tee = TeeRunLogSink()
    a = asyncio.create_task(_collect(tee, since=-1))
    b = asyncio.create_task(_collect(tee, since=-1))
    await asyncio.sleep(0)
    tee.emit(_event("run_started"))
    await asyncio.sleep(0)
    tee.emit(_event("run_finished"))
    tee.close()
    got_a = await asyncio.wait_for(a, 5)
    got_b = await asyncio.wait_for(b, 5)
    assert [m["seq"] for m in got_a] == [0, 1]
    assert got_a == got_b


async def test_stream_on_closed_tee_returns_buffer_then_ends() -> None:
    tee = TeeRunLogSink()
    tee.emit(_event("run_started"))
    tee.append_status("completed")
    tee.close()
    messages = await asyncio.wait_for(_collect(tee, since=-1), 5)
    assert [m["seq"] for m in messages] == [0, 1]
```

Create `webapp/backend/tests/test_inputs.py`:

```python
"""WebInputProvider: pending lifecycle, validation, double-submit. See design §7.4."""

import asyncio

import pytest

from lab_devices.experiment import EvaluationError, InputRequest

from experiment_studio.inputs import NoPendingInputError, WebInputProvider


def _request(type_: str = "int", **kw: object) -> InputRequest:
    fields = {
        "name": "target",
        "type": type_,
        "prompt": "T?",
        "min": 1,
        "max": 10,
        "choices": None,
        "block_id": "blocks[0]",
    }
    fields.update(kw)
    return InputRequest(**fields)  # type: ignore[arg-type]


async def test_submit_resolves_pending_request() -> None:
    provider = WebInputProvider()
    assert provider.pending is None
    task = asyncio.create_task(provider.request(_request()))
    await asyncio.sleep(0)
    assert provider.pending is not None
    assert provider.pending.name == "target"
    assert provider.submit(7) == 7
    assert await asyncio.wait_for(task, 5) == 7
    assert provider.pending is None


async def test_submit_invalid_value_keeps_request_pending() -> None:
    provider = WebInputProvider()
    task = asyncio.create_task(provider.request(_request()))
    await asyncio.sleep(0)
    with pytest.raises(EvaluationError):
        provider.submit(0)  # below min
    with pytest.raises(EvaluationError):
        provider.submit("seven")  # wrong type
    assert provider.pending is not None
    provider.submit(3)
    assert await asyncio.wait_for(task, 5) == 3


async def test_submit_without_pending_raises() -> None:
    provider = WebInputProvider()
    with pytest.raises(NoPendingInputError):
        provider.submit(1)


async def test_double_submit_raises() -> None:
    provider = WebInputProvider()
    task = asyncio.create_task(provider.request(_request()))
    await asyncio.sleep(0)
    provider.submit(2)
    with pytest.raises(NoPendingInputError):
        provider.submit(3)
    assert await asyncio.wait_for(task, 5) == 2


async def test_cancelled_request_clears_pending() -> None:
    """Abort cancels the run task; the awaited future dies with it (§7.4)."""
    provider = WebInputProvider()
    task = asyncio.create_task(provider.request(_request()))
    await asyncio.sleep(0)
    assert provider.pending is not None
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert provider.pending is None
    with pytest.raises(NoPendingInputError):
        provider.submit(1)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_sinks.py tests/test_inputs.py -q`
Expected: FAIL with `ModuleNotFoundError` for both new modules.

- [ ] **Step 3: Implement**

Create `webapp/backend/experiment_studio/sinks.py`:

```python
"""In-memory tee run-log sink feeding the WS broadcast buffer. See design §7.3, §7.5."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

from lab_devices.experiment import RunEvent
from lab_devices.experiment.persist import run_event_to_dict


class TeeRunLogSink:
    """Buffers run events in memory and wakes WebSocket readers.

    `seq` equals the message's index in `messages` (contiguous from 0); event and
    status messages share the counter so `?since=N` replay is a list slice. emit()
    must never raise and never block (§7.3): a raising sink can make a run
    un-abortable (engine Increment-5 lesson).
    """

    def __init__(self) -> None:
        self.messages: list[dict[str, Any]] = []
        self.closed = False
        self._wakeup = asyncio.Event()

    @property
    def last_seq(self) -> int:
        return len(self.messages) - 1

    def emit(self, event: RunEvent) -> None:
        try:
            self._append(
                {"type": "event", "seq": len(self.messages), **run_event_to_dict(event)}
            )
        except Exception:  # pragma: no cover — §7.3 hard rule
            pass

    def append_status(self, status: str) -> None:
        self._append({"type": "status", "seq": len(self.messages), "status": status})

    def close(self) -> None:
        """Terminal: streams drain any remaining messages, then finish."""
        self.closed = True
        self._wakeup.set()

    def events(self) -> list[dict[str, Any]]:
        """Engine events without the WS envelope — the run_log.jsonl payload (§7.1.5)."""
        return [
            {key: value for key, value in message.items() if key not in ("type", "seq")}
            for message in self.messages
            if message["type"] == "event"
        ]

    async def stream(self, since: int) -> AsyncIterator[dict[str, Any]]:
        """Yield messages with seq > since, then live messages until close()."""
        index = max(since + 1, 0)
        while True:
            while index < len(self.messages):
                yield self.messages[index]
                index += 1
            if self.closed:
                return
            self._wakeup.clear()
            if index < len(self.messages) or self.closed:
                continue  # appended/closed between drain and clear — re-check
            await self._wakeup.wait()

    def _append(self, message: dict[str, Any]) -> None:
        self.messages.append(message)
        self._wakeup.set()
```

Create `webapp/backend/experiment_studio/inputs.py`:

```python
"""Web operator-input provider: one pending request, resolved over HTTP. See design §7.4."""

from __future__ import annotations

import asyncio

from lab_devices.experiment import BindingValue, InputRequest
from lab_devices.experiment.inputs import validate_input_value


class NoPendingInputError(Exception):
    """POST /runs/{id}/input with no operator input awaiting a value (§6: 409)."""


class WebInputProvider:
    """Parks each engine InputRequest as an asyncio.Future until submit() resolves it.

    Abort cancels the run task and the awaited future with it; the finally block
    clears pending state so late submits get NoPendingInputError, never a leak.
    """

    def __init__(self) -> None:
        self._request: InputRequest | None = None
        self._future: asyncio.Future[BindingValue] | None = None

    @property
    def pending(self) -> InputRequest | None:
        if self._future is None or self._future.done():
            return None
        return self._request

    async def request(self, request: InputRequest) -> BindingValue:
        self._request = request
        self._future = asyncio.get_running_loop().create_future()
        try:
            return await self._future
        finally:
            self._request = None
            self._future = None

    def submit(self, value: BindingValue) -> BindingValue:
        """Validate with the engine's rules and resolve the pending request.

        Raises NoPendingInputError (409) or EvaluationError (422 — stays pending).
        """
        if self._request is None or self._future is None or self._future.done():
            raise NoPendingInputError("no operator input is pending")
        validated = validate_input_value(self._request, value)
        self._future.set_result(validated)
        return validated
```

- [ ] **Step 4: Run tests + gates**

Run: `.venv/bin/python -m pytest tests/test_sinks.py tests/test_inputs.py -q && .venv/bin/python -m mypy && .venv/bin/python -m ruff check .`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add webapp/backend/experiment_studio/sinks.py webapp/backend/experiment_studio/inputs.py webapp/backend/tests/test_sinks.py webapp/backend/tests/test_inputs.py
git commit -m "feat(studio): tee run-log sink with seq broadcast buffer, web input provider"
```

---

### Task 4: RunManager — start preflight, execution wrapper, terminal finalize

**Files:**
- Create: `webapp/backend/experiment_studio/runner.py` (complete module including the
  control methods Task 5 tests — the module ships whole; Task 5 adds only tests)
- Create: `webapp/backend/tests/runsupport.py` (shared run-test harness)
- Modify: `webapp/backend/tests/conftest.py` (add `env` fixture)
- Test: `webapp/backend/tests/test_runner.py`

**Interfaces:**
- Consumes: Tasks 1–3 (`Database`, `RecordsStore`, `TeeRunLogSink`, `WebInputProvider`),
  `ExperimentsStore`/`ExperimentDoc`, `roles.substitute`, engine `ExperimentRun`/
  `RunOptions`/`workflow_from_dict`/`ValidationError`/`WorkflowLoadError`,
  `LabRegistry.lookup` (async), `LabClient.list_devices`.
- Produces (used by Tasks 5–7):
  - `ClientFactory = Callable[[LabInfo], LabClient]`
  - Exceptions: `RunActiveError(active_run_id: str)`,
    `PreflightError(diagnostics: list[dict[str, str]])`,
    `StartValidationError(diagnostics: list[dict[str, str]], record_id: str)`,
    `UnknownRunError`
  - `@dataclass ActiveRun` — public fields `run_id, record_id, experiment_id,
    experiment_name, lab, role_mapping, status, run, tee, inputs, client,
    artifact_dir, task`
  - `class RunManager:`
    - `__init__(self, db: Database, data_dir: Path, registry: LabRegistry, *, client_factory: ClientFactory | None = None, run_options: dict[str, Any] | None = None) -> None`
    - `async start(self, experiment_id: str, lab: str, role_mapping: dict[str, str]) -> str`
    - `active(self) -> ActiveRun | None`, `active_payload(self) -> dict[str, Any] | None`
    - `is_lab_busy(self, lab: str) -> bool`
    - `stream(self, run_id: str, since: int) -> AsyncIterator[dict[str, Any]]`
    - `pause/resume/abort(self, run_id: str) -> None`,
      `submit_input(self, run_id: str, value: BindingValue) -> None`
    - `async shutdown(self) -> None`, `current_task(self) -> asyncio.Task[None] | None`
- `active_payload()` shape (§6 GET /api/runs/active): `{run_id, record_id,
  experiment: {id, name}, lab, status, seq, pending_input}` where `pending_input` is
  `dataclasses.asdict(InputRequest)` or `None`.
- `report.json` shape (§8.2): `{status, error, finalize_errors, persistence_errors,
  diagnostics, clock_origin, started_at, ended_at, experiment_name, lab, role_mapping}`.

- [ ] **Step 1: Write the shared test harness**

Create `webapp/backend/tests/runsupport.py`:

```python
"""Harness for run-backend tests: fake roster registry, FakeLab-backed clients, fast docs."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

# Engine test doubles live at the repo root (tests/fakelab.py); bootstrap the path so
# the webapp suite reuses them instead of forking a copy.
_ENGINE_TESTS = str(Path(__file__).resolve().parents[3] / "tests")
if _ENGINE_TESTS not in sys.path:
    sys.path.insert(0, _ENGINE_TESTS)

import httpx  # noqa: E402
from fakelab import FakeLab  # noqa: E402

from lab_devices.client import LabClient  # noqa: E402
from lab_devices.discovery import LabInfo, LabRegistry  # noqa: E402

from experiment_studio.runner import ClientFactory  # noqa: E402

LAB = "lab_a"
MAPPING = {"feed": "pump_1", "meter": "densitometer_1"}
FAST_RUN_OPTIONS: dict[str, Any] = {"job_poll_interval": 0.005, "job_poll_max": 0.01}
TERMINAL = {"completed", "failed", "aborted", "cancelled", "interrupted"}


def default_fake() -> FakeLab:
    fake = FakeLab()
    fake.add_device("pump_1", "pump")
    fake.add_device("densitometer_1", "densitometer")
    return fake


def fake_registry() -> LabRegistry:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={LAB: {"host": "lab-a", "port": 9000}})

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return LabRegistry(url="http://siteapp:8000/api/clients/", http=http)


def fake_client_factory(fake: FakeLab) -> ClientFactory:
    def factory(info: LabInfo) -> LabClient:
        http = httpx.AsyncClient(
            transport=httpx.MockTransport(fake.handler),
            base_url=f"http://{info.host}:{info.port}",
        )
        return LabClient(info.host, info.port, http=http)

    return factory


def make_doc(
    blocks: list[dict[str, Any]],
    *,
    name: str = "Growth run",
    roles: dict[str, dict[str, str]] | None = None,
    streams: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "doc_version": 1,
        "name": name,
        "roles": (
            roles
            if roles is not None
            else {"feed": {"type": "pump"}, "meter": {"type": "densitometer"}}
        ),
        "workflow": {
            "schema_version": 1,
            "metadata": {"name": name},
            "persistence": {"default": "in_memory", "format": "jsonl"},
            "streams": streams if streams is not None else {"od": {"units": "AU"}},
            "blocks": blocks,
        },
    }


HAPPY_BLOCKS: list[dict[str, Any]] = [
    {
        "serial": {
            "children": [
                {
                    "command": {
                        "device": "feed",
                        "verb": "dispense",
                        "params": {"volume_ml": 1},
                    }
                },
                {"measure": {"device": "meter", "verb": "measure", "into": "od"}},
                {"wait": {"duration": "1ms"}},
            ]
        }
    }
]

INPUT_BLOCKS: list[dict[str, Any]] = [
    {
        "serial": {
            "children": [
                {
                    "operator_input": {
                        "name": "target",
                        "type": "int",
                        "prompt": "Target cycles?",
                        "min": 1,
                        "max": 10,
                    }
                },
                {"measure": {"device": "meter", "verb": "measure", "into": "od"}},
            ]
        }
    }
]

INVALID_BLOCKS: list[dict[str, Any]] = [
    {
        "serial": {
            "children": [
                {"command": {"device": "feed", "verb": "dispense", "params": {}}}
            ]
        }
    }
]
```

Add to `webapp/backend/tests/conftest.py` (keep the existing fixtures; add imports and
the `env` fixture):

```python
from types import SimpleNamespace

import runsupport
from experiment_studio.db import Database
from experiment_studio.docs_store import ExperimentsStore
from experiment_studio.runner import RunManager


@pytest.fixture
async def env(tmp_path: Path) -> AsyncIterator[SimpleNamespace]:
    """Manager-level harness: real Database + RunManager over a FakeLab."""
    fake = runsupport.default_fake()
    db = await Database.connect(tmp_path / "studio.db")
    registry = runsupport.fake_registry()
    manager = RunManager(
        db,
        tmp_path,
        registry,
        client_factory=runsupport.fake_client_factory(fake),
        run_options=dict(runsupport.FAST_RUN_OPTIONS),
    )
    yield SimpleNamespace(
        fake=fake, db=db, manager=manager, docs=ExperimentsStore(db), data_dir=tmp_path
    )
    await manager.shutdown()
    await registry.aclose()
    await db.close()
```

- [ ] **Step 2: Write the failing tests**

Create `webapp/backend/tests/test_runner.py`:

```python
"""RunManager lifecycle at the manager level (no HTTP). See design §7.1–7.2, §8.2."""

import asyncio
import json
from types import SimpleNamespace

import pytest

import runsupport
from experiment_studio.docs_store import ExperimentDoc
from experiment_studio.records import RecordsStore
from experiment_studio.runner import PreflightError, RunActiveError, StartValidationError


async def _create_doc(env: SimpleNamespace, blocks: list, **kw: object) -> str:
    doc = ExperimentDoc.model_validate(runsupport.make_doc(blocks, **kw))
    created = await env.docs.create(doc)
    return str(created["id"])


async def _finish(env: SimpleNamespace, timeout: float = 10.0) -> None:
    task = env.manager.current_task()
    assert task is not None
    await asyncio.wait_for(task, timeout)


async def test_happy_path_completes_with_full_artifacts(env: SimpleNamespace) -> None:
    experiment_id = await _create_doc(env, runsupport.HAPPY_BLOCKS)
    run_id = await env.manager.start(experiment_id, runsupport.LAB, runsupport.MAPPING)
    payload = env.manager.active_payload()
    assert payload is not None
    assert payload["run_id"] == run_id
    assert payload["record_id"] == run_id
    assert payload["experiment"] == {"id": experiment_id, "name": "Growth run"}
    assert payload["lab"] == runsupport.LAB
    await _finish(env)
    assert env.manager.active_payload() is None

    record = await RecordsStore(env.db, env.data_dir).get(run_id)
    assert record["status"] == "completed"
    assert record["ended_at"] is not None
    assert record["name"].startswith("Growth run — ")

    art = env.data_dir / f"runs/{run_id}"
    assert (art / "doc.json").is_file()
    assert (art / "od.csv").is_file()
    events = [json.loads(line) for line in (art / "run_log.jsonl").read_text().splitlines()]
    kinds = [e["kind"] for e in events]
    assert kinds[0] == "run_started"
    assert "measure_recorded" in kinds
    assert kinds[-1] == "run_finished"

    report = json.loads((art / "report.json").read_text())
    assert report["status"] == "completed"
    assert report["error"] is None
    assert report["finalize_errors"] == []
    assert report["persistence_errors"] == []
    assert isinstance(report["clock_origin"], float)
    assert report["started_at"] < report["ended_at"]
    assert report["role_mapping"] == runsupport.MAPPING
    # engine event timestamps are monotonic-clock values comparable to clock_origin
    measure = next(e for e in events if e["kind"] == "measure_recorded")
    assert measure["timestamp"] >= report["clock_origin"]


async def test_persistence_forced_to_disk_csv(env: SimpleNamespace) -> None:
    """§7.2: whatever the doc says, the run copy persists every stream to disk as CSV."""
    doc = runsupport.make_doc(
        runsupport.HAPPY_BLOCKS,
        streams={"od": {"units": "AU", "persistence": "in_memory"}},
    )
    created = await env.docs.create(ExperimentDoc.model_validate(doc))
    run_id = await env.manager.start(created["id"], runsupport.LAB, runsupport.MAPPING)
    await _finish(env)
    art = env.data_dir / f"runs/{run_id}"
    workflow = json.loads((art / "workflow.json").read_text())
    assert workflow["persistence"] == {"default": "disk", "format": "csv"}
    assert "persistence" not in workflow["streams"]["od"]
    assert workflow["blocks"][0]["serial"]["children"][0]["command"]["device"] == "pump_1"
    lines = (art / "od.csv").read_text().splitlines()
    assert lines[0] == "timestamp,value"
    assert len(lines) == 2


async def test_mapping_saved_on_start(env: SimpleNamespace) -> None:
    experiment_id = await _create_doc(env, runsupport.HAPPY_BLOCKS)
    await env.manager.start(experiment_id, runsupport.LAB, runsupport.MAPPING)
    await _finish(env)
    cur = await env.db.conn.execute(
        "SELECT role, device_id FROM mappings WHERE experiment_id = ? ORDER BY role",
        (experiment_id,),
    )
    rows = [(r["role"], r["device_id"]) for r in await cur.fetchall()]
    assert rows == [("feed", "pump_1"), ("meter", "densitometer_1")]


async def test_second_start_rejected_while_active(env: SimpleNamespace) -> None:
    env.fake.hold_job("dispense")
    experiment_id = await _create_doc(env, runsupport.HAPPY_BLOCKS)
    run_id = await env.manager.start(experiment_id, runsupport.LAB, runsupport.MAPPING)
    with pytest.raises(RunActiveError) as info:
        await env.manager.start(experiment_id, runsupport.LAB, runsupport.MAPPING)
    assert info.value.active_run_id == run_id
    env.fake.complete_job("j-1")
    await _finish(env)


@pytest.mark.parametrize(
    ("mapping", "fragment"),
    [
        ({"feed": "pump_1"}, "not mapped"),
        ({"feed": "densitometer_1", "meter": "densitometer_1"}, "not a 'pump'"),
        ({**{"feed": "pump_1", "meter": "densitometer_1"}, "ghost": "pump_1"}, "unknown role"),
        ({"feed": "pump_9", "meter": "densitometer_1"}, "not found in lab"),
    ],
)
async def test_preflight_failures(
    env: SimpleNamespace, mapping: dict[str, str], fragment: str
) -> None:
    experiment_id = await _create_doc(env, runsupport.HAPPY_BLOCKS)
    with pytest.raises(PreflightError) as info:
        await env.manager.start(experiment_id, runsupport.LAB, mapping)
    assert any(fragment in d["message"] for d in info.value.diagnostics)
    assert all(d["category"] == "mapping" for d in info.value.diagnostics)
    # preflight failures precede record creation (§7.1: record exists only from step 3)
    assert await RecordsStore(env.db, env.data_dir).list() == []
    assert env.manager.active_payload() is None


async def test_construction_validation_failure_finalizes_failed_record(
    env: SimpleNamespace,
) -> None:
    """§7.1: ExperimentRun construction ValidationError -> 422 + failed record with
    diagnostics in report.json."""
    experiment_id = await _create_doc(env, runsupport.INVALID_BLOCKS)
    with pytest.raises(StartValidationError) as info:
        await env.manager.start(experiment_id, runsupport.LAB, runsupport.MAPPING)
    assert info.value.diagnostics
    record = await RecordsStore(env.db, env.data_dir).get(info.value.record_id)
    assert record["status"] == "failed"
    art = env.data_dir / record["dir"]
    report = json.loads((art / "report.json").read_text())
    assert report["status"] == "failed"
    assert report["diagnostics"] == info.value.diagnostics
    assert (art / "doc.json").is_file()
    assert (art / "workflow.json").is_file()
    assert not (art / "run_log.jsonl").exists()
    assert env.manager.active_payload() is None
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_runner.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'experiment_studio.runner'`.

- [ ] **Step 4: Implement `runner.py`**

Create `webapp/backend/experiment_studio/runner.py` (complete module — control methods
included here; Task 5 only adds their tests):

```python
"""RunManager: at most one in-process experiment run per app instance. See design §7."""

from __future__ import annotations

import asyncio
import dataclasses
import json
import logging
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from lab_devices.client import LabClient
from lab_devices.discovery import LabInfo, LabRegistry
from lab_devices.experiment import (
    BindingValue,
    ExperimentRun,
    RunOptions,
    RunReport,
    ValidationError,
    WorkflowLoadError,
    workflow_from_dict,
)

from experiment_studio.db import Database
from experiment_studio.docs_store import ExperimentDoc, ExperimentsStore
from experiment_studio.inputs import WebInputProvider
from experiment_studio.records import RecordsStore
from experiment_studio.roles import substitute
from experiment_studio.sinks import TeeRunLogSink

_LOG = logging.getLogger(__name__)

ClientFactory = Callable[[LabInfo], LabClient]


class RunActiveError(Exception):
    """A run is already active (S8); also raised by guards that refuse work mid-run."""

    def __init__(self, active_run_id: str) -> None:
        super().__init__("a run is already active")
        self.active_run_id = active_run_id


class PreflightError(Exception):
    """Role mapping incomplete/mistyped or devices missing from the roster (§7.1.2)."""

    def __init__(self, diagnostics: list[dict[str, str]]) -> None:
        super().__init__(f"{len(diagnostics)} preflight error(s)")
        self.diagnostics = diagnostics


class StartValidationError(Exception):
    """Engine rejected the substituted workflow at construction (§7.1: 422 + record)."""

    def __init__(self, diagnostics: list[dict[str, str]], record_id: str) -> None:
        super().__init__(f"{len(diagnostics)} validation error(s)")
        self.diagnostics = diagnostics
        self.record_id = record_id


class UnknownRunError(Exception):
    """Control request for a run id that is not the active run (§6: 404)."""


@dataclass
class ActiveRun:
    run_id: str
    record_id: str
    experiment_id: str
    experiment_name: str
    lab: str
    role_mapping: dict[str, str]
    status: str  # running | paused; terminal statuses land on the record row
    run: ExperimentRun
    tee: TeeRunLogSink
    inputs: WebInputProvider
    client: LabClient
    artifact_dir: Path
    task: asyncio.Task[None] | None = None


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _default_record_name(experiment_name: str) -> str:
    local = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M")
    return f"{experiment_name} — {local}"


def _diag(role: str, message: str) -> dict[str, str]:
    return {"category": "mapping", "path": f"roles[{role!r}]", "message": message}


def _mapping_diagnostics(
    doc: ExperimentDoc, role_mapping: dict[str, str]
) -> list[dict[str, str]]:
    """§7.1.2 shape checks (roster existence is checked separately, needs the lab)."""
    diagnostics: list[dict[str, str]] = []
    for role, spec in doc.roles.items():
        device_id = role_mapping.get(role)
        if device_id is None:
            diagnostics.append(_diag(role, f"role {role!r} is not mapped to a device"))
        elif device_id.rsplit("_", 1)[0] != spec.type:
            diagnostics.append(
                _diag(role, f"device {device_id!r} is not a {spec.type!r}")
            )
    for extra in sorted(set(role_mapping) - set(doc.roles)):
        diagnostics.append(_diag(extra, f"mapping references unknown role {extra!r}"))
    return diagnostics


def _force_disk_persistence(workflow: dict[str, Any]) -> None:
    """§7.2: run copies always persist every stream to disk as CSV (S5)."""
    workflow["persistence"] = {"default": "disk", "format": "csv"}
    streams = workflow.get("streams")
    if isinstance(streams, dict):
        for decl in streams.values():
            if isinstance(decl, dict):
                decl.pop("persistence", None)


def _engine_diagnostics(exc: ValidationError | WorkflowLoadError) -> list[dict[str, str]]:
    if isinstance(exc, ValidationError):
        return [
            {"category": d.category, "path": d.path, "message": d.message}
            for d in exc.diagnostics
        ]
    return [{"category": "schema", "path": "workflow", "message": str(exc)}]


def _write_run_log(artifact_dir: Path, tee: TeeRunLogSink) -> None:
    lines = [json.dumps(event) for event in tee.events()]
    text = "\n".join(lines) + ("\n" if lines else "")
    (artifact_dir / "run_log.jsonl").write_text(text)


def _write_report(
    artifact_dir: Path,
    *,
    report: RunReport | None,
    status: str,
    clock_origin: float | None,
    started_at: str,
    ended_at: str,
    experiment_name: str,
    lab: str,
    role_mapping: dict[str, str],
    error: str | None = None,
    diagnostics: list[dict[str, str]] | None = None,
) -> None:
    if report is not None and report.error is not None:
        error = str(report.error)
    payload = {
        "status": status,
        "error": error,
        "finalize_errors": [str(e) for e in report.finalize_errors] if report else [],
        "persistence_errors": (
            [str(e) for e in report.persistence_errors] if report else []
        ),
        "diagnostics": diagnostics or [],
        "clock_origin": clock_origin,
        "started_at": started_at,
        "ended_at": ended_at,
        "experiment_name": experiment_name,
        "lab": lab,
        "role_mapping": role_mapping,
    }
    (artifact_dir / "report.json").write_text(json.dumps(payload, indent=2))


class RunManager:
    """Process singleton owning at most one (LabClient, ExperimentRun, Task) (§7.1)."""

    def __init__(
        self,
        db: Database,
        data_dir: Path,
        registry: LabRegistry,
        *,
        client_factory: ClientFactory | None = None,
        run_options: dict[str, Any] | None = None,
    ) -> None:
        self._db = db
        self._data_dir = data_dir
        self._registry = registry  # not owned: LabsService/lifespan closes it
        self._client_factory: ClientFactory = client_factory or (
            lambda info: LabClient(info.host, info.port)
        )
        self._run_options = dict(run_options or {})
        # kept after terminal so WS replay survives until the next start (§7.5)
        self._current: ActiveRun | None = None

    # ---- introspection ----

    def active(self) -> ActiveRun | None:
        current = self._current
        if current is None or current.task is None or current.task.done():
            return None
        return current

    def active_payload(self) -> dict[str, Any] | None:
        """GET /api/runs/active — everything a fresh browser needs to reattach (§6)."""
        current = self.active()
        if current is None:
            return None
        pending = current.inputs.pending
        return {
            "run_id": current.run_id,
            "record_id": current.record_id,
            "experiment": {"id": current.experiment_id, "name": current.experiment_name},
            "lab": current.lab,
            "status": current.status,
            "seq": current.tee.last_seq,
            "pending_input": dataclasses.asdict(pending) if pending is not None else None,
        }

    def is_lab_busy(self, lab: str) -> bool:
        current = self.active()
        return current is not None and current.lab == lab

    def current_task(self) -> asyncio.Task[None] | None:
        return self._current.task if self._current is not None else None

    def stream(self, run_id: str, since: int) -> AsyncIterator[dict[str, Any]]:
        """WS source: replay + live for the current (possibly finished) run (§7.5)."""
        current = self._current
        if current is None or current.run_id != run_id:
            raise UnknownRunError(f"no run {run_id!r}")
        return current.tee.stream(since)

    # ---- lifecycle ----

    async def start(
        self, experiment_id: str, lab: str, role_mapping: dict[str, str]
    ) -> str:
        active = self.active()
        if active is not None:
            raise RunActiveError(active.run_id)
        stored = await ExperimentsStore(self._db).get(experiment_id)
        doc = ExperimentDoc.model_validate(stored["doc"])
        diagnostics = _mapping_diagnostics(doc, role_mapping)
        if diagnostics:
            raise PreflightError(diagnostics)
        info = await self._registry.lookup(lab)
        client = self._client_factory(info)
        try:
            return await self._start_checked(
                client, stored, doc, experiment_id, lab, role_mapping
            )
        except BaseException:
            await client.aclose()
            raise

    async def _start_checked(
        self,
        client: LabClient,
        stored: dict[str, Any],
        doc: ExperimentDoc,
        experiment_id: str,
        lab: str,
        role_mapping: dict[str, str],
    ) -> str:
        present = {device.id for device in await client.list_devices() if device.id}
        roster_diags = [
            _diag(role, f"device {device_id!r} not found in lab {lab!r}")
            for role, device_id in sorted(role_mapping.items())
            if device_id not in present
        ]
        if roster_diags:
            raise PreflightError(roster_diags)
        substituted, ref_diags = substitute(doc.workflow, role_mapping)
        if ref_diags:
            raise PreflightError(ref_diags)
        _force_disk_persistence(substituted)

        run_id = str(uuid4())
        dir_rel = f"runs/{run_id}"
        artifact_dir = self._data_dir / dir_rel
        artifact_dir.mkdir(parents=True, exist_ok=False)
        started_at = _utc_now()
        records = RecordsStore(self._db, self._data_dir)
        await records.create(
            record_id=run_id,
            name=_default_record_name(doc.name),
            experiment_id=experiment_id,
            experiment_name=doc.name,
            lab=lab,
            role_mapping=role_mapping,
            started_at=started_at,
            dir=dir_rel,
        )
        (artifact_dir / "doc.json").write_text(json.dumps(stored["doc"], indent=2))
        (artifact_dir / "workflow.json").write_text(json.dumps(substituted, indent=2))

        tee = TeeRunLogSink()
        inputs = WebInputProvider()
        options = RunOptions(
            log_sink=tee,
            input_provider=inputs,
            output_dir=artifact_dir,
            **self._run_options,
        )
        try:
            # construction runs the engine validator against the REAL device ids —
            # this is the real-mapping re-validation (two roles on one device etc.)
            run = ExperimentRun(client, workflow_from_dict(substituted), options)
        except (ValidationError, WorkflowLoadError) as exc:
            diagnostics = _engine_diagnostics(exc)
            ended_at = _utc_now()
            _write_report(
                artifact_dir,
                report=None,
                status="failed",
                clock_origin=None,
                started_at=started_at,
                ended_at=ended_at,
                experiment_name=doc.name,
                lab=lab,
                role_mapping=role_mapping,
                error=str(exc),
                diagnostics=diagnostics,
            )
            await records.finalize(run_id, status="failed", ended_at=ended_at)
            raise StartValidationError(diagnostics, run_id) from exc

        clock_origin = options.clock.now()
        current = ActiveRun(
            run_id=run_id,
            record_id=run_id,
            experiment_id=experiment_id,
            experiment_name=doc.name,
            lab=lab,
            role_mapping=dict(role_mapping),
            status="running",
            run=run,
            tee=tee,
            inputs=inputs,
            client=client,
            artifact_dir=artifact_dir,
        )
        self._current = current
        tee.append_status("running")
        current.task = asyncio.create_task(
            self._execute(current, clock_origin=clock_origin, started_at=started_at)
        )
        try:
            await records.save_mapping(experiment_id, lab, role_mapping)  # S2 memory
        except Exception:
            _LOG.exception("failed saving role mapping for %s", run_id)
        return run_id

    async def _execute(
        self, current: ActiveRun, *, clock_origin: float, started_at: str
    ) -> None:
        try:
            await current.run.execute()
        except BaseException:  # outcome (incl. abort/cancel) lives on run.report
            pass
        finally:
            task = asyncio.current_task()
            if task is not None:
                task.uncancel()  # abort() cancelled us once; finalization must proceed
            report = current.run.report
            status = report.status if report is not None else "interrupted"
            current.status = status
            ended_at = _utc_now()
            try:
                _write_run_log(current.artifact_dir, current.tee)
                _write_report(
                    current.artifact_dir,
                    report=report,
                    status=status,
                    clock_origin=clock_origin,
                    started_at=started_at,
                    ended_at=ended_at,
                    experiment_name=current.experiment_name,
                    lab=current.lab,
                    role_mapping=current.role_mapping,
                )
            except OSError:
                _LOG.exception("failed writing artifacts for run %s", current.run_id)
            try:
                await RecordsStore(self._db, self._data_dir).finalize(
                    current.record_id, status=status, ended_at=ended_at
                )
            except Exception:
                _LOG.exception("failed finalizing record %s", current.record_id)
            current.tee.append_status(status)
            current.tee.close()
            try:
                await current.client.aclose()
            except Exception:
                _LOG.exception("failed closing lab client for run %s", current.run_id)

    # ---- controls (§6) ----

    def _require_active(self, run_id: str) -> ActiveRun:
        current = self.active()
        if current is None or current.run_id != run_id:
            raise UnknownRunError(f"no active run {run_id!r}")
        return current

    def pause(self, run_id: str) -> None:
        current = self._require_active(run_id)
        if current.status != "paused":
            current.run.pause()
            current.status = "paused"
            current.tee.append_status("paused")

    def resume(self, run_id: str) -> None:
        current = self._require_active(run_id)
        if current.status != "running":
            current.run.resume()
            current.status = "running"
            current.tee.append_status("running")

    def abort(self, run_id: str) -> None:
        """Idempotent while active (§6); the engine's abort() is itself idempotent."""
        self._require_active(run_id).run.abort()

    def submit_input(self, run_id: str, value: BindingValue) -> None:
        self._require_active(run_id).inputs.submit(value)

    async def shutdown(self) -> None:
        """Graceful teardown: abort any active run and wait for its finalization."""
        current = self._current
        if current is None or current.task is None or current.task.done():
            return
        current.run.abort()
        try:
            await asyncio.wait_for(asyncio.shield(current.task), timeout=15)
        except (TimeoutError, asyncio.CancelledError):
            _LOG.warning("run %s did not finalize during shutdown", current.run_id)
```

- [ ] **Step 5: Run tests + gates**

Run: `.venv/bin/python -m pytest tests/test_runner.py -q && .venv/bin/python -m pytest -q && .venv/bin/python -m mypy && .venv/bin/python -m ruff check .`
Expected: all PASS. (If `test_happy_path` is flaky on timing, the FakeLab jobs are not
completing — check `run_options` reached `RunOptions`, do NOT lengthen sleeps.)

- [ ] **Step 6: Commit**

```bash
git add webapp/backend/experiment_studio/runner.py webapp/backend/tests/runsupport.py webapp/backend/tests/conftest.py webapp/backend/tests/test_runner.py
git commit -m "feat(studio): RunManager start preflight, execution wrapper, terminal finalize"
```

---

### Task 5: RunManager controls — pause/resume/abort/input/shutdown tests

**Files:**
- Test: `webapp/backend/tests/test_runner_controls.py` (new; runner.py already ships the
  methods — this task proves them and fixes anything they get wrong)

**Interfaces:**
- Consumes: Task 4's `RunManager` + `env` fixture + `runsupport`.
- Produces: verified control semantics for Task 6's HTTP layer.

- [ ] **Step 1: Write the tests**

Create `webapp/backend/tests/test_runner_controls.py`:

```python
"""RunManager controls: pause/resume/abort/input/shutdown. See design §7.1, §7.4."""

import asyncio
import json
from types import SimpleNamespace

import pytest

import runsupport
from lab_devices.experiment import EvaluationError

from experiment_studio.docs_store import ExperimentDoc
from experiment_studio.inputs import NoPendingInputError
from experiment_studio.records import RecordsStore
from experiment_studio.runner import UnknownRunError


async def _start(env: SimpleNamespace, blocks: list, mapping: dict | None = None) -> str:
    doc = ExperimentDoc.model_validate(runsupport.make_doc(blocks))
    created = await env.docs.create(doc)
    return str(
        await env.manager.start(
            created["id"], runsupport.LAB, mapping or runsupport.MAPPING
        )
    )


async def _wait_for(predicate, timeout: float = 5.0) -> None:
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(0.005)


async def _finish(env: SimpleNamespace, timeout: float = 10.0) -> None:
    task = env.manager.current_task()
    assert task is not None
    await asyncio.wait_for(task, timeout)


async def test_pause_resume_updates_status_and_tee(env: SimpleNamespace) -> None:
    env.fake.hold_job("dispense")
    run_id = await _start(env, runsupport.HAPPY_BLOCKS)
    await _wait_for(lambda: env.fake.jobs)  # run parked on the held job
    env.manager.pause(run_id)
    env.manager.pause(run_id)  # second pause is a no-op, not a second status message
    payload = env.manager.active_payload()
    assert payload is not None and payload["status"] == "paused"
    env.manager.resume(run_id)
    payload = env.manager.active_payload()
    assert payload is not None and payload["status"] == "running"
    active = env.manager.active()
    assert active is not None
    statuses = [m["status"] for m in active.tee.messages if m["type"] == "status"]
    assert statuses == ["running", "paused", "running"]
    kinds = [m["kind"] for m in active.tee.messages if m["type"] == "event"]
    assert "paused" in kinds and "resumed" in kinds
    env.fake.complete_job("j-1")
    await _finish(env)


async def test_abort_finalizes_aborted_record_with_artifacts(
    env: SimpleNamespace,
) -> None:
    env.fake.hold_job("dispense")
    run_id = await _start(env, runsupport.HAPPY_BLOCKS)
    await _wait_for(lambda: env.fake.jobs)
    env.manager.abort(run_id)
    env.manager.abort(run_id)  # idempotent while still active
    await _finish(env)
    record = await RecordsStore(env.db, env.data_dir).get(run_id)
    assert record["status"] == "aborted"
    art = env.data_dir / record["dir"]
    events = [json.loads(line) for line in (art / "run_log.jsonl").read_text().splitlines()]
    kinds = [e["kind"] for e in events]
    assert "abort_requested" in kinds
    assert kinds[-1] == "run_finished"
    report = json.loads((art / "report.json").read_text())
    assert report["status"] == "aborted"
    # after terminal, control endpoints 404 (§6)
    with pytest.raises(UnknownRunError):
        env.manager.abort(run_id)


async def test_controls_reject_wrong_run_id(env: SimpleNamespace) -> None:
    env.fake.hold_job("dispense")
    await _start(env, runsupport.HAPPY_BLOCKS)
    with pytest.raises(UnknownRunError):
        env.manager.pause("not-the-run")
    with pytest.raises(UnknownRunError):
        env.manager.submit_input("not-the-run", 1)
    env.fake.complete_job("j-1")
    await _finish(env)


async def test_operator_input_flow(env: SimpleNamespace) -> None:
    run_id = await _start(env, runsupport.INPUT_BLOCKS)
    await _wait_for(
        lambda: (env.manager.active_payload() or {}).get("pending_input") is not None
    )
    payload = env.manager.active_payload()
    assert payload is not None
    pending = payload["pending_input"]
    assert pending == {
        "name": "target",
        "type": "int",
        "prompt": "Target cycles?",
        "min": 1,
        "max": 10,
        "choices": None,
        "block_id": pending["block_id"],
    }
    with pytest.raises(EvaluationError):
        env.manager.submit_input(run_id, 99)  # above max — stays pending
    assert (env.manager.active_payload() or {})["pending_input"] is not None
    env.manager.submit_input(run_id, 7)
    await _finish(env)
    record = await RecordsStore(env.db, env.data_dir).get(run_id)
    assert record["status"] == "completed"
    art = env.data_dir / record["dir"]
    events = [json.loads(line) for line in (art / "run_log.jsonl").read_text().splitlines()]
    bound = next(e for e in events if e["kind"] == "input_bound")
    assert bound["data"] == {"name": "target", "value": 7}


async def test_submit_input_without_pending_raises(env: SimpleNamespace) -> None:
    env.fake.hold_job("dispense")
    run_id = await _start(env, runsupport.HAPPY_BLOCKS)
    with pytest.raises(NoPendingInputError):
        env.manager.submit_input(run_id, 1)
    env.fake.complete_job("j-1")
    await _finish(env)


async def test_abort_cancels_pending_input(env: SimpleNamespace) -> None:
    run_id = await _start(env, runsupport.INPUT_BLOCKS)
    await _wait_for(
        lambda: (env.manager.active_payload() or {}).get("pending_input") is not None
    )
    env.manager.abort(run_id)
    await _finish(env)
    record = await RecordsStore(env.db, env.data_dir).get(run_id)
    assert record["status"] == "aborted"


async def test_shutdown_aborts_and_finalizes(env: SimpleNamespace) -> None:
    env.fake.hold_job("dispense")
    run_id = await _start(env, runsupport.HAPPY_BLOCKS)
    await _wait_for(lambda: env.fake.jobs)
    await env.manager.shutdown()
    task = env.manager.current_task()
    assert task is not None and task.done()
    record = await RecordsStore(env.db, env.data_dir).get(run_id)
    assert record["status"] == "aborted"
    assert env.manager.active_payload() is None
    await env.manager.shutdown()  # idempotent


async def test_new_run_allowed_after_terminal(env: SimpleNamespace) -> None:
    run_id_1 = await _start(env, runsupport.HAPPY_BLOCKS)
    await _finish(env)
    doc = ExperimentDoc.model_validate(
        runsupport.make_doc(runsupport.HAPPY_BLOCKS, name="Second")
    )
    created = await env.docs.create(doc)
    run_id_2 = await env.manager.start(
        created["id"], runsupport.LAB, runsupport.MAPPING
    )
    assert run_id_2 != run_id_1
    await _finish(env)
```

Note on `input_bound` data shape: if the assertion `bound["data"] == {"name": "target",
"value": 7}` fails because the engine emits only `{"name": ...}` or a different value
key, relax it to `bound["data"]["name"] == "target"` — the engine's emission is the
contract, do not patch the engine.

- [ ] **Step 2: Run the tests**

Run: `.venv/bin/python -m pytest tests/test_runner_controls.py -q`
Expected: PASS if Task 4's implementation is correct; any failure here is a runner bug —
fix `runner.py`/`inputs.py`, never weaken semantics (pause no-op double-status, abort
idempotence, 404-after-terminal are spec requirements).

- [ ] **Step 3: Full gates**

Run: `.venv/bin/python -m pytest -q && .venv/bin/python -m mypy && .venv/bin/python -m ruff check .`
Expected: all PASS.

- [ ] **Step 4: Commit**

```bash
git add webapp/backend/tests/test_runner_controls.py webapp/backend/experiment_studio/
git commit -m "test(studio): run controls — pause/resume/abort/input/shutdown lifecycle"
```

---

### Task 6: HTTP surface — /api/runs, /api/records, error handlers, lifespan rework, discover guard

**Files:**
- Create: `webapp/backend/experiment_studio/api/deps.py`
- Create: `webapp/backend/experiment_studio/api/runs.py`
- Create: `webapp/backend/experiment_studio/api/records.py`
- Modify: `webapp/backend/experiment_studio/app.py`
- Modify: `webapp/backend/experiment_studio/api/labs.py` (discover guard only)
- Modify: `webapp/backend/tests/conftest.py` (add `api` fixture)
- Test: `webapp/backend/tests/test_runs_api.py`, `webapp/backend/tests/test_records_api.py`, `webapp/backend/tests/test_lifespan.py`

**Interfaces:**
- Consumes: Tasks 1–5.
- Produces:
  - `api/deps.py`: `async get_db(conn: HTTPConnection) -> Database`,
    `async get_records_store(conn, db=Depends(get_db)) -> RecordsStore`,
    `async get_run_manager(conn, db=Depends(get_db)) -> RunManager` — all lazy-singleton
    on `app.state` (lifespan pre-populates in prod; tests override). They take
    `HTTPConnection` (not `Request`) so Task 7's WebSocket route can reuse them.
  - Routers registered in `app.py`: `runs_router` at `/api/runs`, `records_router` at
    `/api/records` (Task 7 adds `ws_router` at `/api`).
  - Error responses (all keep the `{detail, code}` envelope):
    - `RunActiveError` → 409 `run_active` + `active_run_id`
    - `PreflightError` → 422 `preflight_failed` + `diagnostics`
    - `StartValidationError` → 422 `validation_failed` + `diagnostics` + `record_id`
    - `UnknownRunError` → 404 `unknown_run`; `UnknownRecordError` → 404 `unknown_record`
    - `NoPendingInputError` → 409 `no_pending_input`; engine `EvaluationError` → 422 `invalid_value`
  - Lifespan (all W1/W2 carry-forwards land here): eager `Database.connect` + crash
    sweep + one shared `LabRegistry` feeding both `LabsService` and `RunManager`;
    shutdown runs `manager.shutdown()` → `labs.aclose()` → `db.close()`, each guarded.

- [ ] **Step 1: Write the failing tests**

Add to `webapp/backend/tests/conftest.py` (below the `env` fixture; new imports:
`from httpx_ws.transport import ASGIWebSocketTransport`):

```python
@pytest.fixture
async def api(app: FastAPI, tmp_path: Path) -> AsyncIterator[SimpleNamespace]:
    """HTTP+WS harness: real app with an overridden RunManager over a FakeLab."""
    from experiment_studio.api.deps import get_run_manager

    fake = runsupport.default_fake()
    db = await Database.connect(tmp_path / "studio.db")
    app.state.db = db
    registry = runsupport.fake_registry()
    manager = RunManager(
        db,
        tmp_path,
        registry,
        client_factory=runsupport.fake_client_factory(fake),
        run_options=dict(runsupport.FAST_RUN_OPTIONS),
    )
    app.dependency_overrides[get_run_manager] = lambda: manager
    transport = ASGIWebSocketTransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://studio") as client:
        yield SimpleNamespace(
            client=client, fake=fake, manager=manager, db=db, data_dir=tmp_path
        )
    await manager.shutdown()
    await registry.aclose()
    await db.close()
```

Create `webapp/backend/tests/test_runs_api.py`:

```python
"""HTTP layer for runs: envelopes, status codes, controls, input. See design §6."""

import asyncio
import json
from types import SimpleNamespace
from typing import Any

import pytest

import runsupport


async def _create_experiment(api: SimpleNamespace, blocks: list, **kw: Any) -> str:
    response = await api.client.post("/api/experiments", json=runsupport.make_doc(blocks, **kw))
    assert response.status_code == 201
    return str(response.json()["id"])


async def _start(api: SimpleNamespace, blocks: list, **kw: Any) -> str:
    experiment_id = await _create_experiment(api, blocks, **kw)
    response = await api.client.post(
        "/api/runs",
        json={
            "experiment_id": experiment_id,
            "lab": runsupport.LAB,
            "role_mapping": runsupport.MAPPING,
        },
    )
    assert response.status_code == 201, response.text
    return str(response.json()["run_id"])


async def _finish(api: SimpleNamespace, timeout: float = 10.0) -> None:
    task = api.manager.current_task()
    assert task is not None
    await asyncio.wait_for(task, timeout)


async def _wait_pending_input(api: SimpleNamespace) -> dict[str, Any]:
    async with asyncio.timeout(5):
        while True:
            response = await api.client.get("/api/runs/active")
            body = response.json()
            if body and body.get("pending_input"):
                return dict(body)
            await asyncio.sleep(0.005)


async def test_start_returns_run_id_and_active_payload(api: SimpleNamespace) -> None:
    api.fake.hold_job("dispense")
    run_id = await _start(api, runsupport.HAPPY_BLOCKS)
    response = await api.client.get("/api/runs/active")
    body = response.json()
    assert body["run_id"] == run_id
    assert body["status"] == "running"
    assert body["experiment"]["name"] == "Growth run"
    assert body["seq"] >= 0
    assert body["pending_input"] is None
    api.fake.complete_job("j-1")
    await _finish(api)
    response = await api.client.get("/api/runs/active")
    assert response.json() is None


async def test_second_run_409_with_active_run_id(api: SimpleNamespace) -> None:
    api.fake.hold_job("dispense")
    run_id = await _start(api, runsupport.HAPPY_BLOCKS)
    experiment_id = await _create_experiment(api, runsupport.HAPPY_BLOCKS, name="Other")
    response = await api.client.post(
        "/api/runs",
        json={
            "experiment_id": experiment_id,
            "lab": runsupport.LAB,
            "role_mapping": runsupport.MAPPING,
        },
    )
    assert response.status_code == 409
    body = response.json()
    assert body["code"] == "run_active"
    assert body["active_run_id"] == run_id
    assert "detail" in body
    api.fake.complete_job("j-1")
    await _finish(api)


async def test_preflight_422_with_diagnostics(api: SimpleNamespace) -> None:
    experiment_id = await _create_experiment(api, runsupport.HAPPY_BLOCKS)
    response = await api.client.post(
        "/api/runs",
        json={
            "experiment_id": experiment_id,
            "lab": runsupport.LAB,
            "role_mapping": {"feed": "pump_1"},
        },
    )
    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "preflight_failed"
    assert body["diagnostics"][0]["category"] == "mapping"


async def test_validation_422_with_record_id(api: SimpleNamespace) -> None:
    experiment_id = await _create_experiment(api, runsupport.INVALID_BLOCKS)
    response = await api.client.post(
        "/api/runs",
        json={
            "experiment_id": experiment_id,
            "lab": runsupport.LAB,
            "role_mapping": runsupport.MAPPING,
        },
    )
    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "validation_failed"
    assert body["diagnostics"]
    record = await api.client.get(f"/api/records/{body['record_id']}")
    assert record.status_code == 200
    assert record.json()["status"] == "failed"


async def test_unknown_experiment_and_lab_404(api: SimpleNamespace) -> None:
    response = await api.client.post(
        "/api/runs",
        json={"experiment_id": "nope", "lab": runsupport.LAB, "role_mapping": {}},
    )
    assert response.status_code == 404
    assert response.json()["code"] == "unknown_experiment"
    experiment_id = await _create_experiment(api, runsupport.HAPPY_BLOCKS)
    response = await api.client.post(
        "/api/runs",
        json={
            "experiment_id": experiment_id,
            "lab": "ghost-lab",
            "role_mapping": runsupport.MAPPING,
        },
    )
    assert response.status_code == 404
    assert response.json()["code"] == "unknown_lab"


async def test_pause_resume_abort_endpoints(api: SimpleNamespace) -> None:
    api.fake.hold_job("dispense")
    run_id = await _start(api, runsupport.HAPPY_BLOCKS)
    assert (await api.client.post(f"/api/runs/{run_id}/pause")).status_code == 204
    body = (await api.client.get("/api/runs/active")).json()
    assert body["status"] == "paused"
    assert (await api.client.post(f"/api/runs/{run_id}/resume")).status_code == 204
    assert (await api.client.post(f"/api/runs/{run_id}/abort")).status_code == 204
    assert (await api.client.post(f"/api/runs/{run_id}/abort")).status_code == 204
    await _finish(api)
    # 404 for a non-active run id (§6)
    assert (await api.client.post(f"/api/runs/{run_id}/pause")).status_code == 404
    assert (await api.client.post(f"/api/runs/{run_id}/pause")).json()["code"] == "unknown_run"


async def test_input_endpoint_flow(api: SimpleNamespace) -> None:
    run_id = await _start(api, runsupport.INPUT_BLOCKS)
    body = await _wait_pending_input(api)
    assert body["pending_input"]["name"] == "target"
    response = await api.client.post(f"/api/runs/{run_id}/input", json={"value": 99})
    assert response.status_code == 422
    assert response.json()["code"] == "invalid_value"
    response = await api.client.post(f"/api/runs/{run_id}/input", json={"value": 7})
    assert response.status_code == 204
    await _finish(api)
    response = await api.client.post(f"/api/runs/{run_id}/input", json={"value": 7})
    assert response.status_code == 404  # run no longer active


async def test_input_409_when_none_pending(api: SimpleNamespace) -> None:
    api.fake.hold_job("dispense")
    run_id = await _start(api, runsupport.HAPPY_BLOCKS)
    response = await api.client.post(f"/api/runs/{run_id}/input", json={"value": 1})
    assert response.status_code == 409
    assert response.json()["code"] == "no_pending_input"
    api.fake.complete_job("j-1")
    await _finish(api)


async def test_discover_409_while_run_active_on_that_lab(api: SimpleNamespace) -> None:
    """§6: POST /api/labs/{lab}/discover refuses while a run is active on that lab."""
    api.fake.hold_job("dispense")
    await _start(api, runsupport.HAPPY_BLOCKS)
    response = await api.client.post(f"/api/labs/{runsupport.LAB}/discover")
    assert response.status_code == 409
    assert response.json()["code"] == "run_active"
    api.fake.complete_job("j-1")
    await _finish(api)


async def test_run_artifacts_via_records_endpoints(api: SimpleNamespace) -> None:
    run_id = await _start(api, runsupport.HAPPY_BLOCKS)
    await _finish(api)
    events = (await api.client.get(f"/api/records/{run_id}/events")).json()
    assert [e["kind"] for e in events][0] == "run_started"
    streams = (await api.client.get(f"/api/records/{run_id}/streams")).json()
    assert streams["od"]["units"] == "AU"
    assert len(streams["od"]["t"]) == len(streams["od"]["v"]) == 1
    record = (await api.client.get(f"/api/records/{run_id}")).json()
    assert record["status"] == "completed"
    assert record["report"]["status"] == "completed"
    assert record["doc"]["doc_version"] == 1
```

Create `webapp/backend/tests/test_records_api.py`:

```python
"""HTTP layer for records: list/get/rename/delete/download + guards. See design §6."""

import io
import json
import zipfile
from types import SimpleNamespace
from uuid import uuid4

import runsupport
from experiment_studio.records import RecordsStore


async def _seed_record(api: SimpleNamespace, *, status: str = "completed") -> dict:
    record_id = str(uuid4())
    art = api.data_dir / f"runs/{record_id}"
    art.mkdir(parents=True)
    (art / "run_log.jsonl").write_text(
        '{"timestamp": 1.0, "kind": "run_started", "block_id": null, "data": {}}\n'
    )
    (art / "workflow.json").write_text(json.dumps({"streams": {"od": {"units": "AU"}}}))
    (art / "od.csv").write_text("timestamp,value\n1.5,0.5\n")
    (art / "report.json").write_text(json.dumps({"status": status}))
    (art / "doc.json").write_text(json.dumps({"doc_version": 1, "name": "Exp"}))
    store = RecordsStore(api.db, api.data_dir)
    await store.create(
        record_id=record_id,
        name="Exp — 2026-07-12 10:00",
        experiment_id="e1",
        experiment_name="Exp",
        lab=runsupport.LAB,
        role_mapping={"feed": "pump_1"},
        started_at="2026-07-12T10:00:00+00:00",
        dir=f"runs/{record_id}",
    )
    await store.finalize(record_id, status=status, ended_at="2026-07-12T10:05:00+00:00")
    return await store.get(record_id)


async def test_list_and_get(api: SimpleNamespace) -> None:
    record = await _seed_record(api)
    listed = (await api.client.get("/api/records")).json()
    assert [r["id"] for r in listed] == [record["id"]]
    got = (await api.client.get(f"/api/records/{record['id']}")).json()
    assert got["report"] == {"status": "completed"}
    assert got["doc"]["name"] == "Exp"


async def test_get_unknown_404(api: SimpleNamespace) -> None:
    response = await api.client.get("/api/records/nope")
    assert response.status_code == 404
    assert response.json()["code"] == "unknown_record"


async def test_rename(api: SimpleNamespace) -> None:
    record = await _seed_record(api)
    response = await api.client.patch(
        f"/api/records/{record['id']}", json={"name": "First run"}
    )
    assert response.status_code == 200
    assert response.json()["name"] == "First run"
    response = await api.client.patch(f"/api/records/{record['id']}", json={"name": ""})
    assert response.status_code == 422  # pydantic min_length


async def test_delete_removes_row_and_dir(api: SimpleNamespace) -> None:
    record = await _seed_record(api)
    response = await api.client.delete(f"/api/records/{record['id']}")
    assert response.status_code == 204
    assert not (api.data_dir / record["dir"]).exists()
    assert (await api.client.delete(f"/api/records/{record['id']}")).status_code == 404


async def test_delete_active_record_409(api: SimpleNamespace) -> None:
    api.fake.hold_job("dispense")
    response = await api.client.post(
        "/api/experiments", json=runsupport.make_doc(runsupport.HAPPY_BLOCKS)
    )
    experiment_id = response.json()["id"]
    response = await api.client.post(
        "/api/runs",
        json={
            "experiment_id": experiment_id,
            "lab": runsupport.LAB,
            "role_mapping": runsupport.MAPPING,
        },
    )
    run_id = response.json()["run_id"]
    response = await api.client.delete(f"/api/records/{run_id}")
    assert response.status_code == 409
    assert response.json()["code"] == "run_active"
    api.fake.complete_job("j-1")
    task = api.manager.current_task()
    assert task is not None
    await task


async def test_download_zip(api: SimpleNamespace) -> None:
    record = await _seed_record(api)
    response = await api.client.get(f"/api/records/{record['id']}/download")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    assert 'filename="Exp_2026-07-12_10_00.zip"' in response.headers["content-disposition"]
    with zipfile.ZipFile(io.BytesIO(response.content)) as zf:
        assert set(zf.namelist()) == {
            "run_log.jsonl",
            "workflow.json",
            "od.csv",
            "report.json",
            "doc.json",
        }


async def test_events_and_streams_empty_for_interrupted(api: SimpleNamespace) -> None:
    record = await _seed_record(api, status="interrupted")
    (api.data_dir / record["dir"] / "run_log.jsonl").unlink()
    events = (await api.client.get(f"/api/records/{record['id']}/events")).json()
    assert events == []
```

Note: the download filename assertion pins the sanitizer (`[^A-Za-z0-9._-]+` runs → `_`):
`"Exp — 2026-07-12 10:00"` → `"Exp_2026-07-12_10_00"`. If your sanitizer differs, fix the
sanitizer, not the test.

Create `webapp/backend/tests/test_lifespan.py`:

```python
"""Lifespan wiring: eager services, crash sweep, guarded shutdown. See design §7.6."""

from pathlib import Path

from experiment_studio.app import create_app
from experiment_studio.config import Settings
from experiment_studio.db import Database
from experiment_studio.labs import LabsService
from experiment_studio.records import RecordsStore
from experiment_studio.runner import RunManager


async def test_lifespan_constructs_services_and_sweeps(tmp_path: Path) -> None:
    db = await Database.connect(tmp_path / "studio.db")
    await RecordsStore(db, tmp_path).create(
        record_id="phantom",
        name="crashed",
        experiment_id=None,
        experiment_name="Exp",
        lab="lab_a",
        role_mapping={},
        started_at="2026-07-12T10:00:00+00:00",
        dir="runs/phantom",
    )
    await db.close()

    app = create_app(Settings(static_dir=None, data_dir=tmp_path))
    async with app.router.lifespan_context(app):
        assert isinstance(app.state.labs, LabsService)
        assert isinstance(app.state.run_manager, RunManager)
        record = await RecordsStore(app.state.db, tmp_path).get("phantom")
        assert record["status"] == "interrupted"
        assert record["ended_at"] is not None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_runs_api.py tests/test_records_api.py tests/test_lifespan.py -q`
Expected: FAIL (`ModuleNotFoundError: experiment_studio.api.deps`, missing routes → 404,
lifespan missing `labs`/`run_manager`).

- [ ] **Step 3: Implement**

Add `httpx-ws` to `webapp/backend/pyproject.toml` dev extras (needed by the conftest
`api` fixture; Task 7 uses its WS side):

```toml
dev = [
    "pytest>=8",
    "pytest-asyncio>=0.23",
    "mypy>=1.8",
    "ruff>=0.4",
    "httpx>=0.27",
    "httpx-ws>=0.7",
]
```

Then refresh the venv: `.venv/bin/pip install -e ".[dev]" -q`.

Create `webapp/backend/experiment_studio/api/deps.py`:

```python
"""Request-scoped dependencies shared by run, record, and WebSocket routes.

These take HTTPConnection (not Request) so WebSocket endpoints can reuse them. Lazy
construction is the test-only path; production pre-populates app.state in lifespan.
"""

from __future__ import annotations

from fastapi import Depends
from starlette.requests import HTTPConnection

from lab_devices.discovery import LabRegistry

from experiment_studio.db import Database
from experiment_studio.records import RecordsStore
from experiment_studio.runner import RunManager


async def get_db(conn: HTTPConnection) -> Database:
    db = getattr(conn.app.state, "db", None)
    if db is None:
        settings = conn.app.state.settings
        db = await Database.connect(settings.data_dir / "studio.db")
        conn.app.state.db = db
    return db


async def get_records_store(
    conn: HTTPConnection, db: Database = Depends(get_db)
) -> RecordsStore:
    return RecordsStore(db, conn.app.state.settings.data_dir)


async def get_run_manager(
    conn: HTTPConnection, db: Database = Depends(get_db)
) -> RunManager:
    manager = getattr(conn.app.state, "run_manager", None)
    if manager is None:
        manager = RunManager(db, conn.app.state.settings.data_dir, LabRegistry())
        conn.app.state.run_manager = manager
    return manager
```

Create `webapp/backend/experiment_studio/api/runs.py`:

```python
"""Run lifecycle endpoints. See webapp design §6, §7."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from experiment_studio.api.deps import get_run_manager
from experiment_studio.runner import RunManager

router = APIRouter()


class StartRunRequest(BaseModel):
    experiment_id: str
    lab: str
    role_mapping: dict[str, str]


class SubmitInputRequest(BaseModel):
    value: bool | int | float | str


@router.post("", status_code=201)
async def start_run(
    body: StartRunRequest, manager: RunManager = Depends(get_run_manager)
) -> dict[str, Any]:
    run_id = await manager.start(body.experiment_id, body.lab, body.role_mapping)
    return {"run_id": run_id}


@router.get("/active")
async def active_run(
    manager: RunManager = Depends(get_run_manager),
) -> dict[str, Any] | None:
    return manager.active_payload()


@router.post("/{run_id}/pause", status_code=204)
async def pause_run(run_id: str, manager: RunManager = Depends(get_run_manager)) -> None:
    manager.pause(run_id)


@router.post("/{run_id}/resume", status_code=204)
async def resume_run(run_id: str, manager: RunManager = Depends(get_run_manager)) -> None:
    manager.resume(run_id)


@router.post("/{run_id}/abort", status_code=204)
async def abort_run(run_id: str, manager: RunManager = Depends(get_run_manager)) -> None:
    manager.abort(run_id)


@router.post("/{run_id}/input", status_code=204)
async def submit_input(
    run_id: str,
    body: SubmitInputRequest,
    manager: RunManager = Depends(get_run_manager),
) -> None:
    manager.submit_input(run_id, body.value)
```

Create `webapp/backend/experiment_studio/api/records.py`:

```python
"""Run-record endpoints: list, viewer payload, rename, delete, download. See §6, §9.5."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, Field

from experiment_studio.api.deps import get_records_store, get_run_manager
from experiment_studio.records import RecordsStore, build_zip, read_events, read_streams
from experiment_studio.runner import RunActiveError, RunManager

router = APIRouter()


class RenameRequest(BaseModel):
    name: str = Field(min_length=1)


def _read_json(path: Path) -> Any | None:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


@router.get("")
async def list_records(
    store: RecordsStore = Depends(get_records_store),
) -> list[dict[str, Any]]:
    return await store.list()


@router.get("/{record_id}")
async def get_record(
    record_id: str, store: RecordsStore = Depends(get_records_store)
) -> dict[str, Any]:
    """Row + report + source doc for the record viewer (§9.5; §6 amended during W4)."""
    record = await store.get(record_id)
    artifact_dir = store.artifact_dir(record)
    record["report"] = _read_json(artifact_dir / "report.json")
    record["doc"] = _read_json(artifact_dir / "doc.json")
    return record


@router.patch("/{record_id}")
async def rename_record(
    record_id: str,
    body: RenameRequest,
    store: RecordsStore = Depends(get_records_store),
) -> dict[str, Any]:
    return await store.rename(record_id, body.name)


@router.delete("/{record_id}", status_code=204)
async def delete_record(
    record_id: str,
    store: RecordsStore = Depends(get_records_store),
    manager: RunManager = Depends(get_run_manager),
) -> None:
    active = manager.active()
    if active is not None and active.record_id == record_id:
        raise RunActiveError(active.run_id)
    await store.delete(record_id)


@router.get("/{record_id}/download")
async def download_record(
    record_id: str, store: RecordsStore = Depends(get_records_store)
) -> Response:
    record = await store.get(record_id)
    payload = build_zip(store.artifact_dir(record))
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", record["name"]).strip("._") or record["id"]
    return Response(
        content=payload,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{stem}.zip"'},
    )


@router.get("/{record_id}/events")
async def record_events(
    record_id: str, store: RecordsStore = Depends(get_records_store)
) -> list[dict[str, Any]]:
    record = await store.get(record_id)
    return read_events(store.artifact_dir(record))


@router.get("/{record_id}/streams")
async def record_streams(
    record_id: str, store: RecordsStore = Depends(get_records_store)
) -> dict[str, Any]:
    record = await store.get(record_id)
    return read_streams(store.artifact_dir(record))
```

Modify `webapp/backend/experiment_studio/app.py`:

1. Add imports:

```python
import contextlib
import logging

from lab_devices.discovery import LabRegistry
from lab_devices.experiment import EvaluationError

from experiment_studio.api.records import router as records_router
from experiment_studio.api.runs import router as runs_router
from experiment_studio.inputs import NoPendingInputError
from experiment_studio.labs import LabsService
from experiment_studio.records import RecordsStore, UnknownRecordError
from experiment_studio.runner import (
    PreflightError,
    RunActiveError,
    RunManager,
    StartValidationError,
    UnknownRunError,
)

_LOG = logging.getLogger(__name__)
```

2. Extend `_ERROR_MAP` (order among unrelated exception types does not matter; keep the
   `LabError` catch-all last):

```python
    (UnknownRecordError, 404, "unknown_record"),
    (UnknownRunError, 404, "unknown_run"),
    (NoPendingInputError, 409, "no_pending_input"),
    (EvaluationError, 422, "invalid_value"),
```

3. Add payload-carrying handlers after `_error_handler`:

```python
async def _run_active_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RunActiveError)
    return JSONResponse(
        status_code=409,
        content={
            "detail": str(exc),
            "code": "run_active",
            "active_run_id": exc.active_run_id,
        },
    )


async def _preflight_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, PreflightError)
    return JSONResponse(
        status_code=422,
        content={
            "detail": str(exc),
            "code": "preflight_failed",
            "diagnostics": exc.diagnostics,
        },
    )


async def _start_validation_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, StartValidationError)
    return JSONResponse(
        status_code=422,
        content={
            "detail": str(exc),
            "code": "validation_failed",
            "diagnostics": exc.diagnostics,
            "record_id": exc.record_id,
        },
    )
```

4. Replace `_lifespan` (W1/W2 carry-forwards: eager services, guarded shutdown):

```python
@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = app.state.settings
    db = await Database.connect(settings.data_dir / "studio.db")
    app.state.db = db
    swept = await RecordsStore(db, settings.data_dir).sweep_interrupted()  # §7.6
    if swept:
        _LOG.warning("crash sweep: marked %d running record(s) interrupted", swept)
    registry = LabRegistry()
    app.state.labs = LabsService(registry)
    app.state.run_manager = RunManager(db, settings.data_dir, registry)
    try:
        yield
    finally:
        # guard each teardown so one failure cannot leak the others (W2 carry-forward)
        manager = getattr(app.state, "run_manager", None)
        if manager is not None:
            with contextlib.suppress(Exception):
                await manager.shutdown()
        labs = getattr(app.state, "labs", None)
        if labs is not None:
            with contextlib.suppress(Exception):
                await labs.aclose()  # also closes the shared registry
        current_db = getattr(app.state, "db", None)
        if current_db is not None:
            with contextlib.suppress(Exception):
                await current_db.close()
```

5. In `create_app`, register the new handlers and routers:

```python
    app.add_exception_handler(RunActiveError, _run_active_handler)
    app.add_exception_handler(PreflightError, _preflight_handler)
    app.add_exception_handler(StartValidationError, _start_validation_handler)
```

```python
    app.include_router(runs_router, prefix="/api/runs")
    app.include_router(records_router, prefix="/api/records")
```

Modify `webapp/backend/experiment_studio/api/labs.py` — add the discover guard:

```python
from experiment_studio.api.deps import get_run_manager
from experiment_studio.runner import RunActiveError, RunManager
```

```python
@router.post("/{lab}/discover")
async def lab_discover(
    lab: str,
    service: LabsService = Depends(get_labs_service),
    manager: RunManager = Depends(get_run_manager),
) -> list[dict[str, Any]]:
    active = manager.active()
    if active is not None and active.lab == lab:
        raise RunActiveError(active.run_id)  # §6: 409 while a run is active on that lab
    return await service.discover(lab)
```

- [ ] **Step 4: Run tests + gates**

Run: `.venv/bin/python -m pytest -q && .venv/bin/python -m mypy && .venv/bin/python -m ruff check .`
Expected: all PASS, including the pre-existing labs/experiments/validate/spa suites
(the lifespan and labs.py changes must not break them).

- [ ] **Step 5: Commit**

```bash
git add webapp/backend/experiment_studio/api/ webapp/backend/experiment_studio/app.py webapp/backend/pyproject.toml webapp/backend/tests/
git commit -m "feat(studio): runs + records HTTP API, payload error handlers, hardened lifespan"
```

---

### Task 7: WebSocket endpoint with replay

**Files:**
- Create: `webapp/backend/experiment_studio/api/ws.py`
- Modify: `webapp/backend/experiment_studio/app.py` (one router include)
- Test: `webapp/backend/tests/test_ws_api.py`

**Interfaces:**
- Consumes: `RunManager.stream(run_id, since)`, the `api` conftest fixture (its
  `ASGIWebSocketTransport` already speaks WS).
- Produces: `WS /api/runs/{run_id}/events?since=N` — replays buffered messages with
  `seq > N`, then live-streams; closes 1000 after the terminal status; closes 4404 for
  an unknown run id. Message shapes (§7.5):
  `{type: "event", seq, timestamp, kind, block_id, data}` and
  `{type: "status", seq, status}`.

- [ ] **Step 1: Write the failing tests**

Create `webapp/backend/tests/test_ws_api.py`:

```python
"""WebSocket contract: live stream, replay, terminal close, 4404. See design §7.5."""

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest
from httpx_ws import WebSocketDisconnect, aconnect_ws

import runsupport


async def _create_and_start(api: SimpleNamespace, blocks: list) -> str:
    response = await api.client.post("/api/experiments", json=runsupport.make_doc(blocks))
    experiment_id = response.json()["id"]
    response = await api.client.post(
        "/api/runs",
        json={
            "experiment_id": experiment_id,
            "lab": runsupport.LAB,
            "role_mapping": runsupport.MAPPING,
        },
    )
    assert response.status_code == 201, response.text
    return str(response.json()["run_id"])


async def _collect_until_terminal(ws: Any) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    while True:
        message = await asyncio.wait_for(ws.receive_json(), timeout=5)
        messages.append(message)
        if message["type"] == "status" and message["status"] in runsupport.TERMINAL:
            return messages


async def test_ws_streams_run_to_terminal_status(api: SimpleNamespace) -> None:
    run_id = await _create_and_start(api, runsupport.HAPPY_BLOCKS)
    async with aconnect_ws(
        f"http://studio/api/runs/{run_id}/events",
        api.client,
        keepalive_ping_interval_seconds=None,
    ) as ws:
        messages = await _collect_until_terminal(ws)
    assert [m["seq"] for m in messages] == list(range(len(messages)))
    assert messages[0] == {"type": "status", "seq": 0, "status": "running"}
    events = [m for m in messages if m["type"] == "event"]
    kinds = [e["kind"] for e in events]
    assert kinds[0] == "run_started"
    assert "measure_recorded" in kinds
    assert kinds[-1] == "run_finished"
    assert messages[-1]["status"] == "completed"
    measure = next(e for e in events if e["kind"] == "measure_recorded")
    assert set(measure) == {"type", "seq", "timestamp", "kind", "block_id", "data"}
    assert measure["data"]["stream"] == "od"


async def test_ws_replays_from_since(api: SimpleNamespace) -> None:
    run_id = await _create_and_start(api, runsupport.HAPPY_BLOCKS)
    task = api.manager.current_task()
    assert task is not None
    await asyncio.wait_for(task, 10)
    async with aconnect_ws(
        f"http://studio/api/runs/{run_id}/events",
        api.client,
        keepalive_ping_interval_seconds=None,
    ) as ws:
        full = await _collect_until_terminal(ws)
    since = full[2]["seq"]
    async with aconnect_ws(
        f"http://studio/api/runs/{run_id}/events?since={since}",
        api.client,
        keepalive_ping_interval_seconds=None,
    ) as ws:
        tail = await _collect_until_terminal(ws)
    assert tail == full[3:]


async def test_ws_unknown_run_closes_4404(api: SimpleNamespace) -> None:
    with pytest.raises(WebSocketDisconnect) as info:
        async with aconnect_ws(
            "http://studio/api/runs/ghost/events",
            api.client,
            keepalive_ping_interval_seconds=None,
        ) as ws:
            await asyncio.wait_for(ws.receive_json(), timeout=5)
    assert info.value.code == 4404


async def test_ws_sees_input_lifecycle(api: SimpleNamespace) -> None:
    run_id = await _create_and_start(api, runsupport.INPUT_BLOCKS)
    async with aconnect_ws(
        f"http://studio/api/runs/{run_id}/events",
        api.client,
        keepalive_ping_interval_seconds=None,
    ) as ws:
        # drain until the engine asks for input
        while True:
            message = await asyncio.wait_for(ws.receive_json(), timeout=5)
            if message["type"] == "event" and message["kind"] == "input_requested":
                break
        response = await api.client.post(f"/api/runs/{run_id}/input", json={"value": 3})
        assert response.status_code == 204
        messages = await _collect_until_terminal(ws)
    kinds = [m.get("kind") for m in messages if m["type"] == "event"]
    assert "input_bound" in kinds
    assert messages[-1]["status"] == "completed"
```

Note: `pytest.raises(WebSocketDisconnect)` — if httpx-ws surfaces the server close as a
normal iterator stop instead of an exception on `receive_json`, assert via
`httpx_ws.WebSocketDisconnect` on the context exit; adapt to the library's actual
behavior but keep asserting code 4404.

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_ws_api.py -q`
Expected: FAIL — connecting to a non-existent WS route (403/404 from the ASGI app).

- [ ] **Step 3: Implement**

Create `webapp/backend/experiment_studio/api/ws.py`:

```python
"""Run event WebSocket with replay-on-reconnect. See design §7.5."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect

from experiment_studio.api.deps import get_run_manager
from experiment_studio.runner import RunManager, UnknownRunError

router = APIRouter()


@router.websocket("/runs/{run_id}/events")
async def run_events(
    websocket: WebSocket,
    run_id: str,
    since: int = Query(default=-1),
    manager: RunManager = Depends(get_run_manager),
) -> None:
    await websocket.accept()
    try:
        stream = manager.stream(run_id, since)
    except UnknownRunError:
        await websocket.close(code=4404)
        return
    try:
        async for message in stream:
            await websocket.send_json(message)
        await websocket.close(code=1000)
    except (WebSocketDisconnect, RuntimeError):
        # client went away mid-send; a reconnect resumes via ?since=<last seq>
        pass
```

In `app.py`, add `from experiment_studio.api.ws import router as ws_router` and, next to
the other includes: `app.include_router(ws_router, prefix="/api")`.

- [ ] **Step 4: Run tests + gates**

Run: `.venv/bin/python -m pytest tests/test_ws_api.py -q && .venv/bin/python -m pytest -q && .venv/bin/python -m mypy && .venv/bin/python -m ruff check .`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add webapp/backend/experiment_studio/api/ws.py webapp/backend/experiment_studio/app.py webapp/backend/tests/test_ws_api.py
git commit -m "feat(studio): run-events WebSocket with seq replay and terminal close"
```

---

### Task 8: Spec sync, CI check, ledger

**Files:**
- Modify: `docs/superpowers/specs/2026-07-11-experiment-studio-webapp-design.md`
  (two amendment notes)
- Verify: `.github/workflows/` (no change expected — backend job must pick up the new
  dev dep via its existing `pip install -e ".[dev]"` step; if it pins deps differently,
  align it)

**Interfaces:** none (documentation + verification).

- [ ] **Step 1: Amend the spec**

In §6, add one row to the endpoint table after the `GET /api/records` row:

```markdown
| `GET /api/records/{id}` | record row + parsed `report.json` + source `doc.json` for the viewer (amended 2026-07-12 during W4: §9.5's viewer needs the report summary and workflow snapshot; the original table had no single-record read) |
```

In §7.5, append to the first bullet:

```markdown
  Status messages carry a `seq` from the same counter as events (amended 2026-07-12
  during W4) so replay is a single ordered buffer.
```

- [ ] **Step 2: Verify CI covers the new tests**

Run: `grep -n "pip install" .github/workflows/*.yml`
Expected: the webapp-backend job installs `.[dev]` from `webapp/backend` (httpx-ws
arrives automatically). If it enumerates packages instead, add `httpx-ws`.

- [ ] **Step 3: Full gates one last time**

Run (from `webapp/backend/`): `.venv/bin/python -m pytest -q && .venv/bin/python -m mypy && .venv/bin/python -m ruff check .`
Also confirm the frontend is untouched: `git status --short webapp/frontend/` → empty.

- [ ] **Step 4: Commit**

```bash
git add docs/superpowers/specs/2026-07-11-experiment-studio-webapp-design.md
git commit -m "docs(studio): W4 spec amendments — record viewer endpoint, status seq"
```

---

## Deferred out of W4 (do not implement)

- **W3 frontend touch-ups** (client.ts request tests, tsconfig split, tree.ts
  replaceSlot export, Escape-cancel, serverId clear on delete, stale-diagnostics
  dimming, save-as undo depth) — moved to W5 where the frontend is open anyway.
- Mapping-memory **read** endpoint (preflight pre-fill) — W5/W6 with a spec amendment;
  W4 only writes the `mappings` table.
- `list_labs` N+1 roster lookups — library-side backlog.

## Execution notes

- Tests average well under a second each; anything slower than ~2 s means the FakeLab
  poll options did not reach `RunOptions` — fix the wiring, never lengthen timeouts.
- `tests/runsupport.py` bootstraps `sys.path` for the repo-root `tests/fakelab.py`;
  keep that bootstrap at the top of that file only (single `# noqa: E402` site).
- mypy is strict for `experiment_studio/` and does not check `tests/`.


