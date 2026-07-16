# Self-failing blocks (`abort` + `alarm`) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add two leaf blocks — `abort` (hard stop) and `alarm` (flag-and-continue) — that evaluate a boolean condition exactly like `branch.if`, so a workflow can fail or flag itself on a condition (closes `docs/experiment-engine-limitations.md` #7).

**Architecture:** `abort` raises a new never-tolerated, never-retried `AbortSignalError` that unwinds the tree, runs the existing finalizer, and reports status `"aborted"`. `alarm` emits an event + appends to `RunReport.alarms` and continues. Both reuse the existing `_condition`/`_check_condition`/path-analysis machinery, so no new expression, type, or freshness logic is written. Macro expansion handles their string fields for free.

**Tech Stack:** Python 3.14 (`src/lab_devices`), pytest + FakeClock/FakeLab, mypy, ruff. Studio: FastAPI backend (`webapp/backend`), React/TypeScript frontend (`webapp/frontend`, vitest).

**Spec:** `docs/superpowers/specs/2026-07-16-experiment-orchestrator-8-abort-alarm-design.md`

## Global Constraints

- **Line length ≤ 100** across experiment src + tests (gate: `awk 'length>100'`).
- **Gates every task:** `.venv/bin/python -m pytest`, `.venv/bin/mypy src/lab_devices`, `ruff check .`, and `awk 'length>100' <changed files>` (empty output). Frontend tasks also run `npm --prefix webapp/frontend run test` and `npm --prefix webapp/frontend run build`; backend Studio tasks run `webapp/backend/.venv/bin/python -m pytest webapp/backend/tests`.
- **`message` is required and non-empty** on both blocks; **`if` is a required boolean expression**.
- **`abort` may not carry `on_error: "continue"`**; `alarm` may.
- **Reuse `"aborted"` status** for a workflow abort — no fifth status. Distinguish by `AbortSignalError` + the `abort_raised` event.
- **Mutation-verify** every test that defends a safety property (abort non-tolerance, status, parallel-lane): delete the feature from source, confirm the test FAILS, restore, checksum byte-identical, and report it (per the abort-tests-must-be-mutation-verified memory). Assert at the **wire** (no hardware command after the abort fires), not on `report.status` alone.
- **JSON key is `if`**, dataclass field is `if_` (mirrors `Branch`).

---

### Task 1: AST + serialization for `abort` / `alarm`

**Files:**
- Modify: `src/lab_devices/experiment/blocks.py`
- Modify: `src/lab_devices/experiment/serialize.py`
- Test: `tests/test_experiment_serialize.py`

**Interfaces:**
- Produces: `B.Abort(if_: str, message: str)`, `B.Alarm(if_: str, message: str)` (both `BlockBase` leaves); serializer builders under keys `"abort"`/`"alarm"`; `_dump_body` arms.

- [ ] **Step 1: Write the failing round-trip + load-error tests**

Append to `tests/test_experiment_serialize.py` (imports `workflow_from_dict`, `workflow_to_dict` already present in that file; add `WorkflowLoadError` import if absent):

```python
def test_abort_alarm_roundtrip():
    doc = {
        "schema_version": 1,
        "persistence": {"default": "in_memory", "format": "jsonl"},
        "streams": {"od_1": {}},
        "blocks": [
            {"abort": {"if": "count(od_1, last=1min) > 0 and last(od_1) > 2.0",
                       "message": "contaminated"}},
            {"alarm": {"if": "last(od_1) > 1.0", "message": "high od"}},
        ],
    }
    assert workflow_to_dict(workflow_from_dict(doc)) == doc


def test_abort_requires_if_and_message():
    with pytest.raises(WorkflowLoadError):
        workflow_from_dict({"schema_version": 1,
                            "blocks": [{"abort": {"message": "x"}}]})
    with pytest.raises(WorkflowLoadError):
        workflow_from_dict({"schema_version": 1,
                            "blocks": [{"abort": {"if": "true"}}]})


def test_alarm_requires_if_and_message():
    with pytest.raises(WorkflowLoadError):
        workflow_from_dict({"schema_version": 1,
                            "blocks": [{"alarm": {"message": "x"}}]})
    with pytest.raises(WorkflowLoadError):
        workflow_from_dict({"schema_version": 1,
                            "blocks": [{"alarm": {"if": "true"}}]})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_experiment_serialize.py -k "abort or alarm" -q`
Expected: FAIL (`unknown block type 'abort'`).

- [ ] **Step 3: Add the dataclasses**

In `src/lab_devices/experiment/blocks.py`, after the `Record` dataclass (before `ForEach`):

```python
@dataclass(kw_only=True)
class Abort(BlockBase):
    if_: str  # boolean expression; a true value stops the run (design 2026-07-16 §2.1)
    message: str


@dataclass(kw_only=True)
class Alarm(BlockBase):
    if_: str  # boolean expression; a true value flags and continues (design 2026-07-16 §2.2)
    message: str
```

Add both to the `Block` union (after `Record`):

```python
Block = (
    Command
    | Measure
    | OperatorInput
    | Wait
    | Serial
    | Parallel
    | Loop
    | Branch
    | GroupRef
    | Compute
    | Record
    | Abort
    | Alarm
    | ForEach
)
```

- [ ] **Step 4: Add the serializer builders and dump arms**

In `src/lab_devices/experiment/serialize.py`, add builders after `_record` (before `_operator_input` or near the other leaf builders):

```python
def _abort(body: Any, timing: dict[str, Any]) -> B.Block:
    if_ = _checked_expr(_req(body, "if", "abort"), "abort if")
    message = _str(_req(body, "message", "abort"), "abort message")
    return B.Abort(if_=if_, message=message, **timing)


def _alarm(body: Any, timing: dict[str, Any]) -> B.Block:
    if_ = _checked_expr(_req(body, "if", "alarm"), "alarm if")
    message = _str(_req(body, "message", "alarm"), "alarm message")
    return B.Alarm(if_=if_, message=message, **timing)
```

Add to `_BUILDERS`:

```python
    "abort": _abort,
    "alarm": _alarm,
```

Add `_dump_body` arms (after the `Record` arm, before the final `raise`):

