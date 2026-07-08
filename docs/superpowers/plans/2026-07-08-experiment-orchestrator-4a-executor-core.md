# Experiment Orchestrator — Increment 4a: Sequential Executor + Finalizer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Execute a validated workflow end-to-end against a `LabClient` — sequential block execution (Serial/Loop/Branch/GroupRef/Wait/Command/Measure/OperatorInput), trait-driven dispatch with a live occupancy model, clock-driven job polling, and the always-runs safe-shutdown finalizer — proven by call-sequence assertions against FakeLab.

**Architecture:** Design doc `docs/superpowers/specs/2026-07-08-experiment-orchestrator-4-executor-design.md` (read it first; its D1–D8 and every **[settled]** item are user-approved — do not re-litigate). Module-level recursive async functions (`execute.py`) over a `RunContext` (`context.py`), with `clock.py`/`inputs.py`/`runlog.py`/`occupancy.py` as focused units, `finalize.py` for shutdown, and a thin `ExperimentRun` facade (`run.py`) that validates at construction. Parallel and pause/abort land in plan 4b — `_run_parallel` is a stub here.

**Tech Stack:** Python 3.11 asyncio (structured concurrency), dataclasses, Protocols; pytest + pytest-asyncio (`asyncio_mode = "auto"`); FakeLab (httpx.MockTransport) extended in place; a manual-advance FakeClock (no wall-clock anywhere in executor tests).

## Global Constraints

- Interpreter: run ALL tooling as `.venv/bin/python -m <tool>` — bare `python`/`python3` lacks the deps.
- Gate after every task (all must be clean before commit):
  - `.venv/bin/python -m pytest` (whole suite; 361 passing at branch base)
  - `.venv/bin/python -m mypy` (strict; config checks `src/lab_devices` only — tests are not type-checked)
  - `.venv/bin/python -m ruff check .`
  - `awk 'length > 100 {print FILENAME ":" FNR ": " length}' src/lab_devices/experiment/*.py tests/test_experiment_*.py tests/fakelab.py tests/fakeclock.py tests/experiment_run_helpers.py` — must print nothing.
- Source modules start with `from __future__ import annotations` and a one-line docstring citing the design section ("design 4-exec §N" = the Increment-4 spec). Tests live flat in `tests/` as `test_experiment_*.py` and do NOT use the future-import (repo convention).
- Async tests need no marker (`asyncio_mode = "auto"`); follow the style of existing core tests.
- Branch: `feat/experiment-orchestrator-4-executor` (exists; carries the design-spec commit). Never commit to `main`.
- The static validator, loader, and expression engine are NOT modified (except the two additive changes named in Tasks 2–3: `BlockBase.id`, `Trait.result_field`). Everything that loaded and validated before must keep doing so; the whole existing suite must stay green untouched.
- FakeLab extensions must be default-inert: with no new attribute set, behavior is byte-identical to today (the 361 existing tests prove it).
- Increment-3 carry-forwards enforced here: executor pre-creates every declared stream; `resolve()` only on non-string-kind registry slots; busy tracking keyed `(device, channel)`; engine-assigned block id.

## Settled decisions (user-approved; see spec §2 for the full table)

D2 per-device wire lock held only across one HTTP call; D3 manual-advance FakeClock; D4 reject any non-`in_memory` persistence at run start; D5 recursive functions + facade; D6 validate at construction; D7 runtime open/close classification on **resolved** params; D8 `FinalizeError` when a successful run has finalizer errors. Executor-owned clock-driven job polling (spec §6); synchronous occupancy check-and-mark (spec §7); in-flight entries survive cancelled waits (spec §7); `gap_after` honored unconditionally, trailing `pace` skipped (spec §9); fail-safe everywhere (`EvaluationError` → `BlockFailedError` → finalize).

## Setup (before Task 1)

```bash
cd /Users/khamit/lab-devices
git checkout feat/experiment-orchestrator-4-executor
git add docs/superpowers/plans/2026-07-08-experiment-orchestrator-4a-executor-core.md \
        docs/superpowers/plans/2026-07-08-experiment-orchestrator-4b-concurrency-control.md \
        docs/superpowers/specs/2026-07-08-experiment-orchestrator-4-executor-design.md
git commit -m "docs: increment 4a/4b implementation plans + spec refinements (gap_after, context.py)"
```

---

### Task 1: Runtime error taxonomy

**Files:**
- Modify: `src/lab_devices/experiment/errors.py` (append after `ValidationError`)
- Test: `tests/test_experiment_run_errors.py` (create)

**Interfaces:**
- Consumes: `ExperimentError` (Increment 1); `Sequence` (already imported in errors.py).
- Produces (exact names every later task relies on):
  - `ExperimentRunError(ExperimentError)`
  - `BlockFailedError(ExperimentRunError)` — `__init__(self, block_id: str, message: str)`; attr `block_id`; `str(e) == f"block {block_id}: {message}"`.
  - `InvariantViolationError(ExperimentRunError)`
  - `RunAbortedError(ExperimentRunError)`
  - `FinalizeError(ExperimentRunError)` — `__init__(self, errors: Sequence[BaseException])`; attr `errors: tuple[BaseException, ...]`; message `f"{n} finalizer error(s); hardware may not be in a safe state"`.
  - `UnsupportedPersistenceError(ExperimentRunError)`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_experiment_run_errors.py
from lab_devices.experiment.errors import (
    BlockFailedError,
    ExperimentError,
    ExperimentRunError,
    FinalizeError,
    InvariantViolationError,
    RunAbortedError,
    UnsupportedPersistenceError,
)


def test_taxonomy():
    for cls in (
        BlockFailedError,
        InvariantViolationError,
        RunAbortedError,
        FinalizeError,
        UnsupportedPersistenceError,
    ):
        assert issubclass(cls, ExperimentRunError)
    assert issubclass(ExperimentRunError, ExperimentError)


def test_block_failed_carries_block_id():
    err = BlockFailedError("blocks[0].children[2]", "empty stream window")
    assert err.block_id == "blocks[0].children[2]"
    assert str(err) == "block blocks[0].children[2]: empty stream window"


def test_block_failed_cause_chain():
    cause = ValueError("boom")
    try:
        try:
            raise cause
        except ValueError as exc:
            raise BlockFailedError("blocks[1]", str(exc)) from exc
    except BlockFailedError as err:
        assert err.__cause__ is cause


def test_finalize_error_aggregates():
    errs = (RuntimeError("t1"), RuntimeError("t2"))
    err = FinalizeError(errs)
    assert err.errors == errs
    assert str(err) == "2 finalizer error(s); hardware may not be in a safe state"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_experiment_run_errors.py -v`
Expected: FAIL — `ImportError: cannot import name 'ExperimentRunError'`

- [ ] **Step 3: Write minimal implementation** — append to `src/lab_devices/experiment/errors.py`:

```python
class ExperimentRunError(ExperimentError):
    """Base for errors raised while executing a workflow (design 4-exec §15)."""


class BlockFailedError(ExperimentRunError):
    """A block failed at dispatch or completion; `__cause__` carries the original error."""

    def __init__(self, block_id: str, message: str) -> None:
        self.block_id = block_id
        super().__init__(f"block {block_id}: {message}")


class InvariantViolationError(ExperimentRunError):
    """A proven-impossible occupancy state was observed (busy-slot conflict or hardware
    BusyError). Never retried: the static proof was violated (design 4-exec §7)."""


class RunAbortedError(ExperimentRunError):
    """The operator aborted the run; the finalizer has completed (design 4-exec §10)."""


class FinalizeError(ExperimentRunError):
    """The run completed, but the finalizer could not fully reach safe state (D8)."""

    def __init__(self, errors: Sequence[BaseException]) -> None:
        self.errors = tuple(errors)
        super().__init__(
            f"{len(self.errors)} finalizer error(s); hardware may not be in a safe state"
        )


class UnsupportedPersistenceError(ExperimentRunError):
    """The workflow requests persistence that arrives in Increment 5 (design 4-exec D4)."""
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_experiment_run_errors.py -v`
Expected: 4 passed

- [ ] **Step 5: Full gate** (pytest whole suite / mypy / ruff / awk per Global Constraints)

- [ ] **Step 6: Commit**

```bash
git add src/lab_devices/experiment/errors.py tests/test_experiment_run_errors.py
git commit -m "feat(experiment): runtime error taxonomy for the executor"
```

---

### Task 2: Engine-assigned block ids

**Files:**
- Modify: `src/lab_devices/experiment/blocks.py` (add `id` to `BlockBase`)
- Create: `src/lab_devices/experiment/run.py` (only `assign_block_ids` for now; the facade lands in Task 12)
- Test: `tests/test_experiment_block_ids.py` (create)

**Interfaces:**
- Consumes: `blocks.py` dataclasses, `Workflow`.
- Produces:
  - `BlockBase.id: str | None = None` (kw-only default; NEVER serialized).
  - `assign_block_ids(workflow: Workflow) -> None` in `lab_devices.experiment.run` — mutates every block's `id` to its structural path, exactly matching validator diagnostic paths: `blocks[i]`, `.children[i]`, `.body[i]`, `.then[i]`, `.else[i]`, and `groups['name'].body[i]` for group bodies.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_experiment_block_ids.py
from lab_devices.experiment.blocks import Command, Serial
from lab_devices.experiment.run import assign_block_ids
from lab_devices.experiment.serialize import block_to_dict, workflow_from_dict


def _wf(doc_blocks, groups=None):
    doc = {"schema_version": 1, "blocks": doc_blocks}
    if groups:
        doc["groups"] = groups
    return workflow_from_dict(doc)


def test_id_defaults_to_none_and_never_serializes():
    b = Command(device="pump_1", verb="stop")
    assert b.id is None
    b.id = "blocks[0]"
    assert "id" not in block_to_dict(b)


def test_loader_rejects_authored_id_key():
    import pytest

    from lab_devices.experiment.errors import WorkflowLoadError

    with pytest.raises(WorkflowLoadError, match="exactly one type key"):
        workflow_from_dict(
            {"schema_version": 1,
             "blocks": [{"command": {"device": "pump_1", "verb": "stop"}, "id": "x"}]}
        )


def test_assign_ids_structural_paths():
    w = _wf(
        [
            {"serial": {"children": [
                {"command": {"device": "pump_1", "verb": "stop"}},
                {"branch": {"if": "true", "then": [
                    {"command": {"device": "pump_1", "verb": "stop"}}],
                    "else": [{"command": {"device": "pump_1", "verb": "stop"}}]}},
                {"loop": {"count": 2, "body": [
                    {"command": {"device": "pump_1", "verb": "stop"}}]}},
            ]}}
        ],
        groups={"g": {"body": [{"command": {"device": "pump_1", "verb": "stop"}}]}},
    )
    assign_block_ids(w)
    serial = w.blocks[0]
    assert serial.id == "blocks[0]"
    assert serial.children[0].id == "blocks[0].children[0]"
    branch = serial.children[1]
    assert branch.then[0].id == "blocks[0].children[1].then[0]"
    assert branch.else_[0].id == "blocks[0].children[1].else[0]"
    assert serial.children[2].body[0].id == "blocks[0].children[2].body[0]"
    assert w.groups["g"].body[0].id == "groups['g'].body[0]"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_experiment_block_ids.py -v`
Expected: FAIL — `Command has no attribute 'id'` / `ModuleNotFoundError: lab_devices.experiment.run`

- [ ] **Step 3: Write minimal implementation**

In `src/lab_devices/experiment/blocks.py`, add to `BlockBase` (first field):

```python
@dataclass(kw_only=True)
class BlockBase:
    id: str | None = None  # engine-assigned at load; never serialized (design §5, 4-exec §13)
    label: str | None = None
    gap_after: str | None = None  # serial: end-of-this -> start-of-next
    start_offset: str | None = None  # parallel: container-start -> this-start
```

Create `src/lab_devices/experiment/run.py`:

```python
"""Public run facade for the executor. See design 4-exec §3, §13."""

from __future__ import annotations

from lab_devices.experiment import blocks as B
from lab_devices.experiment.workflow import Workflow


def assign_block_ids(workflow: Workflow) -> None:
    """Engine-assigned structural ids matching validator diagnostic paths (4-exec §13)."""

    def walk(blocks: list[B.Block], prefix: str) -> None:
        for i, block in enumerate(blocks):
            path = f"{prefix}[{i}]"
            block.id = path
            if isinstance(block, (B.Serial, B.Parallel)):
                walk(block.children, f"{path}.children")
            elif isinstance(block, B.Loop):
                walk(block.body, f"{path}.body")
            elif isinstance(block, B.Branch):
                walk(block.then, f"{path}.then")
                if block.else_ is not None:
                    walk(block.else_, f"{path}.else")

    walk(workflow.blocks, "blocks")
    for name, group in workflow.groups.items():
        walk(group.body, f"groups[{name!r}].body")
```

- [ ] **Step 4: Run test to verify it passes** — `.venv/bin/python -m pytest tests/test_experiment_block_ids.py -v` → 3 passed

- [ ] **Step 5: Full gate** (note: serializer round-trip tests must stay green — `id` is invisible to JSON)

- [ ] **Step 6: Commit**

```bash
git add src/lab_devices/experiment/blocks.py src/lab_devices/experiment/run.py tests/test_experiment_block_ids.py
git commit -m "feat(experiment): engine-assigned structural block ids"
```

---

### Task 3: Registry `result_field`

**Files:**
- Modify: `src/lab_devices/experiment/registry.py`
- Test: `tests/test_experiment_registry.py` (append)

**Interfaces:**
- Produces: `Trait.result_field: str | None` (kw-only, default `None`); `("densitometer", "measure")` → `"absorbance"`, `("densitometer", "measure_blank")` → `"slope"`; every non-measurement verb keeps `None`.

- [ ] **Step 1: Write the failing test** — append to `tests/test_experiment_registry.py`:

```python
def test_measurement_verbs_declare_result_field():
    assert lookup("densitometer_1", "measure").result_field == "absorbance"
    assert lookup("densitometer_1", "measure_blank").result_field == "slope"


def test_result_field_only_on_measurement_verbs():
    from lab_devices.experiment.registry import _REGISTRY

    for (dtype, verb), trait in _REGISTRY.items():
        if trait.measurement:
            assert trait.result_field is not None, (dtype, verb)
        else:
            assert trait.result_field is None, (dtype, verb)
```

