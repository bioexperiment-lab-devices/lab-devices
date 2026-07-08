# Experiment Orchestrator — Increment 4b: Parallel Concurrency + Pause/Abort Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete Increment 4 on top of plan 4a: `Parallel` execution (TaskGroup + `start_offset`), pause/resume quiesce semantics, operator abort, the runtime invariant-violation safety net under real concurrency, and the concurrent flagship end-to-end scenarios (spec §16 #6–10).

**Architecture:** Same design doc (`docs/superpowers/specs/2026-07-08-experiment-orchestrator-4-executor-design.md`); this plan replaces 4a's `_run_parallel` stub, adds `ExperimentRun.abort()`, and behaviorally proves the gate/finalizer semantics 4a wired. All 4a interfaces are in place — read the 4a plan's Interfaces blocks for exact signatures.

**Tech Stack:** as 4a. `asyncio.TaskGroup` (Python 3.11) for structured concurrency.

## Global Constraints

Identical to plan 4a (interpreter, four-part gate, module conventions, branch `feat/experiment-orchestrator-4-executor`, never commit to main). Suite size at 4b start = 4a's final count — record it when Task 1 begins.

**Adversarial review focus for every task here** (from the increment brief): does the finalizer ALWAYS run and reach the safe-state sweep on every exit path (normal, block error, abort, cancellation)? Are modes always torn down? Does pause leave modes running? Is there any `await` between occupancy check and mark that a sibling task could interleave through?

## Prerequisites

Plan 4a fully landed (Tasks 1–14, gate green). `tests/fakeclock.drive()` accepts a coroutine **or an existing Task** (`asyncio.ensure_future` passes a Task through unchanged) — 4b tests rely on this for start-then-drive patterns.

---

### Task 1: Parallel execution

**Files:**
- Modify: `src/lab_devices/experiment/execute.py` (add `import asyncio`; replace the `_run_parallel` stub; add `_parallel_child`)
- Test: `tests/test_experiment_parallel.py` (create)

