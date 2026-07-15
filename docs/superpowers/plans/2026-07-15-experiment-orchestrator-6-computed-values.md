# Computed Bindings & Computed Streams (`compute` + `record`) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add two leaf blocks — `compute` (name a derived scalar into the binding namespace) and `record` (append a computed number to a declared stream) — turning the engine from a reactive sequencer into a controller that holds derived state.

**Architecture:** Both blocks evaluate one value expression through the existing `resolve`/`evaluate` core and store the result: `compute` binds a number-or-boolean into `RunState.bindings` (overwrite → accumulator), `record` appends a number sample into `RunState.streams` and its disk sink (same path `measure` uses → free charting). Neither touches hardware, so both are free of occupancy, jobs, retry, and the finalizer. The path-sensitive validator gains two leaf cases and inherits read-safety, the seed requirement, and the freshness-guard idiom with no new analysis.

**Tech Stack:** Python 3.14, dataclasses, `pytest` (async), `mypy`, `ruff`. Frontend polish only: TypeScript / Vitest.

**Design spec:** `docs/superpowers/specs/2026-07-15-experiment-orchestrator-6-computed-values-design.md`

## Global Constraints

- Source modules: `from __future__ import annotations` + a one-line docstring citing the design §.
- Test files: flat `tests/test_experiment_*.py`, **no** `from __future__ import annotations`, imports at top (ruff `E402`/`F401` are on).
- Line length ≤ 100 over experiment `src` + `tests` (ruff default has no `E501`; enforced by `awk`).
- Gate after every task (from repo root, `.venv` has the deps — bare `python` does not):
  ```bash
  .venv/bin/python -m pytest -q
  .venv/bin/python -m mypy          # uses pyproject files=["src/lab_devices"]; do NOT add `tests`
  .venv/bin/python -m ruff check .
  awk 'length>100{print FILENAME":"NR}' src/lab_devices/experiment/*.py tests/test_experiment_*.py
  ```
  All four clean (the `awk` prints nothing). Note: mypy's declared scope is `src/lab_devices`
  only — the test files are deliberately untyped, so never pass `tests` to mypy. **Known
  transitional state:** after Task 1, mypy reports 2 `union-attr` errors at `execute.py:604`
  (the `Block` union now includes `Compute`/`Record` but `_execute_inner`'s `else` still assumes
  `GroupRef`). Task 2 closes both by adding the two `_execute_inner` arms. Every task from Task 2
  onward must end with mypy fully clean.
- `value` slot type: `ValueExpr = str | int | float | bool` (a string is an expression; a literal passes through).
- **compute** result: finite `number` **or** `bool`. **record** result: finite `number` only (boolean rejected at runtime — a `Stream` sample is a `float`).
- Event kinds: `binding_computed` (`{name, value}`), `sample_recorded` (`{stream, value}`) — the latter is distinct from `measure_recorded` for provenance.
- Disjointness: a stream is written by `measure` XOR `record`; `record.into` must be a declared stream; `compute.into` must not be; no name is both a scalar binding and a stream; a `compute` target may not also be an `operator_input` name.

---

### Task 1: AST + serialization for `compute` / `record`

**Files:**
- Modify: `src/lab_devices/experiment/blocks.py` (add two dataclasses + `Block` union)
- Modify: `src/lab_devices/experiment/serialize.py` (builders, dump cases, `_value` helper)
- Modify: `src/lab_devices/experiment/__init__.py` (export `Compute`, `Record`)
- Test: `tests/test_experiment_serialize.py` (round-trip + load-error cases)

**Interfaces:**
- Produces: `B.Compute(into: str, value: ValueExpr)`, `B.Record(into: str, value: ValueExpr)` — both `BlockBase` subclasses (carry `id`, `label`, `gap_after`, `start_offset`, `retry`, `on_error`). Serializer keys: `{"compute": {"into", "value"}}`, `{"record": {"into", "value"}}`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_experiment_serialize.py`:

```python
def test_compute_roundtrip_expression():
    d = {"compute": {"into": "c", "value": "c * 0.5 + 1"}}
    b = block_from_dict(d)
    assert isinstance(b, B.Compute)
    assert b.into == "c" and b.value == "c * 0.5 + 1"
    assert block_to_dict(b) == d


def test_compute_roundtrip_literal_and_timing():
    d = {"compute": {"into": "seed", "value": 0}, "label": "seed c"}
    b = block_from_dict(d)
    assert isinstance(b, B.Compute)
    assert b.value == 0 and b.label == "seed c"
    assert block_to_dict(b) == d


def test_record_roundtrip():
    d = {"record": {"into": "r_series", "value": "r_1"}}
    b = block_from_dict(d)
    assert isinstance(b, B.Record)
    assert b.into == "r_series" and b.value == "r_1"
    assert block_to_dict(b) == d


def test_compute_requires_into_and_value():
    with pytest.raises(WorkflowLoadError):
        block_from_dict({"compute": {"value": "1"}})
    with pytest.raises(WorkflowLoadError):
        block_from_dict({"compute": {"into": "c"}})


def test_record_value_bad_expression_rejected_at_load():
    from lab_devices.experiment.errors import ExpressionError
    with pytest.raises(ExpressionError):
        block_from_dict({"record": {"into": "r", "value": "1 +"}})