(If the file's existing imports lack `lookup`, match its current import style.)

- [ ] **Step 2: Run test to verify it fails** — `.venv/bin/python -m pytest tests/test_experiment_registry.py -v` → FAIL: `Trait has no attribute 'result_field'`

- [ ] **Step 3: Write minimal implementation** — in `registry.py`:

Add to `Trait`:

```python
    result_field: str | None = field(default=None, kw_only=True)
```

Change the two measurement entries:

```python
    ("densitometer", "measure"): Trait(
        "job",
        "none",
        channels=_OPTICS,
        measurement=True,
        result_field="absorbance",
        params=(ParamSpec("include_raw", "bool"),),
    ),
    ("densitometer", "measure_blank"): Trait(
        "job", "none", channels=_OPTICS, measurement=True, result_field="slope"
    ),
```

- [ ] **Step 4: Run test to verify it passes** — same command → all passed

- [ ] **Step 5: Full gate**

- [ ] **Step 6: Commit**

```bash
git add src/lab_devices/experiment/registry.py tests/test_experiment_registry.py
git commit -m "feat(experiment): registry result_field for measurement verbs"
```

---

### Task 4: Clock protocol + FakeClock with driver

**Files:**
- Create: `src/lab_devices/experiment/clock.py`
- Create: `tests/fakeclock.py` (helper module, not a test file)
- Test: `tests/test_experiment_clock.py` (create)

**Interfaces:**
- Produces (production):
  - `Clock` Protocol — `def now(self) -> float`; `async def sleep(self, seconds: float) -> None`.
  - `MonotonicClock` — `now()` = `asyncio.get_running_loop().time()`; `sleep` = `asyncio.sleep`.
- Produces (tests; every later executor test uses these):
  - `FakeClock(start: float = 0.0)` — `now()`; `await sleep(s)` (s <= 0 → one yield); `await settle()` (bounded `sleep(0)` rounds); `await advance(seconds)` (fires due sleepers in deadline order, settling between firings so woken tasks can register new sleeps before later deadlines fire); `next_deadline() -> float | None` (skips cancelled sleepers).
  - `await drive(clock, coro, max_steps=10_000)` — runs `coro` to completion by alternating settle / advance-to-next-deadline; `AssertionError("deadlock: ...")` if the task pends with no sleepers; always cancels the task on the way out of a failure.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_experiment_clock.py
import asyncio

import pytest

from lab_devices.experiment.clock import Clock, MonotonicClock
from tests.fakeclock import FakeClock, drive


async def test_monotonic_clock_satisfies_protocol():
    clock: Clock = MonotonicClock()
    before = clock.now()
    await clock.sleep(0)
    assert clock.now() >= before


async def test_fake_clock_no_premature_fire():
    clock = FakeClock()
    fired: list[str] = []

    async def sleeper(name: str, seconds: float) -> None:
        await clock.sleep(seconds)
        fired.append(name)

    t1 = asyncio.ensure_future(sleeper("a", 10.0))
    t2 = asyncio.ensure_future(sleeper("b", 5.0))
    await clock.advance(4.9)
    assert fired == []
    await clock.advance(0.2)
    assert fired == ["b"]
    await clock.advance(5.0)
    assert fired == ["b", "a"]
    assert clock.now() == pytest.approx(10.1)
    await asyncio.gather(t1, t2)


async def test_fake_clock_chained_sleeps_fire_in_order():
    clock = FakeClock()
    fired: list[float] = []

    async def chain() -> None:
        for _ in range(3):
            await clock.sleep(1.0)
            fired.append(clock.now())

    task = asyncio.ensure_future(chain())
    await clock.advance(3.0)  # sleeps registered one at a time; settling must chain them
    assert fired == [pytest.approx(1.0), pytest.approx(2.0), pytest.approx(3.0)]
    await task


async def test_drive_runs_to_completion():
    clock = FakeClock()

    async def work() -> str:
        await clock.sleep(30.0)
        await clock.sleep(30.0)
        return "done"

    assert await drive(clock, work()) == "done"
    assert clock.now() == pytest.approx(60.0)


async def test_drive_detects_deadlock():
    clock = FakeClock()
    gate = asyncio.Event()  # never set: no sleeper, task never done

    async def stuck() -> None:
        await gate.wait()

    with pytest.raises(AssertionError, match="deadlock"):
        await drive(clock, stuck())
```

- [ ] **Step 2: Run test to verify it fails** — `.venv/bin/python -m pytest tests/test_experiment_clock.py -v` → FAIL: `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

`src/lab_devices/experiment/clock.py`:

```python
"""Injectable clock: one time source for stamps, windows, and sleeps. See design 4-exec §6."""

from __future__ import annotations

import asyncio
from typing import Protocol


class Clock(Protocol):
    def now(self) -> float: ...

    async def sleep(self, seconds: float) -> None: ...


class MonotonicClock:
    """Production clock: event-loop time + asyncio.sleep."""

    def now(self) -> float:
        return asyncio.get_running_loop().time()

    async def sleep(self, seconds: float) -> None:
        await asyncio.sleep(seconds)
```

`tests/fakeclock.py`:

```python
"""Deterministic manual-advance clock for executor tests (design 4-exec §6, D3)."""

import asyncio
import heapq
from typing import Any, Coroutine, TypeVar

T = TypeVar("T")

_SETTLE_ROUNDS = 50  # bounded yields; covers httpx.MockTransport's event-loop hops


class FakeClock:
    def __init__(self, start: float = 0.0) -> None:
        self._now = start
        self._heap: list[tuple[float, int, asyncio.Future[None]]] = []
        self._seq = 0

    def now(self) -> float:
        return self._now

    async def sleep(self, seconds: float) -> None:
        if seconds <= 0:
            await asyncio.sleep(0)
            return
        future: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        self._seq += 1
        heapq.heappush(self._heap, (self._now + seconds, self._seq, future))
        await future

    async def settle(self) -> None:
        """Let ready tasks run (bounded, deterministic)."""
        for _ in range(_SETTLE_ROUNDS):
            await asyncio.sleep(0)

    async def advance(self, seconds: float) -> None:
        """Advance time, firing due sleepers in deadline order; settle between firings
        so a woken task can register its next sleep before later deadlines fire."""
        target = self._now + seconds
        await self.settle()
        while self._heap and self._heap[0][0] <= target:
            deadline, _, future = heapq.heappop(self._heap)
            self._now = max(self._now, deadline)
            if not future.cancelled():
                future.set_result(None)
            await self.settle()
        self._now = target
        await self.settle()

    def next_deadline(self) -> "float | None":
        while self._heap and self._heap[0][2].cancelled():
            heapq.heappop(self._heap)
        return self._heap[0][0] if self._heap else None


async def drive(
    clock: FakeClock, coro: Coroutine[Any, Any, T], *, max_steps: int = 10_000
) -> T:
    """Run coro to completion, advancing the clock to each next deadline.

    Raises AssertionError on deadlock (task pending, no sleepers) instead of hanging.
    Not suitable for paused-run phases (a paused gate has no sleeper): use
    settle()/advance() manually there.
    """
    task: "asyncio.Task[T]" = asyncio.ensure_future(coro)
    try:
        for _ in range(max_steps):
            await clock.settle()
            if task.done():
                return task.result()
            deadline = clock.next_deadline()
            if deadline is None:
                raise AssertionError("deadlock: task pending but no sleepers scheduled")
            await clock.advance(deadline - clock.now())
        raise AssertionError(f"drive() did not finish within {max_steps} steps")
    finally:
        if not task.done():
            task.cancel()
            try:
                await task
            except BaseException:
                pass
```

- [ ] **Step 4: Run test to verify it passes** — 5 passed

- [ ] **Step 5: Full gate**

- [ ] **Step 6: Commit**

```bash
git add src/lab_devices/experiment/clock.py tests/fakeclock.py tests/test_experiment_clock.py
git commit -m "feat(experiment): injectable clock + deterministic FakeClock/drive"
```

---

### Task 5: Run log + operator-input provider

**Files:**
- Create: `src/lab_devices/experiment/runlog.py`
- Create: `src/lab_devices/experiment/inputs.py`
- Test: `tests/test_experiment_runlog_inputs.py` (create)

**Interfaces:**
- Produces (`runlog.py`):
  - `RunEvent` — frozen dataclass: `timestamp: float`, `kind: str`, `block_id: str | None = None`, `data: dict[str, Any] = field(default_factory=dict)`.
  - `RunLogSink` Protocol — `def emit(self, event: RunEvent) -> None`.
  - `InMemoryRunLog` — attr `events: list[RunEvent]`; `emit` appends.
- Produces (`inputs.py`):
  - `InputRequest` — frozen dataclass: `name: str`, `type: str`, `prompt: str | None`, `min: float | None`, `max: float | None`, `choices: list[str] | None`, `block_id: str`.
  - `OperatorInputProvider` Protocol — `async def request(self, request: InputRequest) -> BindingValue`.
  - `UnattendedInputProvider` — `request` raises `EvaluationError` (fail-safe default).
  - `validate_input_value(request: InputRequest, value: BindingValue) -> BindingValue` — raises `EvaluationError` on type/constraint violation; `int` accepts only `int` (bool excluded), `float` accepts `int | float` (bool excluded), `bool` only `bool`, `enum` a `str` in `choices`; `min`/`max` checked for numerics.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_experiment_runlog_inputs.py
import pytest

from lab_devices.experiment.errors import EvaluationError
from lab_devices.experiment.inputs import (
    InputRequest,
    UnattendedInputProvider,
    validate_input_value,
)
from lab_devices.experiment.runlog import InMemoryRunLog, RunEvent


def _req(**kw):
    base = dict(name="x", type="float", prompt=None, min=None, max=None,
                choices=None, block_id="blocks[0]")
    base.update(kw)
    return InputRequest(**base)


def test_in_memory_log_appends_in_order():
    log = InMemoryRunLog()
    e1 = RunEvent(0.0, "run_started")
    e2 = RunEvent(1.0, "block_started", "blocks[0]", {"n": 1})
    log.emit(e1)
    log.emit(e2)
    assert log.events == [e1, e2]
    assert log.events[1].data == {"n": 1}


async def test_unattended_provider_is_fail_safe():
    with pytest.raises(EvaluationError, match="no input provider"):
        await UnattendedInputProvider().request(_req())


def test_validate_float_accepts_int_rejects_bool():
    assert validate_input_value(_req(type="float"), 3) == 3
    assert validate_input_value(_req(type="float"), 3.5) == 3.5
    with pytest.raises(EvaluationError):
        validate_input_value(_req(type="float"), True)
    with pytest.raises(EvaluationError):
        validate_input_value(_req(type="float"), "3.5")


def test_validate_int_strict():
    assert validate_input_value(_req(type="int"), 4) == 4
    with pytest.raises(EvaluationError):
        validate_input_value(_req(type="int"), 4.0)  # providers return typed values
    with pytest.raises(EvaluationError):
        validate_input_value(_req(type="int"), True)


def test_validate_bounds():
    req = _req(type="float", min=0.0, max=2.0)
    assert validate_input_value(req, 1.5) == 1.5
    with pytest.raises(EvaluationError, match="below min"):
        validate_input_value(req, -0.1)
    with pytest.raises(EvaluationError, match="above max"):
        validate_input_value(req, 2.1)


def test_validate_enum_and_bool():
    req = _req(type="enum", choices=["a", "b"])
    assert validate_input_value(req, "a") == "a"
    with pytest.raises(EvaluationError):
        validate_input_value(req, "c")
    with pytest.raises(EvaluationError):
        validate_input_value(_req(type="bool"), 1)
    assert validate_input_value(_req(type="bool"), True) is True


def test_validate_unknown_type_fails_safe():
    with pytest.raises(EvaluationError, match="unsupported type"):
        validate_input_value(_req(type="voltage"), 1.0)
```

- [ ] **Step 2: Run test to verify it fails** — FAIL: `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

`src/lab_devices/experiment/runlog.py`:

```python
"""Run-log events and sinks (in-memory this increment). See design 4-exec §12."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class RunEvent:
    """One observable executor event; timestamps come from the run clock."""

    timestamp: float
    kind: str
    block_id: str | None = None
    data: dict[str, Any] = field(default_factory=dict)


class RunLogSink(Protocol):
    def emit(self, event: RunEvent) -> None: ...


class InMemoryRunLog:
    """Default sink: appends to a list (disk sinks arrive in Increment 5)."""

    def __init__(self) -> None:
        self.events: list[RunEvent] = []

    def emit(self, event: RunEvent) -> None:
        self.events.append(event)
```

`src/lab_devices/experiment/inputs.py`:

```python
"""Operator-input provider protocol, unattended default, fail-safe validation.
See design 4-exec §8."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from lab_devices.experiment.errors import EvaluationError
from lab_devices.experiment.state import BindingValue


@dataclass(frozen=True)
class InputRequest:
    """Everything a provider needs to prompt the operator for one binding."""

    name: str
    type: str
    prompt: str | None
    min: float | None
    max: float | None
    choices: list[str] | None
    block_id: str


class OperatorInputProvider(Protocol):
    async def request(self, request: InputRequest) -> BindingValue: ...


class UnattendedInputProvider:
    """Default provider: no operator wired; any request fails the block (fail-safe)."""

    async def request(self, request: InputRequest) -> BindingValue:
        raise EvaluationError(
            f"operator input {request.name!r} requested but no input provider is configured"
        )


def validate_input_value(request: InputRequest, value: BindingValue) -> BindingValue:
    """Executor-side check of a provider's value; providers own any re-prompt UX."""
    kind = request.type
    if kind == "bool":
        if not isinstance(value, bool):
            raise EvaluationError(f"input {request.name!r} requires a bool, got {value!r}")
        return value
    if kind == "enum":
        if not isinstance(value, str):
            raise EvaluationError(
                f"input {request.name!r} requires a string choice, got {value!r}"
            )
        if request.choices is not None and value not in request.choices:
            raise EvaluationError(
                f"input {request.name!r} must be one of {request.choices!r}, got {value!r}"
            )
        return value
    if kind == "int":
        if isinstance(value, bool) or not isinstance(value, int):
            raise EvaluationError(f"input {request.name!r} requires an int, got {value!r}")
        number = float(value)
    elif kind == "float":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise EvaluationError(f"input {request.name!r} requires a number, got {value!r}")
        number = float(value)
    else:
        raise EvaluationError(f"input {request.name!r} has unsupported type {kind!r}")
    if request.min is not None and number < request.min:
        raise EvaluationError(f"input {request.name!r} below min {request.min}: {value!r}")
    if request.max is not None and number > request.max:
        raise EvaluationError(f"input {request.name!r} above max {request.max}: {value!r}")
    return value
```

- [ ] **Step 4: Run test to verify it passes** — 8 passed

- [ ] **Step 5: Full gate**

- [ ] **Step 6: Commit**

```bash
git add src/lab_devices/experiment/runlog.py src/lab_devices/experiment/inputs.py tests/test_experiment_runlog_inputs.py
git commit -m "feat(experiment): run-log sink + operator-input provider protocol"
```

---

### Task 6: Occupancy (busy slots + open-mode registry)

**Files:**
- Create: `src/lab_devices/experiment/occupancy.py`
- Test: `tests/test_experiment_occupancy.py` (create)

**Interfaces:**
- Consumes: `InvariantViolationError` (Task 1).
- Produces:
  - `OpenMode` — frozen dataclass: `device: str`, `mode_verb: str`, `teardown_verb: str`, `teardown_params: dict[str, object]`, `channels: frozenset[str]`, `block_id: str`. (Do not hash instances — `teardown_params` is a dict.)
  - `Occupancy` — ALL methods synchronous (this is the no-interleave guarantee):
    - `acquire(device, channels, block_id, *, closes: str | None = None)` — raises `InvariantViolationError` on conflict; a matching close (`closes == occupant.mode_verb`) passes through mode-held slots.
    - `release(device, channels, block_id)` — frees only this block's command holds.
    - `register_open(mode: OpenMode)` — converts holds to mode occupancy; appends to open list.
    - `register_close(device, mode_verb) -> OpenMode | None` — pops + frees; `None` = legal no-op close.
    - `open_modes() -> tuple[OpenMode, ...]` — snapshot in open order.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_experiment_occupancy.py
import pytest

from lab_devices.experiment.errors import InvariantViolationError
from lab_devices.experiment.occupancy import Occupancy, OpenMode

MOTOR = frozenset({"motor"})
OPTICS = frozenset({"optics"})
THERMAL = frozenset({"thermal"})


def _rotate_mode(block_id="blocks[0]"):
    return OpenMode(
        device="pump_1", mode_verb="rotate", teardown_verb="stop",
        teardown_params={}, channels=MOTOR, block_id=block_id,
    )


def test_acquire_release_cycle():
    occ = Occupancy()
    occ.acquire("pump_1", MOTOR, "blocks[0]")
    with pytest.raises(InvariantViolationError, match="command in flight"):
        occ.acquire("pump_1", MOTOR, "blocks[1]")
    occ.release("pump_1", MOTOR, "blocks[0]")
    occ.acquire("pump_1", MOTOR, "blocks[1]")  # free again


def test_distinct_channels_do_not_conflict():
    occ = Occupancy()
    occ.acquire("densitometer_1", THERMAL, "blocks[0]")
    occ.acquire("densitometer_1", OPTICS, "blocks[1]")  # legal: disjoint channels
    occ.acquire("pump_1", MOTOR, "blocks[2]")  # different device entirely


def test_open_mode_blocks_same_channel_commands():
    occ = Occupancy()
    occ.acquire("pump_1", MOTOR, "blocks[0]")
    occ.register_open(_rotate_mode("blocks[0]"))
    occ.release("pump_1", MOTOR, "blocks[0]")  # opener's hold is gone; mode remains
    with pytest.raises(InvariantViolationError, match="mode 'rotate'"):
        occ.acquire("pump_1", MOTOR, "blocks[1]")  # dispense while rotating
    with pytest.raises(InvariantViolationError):
        occ.acquire("pump_1", MOTOR, "blocks[2]", closes="set_led")  # wrong close


def test_matching_close_passes_through_and_frees():
    occ = Occupancy()
    occ.acquire("pump_1", MOTOR, "blocks[0]")
    occ.register_open(_rotate_mode("blocks[0]"))
    occ.release("pump_1", MOTOR, "blocks[0]")
    occ.acquire("pump_1", MOTOR, "blocks[3]", closes="rotate")  # allowed through
    closed = occ.register_close("pump_1", "rotate")
    assert closed is not None and closed.block_id == "blocks[0]"
    occ.release("pump_1", MOTOR, "blocks[3]")
    occ.acquire("pump_1", MOTOR, "blocks[4]")  # fully free now
    assert occ.open_modes() == ()


def test_close_with_no_open_mode_is_noop():
    occ = Occupancy()
    assert occ.register_close("pump_1", "rotate") is None


def test_release_only_frees_own_holds():
    occ = Occupancy()
    occ.acquire("pump_1", MOTOR, "blocks[0]")
    occ.release("pump_1", MOTOR, "blocks[9]")  # someone else's release: no effect
    with pytest.raises(InvariantViolationError):
        occ.acquire("pump_1", MOTOR, "blocks[1]")


def test_open_modes_snapshot_in_open_order():
    occ = Occupancy()
    led = OpenMode("densitometer_1", "set_led", "set_led", {"level": 0}, OPTICS, "b1")
    thermo = OpenMode(
        "densitometer_1", "set_thermostat", "set_thermostat", {"enabled": False},
        THERMAL, "b2",
    )
    occ.acquire("densitometer_1", OPTICS, "b1")
    occ.register_open(led)
    occ.acquire("densitometer_1", THERMAL, "b2")
    occ.register_open(thermo)
    assert [m.mode_verb for m in occ.open_modes()] == ["set_led", "set_thermostat"]
```

- [ ] **Step 2: Run test to verify it fails** — FAIL: `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation** — `src/lab_devices/experiment/occupancy.py`:

```python
"""Live occupancy: (device, channel) busy slots + the open-mode registry.
See design 4-exec §7."""

from __future__ import annotations

from dataclasses import dataclass

from lab_devices.experiment.errors import InvariantViolationError


@dataclass(frozen=True)
class OpenMode:
    """One live continuous mode awaiting its close or the finalizer."""

    device: str
    mode_verb: str
    teardown_verb: str
    teardown_params: dict[str, object]
    channels: frozenset[str]
    block_id: str


@dataclass(frozen=True)
class _Hold:
    """A slot held by one in-flight command."""

    block_id: str


class Occupancy:
    """Non-blocking busy tracking. Every method is synchronous, so check-and-mark
    cannot be interleaved by a sibling asyncio task (design 4-exec §7 step 4)."""

    def __init__(self) -> None:
        self._slots: dict[tuple[str, str], _Hold | OpenMode] = {}
        self._modes: list[OpenMode] = []  # open order; the finalizer walks it reversed

    def acquire(
        self, device: str, channels: frozenset[str], block_id: str, *,
        closes: str | None = None,
    ) -> None:
        """Mark `channels` busy for `block_id` or raise. `closes` names the mode this
        command closes: the matching close may pass through its own mode's slots — the
        one exception design §12 allows."""
        for channel in sorted(channels):
            occupant = self._slots.get((device, channel))
            if occupant is None:
                continue
            if isinstance(occupant, OpenMode) and closes == occupant.mode_verb:
                continue
            what = (
                f"mode {occupant.mode_verb!r} opened by block {occupant.block_id}"
                if isinstance(occupant, OpenMode)
                else f"command in flight from block {occupant.block_id}"
            )
            raise InvariantViolationError(
                f"({device}, {channel}) is occupied by {what}; block {block_id} "
                f"cannot dispatch — scheduler invariant violated"
            )
        for channel in channels:
            if (device, channel) not in self._slots:
                self._slots[(device, channel)] = _Hold(block_id)

    def release(self, device: str, channels: frozenset[str], block_id: str) -> None:
        """Free the command holds `block_id` placed; mode-held slots are untouched."""
        for channel in channels:
            occupant = self._slots.get((device, channel))
            if isinstance(occupant, _Hold) and occupant.block_id == block_id:
                del self._slots[(device, channel)]

    def register_open(self, mode: OpenMode) -> None:
        """Convert the opener's command holds into the mode's long-lived occupancy."""
        for channel in mode.channels:
            self._slots[(mode.device, channel)] = mode
        self._modes.append(mode)

    def register_close(self, device: str, mode_verb: str) -> OpenMode | None:
        """Pop an open mode and free its channels; None if not open (legal no-op)."""
        for i, mode in enumerate(self._modes):
            if mode.device == device and mode.mode_verb == mode_verb:
                del self._modes[i]
                for channel in mode.channels:
                    if self._slots.get((mode.device, channel)) is mode:
                        del self._slots[(mode.device, channel)]
                return mode
        return None

    def open_modes(self) -> tuple[OpenMode, ...]:
        """Snapshot of live modes in open order (the finalizer tears down reversed)."""
        return tuple(self._modes)
```

- [ ] **Step 4: Run test to verify it passes** — 7 passed

- [ ] **Step 5: Full gate**

- [ ] **Step 6: Commit**

```bash
git add src/lab_devices/experiment/occupancy.py tests/test_experiment_occupancy.py
git commit -m "feat(experiment): synchronous occupancy model (busy slots + open modes)"
```

---

### Task 7: FakeLab extensions + client fixture + workflow helpers

**Files:**
- Modify: `tests/fakelab.py`
- Modify: `tests/conftest.py` (add `fake_client` fixture)
- Create: `tests/experiment_run_helpers.py`
- Test: `tests/test_fakelab.py` (append a new section)

**Interfaces:**
- Produces (FakeLab, all default-inert):
  - `calls: list[tuple[str, str, dict]]` — every routed device command `(device_id, cmd, params)` in order; `get_job` excluded unless `record_polls = True`. Recorded for unreachable devices too (an attempt is an attempt), but NOT for unknown devices.
  - `inject_error(device_id, cmd, code, message, *, times=1)` — queue consumed on match before normal handling (any cmd, including job starts).
  - `fail_jobs: set[str]` — job cmds whose jobs fail with `hardware_error` at completion.
  - `hold_job(cmd)` / `held_jobs: set[str]` — held jobs never advance by polling; `complete_job(job_id, *, error=None)` finishes one manually (success result = canned `JOB_RESULTS`).
  - `polls_to_complete_by_cmd: dict[str, int]` — per-cmd override of `polls_to_complete`.
- Produces (`tests/conftest.py`): fixture `fake_client` → `(fake: FakeLab, client: LabClient)` over MockTransport.
- Produces (`tests/experiment_run_helpers.py`):
  - `make_workflow(blocks, *, streams=None, groups=None, persistence=None) -> Workflow` — builds via `workflow_from_dict` (so the loader is exercised) and calls `assign_block_ids`.
  - `add_standard_devices(fake)` — pump_1, pump_2, valve_1, densitometer_1.
  - `ScriptedInputProvider(values: dict[str, BindingValue])` — records `requests`, returns `values[request.name]`.
  - `verbs(fake) -> list[tuple[str, str]]` — `[(device_id, cmd), ...]` projection of `fake.calls` (the sequence-assertion workhorse).

- [ ] **Step 1: Write the failing test** — append the tests below to `tests/test_fakelab.py`. IMPORTANT: put any imports the file does not already have (`pytest`, `httpx`, `from lab_devices import errors`, `from lab_devices.client import LabClient`) into the EXISTING top-of-file import block — module-level imports mid-file fail ruff E402.

```python
# ---- Increment-4 extensions (executor test surface) ----


@pytest.fixture
def fake_and_client():
    fake = FakeLab()
    fake.add_device("pump_1", "pump")
    http = httpx.AsyncClient(
        transport=httpx.MockTransport(fake.handler), base_url="http://lab"
    )
    return fake, LabClient("lab", 80, http=http)


async def test_calls_recorded_in_order_without_polls(fake_and_client):
    fake, client = fake_and_client
    pump = client.pump(1)
    await pump.rotate(direction="forward", speed_ml_min=2.0)
    job = await pump.dispense(volume_ml=1.0)
    await job.result()
    await pump.stop()
    assert [(d, c) for d, c, _ in fake.calls] == [
        ("pump_1", "rotate"), ("pump_1", "dispense"), ("pump_1", "stop")
    ]
    assert fake.calls[0][2] == {"direction": "forward", "speed_ml_min": 2.0}


async def test_record_polls_opt_in(fake_and_client):
    fake, client = fake_and_client
    fake.record_polls = True
    job = await client.pump(1).dispense(volume_ml=1.0)
    await job.result()
    assert ("pump_1", "get_job") in [(d, c) for d, c, _ in fake.calls]


async def test_inject_error_once_then_normal(fake_and_client):
    fake, client = fake_and_client
    fake.inject_error("pump_1", "dispense", "busy", "job j-9 running")
    with pytest.raises(errors.BusyError):
        await client.pump(1).dispense(volume_ml=1.0)
    job = await client.pump(1).dispense(volume_ml=1.0)  # queue drained
    assert (await job.result())["dispensed_ml"] == 10.0


async def test_fail_jobs_per_command(fake_and_client):
    fake, client = fake_and_client
    fake.fail_jobs.add("dispense")
    job = await client.pump(1).dispense(volume_ml=1.0)
    with pytest.raises(errors.JobFailedError):
        await job.result()


async def test_hold_and_complete_job(fake_and_client):
    fake, client = fake_and_client
    fake.hold_job("dispense")
    job = await client.pump(1).dispense(volume_ml=1.0)
    await job.refresh()
    await job.refresh()
    assert job.state == "running"  # held: polls never complete it
    fake.complete_job(job.job_id)
    await job.refresh()
    assert job.state == "succeeded"


async def test_polls_to_complete_by_cmd(fake_and_client):
    fake, client = fake_and_client
    fake.polls_to_complete_by_cmd["dispense"] = 3
    job = await client.pump(1).dispense(volume_ml=1.0)
    await job.refresh()
    assert job.state == "running"
    await job.refresh()
    assert job.state == "running"
    await job.refresh()
    assert job.state == "succeeded"
```

- [ ] **Step 2: Run test to verify it fails** — `.venv/bin/python -m pytest tests/test_fakelab.py -v` → new tests FAIL (`FakeLab has no attribute 'calls'` etc.); existing tests still pass.

- [ ] **Step 3: Write minimal implementation**

In `tests/fakelab.py`, extend `FakeLab.__init__`:

```python
        # ---- Increment-4 executor test surface (default-inert) ----
        self.calls: list[tuple[str, str, dict[str, Any]]] = []
        self.record_polls = False
        self.fail_jobs: set[str] = set()
        self.held_jobs: set[str] = set()
        self.polls_to_complete_by_cmd: dict[str, int] = {}
        self._injected: dict[tuple[str, str], list[tuple[str, str]]] = {}
```

Add setup helpers after `add_device`:

```python
    def inject_error(
        self, device_id: str, cmd: str, code: str, message: str, *, times: int = 1
    ) -> None:
        """Queue an envelope error for the next `times` matching commands."""
        self._injected.setdefault((device_id, cmd), []).extend([(code, message)] * times)

    def hold_job(self, cmd: str) -> None:
        """Jobs of this command never advance by polling; use complete_job()."""
        self.held_jobs.add(cmd)

    def complete_job(self, job_id: str, *, error: dict[str, Any] | None = None) -> None:
        """Manually finish a (typically held) job."""
        job = self.jobs[job_id]
        if error is not None:
            job.state, job.error = "failed", error
        else:
            job.state, job.result = "succeeded", JOB_RESULTS.get(job.cmd, {})
```

In `_command`, insert immediately after the unknown-device check (before the `get_job` branch):

```python
        if cmd != "get_job" or self.record_polls:
            self.calls.append((device_id, cmd or "", dict(params)))
        queue = self._injected.get((device_id, cmd or ""))
        if queue:
            code, message = queue.pop(0)
            return err(409 if code == "busy" else 500, code, message)
```

Replace `_advance` with:

```python
    def _advance(self, job: FakeJob) -> None:
        if job.state != "running" or job.cmd in self.held_jobs:
            return
        job.polls += 1
        threshold = self.polls_to_complete_by_cmd.get(job.cmd, self.polls_to_complete)
        if job.polls >= threshold:
            if self.fail_job or job.cmd in self.fail_jobs:
                job.state = "failed"
                job.error = {"code": "hardware_error", "message": "device became unreachable"}
            else:
                job.state = "succeeded"
                job.result = JOB_RESULTS.get(job.cmd, {})
```

In `tests/conftest.py`, add `from lab_devices.client import LabClient` to the top import block, and append:

```python
@pytest.fixture
def fake_client():
    fake = FakeLab()
    http = httpx.AsyncClient(transport=httpx.MockTransport(fake.handler), base_url="http://lab")
    return fake, LabClient("lab", 80, http=http)
```

Create `tests/experiment_run_helpers.py`:

```python
"""Shared builders for executor tests: workflows, devices, scripted inputs."""

from typing import Any

from lab_devices.experiment.inputs import InputRequest
from lab_devices.experiment.run import assign_block_ids
from lab_devices.experiment.serialize import workflow_from_dict
from lab_devices.experiment.state import BindingValue
from lab_devices.experiment.workflow import Workflow
from tests.fakelab import FakeLab


def make_workflow(
    blocks: list[dict[str, Any]],
    *,
    streams: dict[str, Any] | None = None,
    groups: dict[str, Any] | None = None,
    persistence: dict[str, Any] | None = None,
) -> Workflow:
    doc: dict[str, Any] = {"schema_version": 1, "blocks": blocks}
    if streams is not None:
        doc["streams"] = streams
    if groups is not None:
        doc["groups"] = groups
    if persistence is not None:
        doc["persistence"] = persistence
    workflow = workflow_from_dict(doc)
    assign_block_ids(workflow)
    return workflow


def add_standard_devices(fake: FakeLab) -> None:
    fake.add_device("pump_1", "pump")
    fake.add_device("pump_2", "pump")
    fake.add_device("valve_1", "valve")
    fake.add_device("densitometer_1", "densitometer")


def verbs(fake: FakeLab) -> list[tuple[str, str]]:
    """(device, cmd) projection of the chronological call log."""
    return [(device, cmd) for device, cmd, _ in fake.calls]


class ScriptedInputProvider:
    """Test provider: returns scripted values by input name; records every request."""

    def __init__(self, values: dict[str, BindingValue]) -> None:
        self.values = dict(values)
        self.requests: list[InputRequest] = []

    async def request(self, request: InputRequest) -> BindingValue:
        self.requests.append(request)
        return self.values[request.name]
```

- [ ] **Step 4: Run test to verify it passes** — `.venv/bin/python -m pytest tests/test_fakelab.py -v` → all passed (old + new)

- [ ] **Step 5: Full gate** — the 361 pre-existing tests prove default-inertness.

- [ ] **Step 6: Commit**

```bash
git add tests/fakelab.py tests/conftest.py tests/experiment_run_helpers.py tests/test_fakelab.py
git commit -m "test(fakelab): call recording, error injection, job hold/complete for executor tests"
```

---

### Task 8: RunOptions + RunContext

**Files:**
- Create: `src/lab_devices/experiment/context.py`
- Test: `tests/test_experiment_context.py` (create)

**Interfaces:**
- Consumes: `Clock`/`MonotonicClock`, `OperatorInputProvider`/`UnattendedInputProvider`, `RunLogSink`/`InMemoryRunLog`/`RunEvent`, `Occupancy`, `RunState`, `Workflow`, `LabClient`, `Device`, `Job`.
- Produces:
  - `RunOptions` — dataclass, fields exactly: `clock: Clock = field(default_factory=MonotonicClock)`, `input_provider: OperatorInputProvider = field(default_factory=UnattendedInputProvider)`, `log_sink: RunLogSink = field(default_factory=InMemoryRunLog)`, `job_poll_interval: float = 0.25`, `job_poll_max: float = 2.0`, `job_timeout: float | None = None`.
  - `RunContext` — dataclass, fields: `client: LabClient`, `workflow: Workflow`, `state: RunState`, `options: RunOptions`, then defaults `occupancy: Occupancy`, `devices: dict[str, Device]`, `locks: dict[str, asyncio.Lock]`, `touched: dict[str, None]`, `in_flight: dict[str, tuple[str, Job]]` (job_id → (device_id, job)), `gate: asyncio.Event` (created **set**), `abort_requested: bool = False`. Methods/properties: `clock` (→ `options.clock`), `inputs` (→ `options.input_provider`), `device(device_id) -> Device` (cached via `client.device`), `lock(device_id) -> asyncio.Lock` (lazy), `emit(kind, block_id=None, **data)` (RunEvent stamped with `clock.now()`).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_experiment_context.py
from lab_devices.experiment.context import RunContext, RunOptions
from lab_devices.experiment.state import RunState
from tests.experiment_run_helpers import add_standard_devices, make_workflow
from tests.fakeclock import FakeClock


def _ctx(client, **opt):
    options = RunOptions(clock=FakeClock(start=100.0), **opt)
    return RunContext(
        client=client, workflow=make_workflow([]), state=RunState(), options=options
    )


def test_defaults():
    options = RunOptions()
    assert options.job_poll_interval == 0.25
    assert options.job_poll_max == 2.0
    assert options.job_timeout is None


async def test_device_handles_cached(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    ctx = _ctx(client)
    assert ctx.device("pump_1") is ctx.device("pump_1")
    assert ctx.device("pump_1").id == "pump_1"


async def test_locks_lazy_and_per_device(fake_client):
    _, client = fake_client
    ctx = _ctx(client)
    lock = ctx.lock("pump_1")
    assert ctx.lock("pump_1") is lock
    assert ctx.lock("pump_2") is not lock


async def test_gate_starts_set(fake_client):
    _, client = fake_client
    assert _ctx(client).gate.is_set()


async def test_emit_stamps_clock_time(fake_client):
    _, client = fake_client
    ctx = _ctx(client)
    ctx.emit("run_started")
    ctx.emit("block_started", "blocks[0]", n=1)
    events = ctx.options.log_sink.events
    assert [e.kind for e in events] == ["run_started", "block_started"]
    assert events[0].timestamp == 100.0
    assert events[1].block_id == "blocks[0]" and events[1].data == {"n": 1}
```

- [ ] **Step 2: Run test to verify it fails** — FAIL: `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation** — `src/lab_devices/experiment/context.py`:

```python
"""Run-scoped context threaded through the executor. See design 4-exec §5."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from lab_devices.client import LabClient
from lab_devices.devices.base import Device
from lab_devices.experiment.clock import Clock, MonotonicClock
from lab_devices.experiment.inputs import OperatorInputProvider, UnattendedInputProvider
from lab_devices.experiment.occupancy import Occupancy
from lab_devices.experiment.runlog import InMemoryRunLog, RunEvent, RunLogSink
from lab_devices.experiment.state import RunState
from lab_devices.experiment.workflow import Workflow
from lab_devices.jobs import Job


@dataclass
class RunOptions:
    """User-tunable executor knobs (design 4-exec §3)."""

    clock: Clock = field(default_factory=MonotonicClock)
    input_provider: OperatorInputProvider = field(default_factory=UnattendedInputProvider)
    log_sink: RunLogSink = field(default_factory=InMemoryRunLog)
    job_poll_interval: float = 0.25
    job_poll_max: float = 2.0
    job_timeout: float | None = None


def _running_gate() -> asyncio.Event:
    gate = asyncio.Event()
    gate.set()
    return gate


@dataclass
class RunContext:
    """Everything one run threads through the recursive walk (design 4-exec §5)."""

    client: LabClient
    workflow: Workflow
    state: RunState
    options: RunOptions
    occupancy: Occupancy = field(default_factory=Occupancy)
    devices: dict[str, Device] = field(default_factory=dict)
    locks: dict[str, asyncio.Lock] = field(default_factory=dict)
    touched: dict[str, None] = field(default_factory=dict)
    in_flight: dict[str, tuple[str, Job]] = field(default_factory=dict)
    gate: asyncio.Event = field(default_factory=_running_gate)
    abort_requested: bool = False

    @property
    def clock(self) -> Clock:
        return self.options.clock

    @property
    def inputs(self) -> OperatorInputProvider:
        return self.options.input_provider

    def device(self, device_id: str) -> Device:
        if device_id not in self.devices:
            self.devices[device_id] = self.client.device(device_id)
        return self.devices[device_id]

    def lock(self, device_id: str) -> asyncio.Lock:
        """Wire-serialization lock (D2): held only across one HTTP call, never across
        a job wait or a mode scope."""
        if device_id not in self.locks:
            self.locks[device_id] = asyncio.Lock()
        return self.locks[device_id]

    def emit(self, kind: str, block_id: str | None = None, **data: Any) -> None:
        self.options.log_sink.emit(RunEvent(self.clock.now(), kind, block_id, dict(data)))
```

Note: the test reads `ctx.options.log_sink.events` — fine untyped in tests; source stays Protocol-typed.

- [ ] **Step 4: Run test to verify it passes** — 5 passed

- [ ] **Step 5: Full gate**

- [ ] **Step 6: Commit**

```bash
git add src/lab_devices/experiment/context.py tests/test_experiment_context.py
git commit -m "feat(experiment): RunOptions + RunContext"
```

---

### Task 9: Action dispatch pipeline (`_run_action` + `_await_job`)

**Files:**
- Create: `src/lab_devices/experiment/execute.py` (first slice)
- Test: `tests/test_experiment_dispatch.py` (create)

**Interfaces:**
- Consumes: everything above; `lab_devices.errors` (`BusyError`, `JobTimeoutError`), `lab_devices.jobs.Job`, `resolve`/`evaluate`/`parse_expression`, `lookup`/`mode_action`/`ParamSpec`/`Trait`, `OpenMode`.
- Produces (used by Tasks 10–11 and plan 4b):
  - `_TERMINAL = frozenset({"succeeded", "failed", "cancelled"})`
  - `_condition(text: str, ctx: RunContext) -> bool`
  - `_resolve_params(block: Command | Measure, trait: Trait, ctx) -> dict[str, Any]`
  - `_check_kind(value: Value, spec: ParamSpec) -> Value`
  - `_await_job(job: Job, device_id: str, ctx) -> Any`
  - `_run_action(block: Command | Measure, ctx) -> Any` — full §7 pipeline; returns the call result (job result for job verbs).

**The five invariants a reviewer must be able to trace in this code** (spec §7): (1) no `await` between occupancy check and mark — `acquire` is sync and called un-awaited; (2) wire lock spans exactly one HTTP call; (3) in-flight entries removed only at terminal state; (4) `BusyError` → `InvariantViolationError`, no retry; (5) mode slots survive the opener's `finally` release.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_experiment_dispatch.py
import pytest

from lab_devices.experiment import blocks as B
from lab_devices.experiment.context import RunContext, RunOptions
from lab_devices.experiment.errors import EvaluationError, InvariantViolationError
from lab_devices.experiment.execute import _await_job, _run_action
from lab_devices.experiment.state import RunState, Stream
from tests.experiment_run_helpers import add_standard_devices, make_workflow, verbs
from tests.fakeclock import FakeClock, drive


def make_ctx(client, workflow=None, *, clock=None, job_timeout=None):
    wf = workflow if workflow is not None else make_workflow([])
    options = RunOptions(clock=clock or FakeClock(), job_timeout=job_timeout)
    state = RunState()
    for name in wf.streams:
        state.streams[name] = Stream()
    return RunContext(client=client, workflow=wf, state=state, options=options)


def cmd(device, verb, params=None, id="blocks[0]"):
    return B.Command(device=device, verb=verb, params=params or {}, id=id)


async def test_immediate_verb_dispatches_and_frees(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    ctx = make_ctx(client)
    await _run_action(cmd("valve_1", "home", {"position": 1}), ctx)
    assert verbs(fake) == [("valve_1", "home")]
    assert fake.calls[0][2] == {"position": 1}
    ctx.occupancy.acquire("valve_1", frozenset({"motor"}), "blocks[9]")  # slot free again
    assert "valve_1" in ctx.touched


async def test_job_verb_polls_via_clock_and_untracks(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    fake.polls_to_complete_by_cmd["dispense"] = 3  # forces two 0.25s poll sleeps
    clock = FakeClock()
    ctx = make_ctx(client, clock=clock)
    result = await drive(clock, _run_action(cmd("pump_1", "dispense", {"volume_ml": 1.0}), ctx))
    assert result.dispensed_ml == 10.0  # typed DispenseResult from the core
    assert ctx.in_flight == {}
    assert clock.now() > 0  # polling really slept on the fake clock


async def test_expression_params_resolved_at_dispatch(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    wf = make_workflow([], streams={"OD": {}})
    ctx = make_ctx(client, wf)
    ctx.state.record("OD", 0.0, 0.4)
    ctx.state.bind("target", 1.0)
    block = cmd("pump_1", "dispense",
                {"volume_ml": "2.0 * (target - mean(OD, last=100))", "speed_ml_min": 3.0})
    await drive(ctx.clock, _run_action(block, ctx))
    sent = fake.calls[0][2]
    assert sent["volume_ml"] == pytest.approx(1.2)
    assert sent["speed_ml_min"] == 3.0


async def test_string_kind_params_stay_opaque(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    ctx = make_ctx(client)
    # "forward" would parse as a binding ref and raise if blanket-resolved (carry-forward)
    block = cmd("pump_2", "rotate", {"direction": "forward", "speed_ml_min": 2.0})
    await _run_action(block, ctx)
    assert fake.calls[0][2]["direction"] == "forward"


async def test_int_slot_coerces_integral_float(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    ctx = make_ctx(client)
    await _run_action(cmd("densitometer_1", "set_led", {"level": "8 / 2"}), ctx)
    sent = fake.calls[0][2]["level"]
    assert sent == 4 and isinstance(sent, int)


async def test_int_slot_rejects_fractional(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    ctx = make_ctx(client)
    with pytest.raises(EvaluationError, match="requires an integer"):
        await _run_action(cmd("densitometer_1", "set_led", {"level": "7 / 2"}), ctx)
    assert fake.calls == []  # failed before the wire


async def test_unresolvable_param_fails_before_wire(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    wf = make_workflow([], streams={"OD": {}})
    ctx = make_ctx(client, wf)
    with pytest.raises(EvaluationError, match="empty stream window"):
        await _run_action(cmd("pump_1", "dispense", {"volume_ml": "mean(OD)"}), ctx)
    assert fake.calls == []


async def test_mode_open_registers_and_survives_release(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    ctx = make_ctx(client)
    await _run_action(cmd("pump_2", "rotate", {"direction": "forward", "speed_ml_min": 2.0}), ctx)
    modes = ctx.occupancy.open_modes()
    assert [(m.device, m.mode_verb, m.teardown_verb) for m in modes] == [
        ("pump_2", "rotate", "stop")
    ]
    with pytest.raises(InvariantViolationError):  # motor is mode-held after the block ended
        await _run_action(cmd("pump_2", "dispense", {"volume_ml": 1.0}, id="blocks[1]"), ctx)


async def test_matching_close_closes_and_frees(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    ctx = make_ctx(client)
    await _run_action(cmd("pump_2", "rotate", {"direction": "forward", "speed_ml_min": 2.0}), ctx)
    await _run_action(cmd("pump_2", "stop", id="blocks[1]"), ctx)
    assert ctx.occupancy.open_modes() == ()
    await drive(ctx.clock, _run_action(cmd("pump_2", "dispense", {"volume_ml": 1.0},
                                           id="blocks[2]"), ctx))  # free again


async def test_runtime_close_on_resolved_params_D7(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    ctx = make_ctx(client)
    await _run_action(cmd("densitometer_1", "set_led", {"level": 5}), ctx)
    assert len(ctx.occupancy.open_modes()) == 1
    # expression resolving to the teardown literal counts as a close at runtime (D7)
    await _run_action(cmd("densitometer_1", "set_led", {"level": "10 - 10"}, id="blocks[1]"), ctx)
    assert ctx.occupancy.open_modes() == ()


async def test_busy_error_maps_to_invariant_violation_no_retry(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    fake.inject_error("pump_1", "dispense", "busy", "job j-1 in progress")
    ctx = make_ctx(client)
    with pytest.raises(InvariantViolationError, match="busy"):
        await _run_action(cmd("pump_1", "dispense", {"volume_ml": 1.0}), ctx)
    assert verbs(fake) == [("pump_1", "dispense")]  # exactly one attempt, never retried
    events = [e.kind for e in ctx.options.log_sink.events]
    assert "invariant_violation" in events
    ctx.occupancy.acquire("pump_1", frozenset({"motor"}), "blocks[9]")  # slot rolled back


async def test_failed_call_rolls_back_mode_open(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    fake.inject_error("pump_2", "rotate", "hardware_error", "stall")
    ctx = make_ctx(client)
    from lab_devices import errors as core_errors

    with pytest.raises(core_errors.HardwareError):
        await _run_action(cmd("pump_2", "rotate",
                              {"direction": "forward", "speed_ml_min": 2.0}), ctx)
    assert ctx.occupancy.open_modes() == ()
    ctx.occupancy.acquire("pump_2", frozenset({"motor"}), "blocks[9]")  # rolled back


async def test_job_timeout_keeps_in_flight_entry(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    fake.hold_job("dispense")
    clock = FakeClock()
    ctx = make_ctx(client, clock=clock, job_timeout=10.0)
    from lab_devices import errors as core_errors

    with pytest.raises(core_errors.JobTimeoutError):
        await drive(clock, _run_action(cmd("pump_1", "dispense", {"volume_ml": 1.0}), ctx))
    assert len(ctx.in_flight) == 1  # still tracked: the finalizer must stop this device
```

- [ ] **Step 2: Run test to verify it fails** — FAIL: `ModuleNotFoundError: lab_devices.experiment.execute`

- [ ] **Step 3: Write minimal implementation** — create `src/lab_devices/experiment/execute.py`:

```python
"""Recursive async executor: trait-driven dispatch over the block tree.
See design 4-exec §7-9."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from lab_devices import errors as core_errors
from lab_devices.experiment import blocks as B
from lab_devices.experiment.context import RunContext
from lab_devices.experiment.errors import EvaluationError, InvariantViolationError
from lab_devices.experiment.evaluate import Value, evaluate, resolve
from lab_devices.experiment.expr import parse_expression
from lab_devices.experiment.occupancy import OpenMode
from lab_devices.experiment.registry import ParamSpec, Trait, lookup, mode_action
from lab_devices.jobs import Job

_TERMINAL = frozenset({"succeeded", "failed", "cancelled"})


def _condition(text: str, ctx: RunContext) -> bool:
    """Evaluate a boolean condition at this instant (fail-safe, design §6)."""
    value = evaluate(parse_expression(text), ctx.state, ctx.clock.now())
    if not isinstance(value, bool):
        raise EvaluationError(f"condition {text!r} evaluated to non-boolean {value!r}")
    return value


def _resolve_params(
    block: B.Command | B.Measure, trait: Trait, ctx: RunContext
) -> dict[str, Any]:
    """Resolve expression slots at dispatch time; string-kind slots stay opaque
    (Increment-3 carry-forward)."""
    specs = {spec.name: spec for spec in trait.params}
    now = ctx.clock.now()
    resolved: dict[str, Any] = {}
    for name, value in block.params.items():
        spec = specs[name]  # unknown params cannot survive validation (D6)
        if spec.kind == "string":
            resolved[name] = value
        else:
            resolved[name] = _check_kind(resolve(value, ctx.state, now), spec)
    return resolved


def _check_kind(value: Value, spec: ParamSpec) -> Value:
    """Runtime kind check: bool never numeric; int slots coerce integral floats."""
    if spec.kind == "bool":
        if not isinstance(value, bool):
            raise EvaluationError(f"param {spec.name!r} requires a bool, got {value!r}")
        return value
    if isinstance(value, bool):
        raise EvaluationError(f"param {spec.name!r} requires a {spec.kind}, got a boolean")
    if spec.kind == "int":
        if isinstance(value, int):
            return value
        if isinstance(value, float) and value.is_integer():
            return int(value)
        raise EvaluationError(f"param {spec.name!r} requires an integer, got {value!r}")
    return value  # kind "number": int | float


async def _call_verb(device: Any, verb: str, params: dict[str, Any]) -> Any:
    method: Callable[..., Awaitable[Any]] = getattr(device, verb)
    return await method(**params)


async def _await_job(job: Job, device_id: str, ctx: RunContext) -> Any:
    """Clock-driven poll to terminal, then delegate interpretation to job.result()
    (terminal-state result() neither polls nor sleeps). Design 4-exec §6."""
    opts = ctx.options
    deadline = None if opts.job_timeout is None else ctx.clock.now() + opts.job_timeout
    interval = opts.job_poll_interval
    while job.state not in _TERMINAL:
        async with ctx.lock(device_id):
            await job.refresh()
        if job.state in _TERMINAL:
            break
        if deadline is not None and ctx.clock.now() >= deadline:
            # NOT untracked: the finalizer must stop this device (design §7 step 6).
            raise core_errors.JobTimeoutError(
                f"job {job.job_id} did not finish within {opts.job_timeout}s"
            )
        await ctx.clock.sleep(interval)
        interval = min(interval * 2, opts.job_poll_max)
    ctx.in_flight.pop(job.job_id, None)  # terminal: hardware is done with it
    return await job.result()


async def _run_action(block: B.Command | B.Measure, ctx: RunContext) -> Any:
    """The dispatch pipeline (design 4-exec §7): resolve -> classify -> occupy ->
    invoke -> complete. The occupancy check-and-mark is synchronous (no interleave
    window); the wire lock spans exactly one HTTP call (D2)."""
    trait = lookup(block.device, block.verb)
    params = _resolve_params(block, trait, ctx)
    action = mode_action(block.device, block.verb, params)  # on RESOLVED values (D7)
    closes = action.mode_verb if action is not None and action.kind == "close" else None
    block_id = str(block.id)
    ctx.touched.setdefault(block.device)
    try:
        ctx.occupancy.acquire(block.device, trait.channels, block_id, closes=closes)
    except InvariantViolationError as exc:
        ctx.emit("invariant_violation", block.id, error=str(exc))
        raise
    holding = True
    try:
        device = ctx.device(block.device)
        try:
            async with ctx.lock(block.device):
                result = await _call_verb(device, block.verb, params)
        except core_errors.BusyError as exc:
            ctx.emit("invariant_violation", block.id, error=str(exc))
            raise InvariantViolationError(
                f"hardware reported busy for a statically-proven-free dispatch: {exc}"
            ) from exc
        if trait.completion == "job":
            job: Job = result
            ctx.in_flight[job.job_id] = (block.device, job)
            result = await _await_job(job, block.device, ctx)
        if action is not None and action.kind == "open":
            assert trait.teardown is not None  # every mode entry declares its teardown
            ctx.occupancy.register_open(
                OpenMode(
                    device=block.device,
                    mode_verb=action.mode_verb,
                    teardown_verb=trait.teardown.verb,
                    teardown_params=dict(trait.teardown.params),
                    channels=trait.channels,
                    block_id=block_id,
                )
            )
            holding = False  # slots now belong to the mode, not this block
            ctx.emit("mode_opened", block.id, device=block.device, verb=action.mode_verb)
        elif action is not None and action.kind == "close":
            if ctx.occupancy.register_close(block.device, action.mode_verb) is not None:
                ctx.emit("mode_closed", block.id, device=block.device, verb=action.mode_verb)
        return result
    finally:
        if holding:
            ctx.occupancy.release(block.device, trait.channels, block_id)
```

- [ ] **Step 4: Run test to verify it passes** — `.venv/bin/python -m pytest tests/test_experiment_dispatch.py -v` → 13 passed

- [ ] **Step 5: Full gate**

- [ ] **Step 6: Commit**

```bash
git add src/lab_devices/experiment/execute.py tests/test_experiment_dispatch.py
git commit -m "feat(experiment): action dispatch pipeline with occupancy + clock-driven job polling"
```

---

### Task 10: Block walker (Serial/Wait/gaps, error funnel) + Measure + OperatorInput

**Files:**
- Modify: `src/lab_devices/experiment/execute.py` (append)
- Test: `tests/test_experiment_walker.py` (create)

**Interfaces:**
- Produces (used by Task 11+, plan 4b, and `run.py`):
  - `execute_blocks(blocks: list[Block], ctx: RunContext) -> None` — serial order; `gap_after` honored **unconditionally** (spec §9: the "next start" is transitive — e.g. a loop's next iteration).
  - `execute_block(block: Block, ctx: RunContext) -> None` — pause-gate wait; `block_started`/`block_finished`/`block_failed` events (failure events exactly once, at the origin frame); wraps unrecognized `Exception`s into `BlockFailedError`; `BlockFailedError`/`InvariantViolationError`/`BaseExceptionGroup` propagate unwrapped.
  - `_run_measure`, `_run_operator_input` (internal); `_run_parallel` stub raising `NotImplementedError` (plan 4b replaces it).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_experiment_walker.py
import pytest

from lab_devices.experiment.context import RunContext, RunOptions
from lab_devices.experiment.errors import BlockFailedError
from lab_devices.experiment.execute import execute_blocks
from lab_devices.experiment.state import RunState, Stream
from tests.experiment_run_helpers import (
    ScriptedInputProvider,
    add_standard_devices,
    make_workflow,
    verbs,
)
from tests.fakeclock import FakeClock, drive


def make_ctx(client, workflow, *, clock=None, inputs=None):
    options = RunOptions(clock=clock or FakeClock())
    if inputs is not None:
        options.input_provider = inputs
    state = RunState()
    for name in workflow.streams:
        state.streams[name] = Stream()
    return RunContext(client=client, workflow=workflow, state=state, options=options)


async def run_blocks(ctx):
    await drive(ctx.clock, execute_blocks(ctx.workflow.blocks, ctx))


def kinds(ctx):
    return [(e.kind, e.block_id) for e in ctx.options.log_sink.events]


async def test_serial_order_and_gap_after(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    wf = make_workflow([
        {"command": {"device": "valve_1", "verb": "home", "params": {"position": 1}},
         "gap_after": "30s"},
        {"command": {"device": "pump_1", "verb": "stop"}},
    ])
    ctx = make_ctx(client, wf)
    await run_blocks(ctx)
    assert verbs(fake) == [("valve_1", "home"), ("pump_1", "stop")]
    assert ctx.clock.now() == pytest.approx(30.0)  # the gap really slept


async def test_trailing_gap_is_honored(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    wf = make_workflow([
        {"command": {"device": "pump_1", "verb": "stop"}, "gap_after": "10s"},
    ])
    ctx = make_ctx(client, wf)
    await run_blocks(ctx)
    assert ctx.clock.now() == pytest.approx(10.0)  # spec §9: honored unconditionally


async def test_wait_block_sleeps(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    wf = make_workflow([{"wait": {"duration": "5min"}}])
    ctx = make_ctx(client, wf)
    await run_blocks(ctx)
    assert ctx.clock.now() == pytest.approx(300.0)


async def test_block_events_wrap_execution(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    wf = make_workflow([{"command": {"device": "pump_1", "verb": "stop"}}])
    ctx = make_ctx(client, wf)
    await run_blocks(ctx)
    assert kinds(ctx) == [
        ("block_started", "blocks[0]"), ("block_finished", "blocks[0]"),
    ]


async def test_failure_wrapped_once_with_origin_id(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    wf = make_workflow(
        [{"serial": {"children": [
            {"command": {"device": "pump_1", "verb": "dispense",
                         "params": {"volume_ml": "mean(OD)"}}},
        ]}}],
        streams={"OD": {}},
    )
    ctx = make_ctx(client, wf)
    with pytest.raises(BlockFailedError) as info:
        await run_blocks(ctx)
    assert info.value.block_id == "blocks[0].children[0]"
    failed = [e for e in ctx.options.log_sink.events if e.kind == "block_failed"]
    assert len(failed) == 1 and failed[0].block_id == "blocks[0].children[0]"
    assert fake.calls == []  # fail-safe: nothing hit the wire


async def test_serial_stops_at_first_failure(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    fake.fail_jobs.add("dispense")
    wf = make_workflow([
        {"command": {"device": "pump_1", "verb": "dispense", "params": {"volume_ml": 1.0}}},
        {"command": {"device": "pump_2", "verb": "stop"}},
    ])
    ctx = make_ctx(client, wf)
    with pytest.raises(BlockFailedError):
        await run_blocks(ctx)
    assert verbs(fake) == [("pump_1", "dispense")]  # second block never dispatched


async def test_measure_stamps_stream_with_clock_time(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    wf = make_workflow(
        [{"wait": {"duration": "10s"}},
         {"measure": {"device": "densitometer_1", "verb": "measure", "into": "OD"}}],
        streams={"OD": {"units": "AU"}},
    )
    ctx = make_ctx(client, wf)
    await run_blocks(ctx)
    samples = ctx.state.streams["OD"].samples
    assert len(samples) == 1
    assert samples[0].value == pytest.approx(0.523)  # FakeLab canned absorbance
    assert samples[0].timestamp == pytest.approx(10.0)
    recorded = [e for e in ctx.options.log_sink.events if e.kind == "measure_recorded"]
    assert recorded[0].data["stream"] == "OD"


async def test_measure_blank_uses_slope_result_field(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    wf = make_workflow(
        [{"measure": {"device": "densitometer_1", "verb": "measure_blank", "into": "S"}}],
        streams={"S": {}},
    )
    ctx = make_ctx(client, wf)
    await run_blocks(ctx)
    assert ctx.state.streams["S"].samples[0].value == pytest.approx(123.45)


async def test_operator_input_binds_scripted_value(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    wf = make_workflow([
        {"operator_input": {"name": "target", "type": "float", "min": 0.0, "max": 2.0}},
    ])
    provider = ScriptedInputProvider({"target": 1.5})
    ctx = make_ctx(client, wf, inputs=provider)
    await run_blocks(ctx)
    assert ctx.state.bindings == {"target": 1.5}
    assert provider.requests[0].block_id == "blocks[0]"
    assert [e.kind for e in ctx.options.log_sink.events if "input" in e.kind] == [
        "input_requested", "input_bound",
    ]


async def test_operator_input_constraint_violation_fails_block(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    wf = make_workflow([
        {"operator_input": {"name": "target", "type": "float", "min": 0.0, "max": 2.0}},
    ])
    ctx = make_ctx(client, wf, inputs=ScriptedInputProvider({"target": 99.0}))
    with pytest.raises(BlockFailedError, match="above max"):
        await run_blocks(ctx)
    assert ctx.state.bindings == {}


async def test_unattended_input_fails_safe(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    wf = make_workflow([
        {"operator_input": {"name": "target", "type": "float"}},
    ])
    ctx = make_ctx(client, wf)  # default UnattendedInputProvider
    with pytest.raises(BlockFailedError, match="no input provider"):
        await run_blocks(ctx)
```

- [ ] **Step 2: Run test to verify it fails** — FAIL: `ImportError: cannot import name 'execute_blocks'`

- [ ] **Step 3: Write minimal implementation** — append to `execute.py` (extend imports with `BlockFailedError`, `parse_duration`, `InputRequest`, `validate_input_value`):

```python
async def execute_blocks(blocks: list[B.Block], ctx: RunContext) -> None:
    """Serial semantics: children in order; gap_after honored unconditionally (§9)."""
    for block in blocks:
        await execute_block(block, ctx)
        if block.gap_after is not None:
            await ctx.clock.sleep(parse_duration(block.gap_after))


async def execute_block(block: B.Block, ctx: RunContext) -> None:
    """One block: pause gate, per-type execution, exactly-once failure events (§7, §10)."""
    await ctx.gate.wait()
    ctx.emit("block_started", block.id)
    try:
        await _execute_inner(block, ctx)
    except (BlockFailedError, InvariantViolationError):
        raise  # the origin frame already emitted its event
    except BaseExceptionGroup:
        raise  # parallel children emitted their own events (plan 4b)
    except Exception as exc:
        ctx.emit("block_failed", block.id, error=str(exc))
        raise BlockFailedError(str(block.id), str(exc)) from exc
    ctx.emit("block_finished", block.id)


async def _execute_inner(block: B.Block, ctx: RunContext) -> None:
    if isinstance(block, B.Command):
        await _run_action(block, ctx)
    elif isinstance(block, B.Measure):
        await _run_measure(block, ctx)
    elif isinstance(block, B.OperatorInput):
        await _run_operator_input(block, ctx)
    elif isinstance(block, B.Wait):
        await ctx.clock.sleep(parse_duration(block.duration))
    elif isinstance(block, B.Serial):
        await execute_blocks(block.children, ctx)
    elif isinstance(block, B.Parallel):
        await _run_parallel(block, ctx)
    elif isinstance(block, B.Loop):
        await _run_loop(block, ctx)
    elif isinstance(block, B.Branch):
        await _run_branch(block, ctx)
    else:
        await execute_blocks(ctx.workflow.groups[block.name].body, ctx)


async def _run_measure(block: B.Measure, ctx: RunContext) -> None:
    """Run the measurement job and stamp (clock.now(), scalar) into the stream (§8)."""
    result = await _run_action(block, ctx)
    field_name = lookup(block.device, block.verb).result_field
    if field_name is None:  # unreachable for validated workflows
        raise EvaluationError(f"verb {block.verb!r} yields no measurement scalar")
    if isinstance(result, dict):
        value = result.get(field_name)
    else:
        value = getattr(result, field_name, None)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise EvaluationError(
            f"measure result field {field_name!r} is missing or non-numeric: {value!r}"
        )
    ctx.state.record(block.into, ctx.clock.now(), float(value))
    ctx.emit("measure_recorded", block.id, stream=block.into, value=float(value))


async def _run_operator_input(block: B.OperatorInput, ctx: RunContext) -> None:
    """Request, validate fail-safe, bind (§8). Only this lane blocks."""
    request = InputRequest(
        name=block.name, type=block.type, prompt=block.prompt,
        min=block.min, max=block.max, choices=block.choices, block_id=str(block.id),
    )
    ctx.emit("input_requested", block.id, name=block.name)
    value = validate_input_value(request, await ctx.inputs.request(request))
    ctx.state.bind(block.name, value)
    ctx.emit("input_bound", block.id, name=block.name, value=value)


async def _run_loop(block: B.Loop, ctx: RunContext) -> None:
    raise NotImplementedError  # Task 11


async def _run_branch(block: B.Branch, ctx: RunContext) -> None:
    raise NotImplementedError  # Task 11


async def _run_parallel(block: B.Parallel, ctx: RunContext) -> None:
    raise NotImplementedError("Parallel execution lands in plan 4b")
```

- [ ] **Step 4: Run test to verify it passes** — 12 passed

- [ ] **Step 5: Full gate**

- [ ] **Step 6: Commit**

```bash
git add src/lab_devices/experiment/execute.py tests/test_experiment_walker.py
git commit -m "feat(experiment): block walker with error funnel, Measure, OperatorInput"
```

---

### Task 11: Loop, Branch, GroupRef

**Files:**
- Modify: `src/lab_devices/experiment/execute.py` (replace the two `NotImplementedError` stubs of `_run_loop`/`_run_branch`; GroupRef already routes through `_execute_inner`)
- Test: `tests/test_experiment_loop_branch.py` (create)

**Interfaces:**
- Consumes: Task 9–10 internals.
- Produces: full loop semantics (spec §9): count mode; until pre/post-test; `pace` floor from iteration start in both modes, never cancels an overrunning body, no trailing pace-sleep; gate re-checked at iteration top. Branch then/else. GroupRef inline execution.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_experiment_loop_branch.py
import pytest

from lab_devices.experiment.context import RunContext, RunOptions
from lab_devices.experiment.errors import BlockFailedError
from lab_devices.experiment.execute import execute_blocks
from lab_devices.experiment.state import RunState, Stream
from tests.experiment_run_helpers import add_standard_devices, make_workflow, verbs
from tests.fakeclock import FakeClock, drive


def make_ctx(client, workflow, *, clock=None):
    state = RunState()
    for name in workflow.streams:
        state.streams[name] = Stream()
    return RunContext(client=client, workflow=workflow, state=state,
                      options=RunOptions(clock=clock or FakeClock()))


async def run_blocks(ctx):
    await drive(ctx.clock, execute_blocks(ctx.workflow.blocks, ctx))


STOP = {"command": {"device": "pump_1", "verb": "stop"}}


async def test_count_loop_runs_n_times(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    wf = make_workflow([{"loop": {"count": 3, "body": [STOP]}}])
    ctx = make_ctx(client, wf)
    await run_blocks(ctx)
    assert verbs(fake) == [("pump_1", "stop")] * 3


async def test_count_loop_pace_is_a_floor(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    wf = make_workflow([{"loop": {"count": 3, "pace": "60s", "body": [STOP]}}])
    ctx = make_ctx(client, wf)
    await run_blocks(ctx)
    # body is instant; two inter-iteration paces, no trailing pace after the last
    assert ctx.clock.now() == pytest.approx(120.0)


async def test_pace_never_cancels_overrunning_body(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    wf = make_workflow([
        {"loop": {"count": 2, "pace": "5s",
                  "body": [{"wait": {"duration": "30s"}}, STOP]}},
    ])
    ctx = make_ctx(client, wf)
    await run_blocks(ctx)
    assert len(verbs(fake)) == 2
    assert ctx.clock.now() == pytest.approx(60.0)  # overrun: next starts immediately


async def test_post_test_until_runs_body_then_checks(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    wf = make_workflow(
        [{"loop": {"check": "after", "until": "count(OD) >= 2",
                   "body": [{"measure": {"device": "densitometer_1", "verb": "measure",
                                         "into": "OD"}}]}}],
        streams={"OD": {}},
    )
    ctx = make_ctx(client, wf)
    await run_blocks(ctx)
    assert len(ctx.state.streams["OD"]) == 2  # >=1 iteration guaranteed; exits at 2


async def test_pre_test_until_can_run_zero_iterations(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    wf = make_workflow(
        [{"loop": {"check": "before", "until": "count(OD) >= 0", "body": [STOP]}}],
        streams={"OD": {}},
    )
    ctx = make_ctx(client, wf)
    await run_blocks(ctx)
    assert fake.calls == []  # already true: check-then-act skipped the body


async def test_pre_test_cold_start_fails_safe(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    wf = make_workflow(
        [{"loop": {"check": "before", "until": "mean(OD) >= 1.0", "body": [STOP]}}],
        streams={"OD": {}},
    )
    # NOTE: built via make_workflow (loader), not load_and_validate — the validator
    # would reject this cold-start read; the runtime backstop is what we pin here.
    ctx = make_ctx(client, wf)
    with pytest.raises(BlockFailedError, match="empty stream window"):
        await run_blocks(ctx)
    assert fake.calls == []


async def test_loop_body_gap_paces_iterations(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    # §15.2 pattern: gap_after on the LAST body child must pace iterations (spec §9)
    wf = make_workflow(
        [{"loop": {"count": 2, "body": [
            dict(STOP, gap_after="30s"),
        ]}}],
    )
    ctx = make_ctx(client, wf)
    await run_blocks(ctx)
    assert ctx.clock.now() == pytest.approx(60.0)  # gap after BOTH iterations


async def test_branch_then_else(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    wf = make_workflow(
        [{"branch": {"if": "count(OD) == 0",
                     "then": [{"command": {"device": "valve_1", "verb": "home",
                                           "params": {"position": 1}}}],
                     "else": [STOP]}},
         {"branch": {"if": "count(OD) > 0", "then": [STOP]}}],  # false, no else: skip
        streams={"OD": {}},
    )
    ctx = make_ctx(client, wf)
    await run_blocks(ctx)
    assert verbs(fake) == [("valve_1", "home")]


async def test_group_ref_executes_body_inline(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    wf = make_workflow(
        [{"group_ref": {"name": "prime"}}, {"group_ref": {"name": "prime"}}],
        groups={"prime": {"body": [STOP]}},
    )
    ctx = make_ctx(client, wf)
    await run_blocks(ctx)
    assert verbs(fake) == [("pump_1", "stop")] * 2
```

- [ ] **Step 2: Run test to verify it fails** — FAIL: `NotImplementedError`

- [ ] **Step 3: Write minimal implementation** — replace the two stubs in `execute.py`:

```python
async def _run_loop(block: B.Loop, ctx: RunContext) -> None:
    """Loop semantics per design §8/§9: post-test default, pace is a floor from
    iteration start (both modes), no trailing pace, gate re-checked per iteration."""
    pace = parse_duration(block.pace) if block.pace is not None else None
    iterations = 0
    while True:
        await ctx.gate.wait()  # quiesce point at each iteration top (design §10)
        if block.until is not None and block.check == "before" and _condition(block.until, ctx):
            break
        started = ctx.clock.now()
        await execute_blocks(block.body, ctx)
        iterations += 1
        if block.until is not None and block.check == "after" and _condition(block.until, ctx):
            break
        if block.count is not None and iterations >= block.count:
            break
        if pace is not None:
            remaining = pace - (ctx.clock.now() - started)
            if remaining > 0:
                await ctx.clock.sleep(remaining)  # floor, not deadline (design §8)


async def _run_branch(block: B.Branch, ctx: RunContext) -> None:
    if _condition(block.if_, ctx):
        await execute_blocks(block.then, ctx)
    elif block.else_ is not None:
        await execute_blocks(block.else_, ctx)
```

- [ ] **Step 4: Run test to verify it passes** — 9 passed

- [ ] **Step 5: Full gate**

- [ ] **Step 6: Commit**

```bash
git add src/lab_devices/experiment/execute.py tests/test_experiment_loop_branch.py
git commit -m "feat(experiment): loop (count/pace/until), branch, group execution"
```

---

### Task 12: Finalizer

**Files:**
- Create: `src/lab_devices/experiment/finalize.py`
- Test: `tests/test_experiment_finalize.py` (create)

**Interfaces:**
- Consumes: `RunContext`, `device_type` (registry), device handles.
- Produces: `run_finalizer(ctx: RunContext) -> list[BaseException]` — fixed order (§11): (1) `stop` per device holding a live in-flight job (deduped, insertion order); (2) open-mode teardowns LIFO, deregistering on success; (3) sweep over `ctx.touched` insertion order — pump/valve: `stop`; densitometer: `stop`, `stop_monitoring`, `set_led(level=0)`, `set_thermostat(enabled=False)`. Every step individually caught (including `CancelledError`); errors collected + `finalize_step_failed` events; NEVER skips remaining steps. Events: `finalize_started`, `job_cancelled`, `teardown_issued`, `sweep_command`, `finalize_step_failed`, `finalize_finished`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_experiment_finalize.py
import pytest

from lab_devices.experiment.context import RunContext, RunOptions
from lab_devices.experiment.execute import _run_action, execute_blocks
from lab_devices.experiment.finalize import run_finalizer
from lab_devices.experiment.state import RunState
from tests.experiment_run_helpers import add_standard_devices, make_workflow, verbs
from tests.fakeclock import FakeClock, drive


def make_ctx(client, workflow=None, *, clock=None):
    wf = workflow if workflow is not None else make_workflow([])
    return RunContext(client=client, workflow=wf, state=RunState(),
                      options=RunOptions(clock=clock or FakeClock()))


async def test_untouched_run_sweeps_nothing(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    ctx = make_ctx(client)
    errors = await run_finalizer(ctx)
    assert errors == [] and fake.calls == []
    assert [e.kind for e in ctx.options.log_sink.events] == [
        "finalize_started", "finalize_finished",
    ]


async def test_fixed_order_jobs_modes_sweep(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    ctx = make_ctx(client)
    from lab_devices.experiment import blocks as B

    # open a rotate mode on pump_2, thermostat on densitometer_1, then hold a job on pump_1
    await _run_action(B.Command(device="pump_2", verb="rotate",
                                params={"direction": "forward", "speed_ml_min": 2.0},
                                id="b0"), ctx)
    await _run_action(B.Command(device="densitometer_1", verb="set_thermostat",
                                params={"enabled": True, "target_c": 37.0}, id="b1"), ctx)
    fake.hold_job("dispense")
    device = ctx.device("pump_1")
    job = await device.dispense(volume_ml=1.0)  # started outside _run_action on purpose
    ctx.in_flight[job.job_id] = ("pump_1", job)
    ctx.touched.setdefault("pump_1")
    fake.calls.clear()

    errors = await run_finalizer(ctx)
    assert errors == []
    assert verbs(fake) == [
        ("pump_1", "stop"),                     # 1: cancel in-flight job
        ("densitometer_1", "set_thermostat"),   # 2: teardowns LIFO (thermostat opened last)
        ("pump_2", "stop"),
        ("pump_2", "stop"),                     # 3: sweep in touched order (pump_2 first)
        ("densitometer_1", "stop"),
        ("densitometer_1", "stop_monitoring"),
        ("densitometer_1", "set_led"),
        ("densitometer_1", "set_thermostat"),
        ("pump_1", "stop"),
    ]
    # teardown params are the registry literals
    teardown_call = fake.calls[1]
    assert teardown_call[2] == {"enabled": False}
    sweep_led = [c for c in fake.calls if c[1] == "set_led"]
    assert sweep_led[0][2] == {"level": 0}
    assert ctx.occupancy.open_modes() == ()  # deregistered on successful teardown


async def test_best_effort_never_skips_sweep(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    ctx = make_ctx(client)
    from lab_devices.experiment import blocks as B

    await _run_action(B.Command(device="pump_2", verb="rotate",
                                params={"direction": "forward", "speed_ml_min": 2.0},
                                id="b0"), ctx)
    ctx.touched.setdefault("densitometer_1")
    fake.calls.clear()
    fake.inject_error("pump_2", "stop", "hardware_error", "stall")   # teardown fails
    fake.inject_error("densitometer_1", "stop", "hardware_error", "x")  # 1st sweep verb fails

    errors = await run_finalizer(ctx)
    # teardown pump_2 stop fails (1); sweep pump_2 stop succeeds (queue drained);
    # sweep densitometer stop fails (2); remaining densitometer verbs still issued
    assert len(errors) == 2
    assert verbs(fake) == [
        ("pump_2", "stop"),                    # teardown attempt (fails)
        ("pump_2", "stop"),                    # sweep (succeeds)
        ("densitometer_1", "stop"),            # sweep (fails)
        ("densitometer_1", "stop_monitoring"),  # sweep continues past the failure
        ("densitometer_1", "set_led"),
        ("densitometer_1", "set_thermostat"),
    ]
    failed = [e.kind for e in ctx.options.log_sink.events if e.kind == "finalize_step_failed"]
    assert len(failed) == 2
    assert len(ctx.occupancy.open_modes()) == 1  # failed teardown stays registered


async def test_finalizer_after_real_failed_run(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    fake.fail_jobs.add("dispense")
    wf = make_workflow([
        {"command": {"device": "pump_2", "verb": "rotate",
                     "params": {"direction": "forward", "speed_ml_min": 2.0}}},
        {"command": {"device": "pump_1", "verb": "dispense", "params": {"volume_ml": 1.0}}},
    ])
    ctx = make_ctx(client, wf)
    from lab_devices.experiment.errors import BlockFailedError

    with pytest.raises(BlockFailedError):
        await drive(ctx.clock, execute_blocks(wf.blocks, ctx))
    errors = await run_finalizer(ctx)
    assert errors == []
    assert ctx.in_flight == {}  # failed job reached terminal state -> untracked
    # calls 0-1 are the run itself (rotate, dispense); then the finalizer:
    assert verbs(fake)[2:] == [
        ("pump_2", "stop"),  # teardown of the still-open rotate
        ("pump_2", "stop"),  # sweep pump_2 (touched first)
        ("pump_1", "stop"),  # sweep pump_1; densitometer never touched -> not swept
    ]
```

- [ ] **Step 2: Run test to verify it fails** — FAIL: `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation** — `src/lab_devices/experiment/finalize.py`:

```python
"""Safe-shutdown finalizer: cancel jobs, tear down modes, sweep. See design 4-exec §11."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from lab_devices.experiment.context import RunContext
from lab_devices.experiment.registry import device_type

_SWEEP: dict[str, tuple[tuple[str, dict[str, Any]], ...]] = {
    "pump": (("stop", {}),),
    "valve": (("stop", {}),),
    "densitometer": (
        ("stop", {}),
        ("stop_monitoring", {}),
        ("set_led", {"level": 0}),
        ("set_thermostat", {"enabled": False}),
    ),
}


async def run_finalizer(ctx: RunContext) -> list[BaseException]:
    """Best-effort, fixed-order shutdown; a failed step never skips the rest (§11)."""
    errors: list[BaseException] = []
    ctx.emit("finalize_started")
    # 1. Cancel in-flight jobs: stop each device that still owns a live job.
    for device_id in dict.fromkeys(entry[0] for entry in ctx.in_flight.values()):
        await _issue(ctx, device_id, "stop", {}, "job_cancelled", errors)
    # 2. Tear down open modes, most recently opened first.
    for mode in reversed(ctx.occupancy.open_modes()):
        ok = await _issue(
            ctx, mode.device, mode.teardown_verb, dict(mode.teardown_params),
            "teardown_issued", errors,
        )
        if ok:
            ctx.occupancy.register_close(mode.device, mode.mode_verb)
    # 3. Unconditional idempotent safe-state sweep over every touched device.
    for device_id in ctx.touched:
        for verb, params in _SWEEP.get(device_type(device_id), ()):
            await _issue(ctx, device_id, verb, dict(params), "sweep_command", errors)
    ctx.emit("finalize_finished", errors=len(errors))
    return errors


async def _issue(
    ctx: RunContext,
    device_id: str,
    verb: str,
    params: dict[str, Any],
    kind: str,
    errors: list[BaseException],
) -> bool:
    """One best-effort call; catches everything (incl. CancelledError) by design —
    an abort arriving mid-finalize must not stop the safe-state sweep."""
    try:
        device = ctx.device(device_id)
        method: Callable[..., Awaitable[Any]] = getattr(device, verb)
        async with ctx.lock(device_id):
            await method(**params)
    except BaseException as exc:
        errors.append(exc)
        ctx.emit("finalize_step_failed", device=device_id, verb=verb, error=str(exc))
        return False
    ctx.emit(kind, device=device_id, verb=verb)
    return True
```

- [ ] **Step 4: Run test to verify it passes** — `.venv/bin/python -m pytest tests/test_experiment_finalize.py -v` → 4 passed

- [ ] **Step 5: Full gate**

- [ ] **Step 6: Commit**

```bash
git add src/lab_devices/experiment/finalize.py tests/test_experiment_finalize.py
git commit -m "feat(experiment): best-effort fixed-order finalizer"
```

---

### Task 13: `ExperimentRun` facade + `RunReport` + public exports

**Files:**
- Modify: `src/lab_devices/experiment/run.py` (extend Task 2's module)
- Modify: `src/lab_devices/experiment/__init__.py`
- Test: `tests/test_experiment_run_facade.py` (create)

**Interfaces:**
- Produces:
  - `RunReport` — dataclass: `status: str` (`"completed" | "failed" | "aborted"`), `error: BaseException | None`, `finalize_errors: tuple[BaseException, ...]`, `state: RunState`, `log: RunLogSink`.
  - `ExperimentRun(client, workflow, options=None)` — `validate(workflow)` at construction (D6, raises `ValidationError`); `assign_block_ids`; builds `RunContext` with pre-created streams.
  - `await execute() -> RunReport` — single-shot; rejects non-`in_memory` persistence (D4) before `run_started`, setting `report` then raising `UnsupportedPersistenceError`; captures ALL exceptions from `execute_blocks`, runs the finalizer on every path, then: completed → return report (or raise `FinalizeError` per D8); failed → re-raise primary error with finalizer errors as `add_note`s; `CancelledError` → status `"aborted"`, re-raised (operator-abort mapping to `RunAbortedError` lands in plan 4b Task 3 — external cancellation is the only cancel source in 4a).
  - `pause()/resume()` — gate flip + `paused`/`resumed` events (behavioral tests in plan 4b).
  - `__init__.py` exports: `ExperimentRun`, `RunOptions`, `RunReport`, `assign_block_ids`, `Clock`, `MonotonicClock`, `OperatorInputProvider`, `InputRequest`, `UnattendedInputProvider`, `RunEvent`, `RunLogSink`, `InMemoryRunLog`, `ExperimentRunError`, `BlockFailedError`, `InvariantViolationError`, `RunAbortedError`, `FinalizeError`, `UnsupportedPersistenceError`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_experiment_run_facade.py
import asyncio

import pytest

from lab_devices.experiment import (
    BlockFailedError,
    ExperimentRun,
    FinalizeError,
    InMemoryRunLog,
    RunOptions,
    UnsupportedPersistenceError,
    ValidationError,
)
from lab_devices.experiment.errors import ExperimentRunError
from tests.experiment_run_helpers import add_standard_devices, make_workflow, verbs
from tests.fakeclock import FakeClock, drive


def make_run(client, workflow, **opt):
    options = RunOptions(clock=opt.pop("clock", FakeClock()), **opt)
    return ExperimentRun(client, workflow, options=options)


async def test_happy_path_report(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    wf = make_workflow(
        [{"measure": {"device": "densitometer_1", "verb": "measure", "into": "OD"}}],
        streams={"OD": {"units": "AU"}},
    )
    run = make_run(client, wf)
    report = await drive(run._options.clock, run.execute())
    assert report.status == "completed" and report.error is None
    assert report.finalize_errors == ()
    assert len(report.state.streams["OD"]) == 1
    assert run.report is report
    kinds = [e.kind for e in report.log.events]
    assert kinds[0] == "run_started" and kinds[-1] == "run_finished"


async def test_validates_at_construction(fake_client):
    _, client = fake_client
    wf = make_workflow(
        [{"measure": {"device": "densitometer_1", "verb": "measure", "into": "ghost"}}]
    )  # undeclared stream -> validator rejects
    with pytest.raises(ValidationError):
        ExperimentRun(client, wf)


async def test_declared_streams_pre_created(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    wf = make_workflow(
        [{"branch": {"if": "count(S) == 0",
                     "then": [{"command": {"device": "pump_1", "verb": "stop"}}]}}],
        streams={"S": {}},
    )
    run = make_run(client, wf)
    report = await drive(run._options.clock, run.execute())
    assert report.status == "completed"
    assert verbs(fake)[0] == ("pump_1", "stop")  # count()==0 on a never-written stream


async def test_disk_persistence_rejected_before_hardware(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    wf = make_workflow(
        [{"command": {"device": "pump_1", "verb": "stop"}}],
        persistence={"default": "disk", "format": "jsonl"},
    )
    run = make_run(client, wf)
    with pytest.raises(UnsupportedPersistenceError, match="Increment 5"):
        await run.execute()
    assert fake.calls == []  # nothing touched the wire
    assert run.report is not None and run.report.status == "failed"


async def test_per_stream_disk_override_rejected(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    wf = make_workflow(
        [{"measure": {"device": "densitometer_1", "verb": "measure", "into": "OD"}}],
        streams={"OD": {"persistence": "disk"}},
    )
    run = make_run(client, wf)
    with pytest.raises(UnsupportedPersistenceError):
        await run.execute()


async def test_block_failure_finalizes_and_reraises_with_notes(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    fake.fail_jobs.add("dispense")
    wf = make_workflow([
        {"command": {"device": "pump_2", "verb": "rotate",
                     "params": {"direction": "forward", "speed_ml_min": 2.0}}},
        {"command": {"device": "pump_1", "verb": "dispense", "params": {"volume_ml": 1.0}}},
    ])
    run = make_run(client, wf)
    with pytest.raises(BlockFailedError):
        await drive(run._options.clock, run.execute())
    assert run.report.status == "failed"
    assert ("pump_2", "stop") in verbs(fake)  # rotate torn down by the finalizer


async def test_finalize_error_on_otherwise_successful_run(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    wf = make_workflow([
        {"command": {"device": "pump_2", "verb": "rotate",
                     "params": {"direction": "forward", "speed_ml_min": 2.0}}},
    ])  # rotate left open: finalizer will close it
    fake.inject_error("pump_2", "stop", "hardware_error", "stall", times=2)  # teardown+sweep
    run = make_run(client, wf)
    with pytest.raises(FinalizeError) as info:
        await drive(run._options.clock, run.execute())
    assert len(info.value.errors) == 2
    assert run.report.status == "completed"  # block plane succeeded (D8)
    assert run.report.finalize_errors == info.value.errors


async def test_execute_is_single_shot(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    wf = make_workflow([{"command": {"device": "pump_1", "verb": "stop"}}])
    run = make_run(client, wf)
    await drive(run._options.clock, run.execute())
    with pytest.raises(ExperimentRunError, match="once"):
        await run.execute()


async def test_external_cancellation_finalizes_and_reraises(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    fake.hold_job("dispense")
    wf = make_workflow([
        {"command": {"device": "pump_2", "verb": "rotate",
                     "params": {"direction": "forward", "speed_ml_min": 2.0}}},
        {"command": {"device": "pump_1", "verb": "dispense", "params": {"volume_ml": 1.0}}},
    ])
    run = make_run(client, wf)
    clock = run._options.clock
    task = asyncio.ensure_future(run.execute())
    await clock.settle()
    task.cancel()  # external cancel, NOT operator abort
    with pytest.raises(asyncio.CancelledError):
        await task
    assert run.report.status == "aborted"
    seq = verbs(fake)
    assert ("pump_1", "stop") in seq  # in-flight job device stopped (step 1)
    assert seq.count(("pump_2", "stop")) >= 1  # rotate torn down


def test_public_exports():
    import lab_devices.experiment as exp

    for name in (
        "ExperimentRun", "RunOptions", "RunReport", "assign_block_ids",
        "Clock", "MonotonicClock", "OperatorInputProvider", "InputRequest",
        "UnattendedInputProvider", "RunEvent", "RunLogSink", "InMemoryRunLog",
        "ExperimentRunError", "BlockFailedError", "InvariantViolationError",
        "RunAbortedError", "FinalizeError", "UnsupportedPersistenceError",
    ):
        assert hasattr(exp, name) and name in exp.__all__, name
```

- [ ] **Step 2: Run test to verify it fails** — FAIL: `ImportError: cannot import name 'ExperimentRun'`

- [ ] **Step 3: Write minimal implementation** — extend `src/lab_devices/experiment/run.py` to:

```python
"""Public run facade: validation gate, lifecycle, outcome reporting.
See design 4-exec §3, §10-12."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from lab_devices.client import LabClient
from lab_devices.experiment import blocks as B
from lab_devices.experiment.context import RunContext, RunOptions
from lab_devices.experiment.errors import (
    ExperimentRunError,
    FinalizeError,
    RunAbortedError,
    UnsupportedPersistenceError,
)
from lab_devices.experiment.execute import execute_blocks
from lab_devices.experiment.finalize import run_finalizer
from lab_devices.experiment.runlog import RunLogSink
from lab_devices.experiment.state import RunState, Stream
from lab_devices.experiment.validate import validate
from lab_devices.experiment.workflow import Workflow


def assign_block_ids(workflow: Workflow) -> None:
    """Engine-assigned structural ids matching validator diagnostic paths (4-exec §13)."""

    def walk(blocks: list[B.Block], prefix: str) -> None:
        for i, block in enumerate(blocks):
            path = f"{prefix}[{i}]"
            block.id = path
            if isinstance(block, (B.Serial, B.Parallel)):
                walk(block.children, f"{path}.children")
            elif isinstance(block, B.Loop):
                walk(block.body, f"{path}.body")
            elif isinstance(block, B.Branch):
                walk(block.then, f"{path}.then")
                if block.else_ is not None:
                    walk(block.else_, f"{path}.else")

    walk(workflow.blocks, "blocks")
    for name, group in workflow.groups.items():
        walk(group.body, f"groups[{name!r}].body")


@dataclass
class RunReport:
    """Outcome of one execution (design 4-exec §12); set before execute() raises."""

    status: str  # "completed" | "failed" | "aborted"
    error: BaseException | None
    finalize_errors: tuple[BaseException, ...]
    state: RunState
    log: RunLogSink


class ExperimentRun:
    """One workflow execution: validates at construction (D6), single-shot execute()."""

    def __init__(
        self, client: LabClient, workflow: Workflow, options: RunOptions | None = None
    ) -> None:
        validate(workflow)  # the runtime's safety model IS the static proof (D6)
        assign_block_ids(workflow)
        self._workflow = workflow
        self._options = options or RunOptions()
        state = RunState()
        for stream_name in workflow.streams:
            state.streams[stream_name] = Stream()  # pre-created: count()==0 (§3)
        self._ctx = RunContext(
            client=client, workflow=workflow, state=state, options=self._options
        )
        self._task: asyncio.Task[object] | None = None
        self._started = False
        self._finalizing = False
        self.report: RunReport | None = None

    # ---- control plane (design §10; behavioral tests in plan 4b) ----
    def pause(self) -> None:
        """Quiesce dispatch: in-flight jobs finish, open modes keep running."""
        if not self._ctx.gate.is_set():
            return
        self._ctx.gate.clear()
        if self._started:
            self._ctx.emit("paused")

    def resume(self) -> None:
        if self._ctx.gate.is_set():
            return
        self._ctx.gate.set()
        if self._started:
            self._ctx.emit("resumed")

    # ---- lifecycle (design §3, §11-12) ----
    async def execute(self) -> RunReport:
        if self._started:
            raise ExperimentRunError("execute() may only be called once per ExperimentRun")
        self._started = True
        ctx = self._ctx
        try:
            self._reject_unsupported_persistence()
        except UnsupportedPersistenceError as exc:
            self.report = RunReport("failed", exc, (), ctx.state, self._options.log_sink)
            raise
        self._task = asyncio.current_task()
        ctx.emit("run_started")
        error: BaseException | None = None
        try:
            if ctx.abort_requested:
                raise asyncio.CancelledError
            await execute_blocks(self._workflow.blocks, ctx)
        except BaseException as exc:
            error = exc
        self._finalizing = True
        finalize_errors = tuple(await run_finalizer(ctx))
        if error is not None:
            for fin_err in finalize_errors:
                error.add_note(f"finalizer: {fin_err!r}")
        cancelled = isinstance(error, asyncio.CancelledError)
        status = "aborted" if cancelled else ("failed" if error is not None else "completed")
        self.report = RunReport(
            status=status, error=error, finalize_errors=finalize_errors,
            state=ctx.state, log=self._options.log_sink,
        )
        ctx.emit("run_finished", status=status)
        if cancelled:
            if ctx.abort_requested:  # operator abort (wired in plan 4b Task 3)
                if self._task is not None:
                    self._task.uncancel()
                raise RunAbortedError("run aborted by operator") from error
            raise error  # external cancellation must propagate (asyncio correctness)
        if error is not None:
            raise error
        if finalize_errors:
            raise FinalizeError(finalize_errors)  # D8
        return self.report

    def _reject_unsupported_persistence(self) -> None:
        """D4: only in_memory runs this increment; disk sinks land in Increment 5."""
        targets = [("workflow default", self._workflow.persistence.default)]
        targets += [
            (f"stream {name!r}", decl.persistence)
            for name, decl in self._workflow.streams.items()
            if decl.persistence is not None
        ]
        for what, value in targets:
            if value != "in_memory":
                raise UnsupportedPersistenceError(
                    f"{what} requests {value!r} persistence; disk sinks arrive in "
                    "Increment 5 — set 'in_memory' to run this workflow today"
                )
```

In `src/lab_devices/experiment/__init__.py`: add these imports (alphabetical within the existing layout) and extend `__all__`:

```python
from lab_devices.experiment.clock import Clock, MonotonicClock
from lab_devices.experiment.context import RunOptions
from lab_devices.experiment.inputs import (
    InputRequest,
    OperatorInputProvider,
    UnattendedInputProvider,
)
from lab_devices.experiment.run import ExperimentRun, RunReport, assign_block_ids
from lab_devices.experiment.runlog import InMemoryRunLog, RunEvent, RunLogSink
```

Extend the existing `errors` import with: `BlockFailedError`, `ExperimentRunError`, `FinalizeError`, `InvariantViolationError`, `RunAbortedError`, `UnsupportedPersistenceError`.

Append to `__all__` (matching the file's grouped style):

```python
    "ExperimentRun", "RunOptions", "RunReport", "assign_block_ids",
    "Clock", "MonotonicClock",
    "OperatorInputProvider", "InputRequest", "UnattendedInputProvider",
    "RunEvent", "RunLogSink", "InMemoryRunLog",
    "ExperimentRunError", "BlockFailedError", "InvariantViolationError",
    "RunAbortedError", "FinalizeError", "UnsupportedPersistenceError",
```

- [ ] **Step 4: Run test to verify it passes** — 10 passed

- [ ] **Step 5: Full gate**

- [ ] **Step 6: Commit**

```bash
git add src/lab_devices/experiment/run.py src/lab_devices/experiment/__init__.py tests/test_experiment_run_facade.py
git commit -m "feat(experiment): ExperimentRun facade with validation gate and outcome reporting"
```

---

### Task 14: Sequential flagship end-to-end scenarios

**Files:**
- Test: `tests/test_experiment_e2e_sequential.py` (create; no source changes expected — this task EXERCISES the increment, spec §16 flagships 1–5)

**Interfaces:** consumes the public API only (`lab_devices.experiment` exports + helpers).

- [ ] **Step 1: Write the tests** (these should PASS if Tasks 1–13 are correct — any failure here is a real integration bug; investigate, do not weaken the assertions)

```python
# tests/test_experiment_e2e_sequential.py
"""Flagship E2E scenarios (design 4-exec §16 #1-5): call-sequence assertions vs FakeLab."""
import pytest

from lab_devices.experiment import BlockFailedError, ExperimentRun, RunOptions
from tests.experiment_run_helpers import (
    ScriptedInputProvider,
    add_standard_devices,
    make_workflow,
    verbs,
)
from tests.fakeclock import FakeClock, drive


def make_run(client, wf, **opt):
    return ExperimentRun(client, wf, options=RunOptions(clock=FakeClock(), **opt))


async def test_flagship_rotate_measure_feedback(fake_client):
    """§15.2-shaped: prime group, stir throughout, feedback dispense, explicit close,
    close-with-no-open branch, full sweep, zero open modes."""
    fake, client = fake_client
    add_standard_devices(fake)
    wf = make_workflow(
        [{"serial": {"children": [
            {"operator_input": {"name": "target_OD", "type": "float",
                                "prompt": "Enter target OD", "min": 0.0, "max": 2.0}},
            {"group_ref": {"name": "prime_line"}},
            {"command": {"device": "pump_2", "verb": "rotate",
                         "params": {"direction": "forward", "speed_ml_min": 2.0}}},
            {"loop": {"check": "after", "until": "mean(OD, last=5min) >= 0.5",
                      "body": [
                          {"measure": {"device": "densitometer_1", "verb": "measure",
                                       "into": "OD"}},
                          {"command": {"device": "pump_1", "verb": "dispense",
                                       "params": {"volume_ml":
                                                  "2.0 * (target_OD - mean(OD, last=100))",
                                                  "speed_ml_min": 3.0}},
                           "gap_after": "30s"},
                      ]}},
            {"command": {"device": "pump_2", "verb": "stop"}},
            {"branch": {"if": "last(OD) < target_OD",
                        "then": [{"command": {"device": "densitometer_1",
                                              "verb": "set_led",
                                              "params": {"level": 0}}}]}},
        ]}}],
        streams={"OD": {"units": "AU"}},
        groups={"prime_line": {"body": [
            {"command": {"device": "pump_1", "verb": "dispense",
                         "params": {"volume_ml": 1.0, "speed_ml_min": 5.0}}}]}},
    )
    run = make_run(client, wf, input_provider=ScriptedInputProvider({"target_OD": 0.55}))
    report = await drive(run._options.clock, run.execute())

    assert report.status == "completed"
    assert verbs(fake) == [
        ("pump_1", "dispense"),            # prime group
        ("pump_2", "rotate"),              # stir mode opens
        ("densitometer_1", "measure"),     # loop iteration 1 (canned OD 0.523)
        ("pump_1", "dispense"),            # feedback dispense
        ("pump_2", "stop"),                # explicit close of rotate
        ("densitometer_1", "set_led"),     # branch: close-with-no-open (level 0)
        # finalizer sweep over touched devices, insertion order:
        ("pump_1", "stop"),
        ("pump_2", "stop"),
        ("densitometer_1", "stop"),
        ("densitometer_1", "stop_monitoring"),
        ("densitometer_1", "set_led"),
        ("densitometer_1", "set_thermostat"),
    ]
    feedback = [c for c in fake.calls if c[1] == "dispense"][1]
    assert feedback[2]["volume_ml"] == pytest.approx(2.0 * (0.55 - 0.523))
    assert run._ctx.occupancy.open_modes() == ()  # nothing left open
    # the 30s gap paced the loop before the until-check
    assert report.log.events[0].kind == "run_started"


async def test_flagship_midrun_job_failure_full_finalizer(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    fake.fail_jobs.add("dispense")
    wf = make_workflow([
        {"command": {"device": "pump_2", "verb": "rotate",
                     "params": {"direction": "forward", "speed_ml_min": 2.0}}},
        {"loop": {"count": 2, "body": [
            {"measure": {"device": "densitometer_1", "verb": "measure", "into": "OD"}},
            {"command": {"device": "pump_1", "verb": "dispense",
                         "params": {"volume_ml": 1.0}}},
        ]}},
    ], streams={"OD": {}})
    run = make_run(client, wf)
    with pytest.raises(BlockFailedError):
        await drive(run._options.clock, run.execute())
    assert run.report.status == "failed"
    seq = verbs(fake)
    assert seq[:4] == [("pump_2", "rotate"), ("densitometer_1", "measure"),
                       ("pump_1", "dispense"), ("pump_2", "stop")]  # teardown right after
    assert ("densitometer_1", "set_thermostat") in seq  # sweep completed
    assert run._ctx.occupancy.open_modes() == ()


async def test_flagship_failsafe_empty_duration_window(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    wf = make_workflow([
        {"measure": {"device": "densitometer_1", "verb": "measure", "into": "OD"}},
        {"wait": {"duration": "10s"}},
        {"command": {"device": "pump_1", "verb": "dispense",
                     "params": {"volume_ml": "mean(OD, last=1s)"}}},
    ], streams={"OD": {}})
    run = make_run(client, wf)
    with pytest.raises(BlockFailedError, match="empty stream window"):
        await drive(run._options.clock, run.execute())
    assert ("pump_1", "dispense") not in verbs(fake)  # failed before the wire
    assert run.report.status == "failed"
    assert ("densitometer_1", "stop") in verbs(fake)  # finalizer swept touched devices
    assert all(d != "pump_1" for d, _ in verbs(fake))  # pump_1 never touched -> not swept


async def test_flagship_count_zero_on_precreated_stream(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    wf = make_workflow([
        {"branch": {"if": "count(S) == 0",
                    "then": [{"command": {"device": "densitometer_1", "verb": "set_led",
                                          "params": {"level": 5}}}]}},
    ], streams={"S": {}})
    run = make_run(client, wf)
    report = await drive(run._options.clock, run.execute())
    assert report.status == "completed"
    seq = verbs(fake)
    assert seq[0] == ("densitometer_1", "set_led")  # branch taken: count(S)==0
    # set_led(5) opened a mode; the finalizer's teardown AND sweep both set_led(0)
    led_calls = [c for c in fake.calls if c[1] == "set_led"]
    assert [c[2]["level"] for c in led_calls] == [5, 0, 0]
    assert run._ctx.occupancy.open_modes() == ()


async def test_flagship_operator_input_feeds_param(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    wf = make_workflow([
        {"operator_input": {"name": "target", "type": "float", "min": 0.0, "max": 100.0}},
        {"command": {"device": "pump_1", "verb": "dispense",
                     "params": {"volume_ml": "target / 10"}}},
    ])
    run = make_run(client, wf, input_provider=ScriptedInputProvider({"target": 42.0}))
    report = await drive(run._options.clock, run.execute())
    assert report.status == "completed"
    assert fake.calls[0][2]["volume_ml"] == pytest.approx(4.2)
```

- [ ] **Step 2: Run the tests** — `.venv/bin/python -m pytest tests/test_experiment_e2e_sequential.py -v` → 5 passed. If any fails, debug the SOURCE (these assertions encode the spec); do not adjust expected sequences without controller sign-off.

- [ ] **Step 3: Full gate**

- [ ] **Step 4: Commit**

```bash
git add tests/test_experiment_e2e_sequential.py
git commit -m "test(experiment): sequential flagship end-to-end scenarios (spec §16 #1-5)"
```

---

## Plan-level self-review notes (already applied)

- Spec §16 flagships 6–10, Parallel, pause/resume behavior, abort, and the runtime
  occupancy-conflict path under real concurrency are 4b scope (same branch, next plan).
- `test_experiment_dispatch.py` pins all five §7 reviewer invariants; task reviewers should
  additionally trace the code path directly (see the invariant list in Task 9).
- `RunAbortedError` code path exists in `run.py` but is unreachable until 4b wires
  `abort()`; 4b Task 3 owns its tests.
