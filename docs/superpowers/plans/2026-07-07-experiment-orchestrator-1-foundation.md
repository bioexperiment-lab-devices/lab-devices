# Experiment Orchestrator — Increment 1: Foundation (AST + Registry + JSON) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the `lab_devices.experiment` submodule's foundation: a typed block AST, the command-trait registry, and lossless pure-JSON load/save of a workflow document.

**Architecture:** Pure, synchronous, hardware-free layer. Dataclasses model the AST (design §5); a `(device-type, verb) → Trait` registry is the single source of truth for which verbs exist and their `completion`/`state_effect` traits (design §4); a serialize module maps JSON dicts ↔ AST, validating verbs at load and round-tripping losslessly. Expressions are stored as unparsed strings/literals here — parsing is Increment 2.

**Tech Stack:** Python 3.11, standard-library `dataclasses`/`json`/`pathlib`, pytest. No async, no httpx, no hardware in this increment.

## Global Constraints

- Python `>=3.11`; code must pass `python -m mypy` (strict) and `python -m ruff check .` (line-length 100, target py311).
- Style matches the core: `from __future__ import annotations` at the top of every module; dataclasses; module docstring citing the design section.
- New code lives in the `lab_devices.experiment` submodule under `src/lab_devices/experiment/`. Hatchling already ships it via `packages = ["src/lab_devices"]` — no `pyproject.toml` change needed.
- The submodule imports only the design-§3 narrow-subset surface from the parent; in this increment it imports nothing from the parent runtime. Device-type parsing mirrors the core's `Device.type` (`device_id.rsplit("_", 1)[0]`).
- Tests are hermetic (no hardware, no network) and live flat in `tests/` as `test_experiment_*.py`.
- Serialization is pure JSON. Every document carries `schema_version`, which must equal `1`; any other value is a load error.
- Expressions and conditions are stored as raw `str` (or literal `int`/`float`/`bool`); they are NOT parsed or evaluated in this increment.

---

### Task 1: Submodule scaffold + error taxonomy

**Files:**
- Create: `src/lab_devices/experiment/__init__.py`
- Create: `src/lab_devices/experiment/errors.py`
- Test: `tests/test_experiment_smoke.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `ExperimentError(Exception)`, `WorkflowLoadError(ExperimentError)`, `UnknownVerbError(WorkflowLoadError)`. Importable as `from lab_devices.experiment.errors import ...`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_experiment_smoke.py
from lab_devices.experiment.errors import (
    ExperimentError,
    UnknownVerbError,
    WorkflowLoadError,
)


def test_error_hierarchy():
    assert issubclass(WorkflowLoadError, ExperimentError)
    assert issubclass(UnknownVerbError, WorkflowLoadError)
    err = UnknownVerbError("nope")
    assert isinstance(err, ExperimentError)
    assert str(err) == "nope"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_experiment_smoke.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'lab_devices.experiment'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/lab_devices/experiment/__init__.py
"""Declarative experiment-orchestration layer on top of lab_devices. See design §1."""

from __future__ import annotations
```

```python
# src/lab_devices/experiment/errors.py
"""Exception taxonomy for the experiment layer. See design §11-12."""

from __future__ import annotations


class ExperimentError(Exception):
    """Root of every error raised by the experiment layer."""


class WorkflowLoadError(ExperimentError):
    """A workflow document is malformed or structurally invalid at load time."""


class UnknownVerbError(WorkflowLoadError):
    """A command targets a (device-type, verb) pair absent from the registry."""
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_experiment_smoke.py -v && python -m mypy && python -m ruff check .`
Expected: PASS; mypy and ruff clean.

- [ ] **Step 5: Commit**

```bash
git add src/lab_devices/experiment/__init__.py src/lab_devices/experiment/errors.py tests/test_experiment_smoke.py
git commit -m "feat(experiment): submodule scaffold + error taxonomy"
```

---

### Task 2: Command-trait registry

**Files:**
- Create: `src/lab_devices/experiment/registry.py`
- Test: `tests/test_experiment_registry.py`

**Interfaces:**
- Consumes: `UnknownVerbError` from Task 1.
- Produces:
  - `Completion = Literal["job", "immediate"]`, `StateEffect = Literal["none", "mode"]`.
  - `Teardown(verb: str, params: dict[str, Any])` dataclass.
  - `Trait(completion: Completion, state_effect: StateEffect, teardown: Teardown | None)` dataclass.
  - `device_type(device_id: str) -> str`.
  - `lookup(device_id: str, verb: str) -> Trait` (raises `UnknownVerbError`).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_experiment_registry.py
import pytest

from lab_devices.experiment.errors import UnknownVerbError
from lab_devices.experiment.registry import Teardown, device_type, lookup