```python
    if isinstance(b, B.Abort):
        return "abort", {"if": b.if_, "message": b.message}
    if isinstance(b, B.Alarm):
        return "alarm", {"if": b.if_, "message": b.message}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_experiment_serialize.py -k "abort or alarm" -q`
Expected: PASS.

- [ ] **Step 6: Gates + commit**

Run: `.venv/bin/python -m pytest tests/test_experiment_serialize.py -q && .venv/bin/mypy src/lab_devices && ruff check . && awk 'length>100' src/lab_devices/experiment/blocks.py src/lab_devices/experiment/serialize.py tests/test_experiment_serialize.py`
Expected: all pass, `awk` empty.

```bash
git add src/lab_devices/experiment/blocks.py src/lab_devices/experiment/serialize.py tests/test_experiment_serialize.py
git commit -m "feat(experiment): AST + serialization for abort/alarm blocks"
```

---

### Task 2: Validator — per-block checks + path analysis

**Files:**
- Modify: `src/lab_devices/experiment/validate.py`
- Test: `tests/test_experiment_validate_blocks.py`

**Interfaces:**
- Consumes: `B.Abort`, `B.Alarm` (Task 1); existing `_check_condition`, `_expr_reads`.
- Produces: validator arms; a `_check_message(message, path, kind, out)` helper.

- [ ] **Step 1: Write the failing validator tests**

Append to `tests/test_experiment_validate_blocks.py` (uses the shared `wf`/`diags` helpers from `tests/experiment_validate_helpers.py`; add `from lab_devices.experiment.validate import validate` and `from tests.experiment_validate_helpers import wf, diags` if not already imported):

```python
def test_abort_condition_must_be_boolean():
    d = diags(wf([{"abort": {"if": "1 + 1", "message": "x"}}]))
    assert any("boolean" in m.message for m in d)


def test_abort_message_required_nonempty():
    d = diags(wf([{"abort": {"if": "true", "message": "   "}}]))
    assert any("non-empty message" in m.message for m in d)


def test_abort_forbids_on_error_continue():
    d = diags(wf([{"abort": {"if": "true", "message": "x"}, "on_error": "continue"}]))
    assert any("cannot be tolerated" in m.message for m in d)


def test_alarm_allows_on_error_continue():
    validate(wf([{"alarm": {"if": "true", "message": "x"}, "on_error": "continue"}]))


def test_retry_on_abort_rejected():
    d = diags(wf([{"abort": {"if": "true", "message": "x"}, "retry": {"attempts": 2}}]))
    assert any("command and measure" in m.message for m in d)


def test_abort_unguarded_window_diagnosed():
    d = diags(wf([{"abort": {"if": "mean(od_1, last=30min) > 1", "message": "x"}}],
                 streams=["od_1"]))
    assert any(m.category == "data-flow" for m in d)


def test_abort_guarded_window_clean():
    validate(wf([{"abort": {"if": "count(od_1, last=30min) > 0 and mean(od_1, last=30min) > 1",
                            "message": "x"}}], streams=["od_1"]))


def test_for_each_abort_expands_per_tube():
    validate(wf([
        {"for_each": {"var": "tube", "in": [1, 2],
            "body": [{"abort": {
                "if": "count(od_{tube}, last=1min) > 0 and last(od_{tube}) > 5",
                "message": "tube {tube} lost"}}]}},
    ], streams=["od_1", "od_2"]))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_experiment_validate_blocks.py -k "abort or alarm or for_each_abort" -q`
Expected: FAIL (no diagnostics produced / clean docs raising, etc.).

- [ ] **Step 3: Add `_check_message` and the `_check_block` arms**

In `src/lab_devices/experiment/validate.py`, add the helper near `_check_condition`:

```python
def _check_message(message: object, path: str, kind: str, out: list[Diagnostic]) -> None:
    if not isinstance(message, str) or not message.strip():
        out.append(Diagnostic("block", path, f"{kind} requires a non-empty message"))
```

In `_check_block`, add arms after the `B.Record` branch:

```python
    elif isinstance(block, B.Abort):
        _check_condition(block.if_, f"{path} abort if", w, binding_types, out)
        _check_message(block.message, path, "abort", out)
        if block.on_error == "continue":
            out.append(Diagnostic(
                "block", path,
                "abort may not carry on_error: 'continue'; a safety stop cannot be tolerated",
            ))
    elif isinstance(block, B.Alarm):
        _check_condition(block.if_, f"{path} alarm if", w, binding_types, out)
        _check_message(block.message, path, "alarm", out)
```

(`_check_retry` already runs unconditionally in `_check_block`'s head and produces the
"command and measure blocks" diagnostic for a `retry` on either block — no extra code.)

- [ ] **Step 4: Add the path-analysis arm**

In `_visit_body`, add after the `B.Record` branch (both blocks read the condition and write no state):

```python
    elif isinstance(b, (B.Abort, B.Alarm)):
        slot = "abort if" if isinstance(b, B.Abort) else "alarm if"
        _expr_reads(b.if_, f"{path} {slot}", state, c)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_experiment_validate_blocks.py -k "abort or alarm or for_each_abort" -q`
Expected: PASS.

- [ ] **Step 6: Gates + commit**

Run: `.venv/bin/python -m pytest tests/test_experiment_validate_blocks.py -q && .venv/bin/mypy src/lab_devices && ruff check . && awk 'length>100' src/lab_devices/experiment/validate.py tests/test_experiment_validate_blocks.py`
Expected: all pass, `awk` empty.

```bash
git add src/lab_devices/experiment/validate.py tests/test_experiment_validate_blocks.py
git commit -m "feat(experiment): validate abort/alarm (condition, message, on_error, freshness)"
```

---

### Task 3: Executor — `abort` (safety-critical, mutation-verified)

**Files:**
- Modify: `src/lab_devices/experiment/errors.py`
- Modify: `src/lab_devices/experiment/execute.py`
- Modify: `src/lab_devices/experiment/run.py`
- Test: `tests/test_experiment_abort_block.py` (new)

**Interfaces:**
- Consumes: `B.Abort` (Task 1); existing `_condition`, `_emit`, `_tolerable`, `execute_block`, finalizer.
- Produces: `AbortSignalError(block_id: str, message: str)`; `_run_abort`; `run._contains_abort`; status `"aborted"` for a workflow abort.

- [ ] **Step 1: Write the failing executor tests (mutation targets marked)**

