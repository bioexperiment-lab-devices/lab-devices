# Engine Fault Tolerance (retry + `on_error`) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A transient device fault must not kill an experiment run — add a `retry` policy on `command`/`measure`, an `on_error: continue` tolerance on any block, and the static-analysis support both need.

**Architecture:** Two orthogonal top-level block keys (siblings of `label`/`gap_after`). `retry` wraps the existing `_run_action` dispatch pipeline; `on_error` is caught in `execute_block`. Per-device fault isolation falls out for free — `_run_parallel` uses an `asyncio.TaskGroup`, which only cancels siblings when a lane *raises*, so a lane that absorbs its own failure leaves its siblings running. The one real complication is static: a tolerated `measure` only *maybe* writes its stream, so the path analyzer learns guard refinement (`count(S) > 0` proves non-emptiness), which also closes a pre-existing gap the evaluator already documented.

**Tech Stack:** Python 3.14, Poetry, pytest/mypy/ruff. Studio backend: FastAPI. Studio frontend: React 19.2 / Vite 8 / Tailwind 4 / vitest, oxlint (not eslint), tsconfig strict + `erasableSyntaxOnly` + `verbatimModuleSyntax`.

**Spec:** `docs/superpowers/specs/2026-07-14-engine-fault-tolerance-design.md`. Read it before Task 1. Where this plan and the spec disagree, the spec wins.

## Global Constraints