def test_device_type_strips_index():
    assert device_type("pump_1") == "pump"
    assert device_type("densitometer_12") == "densitometer"


def test_job_command_trait():
    t = lookup("pump_1", "dispense")
    assert t.completion == "job"
    assert t.state_effect == "none"
    assert t.teardown is None


def test_continuous_mode_has_teardown():
    assert lookup("pump_1", "rotate").teardown == Teardown("stop")
    assert lookup("densitometer_1", "set_led").teardown == Teardown("set_led", {"level": 0})
    assert lookup("densitometer_1", "set_thermostat").teardown == Teardown(
        "set_thermostat", {"enabled": False}
    )


def test_instant_config_trait():
    t = lookup("valve_1", "configure")
    assert t.completion == "immediate"
    assert t.state_effect == "none"


def test_unknown_verb_raises():
    with pytest.raises(UnknownVerbError):
        lookup("pump_1", "teleport")
    with pytest.raises(UnknownVerbError):
        lookup("toaster_1", "dispense")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_experiment_registry.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'lab_devices.experiment.registry'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/lab_devices/experiment/registry.py
"""Command-trait registry: the single source of truth for the narrow subset. See design §3-4."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from lab_devices.experiment.errors import UnknownVerbError

Completion = Literal["job", "immediate"]
StateEffect = Literal["none", "mode"]


@dataclass
class Teardown:
    """How to close a continuous mode (design §4)."""

    verb: str
    params: dict[str, Any] = field(default_factory=dict)


@dataclass
class Trait:
    completion: Completion
    state_effect: StateEffect
    teardown: Teardown | None = None


_REGISTRY: dict[tuple[str, str], Trait] = {
    # pump
    ("pump", "dispense"): Trait("job", "none"),
    ("pump", "rotate"): Trait("immediate", "mode", Teardown("stop")),
    ("pump", "stop"): Trait("immediate", "none"),
    ("pump", "set_calibration"): Trait("immediate", "none"),
    # valve
    ("valve", "set_position"): Trait("job", "none"),
    ("valve", "home"): Trait("immediate", "none"),
    ("valve", "configure"): Trait("immediate", "none"),
    ("valve", "stop"): Trait("immediate", "none"),
    # densitometer
    ("densitometer", "measure"): Trait("job", "none"),
    ("densitometer", "measure_blank"): Trait("job", "none"),
    ("densitometer", "set_led"): Trait("immediate", "mode", Teardown("set_led", {"level": 0})),
    ("densitometer", "set_thermostat"): Trait(
        "immediate", "mode", Teardown("set_thermostat", {"enabled": False})
    ),
    ("densitometer", "set_tube_correction"): Trait("immediate", "none"),
    ("densitometer", "calibrate_tube"): Trait("immediate", "none"),
    ("densitometer", "stop"): Trait("immediate", "none"),
    ("densitometer", "stop_monitoring"): Trait("immediate", "none"),
}


def device_type(device_id: str) -> str:
    """Mirror the core's Device.type derivation."""
    return device_id.rsplit("_", 1)[0]