Create `tests/test_experiment_abort_block.py`:

```python
import asyncio

import pytest

from lab_devices.experiment import ExperimentRun, RunOptions
from lab_devices.experiment.errors import AbortSignalError
from tests.experiment_run_helpers import add_standard_devices, make_workflow, verbs
from tests.fakeclock import FakeClock


def _run(client, wf):
    return ExperimentRun(client, wf, options=RunOptions(clock=FakeClock()))


async def test_abort_false_is_noop(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    wf = make_workflow([
        {"abort": {"if": "false", "message": "never"}},
        {"command": {"device": "pump_1", "verb": "stop"}},
    ])
    report = await _run(client, wf).execute()
    assert report.status == "completed"
    assert ("pump_1", "stop") in verbs(fake)


async def test_abort_true_stops_run_and_skips_successor(fake_client):
    # WIRE assertion: the post-abort dispense must never reach the hardware.
    fake, client = fake_client
    add_standard_devices(fake)
    wf = make_workflow([
        {"abort": {"if": "true", "message": "stop now"}},
        {"command": {"device": "pump_1", "verb": "dispense", "params": {"volume_ml": 1.0}}},
    ])
    run = _run(client, wf)
    with pytest.raises(AbortSignalError):
        await run.execute()
    assert run.report.status == "aborted"                      # MUTATION: except-arm entry
    assert ("pump_1", "dispense") not in verbs(fake)
    kinds = [e.kind for e in run.report.log.events]
    assert "abort_raised" in kinds
    assert "finalize_finished" in kinds


async def test_abort_runs_finalizer_over_touched_device(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    wf = make_workflow([
        {"command": {"device": "pump_1", "verb": "rotate",
                     "params": {"direction": "forward", "speed_ml_min": 2.0}}},
        {"abort": {"if": "true", "message": "stop"}},
    ])
    run = _run(client, wf)
    with pytest.raises(AbortSignalError):
        await run.execute()
    assert run.report.status == "aborted"
    assert ("pump_1", "stop") in verbs(fake)  # rotate teardown + sweep swept the device safe
    assert run._ctx.occupancy.open_modes() == ()


async def test_abort_not_tolerated_by_enclosing_on_error(fake_client):
    # MUTATION: remove AbortSignalError from _tolerable -> this run would "complete".
    fake, client = fake_client
    add_standard_devices(fake)
    wf = make_workflow([
        {"serial": {"children": [
            {"abort": {"if": "true", "message": "stop"}},
        ]}, "on_error": "continue"},
        {"command": {"device": "pump_2", "verb": "dispense", "params": {"volume_ml": 1.0}}},
    ])
    run = _run(client, wf)
    with pytest.raises(AbortSignalError):
        await run.execute()
    assert run.report.status == "aborted"
    assert ("pump_2", "dispense") not in verbs(fake)


async def test_abort_in_parallel_lane_reports_aborted(fake_client):
    # MUTATION: remove _contains_abort's group recursion -> status becomes "failed".
    fake, client = fake_client
    add_standard_devices(fake)
    wf = make_workflow([
        {"parallel": {"children": [
            {"abort": {"if": "true", "message": "lane stop"}},
            {"command": {"device": "pump_1", "verb": "rotate",
                         "params": {"direction": "forward", "speed_ml_min": 2.0}}},
        ]}, "on_error": "continue"},
    ])
    run = _run(client, wf)
    with pytest.raises(BaseException):  # AbortSignalError or the ExceptionGroup carrying it
        await run.execute()
    assert run.report.status == "aborted"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_experiment_abort_block.py -q`
Expected: FAIL (`cannot import name 'AbortSignalError'`).

- [ ] **Step 3: Add `AbortSignalError`**

In `src/lab_devices/experiment/errors.py`, after `InvariantViolationError`:

```python
class AbortSignalError(ExperimentRunError):
    """A workflow `abort` block's condition was true: a deliberate, workflow-initiated stop
    (design 2026-07-16 §2.1). Distinct from an operator abort's RunAbortedError. Never retried,
    never tolerated (execute._tolerable); the finalizer still sweeps to a safe state and the run
    reports status "aborted" (run._contains_abort)."""

    def __init__(self, block_id: str, message: str) -> None:
        self.block_id = block_id
        super().__init__(message)
```

- [ ] **Step 4: Wire the executor**

In `src/lab_devices/experiment/execute.py`:

Import (add `AbortSignalError` to the existing `from lab_devices.experiment.errors import (...)`):

```python
    AbortSignalError,
```

Add the `_run_abort` coroutine (near `_run_compute`/`_run_record`):

```python
async def _run_abort(block: B.Abort, ctx: RunContext) -> None:
    """A true condition is a deliberate, non-tolerable stop (design 2026-07-16 §2.1). Emit the
    event best-effort (a raising sink must not displace the abort), then raise."""
    if _condition(block.if_, ctx):
        _emit(ctx, "abort_raised", block.id, message=block.message)
        raise AbortSignalError(str(block.id), block.message)
```

Add the dispatch arm in `_execute_inner`, before the `GroupRef` arm:

```python
    elif isinstance(block, B.Abort):
        await _run_abort(block, ctx)
```

Add `AbortSignalError` to `_tolerable`'s never-absorb tuple (the `isinstance(exc, (...))` list):

```python
            asyncio.CancelledError,
            InvariantViolationError,
            AbortSignalError,
            RunAbortedError,
            core_errors.BusyError,
```

Add `AbortSignalError` to `execute_block`'s FIRST except tuple so it re-raises unwrapped and is
never re-emitted as `block_failed`:

```python
    except (BlockFailedError, InvariantViolationError, AbortSignalError) as exc:
        if _tolerate(block, exc, ctx):  # the origin frame already emitted its event
            return
        raise
```

- [ ] **Step 5: Wire the run status**

In `src/lab_devices/experiment/run.py`:

Import (add to the `from lab_devices.experiment.errors import (...)`):

```python
    AbortSignalError,
```

Add the helper (module level, near `assign_block_ids`):