def test_compute_value_object_rejected():
    with pytest.raises(WorkflowLoadError):
        block_from_dict({"compute": {"into": "c", "value": {"nope": 1}}})


def test_workflow_roundtrip_with_compute_and_record():
    doc = {
        "schema_version": 1,
        "persistence": {"default": "in_memory", "format": "jsonl"},
        "streams": {"r_series": {"units": "per_hour"}},
        "blocks": [
            {"compute": {"into": "r_1", "value": "2 * 3"}},
            {"record": {"into": "r_series", "value": "r_1"}},
        ],
    }
    assert workflow_to_dict(workflow_from_dict(doc)) == doc
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_experiment_serialize.py -q -k "compute or record"`
Expected: FAIL (`WorkflowLoadError: unknown block type 'compute'`).

- [ ] **Step 3: Add the dataclasses**

In `src/lab_devices/experiment/blocks.py`, after the `Branch` dataclass and before `GroupRef` (or adjacent to the other leaves):

```python
@dataclass(kw_only=True)
class Compute(BlockBase):
    into: str
    value: ValueExpr  # scalar bound into RunState.bindings (number or boolean)


@dataclass(kw_only=True)
class Record(BlockBase):
    into: str
    value: ValueExpr  # numeric sample appended to a declared stream
```

Extend the `Block` union to include `Compute` and `Record`:

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
)
```

- [ ] **Step 4: Add the serializer builders and dump cases**

In `src/lab_devices/experiment/serialize.py`, add a value helper near `_checked_expr`:

```python
def _value(value: Any, ctx: str) -> B.ValueExpr:
    """A scalar slot: a string is an expression (checked now), a number/bool is a literal."""
    if isinstance(value, str):
        return _checked_expr(value, ctx)
    if isinstance(value, bool) or isinstance(value, (int, float)):
        return value
    raise WorkflowLoadError(
        f"{ctx} must be a number, boolean, or expression string, got {value!r}"
    )
```

Add the two builders (near `_measure`):

```python
def _compute(body: Any, timing: dict[str, Any]) -> B.Block:
    into = _str(_req(body, "into", "compute"), "compute into")
    value = _value(_req(body, "value", "compute"), "compute value")
    return B.Compute(into=into, value=value, **timing)


def _record(body: Any, timing: dict[str, Any]) -> B.Block:
    into = _str(_req(body, "into", "record"), "record into")
    value = _value(_req(body, "value", "record"), "record value")
    return B.Record(into=into, value=value, **timing)
```

Register them in `_BUILDERS`:

```python
    "branch": _branch,
    "group_ref": _group_ref,
    "compute": _compute,
    "record": _record,
```

Add the dump cases in `_dump_body`, before the final `raise`:

```python
    if isinstance(b, B.Compute):
        return "compute", {"into": b.into, "value": b.value}
    if isinstance(b, B.Record):
        return "record", {"into": b.into, "value": b.value}
```

- [ ] **Step 5: Export from the package**

In `src/lab_devices/experiment/__init__.py`, add `Compute` and `Record` to the `from lab_devices.experiment.blocks import (...)` list and to `__all__` (in the `"Block", "Branch", ...` line).

- [ ] **Step 6: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_experiment_serialize.py -q`
Expected: PASS (all, including the new cases).

- [ ] **Step 7: Gate + commit**

Run the four gate commands (Global Constraints). Then:

```bash
git add src/lab_devices/experiment/blocks.py src/lab_devices/experiment/serialize.py \
        src/lab_devices/experiment/__init__.py tests/test_experiment_serialize.py
git commit -m "feat(experiment): compute and record block AST + serialization"
```

---

### Task 2: Executor — `_run_compute` / `_run_record`

**Files:**
- Modify: `src/lab_devices/experiment/execute.py` (`import math`; `_eval_value`, `_run_compute`, `_run_record`; two `_execute_inner` arms)
- Test: `tests/test_experiment_computed.py` (new)

**Interfaces:**
- Consumes: `B.Compute`, `B.Record` (Task 1); `resolve` and `Value` from `evaluate.py`; `RunContext`, `Sample`.
- Produces: `_run_compute(block, ctx)`, `_run_record(block, ctx)` (async, return `None`); events `binding_computed` / `sample_recorded`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_experiment_computed.py`:

```python
import math

import pytest

from lab_devices.experiment import blocks as B
from lab_devices.experiment.context import RunContext, RunOptions
from lab_devices.experiment.errors import EvaluationError
from lab_devices.experiment.execute import _run_compute, _run_record
from lab_devices.experiment.state import RunState, Sample, Stream
from lab_devices.experiment.workflow import Workflow
from tests.fakeclock import FakeClock, drive


class _RecordingStreamSink:
    def __init__(self) -> None:
        self.samples: list[Sample] = []

    def write(self, sample: Sample) -> None:
        self.samples.append(sample)

    def flush(self) -> None: ...
    def close(self) -> None: ...


def _ctx(client, clock, state):
    return RunContext(client=client, workflow=Workflow(schema_version=1), state=state,
                      options=RunOptions(clock=clock))


def _block(kind, **kw):
    b = kind(**kw)
    b.id = "blocks[0]"
    return b


async def test_compute_binds_number(fake_client):
    _, client = fake_client
    clock, state = FakeClock(), RunState()
    ctx = _ctx(client, clock, state)
    await drive(clock, _run_compute(_block(B.Compute, into="c", value="2 * 3"), ctx))
    assert state.bindings["c"] == 6


async def test_compute_binds_boolean(fake_client):
    _, client = fake_client
    clock, state = FakeClock(), RunState()
    state.bindings["od"] = 0.9
    ctx = _ctx(client, clock, state)
    await drive(clock, _run_compute(_block(B.Compute, into="hot", value="od > 0.5"), ctx))
    assert state.bindings["hot"] is True


async def test_compute_accumulator_overwrites_reading_own_prior_value(fake_client):
    _, client = fake_client
    clock, state = FakeClock(), RunState()
    state.bindings["c"] = 0.0
    ctx = _ctx(client, clock, state)
    block = _block(B.Compute, into="c", value="c * 0.5 + 1")
    await drive(clock, _run_compute(block, ctx))
    assert state.bindings["c"] == 1.0
    await drive(clock, _run_compute(block, ctx))
    assert state.bindings["c"] == 1.5


async def test_compute_emits_event(fake_client):
    _, client = fake_client
    clock, state = FakeClock(), RunState()
    ctx = _ctx(client, clock, state)
    await drive(clock, _run_compute(_block(B.Compute, into="c", value="7"), ctx))
    kinds = [(e.kind, e.data) for e in ctx.log_sink.events]
    assert ("binding_computed", {"name": "c", "value": 7}) in kinds


async def test_compute_division_by_zero_raises(fake_client):
    _, client = fake_client
    clock, state = FakeClock(), RunState()
    ctx = _ctx(client, clock, state)
    with pytest.raises(EvaluationError):
        await drive(clock, _run_compute(_block(B.Compute, into="c", value="1 / 0"), ctx))
    assert "c" not in state.bindings


async def test_record_appends_to_stream_and_sink(fake_client):
    _, client = fake_client
    clock, state = FakeClock(), RunState()
    state.streams["r"] = Stream()
    state.bindings["x"] = 0.8
    ctx = _ctx(client, clock, state)
    sink = _RecordingStreamSink()
    ctx.stream_sinks = {"r": sink}
    await drive(clock, _run_record(_block(B.Record, into="r", value="x"), ctx))
    assert [s.value for s in state.streams["r"].samples] == [0.8]
    assert [s.value for s in sink.samples] == [0.8]
    assert sink.samples[0].timestamp == state.streams["r"].samples[0].timestamp


async def test_record_emits_sample_recorded_not_measure_recorded(fake_client):
    _, client = fake_client
    clock, state = FakeClock(), RunState()
    state.streams["r"] = Stream()
    ctx = _ctx(client, clock, state)
    await drive(clock, _run_record(_block(B.Record, into="r", value="1.5"), ctx))
    kinds = [e.kind for e in ctx.log_sink.events]
    assert "sample_recorded" in kinds and "measure_recorded" not in kinds


async def test_record_rejects_boolean(fake_client):
    _, client = fake_client
    clock, state = FakeClock(), RunState()
    state.streams["r"] = Stream()
    ctx = _ctx(client, clock, state)
    with pytest.raises(EvaluationError):
        await drive(clock, _run_record(_block(B.Record, into="r", value="true"), ctx))
    assert len(state.streams["r"].samples) == 0
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_experiment_computed.py -q`
Expected: FAIL (`ImportError: cannot import name '_run_compute'`).

- [ ] **Step 3: Implement the executor arms**

In `src/lab_devices/experiment/execute.py`, add `import math` to the top-of-file imports (after `import asyncio`).

Add the helper + two runners (near `_run_measure`):

```python
def _eval_value(value: B.ValueExpr, ctx: RunContext) -> Value:
    """Shared value-slot evaluation for compute/record (design §3)."""
    return resolve(value, ctx.state, ctx.clock.now())


async def _run_compute(block: B.Compute, ctx: RunContext) -> None:
    """Evaluate and bind a derived scalar; number or boolean (design §3.1)."""
    result = _eval_value(block.value, ctx)
    if isinstance(result, float) and not math.isfinite(result):
        raise EvaluationError(
            f"compute into {block.into!r} got a non-finite value {result!r}"
        )
    ctx.state.bind(block.into, result)
    ctx.emit("binding_computed", block.id, name=block.into, value=result)


async def _run_record(block: B.Record, ctx: RunContext) -> None:
    """Evaluate and append a derived number to a declared stream (design §3.2)."""
    result = _eval_value(block.value, ctx)
    if isinstance(result, bool) or not isinstance(result, (int, float)):
        raise EvaluationError(
            f"record into {block.into!r} requires a number, got {result!r}"
        )
    if not math.isfinite(result):
        raise EvaluationError(
            f"record into {block.into!r} got a non-finite value {result!r}"
        )
    ts = ctx.clock.now()
    value = float(result)
    ctx.state.record(block.into, ts, value)
    sink = ctx.stream_sinks.get(block.into)
    if sink is not None:
        sink.write(Sample(ts, value))
    ctx.emit("sample_recorded", block.id, stream=block.into, value=value)
```

Add the two arms to `_execute_inner`, before the final `else` (group_ref):

```python
    elif isinstance(block, B.Compute):
        await _run_compute(block, ctx)
    elif isinstance(block, B.Record):
        await _run_record(block, ctx)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_experiment_computed.py -q`