**Interfaces:**
- Consumes: 4a walker (`execute_block`, `execute_blocks`), `RunContext`, FakeClock/drive, helpers.
- Produces: `_run_parallel(block: Parallel, ctx) -> None` — one `TaskGroup` task per child; each child sleeps `start_offset` (if set) before `execute_block`; a failing child cancels siblings; the `ExceptionGroup` propagates unflattened through ancestor `execute_block` frames (4a's `BaseExceptionGroup` re-raise branch).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_experiment_parallel.py
import asyncio

import pytest

from lab_devices.experiment.context import RunContext, RunOptions
from lab_devices.experiment.errors import BlockFailedError, InvariantViolationError
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


async def test_children_run_concurrently(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    fake.polls_to_complete_by_cmd["dispense"] = 2  # each job needs one 0.25s poll sleep
    wf = make_workflow([
        {"parallel": {"children": [
            {"command": {"device": "pump_1", "verb": "dispense", "params": {"volume_ml": 1.0}}},
            {"command": {"device": "pump_2", "verb": "dispense", "params": {"volume_ml": 2.0}}},
        ]}},
    ])
    ctx = make_ctx(client, wf)
    await drive(ctx.clock, execute_blocks(wf.blocks, ctx))
    assert sorted(verbs(fake)) == [("pump_1", "dispense"), ("pump_2", "dispense")]
    # concurrent poll sleeps overlap: total elapsed is ONE poll interval, not two
    assert ctx.clock.now() == pytest.approx(0.25)


async def test_start_offset_staggers_branch_start(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    wf = make_workflow([
        {"parallel": {"children": [
            {"command": {"device": "pump_1", "verb": "stop"}},
            {"command": {"device": "pump_2", "verb": "stop"}, "start_offset": "60s"},
        ]}},
    ])
    ctx = make_ctx(client, wf)
    task = asyncio.ensure_future(execute_blocks(wf.blocks, ctx))
    await ctx.clock.settle()
    assert verbs(fake) == [("pump_1", "stop")]  # offset branch not started yet
    await ctx.clock.advance(59.9)
    assert verbs(fake) == [("pump_1", "stop")]
    await ctx.clock.advance(0.2)
    assert verbs(fake) == [("pump_1", "stop"), ("pump_2", "stop")]
    await drive(ctx.clock, task)


async def test_failing_child_cancels_siblings_exception_group(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    fake.fail_jobs.add("dispense")
    wf = make_workflow(
        [{"parallel": {"children": [
            {"command": {"device": "pump_1", "verb": "dispense", "params": {"volume_ml": 1.0}}},
            {"loop": {"count": 999, "body": [
                {"measure": {"device": "densitometer_1", "verb": "measure", "into": "OD"}},
                {"wait": {"duration": "10s"}},
            ]}},
        ]}}],
        streams={"OD": {}},
    )
    ctx = make_ctx(client, wf)
    with pytest.raises(BaseExceptionGroup) as info:
        await drive(ctx.clock, execute_blocks(wf.blocks, ctx))
    leaves = info.value.exceptions
    assert len(leaves) == 1 and isinstance(leaves[0], BlockFailedError)
    assert leaves[0].block_id == "blocks[0].children[0]"
    # sibling loop was cancelled long before 999 iterations
    assert len([v for v in verbs(fake) if v == ("densitometer_1", "measure")]) <= 2


async def test_exception_group_not_flattened_by_ancestors(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    fake.fail_jobs.add("dispense")
    wf = make_workflow([
        {"serial": {"children": [
            {"parallel": {"children": [
                {"command": {"device": "pump_1", "verb": "dispense",
                             "params": {"volume_ml": 1.0}}},
                {"command": {"device": "pump_2", "verb": "stop"}},
            ]}},
        ]}},
    ])
    ctx = make_ctx(client, wf)
    with pytest.raises(BaseExceptionGroup):  # NOT BlockFailedError: ancestors must not wrap
        await drive(ctx.clock, execute_blocks(wf.blocks, ctx))
    failed_events = [e for e in ctx.options.log_sink.events if e.kind == "block_failed"]
    assert len(failed_events) == 1  # origin leaf only


async def test_runtime_occupancy_net_under_real_concurrency(fake_client):
    """The validator would reject this tree; built unvalidated on purpose to prove the
    runtime safety net: sibling tasks cannot interleave through check-and-mark."""
    fake, client = fake_client
    add_standard_devices(fake)
    fake.hold_job("dispense")
    wf = make_workflow([
        {"parallel": {"children": [
            {"command": {"device": "pump_1", "verb": "dispense", "params": {"volume_ml": 1.0}}},
            {"command": {"device": "pump_1", "verb": "dispense", "params": {"volume_ml": 2.0}}},
        ]}},
    ])
    ctx = make_ctx(client, wf)
    with pytest.raises(BaseExceptionGroup) as info:
        await drive(ctx.clock, execute_blocks(wf.blocks, ctx))
    assert any(isinstance(e, InvariantViolationError) for e in info.value.exceptions)
    dispenses = [v for v in verbs(fake) if v[1] == "dispense"]
    assert len(dispenses) == 1  # second dispatch never reached the wire
    assert len(ctx.in_flight) == 1  # cancelled wait leaves the job tracked (§7 step 6)
    events = [e.kind for e in ctx.options.log_sink.events]
    assert "invariant_violation" in events
```

- [ ] **Step 2: Run test to verify it fails** — `.venv/bin/python -m pytest tests/test_experiment_parallel.py -v` → FAIL: `NotImplementedError: Parallel execution lands in plan 4b`

- [ ] **Step 3: Write minimal implementation** — in `execute.py`: add `import asyncio` to the imports; replace the stub:

```python
async def _run_parallel(block: B.Parallel, ctx: RunContext) -> None:
    """One task per child (design §9). Device-distinctness is statically proven; the
    occupancy model is the runtime net. A failing child cancels its siblings; the
    TaskGroup's ExceptionGroup propagates unflattened."""
    async with asyncio.TaskGroup() as tg:
        for child in block.children:
            tg.create_task(_parallel_child(child, ctx))


async def _parallel_child(child: B.Block, ctx: RunContext) -> None:
    if child.start_offset is not None:
        await ctx.clock.sleep(parse_duration(child.start_offset))
    await execute_block(child, ctx)
```

- [ ] **Step 4: Run test to verify it passes** — 5 passed

- [ ] **Step 5: Full gate**

- [ ] **Step 6: Commit**

```bash
git add src/lab_devices/experiment/execute.py tests/test_experiment_parallel.py
git commit -m "feat(experiment): parallel execution via TaskGroup with start_offset"
```

---

### Task 2: Pause / resume quiesce semantics

**Files:**
- Test: `tests/test_experiment_pause.py` (create). `pause()`/`resume()` landed in 4a Task 13; this task proves the behavior end-to-end. If any test exposes a defect, fix it in `run.py`/`execute.py` within this task.

**Interfaces:** consumes the public API + FakeLab job hold/complete + FakeClock manual `settle()`/`advance()` (drive() would mis-report a paused run as deadlock — use it only after `resume()`).

- [ ] **Step 1: Write the failing-or-passing test** (expected: mostly passing; any failure is a real 4a defect — fix source, keep assertions)

```python
# tests/test_experiment_pause.py
import asyncio

from lab_devices.experiment import ExperimentRun, RunOptions
from tests.experiment_run_helpers import add_standard_devices, make_workflow, verbs
from tests.fakeclock import FakeClock, drive


def start_run(client, wf, **opt):
    run = ExperimentRun(client, wf, options=RunOptions(clock=FakeClock(), **opt))
    task = asyncio.ensure_future(run.execute())
    return run, run._options.clock, task


async def test_pause_quiesces_while_inflight_job_finishes(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    fake.hold_job("dispense")
    wf = make_workflow([
        {"command": {"device": "pump_1", "verb": "dispense", "params": {"volume_ml": 1.0}}},
        {"command": {"device": "pump_2", "verb": "stop"}},
    ])
    run, clock, task = start_run(client, wf)
    await clock.settle()
    assert verbs(fake) == [("pump_1", "dispense")]  # in flight, held

    run.pause()
    job_id = next(iter(fake.jobs))
    fake.complete_job(job_id)          # hardware finishes WHILE paused
    await clock.advance(5.0)           # poll sleeps elapse; job wait completes
    finished = [e for e in run._ctx.options.log_sink.events if e.kind == "block_finished"]
    assert any(e.block_id == "blocks[0]" for e in finished)  # in-flight block completed
    assert ("pump_2", "stop") not in verbs(fake)  # but nothing NEW dispatched

    run.resume()
    report = await drive(clock, task)
    assert report.status == "completed"
    assert ("pump_2", "stop") in verbs(fake)
    kinds = [e.kind for e in report.log.events]
    assert kinds.index("paused") < kinds.index("resumed")


async def test_pause_leaves_open_modes_running(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    wf = make_workflow([
        {"command": {"device": "pump_2", "verb": "rotate",
                     "params": {"direction": "forward", "speed_ml_min": 2.0}}},
        {"wait": {"duration": "60s"}},
        {"command": {"device": "pump_2", "verb": "stop"}},
    ])
    run, clock, task = start_run(client, wf)
    await clock.settle()
    assert len(run._ctx.occupancy.open_modes()) == 1  # rotate is open

    run.pause()
    await clock.advance(60.0)  # the wait elapses during pause; next block stays gated
    assert len(run._ctx.occupancy.open_modes()) == 1  # STILL open: pause never tears down
    assert ("pump_2", "stop") not in verbs(fake)

    run.resume()
    report = await drive(clock, task)
    assert report.status == "completed"
    assert run._ctx.occupancy.open_modes() == ()


async def test_pause_gates_loop_iteration_top(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    wf = make_workflow([
        {"loop": {"count": 3, "body": [
            {"command": {"device": "pump_1", "verb": "stop"}},
            {"wait": {"duration": "10s"}},
        ]}},
    ])
    run, clock, task = start_run(client, wf)
    await clock.settle()
    assert verbs(fake) == [("pump_1", "stop")]  # iteration 1 dispatched, in its wait

    run.pause()
    await clock.advance(10.0)  # iteration 1 body completes; iteration 2 gated at loop top
    await clock.settle()
    assert verbs(fake) == [("pump_1", "stop")]

    run.resume()
    report = await drive(clock, task)
    assert report.status == "completed"
    assert [v for v in verbs(fake) if v == ("pump_1", "stop")][:3] == [("pump_1", "stop")] * 3


async def test_pause_before_execute_gates_first_block(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    wf = make_workflow([{"command": {"device": "pump_1", "verb": "stop"}}])
    run = ExperimentRun(client, wf, options=RunOptions(clock=FakeClock()))
    run.pause()  # before execute(): gate cleared silently (no clock available yet)
    task = asyncio.ensure_future(run.execute())
    clock = run._options.clock
    await clock.settle()
    assert fake.calls == []  # first block never dispatched
    run.resume()
    report = await drive(clock, task)
    assert report.status == "completed"


async def test_pause_resume_idempotent_events(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    fake.hold_job("dispense")
    wf = make_workflow([
        {"command": {"device": "pump_1", "verb": "dispense", "params": {"volume_ml": 1.0}}},
    ])
    run, clock, task = start_run(client, wf)
    await clock.settle()
    run.pause()
    run.pause()   # no second event
    run.resume()
    run.resume()  # no second event
    fake.complete_job(next(iter(fake.jobs)))
    await drive(clock, task)
    kinds = [e.kind for e in run.report.log.events]
    assert kinds.count("paused") == 1 and kinds.count("resumed") == 1
```

- [ ] **Step 2: Run** — `.venv/bin/python -m pytest tests/test_experiment_pause.py -v`. Expected: 5 passed (4a wired the gate). Any failure = real defect: fix `run.py`/`execute.py`, do not weaken tests.

- [ ] **Step 3: Full gate**

- [ ] **Step 4: Commit**

```bash
git add tests/test_experiment_pause.py
git commit -m "test(experiment): pause/resume quiesce semantics (in-flight finishes, modes stay open)"
```

(Include any source fix in the same commit with an amended message noting it.)

---

### Task 3: Operator abort

**Files:**
- Modify: `src/lab_devices/experiment/run.py` (add `abort()`)
- Test: `tests/test_experiment_abort.py` (create)

**Interfaces:**
- Produces: `ExperimentRun.abort() -> None` (sync, idempotent) — sets `ctx.abort_requested`, emits `abort_requested` once (only if started and unreported), cancels `self._task` unless `self._finalizing` (an abort arriving mid-finalize must not cancel the finalizer; the flag alone suffices). The 4a `execute()` outcome matrix then yields: finalizer runs → `report.status == "aborted"` → `task.uncancel()` → raise `RunAbortedError` (chained from the `CancelledError`).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_experiment_abort.py
import asyncio

import pytest

from lab_devices.experiment import ExperimentRun, RunAbortedError, RunOptions
from tests.experiment_run_helpers import add_standard_devices, make_workflow, verbs
from tests.fakeclock import FakeClock


def start_run(client, wf):
    run = ExperimentRun(client, wf, options=RunOptions(clock=FakeClock()))
    task = asyncio.ensure_future(run.execute())
    return run, run._options.clock, task


async def test_abort_midrun_cancels_and_finalizes(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    fake.hold_job("dispense")
    wf = make_workflow([
        {"command": {"device": "pump_2", "verb": "rotate",
                     "params": {"direction": "forward", "speed_ml_min": 2.0}}},
        {"command": {"device": "pump_1", "verb": "dispense", "params": {"volume_ml": 1.0}}},
    ])
    run, clock, task = start_run(client, wf)
    await clock.settle()
    assert verbs(fake) == [("pump_2", "rotate"), ("pump_1", "dispense")]

    run.abort()
    with pytest.raises(RunAbortedError):
        await task
    assert run.report.status == "aborted"
    assert isinstance(run.report.error, asyncio.CancelledError)
    # finalizer: (1) stop the in-flight job's device, (2) teardown rotate, (3) sweep
    assert verbs(fake)[2:] == [
        ("pump_1", "stop"),   # step 1: cancelled wait left the job tracked
        ("pump_2", "stop"),   # step 2: rotate teardown
        ("pump_2", "stop"),   # step 3: sweep, touched order
        ("pump_1", "stop"),
    ]
    assert run._ctx.occupancy.open_modes() == ()
    kinds = [e.kind for e in run.report.log.events]
    assert "abort_requested" in kinds and "finalize_finished" in kinds


async def test_abort_before_execute(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    wf = make_workflow([{"command": {"device": "pump_1", "verb": "stop"}}])
    run = ExperimentRun(client, wf, options=RunOptions(clock=FakeClock()))
    run.abort()
    with pytest.raises(RunAbortedError):
        await run.execute()
    assert fake.calls == []  # nothing dispatched, nothing touched, empty sweep
    assert run.report.status == "aborted"


async def test_abort_while_paused(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    fake.hold_job("dispense")
    wf = make_workflow([
        {"command": {"device": "pump_1", "verb": "dispense", "params": {"volume_ml": 1.0}}},
        {"command": {"device": "pump_2", "verb": "stop"}},
    ])
    run, clock, task = start_run(client, wf)
    await clock.settle()
    run.pause()
    run.abort()  # abort must win over the closed gate
    with pytest.raises(RunAbortedError):
        await task
    assert run.report.status == "aborted"
    assert ("pump_1", "stop") in verbs(fake)  # in-flight dispense's device stopped
    assert ("pump_2", "stop") not in verbs(fake)[:2]  # second block never dispatched


async def test_abort_idempotent(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    fake.hold_job("dispense")
    wf = make_workflow([
        {"command": {"device": "pump_1", "verb": "dispense", "params": {"volume_ml": 1.0}}},
    ])
    run, clock, task = start_run(client, wf)
    await clock.settle()
    run.abort()
    run.abort()
    with pytest.raises(RunAbortedError):
        await task
    kinds = [e.kind for e in run.report.log.events]
    assert kinds.count("abort_requested") == 1
```

- [ ] **Step 2: Run test to verify it fails** — FAIL: `AttributeError: 'ExperimentRun' object has no attribute 'abort'`

- [ ] **Step 3: Write minimal implementation** — add to `ExperimentRun` (after `resume`):

```python
    def abort(self) -> None:
        """Operator abort: cancel dispatch; the finalizer still reaches safe state (§10)."""
        ctx = self._ctx
        first = not ctx.abort_requested
        ctx.abort_requested = True
        if self._started and first and self.report is None:
            ctx.emit("abort_requested")
        if self._task is not None and not self._finalizing:
            self._task.cancel()
```

- [ ] **Step 4: Run test to verify it passes** — 4 passed

- [ ] **Step 5: Full gate**

- [ ] **Step 6: Commit**

```bash
git add src/lab_devices/experiment/run.py tests/test_experiment_abort.py
git commit -m "feat(experiment): operator abort (cancel + finalize -> RunAbortedError)"
```

---

### Task 4: Invariant-violation and D7 end-to-end flagships

**Files:**
- Test: `tests/test_experiment_e2e_invariants.py` (create; no source changes expected)

**Interfaces:** public API only.

- [ ] **Step 1: Write the tests**

```python
# tests/test_experiment_e2e_invariants.py
"""Flagships: BusyError invariant path (spec §16 #8) and D7 runtime classification."""
import pytest

from lab_devices.experiment import ExperimentRun, InvariantViolationError, RunOptions
from tests.experiment_run_helpers import add_standard_devices, make_workflow, verbs
from tests.fakeclock import FakeClock, drive


def make_run(client, wf):
    return ExperimentRun(client, wf, options=RunOptions(clock=FakeClock()))


async def test_flagship_busy_error_is_invariant_violation_never_retried(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    fake.inject_error("pump_1", "dispense", "busy", "job j-0 in progress")
    wf = make_workflow([
        {"command": {"device": "pump_1", "verb": "dispense", "params": {"volume_ml": 1.0}}},
    ])
    run = make_run(client, wf)
    with pytest.raises(InvariantViolationError):
        await drive(run._options.clock, run.execute())
    assert run.report.status == "failed"
    dispenses = [v for v in verbs(fake) if v[1] == "dispense"]
    assert len(dispenses) == 1  # the call log proves a single attempt: never retried
    assert verbs(fake)[-1] == ("pump_1", "stop")  # finalizer swept the touched device
    kinds = [e.kind for e in run.report.log.events]
    assert "invariant_violation" in kinds


async def test_d7_expression_close_registers_no_mode(fake_client):
    """A mode verb whose expression params resolve to the teardown literal is a CLOSE at
    runtime (D7): no mode registered, no teardown issued — only the sweep touches it.
    (The validator conservatively calls it an open, which is why nothing may follow it
    on the channel — but it validates standalone.)"""
    fake, client = fake_client
    add_standard_devices(fake)
    wf = make_workflow([
        {"command": {"device": "densitometer_1", "verb": "set_led",
                     "params": {"level": "10 - 10"}}},
    ])
    run = make_run(client, wf)
    report = await drive(run._options.clock, run.execute())
    assert report.status == "completed"
    kinds = [e.kind for e in report.log.events]
    assert "mode_opened" not in kinds
    assert "teardown_issued" not in kinds  # nothing was open at run end
    led_levels = [c[2]["level"] for c in fake.calls if c[1] == "set_led"]
    assert led_levels == [0, 0]  # the block's own call, then the sweep's — both closes
```

- [ ] **Step 2: Run** — 2 passed expected; failures are source bugs.

- [ ] **Step 3: Full gate**

- [ ] **Step 4: Commit**

```bash
git add tests/test_experiment_e2e_invariants.py
git commit -m "test(experiment): BusyError invariant + D7 runtime-close flagships"
```

---

### Task 5: Concurrent flagships + increment close-out

**Files:**
- Test: `tests/test_experiment_e2e_concurrent.py` (create)
- Modify: `docs/superpowers/specs/2026-07-08-experiment-orchestrator-4-executor-design.md` (Status line only)

**Interfaces:** public API only.

- [ ] **Step 1: Write the tests**

```python
# tests/test_experiment_e2e_concurrent.py
"""Concurrent flagships (spec §16 #9-10): same-device channel overlap, input lanes."""
import asyncio

from lab_devices.experiment import ExperimentRun, RunOptions
from lab_devices.experiment.inputs import InputRequest
from lab_devices.experiment.state import BindingValue
from tests.experiment_run_helpers import add_standard_devices, make_workflow, verbs
from tests.fakeclock import FakeClock, drive


async def test_flagship_thermal_optics_overlap_one_densitometer(fake_client):
    """Validator-legal same-device parallelism: thermostat (thermal) alongside a measure
    loop (optics), serialized on the wire by the per-device lock (D2)."""
    fake, client = fake_client
    add_standard_devices(fake)
    wf = make_workflow(
        [{"parallel": {"children": [
            {"command": {"device": "densitometer_1", "verb": "set_thermostat",
                         "params": {"enabled": True, "target_c": 37.0}}},
            {"loop": {"count": 2, "body": [
                {"measure": {"device": "densitometer_1", "verb": "measure", "into": "OD"}},
            ]}},
        ]}}],
        streams={"OD": {"units": "AU"}},
    )
    run = ExperimentRun(client, wf, options=RunOptions(clock=FakeClock()))
    report = await drive(run._options.clock, run.execute())
    assert report.status == "completed"
    assert len(report.state.streams["OD"]) == 2
    seq = verbs(fake)
    assert seq.count(("densitometer_1", "measure")) == 2
    # thermostat mode was torn down by the finalizer (never explicitly closed)
    teardowns = [e for e in report.log.events if e.kind == "teardown_issued"]
    assert len(teardowns) == 1 and teardowns[0].data["verb"] == "set_thermostat"
    thermostat_calls = [c[2] for c in fake.calls if c[1] == "set_thermostat"]
    assert thermostat_calls[0] == {"enabled": True, "target_c": 37.0}  # the open
    assert {"enabled": False} in thermostat_calls  # teardown (and sweep) closed it
    assert run._ctx.occupancy.open_modes() == ()


class GatedInputProvider:
    """Blocks its lane until the test releases it — proves siblings keep running."""

    def __init__(self, value: BindingValue) -> None:
        self.value = value
        self.release = asyncio.Event()
        self.requests: list[InputRequest] = []

    async def request(self, request: InputRequest) -> BindingValue:
        self.requests.append(request)
        await self.release.wait()
        return self.value


async def test_flagship_operator_input_blocks_only_its_lane(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    wf = make_workflow([
        {"parallel": {"children": [
            {"operator_input": {"name": "target", "type": "float"}},
            {"command": {"device": "pump_1", "verb": "stop"}},
        ]}},
    ])
    provider = GatedInputProvider(1.5)
    run = ExperimentRun(
        client, wf, options=RunOptions(clock=FakeClock(), input_provider=provider)
    )
    clock = run._options.clock
    task = asyncio.ensure_future(run.execute())
    await clock.settle()
    assert ("pump_1", "stop") in verbs(fake)  # sibling lane ran while input pending
    assert len(provider.requests) == 1        # ...and the request is outstanding
    assert "target" not in run._ctx.state.bindings

    provider.release.set()
    report = await drive(clock, task)
    assert report.status == "completed"
    assert report.state.bindings == {"target": 1.5}
```

- [ ] **Step 2: Run** — 2 passed expected.

- [ ] **Step 3: Increment coverage audit** — confirm every spec §16 flagship has a test:
  1 → `test_flagship_rotate_measure_feedback` (4a); 2 → `test_flagship_midrun_job_failure_full_finalizer` (4a); 3 → `test_flagship_failsafe_empty_duration_window` (4a); 4 → `test_flagship_count_zero_on_precreated_stream` (4a); 5 → `test_flagship_operator_input_feeds_param` + `test_unattended_input_fails_safe` (4a); 6 → `test_pause_quiesces_while_inflight_job_finishes` + `test_pause_leaves_open_modes_running`; 7 → `test_abort_midrun_cancels_and_finalizes`; 8 → `test_flagship_busy_error_is_invariant_violation_never_retried`; 9 → `test_start_offset_staggers_branch_start` + `test_failing_child_cancels_siblings_exception_group`; 10 → both tests in this task. Record the mapping in the SDD ledger.

- [ ] **Step 4: Update the design doc Status line** to `- **Status:** Approved; implemented (plans 4a/4b, Increment 4)`.

- [ ] **Step 5: Full gate** — record the final suite count in the ledger.

- [ ] **Step 6: Commit**

```bash
git add tests/test_experiment_e2e_concurrent.py docs/superpowers/specs/2026-07-08-experiment-orchestrator-4-executor-design.md
git commit -m "test(experiment): concurrent flagships; close out Increment 4"
```

---

## Plan-level self-review notes (already applied)

- The five adversarial review questions from the increment brief map to: finalizer-always-runs (4a Task 13 external-cancel test, 4b Tasks 3–4), modes-always-torn-down (4a Task 12/14, 4b Tasks 2/5), pause-leaves-modes (4b Task 2), no-await-between-check-and-mark (code-level: `Occupancy.acquire` is sync, pinned behaviorally by 4b Task 1's concurrency-net test).
- Deliberately-unvalidated trees (4b Task 1 net test) must use `make_workflow` (loader only), never `ExperimentRun` (which validates, D6) — noted in the test docstring.