def lookup(device_id: str, verb: str) -> Trait:
    key = (device_type(device_id), verb)
    try:
        return _REGISTRY[key]
    except KeyError:
        raise UnknownVerbError(
            f"no registry entry for device-type {key[0]!r} verb {verb!r}"
        ) from None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_experiment_registry.py -v && python -m mypy && python -m ruff check .`
Expected: PASS; mypy and ruff clean.

- [ ] **Step 5: Commit**

```bash
git add src/lab_devices/experiment/registry.py tests/test_experiment_registry.py
git commit -m "feat(experiment): command-trait registry"
```

---

### Task 3: Block AST dataclasses

**Files:**
- Create: `src/lab_devices/experiment/blocks.py`
- Test: `tests/test_experiment_blocks.py`

**Interfaces:**
- Consumes: nothing.
- Produces (all `@dataclass(kw_only=True)`, all leaf/container blocks subclass `BlockBase`):
  - `ValueExpr = str | int | float | bool`
  - `BlockBase(label: str | None, gap_after: str | None, start_offset: str | None)`
  - `Command(device: str, verb: str, params: dict[str, ValueExpr])`
  - `Measure(device: str, verb: str, into: str, params: dict[str, ValueExpr])`
  - `OperatorInput(name: str, type: str, prompt, min, max, choices)`
  - `Wait(duration: str)`
  - `Serial(children: list[Block])`, `Parallel(children: list[Block])`
  - `Loop(body: list[Block], count, pace, until, check="after")`
  - `Branch(if_: str, then: list[Block], else_: list[Block] | None)`
  - `GroupRef(name: str)`
  - `Block` union of all nine concrete block types.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_experiment_blocks.py
from lab_devices.experiment.blocks import (
    Branch,
    Command,
    Loop,
    Measure,
    Serial,
)


def test_leaf_defaults_and_timing():
    cmd = Command(device="pump_1", verb="dispense", params={"volume_ml": 10})
    assert cmd.gap_after is None and cmd.start_offset is None and cmd.label is None
    assert cmd.params == {"volume_ml": 10}


def test_nested_tree_construction():
    tree = Serial(
        children=[
            Loop(
                until="mean(OD, last=5min) >= target",
                check="after",
                body=[
                    Measure(device="densitometer_1", verb="measure", into="OD"),
                    Command(
                        device="pump_1",
                        verb="dispense",
                        params={"volume_ml": "2.0 * mean(OD, last=100)"},
                        gap_after="30s",
                    ),
                ],
            ),
            Branch(if_="last(OD) > target", then=[Command(device="pump_2", verb="stop")]),
        ]
    )
    assert isinstance(tree.children[0], Loop)
    assert tree.children[0].check == "after"
    assert tree.children[0].body[1].gap_after == "30s"
    assert tree.children[1].else_ is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_experiment_blocks.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'lab_devices.experiment.blocks'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/lab_devices/experiment/blocks.py
"""Typed AST for experiment workflows. See design §5."""

from __future__ import annotations

from dataclasses import dataclass, field

# A scalar slot: a literal, or an infix-expression string (parsed in Increment 2).
ValueExpr = str | int | float | bool


@dataclass(kw_only=True)
class BlockBase:
    label: str | None = None
    gap_after: str | None = None  # serial: end-of-this -> start-of-next
    start_offset: str | None = None  # parallel: container-start -> this-start


@dataclass(kw_only=True)
class Command(BlockBase):
    device: str
    verb: str
    params: dict[str, ValueExpr] = field(default_factory=dict)


@dataclass(kw_only=True)
class Measure(BlockBase):
    device: str
    verb: str
    into: str
    params: dict[str, ValueExpr] = field(default_factory=dict)


@dataclass(kw_only=True)
class OperatorInput(BlockBase):
    name: str
    type: str
    prompt: str | None = None
    min: float | None = None
    max: float | None = None
    choices: list[str] | None = None


@dataclass(kw_only=True)
class Wait(BlockBase):
    duration: str


@dataclass(kw_only=True)
class Serial(BlockBase):
    children: list[Block] = field(default_factory=list)


@dataclass(kw_only=True)
class Parallel(BlockBase):
    children: list[Block] = field(default_factory=list)


@dataclass(kw_only=True)
class Loop(BlockBase):
    body: list[Block] = field(default_factory=list)
    count: int | None = None
    pace: str | None = None
    until: str | None = None
    check: str = "after"


@dataclass(kw_only=True)
class Branch(BlockBase):
    if_: str
    then: list[Block] = field(default_factory=list)
    else_: list[Block] | None = None


@dataclass(kw_only=True)
class GroupRef(BlockBase):
    name: str


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
)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_experiment_blocks.py -v && python -m mypy && python -m ruff check .`
Expected: PASS; mypy and ruff clean.

- [ ] **Step 5: Commit**

```bash
git add src/lab_devices/experiment/blocks.py tests/test_experiment_blocks.py
git commit -m "feat(experiment): block AST dataclasses"
```

---

### Task 4: Block deserialization (dict → AST)

**Files:**
- Create: `src/lab_devices/experiment/serialize.py`
- Test: `tests/test_experiment_serialize.py`

**Interfaces:**
- Consumes: `blocks` module (Task 3), `registry.lookup` (Task 2), `WorkflowLoadError` (Task 1).
- Produces:
  - `SCHEMA_VERSION = 1`
  - `block_from_dict(d: dict[str, Any]) -> blocks.Block` — dispatches on the single non-timing key; folds sibling `label`/`gap_after`/`start_offset` onto the block; validates command/measure verbs via `registry.lookup`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_experiment_serialize.py
import pytest

from lab_devices.experiment import blocks as B
from lab_devices.experiment.errors import UnknownVerbError, WorkflowLoadError
from lab_devices.experiment.serialize import block_from_dict


def test_command_with_timing():
    b = block_from_dict(
        {"command": {"device": "pump_1", "verb": "dispense", "params": {"volume_ml": 10}},
         "gap_after": "30s"}
    )
    assert isinstance(b, B.Command)
    assert b.device == "pump_1" and b.params == {"volume_ml": 10}
    assert b.gap_after == "30s"


