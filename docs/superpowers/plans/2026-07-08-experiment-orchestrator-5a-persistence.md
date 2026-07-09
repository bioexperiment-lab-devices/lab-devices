# Experiment Orchestrator — Increment 5a: Disk Persistence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist measurement streams and the run log to disk (jsonl + csv) honoring the workflow's declarative persistence config, replacing Increment-4's D4 rejection — while keeping in-memory state authoritative and never letting disk I/O compromise the finalizer, the report, or dispatch.

**Architecture:** A two-tier data model (design spec §3): in-memory (`RunState` + `InMemoryRunLog`) stays authoritative and synchronous; on-disk files are a *lagging mirror* written synchronously into buffered file objects (no event-loop stall, no fsync) and flushed by a periodic clock-driven task, with a guaranteed final flush + close at finalize. `ExperimentRun` builds the sinks from `workflow.persistence` (default + per-stream override) under a caller-supplied `RunOptions.output_dir`, before any hardware is touched.

**Tech Stack:** Python ≥3.11, asyncio, strict mypy, ruff (line length 100), hermetic pytest (`asyncio_mode=auto`), `FakeLab`/`FakeClock` test harness.

## Global Constraints

- Interpreter: `.venv/bin/python -m pytest|mypy|ruff` (bare `python` lacks deps).
- Gate (must stay green after every task): full `pytest`; `.venv/bin/python -m mypy src` (strict, 36 files clean at branch base); `.venv/bin/python -m ruff check .`; and `awk 'length>100' src/lab_devices/experiment/*.py tests/test_experiment_*.py tests/fakelab.py tests/fakeclock.py tests/experiment_run_helpers.py` prints nothing (ruff default select has no E501, but E402/F401 ARE enforced — keep imports at top of test files).
- Source modules: `from __future__ import annotations` + a one-line module docstring citing the design section. Tests: flat `tests/test_experiment_*.py`, **no** `from __future__ import`, no module docstring (matches existing test convention).
- Suite at branch base (`feat/experiment-orchestrator-5-control-plane`, off main post-PR#4): **483 passed**.
- Design spec: `docs/superpowers/specs/2026-07-08-experiment-orchestrator-5-control-plane-design.md` (I1–I7). This plan implements §4–§8 and §12 of that spec.
- **Durability discipline:** disk writes are synchronous into buffered file objects; no `fsync`. A sink error is *remembered* on the sink and surfaced on the report — it must **never** raise into dispatch, abort the finalizer, or change the run's `status`. Correctness never depends on disk.

---

## File Structure

- `src/lab_devices/experiment/persist.py` **(new)** — `StreamSink` protocol; `run_event_to_dict`; disk sinks (`JsonlRunLogSink`, `CsvRunLogSink`, `JsonlStreamSink`, `CsvStreamSink`); `SinkSet` (config→sinks build, name sanitization, clobber guard, `flush_all`/`close_all`, remembered errors). One responsibility: everything about turning the persistence config into open, writable, flushable files.
- `src/lab_devices/experiment/errors.py` **(modify)** — add `PersistenceError`.
- `src/lab_devices/experiment/context.py` **(modify)** — `RunContext` gains `log_sink` (resolved) + `stream_sinks`; `RunOptions` gains `output_dir` + `flush_interval` and changes `log_sink` default to `None`; `emit` reads `ctx.log_sink`.
- `src/lab_devices/experiment/execute.py` **(modify)** — `_run_measure` captures one timestamp and writes to the stream sink.
- `src/lab_devices/experiment/run.py` **(modify)** — remove D4 rejection; build `SinkSet` before `run_started`; guard the `run_started` emit; launch the gated periodic flush task; final flush/close at finalize; `RunReport` gains `persistence_errors`.
- `src/lab_devices/experiment/__init__.py` **(modify)** — export the new public surface; drop `UnsupportedPersistenceError`.
- `tests/test_experiment_persist.py` **(new)** — unit tests for sinks + `SinkSet`.
- `tests/test_experiment_run_persistence.py` **(new)** — E2E disk-vs-in-memory content, abort completeness, bounded staleness, failure isolation, config/clobber guards.

---

## Task 1: `PersistenceError` in the taxonomy

**Files:**
- Modify: `src/lab_devices/experiment/errors.py`
- Modify: `src/lab_devices/experiment/__init__.py`
- Test: `tests/test_experiment_errors.py` (existing file; add one test)

**Interfaces:**
- Produces: `PersistenceError(ExperimentRunError)` — raised at run start for bad/missing persistence config, missing `output_dir`, target-file clobber, post-sanitization name collision, or a bad `format`. (Runtime per-sink I/O errors are *not* raised — they are remembered on the sink, Task 5/8.)

> `UnsupportedPersistenceError` stays defined and exported through this task (run.py still imports it until Task 8). Task 8 removes it.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_experiment_errors.py` (create it if absent, mirroring existing test style — no future-import, no docstring):

```python
from lab_devices.experiment import PersistenceError
from lab_devices.experiment.errors import ExperimentRunError


def test_persistence_error_is_run_error():
    err = PersistenceError("disk config needs output_dir")
    assert isinstance(err, ExperimentRunError)
    assert "output_dir" in str(err)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_experiment_errors.py::test_persistence_error_is_run_error -v`
Expected: FAIL — `ImportError: cannot import name 'PersistenceError'`.

- [ ] **Step 3: Add the error class**

In `src/lab_devices/experiment/errors.py`, after `UnsupportedPersistenceError`:

```python
class PersistenceError(ExperimentRunError):
    """A persistence sink could not be built: bad/missing config, missing output_dir,
    a target file already exists, a stream-name collision, or a bad format (design 5 §10)."""
```

- [ ] **Step 4: Export it**

In `src/lab_devices/experiment/__init__.py`, add `PersistenceError` to the `from lab_devices.experiment.errors import (...)` block and to `__all__` (next to `UnsupportedPersistenceError`).

- [ ] **Step 5: Run test + gate**

Run: `.venv/bin/python -m pytest tests/test_experiment_errors.py -v && .venv/bin/python -m mypy src && .venv/bin/python -m ruff check .`
Expected: PASS; mypy clean; ruff clean.

- [ ] **Step 6: Commit**

```bash
git add src/lab_devices/experiment/errors.py src/lab_devices/experiment/__init__.py tests/test_experiment_errors.py
git commit -m "feat(experiment): add PersistenceError to run taxonomy (5a)"
```

---

## Task 2: `persist.py` foundations — `StreamSink`, event serialization, name sanitization

**Files:**
- Create: `src/lab_devices/experiment/persist.py`
- Test: `tests/test_experiment_persist.py`

**Interfaces:**
- Produces:
  - `class StreamSink(Protocol)` with `write(self, sample: Sample) -> None`, `flush(self) -> None`, `close(self) -> None`.
  - `run_event_to_dict(event: RunEvent) -> dict[str, Any]` → `{"timestamp","kind","block_id","data"}` (block_id may be `None`).
  - `safe_stream_filename(name: str) -> str` → a filesystem-safe base name (no extension); raises `PersistenceError` if the sanitized result is empty or path-unsafe.

- [ ] **Step 1: Write the failing test**

Create `tests/test_experiment_persist.py`:

```python
import pytest

from lab_devices.experiment import PersistenceError
from lab_devices.experiment.persist import run_event_to_dict, safe_stream_filename
from lab_devices.experiment.runlog import RunEvent


def test_run_event_to_dict_shape():
    ev = RunEvent(12.5, "measure_recorded", "blocks[0]", {"stream": "OD", "value": 0.5})
    assert run_event_to_dict(ev) == {
        "timestamp": 12.5,
        "kind": "measure_recorded",
        "block_id": "blocks[0]",
        "data": {"stream": "OD", "value": 0.5},
    }


def test_run_event_to_dict_none_block_id():
    ev = RunEvent(0.0, "run_started")
    assert run_event_to_dict(ev)["block_id"] is None


def test_safe_stream_filename_passthrough():
    assert safe_stream_filename("OD") == "OD"
    assert safe_stream_filename("temp_C.raw-1") == "temp_C.raw-1"


def test_safe_stream_filename_replaces_unsafe():
    assert safe_stream_filename("O D/2") == "O_D_2"


def test_safe_stream_filename_rejects_empty_and_traversal():
    with pytest.raises(PersistenceError):
        safe_stream_filename("")
    with pytest.raises(PersistenceError):
        safe_stream_filename("..")
    with pytest.raises(PersistenceError):
        safe_stream_filename("///")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_experiment_persist.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'lab_devices.experiment.persist'`.

- [ ] **Step 3: Write the module foundations**

Create `src/lab_devices/experiment/persist.py`:

```python
"""Disk persistence sinks: buffered sync writers mirroring in-memory state. See design 5 §4-7."""

from __future__ import annotations

import re
from typing import Any, Protocol

from lab_devices.experiment.errors import PersistenceError
from lab_devices.experiment.runlog import RunEvent
from lab_devices.experiment.state import Sample


class StreamSink(Protocol):
    """Disk mirror of one measurement stream (sync, buffered). See design 5 §4.1."""

    def write(self, sample: Sample) -> None: ...
    def flush(self) -> None: ...
    def close(self) -> None: ...


def run_event_to_dict(event: RunEvent) -> dict[str, Any]:
    """Lossless dict form of a RunEvent for jsonl / the csv data column (design 5 §7)."""
    return {
        "timestamp": event.timestamp,
        "kind": event.kind,
        "block_id": event.block_id,
        "data": event.data,
    }


_UNSAFE = re.compile(r"[^A-Za-z0-9._-]")


def safe_stream_filename(name: str) -> str:
    """Filesystem-safe base name for a stream file (no extension). Design 5 §6.

    Reject anything that sanitizes to empty or a path-traversal token — a stream name
    is an arbitrary workflow key, never trusted as a path component.
    """
    safe = _UNSAFE.sub("_", name)
    if not safe or set(safe) <= {".", "_"} and safe.strip("._") == "":
        raise PersistenceError(f"stream name {name!r} has no filesystem-safe form")
    if safe in {".", ".."}:
        raise PersistenceError(f"stream name {name!r} is not a safe path component")
    return safe
```

- [ ] **Step 4: Run tests + gate**

Run: `.venv/bin/python -m pytest tests/test_experiment_persist.py -v && .venv/bin/python -m mypy src && .venv/bin/python -m ruff check . && awk 'length>100' src/lab_devices/experiment/persist.py tests/test_experiment_persist.py`
Expected: PASS; mypy clean; ruff clean; awk prints nothing.

- [ ] **Step 5: Commit**

```bash
git add src/lab_devices/experiment/persist.py tests/test_experiment_persist.py
git commit -m "feat(experiment): persist.py foundations — StreamSink, event dict, name sanitization (5a)"
```

---

## Task 3: jsonl sinks (`JsonlRunLogSink`, `JsonlStreamSink`)

**Files:**
- Modify: `src/lab_devices/experiment/persist.py`
- Test: `tests/test_experiment_persist.py`

**Interfaces:**
- Produces:
  - `JsonlRunLogSink(path: Path)` — `emit(event: RunEvent) -> None` writes one JSON object per line; `flush()`, `close()`. Conforms to `RunLogSink`.
  - `JsonlStreamSink(path: Path)` — `write(sample: Sample) -> None` writes `{"timestamp","value"}` per line; `flush()`, `close()`. Conforms to `StreamSink`.
  - Both: internally best-effort — a write/flush error is caught, remembered on `self.errors: list[BaseException]`, and **never raised** (design 5 §8).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_experiment_persist.py`:

```python
import json
from pathlib import Path

from lab_devices.experiment.persist import JsonlRunLogSink, JsonlStreamSink


def test_jsonl_stream_sink_writes_lines(tmp_path: Path):
    sink = JsonlStreamSink(tmp_path / "OD.jsonl")
    sink.write(Sample(1.0, 0.5))
    sink.write(Sample(2.0, 0.6))
    sink.flush()
    sink.close()
    lines = (tmp_path / "OD.jsonl").read_text().splitlines()
    assert [json.loads(x) for x in lines] == [
        {"timestamp": 1.0, "value": 0.5},
        {"timestamp": 2.0, "value": 0.6},
    ]


def test_jsonl_runlog_sink_writes_events(tmp_path: Path):
    sink = JsonlRunLogSink(tmp_path / "run_log.jsonl")
    sink.emit(RunEvent(0.0, "run_started"))
    sink.emit(RunEvent(1.0, "measure_recorded", "blocks[0]", {"stream": "OD", "value": 0.5}))
    sink.flush()
    sink.close()
    lines = (tmp_path / "run_log.jsonl").read_text().splitlines()
    parsed = [json.loads(x) for x in lines]
    assert parsed[0] == {"timestamp": 0.0, "kind": "run_started", "block_id": None, "data": {}}
    assert parsed[1]["kind"] == "measure_recorded"
    assert parsed[1]["data"] == {"stream": "OD", "value": 0.5}


def test_jsonl_sink_remembers_write_error_never_raises(tmp_path: Path):
    sink = JsonlStreamSink(tmp_path / "OD.jsonl")
    sink.close()  # force subsequent writes onto a closed file
    sink.write(Sample(1.0, 0.5))  # must NOT raise
    assert sink.errors  # remembered instead
```

Add the `Sample` and `RunEvent` imports at the top of the test file if not already present (`from lab_devices.experiment.state import Sample`, `from lab_devices.experiment.runlog import RunEvent`).

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_experiment_persist.py -k jsonl -v`
Expected: FAIL — `ImportError: cannot import name 'JsonlRunLogSink'`.

- [ ] **Step 3: Implement the jsonl sinks**

Add to `src/lab_devices/experiment/persist.py` (extend the imports: `import json`, `from pathlib import Path`):

```python
class _JsonlWriter:
    """Shared buffered jsonl append writer; best-effort, remembers its own errors."""

    def __init__(self, path: Path) -> None:
        self.errors: list[BaseException] = []
        self._file = open(path, "w", encoding="utf-8")  # noqa: SIM115 - lifetime is the run

    def _write_obj(self, obj: dict[str, Any]) -> None:
        try:
            self._file.write(json.dumps(obj) + "\n")
        except BaseException as exc:  # noqa: BLE001 - durability is best-effort (design 5 §8)
            self.errors.append(exc)

    def flush(self) -> None:
        try:
            self._file.flush()
        except BaseException as exc:  # noqa: BLE001
            self.errors.append(exc)

    def close(self) -> None:
        try:
            self._file.close()
        except BaseException as exc:  # noqa: BLE001
            self.errors.append(exc)


class JsonlRunLogSink(_JsonlWriter):
    """Run log as one JSON object per line (design 5 §7). Conforms to RunLogSink."""

    def emit(self, event: RunEvent) -> None:
        self._write_obj(run_event_to_dict(event))


class JsonlStreamSink(_JsonlWriter):
    """One measurement stream as {"timestamp","value"} per line (design 5 §7)."""

    def write(self, sample: Sample) -> None:
        self._write_obj({"timestamp": sample.timestamp, "value": sample.value})
```

- [ ] **Step 4: Run tests + gate**

Run: `.venv/bin/python -m pytest tests/test_experiment_persist.py -v && .venv/bin/python -m mypy src && .venv/bin/python -m ruff check . && awk 'length>100' src/lab_devices/experiment/persist.py tests/test_experiment_persist.py`
Expected: PASS; mypy clean; ruff clean; awk silent.

- [ ] **Step 5: Commit**

```bash
git add src/lab_devices/experiment/persist.py tests/test_experiment_persist.py
git commit -m "feat(experiment): jsonl run-log + stream sinks, best-effort remembered errors (5a)"
```

---

## Task 4: csv sinks (`CsvRunLogSink`, `CsvStreamSink`)

**Files:**
- Modify: `src/lab_devices/experiment/persist.py`
- Test: `tests/test_experiment_persist.py`

**Interfaces:**
- Produces:
  - `CsvRunLogSink(path: Path)` — header `timestamp,kind,block_id,data`; `data` is the event's `data` dict JSON-encoded into one column; empty `block_id` when `None`. `emit`/`flush`/`close`; `errors`.
  - `CsvStreamSink(path: Path)` — header `timestamp,value`; one row per sample. `write`/`flush`/`close`; `errors`.
  - Both use `csv.writer` (correct quoting of the JSON `data` column) and are best-effort like the jsonl sinks.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_experiment_persist.py`:

```python
import csv

from lab_devices.experiment.persist import CsvRunLogSink, CsvStreamSink


def test_csv_stream_sink_header_and_rows(tmp_path: Path):
    sink = CsvStreamSink(tmp_path / "OD.csv")
    sink.write(Sample(1.0, 0.5))
    sink.write(Sample(2.0, 0.6))
    sink.flush()
    sink.close()
    rows = list(csv.reader((tmp_path / "OD.csv").read_text().splitlines()))
    assert rows[0] == ["timestamp", "value"]
    assert rows[1] == ["1.0", "0.5"]
    assert rows[2] == ["2.0", "0.6"]


def test_csv_runlog_sink_json_data_column(tmp_path: Path):
    sink = CsvRunLogSink(tmp_path / "run_log.csv")
    sink.emit(RunEvent(1.0, "measure_recorded", "blocks[0]", {"stream": "OD", "value": 0.5}))
    sink.emit(RunEvent(0.0, "run_started"))
    sink.flush()
    sink.close()
    rows = list(csv.reader((tmp_path / "run_log.csv").read_text().splitlines()))
    assert rows[0] == ["timestamp", "kind", "block_id", "data"]
    assert rows[1][0:3] == ["1.0", "measure_recorded", "blocks[0]"]
    assert json.loads(rows[1][3]) == {"stream": "OD", "value": 0.5}
    assert rows[2] == ["0.0", "run_started", "", "{}"]  # None block_id -> empty column
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_experiment_persist.py -k csv -v`
Expected: FAIL — `ImportError: cannot import name 'CsvRunLogSink'`.

- [ ] **Step 3: Implement the csv sinks**

Add to `src/lab_devices/experiment/persist.py` (extend imports: `import csv`):

```python
class _CsvWriter:
    """Shared buffered csv append writer with a fixed header; best-effort."""

    def __init__(self, path: Path, header: list[str]) -> None:
        self.errors: list[BaseException] = []
        self._file = open(path, "w", encoding="utf-8", newline="")  # noqa: SIM115 - run lifetime
        self._writer = csv.writer(self._file)
        self._write_row(header)

    def _write_row(self, row: list[str]) -> None:
        try:
            self._writer.writerow(row)
        except BaseException as exc:  # noqa: BLE001 - durability is best-effort (design 5 §8)
            self.errors.append(exc)

    def flush(self) -> None:
        try:
            self._file.flush()
        except BaseException as exc:  # noqa: BLE001
            self.errors.append(exc)

    def close(self) -> None:
        try:
            self._file.close()
        except BaseException as exc:  # noqa: BLE001
            self.errors.append(exc)


class CsvRunLogSink(_CsvWriter):
    """Run log as csv; the event data dict is JSON-encoded into one column (design 5 §7)."""

    def __init__(self, path: Path) -> None:
        super().__init__(path, ["timestamp", "kind", "block_id", "data"])

    def emit(self, event: RunEvent) -> None:
        self._write_row([
            repr(event.timestamp),
            event.kind,
            event.block_id or "",
            json.dumps(event.data),
        ])


class CsvStreamSink(_CsvWriter):
    """One measurement stream as timestamp,value rows (design 5 §7)."""

    def __init__(self, path: Path) -> None:
        super().__init__(path, ["timestamp", "value"])

    def write(self, sample: Sample) -> None:
        self._write_row([repr(sample.timestamp), repr(sample.value)])
```

> Note: `repr(float)` gives a round-trippable decimal string (`1.0`, `0.5`). The test uses exact fake-clock floats so the strings are stable.

- [ ] **Step 4: Run tests + gate**

Run: `.venv/bin/python -m pytest tests/test_experiment_persist.py -v && .venv/bin/python -m mypy src && .venv/bin/python -m ruff check . && awk 'length>100' src/lab_devices/experiment/persist.py tests/test_experiment_persist.py`
Expected: PASS; mypy clean; ruff clean; awk silent.

- [ ] **Step 5: Commit**

```bash
git add src/lab_devices/experiment/persist.py tests/test_experiment_persist.py
git commit -m "feat(experiment): csv run-log + stream sinks with fixed schemas (5a)"
```

---

## Task 5: `SinkSet` — build from config, sanitize, clobber, flush/close, remembered errors

**Files:**
- Modify: `src/lab_devices/experiment/persist.py`
- Test: `tests/test_experiment_persist.py`

**Interfaces:**
- Consumes: `Workflow` (`.persistence: Persistence`, `.streams: dict[str, StreamDecl]`), the sink classes (Tasks 3–4), `RunLogSink` (runlog.py), `PersistenceError`.
- Produces:
  - `class SinkSet` with fields: `log_sink: RunLogSink`, `stream_sinks: dict[str, StreamSink | None]`, `has_disk: bool`.
  - classmethod `SinkSet.build(workflow, output_dir, log_sink_override) -> SinkSet` — resolves per §5, sanitizes stream filenames (§6), guards missing `output_dir`/clobber/collision/bad-format (§6, §10), creates the dir, opens files. Raises `PersistenceError` **before** opening anything on any guard failure.
  - `flush_all() -> None`, `close_all() -> None` — flush/close every disk sink (duck-typed: anything with `flush`/`close`).
  - `persistence_errors() -> tuple[BaseException, ...]` — aggregated remembered errors across all disk sinks.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_experiment_persist.py`:

```python
from lab_devices.experiment.persist import SinkSet
from lab_devices.experiment.runlog import InMemoryRunLog
from lab_devices.experiment.workflow import Persistence, StreamDecl, Workflow


def _wf(persistence: Persistence, streams: dict[str, StreamDecl]) -> Workflow:
    return Workflow(schema_version=1, streams=streams, persistence=persistence)


def test_sinkset_all_in_memory_no_files(tmp_path: Path):
    wf = _wf(Persistence(default="in_memory"), {"OD": StreamDecl()})
    ss = SinkSet.build(wf, output_dir=None, log_sink_override=None)
    assert isinstance(ss.log_sink, InMemoryRunLog)
    assert ss.stream_sinks == {"OD": None}
    assert ss.has_disk is False
    assert list(tmp_path.iterdir()) == []


def test_sinkset_disk_default_builds_all(tmp_path: Path):
    wf = _wf(Persistence(default="disk", format="jsonl"),
             {"OD": StreamDecl(), "temp": StreamDecl(persistence="in_memory")})
    ss = SinkSet.build(wf, output_dir=tmp_path, log_sink_override=None)
    assert isinstance(ss.log_sink, JsonlRunLogSink)
    assert isinstance(ss.stream_sinks["OD"], JsonlStreamSink)
    assert ss.stream_sinks["temp"] is None  # per-stream override wins
    assert ss.has_disk is True
    assert (tmp_path / "run_log.jsonl").exists()
    assert (tmp_path / "OD.jsonl").exists()
    assert not (tmp_path / "temp.jsonl").exists()
    ss.close_all()


def test_sinkset_injected_log_sink_overrides_config(tmp_path: Path):
    wf = _wf(Persistence(default="disk", format="jsonl"), {})
    inj = InMemoryRunLog()
    ss = SinkSet.build(wf, output_dir=tmp_path, log_sink_override=inj)
    assert ss.log_sink is inj
    assert not (tmp_path / "run_log.jsonl").exists()
    ss.close_all()


def test_sinkset_disk_without_output_dir_raises(tmp_path: Path):
    wf = _wf(Persistence(default="disk"), {"OD": StreamDecl()})
    with pytest.raises(PersistenceError, match="output_dir"):
        SinkSet.build(wf, output_dir=None, log_sink_override=None)


def test_sinkset_refuses_to_clobber(tmp_path: Path):
    (tmp_path / "run_log.jsonl").write_text("stale\n")
    wf = _wf(Persistence(default="disk"), {})
    with pytest.raises(PersistenceError, match="exists"):
        SinkSet.build(wf, output_dir=tmp_path, log_sink_override=None)
    assert (tmp_path / "run_log.jsonl").read_text() == "stale\n"  # untouched


def test_sinkset_name_collision_raises(tmp_path: Path):
    wf = _wf(Persistence(default="disk"), {"O D": StreamDecl(), "O/D": StreamDecl()})
    with pytest.raises(PersistenceError, match="collision"):
        SinkSet.build(wf, output_dir=tmp_path, log_sink_override=None)


def test_sinkset_bad_format_raises(tmp_path: Path):
    wf = _wf(Persistence(default="disk", format="xml"), {})
    with pytest.raises(PersistenceError, match="format"):
        SinkSet.build(wf, output_dir=tmp_path, log_sink_override=None)


def test_sinkset_csv_format(tmp_path: Path):
    wf = _wf(Persistence(default="disk", format="csv"), {"OD": StreamDecl()})
    ss = SinkSet.build(wf, output_dir=tmp_path, log_sink_override=None)
    assert isinstance(ss.log_sink, CsvRunLogSink)
    assert isinstance(ss.stream_sinks["OD"], CsvStreamSink)
    ss.close_all()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_experiment_persist.py -k sinkset -v`
Expected: FAIL — `ImportError: cannot import name 'SinkSet'`.

- [ ] **Step 3: Implement `SinkSet`**

Add to `src/lab_devices/experiment/persist.py` (extend imports: `from lab_devices.experiment.runlog import InMemoryRunLog, RunLogSink`, `from lab_devices.experiment.workflow import Workflow`):

```python
_RUNLOG_SINKS = {"jsonl": JsonlRunLogSink, "csv": CsvRunLogSink}
_STREAM_SINKS = {"jsonl": JsonlStreamSink, "csv": CsvStreamSink}


class SinkSet:
    """Resolved persistence for one run: log sink + per-stream sinks (design 5 §4.2, §5)."""

    def __init__(
        self,
        log_sink: RunLogSink,
        stream_sinks: dict[str, StreamSink | None],
        has_disk: bool,
    ) -> None:
        self.log_sink = log_sink
        self.stream_sinks = stream_sinks
        self.has_disk = has_disk

    @classmethod
    def build(
        cls,
        workflow: Workflow,
        output_dir: Path | None,
        log_sink_override: RunLogSink | None,
    ) -> SinkSet:
        fmt = workflow.persistence.format
        if fmt not in _RUNLOG_SINKS:
            raise PersistenceError(f"unknown persistence format {fmt!r}")
        default = workflow.persistence.default

        # 1. Decide what disk files are needed, without opening anything yet.
        log_on_disk = log_sink_override is None and default == "disk"
        stream_on_disk: dict[str, str] = {}  # stream name -> safe base filename
        used: dict[str, str] = {}  # safe base -> originating stream name (collision guard)
        for name, decl in workflow.streams.items():
            effective = decl.persistence if decl.persistence is not None else default
            if effective == "disk":
                base = safe_stream_filename(name)
                if base in used:
                    raise PersistenceError(
                        f"stream name collision: {name!r} and {used[base]!r} both map to "
                        f"{base!r}.{fmt}"
                    )
                used[base] = name
                stream_on_disk[name] = base

        any_disk = log_on_disk or bool(stream_on_disk)
        if any_disk and output_dir is None:
            raise PersistenceError("disk persistence requested but output_dir is None")

        # 2. Refuse to clobber: check every target before opening any file.
        targets: list[Path] = []
        if any_disk:
            assert output_dir is not None
            if log_on_disk:
                targets.append(output_dir / f"run_log.{fmt}")
            targets += [output_dir / f"{base}.{fmt}" for base in stream_on_disk.values()]
            for path in targets:
                if path.exists():
                    raise PersistenceError(f"persistence target already exists: {path}")
            output_dir.mkdir(parents=True, exist_ok=True)

        # 3. Open sinks (all guards passed).
        if log_sink_override is not None:
            log_sink: RunLogSink = log_sink_override
        elif log_on_disk:
            assert output_dir is not None
            log_sink = _RUNLOG_SINKS[fmt](output_dir / f"run_log.{fmt}")
        else:
            log_sink = InMemoryRunLog()

        stream_sinks: dict[str, StreamSink | None] = {}
        for name in workflow.streams:
            base = stream_on_disk.get(name)
            if base is None:
                stream_sinks[name] = None
            else:
                assert output_dir is not None
                stream_sinks[name] = _STREAM_SINKS[fmt](output_dir / f"{base}.{fmt}")
        return cls(log_sink, stream_sinks, has_disk=bool(stream_on_disk) or log_on_disk)

    def _disk_sinks(self) -> list[Any]:
        sinks: list[Any] = [s for s in self.stream_sinks.values() if s is not None]
        if hasattr(self.log_sink, "flush") or hasattr(self.log_sink, "errors"):
            sinks.append(self.log_sink)
        return sinks

    def flush_all(self) -> None:
        for sink in self._disk_sinks():
            if hasattr(sink, "flush"):
                sink.flush()

    def close_all(self) -> None:
        for sink in self._disk_sinks():
            if hasattr(sink, "close"):
                sink.close()

    def persistence_errors(self) -> tuple[BaseException, ...]:
        errors: list[BaseException] = []
        for sink in self._disk_sinks():
            errors.extend(getattr(sink, "errors", ()))
        return tuple(errors)
```

- [ ] **Step 4: Run tests + gate**

Run: `.venv/bin/python -m pytest tests/test_experiment_persist.py -v && .venv/bin/python -m mypy src && .venv/bin/python -m ruff check . && awk 'length>100' src/lab_devices/experiment/persist.py tests/test_experiment_persist.py`
Expected: PASS (all ~18 persist tests); mypy clean; ruff clean; awk silent.

- [ ] **Step 5: Commit**

```bash
git add src/lab_devices/experiment/persist.py tests/test_experiment_persist.py
git commit -m "feat(experiment): SinkSet builds sinks from config with clobber/collision guards (5a)"
```

---

## Task 6: `RunOptions` + `RunContext` wiring (options, resolved sinks, stream_sinks)

**Files:**
- Modify: `src/lab_devices/experiment/context.py`
- Test: `tests/test_experiment_context.py` (existing; add tests)

**Interfaces:**
- Consumes: `StreamSink` (persist.py), `RunLogSink`/`InMemoryRunLog` (runlog.py).
- Produces:
  - `RunOptions.log_sink: RunLogSink | None = None` (was a defaulted `InMemoryRunLog`); new `RunOptions.output_dir: Path | None = None`; new `RunOptions.flush_interval: float = 30.0`.
  - `RunContext.log_sink: RunLogSink` (resolved, default `InMemoryRunLog`) and `RunContext.stream_sinks: dict[str, StreamSink | None]` (default empty).
  - `RunContext.emit` reads `self.log_sink` (not `self.options.log_sink`).

> `ExperimentRun` (Task 8) overwrites `ctx.log_sink`/`ctx.stream_sinks` during `execute()` prep. Nothing emits before then (pause/abort guard on `_started`), so the construction-time default is never observed by a real run.

- [ ] **Step 1: Write the failing test**

`tests/test_experiment_context.py` already exists (it reads `options.log_sink` — that line is
fixed in Step 5). Add these tests, and add any missing imports at the **top** of the file
(F401/E402): `from pathlib import Path`, `from lab_devices.experiment.context import
RunContext, RunOptions`, `from lab_devices.experiment.runlog import InMemoryRunLog`,
`from lab_devices.experiment.state import RunState`, `from lab_devices.experiment.workflow
import Workflow`. The `fake_client` fixture comes from `tests/conftest.py` (sets `base_url`).

```python
def test_run_options_new_persistence_fields_default():
    opts = RunOptions()
    assert opts.log_sink is None
    assert opts.output_dir is None
    assert opts.flush_interval == 30.0


def test_run_options_accepts_output_dir(tmp_path: Path):
    opts = RunOptions(output_dir=tmp_path, flush_interval=5.0)
    assert opts.output_dir == tmp_path
    assert opts.flush_interval == 5.0


def test_context_default_log_sink_when_options_none(fake_client):
    _, client = fake_client
    ctx = RunContext(client=client, workflow=Workflow(schema_version=1),
                     state=RunState(), options=RunOptions())
    assert isinstance(ctx.log_sink, InMemoryRunLog)  # field default when options.log_sink is None
    ctx.emit("run_started")
    assert ctx.log_sink.events[0].kind == "run_started"


def test_context_adopts_injected_log_sink(fake_client):
    # A directly-built context (as unit tests build) must honor an injected options sink.
    _, client = fake_client
    sink = InMemoryRunLog()
    ctx = RunContext(client=client, workflow=Workflow(schema_version=1),
                     state=RunState(), options=RunOptions(log_sink=sink))
    assert ctx.log_sink is sink
    ctx.emit("run_started")
    assert sink.events[0].kind == "run_started"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_experiment_context.py -v`
Expected: FAIL — `AssertionError` on `opts.log_sink is None` (currently a default `InMemoryRunLog`) / missing `output_dir`.

- [ ] **Step 3: Update `RunOptions` and `RunContext`**

In `src/lab_devices/experiment/context.py`:

Extend imports:
```python
from pathlib import Path

from lab_devices.experiment.persist import StreamSink
```

Change `RunOptions` (`log_sink` default + two new fields):
```python
@dataclass
class RunOptions:
    """User-tunable executor knobs (design 4-exec §3; disk persistence design 5 §5)."""

    clock: Clock = field(default_factory=MonotonicClock)
    input_provider: OperatorInputProvider = field(default_factory=UnattendedInputProvider)
    log_sink: RunLogSink | None = None  # None -> resolved from persistence config at run start
    output_dir: Path | None = None
    flush_interval: float = 30.0
    job_poll_interval: float = 0.25
    job_poll_max: float = 2.0
    job_timeout: float | None = None
```

Add two fields to `RunContext` (after `abort_requested`) plus an injection-aware
`__post_init__`, so a **directly-constructed** context (as the dispatch/finalize/walker unit
tests build) honors an injected `options.log_sink`. `execute()` (Task 8) later overrides both
fields from the resolved `SinkSet`:
```python
    log_sink: RunLogSink = field(default_factory=InMemoryRunLog)
    stream_sinks: dict[str, StreamSink | None] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.options.log_sink is not None:
            self.log_sink = self.options.log_sink
```

Change `RunContext.emit` to use `self.log_sink`:
```python
    def emit(self, kind: str, block_id: str | None = None, **data: Any) -> None:
        self.log_sink.emit(RunEvent(self.clock.now(), kind, block_id, dict(data)))
```

- [ ] **Step 4: Run tests + gate**

Run: `.venv/bin/python -m pytest tests/test_experiment_context.py -v && .venv/bin/python -m mypy src && .venv/bin/python -m ruff check . && awk 'length>100' src/lab_devices/experiment/context.py`
Expected: PASS; mypy clean; ruff clean; awk silent.

> This changes `RunOptions.log_sink`'s default. Some existing executor tests may read `options.log_sink` directly. Run the full suite next step and fix any that assumed a non-None default by reading `run.report.log` instead (the resolved sink).

- [ ] **Step 5: Fix the `options.log_sink` read fallout (14 sites)**

14 existing test sites read the run log via `...options.log_sink.events`; with the `None`
default they must read the resolved `ctx.log_sink` (injection sites — `RunOptions(log_sink=...)`
— are unaffected, they don't end in `.events`). Apply the mechanical transform, then run the
suite:

```bash
grep -rl '\.options\.log_sink\.events' tests/ | xargs sed -i '' 's/\.options\.log_sink\.events/.log_sink.events/g'
.venv/bin/python -m pytest -q
```
Expected: `ctx.options.log_sink.events` → `ctx.log_sink.events` and
`run._ctx.options.log_sink.events` → `run._ctx.log_sink.events` across
dispatch/context/finalize/parallel/walker/pause tests; whole suite green (483+).
(macOS BSD `sed -i ''`; on Linux use `sed -i`.)

- [ ] **Step 6: Commit**

```bash
git add src/lab_devices/experiment/context.py tests/test_experiment_context.py
git commit -m "feat(experiment): RunOptions persistence fields + RunContext resolved sinks (5a)"
```

---

## Task 7: `_run_measure` single timestamp + stream-sink write

**Files:**
- Modify: `src/lab_devices/experiment/execute.py:196-211` (`_run_measure`)
- Test: `tests/test_experiment_execute_measure.py` (existing; add a test) or the file that already exercises `_run_measure`.

**Interfaces:**
- Consumes: `ctx.stream_sinks` (Task 6), `Sample` (state.py).
- Produces: `_run_measure` reads the clock **once**, records to `RunState` and (if present) the stream sink with that same timestamp, then emits.

- [ ] **Step 1: Write the failing test**

Create `tests/test_experiment_execute_measure.py` (uses the `fake_client` fixture from
`conftest.py`, which sets `base_url` — do **not** hand-roll a `LabClient`):

```python
from lab_devices.experiment import blocks as B
from lab_devices.experiment.context import RunContext, RunOptions
from lab_devices.experiment.execute import _run_measure
from lab_devices.experiment.state import RunState, Sample, Stream
from lab_devices.experiment.workflow import Workflow
from tests.experiment_run_helpers import add_standard_devices
from tests.fakeclock import FakeClock, drive


class _RecordingStreamSink:
    def __init__(self) -> None:
        self.samples: list[Sample] = []

    def write(self, sample: Sample) -> None:
        self.samples.append(sample)

    def flush(self) -> None: ...
    def close(self) -> None: ...


async def test_measure_writes_same_timestamp_to_stream_sink(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    clock = FakeClock()
    state = RunState()
    state.streams["OD"] = Stream()
    sink = _RecordingStreamSink()
    ctx = RunContext(client=client, workflow=Workflow(schema_version=1), state=state,
                     options=RunOptions(clock=clock))
    ctx.stream_sinks = {"OD": sink}
    block = B.Measure(device="densitometer_1", verb="measure", into="OD")
    block.id = "blocks[0]"
    await drive(clock, _run_measure(block, ctx))
    assert len(sink.samples) == 1
    # the persisted sample timestamp equals the in-memory sample timestamp exactly
    assert sink.samples[0].timestamp == state.streams["OD"].samples[0].timestamp
    assert sink.samples[0].value == state.streams["OD"].samples[0].value
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_experiment_execute_measure.py -v`
Expected: FAIL — `_RecordingStreamSink.samples` is empty (no stream-sink write yet).

- [ ] **Step 3: Update `_run_measure`**

Replace the tail of `_run_measure` in `src/lab_devices/experiment/execute.py` (the `ctx.state.record(...)` + `ctx.emit(...)` lines) with a single-timestamp version:

```python
    ts = ctx.clock.now()
    fvalue = float(value)
    ctx.state.record(block.into, ts, fvalue)
    sink = ctx.stream_sinks.get(block.into)
    if sink is not None:
        sink.write(Sample(ts, fvalue))
    ctx.emit("measure_recorded", block.id, stream=block.into, value=fvalue)
```

Add `from lab_devices.experiment.state import Sample` to execute.py's imports (top of file).

- [ ] **Step 4: Run test + gate + full suite**

Run: `.venv/bin/python -m pytest tests/test_experiment_execute_measure.py -v && .venv/bin/python -m pytest -q && .venv/bin/python -m mypy src && .venv/bin/python -m ruff check . && awk 'length>100' src/lab_devices/experiment/execute.py`
Expected: PASS; whole suite green; mypy/ruff clean; awk silent.

- [ ] **Step 5: Commit**

```bash
git add src/lab_devices/experiment/execute.py tests/test_experiment_execute_measure.py
git commit -m "feat(experiment): measure records one timestamp to RunState and stream sink (5a)"
```

---

## Task 8: `ExperimentRun` integration — build sinks, remove D4, flush task, finalize flush/close, report

**Files:**
- Modify: `src/lab_devices/experiment/run.py`
- Modify: `src/lab_devices/experiment/__init__.py` (drop `UnsupportedPersistenceError`; export persist surface)
- Modify: `src/lab_devices/experiment/errors.py` (remove `UnsupportedPersistenceError`)
- Test: `tests/test_experiment_run_persistence.py`

**Interfaces:**
- Consumes: `SinkSet` (Task 5), `RunOptions.{output_dir,flush_interval,log_sink}` (Task 6), `ctx.{log_sink,stream_sinks}` (Task 6).
- Produces:
  - `RunReport` gains `persistence_errors: tuple[BaseException, ...] = ()`.
  - `execute()` prep: build `SinkSet` from config **before** `run_started`; set `ctx.log_sink`/`ctx.stream_sinks`; guard the `run_started` emit; launch the periodic flush task **only if `has_disk`**; final flush + close at finalize on every path; populate `report.persistence_errors`.
  - D4 rejection removed; `UnsupportedPersistenceError` deleted.

- [ ] **Step 1: Write the failing tests (build + report + flush lifecycle)**

Create `tests/test_experiment_run_persistence.py`. The `_fresh_client()` helper mirrors
`conftest.py`'s `fake_client` (including `base_url`) for tests that need a second, isolated
lab (Task 9's twin run); single-client tests use the `fake_client` fixture directly.

```python
import json
from pathlib import Path

import httpx
import pytest

from lab_devices.client import LabClient
from lab_devices.experiment import ExperimentRun, PersistenceError, RunOptions
from tests.experiment_run_helpers import add_standard_devices, make_workflow
from tests.fakeclock import FakeClock, drive
from tests.fakelab import FakeLab

_MEASURE = [{"measure": {"device": "densitometer_1", "verb": "measure", "into": "OD"}}]
_STREAMS = {"OD": {"units": "AU"}}
_DISK_JSONL = {"default": "disk", "format": "jsonl"}


def _fresh_client() -> tuple[FakeLab, LabClient]:
    fake = FakeLab()
    add_standard_devices(fake)
    http = httpx.AsyncClient(transport=httpx.MockTransport(fake.handler), base_url="http://lab")
    return fake, LabClient("lab", 80, http=http)


async def test_disk_run_writes_runlog_and_stream(fake_client, tmp_path: Path):
    fake, client = fake_client
    add_standard_devices(fake)
    wf = make_workflow(_MEASURE, streams=_STREAMS, persistence=_DISK_JSONL)
    clock = FakeClock()
    run = ExperimentRun(client, wf, RunOptions(clock=clock, output_dir=tmp_path))
    await drive(clock, run.execute())
    assert run.report is not None and run.report.status == "completed"
    # stream file mirrors RunState exactly (same run)
    od_lines = [json.loads(x) for x in (tmp_path / "OD.jsonl").read_text().splitlines()]
    od_state = run.report.state.streams["OD"].samples
    assert len(od_lines) == len(od_state) == 1
    assert od_lines[0] == {"timestamp": od_state[0].timestamp, "value": od_state[0].value}
    # run log file exists and is parseable, ends with run_finished
    log_lines = [json.loads(x) for x in (tmp_path / "run_log.jsonl").read_text().splitlines()]
    assert log_lines[0]["kind"] == "run_started"
    assert log_lines[-1]["kind"] == "run_finished"
    assert run.report.persistence_errors == ()


async def test_missing_output_dir_fails_before_hardware(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    wf = make_workflow(_MEASURE, streams=_STREAMS, persistence=_DISK_JSONL)
    run = ExperimentRun(client, wf, RunOptions(clock=FakeClock()))  # no output_dir
    with pytest.raises(PersistenceError, match="output_dir"):
        await run.execute()
    assert run.report is not None and run.report.status == "failed"
    assert fake.calls == []  # no hardware touched


async def test_clobber_refused_before_hardware(fake_client, tmp_path: Path):
    fake, client = fake_client
    add_standard_devices(fake)
    (tmp_path / "run_log.jsonl").write_text("stale\n")
    wf = make_workflow(_MEASURE, streams=_STREAMS, persistence=_DISK_JSONL)
    run = ExperimentRun(client, wf, RunOptions(clock=FakeClock(), output_dir=tmp_path))
    with pytest.raises(PersistenceError, match="exists"):
        await run.execute()
    assert fake.calls == []
    assert (tmp_path / "run_log.jsonl").read_text() == "stale\n"  # untouched
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_experiment_run_persistence.py -v`
Expected: FAIL — currently `execute()` raises `UnsupportedPersistenceError` (D4) for disk, and there is no `persistence_errors` field.

- [ ] **Step 3: Add `persistence_errors` to `RunReport` and imports**

In `src/lab_devices/experiment/run.py`:

Replace the D4-era imports:
```python
from lab_devices.experiment.errors import (
    ExperimentRunError,
    FinalizeError,
    PersistenceError,
    RunAbortedError,
)
from lab_devices.experiment.persist import SinkSet
```
(Remove `UnsupportedPersistenceError` from the import list.) Also widen the existing
`runlog` import — the failed-report branch constructs a fresh sink:
```python
from lab_devices.experiment.runlog import InMemoryRunLog, RunLogSink
```

Extend `RunReport`:
```python
@dataclass
class RunReport:
    """Outcome of one execution (design 4-exec §12); set before execute() raises."""

    status: str  # "completed" | "failed" | "aborted" | "cancelled"
    error: BaseException | None
    finalize_errors: tuple[BaseException, ...]
    state: RunState
    log: RunLogSink
    persistence_errors: tuple[BaseException, ...] = ()
```

- [ ] **Step 4: Rewrite `execute()` prep, flush task, and finalize flush/close**

In `ExperimentRun.__init__`, add fields (after `self.report = None`):
```python
        self._sinks: SinkSet | None = None
        self._flush_task: asyncio.Task[None] | None = None
        self._sinks_closed = False
```

Delete `_reject_unsupported_persistence` entirely. Replace the top of `execute()` (the `try/_reject.../except` block) with a sink-build prep:

```python
    async def execute(self) -> RunReport:
        if self._started:
            raise ExperimentRunError("execute() may only be called once per ExperimentRun")
        self._started = True
        ctx = self._ctx
        try:
            sinks = SinkSet.build(
                self._workflow, self._options.output_dir, self._options.log_sink
            )
        except PersistenceError as exc:
            self.report = RunReport("failed", exc, (), ctx.state, InMemoryRunLog())
            raise
        self._sinks = sinks
        ctx.log_sink = sinks.log_sink
        ctx.stream_sinks = sinks.stream_sinks
        self._task = asyncio.current_task()
        try:
            ctx.emit("run_started")
        except BaseException:  # a raising custom sink must not skip finalize (design 5 §8)
            pass
        if sinks.has_disk:
            self._flush_task = asyncio.ensure_future(self._flush_loop())
        error: BaseException | None = None
        try:
            if ctx.abort_requested:
                raise asyncio.CancelledError
            await execute_blocks(self._workflow.blocks, ctx)
        except BaseException as exc:
            error = exc
        await self._stop_flush_task()
        self._finalizing = True
        try:
            finalize_errors = tuple(await run_finalizer(ctx))
        except BaseException as fin_exc:  # finalizer failed catastrophically: still report
            finalize_errors = (fin_exc,)
        if error is not None:
            for fin_err in finalize_errors:
                error.add_note(f"finalizer: {fin_err!r}")
        cancelled = isinstance(error, asyncio.CancelledError)
        aborted = cancelled and ctx.abort_requested
        status = (
            "aborted" if aborted
            else "cancelled" if cancelled
            else "failed" if error is not None
            else "completed"
        )
        self.report = RunReport(
            status=status, error=error, finalize_errors=finalize_errors,
            state=ctx.state, log=sinks.log_sink,
            persistence_errors=sinks.persistence_errors(),
        )
        try:
            ctx.emit("run_finished", status=status)
        except BaseException:  # a raising log sink must not abort reporting (§11)
            pass
        self._flush_and_close_sinks()  # capture run_finished + any post-finalize event
        if cancelled:
            assert error is not None
            if aborted:
                if self._task is not None:
                    self._task.uncancel()
                raise RunAbortedError("run aborted by operator") from error
            raise error
        if error is not None:
            raise error
        if finalize_errors:
            raise FinalizeError(finalize_errors)
        return self.report
```

Add the flush-loop and helpers to the class. The single `_flush_and_close_sinks()` call
sits **after** the `run_finished` emit, so that final event (and all finalizer events)
land on disk before `execute()` raises; the `_sinks_closed` guard keeps it idempotent:
```python
    async def _flush_loop(self) -> None:
        """Periodic durability flush; bounds on-disk staleness (design 5 §4, I2)."""
        interval = self._options.flush_interval
        while True:
            await self._ctx.clock.sleep(interval)
            if self._sinks is not None:
                self._sinks.flush_all()

    async def _stop_flush_task(self) -> None:
        task = self._flush_task
        if task is None:
            return
        self._flush_task = None
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    def _flush_and_close_sinks(self) -> None:
        if self._sinks is not None and not self._sinks_closed:
            self._sinks.flush_all()
            self._sinks.close_all()
            self._sinks_closed = True
```

The `execute()` body above already places the one `self._flush_and_close_sinks()` call
right after the guarded `run_finished` emit — do not add a second call after the finalizer.

- [ ] **Step 5: Remove `UnsupportedPersistenceError` and update exports**

In `src/lab_devices/experiment/errors.py`, delete the `UnsupportedPersistenceError` class.

In `src/lab_devices/experiment/__init__.py`:
- Remove `UnsupportedPersistenceError` from the errors import and from `__all__`.
- Add persist exports: `from lab_devices.experiment.persist import (CsvRunLogSink, CsvStreamSink, JsonlRunLogSink, JsonlStreamSink, SinkSet, StreamSink)` and add those names to `__all__`.

- [ ] **Step 6: Run tests + gate + full suite**

Run: `.venv/bin/python -m pytest tests/test_experiment_run_persistence.py -v && .venv/bin/python -m pytest -q && .venv/bin/python -m mypy src && .venv/bin/python -m ruff check . && awk 'length>100' src/lab_devices/experiment/run.py`
Expected: the 3 new tests PASS; whole suite green (fix any test that referenced `UnsupportedPersistenceError` — none should remain in-tree; grep `git grep UnsupportedPersistenceError` returns nothing); mypy/ruff clean; awk silent.

- [ ] **Step 7: Commit**

```bash
git add src/lab_devices/experiment/run.py src/lab_devices/experiment/errors.py src/lab_devices/experiment/__init__.py tests/test_experiment_run_persistence.py
git commit -m "feat(experiment): build disk sinks from config, gated flush task, finalize flush/close; remove D4 (5a)"
```

---

## Task 9: E2E — flagship §15.2-shaped disk run, jsonl and csv, mirror equality

**Files:**
- Modify: `tests/test_experiment_run_persistence.py`
- May reuse: `tests/experiment_run_helpers.py` (existing compact builders)

**Interfaces:**
- Consumes: `ExperimentRun`, `FakeLab`, `FakeClock`/`drive`, `workflow_from_dict`.

- [ ] **Step 1: Write the failing test — run-log mirror via twin runs; stream mirror via self-consistency**

Add `import csv` and `from lab_devices.experiment.persist import run_event_to_dict` to the
**top** of `tests/test_experiment_run_persistence.py`, then append the `_FEEDBACK` constant
and tests:

```python
_FEEDBACK = [
    {"serial": {"children": [
        {"command": {"device": "pump_2", "verb": "rotate",
                     "params": {"direction": "forward", "speed_ml_min": 2.0}}},
        {"loop": {"check": "after", "count": 2, "body": [
            {"measure": {"device": "densitometer_1", "verb": "measure", "into": "OD"}},
        ]}},
        {"command": {"device": "pump_2", "verb": "stop"}},
    ]}}
]


async def test_disk_jsonl_run_log_mirrors_in_memory(fake_client, tmp_path: Path):
    # Baseline: identical workflow, in-memory persistence, an isolated second lab.
    _, base_client = _fresh_client()
    base_wf = make_workflow(_FEEDBACK, streams=_STREAMS,
                            persistence={"default": "in_memory", "format": "jsonl"})
    base_clock = FakeClock()
    base_run = ExperimentRun(base_client, base_wf, RunOptions(clock=base_clock))
    await drive(base_clock, base_run.execute())
    assert base_run.report is not None
    expected = [run_event_to_dict(e) for e in base_run.report.log.events]
    # Disk run of the identical workflow — deterministic clock => identical event sequence.
    fake, client = fake_client
    add_standard_devices(fake)
    wf = make_workflow(_FEEDBACK, streams=_STREAMS, persistence=_DISK_JSONL)
    clock = FakeClock()
    run = ExperimentRun(client, wf, RunOptions(clock=clock, output_dir=tmp_path))
    await drive(clock, run.execute())
    disk = [json.loads(x) for x in (tmp_path / "run_log.jsonl").read_text().splitlines()]
    assert disk == expected  # byte-for-byte mirror of the in-memory log


async def test_disk_jsonl_stream_mirrors_runstate(fake_client, tmp_path: Path):
    fake, client = fake_client
    add_standard_devices(fake)
    wf = make_workflow(_FEEDBACK, streams=_STREAMS, persistence=_DISK_JSONL)
    clock = FakeClock()
    run = ExperimentRun(client, wf, RunOptions(clock=clock, output_dir=tmp_path))
    await drive(clock, run.execute())
    assert run.report is not None
    disk = [json.loads(x) for x in (tmp_path / "OD.jsonl").read_text().splitlines()]
    state = run.report.state.streams["OD"].samples
    assert len(disk) == len(state) == 2
    assert disk == [{"timestamp": s.timestamp, "value": s.value} for s in state]


async def test_disk_csv_stream_mirrors_runstate(fake_client, tmp_path: Path):
    fake, client = fake_client
    add_standard_devices(fake)
    wf = make_workflow(_FEEDBACK, streams=_STREAMS,
                       persistence={"default": "disk", "format": "csv"})
    clock = FakeClock()
    run = ExperimentRun(client, wf, RunOptions(clock=clock, output_dir=tmp_path))
    await drive(clock, run.execute())
    assert run.report is not None
    rows = list(csv.reader((tmp_path / "OD.csv").read_text().splitlines()))
    assert rows[0] == ["timestamp", "value"]
    state = run.report.state.streams["OD"].samples
    assert [[repr(s.timestamp), repr(s.value)] for s in state] == rows[1:]
```

- [ ] **Step 2: Run tests to verify they fail (then pass)**

Run: `.venv/bin/python -m pytest tests/test_experiment_run_persistence.py -k "mirror" -v`
Expected: PASS if Task 8 is correct. If a mirror assertion fails, the discrepancy IS the bug (e.g. an extra/missing event on disk, a timestamp drift) — fix the source, not the assertion.

- [ ] **Step 3: Gate + commit**

Run: `.venv/bin/python -m pytest tests/test_experiment_run_persistence.py -q && .venv/bin/python -m mypy src && .venv/bin/python -m ruff check . && awk 'length>100' tests/test_experiment_run_persistence.py`
Expected: PASS; mypy/ruff clean; awk silent.

```bash
git add tests/test_experiment_run_persistence.py
git commit -m "test(experiment): disk persistence mirrors in-memory (jsonl log + jsonl/csv streams) (5a)"
```

---

## Task 10: E2E — abort completeness, bounded staleness, failure isolation

**Files:**
- Modify: `tests/test_experiment_run_persistence.py`

**Interfaces:**
- Consumes: `FakeLab.hold_job`/`complete_job`, `run.abort()`, `FakeClock.advance`.

- [ ] **Step 1: Write the failing tests**

Add `import asyncio` and `from lab_devices.experiment import RunAbortedError` to the **top**
of `tests/test_experiment_run_persistence.py`, then append:

```python
class _RaisingLogSink:
    def __init__(self) -> None:
        self.calls = 0

    def emit(self, event) -> None:
        self.calls += 1
        raise RuntimeError("sink boom")


async def test_disk_files_complete_and_parseable_after_abort(fake_client, tmp_path: Path):
    # Held measure job; abort mid-run; the finalizer's final flush must leave whole files.
    fake, client = fake_client
    add_standard_devices(fake)
    fake.hold_job("measure")
    wf = make_workflow(_FEEDBACK, streams=_STREAMS, persistence=_DISK_JSONL)
    clock = FakeClock()
    run = ExperimentRun(client, wf, RunOptions(clock=clock, output_dir=tmp_path))
    task = asyncio.ensure_future(run.execute())
    await clock.settle()  # dispatch reaches the held measure job (mirrors the abort test)
    run.abort()
    with pytest.raises(RunAbortedError):
        await task  # finalizer runs with no clock advance (only HTTP hops)
    assert run.report is not None and run.report.status == "aborted"
    # Every line parses (no torn final line); the log ends at run_finished(aborted).
    parsed = [json.loads(x) for x in (tmp_path / "run_log.jsonl").read_text().splitlines()]
    assert parsed[-1]["kind"] == "run_finished"
    assert parsed[-1]["data"]["status"] == "aborted"
    # Stream file parses; its samples match RunState up to the abort (empty: measure held).
    od = [json.loads(x) for x in (tmp_path / "OD.jsonl").read_text().splitlines()]
    assert od == [
        {"timestamp": s.timestamp, "value": s.value}
        for s in run.report.state.streams["OD"].samples
    ]


async def test_bounded_staleness_periodic_flush(fake_client, tmp_path: Path):
    # With a held job (no finalize yet), advancing past flush_interval flushes buffered lines.
    fake, client = fake_client
    add_standard_devices(fake)
    fake.hold_job("measure")
    wf = make_workflow(_FEEDBACK, streams=_STREAMS, persistence=_DISK_JSONL)
    clock = FakeClock()
    run = ExperimentRun(
        client, wf, RunOptions(clock=clock, output_dir=tmp_path, flush_interval=10.0)
    )
    task = asyncio.ensure_future(run.execute())
    await clock.settle()  # events buffered in userspace, not yet flushed to disk
    assert "run_started" not in (tmp_path / "run_log.jsonl").read_text()
    await clock.advance(10.0)  # fire the periodic flush sleeper (advance() is a coroutine)
    assert "run_started" in (tmp_path / "run_log.jsonl").read_text()  # staleness bounded
    # Clean up: stop holding measures and let the run finish.
    fake.held_jobs.discard("measure")
    report = await drive(clock, task)
    assert report.status == "completed"


async def test_raising_log_sink_still_finalizes_and_sets_report(fake_client):
    # Closes the Increment-4 latent ticket: a custom sink raising on emit must not leave the
    # report unset or skip the finalizer (design 5 §8). The run still fails, but safely.
    fake, client = fake_client
    add_standard_devices(fake)
    wf = make_workflow([{"command": {"device": "pump_1", "verb": "stop"}}])
    sink = _RaisingLogSink()
    run = ExperimentRun(client, wf, RunOptions(clock=FakeClock(), log_sink=sink))
    clock = run._options.clock
    with pytest.raises(RuntimeError):
        await drive(clock, run.execute())
    assert run.report is not None  # finalizer ran and set the report despite the raising sink
    assert sink.calls > 0
```

> Load-bearing assertion in the staleness test: a clock advance past `flush_interval`
> pushes buffered lines to disk *before* finalize. The `"run_started" not in ...` pre-check
> assumes the small run hasn't auto-flushed by buffer-fill (true for a handful of short
> lines under the default ~8 KiB buffer); if a future variant writes more, assert the
> transition on a specific mid-run event instead.

- [ ] **Step 2: Run tests**

Run: `.venv/bin/python -m pytest tests/test_experiment_run_persistence.py -k "abort or staleness or isolated" -v`
Expected: PASS. If the abort scenario deadlocks under `drive`, verify the flush task is cancelled in `_stop_flush_task` before the finalizer (Task 8) and that `drive` keys off the run task.

- [ ] **Step 3: Gate + commit**

Run: `.venv/bin/python -m pytest tests/test_experiment_run_persistence.py -q && .venv/bin/python -m pytest -q && .venv/bin/python -m mypy src && .venv/bin/python -m ruff check . && awk 'length>100' tests/test_experiment_run_persistence.py`
Expected: PASS; whole suite green; mypy/ruff clean; awk silent.

```bash
git add tests/test_experiment_run_persistence.py
git commit -m "test(experiment): disk completeness after abort, bounded staleness, failure isolation (5a)"
```

---

## Task 11: Plan-5a wrap — full gate, ledger, line-length sweep

**Files:**
- Modify: `.superpowers/sdd/progress.md` (append the 5a section)

- [ ] **Step 1: Full gate**

Run:
```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m mypy src
.venv/bin/python -m ruff check .
awk 'length>100' src/lab_devices/experiment/*.py tests/test_experiment_*.py tests/fakelab.py tests/fakeclock.py tests/experiment_run_helpers.py
```
Expected: all green; awk silent. Record the passing count (should be 483 + the new tests).

- [ ] **Step 2: Verify no `UnsupportedPersistenceError` residue**

Run: `git grep -n UnsupportedPersistenceError`
Expected: no matches.

- [ ] **Step 3: Append the 5a ledger section**

Add to `.superpowers/sdd/progress.md` a `# Increment 5a` section noting: tasks 1–11 complete, the passing count, the D4→PersistenceError swap, `has_disk`-gated flush task, and the two-tier durability discipline. (This file is git-ignored; no commit needed for it — confirm with `git check-ignore .superpowers/sdd/progress.md`.)

- [ ] **Step 4: Commit any residual source/tests**

```bash
git add -A -- src/lab_devices tests
git commit -m "chore(experiment): Increment 5a persistence complete — gate green" || echo "nothing to commit"
```

---

## Self-Review (author checklist — completed at write time)

**Spec coverage (design 5 §4–§8, §12):**
- §4.1 protocols/impls → Tasks 2–4. §4.2 SinkSet → Task 5. §4.3 measure single-timestamp → Task 7.
- §5 resolution + options → Tasks 5–6, 8. §6 layout/naming/clobber → Tasks 2, 5. §7 schemas → Tasks 3–4, 9.
- §8 tickets: run_started guard + sink-open-before-dispatch → Task 8; remembered/surfaced sink errors → Tasks 3–5, 8, 10; D4 removal → Task 8; frozen-RunEvent note → documented (no code). abort-vs-cancel `"cancelled"` status is present in `RunReport` (Task 8) and exercised in 5b.
- §12 verification: mirror equality → Task 9; abort completeness / bounded staleness / failure isolation / config+clobber guards → Tasks 8, 10.

**Placeholder scan:** no TBD/TODO; every code step shows complete code; the one soft spot (Task 10 staleness ordering) states the load-bearing assertion explicitly and a fallback.

**Type consistency:** `SinkSet.build(workflow, output_dir, log_sink_override)`, `flush_all`/`close_all`/`persistence_errors`, `ctx.log_sink`/`ctx.stream_sinks`, `RunReport.persistence_errors`, `run_event_to_dict`, `safe_stream_filename` used consistently across Tasks 5–10.

**Deferred to 5b (not this plan):** `status="cancelled"` runtime distinction is *stored* here but its dedicated regression tests, `abort()` double-abort guard, `DeviceBusyError`, `Occupancy.is_busy`, and `Console` all live in plan 5b.