Expected: PASS.

- [ ] **Step 5: Gate + commit**

Run the four gate commands. Then:

```bash
git add src/lab_devices/experiment/execute.py tests/test_experiment_computed.py
git commit -m "feat(experiment): execute compute and record blocks"
```

---

### Task 3: Validator — path leaves, type/declaration checks, disjointness

**Files:**
- Modify: `src/lab_devices/experiment/validate.py`
- Test: `tests/test_experiment_validate_computed.py` (new)

**Interfaces:**
- Consumes: `B.Compute`, `B.Record`; existing `_expr_reads`, `_check_expr_type`, `_check_streams_declared`, `infer_type`, `_IDENT_RE`, `_RESERVED_NAMES`, `_iter_all_blocks`, `Diagnostic`.
- Produces: no new public API — `validate()` now covers the two blocks.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_experiment_validate_computed.py`:

```python
from lab_devices.experiment.validate import validate
from tests.experiment_validate_helpers import MEASURE_OD, cmd, diags, wf

SEED_C = {"compute": {"into": "c", "value": "0"}}
STEP_C = {"compute": {"into": "c", "value": "c * 0.5 + 1"}}
INPUT_X = {"operator_input": {"name": "x", "type": "float"}}


def test_seeded_accumulator_is_clean():
    blocks = [SEED_C, {"loop": {"count": 3, "body": [STEP_C]}}]
    assert validate(wf(blocks)) is None


def test_unseeded_accumulator_is_read_before_write():
    blocks = [{"loop": {"count": 3, "body": [STEP_C]}}]
    d = diags(wf(blocks))
    assert any(x.category == "data-flow" and "'c'" in x.message and "before" in x.message
               for x in d)


def test_compute_then_read_binding_clean():
    blocks = [{"compute": {"into": "c", "value": "2 * 3"}},
              cmd("pump_1", "dispense", {"volume_ml": "c"})]
    assert validate(wf(blocks)) is None


def test_record_writes_undeclared_stream():
    d = diags(wf([{"record": {"into": "r", "value": "1"}}]))
    assert any(x.category == "declaration" and "'r'" in x.message for x in d)


def test_record_reading_own_stream_before_first_write():
    blocks = [{"record": {"into": "r", "value": "mean(r, last=5)"}}]
    d = diags(wf(blocks, streams=["r"]))
    assert any(x.category == "data-flow" and "'r'" in x.message for x in d)


def test_record_reading_measured_stream_clean():
    blocks = [MEASURE_OD, {"record": {"into": "r", "value": "last(OD)"}}]
    assert validate(wf(blocks, streams=["OD", "r"])) is None


def test_stream_written_by_both_measure_and_record():
    blocks = [MEASURE_OD, {"record": {"into": "OD", "value": "1"}}]
    d = diags(wf(blocks, streams=["OD"]))
    assert any(x.category == "declaration" and "OD" in x.message
               and "measure" in x.message and "record" in x.message for x in d)


def test_name_is_both_binding_and_stream():
    blocks = [{"compute": {"into": "OD", "value": "1"}}, MEASURE_OD]
    d = diags(wf(blocks, streams=["OD"]))
    assert any(x.category == "declaration" and "OD" in x.message for x in d)


def test_compute_and_operator_input_same_name():
    blocks = [INPUT_X, {"compute": {"into": "x", "value": "2"}}]
    d = diags(wf(blocks))
    assert any(x.category == "declaration" and "'x'" in x.message for x in d)


def test_retry_on_compute_rejected():
    blocks = [{"compute": {"into": "c", "value": "1"},
               "retry": {"attempts": 2, "backoff": "1s"}}]
    d = diags(wf(blocks))
    assert any("retry is only valid on command and measure" in x.message for x in d)


def test_record_value_must_be_number_not_boolean_literal():
    d = diags(wf([{"record": {"into": "r", "value": True}}], streams=["r"]))
    assert any(x.category == "type" and "number" in x.message for x in d)


def test_compute_reading_tolerated_duration_window_needs_guard():
    # a tolerated measure only maybe-writes OD; a duration read of it must be guarded
    blocks = [
        {"measure": {"device": "densitometer_1", "verb": "measure", "into": "OD"},
         "on_error": "continue"},
        {"compute": {"into": "m", "value": "mean(OD, last=5min)"}},
    ]
    d = diags(wf(blocks, streams=["OD"]))
    assert any(x.category == "data-flow" and "OD" in x.message for x in d)
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_experiment_validate_computed.py -q`
Expected: FAIL (most assertions fail — validator ignores the blocks today).

- [ ] **Step 3: Add per-block checks and value helpers**

In `src/lab_devices/experiment/validate.py`, add value-checkers near `_check_condition`:

```python
def _check_compute_value(
    value: object,
    ctx: str,
    w: Workflow,
    binding_types: Mapping[str, BindingType],
    out: list[Diagnostic],
) -> None:
    """compute stores a number OR a boolean; accept either, surface enum-string refs."""
    if not isinstance(value, str):
        if isinstance(value, bool) or isinstance(value, (int, float)):
            return
        out.append(Diagnostic(
            "type", ctx, f"compute value must be a number, boolean, or expression, got {value!r}"
        ))
        return
    try:
        expr = parse_expression(value)
    except ExpressionError as exc:
        out.append(Diagnostic("type", ctx, f"invalid expression: {exc}"))
        return
    for problem in infer_type(expr, binding_types).problems:
        out.append(Diagnostic("type", ctx, problem))
    _check_streams_declared(value, ctx, w, out)