def test_measure_and_loop_nesting():
    b = block_from_dict(
        {"loop": {"until": "last(OD) >= 1.0", "check": "after",
                  "body": [{"measure": {"device": "densitometer_1", "verb": "measure",
                                        "into": "OD"}}]}}
    )
    assert isinstance(b, B.Loop)
    assert b.check == "after"
    assert isinstance(b.body[0], B.Measure)
    assert b.body[0].into == "OD"


def test_branch_if_else_keyword_mapping():
    b = block_from_dict(
        {"branch": {"if": "last(OD) > 1.0",
                    "then": [{"command": {"device": "pump_2", "verb": "stop"}}],
                    "else": [{"command": {"device": "pump_1", "verb": "stop"}}]}}
    )
    assert isinstance(b, B.Branch)
    assert b.if_ == "last(OD) > 1.0"
    assert isinstance(b.else_[0], B.Command)


def test_unknown_verb_rejected_at_load():
    with pytest.raises(UnknownVerbError):
        block_from_dict({"command": {"device": "pump_1", "verb": "explode"}})


def test_multiple_type_keys_rejected():
    with pytest.raises(WorkflowLoadError):
        block_from_dict({"command": {"device": "pump_1", "verb": "stop"},
                         "measure": {"device": "densitometer_1", "verb": "measure", "into": "OD"}})


def test_loop_requires_exactly_one_of_count_or_until():
    with pytest.raises(WorkflowLoadError):
        block_from_dict({"loop": {"body": []}})
    with pytest.raises(WorkflowLoadError):
        block_from_dict({"loop": {"count": 3, "until": "last(OD) > 1", "body": []}})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_experiment_serialize.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'lab_devices.experiment.serialize'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/lab_devices/experiment/serialize.py
"""Pure-JSON <-> AST (de)serialization. See design §15."""

from __future__ import annotations

from typing import Any, Callable

from lab_devices.experiment import blocks as B
from lab_devices.experiment.errors import WorkflowLoadError
from lab_devices.experiment.registry import lookup

SCHEMA_VERSION = 1
_TIMING_KEYS = ("label", "gap_after", "start_offset")


def _req(body: Any, key: str, ctx: str) -> Any:
    if not isinstance(body, dict) or key not in body:
        raise WorkflowLoadError(f"{ctx} requires {key!r}")
    return body[key]


def _children(raw: Any, ctx: str) -> list[B.Block]:
    if not isinstance(raw, list):
        raise WorkflowLoadError(f"{ctx} must be a list")
    return [block_from_dict(c) for c in raw]


def _command(body: Any, timing: dict[str, Any]) -> B.Block:
    device, verb = _req(body, "device", "command"), _req(body, "verb", "command")
    lookup(device, verb)
    return B.Command(device=device, verb=verb, params=dict(body.get("params", {})), **timing)


def _measure(body: Any, timing: dict[str, Any]) -> B.Block:
    device = _req(body, "device", "measure")
    verb = body.get("verb", "measure")
    lookup(device, verb)
    return B.Measure(
        device=device, verb=verb, into=_req(body, "into", "measure"),
        params=dict(body.get("params", {})), **timing,
    )


def _operator_input(body: Any, timing: dict[str, Any]) -> B.Block:
    return B.OperatorInput(
        name=_req(body, "name", "operator_input"),
        type=_req(body, "type", "operator_input"),
        prompt=body.get("prompt"), min=body.get("min"), max=body.get("max"),
        choices=body.get("choices"), **timing,
    )


def _wait(body: Any, timing: dict[str, Any]) -> B.Block:
    return B.Wait(duration=_req(body, "duration", "wait"), **timing)


def _serial(body: Any, timing: dict[str, Any]) -> B.Block:
    return B.Serial(children=_children(_req(body, "children", "serial"), "serial.children"), **timing)


def _parallel(body: Any, timing: dict[str, Any]) -> B.Block:
    return B.Parallel(
        children=_children(_req(body, "children", "parallel"), "parallel.children"), **timing
    )


def _loop(body: Any, timing: dict[str, Any]) -> B.Block:
    if not isinstance(body, dict):
        raise WorkflowLoadError("loop requires an object body")
    if ("count" in body) == ("until" in body):
        raise WorkflowLoadError("loop requires exactly one of 'count' or 'until'")
    check = body.get("check", "after")
    if check not in ("before", "after"):
        raise WorkflowLoadError(f"loop check must be 'before' or 'after', got {check!r}")
    return B.Loop(
        body=_children(_req(body, "body", "loop"), "loop.body"),
        count=body.get("count"), pace=body.get("pace"),
        until=body.get("until"), check=check, **timing,
    )