```python
def _contains_abort(exc: BaseException) -> bool:
    """True iff `exc` is, or (recursing through ExceptionGroups) contains, an AbortSignalError.
    A parallel lane's abort arrives inside the TaskGroup's ExceptionGroup — the group preserves
    the error (only a racing CancelledError is dropped) — so it must be flattened to find it
    (design 2026-07-16 §4.3)."""
    if isinstance(exc, AbortSignalError):
        return True
    if isinstance(exc, BaseExceptionGroup):
        return any(_contains_abort(inner) for inner in exc.exceptions)
    return False
```

Replace the status computation block in `execute()`:

```python
        cancelled = isinstance(error, asyncio.CancelledError)
        operator_aborted = cancelled and ctx.abort_requested
        workflow_aborted = error is not None and _contains_abort(error)
        status = (
            "aborted" if operator_aborted or workflow_aborted
            else "cancelled" if cancelled
            else "failed" if error is not None
            else "completed"
        )
```

Rename the later `if aborted:` (operator-abort re-raise, ~line 198) to `if operator_aborted:`.
A workflow abort is not a `CancelledError`, so it falls to `if error is not None: raise error`,
which re-raises the `AbortSignalError` (or the group carrying it) after the finalizer has run.

- [ ] **Step 6: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_experiment_abort_block.py -q`
Expected: PASS (all 5).

- [ ] **Step 7: Mutation-verify the three safety tests**

Do each, one at a time; after each, restore and confirm the file is byte-identical (`git diff --stat` shows no change to source):

1. Delete `AbortSignalError` from `_tolerable`'s tuple → run `pytest tests/test_experiment_abort_block.py::test_abort_not_tolerated_by_enclosing_on_error` → **must FAIL**. Restore.
2. Delete `AbortSignalError` from `execute_block`'s first except tuple (leave it to the `except Exception` arm) → run `::test_abort_true_stops_run_and_skips_successor` → **must FAIL** (status becomes `"failed"`). Restore.
3. Delete `_contains_abort`'s `BaseExceptionGroup` recursion (return `isinstance(exc, AbortSignalError)` only) → run `::test_abort_in_parallel_lane_reports_aborted` → **must FAIL**. Restore.

Record the three results in the task's completion note. Confirm restored source is byte-identical.

- [ ] **Step 8: Gates + commit**

Run: `.venv/bin/python -m pytest -q && .venv/bin/mypy src/lab_devices && ruff check . && awk 'length>100' src/lab_devices/experiment/errors.py src/lab_devices/experiment/execute.py src/lab_devices/experiment/run.py tests/test_experiment_abort_block.py`
Expected: full suite green, `awk` empty.

```bash
git add src/lab_devices/experiment/errors.py src/lab_devices/experiment/execute.py src/lab_devices/experiment/run.py tests/test_experiment_abort_block.py
git commit -m "feat(experiment): abort block raises non-tolerable AbortSignalError -> status aborted"
```

---

### Task 4: Executor — `alarm` + `RunReport.alarms`

**Files:**
- Modify: `src/lab_devices/experiment/errors.py`
- Modify: `src/lab_devices/experiment/context.py`
- Modify: `src/lab_devices/experiment/execute.py`
- Modify: `src/lab_devices/experiment/run.py`
- Test: `tests/test_experiment_alarm_block.py` (new)

**Interfaces:**
- Consumes: `B.Alarm` (Task 1); existing `_condition`, `ctx.emit`.
- Produces: `AlarmRecord(block_id: str, message: str)`; `RunContext.alarms: list[AlarmRecord]`; `_run_alarm`; `RunReport.alarms: tuple[AlarmRecord, ...]`.

- [ ] **Step 1: Write the failing alarm tests**

Create `tests/test_experiment_alarm_block.py`:

```python
from lab_devices.experiment import ExperimentRun, RunOptions
from tests.experiment_run_helpers import add_standard_devices, make_workflow, verbs
from tests.fakeclock import FakeClock


def _run(client, wf):
    return ExperimentRun(client, wf, options=RunOptions(clock=FakeClock()))