def _check_record_value(
    value: object,
    ctx: str,
    w: Workflow,
    binding_types: Mapping[str, BindingType],
    out: list[Diagnostic],
) -> None:
    """record stores a number; a boolean literal or a boolean expression is an error."""
    if not isinstance(value, str):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            out.append(Diagnostic(
                "type", ctx, f"record value must be a number or expression, got {value!r}"
            ))
        return
    _check_expr_type(value, "number", ctx, binding_types, out)
    _check_streams_declared(value, ctx, w, out)


def _check_compute(
    b: B.Compute,
    path: str,
    w: Workflow,
    binding_types: Mapping[str, BindingType],
    out: list[Diagnostic],
) -> None:
    usable = (
        isinstance(b.into, str)
        and _IDENT_RE.fullmatch(b.into) is not None
        and b.into not in _RESERVED_NAMES
    )
    if not usable:
        out.append(Diagnostic(
            "block", path, f"compute into {b.into!r} is not a usable binding name"
        ))
    _check_compute_value(b.value, f"{path} compute value", w, binding_types, out)


def _check_record(
    b: B.Record,
    path: str,
    w: Workflow,
    binding_types: Mapping[str, BindingType],
    out: list[Diagnostic],
) -> None:
    if not isinstance(b.into, str):
        out.append(Diagnostic(
            "block", path, f"record into must be a stream name, got {b.into!r}"
        ))
    elif b.into not in w.streams:
        out.append(Diagnostic(
            "declaration", path, f"record writes undeclared stream {b.into!r}"
        ))
    _check_record_value(b.value, f"{path} record value", w, binding_types, out)
```

Add dispatch arms to `_check_block` (alongside the other `elif isinstance` arms):

```python
    elif isinstance(block, B.Compute):
        _check_compute(block, path, w, binding_types, out)
    elif isinstance(block, B.Record):
        _check_record(block, path, w, binding_types, out)
```

- [ ] **Step 4: Add the workflow-global namespace check**

Add `_check_namespaces` near `_check_defaults`:

```python
def _check_namespaces(w: Workflow, out: list[Diagnostic]) -> None:
    """Disjointness across the binding and stream namespaces (design §6)."""
    measure_streams: set[str] = set()
    record_streams: set[str] = set()
    input_names: set[str] = set()
    compute_names: set[str] = set()
    for _, b in _iter_all_blocks(w):
        if isinstance(b, B.Measure) and isinstance(b.into, str):
            measure_streams.add(b.into)
        elif isinstance(b, B.Record) and isinstance(b.into, str):
            record_streams.add(b.into)
        elif isinstance(b, B.OperatorInput) and isinstance(b.name, str):
            input_names.add(b.name)
        elif isinstance(b, B.Compute) and isinstance(b.into, str):
            compute_names.add(b.into)
    binding_names = input_names | compute_names
    declared = set(w.streams)
    for s in sorted(measure_streams & record_streams):
        out.append(Diagnostic(
            "declaration", "streams",
            f"stream {s!r} is written by both measure and record; a stream is measured "
            f"or computed, never both",
        ))
    for n in sorted(binding_names & declared):
        out.append(Diagnostic(
            "declaration", "streams",
            f"name {n!r} is used as both a scalar binding and a stream",
        ))
    for n in sorted(compute_names & input_names):
        out.append(Diagnostic(
            "declaration", "streams",
            f"name {n!r} is written by both operator_input and compute; a binding has "
            f"one kind of writer",
        ))
```

Call it in `validate()`, right after `_check_defaults(workflow, out)`:

```python
    _check_defaults(workflow, out)
    _check_namespaces(workflow, out)
```

- [ ] **Step 5: Add the path-analysis leaf arms**

In `_visit_body`, add before the `GroupRef` arm (`elif isinstance(b, B.GroupRef)`):

```python
    elif isinstance(b, B.Compute):
        _expr_reads(b.value, f"{path} compute value", state, c)
        if isinstance(b.into, str):
            state.bindings.add(b.into)
    elif isinstance(b, B.Record):
        _expr_reads(b.value, f"{path} record value", state, c)
        if isinstance(b.into, str):
            state.streams.add(b.into)
```

(Order matters: check the value's reads against the *current* state before adding this block's own write, so a self-reference is only satisfied by a prior seed.)

- [ ] **Step 6: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_experiment_validate_computed.py -q`
Expected: PASS.

- [ ] **Step 7: Gate + commit**

Run the four gate commands. Then:

```bash
git add src/lab_devices/experiment/validate.py tests/test_experiment_validate_computed.py
git commit -m "feat(experiment): validate compute and record (paths, types, disjointness)"
```

---

### Task 4: End-to-end integration through `ExperimentRun`

**Files:**
- Test: `tests/test_experiment_e2e_computed.py` (new)

**Interfaces:**
- Consumes: `ExperimentRun`, `RunOptions`, `make_workflow`, `add_standard_devices`, `FakeClock`, `drive`. Exercises validate + execute together on a controller-shaped workflow.

- [ ] **Step 1: Write the failing test**

Create `tests/test_experiment_e2e_computed.py`:

```python
from lab_devices.experiment import ExperimentRun, RunOptions
from tests.experiment_run_helpers import add_standard_devices, make_workflow
from tests.fakeclock import FakeClock, drive


def make_run(client, wf):
    return ExperimentRun(client, wf, options=RunOptions(clock=FakeClock()))


async def test_accumulator_and_recording_over_cycles(fake_client):
    """Seed c=0, then each cycle measure OD, compute a decay recursion, record c and a
    derived value into computed streams. Assert the recorded series and the final binding."""
    fake, client = fake_client
    add_standard_devices(fake)
    wf = make_workflow(
        [
            {"compute": {"into": "c", "value": "0"}},
            {"loop": {"count": 3, "body": [
                {"measure": {"device": "densitometer_1", "verb": "measure", "into": "OD"}},
                {"compute": {"into": "c", "value": "c * 0.5 + 1"}},
                {"record": {"into": "c_series", "value": "c"}},
                {"record": {"into": "od_copy", "value": "last(OD)"}},
            ]}},
        ],
        streams={"OD": {"units": "AU"}, "c_series": {}, "od_copy": {}},
    )
    run = make_run(client, wf)
    report = await drive(run._options.clock, run.execute())

    assert report.status == "completed"
    c_series = [s.value for s in report.state.streams["c_series"].samples]
    assert c_series == [1.0, 1.5, 1.75]           # 0→1→1.5→1.75
    assert report.state.bindings["c"] == 1.75
    assert len(report.state.streams["od_copy"].samples) == 3


async def test_record_only_stream_is_precreated_empty(fake_client):
    """A record-only declared stream exists at count()==0 before its first write."""
    fake, client = fake_client
    add_standard_devices(fake)
    wf = make_workflow(
        [{"branch": {"if": "count(r_series) > 0", "then": [
            {"command": {"device": "pump_1", "verb": "stop"}}]}},
         {"record": {"into": "r_series", "value": "1.0"}}],
        streams={"r_series": {}},
    )
    run = make_run(client, wf)
    report = await drive(run._options.clock, run.execute())
    assert report.status == "completed"
    assert [s.value for s in report.state.streams["r_series"].samples] == [1.0]
```

- [ ] **Step 2: Run to verify it passes (it should — Tasks 2 & 3 make it green)**

Run: `.venv/bin/python -m pytest tests/test_experiment_e2e_computed.py -q`
Expected: PASS. If FAIL, the defect is in Task 2/3 wiring — fix there, not here. (This task is the integration gate; it has no production code of its own.)

- [ ] **Step 3: Gate + commit**

Run the four gate commands. Then:

```bash
git add tests/test_experiment_e2e_computed.py
git commit -m "test(experiment): end-to-end compute/record accumulator and recording"
```

---

### Task 5: Studio backend — pass-through confirmation

**Files:**
- Modify: `webapp/backend/experiment_studio/roles.py` (extend the `_LEAF_BLOCKS` doc tuple)
- Test: `webapp/backend/tests/test_roles.py` (add a pass-through case; create file only if absent — otherwise append)

**Interfaces:**
- Consumes: `substitute` from `roles.py`.
- Produces: nothing new — confirms `compute`/`record` survive role substitution untouched.

- [ ] **Step 1: Locate the backend test file and venv**