def _branch(body: Any, timing: dict[str, Any]) -> B.Block:
    return B.Branch(
        if_=_req(body, "if", "branch"),
        then=_children(_req(body, "then", "branch"), "branch.then"),
        else_=_children(body["else"], "branch.else") if isinstance(body, dict) and "else" in body else None,
        **timing,
    )


def _group_ref(body: Any, timing: dict[str, Any]) -> B.Block:
    return B.GroupRef(name=_req(body, "name", "group_ref"), **timing)


_BUILDERS: dict[str, Callable[[Any, dict[str, Any]], B.Block]] = {
    "command": _command,
    "measure": _measure,
    "operator_input": _operator_input,
    "wait": _wait,
    "serial": _serial,
    "parallel": _parallel,
    "loop": _loop,
    "branch": _branch,
    "group_ref": _group_ref,
}


def block_from_dict(d: Any) -> B.Block:
    if not isinstance(d, dict):
        raise WorkflowLoadError(f"block must be an object, got {type(d).__name__}")
    timing = {k: d[k] for k in _TIMING_KEYS if k in d}
    type_keys = [k for k in d if k not in _TIMING_KEYS]
    if len(type_keys) != 1:
        raise WorkflowLoadError(f"block must have exactly one type key, got {type_keys}")
    key = type_keys[0]
    builder = _BUILDERS.get(key)
    if builder is None:
        raise WorkflowLoadError(f"unknown block type {key!r}")
    return builder(d[key], timing)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_experiment_serialize.py -v && python -m mypy && python -m ruff check .`
Expected: PASS; mypy and ruff clean.

- [ ] **Step 5: Commit**

```bash
git add src/lab_devices/experiment/serialize.py tests/test_experiment_serialize.py
git commit -m "feat(experiment): block deserialization (dict -> AST)"
```

---

### Task 5: Block serialization (AST → dict) + block-level round-trip

**Files:**
- Modify: `src/lab_devices/experiment/serialize.py` (append `block_to_dict` and its helper)
- Modify: `tests/test_experiment_serialize.py` (append round-trip tests)

**Interfaces:**
- Consumes: everything from Task 4.
- Produces: `block_to_dict(b: blocks.Block) -> dict[str, Any]` such that `block_from_dict(block_to_dict(b)) == b` for every block type, and timing keys serialize as siblings of the type key.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_experiment_serialize.py  (append)
from lab_devices.experiment.serialize import block_to_dict


@pytest.mark.parametrize("payload", [
    {"command": {"device": "pump_1", "verb": "dispense", "params": {"volume_ml": 10}},
     "gap_after": "30s"},
    {"measure": {"device": "densitometer_1", "verb": "measure", "into": "OD"}},
    {"operator_input": {"name": "target", "type": "float", "prompt": "OD?", "min": 0.0, "max": 2.0}},
    {"wait": {"duration": "5s"}},
    {"parallel": {"children": [
        {"command": {"device": "pump_1", "verb": "rotate",
                     "params": {"direction": "forward", "speed_ml_min": 2.0}},
         "start_offset": "1s"},
        {"measure": {"device": "densitometer_1", "verb": "measure", "into": "OD"}}]}},
    {"loop": {"until": "last(OD) >= 1.0", "check": "before",
              "body": [{"command": {"device": "pump_1", "verb": "stop"}}]}},
    {"loop": {"count": 3, "pace": "60s",
              "body": [{"measure": {"device": "densitometer_1", "verb": "measure", "into": "OD"}}]}},
    {"branch": {"if": "last(OD) > 1.0",
                "then": [{"command": {"device": "pump_2", "verb": "stop"}}],
                "else": [{"command": {"device": "pump_1", "verb": "stop"}}]}},
    {"group_ref": {"name": "prime_line"}, "label": "prime"},
])
def test_block_round_trip(payload):
    ast = block_from_dict(payload)
    assert block_to_dict(ast) == payload
    assert block_from_dict(block_to_dict(ast)) == ast
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_experiment_serialize.py -k round_trip -v`
Expected: FAIL with `ImportError: cannot import name 'block_to_dict'`

- [ ] **Step 3: Write minimal implementation**

Append to `src/lab_devices/experiment/serialize.py`:

```python
def _dump_body(b: B.Block) -> tuple[str, dict[str, Any]]:
    if isinstance(b, B.Command):
        body: dict[str, Any] = {"device": b.device, "verb": b.verb}
        if b.params:
            body["params"] = dict(b.params)
        return "command", body
    if isinstance(b, B.Measure):
        body = {"device": b.device, "verb": b.verb, "into": b.into}
        if b.params:
            body["params"] = dict(b.params)
        return "measure", body
    if isinstance(b, B.OperatorInput):
        body = {"name": b.name, "type": b.type}
        for key in ("prompt", "min", "max", "choices"):
            value = getattr(b, key)
            if value is not None:
                body[key] = value
        return "operator_input", body
    if isinstance(b, B.Wait):
        return "wait", {"duration": b.duration}
    if isinstance(b, B.Serial):
        return "serial", {"children": [block_to_dict(c) for c in b.children]}
    if isinstance(b, B.Parallel):
        return "parallel", {"children": [block_to_dict(c) for c in b.children]}
    if isinstance(b, B.Loop):
        body = {"body": [block_to_dict(c) for c in b.body]}
        if b.count is not None:
            body["count"] = b.count
        if b.pace is not None:
            body["pace"] = b.pace
        if b.until is not None:
            body["until"] = b.until
            body["check"] = b.check
        return "loop", body
    if isinstance(b, B.Branch):
        body = {"if": b.if_, "then": [block_to_dict(c) for c in b.then]}
        if b.else_ is not None:
            body["else"] = [block_to_dict(c) for c in b.else_]
        return "branch", body
    if isinstance(b, B.GroupRef):
        return "group_ref", {"name": b.name}
    raise WorkflowLoadError(f"cannot serialize {type(b).__name__}")


def block_to_dict(b: B.Block) -> dict[str, Any]:
    key, body = _dump_body(b)
    out: dict[str, Any] = {key: body}
    if b.label is not None:
        out["label"] = b.label
    if b.gap_after is not None:
        out["gap_after"] = b.gap_after
    if b.start_offset is not None:
        out["start_offset"] = b.start_offset
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_experiment_serialize.py -v && python -m mypy && python -m ruff check .`
Expected: PASS (all round-trip params); mypy and ruff clean.

- [ ] **Step 5: Commit**

```bash
git add src/lab_devices/experiment/serialize.py tests/test_experiment_serialize.py
git commit -m "feat(experiment): block serialization + block-level round-trip"
```

---

### Task 6: Workflow document + file load/save + full-example round-trip

**Files:**
- Create: `src/lab_devices/experiment/workflow.py`
- Modify: `src/lab_devices/experiment/serialize.py` (append workflow-level (de)serialize + file I/O)
- Modify: `src/lab_devices/experiment/__init__.py` (public exports)
- Test: `tests/test_experiment_workflow.py`

**Interfaces:**
- Consumes: everything above.
- Produces:
  - `workflow.py`: `Metadata`, `Persistence`, `StreamDecl`, `Group`, `Workflow` dataclasses (see code).
  - `serialize.py`: `workflow_from_dict(d) -> Workflow`, `workflow_to_dict(w) -> dict`, `load_workflow(path) -> Workflow`, `save_workflow(w, path) -> None`.
  - `__init__.py` re-exports the public surface.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_experiment_workflow.py
import json

import pytest

from lab_devices.experiment import Workflow, load_workflow, save_workflow
from lab_devices.experiment.errors import WorkflowLoadError

EXAMPLE = {
    "schema_version": 1,
    "metadata": {"name": "od-feedback-feed", "author": "khamitov",
                 "description": "Feed pump_1 by live OD until target, stirring throughout."},
    "persistence": {"default": "disk", "format": "jsonl"},
    "streams": {"OD": {"units": "AU"}, "temp": {"units": "C", "persistence": "in_memory"}},
    "groups": {"prime_line": {"body": [
        {"command": {"device": "pump_1", "verb": "dispense",
                     "params": {"volume_ml": 1.0, "speed_ml_min": 5.0}}}]}},
    "blocks": [{"serial": {"children": [
        {"operator_input": {"name": "target_OD", "type": "float",
                            "prompt": "Enter target OD", "min": 0.0, "max": 2.0}},
        {"group_ref": {"name": "prime_line"}},
        {"command": {"device": "pump_2", "verb": "rotate",
                     "params": {"direction": "forward", "speed_ml_min": 2.0}}},
        {"loop": {"check": "after", "until": "mean(OD, last=5min) >= target_OD", "body": [
            {"measure": {"device": "densitometer_1", "verb": "measure", "into": "OD"}},
            {"command": {"device": "pump_1", "verb": "dispense",
                         "params": {"volume_ml": "2.0 * (target_OD - mean(OD, last=100))",
                                    "speed_ml_min": 3.0}}, "gap_after": "30s"}]}},
        {"command": {"device": "pump_2", "verb": "stop"}},
        {"branch": {"if": "last(OD) > target_OD",
                    "then": [{"command": {"device": "densitometer_1", "verb": "set_led",
                                          "params": {"level": 0}}}]}}]}}],
}