- **Engine gate (must pass before every commit):** `.venv/bin/python -m pytest && .venv/bin/python -m mypy && .venv/bin/python -m ruff check .` — bare `python` lacks the deps; always use `.venv/bin/python`.
- **Line length ≤ 100.** Ruff's default select has no E501, so check manually: `awk 'length>100 {print FILENAME":"FNR}' src/lab_devices/experiment/*.py tests/test_experiment_*.py` must print nothing.
- **Source module convention:** every module in `src/lab_devices/experiment/` starts with `from __future__ import annotations` and a one-line docstring citing its design section.
- **Test convention:** tests are flat files, `tests/test_experiment_*.py`. **No `from __future__ import annotations` in test files.** Imports at top of file (ruff's default select includes E402 and F401).
- **Executor tests use zero wall-clock:** `tests/fakeclock.py` provides `FakeClock` (manual advance) and `drive(clock, coro)`. `tests/fakelab.py` provides `FakeLab` with `inject_error(device_id, cmd, code, message, times=N)` (queues an envelope error, mapped to an exception class by `map_command_error`) and `fail_jobs: set[str]`. `tests/experiment_run_helpers.py` provides `make_workflow(blocks, streams=...)` and `add_standard_devices(fake)`.
- **Webapp backend gate:** `cd webapp/backend && .venv/bin/python -m pytest -q && .venv/bin/python -m mypy && .venv/bin/python -m ruff check .` — **mypy takes no path argument.**
- **Frontend gate:** `cd webapp/frontend && npm run lint && npm run typecheck && npm test -- --run && npm run build`. Two pre-existing oxlint fast-refresh warnings are expected; exit code is still 0.
- **`attempts` means TOTAL tries**, not retries-after-the-first. Never rename it to `times`.

---

## File Structure

| File | Change | Responsibility |
|---|---|---|
| `src/lab_devices/experiment/blocks.py` | Modify | `Retry` dataclass; `retry` + `on_error` on `BlockBase` |
| `src/lab_devices/experiment/workflow.py` | Modify | `Defaults` dataclass; `defaults` on `Workflow` |
| `src/lab_devices/experiment/serialize.py` | Modify | `_BLOCK_KEYS` (renamed from `_TIMING_KEYS`); parse/emit both keys + `defaults` |
| `src/lab_devices/experiment/registry.py` | Modify | `Trait.retry_safe` |
| `src/lab_devices/experiment/catalog.py` | Modify | project `retry_safe` into `VerbEntry` |
| `src/lab_devices/experiment/analyze.py` | Modify | `proven_nonempty(expr)` |
| `src/lab_devices/experiment/validate.py` | Modify | `_check_block` restructure; `_check_retry`/`_check_on_error`/`_check_defaults`; guard refinement in `_expr_reads` + `_visit` |
| `src/lab_devices/experiment/errors.py` | Modify | `ToleratedError` dataclass |
| `src/lab_devices/experiment/execute.py` | Modify | retry loop around `_run_action`; `on_error` catch in `execute_block` |
| `src/lab_devices/experiment/context.py` | Modify | `RunContext.tolerated` |
| `src/lab_devices/experiment/run.py` | Modify | `RunReport.tolerated_errors` |
| `webapp/backend/experiment_studio/roles.py` | Modify | `_BLOCK_KEYS` mirror (silent-skip bug) |
| `webapp/backend/experiment_studio/runner.py` | Modify | `tolerated_errors` into `report.json` |
| `webapp/frontend/src/types/doc.ts` | Modify | `RetryJson`, `on_error` on `BlockJson`, `defaults` |
| `webapp/frontend/src/builder/tree.ts` | Modify | `retry`/`onError` on `NodeBase` |
| `webapp/frontend/src/builder/convert.ts` | Modify | `BLOCK_KEYS`; round-trip both fields |
| `webapp/frontend/src/builder/Inspector.tsx` | Modify | retry/on_error controls |
| `webapp/frontend/src/run/describeEvent.ts`, `run/EventLog.tsx` | Modify | new event kinds |
| `webapp/frontend/src/types/records.ts`, `records/RecordViewer.tsx` | Modify | display `tolerated_errors` |
| `examples/morbidostat.json`, `examples/morbidostat-demo-speed.json` | Modify | use retry + on_error + guards |
| `docs/experiment-engine-limitations.md`, `examples/README.md` | Modify | §0 shipped; retract the "will destroy your run" warning |

New test files: `tests/test_experiment_retry.py`, `tests/test_experiment_on_error.py`, `tests/test_experiment_validate_faults.py`.

---

## Task 1: Schema and serialization

**Files:**
- Modify: `src/lab_devices/experiment/blocks.py`
- Modify: `src/lab_devices/experiment/workflow.py`
- Modify: `src/lab_devices/experiment/serialize.py`
- Test: `tests/test_experiment_serialize.py` (existing — append)

**Interfaces:**
- Produces: `blocks.Retry(attempts: int, backoff: str, allow_repeat: bool)`; `BlockBase.retry: Retry | None`; `BlockBase.on_error: str` (`"fail"` default); `workflow.Defaults(retry: Retry | None)`; `Workflow.defaults: Defaults`; `serialize._BLOCK_KEYS`.
- Consumed by: every later task.

**Context you need:** In the JSON, a block is `{"<type>": {...body...}, "label": ..., "gap_after": ...}`. `serialize.py:172` computes `type_keys = [k for k in d if k not in _TIMING_KEYS]` and raises if there isn't exactly one. So a new top-level key **must** be added to that tuple or every workflow using it fails to load. `block_to_dict` (`serialize.py:226`) hand-writes each key, so it must learn them too or they are silently dropped on save.

- [ ] **Step 1: Write the failing round-trip test**

Append to `tests/test_experiment_serialize.py`:

```python
def test_round_trip_preserves_retry_and_on_error():
    doc = {
        "schema_version": 1,
        "persistence": {"default": "in_memory", "format": "jsonl"},
        "defaults": {"retry": {"attempts": 2, "backoff": "5s"}},
        "streams": {"od_1": {"units": "AU"}},
        "blocks": [
            {
                "measure": {"device": "densitometer_1", "verb": "measure", "into": "od_1"},
                "label": "read OD",
                "retry": {"attempts": 3, "backoff": "2s"},
                "on_error": "continue",
            },
            {
                "command": {
                    "device": "pump_1", "verb": "dispense", "params": {"volume_ml": 0.5}
                },
                "retry": {"attempts": 2, "backoff": "1s", "allow_repeat": True},
            },
        ],
    }
    assert workflow_to_dict(workflow_from_dict(doc)) == doc


def test_retry_defaults_backoff_to_one_second():
    w = workflow_from_dict({
        "schema_version": 1,
        "streams": {"od_1": {}},
        "blocks": [{"measure": {"device": "densitometer_1", "verb": "measure", "into": "od_1"},
                    "retry": {"attempts": 3}}],
    })
    assert w.blocks[0].retry.attempts == 3
    assert w.blocks[0].retry.backoff == "1s"
    assert w.blocks[0].retry.allow_repeat is False
    assert w.blocks[0].on_error == "fail"


def test_bad_on_error_value_rejected_at_load():
    with pytest.raises(WorkflowLoadError, match="on_error"):
        workflow_from_dict({
            "schema_version": 1,
            "blocks": [{"wait": {"duration": "1s"}, "on_error": "retry"}],
        })


def test_bad_retry_attempts_rejected_at_load():
    with pytest.raises(WorkflowLoadError, match="attempts"):
        workflow_from_dict({
            "schema_version": 1,
            "streams": {"od_1": {}},
            "blocks": [{"measure": {"device": "densitometer_1", "verb": "measure",
                                    "into": "od_1"}, "retry": {"attempts": 0}}],
        })
```

Make sure `pytest` and `WorkflowLoadError` are imported at the top of that file (they should already be; add if not).

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_experiment_serialize.py -k "retry or on_error" -v`
Expected: FAIL — `WorkflowLoadError: block must have exactly one type key, got ['measure', 'retry', 'on_error']`

- [ ] **Step 3: Add the AST types**

In `src/lab_devices/experiment/blocks.py`, add above `BlockBase`:

```python
@dataclass(frozen=True)
class Retry:
    """Retry policy for one action block (design 2026-07-14 §2.1)."""

    attempts: int  # TOTAL tries, not retries-after-the-first
    backoff: str = "1s"
    allow_repeat: bool = False  # explicit opt-in to retry a non-idempotent verb (§4)
```

and extend `BlockBase`:

```python
@dataclass(kw_only=True)
class BlockBase:
    id: str | None = None  # engine-assigned at load; never serialized (design §5, 4-exec §13)
    label: str | None = None
    gap_after: str | None = None  # serial: end-of-this -> start-of-next
    start_offset: str | None = None  # parallel: container-start -> this-start
    retry: Retry | None = None  # command/measure only (2026-07-14 §2.1)
    on_error: str = "fail"  # "fail" | "continue" (2026-07-14 §2.2)
```

- [ ] **Step 4: Add `Defaults` to the workflow**

In `src/lab_devices/experiment/workflow.py`, import `Retry` and add:

```python
from lab_devices.experiment.blocks import Block, Retry


@dataclass
class Defaults:
    """Workflow-wide defaults (design 2026-07-14 §2.4). `retry` only — a blanket
    `on_error` would silently make a missed injection survivable."""

    retry: Retry | None = None
```

and add the field to `Workflow` (last, so positional construction elsewhere still works):

```python
    defaults: Defaults = field(default_factory=Defaults)
```

- [ ] **Step 5: Teach the serializer both directions**

In `src/lab_devices/experiment/serialize.py`:

```python
_BLOCK_KEYS = ("label", "gap_after", "start_offset", "retry", "on_error")
_ON_ERROR_VALUES = ("fail", "continue")
```

(Delete `_TIMING_KEYS`; it is no longer only about timing.)

Add the parser:

```python
def _retry(value: Any, ctx: str) -> B.Retry:
    body = _obj(value, ctx)
    attempts = body.get("attempts")
    if not isinstance(attempts, int) or isinstance(attempts, bool) or attempts < 1:
        raise WorkflowLoadError(f"{ctx}: attempts must be an integer >= 1, got {attempts!r}")
    backoff = _checked_duration(body.get("backoff", "1s"), f"{ctx} backoff")
    allow_repeat = body.get("allow_repeat", False)
    if not isinstance(allow_repeat, bool):
        raise WorkflowLoadError(f"{ctx}: allow_repeat must be a boolean, got {allow_repeat!r}")
    return B.Retry(attempts=attempts, backoff=backoff, allow_repeat=allow_repeat)
```

Rewrite `block_from_dict`'s preamble (replacing the `timing` handling at `serialize.py:167-171`):

```python
def block_from_dict(d: Any) -> B.Block:
    if not isinstance(d, dict):
        raise WorkflowLoadError(f"block must be an object, got {type(d).__name__}")
    timing = {k: d[k] for k in _BLOCK_KEYS if k in d}
    if "gap_after" in timing:
        timing["gap_after"] = _checked_duration(timing["gap_after"], "gap_after")
    if "start_offset" in timing:
        timing["start_offset"] = _checked_duration(timing["start_offset"], "start_offset")
    if "retry" in timing:
        timing["retry"] = _retry(timing["retry"], "retry")
    if "on_error" in timing and timing["on_error"] not in _ON_ERROR_VALUES:
        raise WorkflowLoadError(
            f"on_error must be one of {_ON_ERROR_VALUES}, got {timing['on_error']!r}"
        )
    type_keys = [k for k in d if k not in _BLOCK_KEYS]
    if len(type_keys) != 1:
        raise WorkflowLoadError(f"block must have exactly one type key, got {type_keys}")
    key = type_keys[0]
    builder = _BUILDERS.get(key)
    if builder is None:
        raise WorkflowLoadError(f"unknown block type {key!r}")
    return builder(d[key], timing)
```

Add the emitter helper and extend `block_to_dict`:

```python
def _retry_to_dict(r: B.Retry) -> dict[str, Any]:
    body: dict[str, Any] = {"attempts": r.attempts, "backoff": r.backoff}
    if r.allow_repeat:
        body["allow_repeat"] = True
    return body


def block_to_dict(b: B.Block) -> dict[str, Any]:
    """Serialize a block to its canonical JSON form."""
    key, body = _dump_body(b)
    out: dict[str, Any] = {key: body}
    if b.label is not None:
        out["label"] = b.label
    if b.gap_after is not None:
        out["gap_after"] = b.gap_after
    if b.start_offset is not None:
        out["start_offset"] = b.start_offset
    if b.retry is not None:
        out["retry"] = _retry_to_dict(b.retry)
    if b.on_error != "fail":
        out["on_error"] = b.on_error
    return out
```

- [ ] **Step 6: Wire `defaults` through the workflow (de)serializer**

In `workflow_from_dict`, after the `persistence` block:

```python
    dd = _obj(d.get("defaults", {}), "defaults")
    defaults = Defaults(
        retry=_retry(dd["retry"], "defaults.retry") if "retry" in dd else None
    )
```

and pass `defaults=defaults` to the `Workflow(...)` constructor. Import `Defaults` from `workflow`.

In `workflow_to_dict`, after the `persistence` line:

```python
    if w.defaults.retry is not None:
        out["defaults"] = {"retry": _retry_to_dict(w.defaults.retry)}
```

**Key ordering matters** for the round-trip equality test: emit `defaults` after `persistence` and before `streams`, matching the test's dict literal.

- [ ] **Step 7: Run the gate**

Run: `.venv/bin/python -m pytest tests/test_experiment_serialize.py -v && .venv/bin/python -m mypy && .venv/bin/python -m ruff check . && awk 'length>100 {print FILENAME":"FNR}' src/lab_devices/experiment/*.py`
Expected: all PASS, mypy clean, ruff clean, awk prints nothing.

- [ ] **Step 8: Run the full suite** (nothing should regress — `defaults` has a default, `_BLOCK_KEYS` is a superset of `_TIMING_KEYS`)

Run: `.venv/bin/python -m pytest -q`
Expected: all PASS.

- [ ] **Step 9: Commit**

```bash
git add src/lab_devices/experiment/blocks.py src/lab_devices/experiment/workflow.py \
        src/lab_devices/experiment/serialize.py tests/test_experiment_serialize.py
git commit -m "feat(experiment): retry + on_error block schema and round-trip"
```

---

## Task 2: Registry `retry_safe`

**Files:**
- Modify: `src/lab_devices/experiment/registry.py`
- Modify: `src/lab_devices/experiment/catalog.py`
- Test: `tests/test_experiment_registry.py`, `tests/test_experiment_catalog.py` (existing — append)

**Interfaces:**
- Consumes: nothing.
- Produces: `Trait.retry_safe: bool`; `VerbEntry["retry_safe"]`.

**Context you need:** `Trait` (`registry.py:33`) has three positional fields (`completion`, `state_effect`, `teardown`) followed by a `kw_only=True` block. A new `kw_only` field with a default breaks none of the 16 existing declarations. `catalog.py:8` imports the private `_REGISTRY` and projects each Trait into a `VerbEntry` TypedDict for the Studio verb picker.

**The classification — this is the safety-critical part of the task.** `pump.dispense` takes a **relative** `volume_ml`: retrying after a partial dispense double-doses the culture. Pure reads and *absolute* setters are idempotent. `retry_safe=True` goes on exactly these verbs and no others:

- `densitometer`: `measure`, `measure_blank`, `set_thermostat`
- `valve`: `set_position`, `home`, `configure`
- `pump`: `stop`, `set_calibration`, and any other absolute setter (`set_*`/`configure`) present in the registry
- **`pump.dispense` stays `False`.** So does anything else that moves a relative quantity.
- **`pump.start_calibration` stays `False` too — do not mark it retry-safe.** Per
  `docs/lab-bridge-api-reference.md` §3.6, it physically runs the pump for ~2 minutes moving
  liquid and returns `{steps}`; the operator then measures the delivered volume and feeds it to
  `set_calibration`. A retry after a partial run leaves the collection vessel holding *partial +
  full* volume while the job reports only the second run's steps → inflated `measured_volume_ml`
  → inflated `ml_per_step` → every subsequent dispense silently under-doses, permanently. Same
  corruption class as a double dispense.
- `densitometer.read_raw` and `pump.home` are **not** in `_REGISTRY` and do not belong on the
  "should be True" list above. `pump.home` does not exist in the firmware at all — the **valve**
  is the homed device (§3.6's pump table has no `home` and explicitly notes "No `not_homed`").
  (If `read_raw` were ever admitted to the registry it would legitimately be `True` — a pure
  read — but `start_calibration` and `rotate_raw` would be `False`, for the same reason as above.)

Open `registry.py` and classify **every** entry explicitly — do not guess from the list above alone; read each trait's params and decide whether re-issuing it with the same params is idempotent.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_experiment_registry.py`:

```python
def test_dispense_is_not_retry_safe():
    assert lookup("pump_1", "dispense").retry_safe is False


def test_reads_and_absolute_setters_are_retry_safe():
    assert lookup("densitometer_1", "measure").retry_safe is True
    assert lookup("densitometer_1", "measure_blank").retry_safe is True
    assert lookup("densitometer_1", "set_thermostat").retry_safe is True
    assert lookup("valve_1", "set_position").retry_safe is True
    assert lookup("valve_1", "home").retry_safe is True
    assert lookup("pump_1", "stop").retry_safe is True
```

Append to `tests/test_experiment_catalog.py`:

```python
def test_catalog_exposes_retry_safe():
    catalog = verb_catalog()
    assert catalog["densitometer"]["measure"]["retry_safe"] is True
    assert catalog["pump"]["dispense"]["retry_safe"] is False
```

(Match the existing shape of `verb_catalog()`'s return value in that test file — if it nests differently, follow the file, not this snippet.)

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_experiment_registry.py tests/test_experiment_catalog.py -k retry_safe -v`
Expected: FAIL — `AttributeError: 'Trait' object has no attribute 'retry_safe'`

- [ ] **Step 3: Add the field**

In `registry.py`, append to `Trait`:

```python
    retry_safe: bool = field(default=False, kw_only=True)
    # True iff re-issuing this verb with the same params is idempotent. False for
    # relative actions (pump.dispense): a retry after a partial dispense double-doses
    # the culture (design 2026-07-14 §4). Default False — a verb added later is
    # conservative until someone thinks about it.
```

- [ ] **Step 4: Annotate every idempotent verb**

Add `retry_safe=True` to each trait identified above. Example (`densitometer.measure`):

```python
    ("densitometer", "measure"): Trait(
        "job",
        "none",
        channels=_OPTICS,
        measurement=True,
        result_field="absorbance",
        retry_safe=True,
        params=(ParamSpec("include_raw", "bool"),),
    ),
```

Leave `("pump", "dispense")` untouched (it inherits `False`).

- [ ] **Step 5: Project it into the catalog**

In `catalog.py`, add `retry_safe: bool` to the `VerbEntry` TypedDict and set it in the projection alongside `kind`/`params`/`result_field`.

- [ ] **Step 6: Run the gate**

Run: `.venv/bin/python -m pytest -q && .venv/bin/python -m mypy && .venv/bin/python -m ruff check .`
Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add src/lab_devices/experiment/registry.py src/lab_devices/experiment/catalog.py \
        tests/test_experiment_registry.py tests/test_experiment_catalog.py
git commit -m "feat(experiment): declare per-verb retry_safe in the registry"
```

---

## Task 3: Validator — retry and on_error rules

**Files:**
- Modify: `src/lab_devices/experiment/validate.py`
- Test: `tests/test_experiment_validate_faults.py` (create)

**Interfaces:**
- Consumes: `B.Retry`, `BlockBase.on_error`, `Workflow.defaults`, `Trait.retry_safe`.
- Produces: `Diagnostic(category="block", ...)` for every rule below.

**Context you need.** `_check_block` (`validate.py:305`) is an `isinstance` chain, **not** a dispatch table, and `B.Serial`, `B.Parallel`, `B.Wait`, and `B.GroupRef` currently reach **no checker at all** — they fall through silently. `on_error` is legal on all of them, so the chain needs an unconditional per-block check *before* the type-specific chain. Note the deliberate `if`/`if`/`elif` split already there (Command|Measure → `_check_action`, then a second chain starting at Measure): preserve it.

Rules to enforce (all `category="block"`):

1. `retry` on a block that is not `command`/`measure` → `"retry is only valid on command and measure blocks"`
2. `retry` on a verb where `not trait.retry_safe and not retry.allow_repeat` → `"verb 'dispense' on 'pump_1' is not idempotent; a retry after a partial action may repeat it. Set retry.allow_repeat=true to accept this."`
3. `defaults.retry.allow_repeat` is true → `"defaults.retry may not set allow_repeat; a blanket policy must never retry a non-idempotent verb"` (path `"defaults.retry"`)
4. `on_error` not in `("fail", "continue")` → belt-and-braces; the loader already rejects it, but a programmatically built AST bypasses the loader.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_experiment_validate_faults.py`:

```python
import pytest

from lab_devices.experiment.errors import ValidationError
from lab_devices.experiment.serialize import workflow_from_dict
from lab_devices.experiment.validate import validate


def _validate(doc):
    validate(workflow_from_dict(doc))


def _messages(exc):
    return [d.message for d in exc.value.diagnostics]


def test_retry_on_a_wait_block_is_rejected():
    with pytest.raises(ValidationError) as exc:
        _validate({
            "schema_version": 1,
            "blocks": [{"wait": {"duration": "1s"}, "retry": {"attempts": 3}}],
        })
    assert any("only valid on command and measure" in m for m in _messages(exc))


def test_retry_on_dispense_without_allow_repeat_is_rejected():
    with pytest.raises(ValidationError) as exc:
        _validate({
            "schema_version": 1,
            "blocks": [{
                "command": {"device": "pump_1", "verb": "dispense",
                            "params": {"volume_ml": 0.5}},
                "retry": {"attempts": 3},
            }],
        })
    assert any("not idempotent" in m for m in _messages(exc))


def test_retry_on_dispense_with_allow_repeat_is_accepted():
    _validate({
        "schema_version": 1,
        "blocks": [{
            "command": {"device": "pump_1", "verb": "dispense", "params": {"volume_ml": 0.5}},
            "retry": {"attempts": 3, "allow_repeat": True},
        }],
    })


def test_retry_on_a_measure_needs_no_opt_in():
    _validate({
        "schema_version": 1,
        "streams": {"od_1": {}},
        "blocks": [{
            "measure": {"device": "densitometer_1", "verb": "measure", "into": "od_1"},
            "retry": {"attempts": 3, "backoff": "2s"},
        }],
    })


def test_defaults_retry_may_not_set_allow_repeat():
    with pytest.raises(ValidationError) as exc:
        _validate({
            "schema_version": 1,
            "defaults": {"retry": {"attempts": 2, "allow_repeat": True}},
            "blocks": [{"wait": {"duration": "1s"}}],
        })
    assert any("blanket policy" in m for m in _messages(exc))


def test_defaults_retry_does_not_make_dispense_retryable():
    """A workflow-wide default must never silently start retrying a relative action."""
    _validate({
        "schema_version": 1,
        "defaults": {"retry": {"attempts": 3}},
        "blocks": [{
            "command": {"device": "pump_1", "verb": "dispense", "params": {"volume_ml": 0.5}}
        }],
    })


def test_on_error_continue_is_accepted_on_every_container():
    _validate({
        "schema_version": 1,
        "blocks": [
            {"serial": {"children": [{"wait": {"duration": "1s"}}]}, "on_error": "continue"},
            {"parallel": {"children": [{"wait": {"duration": "1s"}}]}, "on_error": "continue"},
            {"wait": {"duration": "1s"}, "on_error": "continue"},
        ],
    })
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_experiment_validate_faults.py -v`
Expected: the four negative tests FAIL (no `ValidationError` raised); the positive ones may already pass.

- [ ] **Step 3: Add the checkers**

In `validate.py`, add above `_check_block`:

```python
_ON_ERROR_VALUES = ("fail", "continue")


def _check_on_error(block: B.Block, path: str, out: list[Diagnostic]) -> None:
    """Legal on every block type (design 2026-07-14 §2.2)."""
    if block.on_error not in _ON_ERROR_VALUES:
        out.append(Diagnostic(
            "block", path,
            f"on_error must be one of {_ON_ERROR_VALUES}, got {block.on_error!r}",
        ))


def _check_retry(block: B.Block, path: str, out: list[Diagnostic]) -> None:
    """retry is command/measure only, and a non-idempotent verb needs an explicit
    in-document opt-in (design 2026-07-14 §4)."""
    retry = block.retry
    if retry is None:
        return
    if not isinstance(block, (B.Command, B.Measure)):
        out.append(Diagnostic(
            "block", path, "retry is only valid on command and measure blocks"
        ))
        return
    try:
        trait = lookup(block.device, block.verb)
    except UnknownVerbError:
        return  # already diagnosed by _check_action
    if not trait.retry_safe and not retry.allow_repeat:
        out.append(Diagnostic(
            "block", path,
            f"verb {block.verb!r} on {block.device!r} is not idempotent; a retry after a "
            f"partial action may repeat it. Set retry.allow_repeat=true to accept this.",
        ))


def _check_defaults(w: Workflow, out: list[Diagnostic]) -> None:
    if w.defaults.retry is not None and w.defaults.retry.allow_repeat:
        out.append(Diagnostic(
            "block", "defaults.retry",
            "defaults.retry may not set allow_repeat; a blanket policy must never retry a "
            "non-idempotent verb",
        ))
```

- [ ] **Step 4: Restructure `_check_block` and call `_check_defaults`**

Replace `_check_block` (`validate.py:305`):

```python
def _check_block(
    block: B.Block, path: str, w: Workflow,
    binding_types: Mapping[str, BindingType], out: list[Diagnostic],
) -> None:
    # Unconditional: legal on every block type, including Serial/Parallel/Wait/GroupRef,
    # which reach none of the type-specific checks below.
    _check_on_error(block, path, out)
    _check_retry(block, path, out)
    if isinstance(block, (B.Command, B.Measure)):
        _check_action(block, path, w, binding_types, out)
    if isinstance(block, B.Measure):
        _check_measure(block, path, w, out)
    elif isinstance(block, B.OperatorInput):
        _check_operator_input(block, path, out)
    elif isinstance(block, B.Loop):
        _check_loop(block, path, w, binding_types, out)
    elif isinstance(block, B.Branch):
        _check_condition(block.if_, f"{path} branch if", w, binding_types, out)
```

In `validate()`, add `_check_defaults(workflow, out)` immediately after `_check_groups(...)`.

- [ ] **Step 5: Run the tests**

Run: `.venv/bin/python -m pytest tests/test_experiment_validate_faults.py -v`
Expected: all PASS.

- [ ] **Step 6: Run the gate**

Run: `.venv/bin/python -m pytest -q && .venv/bin/python -m mypy && .venv/bin/python -m ruff check . && awk 'length>100 {print FILENAME":"FNR}' src/lab_devices/experiment/*.py tests/test_experiment_*.py`
Expected: all PASS, awk silent.

- [ ] **Step 7: Commit**

```bash
git add src/lab_devices/experiment/validate.py tests/test_experiment_validate_faults.py
git commit -m "feat(experiment): validate retry placement, idempotency opt-in, defaults"
```

---

## Task 4: Validator — guard refinement for may-written streams

**Files:**
- Modify: `src/lab_devices/experiment/analyze.py`
- Modify: `src/lab_devices/experiment/validate.py`
- Test: `tests/test_experiment_validate_faults.py` (append), `tests/test_experiment_analyze.py` (append)

**Interfaces:**
- Consumes: `BlockBase.on_error`.
- Produces: `analyze.proven_nonempty(expr: Expr) -> frozenset[str]`.

**Context you need — read this whole block before writing code.**

The phase-2 path analyzer treats a `measure` as **definitely** writing its stream (`validate.py:407-408`). `_expr_reads` (`validate.py:361`) then hard-errors on a *windowed* stat (`last`/`mean`/`min`/`max`) over a stream not in `state.streams`. `count()` is already exempt — `ExprRefs` splits `streams_windowed` from `streams_counted` (`analyze.py:30-31`).

A `measure` with `on_error: "continue"` only *maybe* writes. Two changes:

**(a) A tolerant block joins like a branch with an empty else.** In `_visit`, a block with `on_error == "continue"` must yield `_merge(entry, exit)`. `_merge` (`validate.py:337`) already computes the right join (streams intersect, modes → `"maybe"`). So after a tolerant measure, `od_1` is not provably written and a later `mean(od_1, last=10)` **is** diagnosed. That is correct: if all ten reads fail, the stream is empty and the run would die on `EvaluationError`.

**(b) The author guards; the validator checks the guard.** `_window_values` slices `samples[-n:]` (`evaluate.py:162`), so a *short* window is fine — only a **truly empty** one raises (`evaluate.py:138`). So `count(S) > 0` is sufficient to make **any** windowed stat on `S` safe; nothing needs to track counts.

This is not a new concession. `evaluate.py:85` already says:
> `# Short-circuit enables guard conditions: count(S) > 0 and mean(S) > x (§6).`
The evaluator was *designed* for this idiom and the analyzer never learned it. This closes that gap and, as a side effect, fixes the pre-existing over-strictness where "measure inside a `branch`, read it later" is banned with no way to express the guard.

Refinement applies in exactly two places: the **right operand of an `and`** (short-circuit), and a **`branch.then` body**. The `else` arm is never refined — the negation proves emptiness, which is not useful.

- [ ] **Step 1: Write the failing test for `proven_nonempty`**

Append to `tests/test_experiment_analyze.py`:

```python
def test_proven_nonempty_recognises_count_guards():
    assert proven_nonempty(parse_expression("count(od_1) > 0")) == {"od_1"}
    assert proven_nonempty(parse_expression("count(od_1) >= 1")) == {"od_1"}
    assert proven_nonempty(parse_expression("count(od_1) != 0")) == {"od_1"}
    assert proven_nonempty(parse_expression("0 < count(od_1)")) == {"od_1"}
    assert proven_nonempty(parse_expression("count(od_1) > 5")) == {"od_1"}


def test_proven_nonempty_rejects_non_guards():
    assert proven_nonempty(parse_expression("count(od_1) >= 0")) == frozenset()
    assert proven_nonempty(parse_expression("count(od_1) < 3")) == frozenset()
    assert proven_nonempty(parse_expression("mean(od_1, last=3) > 0.4")) == frozenset()


def test_proven_nonempty_combines_over_and_or():
    both = proven_nonempty(parse_expression("count(od_1) > 0 and count(od_2) > 0"))
    assert both == {"od_1", "od_2"}
    either = proven_nonempty(parse_expression("count(od_1) > 0 or count(od_2) > 0"))
    assert either == frozenset()
    same = proven_nonempty(parse_expression("count(od_1) > 0 or count(od_1) > 3"))
    assert same == {"od_1"}
```

Import `proven_nonempty` and `parse_expression` at the top of that file.

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_experiment_analyze.py -k proven_nonempty -v`
Expected: FAIL — `ImportError: cannot import name 'proven_nonempty'`

- [ ] **Step 3: Implement `proven_nonempty`**

Append to `analyze.py`:

```python
def proven_nonempty(expr: Expr) -> frozenset[str]:
    """Streams this expression proves non-empty whenever it evaluates True.

    A windowed stat only raises on a *truly empty* window (evaluate.py `_stat`); a short
    window is fine. So `count(S) > 0` is enough to make any windowed stat on S safe
    (design 2026-07-14 §5.2).
    """
    if isinstance(expr, BinaryOp):
        if expr.op == "and":
            return proven_nonempty(expr.left) | proven_nonempty(expr.right)
        if expr.op == "or":
            return proven_nonempty(expr.left) & proven_nonempty(expr.right)
        return _proven_by_comparison(expr)
    return frozenset()


def _count_stream(e: Expr) -> str | None:
    return e.stream if isinstance(e, StatCall) and e.fn == "count" else None


def _int_const(e: Expr) -> int | None:
    if isinstance(e, Const) and isinstance(e.value, int) and not isinstance(e.value, bool):
        return e.value
    return None


def _proven_by_comparison(e: BinaryOp) -> frozenset[str]:
    """`count(S) > k` (k>=0), `count(S) >= k` (k>=1), `count(S) != 0`, and mirrors."""
    stream, bound, op = _count_stream(e.left), _int_const(e.right), e.op
    if stream is None or bound is None:  # try the mirrored form: k <op> count(S)
        stream, bound = _count_stream(e.right), _int_const(e.left)
        op = {"<": ">", "<=": ">=", ">": "<", ">=": "<="}.get(e.op, e.op)
    if stream is None or bound is None:
        return frozenset()
    proves = (
        (op == ">" and bound >= 0)
        or (op == ">=" and bound >= 1)
        or (op == "!=" and bound == 0)
    )
    return frozenset({stream}) if proves else frozenset()
```

Import `Const` and `StatCall` at the top of `analyze.py` (`StatCall` is already imported; add `Const` if it is not).

- [ ] **Step 4: Run the analyze tests**

Run: `.venv/bin/python -m pytest tests/test_experiment_analyze.py -v`
Expected: all PASS.

- [ ] **Step 5: Write the failing validator tests**

Append to `tests/test_experiment_validate_faults.py`:

```python
_TOLERANT_MEASURE = {
    "measure": {"device": "densitometer_1", "verb": "measure", "into": "od_1"},
    "retry": {"attempts": 3, "backoff": "2s"},
    "on_error": "continue",
}


def test_tolerated_measure_then_unguarded_windowed_read_is_rejected():
    with pytest.raises(ValidationError) as exc:
        _validate({
            "schema_version": 1,
            "streams": {"od_1": {}},
            "blocks": [
                _TOLERANT_MEASURE,
                {"branch": {"if": "mean(od_1, last=3) > 0.4",
                            "then": [{"wait": {"duration": "1s"}}]}},
            ],
        })
    assert any("no preceding measure" in d.message for d in exc.value.diagnostics)


def test_tolerated_measure_guarded_by_a_count_branch_validates():
    _validate({
        "schema_version": 1,
        "streams": {"od_1": {}},
        "blocks": [
            _TOLERANT_MEASURE,
            {"branch": {
                "if": "count(od_1) > 0",
                "then": [{"branch": {"if": "mean(od_1, last=3) > 0.4",
                                     "then": [{"wait": {"duration": "1s"}}]}}],
            }},
        ],
    })


def test_tolerated_measure_guarded_by_a_short_circuit_and_validates():
    """evaluate.py:85 documents this idiom; the analyzer now recognises it."""
    _validate({
        "schema_version": 1,
        "streams": {"od_1": {}},
        "blocks": [
            _TOLERANT_MEASURE,
            {"branch": {"if": "count(od_1) > 0 and mean(od_1, last=3) > 0.4",
                        "then": [{"wait": {"duration": "1s"}}]}},
        ],
    })


def test_an_untolerated_measure_still_needs_no_guard():
    """Regression: the existing definitely-written proof must not weaken."""
    _validate({
        "schema_version": 1,
        "streams": {"od_1": {}},
        "blocks": [
            {"measure": {"device": "densitometer_1", "verb": "measure", "into": "od_1"}},
            {"branch": {"if": "mean(od_1, last=3) > 0.4",
                        "then": [{"wait": {"duration": "1s"}}]}},
        ],
    })
```

- [ ] **Step 6: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_experiment_validate_faults.py -k "tolerated or untolerated" -v`
Expected: the two guarded tests FAIL (a diagnostic is raised where none should be); the unguarded-rejection test FAILS (no diagnostic raised — the tolerant block still counts as a definite write).

- [ ] **Step 7: Teach `_expr_reads` about `and` short-circuit**

Replace `_expr_reads` (`validate.py:361`):

```python
def _expr_reads(text: object, ctx: str, state: _PathState, c: _Ctx) -> None:
    """Check one expression slot's reads against the current path state."""
    if not isinstance(text, str):
        return  # literals read nothing; non-string garbage is diagnosed globally
    try:
        expr = parse_expression(text)
    except ExpressionError:
        return  # already diagnosed globally
    _expr_reads_ast(expr, ctx, state.bindings, state.streams, c)


def _expr_reads_ast(
    expr: Expr, ctx: str, bindings: set[str], streams: set[str], c: _Ctx
) -> None:
    """Walk `and` chains left-to-right so a `count(S) > 0` guard extends the proven set
    for everything to its right — mirroring the evaluator's short-circuit (design §5.2)."""
    if isinstance(expr, BinaryOp) and expr.op == "and":
        _expr_reads_ast(expr.left, ctx, bindings, streams, c)
        guarded = streams | proven_nonempty(expr.left)
        _expr_reads_ast(expr.right, ctx, bindings, guarded, c)
        return
    refs = references(expr)
    for name in sorted(refs.bindings - bindings):
        c.emit("data-flow", ctx, f"binding {name!r} may be read before it is written")
    for stream in sorted(refs.streams_windowed - streams):
        if stream in c.workflow.streams:  # undeclared streams already got a diagnostic
            c.emit(
                "data-flow", ctx,
                f"stat over stream {stream!r} has no preceding measure on some path",
            )
```

Add `BinaryOp` and `Expr` to the `expr` imports and `proven_nonempty` to the `analyze` imports at the top of `validate.py`.

- [ ] **Step 8: Make a tolerant block join like an empty-else branch, and refine `branch.then`**

In `_visit` (`validate.py:503`), wrap the dispatch and refine the `Branch` arm:

```python
def _visit(b: B.Block, path: str, state: _PathState, c: _Ctx) -> _PathState:
    entry = state.copy() if b.on_error == "continue" else None
    state = _visit_body(b, path, state, c)
    if entry is not None:
        # A tolerated failure can skip this block's writes entirely: join like a branch
        # with an empty else (design 2026-07-14 §5.2).
        state = _merge(entry, state)
    return state


def _visit_body(b: B.Block, path: str, state: _PathState, c: _Ctx) -> _PathState:
    if isinstance(b, (B.Command, B.Measure)):
        _visit_action(b, path, state, c)
    elif isinstance(b, B.OperatorInput):
        if isinstance(b.name, str):
            state.bindings.add(b.name)
    elif isinstance(b, B.Serial):
        state = _visit_blocks(b.children, f"{path}.children", state, c)
    elif isinstance(b, B.Parallel):
        state = _visit_parallel(b, path, state, c)
    elif isinstance(b, B.Loop):
        state = _visit_loop(b, path, state, c)
    elif isinstance(b, B.Branch):
        _expr_reads(b.if_, f"{path} branch if", state, c)
        then_state = state.copy()
        if isinstance(b.if_, str):
            try:
                then_state.streams |= proven_nonempty(parse_expression(b.if_))
            except ExpressionError:
                pass  # unparseable: already diagnosed globally
        then_state = _visit_blocks(b.then, f"{path}.then", then_state, c)
        else_state = _visit_blocks(b.else_ or [], f"{path}.else", state.copy(), c)
        state = _merge(then_state, else_state)
    elif isinstance(b, B.GroupRef):
        group = c.workflow.groups.get(b.name)
        if group is not None:  # unknown refs are diagnosed globally; phase is gated anyway
            state = _visit_blocks(group.body, f"{path}->{b.name}.body", state, c)
    return state  # Wait blocks fall through unchanged
```

**Careful:** `_visit_action` mutates `state` in place rather than returning it, which is why `_visit_body` returns `state` unchanged in that arm. Keep that.

**Also careful:** the `then_state.streams |= proven_nonempty(...)` seeding must happen *before* `_visit_blocks(b.then, ...)` and must NOT leak into `else_state` or into the merged result beyond what the bodies actually write. Because `_merge` intersects, a stream proven only by the guard is dropped at the join unless the `then` body actually measured it — which is correct.

- [ ] **Step 9: Run the tests**

Run: `.venv/bin/python -m pytest tests/test_experiment_validate_faults.py -v`
Expected: all PASS.

- [ ] **Step 10: Run the full suite and read any failure carefully**

Run: `.venv/bin/python -m pytest -q`

Expected: all PASS. If `tests/test_experiment_validate_dataflow.py` now has a test that expected a diagnostic for a `count(S) > 0`-guarded read, that test was asserting the *bug* — the guard idiom is documented at `evaluate.py:85` and is now correctly accepted. Update the test and note it in the commit message. **Any other failure is a real regression — do not paper over it.**

- [ ] **Step 11: Run the gate**

Run: `.venv/bin/python -m mypy && .venv/bin/python -m ruff check . && awk 'length>100 {print FILENAME":"FNR}' src/lab_devices/experiment/*.py tests/test_experiment_*.py`
Expected: clean, awk silent.

- [ ] **Step 12: Commit**

```bash
git add src/lab_devices/experiment/analyze.py src/lab_devices/experiment/validate.py \
        tests/test_experiment_analyze.py tests/test_experiment_validate_faults.py \
        tests/test_experiment_validate_dataflow.py
git commit -m "feat(experiment): guard refinement for may-written streams

A tolerated measure only maybe-writes its stream, so it joins like a branch with an
empty else. The author guards the read with count(S) > 0 and the analyzer now checks
the guard — closing the gap with the short-circuit idiom evaluate.py:85 already
documented."
```

---

## Task 5: Executor — retry

**Files:**
- Modify: `src/lab_devices/experiment/execute.py`
- Test: `tests/test_experiment_retry.py` (create)

**Interfaces:**
- Consumes: `B.Retry`, `Workflow.defaults`, `Trait.retry_safe`, `RunContext`.
- Produces: run-log event `block_retried` with `data={"attempt": int, "of": int, "error": str}`.

**Context you need.**

`_run_action` (`execute.py:99`) is the whole dispatch pipeline: resolve → classify → occupy → invoke → complete, with a `finally` that releases occupancy. Retry wraps **the whole pipeline**, so each attempt re-resolves params against fresh state and re-acquires occupancy cleanly. `register_open` only fires on success, so a failed open leaves no phantom `OpenMode`.

**The deny-list is the safety-critical part.** These must NEVER be retried:

| Error | Why |
|---|---|
| `asyncio.CancelledError` | An operator abort must never be delayed or swallowed. It is a `BaseException`, so a bare `except Exception` already misses it — but be explicit. |
| `InvariantViolationError` | A proven-impossible occupancy state. `errors.py:63` already says "never retried". |
| `EvaluationError` | Empty window / unbound binding / divide-by-zero. Nothing changes in 2s. |
| `InvalidParamsError`, `InvalidRequestError`, `UnknownCommandError`, `UnknownDeviceError`, `NotCalibratedError`, `NotHomedError` | Author/setup errors; will fail identically forever. |

Everything else from the device or transport **is** retryable (`HardwareError`, `InternalDeviceError`, `DeviceUnreachableError`, `JobFailedError`, `JobTimeoutError`, `LabProtocolError`, any unmapped `LabError`). Allow-by-default with a deny-list: an unknown error code is more likely a transient hardware oddity than a permanent one, and the whole point is that a transient fault must not kill a three-week run.

Note `BusyError` is already converted to `InvariantViolationError` at `execute.py:120`, so it is covered by the deny-list transitively.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_experiment_retry.py`:

```python
import asyncio

import httpx
import pytest

from lab_devices.client import LabClient
from lab_devices.experiment.blocks import Retry
from lab_devices.experiment.context import RunOptions
from lab_devices.experiment.errors import BlockFailedError
from lab_devices.experiment.run import ExperimentRun
from tests.experiment_run_helpers import make_workflow
from tests.fakeclock import FakeClock, drive
from tests.fakelab import FakeLab


def _client(fake):
    return LabClient("http://fake", transport=httpx.MockTransport(fake.handler))


def _od_workflow(retry=None, **block_extra):
    block = {"measure": {"device": "densitometer_1", "verb": "measure", "into": "od_1"}}
    if retry is not None:
        block["retry"] = retry
    block.update(block_extra)
    return make_workflow([block], streams={"od_1": {"units": "AU"}})


@pytest.mark.asyncio
async def test_retry_recovers_from_a_transient_fault():
    fake = FakeLab()
    fake.add_device("densitometer_1", "densitometer")
    fake.inject_error(
        "densitometer_1", "measure", "hardware_error",
        "intensity array: record header/index mismatch", times=1,
    )
    clock = FakeClock()
    run = ExperimentRun(
        _client(fake),
        _od_workflow(retry={"attempts": 3, "backoff": "2s"}),
        options=RunOptions(clock=clock),
    )
    report = await drive(clock, run.execute())
    assert report.status == "completed"
    assert len(report.state.streams["od_1"].samples) == 1
    kinds = [e.kind for e in report.log.events]
    assert kinds.count("block_retried") == 1
    assert kinds.count("block_failed") == 0


@pytest.mark.asyncio
async def test_retry_exhausts_and_fails_the_run():
    fake = FakeLab()
    fake.add_device("densitometer_1", "densitometer")
    fake.inject_error("densitometer_1", "measure", "hardware_error", "flaky", times=10)
    clock = FakeClock()
    run = ExperimentRun(
        _client(fake),
        _od_workflow(retry={"attempts": 3, "backoff": "2s"}),
        options=RunOptions(clock=clock),
    )
    with pytest.raises(BlockFailedError):
        await drive(clock, run.execute())
    assert run.report.status == "failed"
    kinds = [e.kind for e in run.report.log.events]
    assert kinds.count("block_retried") == 2  # attempts=3 -> 2 retries, then failure
    assert kinds.count("block_failed") == 1


@pytest.mark.asyncio
async def test_a_deny_listed_error_is_never_retried():
    fake = FakeLab()
    fake.add_device("densitometer_1", "densitometer")
    fake.inject_error("densitometer_1", "measure", "not_calibrated", "calibrate me", times=10)
    clock = FakeClock()
    run = ExperimentRun(
        _client(fake),
        _od_workflow(retry={"attempts": 5, "backoff": "2s"}),
        options=RunOptions(clock=clock),
    )
    with pytest.raises(BlockFailedError):
        await drive(clock, run.execute())
    kinds = [e.kind for e in run.report.log.events]
    assert kinds.count("block_retried") == 0  # fails fast; the error will never change


@pytest.mark.asyncio
async def test_backoff_sleeps_on_the_clock():
    fake = FakeLab()
    fake.add_device("densitometer_1", "densitometer")
    fake.inject_error("densitometer_1", "measure", "hardware_error", "flaky", times=1)
    clock = FakeClock()
    run = ExperimentRun(
        _client(fake),
        _od_workflow(retry={"attempts": 3, "backoff": "30s"}),
        options=RunOptions(clock=clock),
    )
    await drive(clock, run.execute())
    assert clock.now() >= 30.0  # the back-off was actually waited, on the fake clock


@pytest.mark.asyncio
async def test_abort_during_backoff_is_not_retried():
    fake = FakeLab()
    fake.add_device("densitometer_1", "densitometer")
    fake.inject_error("densitometer_1", "measure", "hardware_error", "flaky", times=10)
    clock = FakeClock()
    run = ExperimentRun(
        _client(fake),
        _od_workflow(retry={"attempts": 5, "backoff": "60s"}),
        options=RunOptions(clock=clock),
    )
    task = asyncio.ensure_future(run.execute())
    await clock.settle()
    await clock.advance(1.0)  # first attempt has failed; we are inside the back-off sleep
    run.abort()
    with pytest.raises(Exception):  # RunAbortedError
        await task
    assert run.report.status == "aborted"


@pytest.mark.asyncio
async def test_workflow_defaults_apply_to_a_block_without_retry():
    fake = FakeLab()
    fake.add_device("densitometer_1", "densitometer")
    fake.inject_error("densitometer_1", "measure", "hardware_error", "flaky", times=1)
    clock = FakeClock()
    workflow = make_workflow(
        [{"measure": {"device": "densitometer_1", "verb": "measure", "into": "od_1"}}],
        streams={"od_1": {}},
    )
    workflow.defaults.retry = Retry(attempts=3, backoff="1s")
    run = ExperimentRun(_client(fake), workflow, options=RunOptions(clock=clock))
    report = await drive(clock, run.execute())
    assert report.status == "completed"


@pytest.mark.asyncio
async def test_workflow_defaults_never_retry_a_non_idempotent_verb():
    """A blanket default must not silently double-dose a culture."""
    fake = FakeLab()
    fake.add_device("pump_1", "pump")
    fake.inject_error("pump_1", "dispense", "hardware_error", "flaky", times=1)
    clock = FakeClock()
    workflow = make_workflow([{
        "command": {"device": "pump_1", "verb": "dispense",
                    "params": {"volume_ml": 0.5, "speed_ml_min": 3.0}}
    }])
    workflow.defaults.retry = Retry(attempts=3, backoff="1s")
    run = ExperimentRun(_client(fake), workflow, options=RunOptions(clock=clock))
    with pytest.raises(BlockFailedError):
        await drive(clock, run.execute())
    assert [e.kind for e in run.report.log.events].count("block_retried") == 0
```

**Before writing these, read `tests/test_experiment_e2e_sequential.py`** to see how the existing executor tests build a `LabClient` from a `FakeLab` and how they access the run log (`report.log.events` is the shape used above — confirm it). If there is already a shared client helper in `tests/experiment_run_helpers.py`, use that instead of the local `_client`.

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_experiment_retry.py -v`
Expected: FAIL — the run dies on the first injected fault; no `block_retried` events exist.

- [ ] **Step 3: Add the deny-list and the effective-policy resolver**

In `execute.py`, add near the top:

```python
from lab_devices.experiment.blocks import Retry

# Errors a retry can never fix: they will fail identically, or they mean the safety
# model itself is broken (design 2026-07-14 §3.1).
_NEVER_RETRY: tuple[type[BaseException], ...] = (
    InvariantViolationError,
    EvaluationError,
    core_errors.InvalidParamsError,
    core_errors.InvalidRequestError,
    core_errors.UnknownCommandError,
    core_errors.UnknownDeviceError,
    core_errors.NotCalibratedError,
    core_errors.NotHomedError,
)


def _is_retryable(exc: BaseException) -> bool:
    """Allow-by-default over device/transport faults, with a deny-list. CancelledError is
    a BaseException and never reaches here, but the isinstance guard is explicit anyway."""
    if isinstance(exc, asyncio.CancelledError):
        return False
    return not isinstance(exc, _NEVER_RETRY)


def _effective_retry(block: B.Command | B.Measure, trait: Trait, ctx: RunContext) -> Retry | None:
    """Block policy wins; otherwise the workflow default — but a blanket default never
    retries a non-idempotent verb (design 2026-07-14 §2.4)."""
    if block.retry is not None:
        return block.retry
    default = ctx.workflow.defaults.retry
    if default is not None and trait.retry_safe:
        return default
    return None
```

- [ ] **Step 4: Wrap `_run_action` in the retry loop**

Rename the existing `_run_action` to `_dispatch_action` (no body change), and add the new `_run_action`:

```python
async def _run_action(block: B.Command | B.Measure, ctx: RunContext) -> Any:
    """Retry envelope around the dispatch pipeline (design 2026-07-14 §3.2). Each attempt
    re-resolves params against fresh state and re-acquires occupancy — a retry is a fresh
    dispatch, and this is what a fresh dispatch does."""
    policy = _effective_retry(block, lookup(block.device, block.verb), ctx)
    attempts = 1 if policy is None else policy.attempts
    backoff = 0.0 if policy is None else parse_duration(policy.backoff)
    for attempt in range(1, attempts + 1):
        await ctx.gate.wait()  # a pause during a retry storm quiesces at the next attempt
        try:
            return await _dispatch_action(block, ctx)
        except Exception as exc:
            if attempt == attempts or not _is_retryable(exc):
                raise
            ctx.emit(
                "block_retried", block.id,
                attempt=attempt, of=attempts, error=str(exc),
            )
            await ctx.clock.sleep(backoff)
    raise AssertionError("unreachable: the loop either returns or raises")  # pragma: no cover
```

`_run_measure` (`execute.py:197`) already calls `_run_action`, so measures get retry with no further change.

- [ ] **Step 5: Run the tests**

Run: `.venv/bin/python -m pytest tests/test_experiment_retry.py -v`
Expected: all PASS.

- [ ] **Step 6: Run the gate**

Run: `.venv/bin/python -m pytest -q && .venv/bin/python -m mypy && .venv/bin/python -m ruff check . && awk 'length>100 {print FILENAME":"FNR}' src/lab_devices/experiment/*.py tests/test_experiment_*.py`
Expected: all PASS, awk silent.

- [ ] **Step 7: Commit**

```bash
git add src/lab_devices/experiment/execute.py tests/test_experiment_retry.py
git commit -m "feat(experiment): retry policy on command and measure blocks"
```

---

## Task 6: Executor — `on_error: continue`

**Files:**
- Modify: `src/lab_devices/experiment/errors.py`
- Modify: `src/lab_devices/experiment/context.py`
- Modify: `src/lab_devices/experiment/execute.py`
- Modify: `src/lab_devices/experiment/run.py`
- Modify: `src/lab_devices/experiment/__init__.py` (re-export `ToleratedError`)
- Test: `tests/test_experiment_on_error.py` (create)

**Interfaces:**
- Consumes: `BlockBase.on_error`.
- Produces: `errors.ToleratedError(block_id: str, error: str)` (frozen dataclass); `RunContext.tolerated: list[ToleratedError]`; `RunReport.tolerated_errors: tuple[ToleratedError, ...]`; run-log event `block_error_tolerated` with `data={"error": str}`.

**Context you need.**

`execute_block` (`execute.py:160`) is where a block's failure is turned into a `BlockFailedError`. That is where the catch goes.

**What `on_error: continue` must NEVER swallow:**

| Error | Why |
|---|---|
| `asyncio.CancelledError` / `RunAbortedError` | An operator abort must never be absorbed. `CancelledError` is a `BaseException`, so `except Exception` misses it — but the existing code catches `BaseExceptionGroup` explicitly, so be careful. |
| `InvariantViolationError` | A proven-impossible occupancy state; the safety model is broken. |
| `BaseExceptionGroup` from a `parallel` | Handled below. |

**The `parallel` interaction — this is feature #3 and the most important test in the plan.** `_run_parallel` (`execute.py:261`) uses an `asyncio.TaskGroup`, which cancels siblings only when a lane **raises**. So:
- `on_error: "continue"` on a **parallel child** → the child's `execute_block` absorbs the failure and returns normally → the TaskGroup never sees an exception → **the siblings run to completion.** One bad vial no longer kills the other fourteen.
- `on_error: "continue"` on the **`parallel` block itself** → the TaskGroup raises a `BaseExceptionGroup`, `execute_block` catches it at the parallel's own frame, and the parent continues to the next sibling.

For the second case, `execute_block` currently re-raises `BaseExceptionGroup` untouched (`execute.py:168-169`). It must now be tolerable when `on_error == "continue"` — but still re-raised when the group contains a `CancelledError` or an `InvariantViolationError`.

`RunReport` is constructed **positionally** at `run.py:137`, so `tolerated_errors` must be declared **after** `persistence_errors` with a default.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_experiment_on_error.py`:

```python
import httpx
import pytest

from lab_devices.client import LabClient
from lab_devices.experiment.context import RunOptions
from lab_devices.experiment.errors import InvariantViolationError
from lab_devices.experiment.run import ExperimentRun
from tests.experiment_run_helpers import make_workflow
from tests.fakeclock import FakeClock, drive
from tests.fakelab import FakeLab


def _client(fake):
    return LabClient("http://fake", transport=httpx.MockTransport(fake.handler))


@pytest.mark.asyncio
async def test_tolerated_failure_continues_to_the_next_sibling():
    fake = FakeLab()
    fake.add_device("densitometer_1", "densitometer")
    fake.add_device("valve_1", "valve")
    fake.inject_error("densitometer_1", "measure", "hardware_error", "flaky", times=10)
    clock = FakeClock()
    workflow = make_workflow(
        [
            {"measure": {"device": "densitometer_1", "verb": "measure", "into": "od_1"},
             "on_error": "continue"},
            {"command": {"device": "valve_1", "verb": "home"}},
        ],
        streams={"od_1": {}},
    )
    report = await drive(clock, ExperimentRun(
        _client(fake), workflow, options=RunOptions(clock=clock)
    ).execute())
    assert report.status == "completed"
    assert ("valve_1", "home") in [(d, c) for d, c, _ in fake.calls]  # sibling still ran
    assert len(report.tolerated_errors) == 1
    assert report.tolerated_errors[0].block_id == "blocks[0]"
    assert "block_error_tolerated" in [e.kind for e in report.log.events]
    assert report.state.streams["od_1"].samples == []  # the sample really was dropped


@pytest.mark.asyncio
async def test_a_tolerated_parallel_lane_leaves_its_siblings_running():
    """Feature #3: one bad vial must not kill the other fourteen."""
    fake = FakeLab()
    for i in (1, 2, 3):
        fake.add_device(f"densitometer_{i}", "densitometer")
    fake.inject_error("densitometer_2", "measure", "hardware_error", "flaky", times=10)
    clock = FakeClock()
    workflow = make_workflow(
        [{"parallel": {"children": [
            {"measure": {"device": f"densitometer_{i}", "verb": "measure", "into": f"od_{i}"},
             "on_error": "continue"}
            for i in (1, 2, 3)
        ]}}],
        streams={"od_1": {}, "od_2": {}, "od_3": {}},
    )
    report = await drive(clock, ExperimentRun(
        _client(fake), workflow, options=RunOptions(clock=clock)
    ).execute())
    assert report.status == "completed"
    assert len(report.state.streams["od_1"].samples) == 1
    assert len(report.state.streams["od_2"].samples) == 0  # the bad vial dropped its sample
    assert len(report.state.streams["od_3"].samples) == 1  # the good vials are untouched
    assert len(report.tolerated_errors) == 1


@pytest.mark.asyncio
async def test_tolerance_on_the_parallel_itself_abandons_the_container():
    fake = FakeLab()
    for i in (1, 2):
        fake.add_device(f"densitometer_{i}", "densitometer")
    fake.add_device("valve_1", "valve")
    fake.inject_error("densitometer_2", "measure", "hardware_error", "flaky", times=10)
    clock = FakeClock()
    workflow = make_workflow(
        [
            {"parallel": {"children": [
                {"measure": {"device": f"densitometer_{i}", "verb": "measure",
                             "into": f"od_{i}"}} for i in (1, 2)
            ]}, "on_error": "continue"},
            {"command": {"device": "valve_1", "verb": "home"}},
        ],
        streams={"od_1": {}, "od_2": {}},
    )
    report = await drive(clock, ExperimentRun(
        _client(fake), workflow, options=RunOptions(clock=clock)
    ).execute())
    assert report.status == "completed"
    assert ("valve_1", "home") in [(d, c) for d, c, _ in fake.calls]
    assert len(report.tolerated_errors) == 1


@pytest.mark.asyncio
async def test_gap_after_is_still_honored_after_a_tolerated_block():
    fake = FakeLab()
    fake.add_device("densitometer_1", "densitometer")
    fake.inject_error("densitometer_1", "measure", "hardware_error", "flaky", times=10)
    clock = FakeClock()
    workflow = make_workflow(
        [{"measure": {"device": "densitometer_1", "verb": "measure", "into": "od_1"},
          "on_error": "continue", "gap_after": "45s"}],
        streams={"od_1": {}},
    )
    await drive(clock, ExperimentRun(
        _client(fake), workflow, options=RunOptions(clock=clock)
    ).execute())
    assert clock.now() >= 45.0


@pytest.mark.asyncio
async def test_retry_then_tolerate_composes():
    """Retry first; only a persistent fault reaches the tolerance."""
    fake = FakeLab()
    fake.add_device("densitometer_1", "densitometer")
    fake.inject_error("densitometer_1", "measure", "hardware_error", "flaky", times=10)
    clock = FakeClock()
    workflow = make_workflow(
        [{"measure": {"device": "densitometer_1", "verb": "measure", "into": "od_1"},
          "retry": {"attempts": 3, "backoff": "2s"}, "on_error": "continue"}],
        streams={"od_1": {}},
    )
    report = await drive(clock, ExperimentRun(
        _client(fake), workflow, options=RunOptions(clock=clock)
    ).execute())
    assert report.status == "completed"
    kinds = [e.kind for e in report.log.events]
    assert kinds.count("block_retried") == 2  # exhausted the policy...
    assert kinds.count("block_error_tolerated") == 1  # ...then tolerated the failure


@pytest.mark.asyncio
async def test_an_invariant_violation_is_never_tolerated():
    """A proven-impossible state means the safety model is broken. Fail the run."""
    fake = FakeLab()
    fake.add_device("densitometer_1", "densitometer")
    fake.inject_error("densitometer_1", "measure", "busy", "device busy", times=10)
    clock = FakeClock()
    workflow = make_workflow(
        [{"measure": {"device": "densitometer_1", "verb": "measure", "into": "od_1"},
          "on_error": "continue"}],
        streams={"od_1": {}},
    )
    run = ExperimentRun(_client(fake), workflow, options=RunOptions(clock=clock))
    with pytest.raises(InvariantViolationError):
        await drive(clock, run.execute())
    assert run.report.status == "failed"
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_experiment_on_error.py -v`
Expected: FAIL — every run dies on the injected fault; `RunReport` has no `tolerated_errors`.

- [ ] **Step 3: Add `ToleratedError`**

In `errors.py`:

```python
@dataclass(frozen=True)
class ToleratedError:
    """A block failure absorbed by `on_error: continue` (design 2026-07-14 §3.4)."""

    block_id: str
    error: str
```

Re-export it from `src/lab_devices/experiment/__init__.py` alongside the other public errors.

- [ ] **Step 4: Add `RunContext.tolerated`**

In `context.py`, import `ToleratedError` and add to `RunContext`:

```python
    tolerated: list[ToleratedError] = field(default_factory=list)
```

- [ ] **Step 5: Catch in `execute_block`**

Replace `execute_block` (`execute.py:160`):

```python
def _tolerable(exc: BaseException) -> bool:
    """An abort and a broken safety invariant escape every tolerance (design §3.3)."""
    if isinstance(exc, (asyncio.CancelledError, InvariantViolationError)):
        return False
    if isinstance(exc, BaseExceptionGroup):
        # A parallel lane may have been cancelled, or may have violated an invariant.
        return not any(not _tolerable(e) for e in exc.exceptions)
    return True


async def execute_block(block: B.Block, ctx: RunContext) -> None:
    """One block: pause gate, per-type execution, exactly-once failure events (§7, §10)."""
    await ctx.gate.wait()
    ctx.emit("block_started", block.id)
    try:
        await _execute_inner(block, ctx)
    except (BlockFailedError, InvariantViolationError) as exc:
        # the origin frame already emitted its event
        if block.on_error == "continue" and _tolerable(exc):
            _tolerate(block, exc, ctx)
            return
        raise
    except BaseExceptionGroup as exc:
        # parallel children emitted their own events (plan 4b)
        if block.on_error == "continue" and _tolerable(exc):
            _tolerate(block, exc, ctx)
            return
        raise
    except asyncio.CancelledError:
        raise  # an abort is never a block failure and is never tolerated
    except Exception as exc:
        ctx.emit("block_failed", block.id, error=str(exc))
        if block.on_error == "continue":
            _tolerate(block, exc, ctx)
            return
        raise BlockFailedError(str(block.id), str(exc)) from exc
    ctx.emit("block_finished", block.id)


def _tolerate(block: B.Block, exc: BaseException, ctx: RunContext) -> None:
    """Absorb a failure at this block and let the parent proceed (design §3.3)."""
    ctx.tolerated.append(ToleratedError(str(block.id), str(exc)))
    ctx.emit("block_error_tolerated", block.id, error=str(exc))
```

Import `ToleratedError` in `execute.py`.

**Careful:** `RunAbortedError` is raised by `ExperimentRun.execute()` *after* the walk, never inside a block, so it needs no special case here. `asyncio.CancelledError` is what actually propagates through a block during an abort.

**Careful:** the `except asyncio.CancelledError: raise` arm must come **before** `except Exception` — although `CancelledError` is a `BaseException` in 3.14 and would not be caught by `except Exception` anyway, the explicit arm documents the intent and guards against a future change.

- [ ] **Step 6: Surface it on the report**

In `run.py`, add to `RunReport` **after** `persistence_errors` (positional construction at `run.py:137`):

```python
    tolerated_errors: tuple[ToleratedError, ...] = ()
```

and pass it in the final `RunReport(...)` construction (the keyword one, `run.py:183`):

```python
            tolerated_errors=tuple(ctx.tolerated),
```

Import `ToleratedError` in `run.py`.

- [ ] **Step 7: Run the tests**

Run: `.venv/bin/python -m pytest tests/test_experiment_on_error.py -v`
Expected: all PASS.

- [ ] **Step 8: Run the gate**

Run: `.venv/bin/python -m pytest -q && .venv/bin/python -m mypy && .venv/bin/python -m ruff check . && awk 'length>100 {print FILENAME":"FNR}' src/lab_devices/experiment/*.py tests/test_experiment_*.py`
Expected: all PASS, awk silent.

- [ ] **Step 9: Commit**

```bash
git add src/lab_devices/experiment/errors.py src/lab_devices/experiment/context.py \
        src/lab_devices/experiment/execute.py src/lab_devices/experiment/run.py \
        src/lab_devices/experiment/__init__.py tests/test_experiment_on_error.py
git commit -m "feat(experiment): on_error tolerance and per-lane fault isolation

on_error: continue on a parallel child absorbs the failure inside that child's task,
so the TaskGroup never cancels its siblings — one bad vial no longer kills the other
fourteen."
```

---

## Task 7: Studio backend

**Files:**
- Modify: `webapp/backend/experiment_studio/roles.py:11` and `:78`
- Modify: `webapp/backend/experiment_studio/runner.py:143-174` (`_write_report`)
- Test: `webapp/backend/tests/` (follow the existing test-file naming there)

**Interfaces:**
- Consumes: `RunReport.tolerated_errors`.
- Produces: `report.json` gains `"tolerated_errors": [{"block_id": ..., "error": ...}, ...]`.

**Context you need — there is a silent-failure bug here.** `roles.py:11` mirrors the engine's block-key rule:

```python
# Mirrors the engine serializer: block dict = one type key + optional timing keys.
_TIMING_KEYS = ("label", "gap_after", "start_offset")
```

and `roles.py:78`:

```python
type_keys = [k for k in block if k not in _TIMING_KEYS]
if len(type_keys) != 1:
    continue          # <-- silently skips the block
```

A block carrying `retry` or `on_error` would be **silently skipped** by the role→device substitution walker, so its `device` stays a *role name* and the run fails later with a confusing "unknown device". This is a wrong-behaviour bug, not a clean error.

- [ ] **Step 1: Write the failing test**

`roles.substitute(workflow, mapping) -> tuple[dict, list[diag]]` takes the **workflow** dict (not the whole `ExperimentDoc`) and returns `(substituted, diagnostics)`. Append to `webapp/backend/tests/test_roles.py`:

```python
def test_substitute_handles_blocks_with_retry_and_on_error():
    workflow = {
        "schema_version": 1,
        "streams": {"od_1": {}},
        "blocks": [{
            "measure": {"device": "od_meter", "verb": "measure", "into": "od_1"},
            "retry": {"attempts": 3, "backoff": "2s"},
            "on_error": "continue",
        }],
    }
    out, diags = substitute(workflow, {"od_meter": "densitometer_1"})
    assert diags == []
    assert out["blocks"][0]["measure"]["device"] == "densitometer_1"
    assert out["blocks"][0]["retry"] == {"attempts": 3, "backoff": "2s"}
    assert out["blocks"][0]["on_error"] == "continue"
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd webapp/backend && .venv/bin/python -m pytest tests/test_roles.py -q -k retry_and_on_error`
Expected: FAIL — device is still `"od_meter"`. `_walk` (`roles.py:80`) computed `type_keys = ["measure", "retry", "on_error"]`, saw `len != 1`, and `continue`d past the block **silently**.

- [ ] **Step 3: Fix the mirror**

In `roles.py:12`:

```python
# Mirrors the engine serializer (serialize.py _BLOCK_KEYS): a block dict is one type key
# plus optional block-level keys. Keep in sync or blocks are silently skipped in _walk.
_BLOCK_KEYS = ("label", "gap_after", "start_offset", "retry", "on_error")
```

and update the `type_keys` computation in `_walk` (`roles.py:80`) to use it. Delete `_TIMING_KEYS`.

- [ ] **Step 4: Add `tolerated_errors` to `report.json`**

In `runner.py`'s `_write_report` (`:143`), alongside `finalize_errors`/`persistence_errors`:

```python
        "tolerated_errors": [
            {"block_id": t.block_id, "error": t.error} for t in report.tolerated_errors
        ],
```

- [ ] **Step 5: Run the backend gate**

Run: `cd webapp/backend && .venv/bin/python -m pytest -q && .venv/bin/python -m mypy && .venv/bin/python -m ruff check .`
Expected: all PASS. (`mypy` takes no path argument.)

- [ ] **Step 6: Commit**

```bash
git add webapp/backend/
git commit -m "fix(studio): role substitution silently skipped blocks with new block keys

roles.py mirrored the engine's block-key rule and 'continue'd past any block whose
shape it did not recognise, leaving the role name in place as a device id. Adding
retry/on_error to the engine would have made that fire silently."
```

---

## Task 8: Studio frontend

**Files:**
- Modify: `webapp/frontend/src/types/doc.ts:7-18, 59-72`
- Modify: `webapp/frontend/src/builder/tree.ts:9-14`
- Modify: `webapp/frontend/src/builder/convert.ts:32, 61-64, 155-211`
- Modify: `webapp/frontend/src/builder/Inspector.tsx:83-110`
- Modify: `webapp/frontend/src/builder/summary.ts`
- Modify: `webapp/frontend/src/run/describeEvent.ts:14-40`, `src/run/EventLog.tsx:15-22`
- Modify: `webapp/frontend/src/types/records.ts`, `src/records/RecordViewer.tsx:79-104`
- Test: `webapp/frontend/src/builder/convert.test.ts`, `src/run/describeEvent.test.ts`

**Context you need.** `convert.ts:32` `TIMING_KEYS` is the third mirror of the block-key rule; missing it throws `DocConvertError` in the builder **and** kills the read-only `records/WorkflowSnapshot.tsx`. Worse, `nodeToBlock` (`convert.ts:155`) rebuilds each block dict from scratch, so **without plumbing, `retry`/`on_error` are silently dropped on any builder save** — a data-loss bug. Round-trip is not optional.

- [ ] **Step 1: Write the failing round-trip test**

Append to `webapp/frontend/src/builder/convert.test.ts` (match the file's existing style):

```ts
it('round-trips retry and on_error through the builder tree', () => {
  const doc: BlockJson[] = [
    {
      measure: { device: 'od_meter', verb: 'measure', into: 'od_1' },
      label: 'read OD',
      retry: { attempts: 3, backoff: '2s' },
      on_error: 'continue',
    },
  ]
  expect(treeToDoc(docToTree(doc))).toEqual(doc)
})
```

Use the real exported names from `convert.ts` (`docToTree`/`treeToDoc` are a guess — read the module).

- [ ] **Step 2: Run to verify it fails**

Run: `cd webapp/frontend && npm test -- --run convert`
Expected: FAIL — `DocConvertError: block must have exactly one type key`.

- [ ] **Step 3: Add the types**

In `src/types/doc.ts`:

```ts
export type RetryJson = {
  attempts: number
  backoff?: string
  allow_repeat?: boolean
}
```

Add to `BlockJson` (the block-level union at `:59`):

```ts
  retry?: RetryJson
  on_error?: 'fail' | 'continue'
```

Add the workflow-level default:

```ts
  defaults?: { retry?: RetryJson }
```

- [ ] **Step 4: Plumb it through the tree and the converter**

`src/builder/tree.ts` — add to `NodeBase`:

```ts
  retry?: RetryJson
  onError?: 'fail' | 'continue'
```

`src/builder/convert.ts`:

```ts
const BLOCK_KEYS = ['label', 'gap_after', 'start_offset', 'retry', 'on_error']
```

(rename from `TIMING_KEYS`; update the `type_keys` computation at `:61`.)

In `blockToNode`, carry `retry` → `node.retry` and `on_error` → `node.onError`. In `nodeToBlock`, emit them back — `retry` verbatim, and `on_error` **only when it is `'continue'`** (so a default-`fail` block round-trips to a dict with no `on_error` key, matching the engine's `block_to_dict`).

- [ ] **Step 5: Run the round-trip test**

Run: `cd webapp/frontend && npm test -- --run convert`
Expected: PASS.

- [ ] **Step 6: Add the Inspector controls**

In `src/builder/Inspector.tsx`, extend the existing "Timing & label" section (`:83`):

- An `on_error` select (`fail` / `continue`) — shown for **every** block type.
- A `retry` group (`attempts` number input, `backoff` text input) — shown **only** for `command`/`measure` nodes.
- The `retry` group is disabled with the hint *"`dispense` is not idempotent — a retry may repeat it"* when the verb catalog reports `retry_safe: false` for that node's verb, unless `allow_repeat` is checked. Surface `allow_repeat` as a checkbox inside the retry group, only for non-`retry_safe` verbs.

The verb catalog already reaches the frontend (Task 2 added `retry_safe` to `VerbEntry`); find where the frontend consumes `verb_catalog()` and read `retry_safe` from there.

Update `src/builder/summary.ts` so a block card shows a compact `↻3` / `⤳` marker when `retry` / `on_error: continue` is set — otherwise these are invisible in the tree.

- [ ] **Step 7: Add the run-log event arms**

`src/run/describeEvent.ts` — add cases (both kinds currently fall through to the `default:` and render as raw JSON, so this is polish, not a break):

```ts
    case 'block_retried':
      return `retrying ${e.block_id ?? ''} (attempt ${d.attempt}/${d.of}): ${d.error}`
    case 'block_error_tolerated':
      return `tolerated failure in ${e.block_id ?? ''}: ${d.error}`
```

Match the file's exact formatting idiom — read the neighbouring cases. Add matching assertions to `describeEvent.test.ts`.

`src/run/EventLog.tsx` — add to `KIND_COLOR`: `block_retried` amber, `block_error_tolerated` amber/red. Follow the existing Tailwind class idiom.

- [ ] **Step 8: Display `tolerated_errors` on the record**

`src/types/records.ts` — add to `RecordReport`:

```ts
  tolerated_errors?: { block_id: string; error: string }[]
```

`src/records/RecordViewer.tsx` (`:79-104`) — the warning panel already renders `finalize_errors` / `persistence_errors`. Add a `tolerated_errors` panel in the same idiom, headed *"N block failure(s) tolerated"*. **This is the point of the field:** a run that dropped 40 samples must not look identical to a clean one.

- [ ] **Step 9: Run the frontend gate**

Run: `cd webapp/frontend && npm run lint && npm run typecheck && npm test -- --run && npm run build`
Expected: all PASS. (Two pre-existing oxlint fast-refresh warnings are expected; exit code 0.)

- [ ] **Step 10: Commit**

```bash
git add webapp/frontend/
git commit -m "feat(studio): author and display retry / on_error in the builder and run log"
```

---

## Task 9: The morbidostat example

**Files:**
- Modify: `examples/morbidostat.json`
- Modify: `examples/morbidostat-demo-speed.json`
- Modify: `tests/test_examples_morbidostat.py`

**Context you need.** This example is the *proof*. `docs/experiment-engine-limitations.md` §0 says the morbidostat "cannot actually be run to completion on this stack today". After this task it can.

The two docs are `ExperimentDoc`s (`doc_version`, `name`, `roles`, `workflow`), so engine block paths are relative to `workflow.blocks`. Three changes:

1. **Retry on all six densitometer reads.** Three `measure_blank` (`workflow.blocks[0].children[7].children[0..2]`) and three `measure` (`workflow.blocks[0].children[10].body[0].body[0].children[0..2]`). Use `{"attempts": 3, "backoff": "2s"}` — `measure`/`measure_blank` are `retry_safe`, so no `allow_repeat`. **This alone would have saved the run that died at cycle 17.**
2. **`on_error: "continue"` on the three OD reads** (not the blanks — a failed blank is a setup failure and should stop the run before any culture is committed). Then **guard each tube's decision tree with `count(od_N) > 0`** per spec §5.3 — validation will fail without it, which is the design working as intended.
3. **Restore the parallel thermostat setup.** The example was forced to serialize its one-time thermostat/blank/valve setup because of the duplicate-serial store race (`experiment-engine-limitations.md`, final section — parallel `set_thermostat` across the three simulated densitometers fails ~92% of the time). `set_thermostat` is `retry_safe`; with `retry: {"attempts": 3, "backoff": "1s"}` the parallel setup is safe again. **Do this only after Task 11 confirms it on real hardware** — leave a note in the commit if you reach Task 9 first.

- [ ] **Step 1: Read the current example and the algorithm doc**

Read `examples/morbidostat.json` in full, plus `docs/morbidostat_algorithm.md` §1 and the §0/§2 sections of `docs/experiment-engine-limitations.md`. You must understand the decision tree before you wrap it in a guard.

- [ ] **Step 2: Apply the three changes to `morbidostat.json`**

- [ ] **Step 3: Validate it**

Run: `.venv/bin/python -c "from lab_devices.experiment.validate import load_and_validate; load_and_validate('examples/morbidostat.json')"`

**Careful:** this is an `ExperimentDoc`, not a bare workflow. Check how `tests/test_examples_morbidostat.py:155-199` loads it and use the same path.

Expected: no `ValidationError`. If you get `"stat over stream 'od_1' has no preceding measure on some path"`, the guard from change (2) is missing or misplaced — that is the validator doing its job.

- [ ] **Step 4: Mirror the changes into `morbidostat-demo-speed.json`**

- [ ] **Step 5: Run the example tests**

Run: `.venv/bin/python -m pytest tests/test_examples_morbidostat.py -v`
Expected: all PASS. The closed-loop test may need its assertions updated if the guard branch changed the block paths — update them.

- [ ] **Step 6: Run the gate and commit**

```bash
.venv/bin/python -m pytest -q && .venv/bin/python -m mypy && .venv/bin/python -m ruff check .
git add examples/ tests/test_examples_morbidostat.py
git commit -m "feat(examples): morbidostat survives a transient device fault

Retry on the six densitometer reads, on_error: continue on the three OD reads with
count(od_N) > 0 guards on each tube's decision tree, and the one-time thermostat setup
back in parallel now that retry covers the duplicate-serial store race."
```

---

## Task 10: Documentation

**Files:**
- Modify: `docs/experiment-engine-limitations.md` §0, the summary table, and the closing paragraph
- Modify: `examples/README.md:165-171`
- Modify: `docs/superpowers/specs/2026-07-07-experiment-orchestrator-design.md` §5 and §15

- [ ] **Step 1: Rewrite `experiment-engine-limitations.md` §0**

Keep the incident — it is the motivation and it is a good story. Change the framing from "here is what is missing" to "here is what shipped, and here is how to use it". Document:

- `retry` (`attempts` is TOTAL tries; `backoff`; `allow_repeat`)
- `on_error: continue|fail`, and that it is what gives per-device fault isolation
- `defaults.retry`, and why it never applies to a non-idempotent verb
- The **guard idiom**: a tolerated `measure` requires `count(S) > 0` before any windowed read, and *why* (the fail-safe on an empty window would otherwise re-introduce the very failure we removed)
- The **double-dose caveat**: `pump.dispense` is relative; `allow_repeat` is an explicit acceptance that a retry may repeat the action

Renumber nothing — leave §1–§8 as they are. Update the §0 row of the summary table and the closing paragraph ("If only two were built…"), which currently reasons about a world where none of this exists.

- [ ] **Step 2: Fix `examples/README.md:165-171`**

It currently says: **"A single flaky sensor read will destroy your run."** That is no longer true. Replace with the authoring guidance (retry, `on_error`, the guard idiom, the double-dose caveat).

- [ ] **Step 3: Update the orchestrator design reference**

`2026-07-07-experiment-orchestrator-design.md` §5 (block taxonomy table) and §15 (serialization + the full JSON example) are the closest thing this repo has to an authoring reference. Add the two block keys and the `defaults` section. Mark the edits as an amendment dated 2026-07-14 referencing the new spec, matching how earlier amendments in that file are marked.

- [ ] **Step 4: Commit**

```bash
git add docs/ examples/README.md
git commit -m "docs: engine fault tolerance shipped; retract the flaky-read warning"
```

---

## Task 11: Real-hardware validation on lab-bridge preprod

**Files:** none (validation only). Write scratch scripts to the session scratchpad, not the repo.

**Context you need.** `ssh khamit@111.88.145.138`, then drive everything through one python script piped into the jupyter container:

```bash
ssh khamit@111.88.145.138 docker exec -i lab-bridge-jupyter-1 python - <<'PY'
...
PY
```

First `pip install --upgrade` the local `lab_devices` build into `lab-bridge-jupyter-1` so the container runs *this branch*. The target lab is `windows_arm64_test_client` (7 devices). Known gotchas: the simulated pump agent **requires a positive `speed_ml_min`** on `dispense` (the library leaves it optional; omitting it fails the block), and the densitometer needs a `measure_blank` job before `measure`.

**Why this test is worth doing.** We have a *genuine, reproducible transient fault* to aim at, which is rare. Per `experiment-engine-limitations.md`, the test client's three simulated densitometers all report serial `25-006`, so they alias onto one agent state file (`densitometer-25-006.json`); a `parallel` block of `set_thermostat` across all three fails **23 times in 25** on a non-atomic rename. That is a real, transient, retry-curable fault of exactly the class feature #0 exists for.

- [ ] **Step 1: Deploy this branch into the container**

Build and install the branch's `lab_devices` into `lab-bridge-jupyter-1`. Confirm the version, and confirm `windows_arm64_test_client` is online with its 7 devices.

- [ ] **Step 2: Reproduce the baseline failure**

Run a workflow with a `parallel` block of `set_thermostat` across `densitometer_1/2/3`, **no retry**. Repeat ~10 times.
Expected: most runs fail with `block_failed` naming `densitometer-25-006.json` ("The process cannot access the file because it is being used by another process").

**If it does NOT reproduce, stop and report.** The lab-bridge team may have fixed the duplicate serials since the limitations doc was written — in which case this test has lost its fault source and you need another (ask before inventing one).

- [ ] **Step 3: Prove retry fixes it**

Same workflow, `retry: {"attempts": 3, "backoff": "1s"}` on each `set_thermostat`. Repeat ~10 times.
Expected: **all runs complete.** `block_retried` events appear in the run log. `set_thermostat` is `retry_safe`, so no `allow_repeat` is needed.

- [ ] **Step 4: Prove `on_error: continue` tolerates it**

Same workflow, **no retry**, `on_error: "continue"` on each `set_thermostat`.
Expected: runs **complete** (status `"completed"`), with the failures listed in `report.tolerated_errors` instead of killing the run.

- [ ] **Step 5: Prove per-lane isolation**

A `parallel` of three `measure` blocks, each `on_error: "continue"`, with one densitometer made to fail (disconnect it, or point one lane at a bogus device id).
Expected: the two healthy lanes still record their samples; only the bad lane's stream is short.

- [ ] **Step 6: Run the full demo-speed morbidostat to completion**

Run the updated `examples/morbidostat-demo-speed.json` (25 cycles) end to end against `windows_arm64_test_client`.
Expected: **status `"completed"`.** This is the headline result — the doc says this workflow died at cycle 17 of 25. Record the number of `block_retried` and `block_error_tolerated` events; a run with zero of both is a weaker result (the fault simply did not fire), so say so plainly rather than claiming more than the evidence supports.

- [ ] **Step 7: Report the results**

Write the measured numbers (trials, failures, retries) into the PR description. If Step 3 confirmed the parallel thermostat setup is now safe, that unblocks change (3) of Task 9 — go back and make it.

---

## Final gate

- [ ] Engine: `.venv/bin/python -m pytest && .venv/bin/python -m mypy && .venv/bin/python -m ruff check .`
- [ ] Line length: `awk 'length>100 {print FILENAME":"FNR}' src/lab_devices/experiment/*.py tests/test_experiment_*.py` prints nothing
- [ ] Backend: `cd webapp/backend && .venv/bin/python -m pytest -q && .venv/bin/python -m mypy && .venv/bin/python -m ruff check .`
- [ ] Frontend: `cd webapp/frontend && npm run lint && npm run typecheck && npm test -- --run && npm run build`
- [ ] Preprod: Task 11 steps 2–6 all confirmed on `windows_arm64_test_client`
- [ ] Open the PR with the measured preprod numbers in the description