Run: `ls webapp/backend/tests/ | grep -i roles` and `ls webapp/backend/.venv/bin/python`
Expected: find the roles test file and the backend venv. If no roles test exists, create `webapp/backend/tests/test_roles.py` with the import block used by the other backend tests (check a sibling test's imports).

- [ ] **Step 2: Write the failing test**

Append to the roles test file:

```python
def test_substitute_passes_compute_and_record_through():
    from experiment_studio.roles import substitute
    wf = {
        "schema_version": 1,
        "streams": {"c_series": {}},
        "blocks": [
            {"measure": {"device": "od", "verb": "measure", "into": "OD"}},
            {"compute": {"into": "c", "value": "last(OD)"}},
            {"record": {"into": "c_series", "value": "c"}},
        ],
    }
    out, diags = substitute(wf, {"od": "densitometer_1"})
    assert diags == []
    assert out["blocks"][0]["measure"]["device"] == "densitometer_1"
    # compute/record carry no device and are returned byte-identical
    assert out["blocks"][1] == {"compute": {"into": "c", "value": "last(OD)"}}
    assert out["blocks"][2] == {"record": {"into": "c_series", "value": "c"}}
```

- [ ] **Step 3: Run to verify it passes (pass-through is already correct)**

Run: `cd webapp/backend && .venv/bin/python -m pytest tests/test_roles.py -q -k compute_and_record; cd ../..`
Expected: PASS — `_walk` already skips non-device, non-container blocks. If it FAILS, the walker is mutating them; fix `_walk` to leave them untouched.

- [ ] **Step 4: Update the doc tuple**

In `webapp/backend/experiment_studio/roles.py`, extend `_LEAF_BLOCKS` for documentation accuracy:

```python
_LEAF_BLOCKS = ("wait", "operator_input", "group_ref", "compute", "record")
```

- [ ] **Step 5: Gate (backend) + commit**

Run: `cd webapp/backend && .venv/bin/python -m pytest -q && .venv/bin/python -m ruff check . ; cd ../..`
Then:

```bash
git add webapp/backend/experiment_studio/roles.py webapp/backend/tests/test_roles.py
git commit -m "test(studio): role substitution passes compute/record through untouched"
```

---

### Task 6: Studio frontend — event-log display (polish)

**Files:**
- Modify: `webapp/frontend/src/run/describeEvent.ts` (two arms)
- Modify: `webapp/frontend/src/run/EventLog.tsx` (two color entries)
- Test: `webapp/frontend/src/run/describeEvent.test.ts` (two cases)

**Interfaces:**
- Consumes: the `binding_computed` / `sample_recorded` event kinds emitted by the engine (Task 2).
- Produces: human-readable log lines for the two kinds. (The live chart already renders computed streams — it sources from `/streams`, not events; see spec §7.1. No chart change.)

- [ ] **Step 1: Write the failing test**

Add to `webapp/frontend/src/run/describeEvent.test.ts`:

```typescript
  it('describes binding_computed and sample_recorded', () => {
    expect(d('binding_computed', { name: 'c_1', value: 3.14 })).toBe('c_1 = 3.14')
    expect(d('sample_recorded', { stream: 'c_series_1', value: 3.14 })).toBe(
      'c_series_1 = 3.14',
    )
  })
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd webapp/frontend && npm run test -- src/run/describeEvent.test.ts; cd ../..`
Expected: FAIL (falls through to the default formatter).

- [ ] **Step 3: Add the describeEvent arms**

In `webapp/frontend/src/run/describeEvent.ts`, add next to the `measure_recorded` case:

```typescript
    case 'binding_computed': return `${s(d.name)} = ${s(d.value)}`
    case 'sample_recorded': return `${s(d.stream)} = ${s(d.value)}`
```

- [ ] **Step 4: Add the color entries**

In `webapp/frontend/src/run/EventLog.tsx`, alongside `measure_recorded`:

```typescript
  binding_computed: 'text-teal-700',
  sample_recorded: 'text-blue-700',
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `cd webapp/frontend && npm run test -- src/run/describeEvent.test.ts; cd ../..`
Expected: PASS.

- [ ] **Step 6: Gate (frontend) + commit**

Run: `cd webapp/frontend && npm run test && npm run typecheck && npm run lint; cd ../..`
Then:

```bash
git add webapp/frontend/src/run/describeEvent.ts webapp/frontend/src/run/EventLog.tsx \
        webapp/frontend/src/run/describeEvent.test.ts
git commit -m "feat(studio): event-log arms for binding_computed and sample_recorded"
```

---

### Task 7: Rewrite the morbidostat example as a controller

**Files:**
- Modify: `examples/morbidostat.json`
- Modify: `examples/morbidostat-demo-speed.json`
- Modify: `examples/README.md`

**Interfaces:**
- Consumes: the shipped `compute`/`record` blocks. The rewrite must `load_and_validate` clean and preserve the existing freshness-guard and retry/on_error behavior.

**Transformation rules (apply per tube `i ∈ {1,2,3}` in both example files; the demo-speed doc uses the same shape with its scaled constants):**

1. **Declare computed streams** in `workflow.streams` (disjoint from the measured `od_i`/`blank_i`):
   ```json
   "c_series_1": {"units": "x_MIC"}, "r_series_1": {"units": "per_hour"},
   ```
   (and `_2`, `_3`).

2. **Seed the drug-concentration accumulator** once, before the cycle loop, per tube:
   ```json
   { "compute": {"into": "c_1", "value": "0"} }
   ```

3. **Inside each tube's guarded decision subtree** (already gated by `count(od_i, last=D) > 0`),
   after the growth-rate branch condition is available, compute the growth rate as a **named
   binding** and record it, replacing the inline expression in the branch `if`:
   ```json
   { "compute": {"into": "r_1",
                 "value": "24 * (mean(od_1, last=5) - mean(od_1, last=10)) / last(od_1)"} },
   { "record": {"into": "r_series_1", "value": "r_1"} },
   ```
   Then the decision branch reads the binding: `"if": "r_1 > r_dil"` (was the full inline
   expression). Preserve the existing `od_min` freshness/positivity guards exactly.

4. **Update the concentration accumulator on each injection arm**, and record it once per cycle
   after the decision:
   - On the **drug** arm (after the drug dispense):
     ```json
     { "compute": {"into": "c_1", "value": "c_1 * V/(V+dV) + C * dV/(V+dV)"} }
     ```
   - On the **medium** arm (after the medium dispense):
     ```json
     { "compute": {"into": "c_1", "value": "c_1 * V/(V+dV)"} }
     ```
   - After the branch (once per cycle, in both arms' common tail — or in each arm):
     ```json
     { "record": {"into": "c_series_1", "value": "c_1"} }
     ```
   `V`, `dV`, `C` are the working-volume, injection-volume, and stock-concentration constants —
   add them as workflow-level seed `compute` blocks (`compute V = <ml>`, etc.) before the loop, or
   inline the numeric literals if they are single-use. Prefer named seeds so the recursion reads
   like the algorithm. `dV` is the same in both arms (identical injection volume), which is why the
   dilution rate is arm-independent — keep it one constant.

5. **The `c_i` accumulator must stay inside the tube's freshness guard.** A skipped cycle (no
   reading) must not update `c_i` — the guard already wraps the decision; keep the accumulator
   updates inside it so a dead sensor freezes `c_i` rather than latching it.

- [ ] **Step 1: Read the current example to learn its exact shape**

Run: `.venv/bin/python -m json.tool examples/morbidostat-demo-speed.json | head -120`
Study the tube-service subtree, the freshness guard window, and where the injection dispenses sit.

- [ ] **Step 2: Rewrite `morbidostat-demo-speed.json` first (smaller / faster to validate)**

Apply the transformation rules above to all three tubes. Keep every existing retry/on_error and
the `count(od_i, last=45s) > 0` freshness guard.

- [ ] **Step 3: Validate the demo-speed doc**

Run:
```bash
.venv/bin/python -c "from lab_devices.experiment import load_and_validate; \
import json; d=json.load(open('examples/morbidostat-demo-speed.json')); \
from lab_devices.experiment.serialize import workflow_from_dict; \
from lab_devices.experiment.validate import validate; \
w=workflow_from_dict(d['workflow']); validate(w); print('OK')"
```
Expected: `OK`. If a `ValidationError` prints, read each `Diagnostic` and fix (most likely an
unseeded `c_i`, a `c_series_i` collision, or an undeclared computed stream).

- [ ] **Step 4: Apply the same rewrite to `morbidostat.json`** (faithful doc, `count(od_i, last=11min) > 0`), and validate it the same way.

- [ ] **Step 5: Update `examples/README.md`**

In the walkthrough prose: state that the workflow now **computes and records** the drug
concentration `c_i` (the sawtooth is chartable) and the growth rate `r_i`, and remove the
"reconstructed offline" caveat for `c`. Keep the freshness-guard and dropped-sample caveats.

- [ ] **Step 6: Commit**

```bash
git add examples/morbidostat.json examples/morbidostat-demo-speed.json examples/README.md
git commit -m "feat(examples): morbidostat computes drug concentration and growth rate"
```

---

### Task 8: Documentation — limitations + parent design

**Files:**
- Modify: `docs/experiment-engine-limitations.md`
- Modify: `docs/superpowers/specs/2026-07-07-experiment-orchestrator-design.md`

- [ ] **Step 1: Update the limitations doc**

- Rewrite **§1 (No computed bindings)** and **§3 (Streams cannot hold computed values)** from
  "what is missing" to "what shipped", keeping the "where it bit" motivation. Cite the design
  spec `2026-07-15-experiment-orchestrator-6-computed-values-design.md`.
- Update the **summary table** rows for #1 and #3 to a shipped marker (mirroring how #0 reads).
- Update the closing paragraph: #1+#3 are now realized in the example, and #2's `slope` is now
  optional (the growth rate is a named `compute`).

- [ ] **Step 2: Update the parent design doc**

- §5.1 action-leaf table: add `compute` (`into`, `value` → binding) and `record` (`into`, `value`
  → stream) rows.
- §6 data plane: amend "Bindings — scalars produced by `OperatorInput`" to "…by `OperatorInput`
  and `compute`"; note that streams are produced by `Measure` **or** `record`.
- §15 serialization: add the `{"compute": {...}}` and `{"record": {...}}` block forms.

- [ ] **Step 3: Commit**

```bash
git add docs/experiment-engine-limitations.md \
        docs/superpowers/specs/2026-07-07-experiment-orchestrator-design.md
git commit -m "docs: computed bindings and computed streams shipped (#1, #3)"
```

---

## Preprod validation (after Task 7, before merge — not a code task)

Run the rewritten `morbidostat-demo-speed.json` against `windows_arm64_test_client` through the
engine (SSH `khamit@111.88.145.138` → docker exec into the jupyter container → Python driving
`ExperimentRun`, per the established preprod recipe). Confirm: `compute`/`record` execute on real
hardware; `c_series_i` / `r_series_i` are populated; the run completes with `binding_computed` /
`sample_recorded` in the log. The rig reads absorbance 0.0, so dosing arms may not fire and `c`
may stay 0 — record what was actually exercised (control flow, accumulator, recording), matching
the honesty of the fault-tolerance run.

---

## Self-Review

**Spec coverage.** §2 blocks → Task 1; §3 semantics/events → Task 2; §4 seeding → Task 3
(unseeded test) + Task 4 (accumulator); §5 path analysis/type checks → Task 3; §6 disjointness →
Task 3; §7 mirrors (engine → Task 1; backend → Task 5; frontend chart free / events → Task 6);
§8 example → Task 7; §9 testing → Tasks 1–4; §10 preprod → preprod section; §11 docs → Task 8;
§12 out-of-scope → nothing built. All covered.

**Placeholder scan.** No TBD/TODO; every code step shows code; every command shows expected
output. Task 7's example JSON is described by exact transformation rules + validation command
rather than a full literal (the file is large and derived from the existing doc); this is a
deliberate transform-in-place, not a placeholder.

**Type consistency.** `_eval_value(value, ctx) -> Value`, `_run_compute`/`_run_record(block, ctx)
-> None`, events `binding_computed{name,value}` / `sample_recorded{stream,value}`, and the
disjointness diagnostics are named identically across Tasks 2, 4, and 6. `_value` (serializer),
`_check_compute_value`/`_check_record_value`/`_check_compute`/`_check_record`/`_check_namespaces`
(validator) are each defined once and used consistently.