def test_full_example_round_trips_through_file(tmp_path):
    path = tmp_path / "wf.json"
    path.write_text(json.dumps(EXAMPLE))
    wf = load_workflow(path)
    assert isinstance(wf, Workflow)
    assert wf.metadata.name == "od-feedback-feed"
    assert wf.persistence.default == "disk"
    assert wf.streams["temp"].persistence == "in_memory"
    assert "prime_line" in wf.groups

    out = tmp_path / "out.json"
    save_workflow(wf, out)
    assert json.loads(out.read_text()) == EXAMPLE


def test_bad_schema_version_rejected(tmp_path):
    path = tmp_path / "wf.json"
    path.write_text(json.dumps({"schema_version": 99, "blocks": []}))
    with pytest.raises(WorkflowLoadError):
        load_workflow(path)


def test_invalid_json_rejected(tmp_path):
    path = tmp_path / "wf.json"
    path.write_text("{not json")
    with pytest.raises(WorkflowLoadError):
        load_workflow(path)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_experiment_workflow.py -v`
Expected: FAIL with `ImportError: cannot import name 'Workflow' from 'lab_devices.experiment'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/lab_devices/experiment/workflow.py
"""Top-level workflow document. See design §15."""

from __future__ import annotations

from dataclasses import dataclass, field

from lab_devices.experiment.blocks import Block


@dataclass
class Metadata:
    name: str | None = None
    author: str | None = None
    description: str | None = None


@dataclass
class Persistence:
    default: str = "in_memory"  # "in_memory" | "disk"
    format: str = "jsonl"  # "jsonl" | "csv"


@dataclass
class StreamDecl:
    units: str | None = None
    persistence: str | None = None  # per-stream override


@dataclass
class Group:
    name: str
    body: list[Block] = field(default_factory=list)


@dataclass
class Workflow:
    schema_version: int
    blocks: list[Block] = field(default_factory=list)
    metadata: Metadata = field(default_factory=Metadata)
    persistence: Persistence = field(default_factory=Persistence)
    streams: dict[str, StreamDecl] = field(default_factory=dict)
    groups: dict[str, Group] = field(default_factory=dict)
```

Append to `src/lab_devices/experiment/serialize.py` (add `import json` and `from pathlib import Path` to the top imports, and `from lab_devices.experiment.workflow import ...`):

```python
def workflow_from_dict(d: Any) -> Workflow:
    if not isinstance(d, dict):
        raise WorkflowLoadError("workflow must be an object")
    version = d.get("schema_version")
    if version != SCHEMA_VERSION:
        raise WorkflowLoadError(
            f"unsupported schema_version {version!r}; expected {SCHEMA_VERSION}"
        )
    md = d.get("metadata", {})
    metadata = Metadata(name=md.get("name"), author=md.get("author"),
                        description=md.get("description"))
    pd = d.get("persistence", {})
    persistence = Persistence(default=pd.get("default", "in_memory"),
                              format=pd.get("format", "jsonl"))
    streams = {
        name: StreamDecl(units=s.get("units"), persistence=s.get("persistence"))
        for name, s in d.get("streams", {}).items()
    }
    groups = {
        name: Group(name=name, body=_children(g.get("body", []), f"groups.{name}.body"))
        for name, g in d.get("groups", {}).items()
    }
    return Workflow(
        schema_version=version,
        blocks=_children(d.get("blocks", []), "blocks"),
        metadata=metadata, persistence=persistence, streams=streams, groups=groups,
    )


def workflow_to_dict(w: Workflow) -> dict[str, Any]:
    out: dict[str, Any] = {"schema_version": w.schema_version}
    md = {
        k: v for k, v in (("name", w.metadata.name), ("author", w.metadata.author),
                          ("description", w.metadata.description)) if v is not None
    }
    if md:
        out["metadata"] = md
    out["persistence"] = {"default": w.persistence.default, "format": w.persistence.format}
    if w.streams:
        out["streams"] = {
            name: {k: v for k, v in (("units", s.units), ("persistence", s.persistence))
                   if v is not None}
            for name, s in w.streams.items()
        }
    if w.groups:
        out["groups"] = {
            name: {"body": [block_to_dict(c) for c in g.body]} for name, g in w.groups.items()
        }
    out["blocks"] = [block_to_dict(c) for c in w.blocks]
    return out


def load_workflow(path: str | Path) -> Workflow:
    try:
        data = json.loads(Path(path).read_text())
    except json.JSONDecodeError as exc:
        raise WorkflowLoadError(f"invalid JSON: {exc}") from exc
    return workflow_from_dict(data)


def save_workflow(w: Workflow, path: str | Path) -> None:
    Path(path).write_text(json.dumps(workflow_to_dict(w), indent=2) + "\n")