async def test_alarm_fires_and_run_continues(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    wf = make_workflow([
        {"alarm": {"if": "true", "message": "flagged"}},
        {"command": {"device": "pump_1", "verb": "stop"}},
    ])
    report = await _run(client, wf).execute()
    assert report.status == "completed"
    assert [a.message for a in report.alarms] == ["flagged"]
    assert "alarm_raised" in [e.kind for e in report.log.events]
    assert ("pump_1", "stop") in verbs(fake)


async def test_alarm_false_is_silent(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    wf = make_workflow([{"alarm": {"if": "false", "message": "nope"}}])
    report = await _run(client, wf).execute()
    assert report.alarms == ()
    assert "alarm_raised" not in [e.kind for e in report.log.events]


async def test_alarm_is_stateless_fires_each_cycle(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    wf = make_workflow([
        {"loop": {"count": 3, "body": [{"alarm": {"if": "true", "message": "tick"}}]}},
    ])
    report = await _run(client, wf).execute()
    assert len(report.alarms) == 3


async def test_alarm_latch_idiom_fires_once(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    wf = make_workflow([
        {"compute": {"into": "alarmed", "value": "false"}},
        {"loop": {"count": 3, "body": [
            {"alarm": {"if": "not alarmed", "message": "once"}},
            {"compute": {"into": "alarmed", "value": "true"}},
        ]}},
    ])
    report = await _run(client, wf).execute()
    assert len(report.alarms) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_experiment_alarm_block.py -q`
Expected: FAIL (`RunReport` has no attribute `alarms` / `unknown block type`... actually the block loads, but `report.alarms` is missing).

- [ ] **Step 3: Add `AlarmRecord`**

In `src/lab_devices/experiment/errors.py`, after `ToleratedError`:

```python
@dataclass(frozen=True)
class AlarmRecord:
    """An `alarm` block whose condition fired (design 2026-07-16 §4.4). Not an exception: the
    run continued. The record that it happened, so a run that raised alarms is distinguishable
    from a silent one."""

    block_id: str
    message: str
```

- [ ] **Step 4: Add `RunContext.alarms`**

In `src/lab_devices/experiment/context.py`:

Import (add to `from lab_devices.experiment.errors import ...`):

```python
from lab_devices.experiment.errors import AlarmRecord, ToleratedError
```

Add the field to `RunContext` (next to `tolerated`):

```python
    alarms: list[AlarmRecord] = field(default_factory=list)  # alarm blocks that fired (§4.4)
```

- [ ] **Step 5: Add `_run_alarm` and the dispatch arm**

In `src/lab_devices/experiment/execute.py`:

Import (add to the errors import): `AlarmRecord`.

Add the coroutine near `_run_abort`:

```python
async def _run_alarm(block: B.Alarm, ctx: RunContext) -> None:
    """A true condition flags and continues (design 2026-07-16 §2.2)."""
    if _condition(block.if_, ctx):
        ctx.alarms.append(AlarmRecord(str(block.id), block.message))
        ctx.emit("alarm_raised", block.id, message=block.message)
```

Add the dispatch arm in `_execute_inner`, right after the `B.Abort` arm:

```python
    elif isinstance(block, B.Alarm):
        await _run_alarm(block, ctx)
```

- [ ] **Step 6: Add `RunReport.alarms` and populate it**

In `src/lab_devices/experiment/run.py`:

Import (add to the errors import): `AlarmRecord`.

Add the field to `RunReport` (last, with a default, after `tolerated_errors`):

```python
    alarms: tuple[AlarmRecord, ...] = ()  # alarm blocks that fired (design 2026-07-16 §4.4)
```

In `execute()`, add `alarms=tuple(ctx.alarms)` to the successful-path `RunReport(...)`
construction (alongside `tolerated_errors=tuple(ctx.tolerated)`):

```python
            tolerated_errors=tuple(ctx.tolerated),
            alarms=tuple(ctx.alarms),
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_experiment_alarm_block.py -q`
Expected: PASS (all 4).

- [ ] **Step 8: Gates + commit**

Run: `.venv/bin/python -m pytest -q && .venv/bin/mypy src/lab_devices && ruff check . && awk 'length>100' src/lab_devices/experiment/errors.py src/lab_devices/experiment/context.py src/lab_devices/experiment/execute.py src/lab_devices/experiment/run.py tests/test_experiment_alarm_block.py`
Expected: full suite green, `awk` empty.

```bash
git add src/lab_devices/experiment/errors.py src/lab_devices/experiment/context.py src/lab_devices/experiment/execute.py src/lab_devices/experiment/run.py tests/test_experiment_alarm_block.py
git commit -m "feat(experiment): alarm block emits event + RunReport.alarms, run continues"
```

---

### Task 5: Studio backend — grammar parity + report plumbing

**Files:**
- Modify: `webapp/backend/experiment_studio/roles.py`
- Modify: `webapp/backend/experiment_studio/runner.py`
- Test: `webapp/backend/tests/test_roles.py`

**Interfaces:**
- Consumes: engine `serialize._BUILDERS` (now includes `abort`/`alarm`); `RunReport.alarms`.
- Produces: `abort`/`alarm` in `roles._LEAF_BLOCKS`; `alarms` key in the runner's report payload.

- [ ] **Step 1: Confirm the parity test currently fails after Task 1**

The parity test asserts `_DEVICE_BLOCKS ∪ _CHILD_LISTS ∪ _LEAF_BLOCKS == set(serialize._BUILDERS)`.
Task 1 added `abort`/`alarm` to `_BUILDERS`, so this test is now RED.

Run: `webapp/backend/.venv/bin/python -m pytest webapp/backend/tests/test_roles.py -k grammar -q`
Expected: FAIL (walker grammar missing `abort`, `alarm`).

- [ ] **Step 2: Add both to `_LEAF_BLOCKS`**

In `webapp/backend/experiment_studio/roles.py`:

```python
_LEAF_BLOCKS = ("wait", "operator_input", "group_ref", "compute", "record", "abort", "alarm")
```

- [ ] **Step 3: Run the parity test to verify it passes**

Run: `webapp/backend/.venv/bin/python -m pytest webapp/backend/tests/test_roles.py -k grammar -q`
Expected: PASS.

- [ ] **Step 4: Write the failing report-plumbing test**

Append to `webapp/backend/tests/test_roles.py` (or the runner test file if the project keeps
report-payload tests there — check `webapp/backend/tests/` for an existing `finalize`/`payload`
test and colocate). Minimal direct test of the payload builder — locate the report-dict builder
in `runner.py` (the `payload = {...}` near line 160) and add a unit test that a `RunReport`
carrying one `AlarmRecord` yields an `alarms` entry. If the builder is not independently callable,
add the assertion to the existing runner integration test that inspects a finalized payload:

```python
def test_report_payload_carries_alarms():
    from lab_devices.experiment.errors import AlarmRecord
    from lab_devices.experiment.run import RunReport
    from lab_devices.experiment.state import RunState
    from lab_devices.experiment.runlog import InMemoryRunLog
    report = RunReport(
        status="completed", error=None, finalize_errors=(), state=RunState(),
        log=InMemoryRunLog(), alarms=(AlarmRecord("blocks[0]", "tube 3 contaminated"),),
    )
    # <call the runner's payload builder with report=report; the exact call mirrors the
    #  existing tolerated_errors payload test in this file>
    payload = _build_payload(report)  # adapt to the real helper name in runner.py
    assert payload["alarms"] == [{"block_id": "blocks[0]", "message": "tube 3 contaminated"}]
```

If `runner.py`'s payload builder is a private method not unit-testable in isolation, instead
extend the existing runner test that asserts on `tolerated_errors` to also assert `alarms == []`
on a clean run, and add a dedicated engine-level test in `tests/test_experiment_run_facade.py`
that a run with an `alarm` block populates `report.alarms` (already covered by Task 4 — reference
it and skip a duplicate). The load-bearing assertion is Step 6's payload key.

- [ ] **Step 5: Add the `alarms` key to the payload**

In `webapp/backend/experiment_studio/runner.py`, in the `payload = {...}` dict (right after the
`tolerated_errors` entry, ~line 175):

```python
        # alarm blocks that fired (design 2026-07-16 §4.4); a completed run that raised alarms
        # must not look identical to a silent one. Field-by-field payload: add here or it drops.
        "alarms": (
            [{"block_id": a.block_id, "message": a.message} for a in report.alarms]
            if report
            else []
        ),
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `webapp/backend/.venv/bin/python -m pytest webapp/backend/tests -q`
Expected: PASS.

- [ ] **Step 7: Gates + commit**

Run: `webapp/backend/.venv/bin/python -m pytest webapp/backend/tests -q && ruff check webapp/backend && awk 'length>100' webapp/backend/experiment_studio/roles.py webapp/backend/experiment_studio/runner.py`
Expected: pass, `awk` empty.

```bash
git add webapp/backend/experiment_studio/roles.py webapp/backend/experiment_studio/runner.py webapp/backend/tests/test_roles.py
git commit -m "feat(studio-backend): abort/alarm grammar parity + alarms in run report payload"
```

---

### Task 6: Studio frontend — events, report summary, types, builder degradation

**Files:**
- Modify: `webapp/frontend/src/run/describeEvent.ts`
- Modify: `webapp/frontend/src/run/describeEvent.test.ts`
- Modify: `webapp/frontend/src/run/reportSummary.ts`
- Modify: `webapp/frontend/src/run/reportSummary.test.ts`
- Modify: `webapp/frontend/src/types/records.ts`
- Modify: `webapp/frontend/src/records/RecordViewer.tsx` and `webapp/frontend/src/run/RunView.tsx` (surface `alarmSummary`, mirroring where `toleratedSummary` is rendered)
- Modify: `webapp/frontend/src/builder/convert.ts`

**Interfaces:**
- Consumes: backend `abort_raised`/`alarm_raised` events; report `alarms` field.
- Produces: `alarmSummary(report)`; `AlarmJson` type; `abort`/`alarm` handled in `convert.ts`.

- [ ] **Step 1: Write the failing frontend tests**

In `webapp/frontend/src/run/describeEvent.test.ts`, add:

```typescript
it('describes abort_raised and alarm_raised', () => {
  expect(describeEvent({ kind: 'abort_raised', data: { message: 'contaminated' } }))
    .toBe('run aborted by workflow: contaminated')
  expect(describeEvent({ kind: 'alarm_raised', data: { message: 'tube 3 flagged' } }))
    .toBe('alarm: tube 3 flagged')
})
```

In `webapp/frontend/src/run/reportSummary.test.ts`, add (mirror the existing `toleratedSummary`
tests in that file):

```typescript
it('summarizes alarms, null when none', () => {
  expect(alarmSummary({ alarms: [] } as never)).toBeNull()
  expect(alarmSummary({ alarms: [{ block_id: 'blocks[0]', message: 'lost' }] } as never))
    .toBe('1 alarm(s): blocks[0]: lost')
})
```

Add the import of `alarmSummary` to that test file's existing import from `./reportSummary`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `npm --prefix webapp/frontend run test -- describeEvent reportSummary`
Expected: FAIL (`alarmSummary` undefined; new event cases missing).

- [ ] **Step 3: Add the event cases**

In `webapp/frontend/src/run/describeEvent.ts`, add before the `default:` case:

```typescript
    case 'abort_raised': return `run aborted by workflow: ${s(d.message)}`
    case 'alarm_raised': return `alarm: ${s(d.message)}`
```

- [ ] **Step 4: Add the `alarms` type and `alarmSummary`**

In `webapp/frontend/src/types/records.ts`, add after `ToleratedErrorJson`:

```typescript
export interface AlarmJson {
  block_id: string
  message: string
}
```

And add to `RecordReport` (after `tolerated_errors`):

```typescript
  // alarm blocks that fired (design 2026-07-16 §4.4); a completed run with alarms is not silent.
  alarms?: AlarmJson[]
```

In `webapp/frontend/src/run/reportSummary.ts`, add (mirroring `toleratedSummary`):

```typescript
/** Formats the alarms line, or null when there are none. A run that raised alarms still reports
 * status 'completed' — this line is what stops it looking identical to a silent run (design
 * 2026-07-16 §4.4). */
export function alarmSummary(report: RecordReport | null): string | null {
  const alarms = report?.alarms ?? []
  if (alarms.length === 0) return null
  const list = alarms.map((a) => `${a.block_id}: ${a.message}`).join('; ')
  return `${alarms.length} alarm(s): ${list}`
}
```

- [ ] **Step 5: Surface `alarmSummary` in the UI**

In `webapp/frontend/src/run/RunView.tsx` and `webapp/frontend/src/records/RecordViewer.tsx`,
find where `toleratedSummary(report)` is rendered and add a sibling line for `alarmSummary(report)`
(import it from `../run/reportSummary`), rendered the same way (only when non-null). Match the
surrounding JSX exactly — one line, same panel/class as the tolerated-errors line.

- [ ] **Step 6: Builder graceful degradation for `abort`/`alarm`**

In `webapp/frontend/src/builder/convert.ts`, replace the single `case 'for_each':` throw with a
grouped case that names all known-but-unsupported block types (keep the specific message):

```typescript
    case 'for_each':
      throw new DocConvertError(
        'for_each is not yet supported in the builder (author it as JSON; it runs and charts)',
      )
    case 'abort':
    case 'alarm':
      throw new DocConvertError(
        `${kind} is not yet supported in the builder (author it as JSON; it runs and charts)`,
      )
```

(This keeps the canvas non-crashing and specific, exactly as `for_each`/`compute`/`record` are
handled. A morbidostat doc already imports/runs/charts and is not canvas-editable.)

- [ ] **Step 7: Run tests + build to verify they pass**

Run: `npm --prefix webapp/frontend run test -- describeEvent reportSummary && npm --prefix webapp/frontend run build`
Expected: tests PASS; build succeeds (no TS errors).

- [ ] **Step 8: Commit**

```bash
git add webapp/frontend/src/run/describeEvent.ts webapp/frontend/src/run/describeEvent.test.ts webapp/frontend/src/run/reportSummary.ts webapp/frontend/src/run/reportSummary.test.ts webapp/frontend/src/types/records.ts webapp/frontend/src/run/RunView.tsx webapp/frontend/src/records/RecordViewer.tsx webapp/frontend/src/builder/convert.ts
git commit -m "feat(studio-frontend): render abort/alarm events + alarm summary; builder degrades gracefully"
```

---

### Task 7: The demonstrator — morbidostat contamination guard + emergency stop

**Files:**
- Modify: `examples/morbidostat.json`
- Modify: `examples/morbidostat-demo-speed.json`
- Modify: `examples/README.md`
- Test: `tests/test_examples_morbidostat.py`
- Create: `tests/fixtures/morbidostat_expanded.json` (golden expansion) — only if the existing test uses a golden fixture; otherwise skip and rely on the integration test.

**Interfaces:**
- Consumes: `abort`/`alarm` blocks (Tasks 1–4); the existing `service(tube)` group + `for_each` scaffolding.

**Design of the additions (apply to both example files; constants differ by speed):**

1. **Seed a latch per tube.** In the existing `for_each … compute c_{tube}=0` seed block, add a
   sibling seeded compute in the same `for_each` body: `{"compute": {"into": "contaminated_{tube}", "value": "false"}}` and `{"compute": {"into": "alarmed_{tube}", "value": "false"}}`.

2. **Collect the emergency-stop input.** Add an `operator_input` at setup:
   `{"operator_input": {"name": "emergency_stop", "type": "bool", "prompt": "Emergency stop the run?"}}` (default answered `false` in the unattended provider / the example's operator answers).

3. **Whole-run aborts at the top of the cycle loop body** (before the OD reads):
   - `{"abort": {"if": "emergency_stop", "message": "operator emergency stop"}}`
   - `{"abort": {"if": "contaminated_1 and contaminated_2 and contaminated_3", "message": "all vials contaminated — nothing left to run"}}`

4. **Per-tube contamination detection inside the `service(tube)` group**, at the top of the
   group body (before the existing freshness `branch`):
   - Latch: `{"compute": {"into": "contaminated_{tube}", "value": "contaminated_{tube} or (count(od_{tube}, last=Wc) > 0 and c_{tube} >= stock_ceiling and mean(od_{tube}, last=Wc) > od_ceiling)"}}`
   - Rising-edge alarm: `{"alarm": {"if": "contaminated_{tube} and not alarmed_{tube}", "message": "tube {tube} contaminated — dropped from service"}}`
   - Latch the alarm: `{"compute": {"into": "alarmed_{tube}", "value": "alarmed_{tube} or contaminated_{tube}"}}`
   - Wrap the existing service `branch` in `{"branch": {"if": "not contaminated_{tube}", "then": [ <existing service branch> ]}}` so a contaminated tube is skipped entirely.

**Constants** (pin exactly, matching each file's OD/pace scaling — read the existing constants in
each file first):
- `Wc` (contamination window): use the file's existing cycle-freshness window (`45s` in
  demo-speed, the `11min`-class window in the faithful doc) so the mean spans this cycle's samples.
- `od_ceiling`: a value above the demo's normal steady-state OD band (contamination = OD stuck
  high). Since the preprod sim reads OD `0.0`, this never fires on that hardware (the honest gap);
  set it to a value the FakeLab integration test drives past.
- `stock_ceiling`: `stock_a * 0.99` where `stock_a` is the existing max-drug concentration binding
  (read the exact binding/name from the file; if the concentration recursion uses a literal `C`,
  reuse that literal).

- [ ] **Step 1: Read the current example constants**

Run: `.venv/bin/python -c "import json; w=json.load(open('examples/morbidostat-demo-speed.json'))['workflow']; import pprint; pprint.pp([b for b in w['groups']['service']['body']])"`
and the same for `examples/morbidostat.json`. Note the exact stream names, the freshness window,
the concentration binding/literal, and the steady-state OD band, to pin `Wc`/`od_ceiling`/`stock_ceiling`.

- [ ] **Step 2: Write the failing integration tests**

In `tests/test_examples_morbidostat.py` (this test loads the doc, expands, role-substitutes, and
runs on FakeLab; follow the existing helpers in that file), add:

```python
async def test_operator_emergency_stop_aborts_and_finalizes():
    # Drive emergency_stop=True via the scripted input provider; the run must abort and sweep.
    run = _build_run(EMERGENCY_STOP_INPUTS)   # helper in this file; emergency_stop -> True
    with pytest.raises(AbortSignalError):
        await run.execute()
    assert run.report.status == "aborted"
    assert "abort_raised" in [e.kind for e in run.report.log.events]
    assert "finalize_finished" in [e.kind for e in run.report.log.events]


async def test_contaminated_tube_is_alarmed_and_dropped_from_service():
    # Script tube-3 OD to stay high while its drug concentration is maxed (contamination),
    # other tubes healthy. Tube 3 fires one alarm, receives no further injection; others run.
    run = _build_run(CONTAMINATION_OD_SCRIPT)   # FakeLab OD script per the helper in this file
    report = await run.execute()
    assert report.status == "completed"
    msgs = [a.message for a in report.alarms]
    assert any("tube 3 contaminated" in m for m in msgs)
    assert msgs.count(next(m for m in msgs if "tube 3" in m)) == 1  # fired once (latched)
    # tube 3 received no drug/medium injection after contamination (assert via verbs / no
    # dispense on tube 3's line past the contamination cycle — mirror the file's existing
    # injection-count assertions)
```

Adapt `_build_run`, `EMERGENCY_STOP_INPUTS`, and `CONTAMINATION_OD_SCRIPT` to the concrete
harness already in `tests/test_examples_morbidostat.py` (it already builds a FakeLab, scripts OD,
and runs the doc — reuse those seams; do not invent a new harness). Import `AbortSignalError`.

- [ ] **Step 3: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_examples_morbidostat.py -k "emergency or contaminated" -q`
Expected: FAIL (blocks absent from the doc).

- [ ] **Step 4: Edit both example JSON files**

Apply the additions from the design block above to `examples/morbidostat-demo-speed.json` and
`examples/morbidostat.json`, pinning the constants read in Step 1. Validate each after editing:

```bash
.venv/bin/python -c "from lab_devices.experiment.serialize import workflow_from_dict; from lab_devices.experiment.validate import validate; from lab_devices.experiment.expand import expand_dict; import json; \
d=json.load(open('examples/morbidostat-demo-speed.json'))['workflow']; validate(workflow_from_dict(d)); print('demo-speed OK')"
```
(and the faithful doc). Expected: no `ValidationError` (freshness guards satisfied, latches
seeded before use).

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_examples_morbidostat.py -q`
Expected: PASS — including the **pre-existing IC50 control-loop test unchanged** (the new blocks
are inert on the healthy, no-emergency path: behavior preserved).

- [ ] **Step 6: Update `examples/README.md`**

Add prose describing: the contamination latch + per-vial `alarm` + drop-from-service; the
whole-run `abort`s (all-contaminated and operator `emergency_stop`); the fire-once alarm idiom
(alarm-on-edge then `compute` latch); and the honest gap (contamination firing is proven in
FakeLab; the operator abort is the real-hardware proof because the sim reads OD 0.0).

- [ ] **Step 7: Gates + commit**

Run: `.venv/bin/python -m pytest -q && .venv/bin/mypy src/lab_devices && ruff check . && awk 'length>100' tests/test_examples_morbidostat.py`
Expected: full suite green, `awk` empty.

```bash
git add examples/morbidostat.json examples/morbidostat-demo-speed.json examples/README.md tests/test_examples_morbidostat.py
git commit -m "example(morbidostat): contamination alarm + drop-from-service + emergency/all-lost abort"
```

---

### Task 8: Documentation

**Files:**
- Modify: `docs/experiment-engine-limitations.md`
- Modify: `docs/superpowers/specs/2026-07-07-experiment-orchestrator-design.md`

- [ ] **Step 1: Rewrite limitations #7**

In `docs/experiment-engine-limitations.md`, rewrite section **## 7. No abort or assert block**
from "what is missing" to "what shipped" (mirror the #1/#3/#4 rewrites): open with a
**SHIPPED (2026-07-16)** line pointing at the design doc; describe `abort` (hard stop → status
`"aborted"`, non-tolerable `AbortSignalError`, finalizer sweep, `abort_raised`) and `alarm`
(flag-and-continue, `alarm_raised`, `RunReport.alarms`, stateless with the latch idiom); keep the
contamination motivation; state the honest gap (§8.3 — contamination firing proven in FakeLab, the
operator abort on real hardware). Keep the original problem statement below as motivation.

- [ ] **Step 2: Update the summary table + closing paragraphs**

Change the `| 7 |` row to strike-through the limitation and name the shipped feature (as the
#0/#1/#3/#4 rows do). Update the closing paragraphs: #7 was named the natural sequel to #0
throughout the doc — mark it done and note that a run can now both survive a dead sensor (#0) and
*flag/halt* on one (#7).

- [ ] **Step 3: Update the parent orchestrator design**

In `docs/superpowers/specs/2026-07-07-experiment-orchestrator-design.md`: §5 (block taxonomy)
gains `abort`/`alarm`; §12 (validation) gains the condition + non-empty-message + abort-`on_error`
rules; §15 (serialization) gains the two new forms.

- [ ] **Step 4: Commit**

```bash
git add docs/experiment-engine-limitations.md docs/superpowers/specs/2026-07-07-experiment-orchestrator-design.md
git commit -m "docs: mark limitations #7 shipped; amend parent design for abort/alarm"
```

---

### Task 9: Preprod validation on `windows_arm64_test_client`

**Files:** none (validation only); capture results in the PR body and a memory note.

**Interfaces:** Consumes the merged-to-branch engine + the rewritten `morbidostat-demo-speed.json`.

- [ ] **Step 1: Sync the branch to preprod and run the demo-speed doc clean**

SSH per the preprod recipe (`ssh khamit@111.88.145.138`, docker exec into the jupyter container).
Run `morbidostat-demo-speed.json` against `windows_arm64_test_client` with `emergency_stop=false`.
Expected: completes; **no spurious `abort_raised` or `alarm_raised`** (the sim reads OD 0.0, so
contamination cannot fire) — the negative control that the new blocks do not misfire.

- [ ] **Step 2: Trigger a real abort on hardware**

Run the same doc with `emergency_stop=true`. Expected: the run raises the `abort`, status
`"aborted"`, `abort_raised` in the run log, and the finalizer sweeps the thermostats/pumps/valves
to safe state (observe `finalize_finished` + the sweep commands). This is the end-to-end
real-hardware proof of the raise → non-tolerance → finalizer path.

- [ ] **Step 3: Record results**

Capture both runs' outcomes (cycles completed, events, finalizer sweep, any dropped samples) for
the PR body. Note the honest gap explicitly: contamination-firing was proven in FakeLab (Task 7),
the operator abort on real hardware here.

- [ ] **Step 4: Update memory**

Update `morbidostat-example-and-engine-limitations` (or add an `abort-alarm` memory) with what the
preprod run showed, and cross-link `[[engine-fault-tolerance]]` (abort is #0's sequel).

---

## Self-Review

**Spec coverage:**
- §2.1/§2.2 abort/alarm blocks → Tasks 1 (AST/serialize), 3 (abort exec), 4 (alarm exec). ✓
- §3 schema/serialization → Task 1. ✓
- §4.1 executor arms → Tasks 3, 4. ✓
- §4.2 never-tolerated/wrapped/retried → Task 3 (mutation-verified). ✓
- §4.3 status reuse + `_contains_abort` → Task 3. ✓
- §4.4 `RunReport.alarms`/`RunContext.alarms`/`AlarmRecord` → Task 4. ✓
- §5 validation (condition, message, abort-`on_error`, path analysis) → Task 2. ✓
- §6 inherited analysis (for_each expansion) → Task 2 (`test_for_each_abort_expands_per_tube`). ✓
- §7 testing incl. mutation verification → Tasks 3 (Step 7), 4, 7. ✓
- §8 demonstrator + honest gap → Task 7. ✓
- §9 Studio backend + frontend → Tasks 5, 6. ✓
- §11 docs → Task 8. ✓
- Preprod (settled fork) → Task 9. ✓

**Placeholder scan:** Task 5 Step 4 and Task 7 Step 2 intentionally defer the *exact* test-harness
seam names to "the helper already in this file" because those seams are file-local and must be read
at implementation time — the assertions and the code under test are fully specified. Task 7's
numeric constants are deferred to Step 1's read for the documented reason (they are file-specific
and pace-coupled). No other placeholders.

**Type consistency:** `AbortSignalError(block_id, message)`, `AlarmRecord(block_id, message)`,
`RunReport.alarms: tuple[AlarmRecord, ...]`, `RunContext.alarms: list[AlarmRecord]`,
`_contains_abort(exc) -> bool`, `alarmSummary(report)`, `AlarmJson{block_id, message}`, event
kinds `abort_raised`/`alarm_raised` with a `message` field — used consistently across Tasks 3–6.
