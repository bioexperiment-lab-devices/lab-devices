# Experiment Orchestrator — Increment 3: Static Validator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `validate(workflow)` — a pure, synchronous, hardware-free static analysis (design §12) that proves registry/param correctness, `(device, channel)` affinity, may-open mode-interval safety, and all-paths data-flow over the block tree, and rejects violations before any run.

**Architecture:** Two new modules in `lab_devices.experiment`: `analyze.py` (expression-level static API: referenced names + type inference over Increment 2's parsed AST) and `validate.py` (two-phase validation: cheap global checks over every block, then a path-sensitive abstract interpretation with a `_PathState` of definitely-written bindings/streams and a closed→open→maybe-open mode lattice). `errors.py` gains `Diagnostic` + `ValidationError`; `registry.py` gains `channels`, `measurement`, per-verb `ParamSpec`s, and the `mode_action()` open/close classifier.

**Tech Stack:** Python 3.11, standard library only (`re`, `dataclasses`), pytest. No async, no hardware, no new dependencies.

## Global Constraints

- Interpreter: run ALL tooling as `.venv/bin/python -m <tool>` — bare `python`/`python3` lacks the deps.
- Gate after every task (all must be clean before commit):
  - `.venv/bin/python -m pytest` (whole suite, not just the new file; 233 passing at branch base)
  - `.venv/bin/python -m mypy` (strict; config checks `src/lab_devices` only — tests are not type-checked)
  - `.venv/bin/python -m ruff check .`
  - `awk 'length > 100 {print FILENAME ":" FNR ": " length}' src/lab_devices/experiment/*.py tests/test_experiment_*.py` — must print nothing (ruff's default select does not include E501).
- Source modules start with `from __future__ import annotations` and a one-line docstring citing the design section. Dataclasses throughout. Python ≥3.11.
- Tests live flat in `tests/` as `test_experiment_*.py` and do NOT use the future-import (repo convention).
- Branch: `feat/experiment-orchestrator-3-validator` off `main` (Increments 1 and 2 are merged; the branch already exists and carries the spec-amendment commit). Never commit to `main`.
- The loader (`serialize.py`) is NOT modified in this increment. Validation is a distinct phase after load (design §11); everything the loader already accepts must keep loading.
- The design spec was amended for this increment (commit on this branch): §4 registry channels/params/measurement, §12 rules rewrite, §13.1 channel affinity, §6 count exception. Read the amended spec, not memory of the old one.

## Settled design sub-decisions (user-approved in brainstorm; do not re-litigate in-task)

1. **Affinity is per `(device, channel)`** (spec amendment, user decision). Registry channels: every pump and valve verb → `motor`; densitometer `measure`/`measure_blank`/`set_led`/`set_tube_correction`/`calibrate_tube` → `optics`, `set_thermostat` → `thermal`, `stop` → `{optics, thermal}` (the blunt safe-state primitive conflicts with everything on its device). Two commands conflict only when device AND channel-sets intersect. Thermostat-while-measuring is valid; parallel branches may share a device on disjoint channels.
2. **Mode lifetimes are least-strict** (user decision: "no restrictions; every opened state will be closed at the end anyway"). Closes are OPTIONAL everywhere — end of workflow, branch arms, loop exits. The finalizer (§13.2) is the universal close. The ONE hard rule (required for the lock-free runtime): no same-`(device, channel)` command while a mode is possibly open on any path to it — except that mode's matching close, which is always legal (closes if open, no-ops if not).
3. **Open/close classification by teardown comparison.** A `state_effect="mode"` command closes iff its verb equals its teardown verb and its params literally equal the teardown params (same keys, equal values, bool never matching int — `False != 0`); anything else — including ANY expression-valued param, conservatively — opens. A `state_effect="none"` command whose verb+params match some mode's teardown (pump `stop` → `rotate`) closes that mode. Conservative-open is sound: worst case it demands a redundant idempotent close.
4. **May-open tracking at merges.** Branch join: open∧open → open; open/maybe on one side only → maybe. A maybe-open mode admits only its matching close; any other same-channel command errors ("possibly open"). Loop back-edges: re-analyze the body from the first pass's exit state to a fixpoint (state space is tiny; dedup makes re-emission harmless) — a body that opens without closing errors on its second pass because the open re-executes inside the still-open interval. A `count: 1` loop has no back-edge.
5. **`count()` is exempt from the prior-writer rule** (user decision). Every other stat (`last/mean/min/max`) needs a definite prior `Measure` into that stream on EVERY path to it. Both `count` and windowed stats require the stream to be **declared** in `workflow.streams` — and `Measure.into` must be declared too. Corollary (hard carry-forward to Increment 4): the executor MUST pre-create every declared stream at run start, else `count` on a never-written stream raises unknown-stream at runtime.
6. **Definitely-written joins:** branch = intersection of arms (missing `else` = empty arm); post-test and count≥1 loops guarantee one body execution (their writes survive the loop; a post-test `until` sees body writes; a pre-test `until` sees loop entry only); pre-test bodies contribute nothing after the loop. Parallel lanes see entry state + own writes only (sibling writes are unordered); after the join, the union (all lanes completed).
7. **Diagnostics: collect-all, one exception** (user decision). `validate()` walks everything, collects every violation as `Diagnostic(category, path, message)`, raises a single `ValidationError(ExperimentError)` carrying the tuple. Categories: `group`, `registry`, `params`, `type`, `block`, `declaration`, `data-flow`, `mode`, `affinity`. `ValidationError` is NOT a `WorkflowLoadError` — validation is a distinct phase (§11).
8. **Diagnostic paths are structural index strings:** `blocks[0].children[2].body[1]`; branch arms `.then[i]`/`.else[i]`; group bodies in the global phase `groups['name'].body[i]`; group expansion in the path phase appends `->name.body[i]`. Expression-slot contexts append ` param 'x'`, ` branch if`, ` loop until`.
9. **Param kinds** `number | int | bool | string` from the real driver signatures. Numeric/int/bool params accept literals of the right shape or expressions of the right inferred type; `int` accepts numeric expressions (static analysis cannot prove integerness — runtime coercion is Increment 4's). **String-kind params are opaque literals, never expressions** (closes Increment 2's deferred enum-vs-expression ticket: `direction: "forward"` produces no binding/type/data-flow diagnostics). Dict-valued driver params (`speed_profile`, `job_id`) are omitted from the specs, so they surface as unknown-param errors.
10. **Expression typing is lenient on unknowns.** `infer_type` returns `number`/`boolean`/`unknown`; `unknown` (undeclared binding, conflicting redeclarations) never errors — the runtime evaluator is the backstop. String-typed (enum) bindings referenced in any expression ARE static errors (the evaluator always rejects them). Conditions (`branch if`, `loop until`) must infer `boolean`-or-`unknown`; numeric slots `number`-or-`unknown`.
11. **`Measure` needs a measurement verb** (new registry flag on `measure`/`measure_blank`): a `Measure` block with any other verb is a `block` error. A `Command` with a measurement verb (result discarded) is legal.
12. **Loop fields:** exactly one of `count`/`until`; `count` must be an `int` (not `bool`) ≥ 1 (closes Increment 2's count-typing ticket); `pace` only with `count`; `check` ∈ {`before`, `after`}. A count-loop's stored `check` value is ignored (meaningless without `until`).
13. **OperatorInput:** `type` ∈ {`float`, `int`, `enum`, `bool`}; `enum` requires non-empty string `choices` (and no `min`/`max`); `choices` only for `enum`; `min`/`max` only for `float`/`int`, must be numbers, `min <= max`; `name` must be a non-reserved identifier (`and or not true false` are unusable as binding refs). Duplicate `OperatorInput` names are legal (rebinding); conflicting declared types degrade that binding's type to `unknown`.
14. **Group expansion** inlines bodies for the path phase; unknown `GroupRef` names and self/mutual recursion are `group` errors, and the path phase is skipped entirely when any group diagnostic exists (the tree cannot be soundly expanded) — global diagnostics are still all reported.
15. **The validator never crashes on programmatically-built garbage** the loader would have rejected (unknown verbs, non-string conditions, unparseable expression strings, non-`ValueExpr` params): each such case degrades to a diagnostic, and the analysis skips what it cannot interpret (it is already reported).
16. **§15.2's flagship example must validate cleanly end-to-end** — it exercises free start/stop, close-with-no-open, post-test feedback, groups, and bindings. It is the canonical positive fixture (Task 9).

## Carry-forward requirements for Increment 4 (record in ledger at final review)

- Executor pre-creates every declared stream at run start (decision 5 depends on it).
- Scheduler/busy-tracker keyed by `(device, channel)`; decide transport tolerance vs transparent serialization of same-device dispatches on distinct channels (amended §13.1).
- `resolve()` runs only on registry non-string-kind param slots; string-kind params are opaque literals (refines Increment 2's deferred note).
- Block `id`: engine-assigned at load (existing carry from Increment 1).

## Setup (before Task 1)

The branch already exists with the spec-amendment commit. Commit the plan:

```bash
cd /Users/khamit/lab-devices
git checkout feat/experiment-orchestrator-3-validator
git add docs/superpowers/plans/2026-07-07-experiment-orchestrator-3-validator.md
git commit -m "docs: increment 3 (static validator) implementation plan"
```

---

### Task 1: Diagnostics + ValidationError

**Files:**
- Modify: `src/lab_devices/experiment/errors.py`
- Test: `tests/test_experiment_diagnostics.py` (create)

**Interfaces:**
- Consumes: `ExperimentError` (Increment 1).
- Produces (later tasks and the public API rely on these exact names):
  - `Diagnostic` — frozen dataclass, fields `category: str`, `path: str`, `message: str`; `str(d)` == `"[{category}] {path}: {message}"`.
  - `ValidationError(ExperimentError)` — `__init__(self, diagnostics: Sequence[Diagnostic])`; attribute `diagnostics: tuple[Diagnostic, ...]`; `str(err)` starts with `"{n} validation error(s):"` followed by one `"  - {diagnostic}"` line each.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_experiment_diagnostics.py
import pytest

from lab_devices.experiment.errors import Diagnostic, ExperimentError, ValidationError


def test_validation_error_taxonomy():
    assert issubclass(ValidationError, ExperimentError)


def test_diagnostic_str():
    d = Diagnostic("mode", "blocks[0].children[2]", "command inside open interval")
    assert str(d) == "[mode] blocks[0].children[2]: command inside open interval"


def test_diagnostic_is_frozen():
    d = Diagnostic("block", "blocks[0]", "msg")
    with pytest.raises(Exception):
        d.category = "other"


def test_validation_error_carries_diagnostics():
    d1 = Diagnostic("group", "blocks[0]", "unknown group 'x'")
    d2 = Diagnostic("data-flow", "blocks[1]", "binding 'y' may be read before it is written")
    err = ValidationError([d1, d2])
    assert err.diagnostics == (d1, d2)
    text = str(err)
    assert text.startswith("2 validation error(s):")
    assert "  - [group] blocks[0]: unknown group 'x'" in text
    assert "  - [data-flow] blocks[1]:" in text


def test_validation_error_single():
    err = ValidationError([Diagnostic("affinity", "blocks[3]", "overlap")])
    assert "1 validation error(s):" in str(err)
    assert len(err.diagnostics) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_experiment_diagnostics.py -v`
Expected: FAIL — `ImportError: cannot import name 'Diagnostic'`

- [ ] **Step 3: Implement**

Append to `src/lab_devices/experiment/errors.py` (add the imports at the top, below the future-import; keep the existing classes untouched):

```python
from collections.abc import Sequence
from dataclasses import dataclass
```

```python
@dataclass(frozen=True)
class Diagnostic:
    """One static-validation violation (design §12)."""

    category: str  # group|registry|params|type|block|declaration|data-flow|mode|affinity
    path: str  # structural block path, e.g. "blocks[0].children[2].body[1]"
    message: str

    def __str__(self) -> str:
        return f"[{self.category}] {self.path}: {self.message}"


class ValidationError(ExperimentError):
    """A workflow failed static validation (design §11-12); carries every violation found."""

    def __init__(self, diagnostics: Sequence[Diagnostic]) -> None:
        self.diagnostics = tuple(diagnostics)
        lines = "\n".join(f"  - {d}" for d in self.diagnostics)
        super().__init__(f"{len(self.diagnostics)} validation error(s):\n{lines}")
```

- [ ] **Step 4: Run test + full gate**

Run: `.venv/bin/python -m pytest tests/test_experiment_diagnostics.py -v` → all PASS.
Then the full gate (see Global Constraints): whole suite, mypy, ruff, awk — all clean.

- [ ] **Step 5: Commit**

```bash
git add src/lab_devices/experiment/errors.py tests/test_experiment_diagnostics.py
git commit -m "feat(experiment): validation diagnostics + ValidationError"
```

---

### Task 2: Registry channels, param specs, measurement flag, mode classification

**Files:**
- Modify: `src/lab_devices/experiment/registry.py` (full rewrite of the table; `Teardown`, `device_type`, `lookup` keep their exact existing signatures/behavior)
- Test: `tests/test_experiment_registry.py` (append; existing tests must stay green unchanged)

**Interfaces:**
- Consumes: `UnknownVerbError` (Increment 1).
- Produces (Tasks 5, 7, 8 rely on these exact names):
  - `Kind = Literal["number", "int", "bool", "string"]`
  - `ParamSpec` — frozen dataclass `(name: str, kind: Kind, required: bool = False)`.
  - `Trait` gains kw-only fields: `channels: frozenset[str]` (required, no default), `measurement: bool = False`, `params: tuple[ParamSpec, ...] = ()`.
  - `ModeAction` — frozen dataclass `(kind: Literal["open", "close"], mode_verb: str)`.
  - `mode_action(device_id: str, verb: str, params: Mapping[str, object]) -> ModeAction | None` — classifies a command instance per settled decision 3; raises `UnknownVerbError` for unknown verbs (callers guard).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_experiment_registry.py` (keep existing imports and tests; extend the import line):

First REPLACE the file's existing `from lab_devices.experiment.registry import ...` line with
this single import (ruff F811 forbids two import lines for the same module):

```python
from lab_devices.experiment.registry import (
    _REGISTRY,
    ModeAction,
    ParamSpec,
    Teardown,
    device_type,
    lookup,
    mode_action,
)
```

Then append the new tests:

```python


def test_every_entry_declares_channels():
    for key, trait in _REGISTRY.items():
        assert trait.channels, f"{key} has no channels"


def test_channel_table():
    assert lookup("pump_1", "dispense").channels == frozenset({"motor"})
    assert lookup("pump_1", "rotate").channels == frozenset({"motor"})
    assert lookup("pump_1", "stop").channels == frozenset({"motor"})
    assert lookup("valve_1", "set_position").channels == frozenset({"motor"})
    assert lookup("valve_1", "configure").channels == frozenset({"motor"})
    assert lookup("densitometer_1", "measure").channels == frozenset({"optics"})
    assert lookup("densitometer_1", "set_led").channels == frozenset({"optics"})
    assert lookup("densitometer_1", "set_tube_correction").channels == frozenset({"optics"})
    assert lookup("densitometer_1", "set_thermostat").channels == frozenset({"thermal"})
    assert lookup("densitometer_1", "stop").channels == frozenset({"optics", "thermal"})
    assert lookup("densitometer_1", "stop_monitoring").channels == frozenset({"optics"})


def test_measurement_flags():
    measuring = {key for key, t in _REGISTRY.items() if t.measurement}
    assert measuring == {("densitometer", "measure"), ("densitometer", "measure_blank")}
    for key in measuring:
        assert _REGISTRY[key].completion == "job"


def test_param_specs_dispense():
    specs = {s.name: s for s in lookup("pump_1", "dispense").params}
    assert specs["volume_ml"] == ParamSpec("volume_ml", "number", required=True)
    assert specs["speed_ml_min"] == ParamSpec("speed_ml_min", "number")
    assert specs["direction"].kind == "string" and not specs["direction"].required
    assert set(specs) == {"volume_ml", "speed_ml_min", "direction", "drop_suckback_ml"}


def test_param_specs_spot_checks():
    rotate = {s.name: s for s in lookup("pump_1", "rotate").params}
    assert rotate["direction"] == ParamSpec("direction", "string", required=True)
    assert rotate["speed_ml_min"] == ParamSpec("speed_ml_min", "number", required=True)
    setpos = {s.name: s for s in lookup("valve_1", "set_position").params}
    assert setpos["position"] == ParamSpec("position", "int", required=True)
    assert setpos["rotation"].kind == "string"
    thermo = {s.name: s for s in lookup("densitometer_1", "set_thermostat").params}
    assert thermo["enabled"] == ParamSpec("enabled", "bool", required=True)
    assert thermo["target_c"].kind == "number"
    led = {s.name: s for s in lookup("densitometer_1", "set_led").params}
    assert led["level"] == ParamSpec("level", "int", required=True)
    assert lookup("pump_1", "stop").params == ()
    assert lookup("valve_1", "home").params == (ParamSpec("position", "int", required=True),)
    conf = {s.name: s for s in lookup("valve_1", "configure").params}
    assert conf["hold_torque"].kind == "bool"


def test_teardown_verbs_are_registered():
    for (dtype, _), trait in _REGISTRY.items():
        if trait.teardown is not None:
            assert (dtype, trait.teardown.verb) in _REGISTRY


def test_mode_action_open_close_by_teardown_comparison():
    assert mode_action(
        "pump_1", "rotate", {"direction": "forward", "speed_ml_min": 2.0}
    ) == ModeAction("open", "rotate")
    assert mode_action("pump_1", "stop", {}) == ModeAction("close", "rotate")
    assert mode_action("valve_1", "stop", {}) is None
    assert mode_action("densitometer_1", "set_led", {"level": 5}) == ModeAction("open", "set_led")
    assert mode_action("densitometer_1", "set_led", {"level": 0}) == ModeAction("close", "set_led")
    assert mode_action(
        "densitometer_1", "set_thermostat", {"enabled": False}
    ) == ModeAction("close", "set_thermostat")
    assert mode_action(
        "densitometer_1", "set_thermostat", {"enabled": True, "target_c": 37.0}
    ) == ModeAction("open", "set_thermostat")
    assert mode_action("pump_1", "dispense", {"volume_ml": 1.0}) is None
    assert mode_action("densitometer_1", "measure", {}) is None
    assert mode_action("densitometer_1", "stop", {}) is None


def test_mode_action_conservative_cases():
    # An expression-valued level can be 0 at runtime, but statically it is an open.
    assert mode_action(
        "densitometer_1", "set_led", {"level": "x - x"}
    ) == ModeAction("open", "set_led")
    # bool is not int: set_led(level=False) does not match teardown level=0.
    assert mode_action(
        "densitometer_1", "set_led", {"level": False}
    ) == ModeAction("open", "set_led")
    # Extra params beyond the teardown's do not match: still an open.
    assert mode_action(
        "densitometer_1", "set_thermostat", {"enabled": False, "target_c": 20.0}
    ) == ModeAction("open", "set_thermostat")
    # A stop with unexpected params does not match the bare teardown: not a close.
    assert mode_action("pump_1", "stop", {"force": True}) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_experiment_registry.py -v`
Expected: FAIL — `ImportError: cannot import name 'ModeAction'`

- [ ] **Step 3: Implement**

Rewrite `src/lab_devices/experiment/registry.py` as:

```python
"""Command-trait registry: the single source of truth for the narrow subset. See design §3-4."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

from lab_devices.experiment.errors import UnknownVerbError

Completion = Literal["job", "immediate"]
StateEffect = Literal["none", "mode"]
Kind = Literal["number", "int", "bool", "string"]


@dataclass(frozen=True)
class ParamSpec:
    """One verb parameter: its scalar kind and whether the verb requires it (design §4)."""

    name: str
    kind: Kind
    required: bool = False


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
    channels: frozenset[str] = field(kw_only=True)
    measurement: bool = field(default=False, kw_only=True)
    params: tuple[ParamSpec, ...] = field(default=(), kw_only=True)


_MOTOR = frozenset({"motor"})
_OPTICS = frozenset({"optics"})
_THERMAL = frozenset({"thermal"})

_REGISTRY: dict[tuple[str, str], Trait] = {
    # pump — one actuator: every verb occupies the motor channel
    ("pump", "dispense"): Trait(
        "job",
        "none",
        channels=_MOTOR,
        params=(
            ParamSpec("volume_ml", "number", required=True),
            ParamSpec("speed_ml_min", "number"),
            ParamSpec("direction", "string"),
            ParamSpec("drop_suckback_ml", "number"),
        ),
    ),
    ("pump", "rotate"): Trait(
        "immediate",
        "mode",
        Teardown("stop"),
        channels=_MOTOR,
        params=(
            ParamSpec("direction", "string", required=True),
            ParamSpec("speed_ml_min", "number", required=True),
        ),
    ),
    ("pump", "stop"): Trait("immediate", "none", channels=_MOTOR),
    ("pump", "set_calibration"): Trait(
        "immediate",
        "none",
        channels=_MOTOR,
        params=(
            ParamSpec("measured_volume_ml", "number"),
            ParamSpec("ml_per_step", "number"),
        ),
    ),
    # valve — one actuator: motor channel
    ("valve", "set_position"): Trait(
        "job",
        "none",
        channels=_MOTOR,
        params=(
            ParamSpec("position", "int", required=True),
            ParamSpec("rotation", "string"),
        ),
    ),
    ("valve", "home"): Trait(
        "immediate",
        "none",
        channels=_MOTOR,
        params=(ParamSpec("position", "int", required=True),),
    ),
    ("valve", "configure"): Trait(
        "immediate",
        "none",
        channels=_MOTOR,
        params=(
            ParamSpec("default_rotation", "string"),
            ParamSpec("hold_torque", "bool"),
        ),
    ),
    ("valve", "stop"): Trait("immediate", "none", channels=_MOTOR),
    # densitometer — optics (LED/measure path) and thermal are independent subsystems
    ("densitometer", "measure"): Trait(
        "job",
        "none",
        channels=_OPTICS,
        measurement=True,
        params=(ParamSpec("include_raw", "bool"),),
    ),
    ("densitometer", "measure_blank"): Trait(
        "job", "none", channels=_OPTICS, measurement=True
    ),
    ("densitometer", "set_led"): Trait(
        "immediate",
        "mode",
        Teardown("set_led", {"level": 0}),
        channels=_OPTICS,
        params=(ParamSpec("level", "int", required=True),),
    ),
    ("densitometer", "set_thermostat"): Trait(
        "immediate",
        "mode",
        Teardown("set_thermostat", {"enabled": False}),
        channels=_THERMAL,
        params=(
            ParamSpec("enabled", "bool", required=True),
            ParamSpec("target_c", "number"),
        ),
    ),
    ("densitometer", "set_tube_correction"): Trait(
        "immediate",
        "none",
        channels=_OPTICS,
        params=(ParamSpec("factor", "number", required=True),),
    ),
    ("densitometer", "calibrate_tube"): Trait(
        "immediate",
        "none",
        channels=_OPTICS,
        params=(ParamSpec("reference_absorbance", "number", required=True),),
    ),
    ("densitometer", "stop"): Trait("immediate", "none", channels=_OPTICS | _THERMAL),
    ("densitometer", "stop_monitoring"): Trait("immediate", "none", channels=_OPTICS),
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


@dataclass(frozen=True)
class ModeAction:
    """A command instance's effect on its device's mode state (design §12)."""

    kind: Literal["open", "close"]
    mode_verb: str


def _params_match(teardown: Teardown, params: Mapping[str, object]) -> bool:
    """Literal match: same keys, equal values, bools only matching bools (False != 0)."""
    if set(params) != set(teardown.params):
        return False
    for key, expected in teardown.params.items():
        actual = params[key]
        if isinstance(expected, bool) != isinstance(actual, bool):
            return False
        if actual != expected:
            return False
    return True


def mode_action(device_id: str, verb: str, params: Mapping[str, object]) -> ModeAction | None:
    """Classify a command instance as a mode-open, a mode-close, or neither (design §12).

    Conservative: any params that do not literally equal the teardown's (including
    expression strings) classify a mode verb as an open.
    """
    dtype = device_type(device_id)
    trait = lookup(device_id, verb)
    if trait.state_effect == "mode":
        assert trait.teardown is not None  # every mode entry declares its teardown
        if trait.teardown.verb == verb and _params_match(trait.teardown, params):
            return ModeAction("close", verb)
        return ModeAction("open", verb)
    for (entry_type, mode_verb), entry in _REGISTRY.items():
        if entry_type != dtype or entry.state_effect != "mode":
            continue
        assert entry.teardown is not None
        if entry.teardown.verb == verb and _params_match(entry.teardown, params):
            return ModeAction("close", mode_verb)
    return None
```

- [ ] **Step 4: Run test + full gate**

Run: `.venv/bin/python -m pytest tests/test_experiment_registry.py -v` → all PASS (old and new).
Full gate clean.

- [ ] **Step 5: Commit**

```bash
git add src/lab_devices/experiment/registry.py tests/test_experiment_registry.py
git commit -m "feat(experiment): registry channels, param specs, measurement flag, mode classification"
```

---

### Task 3: Expression analysis API (`analyze.py`)

**Files:**
- Create: `src/lab_devices/experiment/analyze.py`
- Test: `tests/test_experiment_analyze.py` (create)

**Interfaces:**
- Consumes: `Expr`, `Const`, `BindingRef`, `StatCall`, `UnaryOp`, `BinaryOp` from `expr.py` (Increment 2).
- Produces (Tasks 5-7 rely on these exact names):
  - `BindingType = Literal["number", "boolean", "string", "unknown"]`
  - `ExprType = Literal["number", "boolean", "unknown"]`
  - `ExprRefs` — frozen dataclass `(bindings: frozenset[str], streams_windowed: frozenset[str], streams_counted: frozenset[str])`.
  - `references(expr: Expr) -> ExprRefs` — every binding name, plus stream names split by how they are consumed (`count` vs windowed stats).
  - `TypeReport` — frozen dataclass `(type: ExprType, problems: tuple[str, ...])`.
  - `infer_type(expr: Expr, binding_types: Mapping[str, BindingType]) -> TypeReport` — lenient bottom-up inference per settled decision 10.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_experiment_analyze.py
from lab_devices.experiment.analyze import ExprRefs, TypeReport, infer_type, references
from lab_devices.experiment.expr import parse_expression


def refs(text):
    return references(parse_expression(text))


def report(text, bindings=None):
    return infer_type(parse_expression(text), bindings or {})


def test_references_bindings_and_streams():
    r = refs("2.0 * (target - mean(OD, last=100)) + last(temp)")
    assert r.bindings == frozenset({"target"})
    assert r.streams_windowed == frozenset({"OD", "temp"})
    assert r.streams_counted == frozenset()


def test_references_count_separated():
    r = refs("count(OD) > 0 and mean(OD) > x or count(pressure) == 0")
    assert r.bindings == frozenset({"x"})
    assert r.streams_windowed == frozenset({"OD"})
    assert r.streams_counted == frozenset({"OD", "pressure"})


def test_references_literals_only():
    assert refs("1 + 2 < 4") == ExprRefs(frozenset(), frozenset(), frozenset())


def test_references_unary_and_nesting():
    r = refs("not (a > -b)")
    assert r.bindings == frozenset({"a", "b"})


def test_infer_const_and_stat_types():
    assert report("1 + 2.5").type == "number"
    assert report("true").type == "boolean"
    assert report("1 < 2").type == "boolean"
    assert report("not (1 < 2)").type == "boolean"
    assert report("-(3 * 2)").type == "number"
    assert report("mean(OD)").type == "number"
    assert report("count(OD) >= 3").type == "boolean"


def test_infer_binding_types():
    assert report("x + 1", {"x": "number"}) == TypeReport("number", ())
    assert report("flag and true", {"flag": "boolean"}) == TypeReport("boolean", ())
    assert report("x", {}).type == "unknown"
    assert report("x + 1").type == "number"  # unknown operand: no false positive


def test_string_binding_is_a_problem():
    rep = report("mode_sel + 1", {"mode_sel": "string"})
    assert any("string" in p for p in rep.problems)


def test_boolean_number_mixes_are_problems():
    assert report("true + 1").problems
    assert report("1 and 2").problems
    assert report("not 3").problems
    assert report("-true").problems
    assert report("true > false").problems
    assert report("(1 < 2) == 3").problems


def test_equality_same_kind_ok():
    assert report("(1 < 2) == (3 < 4)") == TypeReport("boolean", ())
    assert report("1 == 2") == TypeReport("boolean", ())


def test_unknown_propagates_without_problems():
    rep = report("x + 1 > 0 and y", {})
    assert rep.type == "boolean"
    assert rep.problems == ()


def test_multiple_problems_collected():
    rep = report("(true + 1) * (not 2)")
    assert len(rep.problems) >= 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_experiment_analyze.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'lab_devices.experiment.analyze'`

- [ ] **Step 3: Implement**

```python
# src/lab_devices/experiment/analyze.py
"""Expression-level static analysis: referenced names and type inference. See design §12."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from lab_devices.experiment.expr import (
    BinaryOp,
    BindingRef,
    Const,
    Expr,
    StatCall,
    UnaryOp,
)

BindingType = Literal["number", "boolean", "string", "unknown"]
ExprType = Literal["number", "boolean", "unknown"]

_ARITH_OPS = frozenset({"+", "-", "*", "/"})
_ORDER_OPS = frozenset({"<", "<=", ">", ">="})


@dataclass(frozen=True)
class ExprRefs:
    """Names an expression consumes, split by how they are consumed (design §12)."""

    bindings: frozenset[str]
    streams_windowed: frozenset[str]  # via last/mean/min/max: need a definite prior writer
    streams_counted: frozenset[str]  # via count only: need declaration only


def references(expr: Expr) -> ExprRefs:
    """Enumerate every binding and stream an expression references."""
    bindings: set[str] = set()
    windowed: set[str] = set()
    counted: set[str] = set()

    def walk(e: Expr) -> None:
        if isinstance(e, BindingRef):
            bindings.add(e.name)
        elif isinstance(e, StatCall):
            (counted if e.fn == "count" else windowed).add(e.stream)
        elif isinstance(e, UnaryOp):
            walk(e.operand)
        elif isinstance(e, BinaryOp):
            walk(e.left)
            walk(e.right)

    walk(expr)
    return ExprRefs(frozenset(bindings), frozenset(windowed), frozenset(counted))


@dataclass(frozen=True)
class TypeReport:
    """Inferred expression type plus every type problem found (design §12)."""

    type: ExprType
    problems: tuple[str, ...]


def infer_type(expr: Expr, binding_types: Mapping[str, BindingType]) -> TypeReport:
    """Lenient bottom-up type inference; 'unknown' never produces a problem —
    the runtime evaluator (fail-safe rule, design §6) is the backstop."""
    problems: list[str] = []

    def expect(e: Expr, expected: ExprType, ctx: str) -> None:
        got = infer(e)
        if got not in (expected, "unknown"):
            problems.append(f"{ctx} requires a {expected} operand, got {got}")

    def infer(e: Expr) -> ExprType:
        if isinstance(e, Const):
            return "boolean" if isinstance(e.value, bool) else "number"
        if isinstance(e, BindingRef):
            bound = binding_types.get(e.name, "unknown")
            if bound == "string":
                problems.append(
                    f"binding {e.name!r} holds a string (enum operator input); "
                    "expressions evaluate numbers and booleans"
                )
                return "unknown"
            if bound == "number" or bound == "boolean":
                return bound
            return "unknown"
        if isinstance(e, StatCall):
            return "number"
        if isinstance(e, UnaryOp):
            if e.op == "not":
                expect(e.operand, "boolean", "'not'")
                return "boolean"
            expect(e.operand, "number", "unary '-'")
            return "number"
        if e.op in ("and", "or"):
            expect(e.left, "boolean", f"{e.op!r}")
            expect(e.right, "boolean", f"{e.op!r}")
            return "boolean"
        if e.op in _ARITH_OPS:
            expect(e.left, "number", f"operator {e.op!r}")
            expect(e.right, "number", f"operator {e.op!r}")
            return "number"
        if e.op in _ORDER_OPS:
            expect(e.left, "number", f"operator {e.op!r}")
            expect(e.right, "number", f"operator {e.op!r}")
            return "boolean"
        left, right = infer(e.left), infer(e.right)  # == / !=
        if "unknown" not in (left, right) and left != right:
            problems.append(f"operator {e.op!r} cannot compare a boolean with a number")
        return "boolean"

    top = infer(expr)
    return TypeReport(top, tuple(problems))
```

- [ ] **Step 4: Run test + full gate**

Run: `.venv/bin/python -m pytest tests/test_experiment_analyze.py -v` → all PASS. Full gate clean.

- [ ] **Step 5: Commit**

```bash
git add src/lab_devices/experiment/analyze.py tests/test_experiment_analyze.py
git commit -m "feat(experiment): expression reference/type analysis API"
```

---

### Task 4: Validator skeleton — block iteration, paths, group checks

**Files:**
- Create: `src/lab_devices/experiment/validate.py`
- Create: `tests/experiment_validate_helpers.py` (shared test builders; repo precedent for
  non-test helper modules in `tests/`: `fakelab.py`, imported as `from tests.fakelab import ...`)
- Test: `tests/test_experiment_validate_groups.py` (create)

**Interfaces:**
- Consumes: `Diagnostic`, `ValidationError` (Task 1); `blocks` AST, `Workflow` (Increment 1).
- Produces (Tasks 5-9 build inside this module):
  - `validate(workflow: Workflow) -> None` — raises `ValidationError` carrying ALL collected diagnostics; returns `None` when clean.
  - `_iter_blocks(blocks: list[B.Block], prefix: str) -> Iterator[tuple[str, B.Block]]` — depth-first, yields every block with its structural path; does NOT expand group refs.
  - `_iter_all_blocks(w: Workflow) -> Iterator[tuple[str, B.Block]]` — `workflow.blocks` under `blocks[...]` plus each group body under `groups['name'].body[...]`.
  - `_check_groups(w: Workflow, out: list[Diagnostic]) -> bool` — unknown-ref + recursion diagnostics; returns True iff the tree is expandable (used to gate the path phase in Task 7).

- [ ] **Step 1: Write the failing test**

First the shared helper module used by every validator test file (Tasks 4-8; NOT collected
by pytest — the filename does not match `test_*.py`):

```python
# tests/experiment_validate_helpers.py
"""Shared builders for the validator test files."""
import pytest

from lab_devices.experiment.errors import ValidationError
from lab_devices.experiment.serialize import workflow_from_dict
from lab_devices.experiment.validate import validate


def wf(blocks, streams=None, groups=None):
    return workflow_from_dict({
        "schema_version": 1,
        "streams": {name: {} for name in (streams or [])},
        "groups": groups or {},
        "blocks": blocks,
    })


def diags(workflow):
    with pytest.raises(ValidationError) as exc:
        validate(workflow)
    return exc.value.diagnostics


def cmd(device, verb, params=None):
    return {"command": {"device": device, "verb": verb, "params": params or {}}}


MEASURE_OD = {"measure": {"device": "densitometer_1", "verb": "measure", "into": "OD"}}
```

Then the test file:

```python
# tests/test_experiment_validate_groups.py
from lab_devices.experiment.validate import validate
from tests.experiment_validate_helpers import diags, wf

DISPENSE = {"command": {"device": "pump_1", "verb": "dispense", "params": {"volume_ml": 1.0}}}


def test_unknown_group_ref():
    d = diags(wf([{"group_ref": {"name": "nope"}}]))
    assert any(
        x.category == "group" and "unknown group 'nope'" in x.message and x.path == "blocks[0]"
        for x in d
    )


def test_self_recursive_group():
    d = diags(wf(
        [{"group_ref": {"name": "a"}}],
        groups={"a": {"body": [{"group_ref": {"name": "a"}}]}},
    ))
    assert any(x.category == "group" and "recursive" in x.message for x in d)


def test_mutually_recursive_groups():
    groups = {
        "a": {"body": [{"group_ref": {"name": "b"}}]},
        "b": {"body": [{"group_ref": {"name": "a"}}]},
    }
    d = diags(wf([{"group_ref": {"name": "a"}}], groups=groups))
    assert any(x.category == "group" and "recursive" in x.message for x in d)


def test_acyclic_groups_pass():
    groups = {
        "leaf": {"body": [DISPENSE]},
        "mid": {"body": [{"group_ref": {"name": "leaf"}}]},
    }
    w = wf([{"group_ref": {"name": "mid"}}, {"group_ref": {"name": "leaf"}}], groups=groups)
    assert validate(w) is None


def test_diamond_is_not_recursion():
    groups = {
        "shared": {"body": [DISPENSE]},
        "a": {"body": [{"group_ref": {"name": "shared"}}]},
        "b": {"body": [{"group_ref": {"name": "shared"}}]},
    }
    w = wf(
        [{"group_ref": {"name": "a"}}, {"group_ref": {"name": "b"}}],
        groups=groups,
    )
    assert validate(w) is None


def test_group_ref_found_in_nested_containers():
    blocks = [{"serial": {"children": [
        {"parallel": {"children": [
            {"loop": {"count": 2, "body": [{"group_ref": {"name": "ghost"}}]}},
        ]}},
    ]}}]
    d = diags(wf(blocks))
    assert any(x.path == "blocks[0].children[0].children[0].body[0]" for x in d)


def test_unknown_ref_inside_group_body():
    d = diags(wf([], groups={"a": {"body": [{"group_ref": {"name": "ghost"}}]}}))
    assert any(x.path == "groups['a'].body[0]" and x.category == "group" for x in d)


def test_branch_else_paths():
    blocks = [{"branch": {
        "if": "1 < 2",
        "then": [DISPENSE],
        "else": [{"group_ref": {"name": "ghost"}}],
    }}]
    d = diags(wf(blocks))
    assert any(x.path == "blocks[0].else[0]" for x in d)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_experiment_validate_groups.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'lab_devices.experiment.validate'`

- [ ] **Step 3: Implement**

```python
# src/lab_devices/experiment/validate.py
"""Static workflow validator: registry, affinity, mode lifetimes, data-flow. See design §12."""

from __future__ import annotations

from collections.abc import Iterator

from lab_devices.experiment import blocks as B
from lab_devices.experiment.errors import Diagnostic, ValidationError
from lab_devices.experiment.workflow import Workflow


def _iter_blocks(blocks: list[B.Block], prefix: str) -> Iterator[tuple[str, B.Block]]:
    """Depth-first (path, block) pairs; group refs are yielded, not expanded."""
    for i, b in enumerate(blocks):
        path = f"{prefix}[{i}]"
        yield path, b
        if isinstance(b, (B.Serial, B.Parallel)):
            yield from _iter_blocks(b.children, f"{path}.children")
        elif isinstance(b, B.Loop):
            yield from _iter_blocks(b.body, f"{path}.body")
        elif isinstance(b, B.Branch):
            yield from _iter_blocks(b.then, f"{path}.then")
            if b.else_ is not None:
                yield from _iter_blocks(b.else_, f"{path}.else")


def _iter_all_blocks(w: Workflow) -> Iterator[tuple[str, B.Block]]:
    yield from _iter_blocks(w.blocks, "blocks")
    for name, group in w.groups.items():
        yield from _iter_blocks(group.body, f"groups[{name!r}].body")


def _check_groups(w: Workflow, out: list[Diagnostic]) -> bool:
    """Unknown group refs and self/mutual recursion (design §12); True iff expandable."""
    ok = True
    for path, b in _iter_all_blocks(w):
        if isinstance(b, B.GroupRef) and b.name not in w.groups:
            out.append(Diagnostic("group", path, f"unknown group {b.name!r}"))
            ok = False
    colors: dict[str, int] = {}  # 0 = on the current DFS path, 1 = fully explored

    def visit(name: str, stack: tuple[str, ...]) -> None:
        nonlocal ok
        state = colors.get(name)
        if state == 1:
            return
        if state == 0:
            cycle = " -> ".join((*stack[stack.index(name):], name))
            out.append(Diagnostic("group", f"groups[{name!r}]", f"recursive group: {cycle}"))
            ok = False
            return
        colors[name] = 0
        for _, b in _iter_blocks(w.groups[name].body, ""):
            if isinstance(b, B.GroupRef) and b.name in w.groups:
                visit(b.name, (*stack, name))
        colors[name] = 1

    for name in w.groups:
        visit(name, ())
    return ok


def validate(workflow: Workflow) -> None:
    """Statically validate a loaded workflow (design §11 phase 2, rules §12).

    Collects every violation and raises one ValidationError; returns None when clean.
    """
    out: list[Diagnostic] = []
    _check_groups(workflow, out)
    if out:
        raise ValidationError(out)
```

- [ ] **Step 4: Run test + full gate**

Run: `.venv/bin/python -m pytest tests/test_experiment_validate_groups.py -v` → all PASS. Full gate clean.

- [ ] **Step 5: Commit**

```bash
git add src/lab_devices/experiment/validate.py tests/test_experiment_validate_groups.py
git commit -m "feat(experiment): validator skeleton with group resolution checks"
```

---

### Task 5: Registry param + expression type checks for Command/Measure

**Files:**
- Modify: `src/lab_devices/experiment/validate.py`
- Test: `tests/test_experiment_validate_params.py` (create)

**Interfaces:**
- Consumes: `ParamSpec`, `lookup` (Task 2); `BindingType`, `infer_type` (Task 3); `parse_expression`, `ExpressionError`, `UnknownVerbError` (Increments 1-2).
- Produces (Task 6 extends these):
  - `_INPUT_TYPES: dict[str, BindingType]` — `{"float": "number", "int": "number", "bool": "boolean", "enum": "string"}`.
  - `_collect_binding_types(w: Workflow) -> dict[str, BindingType]` — every `OperatorInput` anywhere; conflicting redeclarations degrade to `"unknown"`.
  - `_check_block(block, path, w, binding_types, out) -> None` — per-block dispatcher, called for every block by `validate()`.
  - `_check_action(b: B.Command | B.Measure, path, w, binding_types, out)` — registry existence, param specs, param values.
  - `_check_param_value(spec: ParamSpec, value: object, ctx: str, w: Workflow, binding_types, out)` — the `w` parameter is reserved for Task 6's stream-declaration check.
  - `_check_expr_type(text: str, expected: ExprType, ctx: str, binding_types, out)`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_experiment_validate_params.py
from lab_devices.experiment.blocks import Command
from lab_devices.experiment.validate import validate
from lab_devices.experiment.workflow import Workflow
from tests.experiment_validate_helpers import cmd, diags, wf


def test_unknown_verb_programmatic():
    w = Workflow(schema_version=1, blocks=[Command(device="pump_1", verb="teleport")])
    d = diags(w)
    assert any(x.category == "registry" and "teleport" in x.message for x in d)


def test_unknown_param():
    d = diags(wf([cmd("pump_1", "dispense", {"volume_ml": 1.0, "speed_profile": "fast"})]))
    assert any(x.category == "params" and "speed_profile" in x.message for x in d)


def test_missing_required_param():
    d = diags(wf([cmd("pump_1", "rotate", {"direction": "forward"})]))
    assert any(x.category == "params" and "speed_ml_min" in x.message for x in d)


def test_int_param_rejects_float_literal():
    d = diags(wf([cmd("densitometer_1", "set_led", {"level": 2.5})]))
    assert any(
        x.category == "params" and "integer" in x.message and x.path == "blocks[0] param 'level'"
        for x in d
    )


def test_bool_param_rejects_int_literal():
    d = diags(wf([cmd("densitometer_1", "set_thermostat", {"enabled": 1})]))
    assert any(x.category == "params" and "boolean" in x.message for x in d)


def test_number_param_rejects_bool_literal():
    d = diags(wf([cmd("pump_1", "dispense", {"volume_ml": True})]))
    assert any(x.category == "params" and "number" in x.message for x in d)


def test_string_param_rejects_number():
    d = diags(wf([cmd("pump_1", "rotate", {"direction": 5, "speed_ml_min": 1.0})]))
    assert any(x.category == "params" and "string" in x.message for x in d)


def test_non_value_param_rejected():
    w = Workflow(schema_version=1, blocks=[
        Command(device="pump_1", verb="dispense", params={"volume_ml": None}),
    ])
    d = diags(w)
    assert any(x.category == "params" and "number" in x.message for x in d)


def test_number_param_rejects_boolean_expression():
    d = diags(wf([cmd("pump_1", "dispense", {"volume_ml": "1 < 2"})]))
    assert any(x.category == "type" and "number" in x.message for x in d)


def test_bool_param_accepts_boolean_expression():
    assert validate(wf([cmd("valve_1", "configure", {"hold_torque": "1 < 2"})])) is None


def test_bool_param_rejects_number_expression():
    d = diags(wf([cmd("valve_1", "configure", {"hold_torque": "1 + 1"})]))
    assert any(x.category == "type" for x in d)


def test_string_param_is_opaque_not_expression():
    # 'forward' parses as a binding ref, but string-kind params are opaque literals:
    # no unbound-binding or type diagnostics may appear, now or in later tasks.
    w = wf([cmd("pump_1", "rotate", {"direction": "forward", "speed_ml_min": 2.0})])
    assert validate(w) is None


def test_string_binding_in_expression_flagged():
    blocks = [
        {"operator_input": {"name": "sel", "type": "enum", "choices": ["a", "b"]}},
        cmd("pump_1", "dispense", {"volume_ml": "sel * 2"}),
    ]
    d = diags(wf(blocks))
    assert any(x.category == "type" and "sel" in x.message for x in d)


def test_invalid_expression_param_programmatic():
    w = Workflow(schema_version=1, blocks=[
        Command(device="pump_1", verb="dispense", params={"volume_ml": "1 +"}),
    ])
    d = diags(w)
    assert any(x.category == "type" and "invalid expression" in x.message for x in d)


def test_declared_binding_number_type_passes():
    blocks = [
        {"operator_input": {"name": "x", "type": "float", "prompt": "x"}},
        cmd("pump_1", "dispense", {"volume_ml": "x * 2"}),
    ]
    assert validate(wf(blocks)) is None


def test_valid_dispense_clean():
    w = wf([cmd(
        "pump_1", "dispense",
        {"volume_ml": 1.5, "speed_ml_min": 3.0, "direction": "reverse"},
    )])
    assert validate(w) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_experiment_validate_params.py -v`
Expected: most tests FAIL — `diags()` raises `Failed: DID NOT RAISE` (validate only checks groups so far).

- [ ] **Step 3: Implement**

In `src/lab_devices/experiment/validate.py`: extend the imports —

```python
from collections.abc import Iterator, Mapping

from lab_devices.experiment import blocks as B
from lab_devices.experiment.analyze import BindingType, ExprType, infer_type
from lab_devices.experiment.errors import (
    Diagnostic,
    ExpressionError,
    UnknownVerbError,
    ValidationError,
)
from lab_devices.experiment.expr import parse_expression
from lab_devices.experiment.registry import ParamSpec, lookup
from lab_devices.experiment.workflow import Workflow
```

Add below `_check_groups`:

```python
_INPUT_TYPES: dict[str, BindingType] = {
    "float": "number",
    "int": "number",
    "bool": "boolean",
    "enum": "string",
}


def _collect_binding_types(w: Workflow) -> dict[str, BindingType]:
    """Declared type of every operator-input binding; conflicts degrade to 'unknown'."""
    types: dict[str, BindingType] = {}
    for _, b in _iter_all_blocks(w):
        if not isinstance(b, B.OperatorInput) or not isinstance(b.name, str):
            continue
        t = _INPUT_TYPES.get(b.type, "unknown")
        if b.name in types:
            if types[b.name] != t:
                types[b.name] = "unknown"
        else:
            types[b.name] = t
    return types


def _check_expr_type(
    text: str,
    expected: ExprType,
    ctx: str,
    binding_types: Mapping[str, BindingType],
    out: list[Diagnostic],
) -> None:
    try:
        expr = parse_expression(text)
    except ExpressionError as exc:
        out.append(Diagnostic("type", ctx, f"invalid expression: {exc}"))
        return
    report = infer_type(expr, binding_types)
    for problem in report.problems:
        out.append(Diagnostic("type", ctx, problem))
    if report.type not in (expected, "unknown"):
        out.append(Diagnostic(
            "type", ctx, f"expected a {expected} expression, got {report.type}"
        ))


def _check_param_value(
    spec: ParamSpec,
    value: object,
    ctx: str,
    w: Workflow,
    binding_types: Mapping[str, BindingType],
    out: list[Diagnostic],
) -> None:
    """Check one param value against its spec. The w parameter feeds the Task 6
    stream-declaration check; it is deliberately unused until then."""
    if spec.kind == "string":
        if not isinstance(value, str):
            out.append(Diagnostic("params", ctx, f"expected a string literal, got {value!r}"))
        return
    if isinstance(value, str):
        expected: ExprType = "boolean" if spec.kind == "bool" else "number"
        _check_expr_type(value, expected, ctx, binding_types, out)
        return
    if spec.kind == "bool":
        if not isinstance(value, bool):
            out.append(Diagnostic("params", ctx, f"expected a boolean, got {value!r}"))
    elif spec.kind == "int":
        if isinstance(value, bool) or not isinstance(value, int):
            out.append(Diagnostic("params", ctx, f"expected an integer, got {value!r}"))
    else:  # number
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            out.append(Diagnostic("params", ctx, f"expected a number, got {value!r}"))


def _check_action(
    b: B.Command | B.Measure,
    path: str,
    w: Workflow,
    binding_types: Mapping[str, BindingType],
    out: list[Diagnostic],
) -> None:
    try:
        trait = lookup(b.device, b.verb)
    except UnknownVerbError as exc:
        out.append(Diagnostic("registry", path, str(exc)))
        return
    specs = {s.name: s for s in trait.params}
    for name, value in b.params.items():
        spec = specs.get(name)
        if spec is None:
            out.append(Diagnostic("params", path, f"unknown param {name!r} for verb {b.verb!r}"))
            continue
        _check_param_value(spec, value, f"{path} param {name!r}", w, binding_types, out)
    for spec in trait.params:
        if spec.required and spec.name not in b.params:
            out.append(Diagnostic(
                "params", path, f"missing required param {spec.name!r} for verb {b.verb!r}"
            ))


def _check_block(
    block: B.Block,
    path: str,
    w: Workflow,
    binding_types: Mapping[str, BindingType],
    out: list[Diagnostic],
) -> None:
    if isinstance(block, (B.Command, B.Measure)):
        _check_action(block, path, w, binding_types, out)
```

Replace `validate()` with:

```python
def validate(workflow: Workflow) -> None:
    """Statically validate a loaded workflow (design §11 phase 2, rules §12).

    Collects every violation and raises one ValidationError; returns None when clean.
    """
    out: list[Diagnostic] = []
    _check_groups(workflow, out)
    binding_types = _collect_binding_types(workflow)
    for path, block in _iter_all_blocks(workflow):
        _check_block(block, path, workflow, binding_types, out)
    if out:
        raise ValidationError(out)
```

- [ ] **Step 4: Run test + full gate**

Run: `.venv/bin/python -m pytest tests/test_experiment_validate_params.py tests/test_experiment_validate_groups.py -v` → all PASS.
Full gate clean (whole suite — Task 4's group tests must still pass).

- [ ] **Step 5: Commit**

```bash
git add src/lab_devices/experiment/validate.py tests/test_experiment_validate_params.py
git commit -m "feat(experiment): registry param and expression type checks"
```

---

### Task 6: Block-field and stream-declaration checks

**Files:**
- Modify: `src/lab_devices/experiment/validate.py`
- Test: `tests/test_experiment_validate_blocks.py` (create)

**Interfaces:**
- Consumes: `references` (Task 3); everything from Task 5.
- Produces:
  - `_check_streams_declared(text: str, ctx: str, w: Workflow, out) -> None` — every stat-referenced stream (windowed AND counted) must be in `workflow.streams`.
  - `_check_condition(text: object, ctx: str, w, binding_types, out)` — boolean-typed + streams declared; non-string conditions degrade to a diagnostic.
  - `_check_measure`, `_check_operator_input`, `_check_loop` — settled decisions 11-13.
  - `_check_block` grows the full dispatch (Command/Measure/OperatorInput/Loop/Branch).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_experiment_validate_blocks.py
from lab_devices.experiment.blocks import Loop, Measure
from lab_devices.experiment.validate import validate
from lab_devices.experiment.workflow import Workflow
from tests.experiment_validate_helpers import MEASURE_OD, cmd, diags, wf


def test_loop_count_zero():
    d = diags(wf([{"loop": {"count": 0, "body": [MEASURE_OD]}}], streams=["OD"]))
    assert any(x.category == "block" and ">= 1" in x.message for x in d)


def test_loop_count_bool_and_str():
    w = Workflow(schema_version=1, blocks=[Loop(count=True, body=[])])
    assert any("integer" in x.message for x in diags(w))
    w2 = Workflow(schema_version=1, blocks=[Loop(count="5", body=[])])
    assert any("integer" in x.message for x in diags(w2))


def test_loop_count_and_until_both():
    w = Workflow(schema_version=1, blocks=[Loop(count=2, until="1 < 2", body=[])])
    assert any("exactly one" in x.message for x in diags(w))


def test_loop_neither_count_nor_until():
    w = Workflow(schema_version=1, blocks=[Loop(body=[])])
    assert any("exactly one" in x.message for x in diags(w))


def test_pace_only_with_count():
    d = diags(wf(
        [{"loop": {"until": "count(OD) > 3", "pace": "30s", "body": [MEASURE_OD]}}],
        streams=["OD"],
    ))
    assert any("pace" in x.message for x in d)


def test_pace_with_count_ok():
    w = wf([{"loop": {"count": 3, "pace": "30s", "body": [MEASURE_OD]}}], streams=["OD"])
    assert validate(w) is None


def test_invalid_check_programmatic():
    w = Workflow(
        schema_version=1, blocks=[Loop(until="1 < 2", check="sometimes", body=[])]
    )
    assert any("check" in x.message for x in diags(w))


def test_branch_condition_must_be_boolean():
    d = diags(wf([{"branch": {"if": "1 + 1", "then": [MEASURE_OD]}}], streams=["OD"]))
    assert any(x.category == "type" and "boolean" in x.message for x in d)


def test_until_condition_must_be_boolean():
    d = diags(wf(
        [{"loop": {"until": "count(OD) + 1", "check": "after", "body": [MEASURE_OD]}}],
        streams=["OD"],
    ))
    assert any(x.category == "type" and "boolean" in x.message for x in d)


def test_operator_input_bad_type():
    d = diags(wf([{"operator_input": {"name": "x", "type": "string"}}]))
    assert any(x.category == "block" and "float, int, enum, bool" in x.message for x in d)


def test_enum_requires_choices():
    d = diags(wf([{"operator_input": {"name": "x", "type": "enum"}}]))
    assert any("choices" in x.message for x in d)


def test_choices_only_for_enum():
    d = diags(wf([{"operator_input": {"name": "x", "type": "float", "choices": ["a"]}}]))
    assert any("choices" in x.message for x in d)


def test_min_max_only_numeric():
    d = diags(wf([{"operator_input": {"name": "x", "type": "bool", "min": 0}}]))
    assert any("min" in x.message for x in d)


def test_min_exceeds_max():
    d = diags(wf(
        [{"operator_input": {"name": "x", "type": "float", "min": 2.0, "max": 1.0}}]
    ))
    assert any("exceeds" in x.message for x in d)


def test_reserved_binding_name():
    d = diags(wf([{"operator_input": {"name": "not", "type": "float"}}]))
    assert any("binding name" in x.message for x in d)


def test_valid_operator_input():
    w = wf([{"operator_input": {"name": "target", "type": "float", "prompt": "t",
                                "min": 0.0, "max": 2.0}}])
    assert validate(w) is None


def test_measure_into_undeclared_stream():
    d = diags(wf([MEASURE_OD]))  # no streams declared
    assert any(x.category == "declaration" and "'OD'" in x.message for x in d)


def test_measure_requires_measurement_verb():
    w = wf(
        [{"measure": {"device": "pump_1", "verb": "dispense", "into": "OD",
                      "params": {"volume_ml": 1.0}}}],
        streams=["OD"],
    )
    d = diags(w)
    assert any(x.category == "block" and "measurement verb" in x.message for x in d)


def test_measure_into_non_string():
    w = Workflow(schema_version=1, blocks=[
        Measure(device="densitometer_1", verb="measure", into=5),
    ])
    assert any(x.category == "block" and "into" in x.message for x in diags(w))


def test_stat_over_undeclared_stream_in_condition():
    d = diags(wf(
        [{"branch": {"if": "count(ghost) > 0", "then": [MEASURE_OD]}}],
        streams=["OD"],
    ))
    assert any(x.category == "declaration" and "'ghost'" in x.message for x in d)


def test_stat_in_param_over_undeclared_stream():
    d = diags(wf([cmd("pump_1", "dispense", {"volume_ml": "mean(ghost)"})]))
    assert any(x.category == "declaration" and "'ghost'" in x.message for x in d)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_experiment_validate_blocks.py -v`
Expected: FAIL — most tests report `DID NOT RAISE` or missing diagnostics.

- [ ] **Step 3: Implement**

In `src/lab_devices/experiment/validate.py`: add `import re` and extend the analyze import to `from lab_devices.experiment.analyze import BindingType, ExprType, infer_type, references`.

Add:

```python
_IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
_RESERVED_NAMES = frozenset({"and", "or", "not", "true", "false"})


def _check_streams_declared(text: str, ctx: str, w: Workflow, out: list[Diagnostic]) -> None:
    try:
        expr = parse_expression(text)
    except ExpressionError:
        return  # unparseable strings are already diagnosed by the type check
    refs = references(expr)
    for stream in sorted(refs.streams_windowed | refs.streams_counted):
        if stream not in w.streams:
            out.append(Diagnostic(
                "declaration", ctx, f"stat references undeclared stream {stream!r}"
            ))


def _check_condition(
    text: object,
    ctx: str,
    w: Workflow,
    binding_types: Mapping[str, BindingType],
    out: list[Diagnostic],
) -> None:
    if not isinstance(text, str):
        out.append(Diagnostic(
            "type", ctx, f"condition must be an expression string, got {text!r}"
        ))
        return
    _check_expr_type(text, "boolean", ctx, binding_types, out)
    _check_streams_declared(text, ctx, w, out)


def _check_measure(b: B.Measure, path: str, w: Workflow, out: list[Diagnostic]) -> None:
    try:
        trait = lookup(b.device, b.verb)
    except UnknownVerbError:
        return  # already diagnosed by _check_action
    if not trait.measurement:
        out.append(Diagnostic(
            "block", path, f"measure requires a measurement verb, got {b.verb!r}"
        ))
    if not isinstance(b.into, str):
        out.append(Diagnostic(
            "block", path, f"measure into must be a stream name, got {b.into!r}"
        ))
    elif b.into not in w.streams:
        out.append(Diagnostic(
            "declaration", path, f"measure writes undeclared stream {b.into!r}"
        ))


def _check_operator_input(b: B.OperatorInput, path: str, out: list[Diagnostic]) -> None:
    usable = (
        isinstance(b.name, str)
        and _IDENT_RE.fullmatch(b.name) is not None
        and b.name not in _RESERVED_NAMES
    )
    if not usable:
        out.append(Diagnostic(
            "block", path, f"operator_input name {b.name!r} is not a usable binding name"
        ))
    if b.type not in _INPUT_TYPES:
        out.append(Diagnostic(
            "block", path,
            f"operator_input type must be one of float, int, enum, bool; got {b.type!r}",
        ))
        return
    numeric = b.type in ("float", "int")
    if b.type == "enum":
        if not b.choices or not all(isinstance(c, str) for c in b.choices):
            out.append(Diagnostic(
                "block", path, "enum operator_input requires a non-empty list of string choices"
            ))
    elif b.choices is not None:
        out.append(Diagnostic(
            "block", path, f"choices are only valid for enum operator_input, not {b.type!r}"
        ))
    for attr in ("min", "max"):
        value = getattr(b, attr)
        if value is None:
            continue
        if not numeric:
            out.append(Diagnostic(
                "block", path, f"{attr} is only valid for float/int operator_input"
            ))
        elif isinstance(value, bool) or not isinstance(value, (int, float)):
            out.append(Diagnostic("block", path, f"{attr} must be a number, got {value!r}"))
    if (
        isinstance(b.min, (int, float)) and not isinstance(b.min, bool)
        and isinstance(b.max, (int, float)) and not isinstance(b.max, bool)
        and b.min > b.max
    ):
        out.append(Diagnostic("block", path, f"min {b.min} exceeds max {b.max}"))


def _check_loop(
    b: B.Loop,
    path: str,
    w: Workflow,
    binding_types: Mapping[str, BindingType],
    out: list[Diagnostic],
) -> None:
    has_count = b.count is not None
    has_until = b.until is not None
    if has_count == has_until:
        out.append(Diagnostic("block", path, "loop requires exactly one of count or until"))
    if has_count:
        if isinstance(b.count, bool) or not isinstance(b.count, int):
            out.append(Diagnostic(
                "block", path, f"loop count must be an integer, got {b.count!r}"
            ))
        elif b.count < 1:
            out.append(Diagnostic("block", path, f"loop count must be >= 1, got {b.count}"))
    if b.check not in ("before", "after"):
        out.append(Diagnostic(
            "block", path, f"loop check must be 'before' or 'after', got {b.check!r}"
        ))
    if has_until:
        if b.pace is not None:
            out.append(Diagnostic("block", path, "loop pace is only valid with count mode"))
        _check_condition(b.until, f"{path} loop until", w, binding_types, out)
```

Extend `_check_param_value` — inside the `if isinstance(value, str):` branch, after the `_check_expr_type(...)` call, add:

```python
        _check_streams_declared(value, ctx, w, out)
```

Replace `_check_block` with the full dispatcher:

```python
def _check_block(
    block: B.Block,
    path: str,
    w: Workflow,
    binding_types: Mapping[str, BindingType],
    out: list[Diagnostic],
) -> None:
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

- [ ] **Step 4: Run test + full gate**

Run: `.venv/bin/python -m pytest tests/test_experiment_validate_blocks.py tests/test_experiment_validate_params.py tests/test_experiment_validate_groups.py -v` → all PASS.
Full gate clean.

- [ ] **Step 5: Commit**

```bash
git add src/lab_devices/experiment/validate.py tests/test_experiment_validate_blocks.py
git commit -m "feat(experiment): block-field and stream-declaration checks"
```

---

### Task 7: All-paths data-flow analysis

**Files:**
- Modify: `src/lab_devices/experiment/validate.py`
- Test: `tests/test_experiment_validate_dataflow.py` (create)

**Interfaces:**
- Consumes: `references` (Task 3); `_check_groups`'s expandable flag (Task 4); traits/param kinds (Task 2).
- Produces (Task 8 extends these exact structures):
  - `_PathState` — dataclass with `bindings: set[str]`, `streams: set[str]` (both "definitely written"), a `copy()` method; default `__eq__` used for the loop fixpoint test.
  - `_merge(a, b) -> _PathState` — intersection join.
  - `_Ctx` — dataclass `(workflow, out, seen)` with `emit(category, path, message)` deduplicating by the triple (loop re-analysis revisits blocks).
  - `_visit(b, path, state, c) -> _PathState`, `_visit_blocks(blocks, prefix, state, c) -> _PathState`, `_visit_action`, `_visit_loop`, `_visit_parallel`, `_expr_reads`, `_analyze_paths(w, out)`.
  - `validate()` gains the path phase, gated on `_check_groups`'s return.

Semantics implemented here (settled decisions 5-6): reads = expression strings in non-string-kind declared params, `branch if`, `loop until`; writes = `OperatorInput` (binding), `Measure.into` (stream, after its own params are read). Branch joins intersect; parallel lanes see entry + own writes, union after; post-test/count loops guarantee one execution; pre-test `until` reads against loop entry; back-edge re-analysis to a fixpoint with deduped emission. Windowed stats missing a definite writer emit `data-flow` ONLY for declared streams (undeclared ones already got a `declaration` diagnostic); counted streams are exempt.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_experiment_validate_dataflow.py
from lab_devices.experiment.validate import validate
from tests.experiment_validate_helpers import MEASURE_OD, cmd, diags, wf

INPUT_X = {"operator_input": {"name": "x", "type": "float"}}
DISPENSE_X = cmd("pump_1", "dispense", {"volume_ml": "x * 2"})


def test_read_before_write_binding():
    d = diags(wf([DISPENSE_X, INPUT_X]))
    assert any(
        x.category == "data-flow" and "'x'" in x.message and "before" in x.message for x in d
    )


def test_write_then_read_clean():
    assert validate(wf([INPUT_X, DISPENSE_X])) is None


def test_branch_one_arm_write_not_definite():
    blocks = [
        {"branch": {"if": "1 < 2", "then": [INPUT_X]}},
        DISPENSE_X,
    ]
    d = diags(wf(blocks))
    assert any(x.category == "data-flow" and "'x'" in x.message for x in d)


def test_branch_both_arms_write_definite():
    blocks = [
        {"branch": {"if": "1 < 2", "then": [INPUT_X], "else": [INPUT_X]}},
        DISPENSE_X,
    ]
    assert validate(wf(blocks)) is None


def test_read_inside_writing_arm_clean():
    blocks = [{"branch": {"if": "1 < 2", "then": [INPUT_X, DISPENSE_X]}}]
    assert validate(wf(blocks)) is None


def test_condition_read_before_write():
    blocks = [{"branch": {"if": "x > 1", "then": [INPUT_X]}}]
    d = diags(wf(blocks))
    assert any(
        x.category == "data-flow" and "'x'" in x.message and "branch if" in x.path for x in d
    )


def test_post_test_until_sees_body_writes():
    blocks = [{"loop": {"until": "mean(OD) > 1", "check": "after", "body": [MEASURE_OD]}}]
    assert validate(wf(blocks, streams=["OD"])) is None


def test_pre_test_until_needs_preseed():
    blocks = [{"loop": {"until": "mean(OD) > 1", "check": "before", "body": [MEASURE_OD]}}]
    d = diags(wf(blocks, streams=["OD"]))
    assert any(x.category == "data-flow" and "'OD'" in x.message for x in d)


def test_pre_test_until_with_preseed_clean():
    blocks = [
        MEASURE_OD,
        {"loop": {"until": "mean(OD) > 1", "check": "before", "body": [MEASURE_OD]}},
    ]
    assert validate(wf(blocks, streams=["OD"])) is None


def test_pre_test_count_exemption():
    blocks = [{"loop": {"until": "count(OD) >= 10", "check": "before", "body": [MEASURE_OD]}}]
    assert validate(wf(blocks, streams=["OD"])) is None


def test_count_loop_writes_survive():
    blocks = [
        {"loop": {"count": 3, "body": [MEASURE_OD]}},
        cmd("pump_1", "dispense", {"volume_ml": "last(OD)"}),
    ]
    assert validate(wf(blocks, streams=["OD"])) is None


def test_pre_test_loop_writes_do_not_survive():
    blocks = [
        {"loop": {"until": "count(OD) >= 1", "check": "before", "body": [MEASURE_OD]}},
        cmd("pump_1", "dispense", {"volume_ml": "last(OD)"}),
    ]
    d = diags(wf(blocks, streams=["OD"]))
    assert any(x.category == "data-flow" and "'OD'" in x.message for x in d)


def test_post_test_loop_writes_survive():
    blocks = [
        {"loop": {"until": "count(OD) >= 5", "check": "after", "body": [MEASURE_OD]}},
        cmd("pump_1", "dispense", {"volume_ml": "last(OD)"}),
    ]
    assert validate(wf(blocks, streams=["OD"])) is None


def test_parallel_sibling_writes_not_visible():
    blocks = [{"parallel": {"children": [
        {"serial": {"children": [INPUT_X]}},
        {"serial": {"children": [DISPENSE_X]}},
    ]}}]
    d = diags(wf(blocks))
    assert any(x.category == "data-flow" and "'x'" in x.message for x in d)


def test_parallel_writes_visible_after_join():
    blocks = [
        {"parallel": {"children": [
            {"serial": {"children": [INPUT_X]}},
            {"serial": {"children": [MEASURE_OD]}},
        ]}},
        DISPENSE_X,
        cmd("pump_2", "dispense", {"volume_ml": "last(OD)"}),
    ]
    assert validate(wf(blocks, streams=["OD"])) is None


def test_group_expansion_flows_state():
    groups = {"seed": {"body": [INPUT_X]}}
    blocks = [{"group_ref": {"name": "seed"}}, DISPENSE_X]
    assert validate(wf(blocks, groups=groups)) is None


def test_binding_written_in_loop_body_post_test_until():
    blocks = [{"loop": {"until": "x > 1", "check": "after", "body": [INPUT_X]}}]
    assert validate(wf(blocks)) is None


def test_binding_pre_test_until_unwritten():
    blocks = [{"loop": {"until": "x > 1", "check": "before", "body": [INPUT_X]}}]
    d = diags(wf(blocks))
    assert any(x.category == "data-flow" and "'x'" in x.message for x in d)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_experiment_validate_dataflow.py -v`
Expected: the negative tests FAIL with `DID NOT RAISE`; the positive tests already pass.

- [ ] **Step 3: Implement**

In `src/lab_devices/experiment/validate.py`: add `from dataclasses import dataclass, field` to the imports. Append:

```python
@dataclass
class _PathState:
    """Abstract state along one control-flow path (design §12)."""

    bindings: set[str] = field(default_factory=set)  # definitely written by operator_input
    streams: set[str] = field(default_factory=set)  # definitely written by a measure

    def copy(self) -> _PathState:
        return _PathState(set(self.bindings), set(self.streams))


def _merge(a: _PathState, b: _PathState) -> _PathState:
    """Join at a control-flow merge: definitely-written = written on both sides."""
    return _PathState(a.bindings & b.bindings, a.streams & b.streams)


@dataclass
class _Ctx:
    workflow: Workflow
    out: list[Diagnostic]
    seen: set[tuple[str, str, str]] = field(default_factory=set)

    def emit(self, category: str, path: str, message: str) -> None:
        """Append a diagnostic once; loop re-analysis legitimately revisits blocks."""
        key = (category, path, message)
        if key not in self.seen:
            self.seen.add(key)
            self.out.append(Diagnostic(category, path, message))


def _expr_reads(text: object, ctx: str, state: _PathState, c: _Ctx) -> None:
    """Check one expression slot's reads against the current path state."""
    if not isinstance(text, str):
        return  # literals read nothing; non-string garbage is diagnosed globally
    try:
        expr = parse_expression(text)
    except ExpressionError:
        return  # already diagnosed globally
    refs = references(expr)
    for name in sorted(refs.bindings - state.bindings):
        c.emit("data-flow", ctx, f"binding {name!r} may be read before it is written")
    for stream in sorted(refs.streams_windowed - state.streams):
        if stream in c.workflow.streams:  # undeclared streams already got a diagnostic
            c.emit(
                "data-flow", ctx,
                f"stat over stream {stream!r} has no preceding measure on some path",
            )


def _visit_action(b: B.Command | B.Measure, path: str, state: _PathState, c: _Ctx) -> None:
    try:
        trait = lookup(b.device, b.verb)
    except UnknownVerbError:
        return  # already diagnosed globally; nothing to analyze against
    specs = {s.name: s for s in trait.params}
    for name, value in b.params.items():
        spec = specs.get(name)
        if spec is not None and spec.kind != "string":
            _expr_reads(value, f"{path} param {name!r}", state, c)
    if isinstance(b, B.Measure) and isinstance(b.into, str):
        state.streams.add(b.into)


def _visit_loop(b: B.Loop, path: str, state: _PathState, c: _Ctx) -> _PathState:
    body_path = f"{path}.body"
    until_ctx = f"{path} loop until"
    count = b.count if isinstance(b.count, int) and not isinstance(b.count, bool) else None
    if b.until is not None:
        repeats, guaranteed = True, b.check != "before"
    elif count is not None and count >= 1:
        repeats, guaranteed = count > 1, True
    else:  # invalid loop fields (diagnosed globally): assume the worst on both axes
        repeats, guaranteed = True, False
    if b.until is not None and b.check == "before":
        _expr_reads(b.until, until_ctx, state, c)  # pre-test: first check sees entry only
    exit_state = _visit_blocks(b.body, body_path, state.copy(), c)
    if b.until is not None and b.check != "before":
        _expr_reads(b.until, until_ctx, exit_state, c)  # post-test: check sees body writes
    result = exit_state
    if repeats:
        # Back edge: iteration k+1 starts from iteration k's exit. Re-analyze to a
        # fixpoint (the abstract state space is tiny); _Ctx.emit dedupes repeats.
        prev = exit_state
        for _ in range(3):
            nxt = _visit_blocks(b.body, body_path, prev.copy(), c)
            if b.until is not None and b.check != "before":
                _expr_reads(b.until, until_ctx, nxt, c)
            result = _merge(result, nxt)
            if nxt == prev:
                break
            prev = nxt
    if not guaranteed:
        result = _merge(state, result)  # zero iterations possible: entry state survives
    return result


def _visit_parallel(b: B.Parallel, path: str, state: _PathState, c: _Ctx) -> _PathState:
    exits = []
    for i, child in enumerate(b.children):
        # Each concurrent lane sees only the entry state plus its own writes:
        # sibling writes are unordered relative to this lane (design §12).
        exits.append(_visit(child, f"{path}.children[{i}]", state.copy(), c))
    for e in exits:  # the container completes when every lane does: union of writes
        state.bindings |= e.bindings
        state.streams |= e.streams
    return state


def _visit(b: B.Block, path: str, state: _PathState, c: _Ctx) -> _PathState:
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
        then_state = _visit_blocks(b.then, f"{path}.then", state.copy(), c)
        else_state = _visit_blocks(b.else_ or [], f"{path}.else", state.copy(), c)
        state = _merge(then_state, else_state)
    elif isinstance(b, B.GroupRef):
        group = c.workflow.groups.get(b.name)
        if group is not None:  # unknown refs are diagnosed globally; phase is gated anyway
            state = _visit_blocks(group.body, f"{path}->{b.name}.body", state, c)
    return state  # Wait blocks fall through unchanged


def _visit_blocks(blocks: list[B.Block], prefix: str, state: _PathState, c: _Ctx) -> _PathState:
    for i, b in enumerate(blocks):
        state = _visit(b, f"{prefix}[{i}]", state, c)
    return state


def _analyze_paths(w: Workflow, out: list[Diagnostic]) -> None:
    _visit_blocks(w.blocks, "blocks", _PathState(), _Ctx(w, out))
```

Replace `validate()` with (the path phase is gated on group sanity):

```python
def validate(workflow: Workflow) -> None:
    """Statically validate a loaded workflow (design §11 phase 2, rules §12).

    Collects every violation and raises one ValidationError; returns None when clean.
    The path-sensitive phase is skipped when group references cannot be resolved
    (unknown or recursive groups) — the tree cannot be soundly expanded.
    """
    out: list[Diagnostic] = []
    expandable = _check_groups(workflow, out)
    binding_types = _collect_binding_types(workflow)
    for path, block in _iter_all_blocks(workflow):
        _check_block(block, path, workflow, binding_types, out)
    if expandable:
        _analyze_paths(workflow, out)
    if out:
        raise ValidationError(out)
```

- [ ] **Step 4: Run test + full gate**

Run: `.venv/bin/python -m pytest tests/test_experiment_validate_dataflow.py -v` → all PASS.
Full gate clean — pay attention to Tasks 4-6 test files: their positive fixtures were designed to stay clean under data-flow (e.g. `direction: "forward"` reads nothing because string-kind params are opaque).

- [ ] **Step 5: Commit**

```bash
git add src/lab_devices/experiment/validate.py tests/test_experiment_validate_dataflow.py
git commit -m "feat(experiment): all-paths data-flow analysis"
```

---

### Task 8: May-open mode intervals + channel affinity

**Files:**
- Modify: `src/lab_devices/experiment/validate.py`
- Test: `tests/test_experiment_validate_modes.py` (create)

**Interfaces:**
- Consumes: `mode_action`, `ModeAction`, trait `channels` (Task 2); the Task 7 walk.
- Produces:
  - `_PathState` gains `modes: dict[tuple[str, str], str]` — `(device_id, mode_verb) → "open" | "maybe"`; absent = closed. `copy()` and `_merge` extended (merge lattice: open∧open → open, else maybe).
  - `_visit_action` gains the mode/affinity middle section (settled decisions 2-4).
  - `_footprint(root: B.Block, w: Workflow) -> set[tuple[str, str]]` — every `(device, channel)` a subtree can command on any reachable path, groups inlined.
  - `_visit_parallel` gains pairwise footprint disjointness + per-lane mode-delta application.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_experiment_validate_modes.py
from lab_devices.experiment.validate import validate
from tests.experiment_validate_helpers import MEASURE_OD, cmd, diags, wf

ROTATE = cmd("pump_1", "rotate", {"direction": "forward", "speed_ml_min": 2.0})
STOP = cmd("pump_1", "stop")
DISPENSE = cmd("pump_1", "dispense", {"volume_ml": 1.0})
DISPENSE_2 = cmd("pump_2", "dispense", {"volume_ml": 1.0})
THERMO_ON = cmd("densitometer_1", "set_thermostat", {"enabled": True, "target_c": 37.0})
THERMO_OFF = cmd("densitometer_1", "set_thermostat", {"enabled": False})
LED_ON = cmd("densitometer_1", "set_led", {"level": 5})
LED_OFF = cmd("densitometer_1", "set_led", {"level": 0})


def test_free_start_stop_mode_valid():
    # §15.2 pattern: rotate ... other-device work ... stop
    assert validate(wf([ROTATE, MEASURE_OD, STOP], streams=["OD"])) is None


def test_command_inside_open_mode():
    d = diags(wf([ROTATE, DISPENSE, STOP]))
    assert any(
        x.category == "mode" and "'rotate'" in x.message and x.path == "blocks[1]" for x in d
    )


def test_reopen_same_mode():
    d = diags(wf([ROTATE, ROTATE]))
    assert any(x.category == "mode" for x in d)


def test_adjust_open_led_mode_rejected():
    d = diags(wf([LED_ON, cmd("densitometer_1", "set_led", {"level": 3})]))
    assert any(x.category == "mode" for x in d)


def test_close_without_open_is_noop():
    assert validate(wf([LED_OFF, STOP, THERMO_OFF])) is None


def test_unclosed_mode_at_end_is_legal():
    # Least-strict lifetimes: the finalizer is the universal close (design §12-13).
    assert validate(wf([ROTATE])) is None


def test_maybe_open_then_matching_close_clean():
    blocks = [
        {"branch": {"if": "1 < 2", "then": [ROTATE]}},
        STOP,
        DISPENSE,
    ]
    assert validate(wf(blocks)) is None


def test_maybe_open_then_conflicting_command():
    blocks = [
        {"branch": {"if": "1 < 2", "then": [ROTATE]}},
        DISPENSE,
    ]
    d = diags(wf(blocks))
    assert any(x.category == "mode" and "possibly open" in x.message for x in d)


def test_open_on_both_arms_is_definitely_open():
    blocks = [
        {"branch": {"if": "1 < 2", "then": [ROTATE], "else": [ROTATE]}},
        DISPENSE,
    ]
    d = diags(wf(blocks))
    assert any(x.category == "mode" and "open interval" in x.message for x in d)


def test_thermostat_and_measure_disjoint_channels():
    assert validate(wf([THERMO_ON, MEASURE_OD, THERMO_OFF], streams=["OD"])) is None


def test_led_mode_blocks_measure():
    d = diags(wf([LED_ON, MEASURE_OD], streams=["OD"]))
    assert any(x.category == "mode" and "'set_led'" in x.message for x in d)


def test_densitometer_stop_conflicts_with_thermostat_mode():
    d = diags(wf([THERMO_ON, cmd("densitometer_1", "stop")]))
    assert any(x.category == "mode" for x in d)


def test_loop_body_open_without_close_back_edge():
    d = diags(wf([{"loop": {"count": 3, "body": [ROTATE]}}]))
    assert any(x.category == "mode" and "body[0]" in x.path for x in d)


def test_loop_body_balanced_clean():
    assert validate(wf([{"loop": {"count": 3, "body": [ROTATE, STOP]}}])) is None


def test_count_one_loop_open_no_back_edge():
    assert validate(wf([{"loop": {"count": 1, "body": [ROTATE]}}])) is None


def test_expression_param_mode_is_conservative_open():
    blocks = [
        {"operator_input": {"name": "lvl", "type": "int"}},
        cmd("densitometer_1", "set_led", {"level": "lvl"}),
        MEASURE_OD,
    ]
    d = diags(wf(blocks, streams=["OD"]))
    assert any(x.category == "mode" for x in d)


def test_parallel_same_device_channel_overlap():
    blocks = [{"parallel": {"children": [
        DISPENSE, cmd("pump_1", "dispense", {"volume_ml": 2.0}),
    ]}}]
    d = diags(wf(blocks))
    assert any(x.category == "affinity" and "'pump_1'" in x.message for x in d)


def test_parallel_disjoint_devices_clean():
    assert validate(wf([{"parallel": {"children": [DISPENSE, DISPENSE_2]}}])) is None


def test_parallel_same_device_disjoint_channels_clean():
    blocks = [{"parallel": {"children": [MEASURE_OD, THERMO_ON]}}]
    assert validate(wf(blocks, streams=["OD"])) is None


def test_parallel_same_device_same_channel_conflict():
    blocks = [{"parallel": {"children": [MEASURE_OD, LED_ON]}}]
    d = diags(wf(blocks, streams=["OD"]))
    assert any(x.category == "affinity" and "optics" in x.message for x in d)


def test_footprint_reaches_nested_and_groups():
    groups = {"work": {"body": [DISPENSE]}}
    blocks = [{"parallel": {"children": [
        {"loop": {"count": 2, "body": [{"group_ref": {"name": "work"}}]}},
        {"branch": {"if": "1 < 2", "then": [ROTATE, STOP]}},
    ]}}]
    d = diags(wf(blocks, groups=groups))
    assert any(x.category == "affinity" and "motor" in x.message for x in d)


def test_mode_spanning_parallel_other_devices_clean():
    blocks = [
        ROTATE,
        {"parallel": {"children": [DISPENSE_2, MEASURE_OD]}},
        STOP,
    ]
    assert validate(wf(blocks, streams=["OD"])) is None


def test_mode_spanning_parallel_conflicting_child():
    blocks = [ROTATE, {"parallel": {"children": [DISPENSE, MEASURE_OD]}}, STOP]
    d = diags(wf(blocks, streams=["OD"]))
    assert any(x.category == "mode" for x in d)


def test_close_inside_parallel_child():
    blocks = [ROTATE, {"parallel": {"children": [STOP, MEASURE_OD]}}, DISPENSE]
    assert validate(wf(blocks, streams=["OD"])) is None


def test_mode_opened_in_child_closed_after_parallel():
    blocks = [{"parallel": {"children": [ROTATE, MEASURE_OD]}}, STOP, DISPENSE]
    assert validate(wf(blocks, streams=["OD"])) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_experiment_validate_modes.py -v`
Expected: negative tests FAIL with `DID NOT RAISE`; positives pass.

- [ ] **Step 3: Implement**

In `src/lab_devices/experiment/validate.py`: extend the registry import to `from lab_devices.experiment.registry import ParamSpec, lookup, mode_action`.

Replace `_PathState` and `_merge`:

```python
@dataclass
class _PathState:
    """Abstract state along one control-flow path (design §12)."""

    bindings: set[str] = field(default_factory=set)  # definitely written by operator_input
    streams: set[str] = field(default_factory=set)  # definitely written by a measure
    modes: dict[tuple[str, str], str] = field(default_factory=dict)
    # modes: (device_id, mode_verb) -> "open" | "maybe"; absent = closed

    def copy(self) -> _PathState:
        return _PathState(set(self.bindings), set(self.streams), dict(self.modes))


def _merge(a: _PathState, b: _PathState) -> _PathState:
    """Join at a control-flow merge: definitely-written = written on both sides;
    a mode is open only if open on both, else possibly open (may-open tracking)."""
    modes: dict[tuple[str, str], str] = {}
    for key in a.modes.keys() | b.modes.keys():
        sa, sb = a.modes.get(key), b.modes.get(key)
        modes[key] = "open" if sa == "open" and sb == "open" else "maybe"
    return _PathState(a.bindings & b.bindings, a.streams & b.streams, modes)
```

Replace `_visit_action` (adds the mode/affinity middle section between reads and writes):

```python
def _visit_action(b: B.Command | B.Measure, path: str, state: _PathState, c: _Ctx) -> None:
    try:
        trait = lookup(b.device, b.verb)
    except UnknownVerbError:
        return  # already diagnosed globally; nothing to analyze against
    specs = {s.name: s for s in trait.params}
    for name, value in b.params.items():
        spec = specs.get(name)
        if spec is not None and spec.kind != "string":
            _expr_reads(value, f"{path} param {name!r}", state, c)
    action = mode_action(b.device, b.verb, b.params)
    if action is not None and action.kind == "close":
        # A matching close is always legal: closes if open, no-ops if not (design §12).
        state.modes.pop((b.device, action.mode_verb), None)
    else:
        for (device, mode_verb), status in sorted(state.modes.items()):
            if device != b.device:
                continue
            if lookup(device, mode_verb).channels & trait.channels:
                word = "open" if status == "open" else "possibly open"
                c.emit(
                    "mode", path,
                    f"{b.verb!r} on {b.device!r} falls inside the {word} interval of "
                    f"mode {mode_verb!r}",
                )
        if action is not None:
            state.modes[(b.device, action.mode_verb)] = "open"
    if isinstance(b, B.Measure) and isinstance(b.into, str):
        state.streams.add(b.into)
```

Add `_footprint` and replace `_visit_parallel`:

```python
def _footprint(root: B.Block, w: Workflow) -> set[tuple[str, str]]:
    """Every (device, channel) a subtree can command on any reachable path (groups
    inlined; the path phase only runs when the group graph is acyclic)."""
    found: set[tuple[str, str]] = set()
    stack: list[B.Block] = [root]
    while stack:
        b = stack.pop()
        if isinstance(b, (B.Command, B.Measure)):
            try:
                trait = lookup(b.device, b.verb)
            except UnknownVerbError:
                continue
            found.update((b.device, ch) for ch in trait.channels)
        elif isinstance(b, (B.Serial, B.Parallel)):
            stack.extend(b.children)
        elif isinstance(b, B.Loop):
            stack.extend(b.body)
        elif isinstance(b, B.Branch):
            stack.extend(b.then)
            if b.else_ is not None:
                stack.extend(b.else_)
        elif isinstance(b, B.GroupRef):
            group = w.groups.get(b.name)
            if group is not None:
                stack.extend(group.body)
    return found


def _visit_parallel(b: B.Parallel, path: str, state: _PathState, c: _Ctx) -> _PathState:
    footprints = [_footprint(child, c.workflow) for child in b.children]
    for i in range(len(b.children)):
        for j in range(i + 1, len(b.children)):
            for device, channel in sorted(footprints[i] & footprints[j]):
                c.emit(
                    "affinity", path,
                    f"parallel children [{i}] and [{j}] both command device {device!r} "
                    f"channel {channel!r}",
                )
    entry_modes = dict(state.modes)
    exits = []
    for i, child in enumerate(b.children):
        # Each concurrent lane sees only the entry state plus its own writes:
        # sibling writes are unordered relative to this lane (design §12).
        exits.append(_visit(child, f"{path}.children[{i}]", state.copy(), c))
    for e in exits:  # the container completes when every lane does: union of writes
        state.bindings |= e.bindings
        state.streams |= e.streams
        # Footprint disjointness means each lane owns the modes it touches:
        # apply every lane's delta against the shared entry.
        for key in e.modes.keys() - entry_modes.keys():
            state.modes[key] = e.modes[key]
        for key in entry_modes.keys() - e.modes.keys():
            state.modes.pop(key, None)
        for key in entry_modes.keys() & e.modes.keys():
            if e.modes[key] != entry_modes[key]:
                state.modes[key] = e.modes[key]
    return state
```

- [ ] **Step 4: Run test + full gate**

Run: `.venv/bin/python -m pytest tests/test_experiment_validate_modes.py -v` → all PASS.
Full gate clean. Earlier positive fixtures must stay clean — in particular Task 5's
`test_string_param_is_opaque_not_expression` leaves a rotate mode open at workflow end,
which is legal under least-strict lifetimes.

- [ ] **Step 5: Commit**

```bash
git add src/lab_devices/experiment/validate.py tests/test_experiment_validate_modes.py
git commit -m "feat(experiment): may-open mode intervals and channel affinity analysis"
```

---

### Task 9: Public API + flagship end-to-end coverage

**Files:**
- Modify: `src/lab_devices/experiment/validate.py` (add `load_and_validate`)
- Modify: `src/lab_devices/experiment/__init__.py` (exports)
- Test: `tests/test_experiment_validate_api.py` (create)

**Interfaces:**
- Produces:
  - `load_and_validate(path: str | Path) -> Workflow` — `load_workflow` then `validate`; the two phases stay individually callable (design §11).
  - Public exports: `validate`, `load_and_validate`, `ValidationError`, `Diagnostic`, `references`, `ExprRefs`, `infer_type`, `TypeReport`, `BindingType`, `ExprType`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_experiment_validate_api.py
import json

import pytest

import lab_devices.experiment as exp
from lab_devices.experiment import (
    ValidationError,
    load_and_validate,
    validate,
    workflow_from_dict,
)

# The design spec's flagship example (§15.2), verbatim. It must validate cleanly:
# free start/stop rotate..stop, close-with-no-open set_led(0), post-test feedback
# loop, group ref, operator-input binding.
SPEC_EXAMPLE = {
    "schema_version": 1,
    "metadata": {
        "name": "od-feedback-feed",
        "author": "khamitov",
        "description": "Feed pump_1 by live OD until target, stirring throughout.",
    },
    "persistence": {"default": "disk", "format": "jsonl"},
    "streams": {
        "OD": {"units": "AU"},
        "temp": {"units": "C", "persistence": "in_memory"},
    },
    "groups": {
        "prime_line": {
            "body": [
                {"command": {"device": "pump_1", "verb": "dispense",
                             "params": {"volume_ml": 1.0, "speed_ml_min": 5.0}}}
            ]
        }
    },
    "blocks": [
        {"serial": {"children": [
            {"operator_input": {"name": "target_OD", "type": "float",
                                "prompt": "Enter target OD", "min": 0.0, "max": 2.0}},
            {"group_ref": {"name": "prime_line"}},
            {"command": {"device": "pump_2", "verb": "rotate",
                         "params": {"direction": "forward", "speed_ml_min": 2.0}}},
            {"loop": {
                "check": "after",
                "until": "mean(OD, last=5min) >= target_OD",
                "body": [
                    {"measure": {"device": "densitometer_1", "verb": "measure",
                                 "into": "OD"}},
                    {"command": {"device": "pump_1", "verb": "dispense",
                                 "params": {
                                     "volume_ml": "2.0 * (target_OD - mean(OD, last=100))",
                                     "speed_ml_min": 3.0}},
                     "gap_after": "30s"},
                ],
            }},
            {"command": {"device": "pump_2", "verb": "stop"}},
            {"branch": {
                "if": "last(OD) > target_OD",
                "then": [{"command": {"device": "densitometer_1", "verb": "set_led",
                                      "params": {"level": 0}}}],
            }},
        ]}}
    ],
}


def test_spec_flagship_example_validates():
    assert validate(workflow_from_dict(SPEC_EXAMPLE)) is None


def test_load_and_validate_returns_workflow(tmp_path):
    p = tmp_path / "wf.json"
    p.write_text(json.dumps(SPEC_EXAMPLE))
    w = load_and_validate(p)
    assert w.metadata.name == "od-feedback-feed"


def test_load_and_validate_rejects(tmp_path):
    doc = {
        "schema_version": 1,
        "blocks": [
            {"command": {"device": "pump_1", "verb": "rotate",
                         "params": {"direction": "forward", "speed_ml_min": 2.0}}},
            {"command": {"device": "pump_1", "verb": "dispense",
                         "params": {"volume_ml": 1.0}}},
        ],
    }
    p = tmp_path / "bad.json"
    p.write_text(json.dumps(doc))
    with pytest.raises(ValidationError) as exc:
        load_and_validate(p)
    assert any(x.category == "mode" for x in exc.value.diagnostics)


def test_collect_all_categories_in_one_raise():
    doc = {
        "schema_version": 1,
        "streams": {},
        "blocks": [
            {"group_ref": {"name": "ghost"}},
            {"command": {"device": "pump_1", "verb": "rotate",
                         "params": {"direction": "forward"}}},
            {"measure": {"device": "densitometer_1", "verb": "measure", "into": "OD"}},
            {"branch": {"if": "1 + 1",
                        "then": [{"command": {"device": "pump_1", "verb": "stop"}}]}},
        ],
    }
    with pytest.raises(ValidationError) as exc:
        validate(workflow_from_dict(doc))
    cats = {d.category for d in exc.value.diagnostics}
    assert {"group", "params", "declaration", "type"} <= cats


def test_validation_error_message_lists_each_diagnostic():
    doc = {
        "schema_version": 1,
        "blocks": [{"group_ref": {"name": "ghost"}}],
    }
    with pytest.raises(ValidationError) as exc:
        validate(workflow_from_dict(doc))
    assert "unknown group 'ghost'" in str(exc.value)


def test_exports():
    for name in (
        "validate", "load_and_validate", "ValidationError", "Diagnostic",
        "references", "ExprRefs", "infer_type", "TypeReport", "BindingType", "ExprType",
    ):
        assert name in exp.__all__
        assert getattr(exp, name) is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_experiment_validate_api.py -v`
Expected: FAIL — `ImportError: cannot import name 'load_and_validate'`

- [ ] **Step 3: Implement**

In `src/lab_devices/experiment/validate.py`: add imports —

```python
from pathlib import Path

from lab_devices.experiment.serialize import load_workflow
```

Append:

```python
def load_and_validate(path: str | Path) -> Workflow:
    """Load a workflow document and statically validate it (design §11 phases 1-2)."""
    workflow = load_workflow(path)
    validate(workflow)
    return workflow
```

In `src/lab_devices/experiment/__init__.py`: extend the analyze/errors/validate imports —

```python
from lab_devices.experiment.analyze import (
    BindingType,
    ExprRefs,
    ExprType,
    TypeReport,
    infer_type,
    references,
)
from lab_devices.experiment.errors import Diagnostic, ValidationError
from lab_devices.experiment.validate import load_and_validate, validate
```

(the errors import merges into the existing `from lab_devices.experiment.errors import ...` line), and extend `__all__` with:

```python
    "BindingType", "Diagnostic", "ExprRefs", "ExprType", "TypeReport",
    "ValidationError", "infer_type", "load_and_validate", "references", "validate",
```

- [ ] **Step 4: Run test + full gate**

Run: `.venv/bin/python -m pytest tests/test_experiment_validate_api.py -v` → all PASS.
Full gate clean (whole suite, mypy, ruff, awk length check on ALL experiment source
and test files).

- [ ] **Step 5: Commit**

```bash
git add src/lab_devices/experiment/validate.py src/lab_devices/experiment/__init__.py \
    tests/test_experiment_validate_api.py
git commit -m "feat(experiment): validator public API + flagship end-to-end coverage"
```

---

## Final verification (before requesting the whole-branch review)

- Whole gate: `.venv/bin/python -m pytest` / `-m mypy` / `-m ruff check .` / awk length check.
- Re-read amended spec §12 and cross-check every rule maps to a test: registry/params (Tasks 2, 5), affinity (Task 8), mode lifetime incl. optional closes + matching-close exception (Task 8), data-flow incl. count exemption + declarations (Tasks 6, 7), group expansion (Task 4), §15.2 flagship (Task 9).
- Confirm the Increment 2 deferred tickets are closed: loop count typing (Task 6), non-ValueExpr params (Task 5), enum-vs-expression param typing (Tasks 2, 5).
- Record the Increment 4 carry-forwards (top of this plan) in the SDD ledger.