```

```python
# src/lab_devices/experiment/__init__.py  (replace body)
"""Declarative experiment-orchestration layer on top of lab_devices. See design §1."""

from __future__ import annotations

from lab_devices.experiment.blocks import (
    Block,
    Branch,
    Command,
    GroupRef,
    Loop,
    Measure,
    OperatorInput,
    Parallel,
    Serial,
    Wait,
)
from lab_devices.experiment.errors import (
    ExperimentError,
    UnknownVerbError,
    WorkflowLoadError,
)
from lab_devices.experiment.serialize import (
    block_from_dict,
    block_to_dict,
    load_workflow,
    save_workflow,
    workflow_from_dict,
    workflow_to_dict,
)
from lab_devices.experiment.workflow import (
    Group,
    Metadata,
    Persistence,
    StreamDecl,
    Workflow,
)

__all__ = [
    "Block", "Branch", "Command", "GroupRef", "Loop", "Measure", "OperatorInput",
    "Parallel", "Serial", "Wait",
    "ExperimentError", "UnknownVerbError", "WorkflowLoadError",
    "block_from_dict", "block_to_dict", "load_workflow", "save_workflow",
    "workflow_from_dict", "workflow_to_dict",
    "Group", "Metadata", "Persistence", "StreamDecl", "Workflow",
]
```

Note: the `# noqa: F401` re-export style already used by the parent package's `__init__.py` (a plain sorted `__all__` literal) satisfies ruff; mirror it if ruff flags unused imports.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_experiment_workflow.py -v && python -m pytest && python -m mypy && python -m ruff check .`
Expected: PASS (new tests + whole suite still green); mypy and ruff clean.

- [ ] **Step 5: Commit**

```bash
git add src/lab_devices/experiment/workflow.py src/lab_devices/experiment/serialize.py src/lab_devices/experiment/__init__.py tests/test_experiment_workflow.py
git commit -m "feat(experiment): workflow document + file load/save round-trip"
```

---

## Self-Review

**1. Spec coverage (Increment 1 scope only):**
- Design §5 block taxonomy → Task 3 (all nine block types). ✓
- Design §4 command traits + registry → Task 2 (registry with completion/state_effect/teardown). ✓
- Design §3 narrow subset → Task 2 (`_REGISTRY` encodes exactly the §3.1 block-plane verbs; excluded verbs absent → `UnknownVerbError`). ✓
- Design §15 pure-JSON serialization, schema-versioned, infix-string expressions → Tasks 4–6 (expressions carried verbatim as strings; `schema_version` enforced). ✓
- Design §15.1 persistence config (workflow default + per-stream override) → Task 6 (`Persistence`, `StreamDecl.persistence`). ✓
- Design §16 package = `lab_devices.experiment` submodule → all tasks. ✓
- Deferred to later increments (correctly NOT in this plan): expression parsing/evaluation (§6, Increment 2), static validation (§12, Increment 3), execution/scheduler/finalizer (§11–14, Increment 4), control plane & disk sinks (§14–15.1, Increment 5). Verb-existence is the only validation done here, as a natural load-time byproduct of the registry.

**2. Placeholder scan:** No TBD/TODO; every code step shows complete code; no "similar to Task N" references. ✓

**3. Type consistency:** `block_from_dict`/`block_to_dict` names consistent across Tasks 4–6; `Block` union defined in Task 3 used everywhere; `Trait`/`Teardown`/`lookup` names consistent between Tasks 2 and 4; `Workflow` field names match between `workflow.py` and `workflow_to_dict`/`workflow_from_dict`. The `if_`/`else_` (Python) ↔ `if`/`else` (JSON) mapping is handled in both directions (Task 4 `_branch`, Task 5 `_dump_body`). ✓

## Roadmap (subsequent increments — separate plans)

- **Increment 2 — Data plane:** expression tokenizer/parser for the infix sublanguage (§6 grammar), evaluator over a runtime state (`streams` + `bindings`), fail-safe missing-data semantics (§6). Replaces the "expressions as opaque strings" with parsed, evaluable expressions.
- **Increment 3 — Validator:** the static checks of §12 (registry already covered; add device-affinity non-overlap, mode-lifetime balance over the CFG, data-flow write-before-read).
- **Increment 4 — Executor:** async scheduler (structured concurrency, §13.1), live open-mode registry + non-blocking busy-tracker, fixed-order finalizer (§13.2), pause-as-quiesce (§14), run end-to-end against `tests/fakelab.py`.
- **Increment 5 — Control plane + persistence sinks:** run-level controls (§14 three tiers), in-memory and disk (jsonl/csv) stream/log sinks (§15.1).
