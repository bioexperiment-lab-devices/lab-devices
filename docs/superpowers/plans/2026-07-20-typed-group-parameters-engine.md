# Typed Group Parameters — Engine Implementation Plan (PR 1)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the untyped `Group.params: list[str]` textual macro with a kind system shared by group params, group locals, and `for_each` vars, and move role ownership into the engine.

**Architecture:** One kind set (`int`/`number`/`bool`/`string` values; `role`/`stream`/`binding` references) is declared on group params, group locals, and `for_each` vars, and consumed by a single kind-aware substitution engine in `expand.py`. Group locals let a group own its streams and bindings, expanding to namespaced top-level declarations with hoisted initializers, so a typed `service` group needs two params instead of nine. Roles become a first-class `Workflow.roles` section: `device:` fields hold role names end-to-end, device *types* come from the declaration rather than from `rsplit("_", 1)` on an id, and a single resolution point converts a role to a physical handle at the wire boundary.

**Tech Stack:** Python 3.14, dataclasses, pytest, mypy, ruff. No new dependencies.

## Global Constraints

- **Design spec:** `docs/superpowers/specs/2026-07-20-typed-group-parameters-design.md` — read it before Task 1. Every task cites the section it implements.
- **Branch:** `feat/group-param-types` in the worktree `.claude/worktrees/group-param-types`.
- **Python 3.14.** Use `.venv/bin/python` — bare `python` lacks the dependencies.
- **Gate, run after every task:** `.venv/bin/python -m pytest`, `.venv/bin/python -m mypy src/lab_devices` (**never** pass `tests/` — the scope is `src/lab_devices` only), `.venv/bin/python -m ruff check .`, and `awk 'length>100'` over experiment `src` + `tests`.
- **Line length ≤ 100.** Ruff's default `select` has no `E501`, so the `awk` check is what enforces it. `E402`/`F401` *are* selected — imports go at the top of test files.
- **Source modules:** `from __future__ import annotations` plus a one-line docstring citing the design section. **Test modules:** flat as `tests/test_experiment_*.py`, **no** `from __future__ import annotations`.
- **Executor tests** use `tests/fakeclock.py` (`FakeClock` + `drive`, zero wall-clock) and the `FakeLab` call-recording helper in `tests/experiment_run_helpers.py`.
- **Every intermediate commit must be green.** Task 2 introduces a deliberate transitional shim (`_legacy_ids.py`) to hold that invariant; **Task 8 Step 7 deletes it**. The increment is not complete while it exists.
- **Schema break:** `SCHEMA_VERSION = 2`. A v1 document using `groups` or `for_each` must fail to load with the message from design §7 — its param types were never recorded and cannot be inferred.
- **Regression oracle:** `tests/test_examples_morbidostat.py`'s 120-cycle IC50 assertion must hold **unchanged** across the migration. If it moves, the migration changed behaviour and is wrong.

---

### Task 1: Typed declaration data model

**Files:**
- Modify `src/lab_devices/experiment/errors.py` (insert after line 18, below `UnknownVerbError`)
- Modify `src/lab_devices/experiment/workflow.py` (lines 1–7 header/imports; 29–33 `Group`; 44–52 `Workflow`)
- Modify `src/lab_devices/experiment/serialize.py` (lines 408–417 group parse; 445–450 group emit) — **transitional bridge only**, so `mypy` and the existing round-trip stay green; Task 3 deletes it
- Create `tests/test_experiment_param_types.py`

**Interfaces:**

*Consumes:* `lab_devices.experiment.errors.WorkflowLoadError`; `lab_devices.experiment.blocks.Block`, `Retry`.

*Produces (verbatim from contract):*
```python
ParamKind = Literal["int", "number", "bool", "string", "role", "stream", "binding"]
VALUE_KINDS: frozenset[str]
REFERENCE_KINDS: frozenset[str]

@dataclass(frozen=True)
class ParamDecl:
    name: str
    kind: ParamKind
    device_type: str | None = None

@dataclass(frozen=True)
class LocalDecl:
    kind: Literal["stream", "binding"]
    init: str | None = None
    units: str | None = None
    persistence: str | None = None

@dataclass(frozen=True)
class RoleDecl:
    type: str
    device: str | None = None

@dataclass
class Group:
    name: str
    body: list[Block] = field(default_factory=list)
    params: list[ParamDecl] = field(default_factory=list)
    locals: dict[str, LocalDecl] = field(default_factory=dict)

@dataclass
class Workflow:
    ...
    roles: dict[str, RoleDecl] = field(default_factory=dict)
    def role_type(self, role: str) -> str: ...

class UnknownRoleError(WorkflowLoadError): ...
```

Nothing in this task validates a declaration — parsing lands in Task 3, checking in the validate task. This is the data model plus one accessor.

- [ ] **Step 1: Write the failing test**

Create `tests/test_experiment_param_types.py`:

```python
import dataclasses
from typing import get_args

import pytest

from lab_devices.experiment.errors import UnknownRoleError, WorkflowLoadError
from lab_devices.experiment.workflow import (
    REFERENCE_KINDS,
    VALUE_KINDS,
    Group,
    LocalDecl,
    ParamDecl,
    ParamKind,
    RoleDecl,
    Workflow,
)


def test_kind_sets_partition_the_param_kind_union():
    """VALUE_KINDS and REFERENCE_KINDS must cover ParamKind exactly and not overlap:
    every substitution rule in design 2026-07-20 §3 branches on which set a kind is in,
    so a kind in neither set (or both) has undefined substitution behaviour."""
    assert VALUE_KINDS == {"int", "number", "bool", "string"}
    assert REFERENCE_KINDS == {"role", "stream", "binding"}
    assert not (VALUE_KINDS & REFERENCE_KINDS)
    assert VALUE_KINDS | REFERENCE_KINDS == set(get_args(ParamKind))


def test_param_decl_defaults_and_role_carries_device_type():
    p = ParamDecl("tube", "int")
    assert p.name == "tube" and p.kind == "int" and p.device_type is None
    meter = ParamDecl(name="meter", kind="role", device_type="densitometer")
    assert meter.device_type == "densitometer"
    with pytest.raises(dataclasses.FrozenInstanceError):
        meter.kind = "int"


def test_local_decl_defaults():
    binding = LocalDecl(kind="binding", init="0")
    assert binding.kind == "binding" and binding.init == "0"
    assert binding.units is None and binding.persistence is None
    stream = LocalDecl(kind="stream", units="ug/mL", persistence="disk")
    assert stream.init is None and stream.units == "ug/mL"
    assert stream.persistence == "disk"


def test_role_decl_device_is_optional():
    assert RoleDecl(type="densitometer").device is None
    assert RoleDecl(type="pump", device="pump_2").device == "pump_2"


def test_group_declares_typed_params_and_locals():
    g = Group(name="service")
    assert g.params == [] and g.locals == {} and g.body == []
    typed = Group(
        name="service",
        params=[ParamDecl("tube", "int"), ParamDecl("od", "stream")],
        locals={"c": LocalDecl(kind="binding", init="0")},
    )
    assert [p.name for p in typed.params] == ["tube", "od"]
    assert typed.params[1].kind == "stream"
    assert typed.locals["c"].init == "0"


def test_workflow_roles_default_empty():
    w = Workflow(schema_version=2)
    assert w.roles == {}


def test_role_type_reads_the_declaration():
    w = Workflow(
        schema_version=2,
        roles={"od_meter_1": RoleDecl(type="densitometer"),
               "medium_pump": RoleDecl(type="pump", device="pump_2")},
    )
    assert w.role_type("od_meter_1") == "densitometer"
    assert w.role_type("medium_pump") == "pump"


def test_role_type_raises_unknown_role_error_naming_the_declared_roles():
    w = Workflow(schema_version=2, roles={"od_meter_1": RoleDecl(type="densitometer")})
    with pytest.raises(UnknownRoleError, match="od_meter_2"):
        w.role_type("od_meter_2")
    with pytest.raises(UnknownRoleError, match=r"od_meter_1"):
        w.role_type("od_meter_2")


def test_unknown_role_error_is_a_workflow_load_error():
    """Existing callers catch WorkflowLoadError; an undeclared role must not escape them."""
    assert issubclass(UnknownRoleError, WorkflowLoadError)
```

- [ ] **Step 2: Run it and watch it fail**

```
.venv/bin/python -m pytest tests/test_experiment_param_types.py -v
```

Expected — collection fails before any test runs:

```
tests/test_experiment_param_types.py:7: in <module>
    from lab_devices.experiment.errors import UnknownRoleError, WorkflowLoadError
E   ImportError: cannot import name 'UnknownRoleError' from 'lab_devices.experiment.errors'
=========================== short test summary info ============================
ERROR tests/test_experiment_param_types.py
!!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!
```

- [ ] **Step 3: Add `UnknownRoleError`**

In `src/lab_devices/experiment/errors.py`, immediately after `UnknownVerbError` (line 18):

```python
class UnknownRoleError(WorkflowLoadError):
    """A device field or role-kinded arg names a role with no declaration
    (design 2026-07-20 §5.1)."""
```

- [ ] **Step 4: Add the typed declarations to `workflow.py`**

Replace lines 1–7 of `src/lab_devices/experiment/workflow.py`:

```python
"""Top-level workflow document. See design §15; typed declarations design 2026-07-20 §2, §5.1."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from lab_devices.experiment.blocks import Block, Retry
from lab_devices.experiment.errors import UnknownRoleError

ParamKind = Literal["int", "number", "bool", "string", "role", "stream", "binding"]

VALUE_KINDS: frozenset[str] = frozenset({"int", "number", "bool", "string"})
REFERENCE_KINDS: frozenset[str] = frozenset({"role", "stream", "binding"})
```

(`errors.py` imports nothing from the package, so this adds no import cycle.)

Replace the `Group` dataclass (lines 29–33) with:

```python
@dataclass(frozen=True)
class ParamDecl:
    """One typed group param or for_each var (design 2026-07-20 §2.1)."""

    name: str
    kind: ParamKind
    device_type: str | None = None  # required iff kind == "role", forbidden otherwise


@dataclass(frozen=True)
class LocalDecl:
    """A stream or binding a group owns (design 2026-07-20 §2.2)."""

    kind: Literal["stream", "binding"]
    init: str | None = None          # constant expression; binding-kind only
    units: str | None = None         # stream-kind only
    persistence: str | None = None   # stream-kind only


@dataclass(frozen=True)
class RoleDecl:
    """A named instrument slot (design 2026-07-20 §5.1)."""

    type: str
    device: str | None = None  # optional direct binding for standalone (non-Studio) use


@dataclass
class Group:
    name: str
    body: list[Block] = field(default_factory=list)
    params: list[ParamDecl] = field(default_factory=list)
    locals: dict[str, LocalDecl] = field(default_factory=dict)
```

Replace the `Workflow` dataclass (lines 44–52) with:

```python
@dataclass
class Workflow:
    schema_version: int
    blocks: list[Block] = field(default_factory=list)
    metadata: Metadata = field(default_factory=Metadata)
    persistence: Persistence = field(default_factory=Persistence)
    streams: dict[str, StreamDecl] = field(default_factory=dict)
    groups: dict[str, Group] = field(default_factory=dict)
    roles: dict[str, RoleDecl] = field(default_factory=dict)
    defaults: Defaults = field(default_factory=Defaults)

    def role_type(self, role: str) -> str:
        """Device type of a declared role (design 2026-07-20 §5.1). The single site every
        type-consuming caller reads, now that registry.device_type is gone."""
        try:
            return self.roles[role].type
        except KeyError:
            raise UnknownRoleError(
                f"undeclared role {role!r}; declared roles: {sorted(self.roles)}"
            ) from None
```

- [ ] **Step 5: Add the transitional serialize bridge**

`Group.params` is now `list[ParamDecl]`, but `serialize.py` still reads and writes v1 strings; without this shim `mypy` fails on the `list[str]` -> `list[ParamDecl]` assignment and the existing round-trip test dumps dataclasses into JSON. Both sides are deleted in Task 3.

In `src/lab_devices/experiment/serialize.py`, add `ParamDecl` to the `workflow` import block (lines 14–21), then replace the group-parse body (lines 411–417):

```python
        params = g.get("params", [])
        if not isinstance(params, list) or not all(isinstance(p, str) for p in params):
            raise WorkflowLoadError(f"group {name!r} params must be a list of strings")
        groups[name] = Group(
            name=name, body=_children(g.get("body", []), f"groups.{name}.body"),
            # TRANSITIONAL (Task 1 -> Task 3): v1 params are untyped strings. Task 3
            # replaces this with the typed `params` list parser (design 2026-07-20 §2.1).
            params=[ParamDecl(name=p, kind="string") for p in params],
        )
```

And the group-emit expression (lines 445–450):

```python
    if w.groups:
        out["groups"] = {
            # TRANSITIONAL (Task 1 -> Task 3): emits v1 name-only params.
            name: ({"params": [p.name for p in g.params]} if g.params else {})
                  | {"body": [block_to_dict(c) for c in g.body]}
            for name, g in w.groups.items()
        }
```

- [ ] **Step 6: Run the tests and the gate**

```
.venv/bin/python -m pytest tests/test_experiment_param_types.py -v
```

Expected: `8 passed`, with every test named above showing `PASSED`.

Then confirm nothing regressed:

```
.venv/bin/python -m pytest -q
.venv/bin/python -m mypy src/lab_devices
.venv/bin/python -m ruff check .
awk 'length>100 {print FILENAME": "FNR}' src/lab_devices/experiment/workflow.py \
    src/lab_devices/experiment/errors.py src/lab_devices/experiment/serialize.py \
    tests/test_experiment_param_types.py
```

Expected: pytest ends `N passed` with zero failures, mypy prints `Success: no issues found`, ruff prints `All checks passed!`, `awk` prints nothing.

- [ ] **Step 7: Commit**

```
git add src/lab_devices/experiment/workflow.py src/lab_devices/experiment/errors.py \
        src/lab_devices/experiment/serialize.py tests/test_experiment_param_types.py
git commit -m "feat(experiment): typed param, local, and role declarations in the workflow model"
```

---

### Task 2: Registry takes device types

**Files:**
- Modify `src/lab_devices/experiment/registry.py` (delete `device_type` at 200–202; re-signature `lookup` 205–212 and `mode_action` 236–243; add `DEVICE_TYPES` after `_REGISTRY` at line 197)
- Create `src/lab_devices/experiment/_legacy_ids.py` (transitional; deleted by the role-threading task)
- Modify `src/lab_devices/experiment/serialize.py` (lines 131, 139)
- Modify `src/lab_devices/experiment/validate.py` (line 39 import; call sites 238, 376, 492, 721, 729, 737, 792)
- Modify `src/lab_devices/experiment/execute.py` (line 30 import; call sites 209, 267, 368, 370, 630)
- Modify `src/lab_devices/experiment/finalize.py` (line 9 import; line 58)
- Modify `tests/test_experiment_registry.py` (whole file)

Not touched: `webapp/backend/experiment_studio/runner.py:110` (PR 2, design §9.2); `src/lab_devices/client.py:62` and `src/lab_devices/devices/base.py:19` (the **core's** own id convention, which stays — only the experiment layer's copy goes); `catalog.py:27` iterates `_REGISTRY` directly and needs no change.

**Interfaces:**

*Consumes:* `_REGISTRY: dict[tuple[str, str], Trait]`.

*Produces (verbatim from contract):*
```python
DEVICE_TYPES: frozenset[str]                 # device types present in _REGISTRY
def lookup(dtype: str, verb: str) -> Trait: ...
def mode_action(dtype: str, verb: str, params: Mapping[str, object]) -> ModeAction | None: ...
# registry.device_type is DELETED
```

*Produces (transitional, `src/lab_devices/experiment/_legacy_ids.py`):*
```python
def legacy_device_type(device_id: str) -> str: ...
```

**Why the shim exists, stated plainly:** four modules must hand `lookup` a *type* the moment its signature changes, but they will not receive one from `workflow.roles` until the role-threading task. Three private `rsplit` copies hidden in three modules is exactly what the design set out to delete. One named function in one file, whose docstring names its executioner, keeps the suite green now and makes `grep -rn legacy_device_type src` the complete removal checklist later.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_experiment_registry.py`:

```python
def test_lookup_takes_a_device_type_not_an_id():
    """The discriminating assertion is the SECOND one. `lookup("pump", ...)` passes today
    too, because rsplit("_", 1) on a string with no underscore returns it unchanged --
    a probe that only asserts the positive case is vacuous here."""
    assert lookup("pump", "dispense").completion == "job"
    with pytest.raises(UnknownVerbError):
        lookup("pump_1", "dispense")


def test_mode_action_takes_a_device_type_not_an_id():
    assert mode_action("pump", "stop", {}) == ModeAction("close", "rotate")
    with pytest.raises(UnknownVerbError):
        mode_action("pump_1", "stop", {})


def test_device_type_helper_is_deleted():
    """Roles carry their type in the declaration; deriving it from an id is the convention
    this increment removes (design 2026-07-20 §5.2)."""
    assert not hasattr(registry, "device_type")


def test_device_types_is_derived_from_the_registry():
    assert registry.DEVICE_TYPES == frozenset({"pump", "valve", "densitometer"})
    assert registry.DEVICE_TYPES == frozenset(dtype for dtype, _verb in _REGISTRY)
    assert isinstance(registry.DEVICE_TYPES, frozenset)
```

and add `from lab_devices.experiment import registry` to that file's imports (line 3).

- [ ] **Step 2: Run it and watch it fail**

```
.venv/bin/python -m pytest tests/test_experiment_registry.py -k "device_type or takes_a_device_type" -v
```

Expected:

```
__________________ test_lookup_takes_a_device_type_not_an_id ___________________
        assert lookup("pump", "dispense").completion == "job"
>       with pytest.raises(UnknownVerbError):
E       Failed: DID NOT RAISE UnknownVerbError
_________________________ test_device_type_helper_is_deleted __________________
>       assert not hasattr(registry, "device_type")
E       AssertionError: assert not True
E        +  where True = hasattr(registry, 'device_type')
=========================== short test summary item ============================
FAILED tests/test_experiment_registry.py::test_lookup_takes_a_device_type_not_an_id
FAILED tests/test_experiment_registry.py::test_mode_action_takes_a_device_type_not_an_id
FAILED tests/test_experiment_registry.py::test_device_type_helper_is_deleted
FAILED tests/test_experiment_registry.py::test_device_types_is_derived_from_the_registry
```

(`test_device_type_strips_index` still passes at this point; it is deleted in Step 3.)

- [ ] **Step 3: Re-signature the registry**

In `src/lab_devices/experiment/registry.py`, after the `_REGISTRY` literal closes (line 197) add:

```python
DEVICE_TYPES: frozenset[str] = frozenset(dtype for dtype, _verb in _REGISTRY)
```

Delete `device_type` (lines 200–202) entirely and replace `lookup` (205–212):

```python
def lookup(dtype: str, verb: str) -> Trait:
    """Trait for a (device TYPE, verb) pair. The caller supplies the type -- read it from
    `workflow.roles[name].type` (design 2026-07-20 §5.2)."""
    try:
        return _REGISTRY[(dtype, verb)]
    except KeyError:
        raise UnknownVerbError(
            f"no registry entry for device-type {dtype!r} verb {verb!r}"
        ) from None
```

Replace `mode_action`'s signature and first two lines (236–243):

```python
def mode_action(dtype: str, verb: str, params: Mapping[str, object]) -> ModeAction | None:
    """Classify a command instance as a mode-open, a mode-close, or neither (design §12).

    Conservative: any params that do not literally equal the teardown's (including
    expression strings) classify a mode verb as an open.
    """
    trait = lookup(dtype, verb)
```

The `for (entry_type, mode_verb), entry in _REGISTRY.items()` loop below already compares against `dtype`; leave it unchanged.

- [ ] **Step 4: Migrate the rest of `tests/test_experiment_registry.py`**

```
sed -i '' -E 's/(lookup|mode_action)\("(pump|valve|densitometer|toaster)_[0-9]+"/\1("\2"/g' \
    tests/test_experiment_registry.py
```

Then by hand: delete `device_type,` from the import block (line 9) and delete `test_device_type_strips_index` (lines 15–17) — the convention it pins no longer exists.

```
.venv/bin/python -m pytest tests/test_experiment_registry.py -v
```

Expected: `24 passed`, including `test_lookup_takes_a_device_type_not_an_id PASSED` and `test_device_types_is_derived_from_the_registry PASSED`.

- [ ] **Step 5: Add the transitional shim and update the four src callers**

Create `src/lab_devices/experiment/_legacy_ids.py`:

```python
"""TRANSITIONAL id->type derivation (design 2026-07-20 §5.2). DELETE THIS FILE.

`registry.device_type` is gone: a device type now comes from `workflow.roles[name].type`.
The validator, executor, finalizer, and loader cannot read a declaration until roles are
threaded through them, so they route through this one named function in the meantime.
`grep -rn legacy_device_type src` is the complete list of sites the role-threading task
must convert; when it returns nothing, delete this module.
"""

from __future__ import annotations


def legacy_device_type(device_id: str) -> str:
    """Mirror the core's Device.type derivation (client.py:62, devices/base.py:19)."""
    return device_id.rsplit("_", 1)[0]
```

`src/lab_devices/experiment/serialize.py` — line 13 stays; add the shim import below it, then lines 131 and 139 become:

```python
        lookup(legacy_device_type(device), verb)
```

`src/lab_devices/experiment/validate.py` — add `from lab_devices.experiment._legacy_ids import legacy_device_type` beside line 39, then:

| line | before | after |
|---|---|---|
| 238 | `lookup(b.device, b.verb)` | `lookup(legacy_device_type(b.device), b.verb)` |
| 376 | `lookup(b.device, b.verb)` | `lookup(legacy_device_type(b.device), b.verb)` |
| 492 | `lookup(block.device, block.verb)` | `lookup(legacy_device_type(block.device), block.verb)` |
| 721 | `lookup(b.device, b.verb)` | `lookup(legacy_device_type(b.device), b.verb)` |
| 729 | `mode_action(b.device, b.verb, b.params)` | `mode_action(legacy_device_type(b.device), b.verb, b.params)` |
| 737 | `lookup(device, mode_verb)` | `lookup(legacy_device_type(device), mode_verb)` |
| 792 | `lookup(b.device, b.verb)` | `lookup(legacy_device_type(b.device), b.verb)` |

`src/lab_devices/experiment/execute.py` — add the same import beside line 30, then:

| line | before | after |
|---|---|---|
| 209 | `lookup(block.device, block.verb)` | `lookup(legacy_device_type(block.device), block.verb)` |
| 267 | `lookup(device, "stop").channels` | `lookup(legacy_device_type(device), "stop").channels` |
| 368 | `lookup(block.device, block.verb)` | `lookup(legacy_device_type(block.device), block.verb)` |
| 370 | `mode_action(block.device, block.verb, params)` | `mode_action(legacy_device_type(block.device), block.verb, params)` |
| 630 | `lookup(block.device, block.verb).result_field` | `lookup(legacy_device_type(block.device), block.verb).result_field` |

Line 370 exceeds 100 columns once wrapped; write it as:

```python
    action = mode_action(  # on RESOLVED values (D7)
        legacy_device_type(block.device), block.verb, params
    )
```

`src/lab_devices/experiment/finalize.py` — replace line 9 and line 58:

```python
from lab_devices.experiment._legacy_ids import legacy_device_type
```
```python
        for verb, params in _SWEEP.get(legacy_device_type(device_id), ()):
```

- [ ] **Step 6: Run the full suite and the gate**

```
.venv/bin/python -m pytest -q
.venv/bin/python -m mypy src/lab_devices
.venv/bin/python -m ruff check .
awk 'length>100 {print FILENAME": "FNR}' src/lab_devices/experiment/*.py \
    tests/test_experiment_registry.py
grep -rn "device_type(" src/lab_devices/experiment/
```

Expected: pytest ends `N passed` with **zero failures** — this task keeps the suite green end to end. mypy `Success: no issues found`, ruff `All checks passed!`, `awk` silent. The `grep` must show only `legacy_device_type(` hits plus `_legacy_ids.py`'s own definition — no `registry.device_type`, no bare `rsplit("_", 1)` inside `experiment/`.

- [ ] **Step 7: Commit**

```
git add src/lab_devices/experiment/registry.py src/lab_devices/experiment/_legacy_ids.py \
        src/lab_devices/experiment/serialize.py src/lab_devices/experiment/validate.py \
        src/lab_devices/experiment/execute.py src/lab_devices/experiment/finalize.py \
        tests/test_experiment_registry.py
git commit -m "refactor(experiment)!: registry lookup and mode_action take a device type

registry.device_type is deleted; callers route through the transitional
_legacy_ids.legacy_device_type until roles are threaded (design 2026-07-20 §5.2)."
```

---

### Task 3: Serialization

**Files:**
- Modify `src/lab_devices/experiment/serialize.py` (line 13 imports; 23 `SCHEMA_VERSION`; 34–37 `_children`; 127–143 `_command`/`_measure`; every builder 146–242; 245–260 `_BUILDERS`; 263–285 `block_from_dict`; 374–423 `workflow_from_dict`; 426–452 `workflow_to_dict`)
- Create `tests/test_experiment_serialize_v2.py`
- Create `tests/experiment_role_helpers.py`
- Modify `tests/test_experiment_serialize.py` (whole file — v1 docs to v2 + roles)
- Modify `tests/test_experiment_workflow.py` (whole file — same)
- Modify `tests/experiment_validate_helpers.py` (lines 9–15) and `tests/experiment_run_helpers.py` (lines 13–29)

**Interfaces:**

*Consumes:* `ParamDecl`, `ParamKind`, `LocalDecl`, `RoleDecl`, `Group`, `Workflow` (Task 1); `DEVICE_TYPES`, `lookup` (Task 2); `UnknownRoleError` (Task 1).

*Produces:*
```python
SCHEMA_VERSION = 2

def _command(body: Any, timing: dict[str, Any], roles: dict[str, RoleDecl]) -> B.Block: ...
def _measure(body: Any, timing: dict[str, Any], roles: dict[str, RoleDecl]) -> B.Block: ...
def _children(raw: Any, ctx: str, roles: dict[str, RoleDecl]) -> list[B.Block]: ...
def block_from_dict(d: Any, roles: dict[str, RoleDecl] | None = None) -> B.Block: ...
def _param_decls(raw: Any, ctx: str) -> list[ParamDecl]: ...
def _local_decls(raw: Any, ctx: str) -> dict[str, LocalDecl]: ...
```
Emitted top-level key order: `schema_version, metadata, persistence, defaults, roles, streams, groups, blocks`. Group key order: `params, locals, body`.

*Deleted:* the Task-1 transitional group-param bridge in both directions.

*Explicitly NOT in this task:* `group_ref.as` (blocks.py field), the typed `for_each` `vars`/`in` table, constant-only `init` checking, and the removal of `_legacy_ids`. Those belong to the expansion and validation tasks; `_for_each` and `_group_ref` here gain only the `roles` parameter their builder signature now requires.

**The parse-ordering problem, concretely.** Today `workflow_from_dict` parses blocks *inside* the constructor call (`serialize.py:418–423`) while `_command`/`_measure` resolve a device to a trait at parse time (`serialize.py:131,139`). With role names in `device:`, that lookup needs a type that only a `roles` declaration can supply. So `roles` is parsed into a local *before* any block is built, and threaded down `_children` -> `block_from_dict` -> every builder. Group bodies get the same dict — a group body's `device:` fields name roles from the same top-level table.

- [ ] **Step 1: Write the failing test**

Create `tests/test_experiment_serialize_v2.py`:

```python
import pytest

from lab_devices.experiment import blocks as B
from lab_devices.experiment.errors import UnknownRoleError, WorkflowLoadError
from lab_devices.experiment.serialize import (
    SCHEMA_VERSION,
    block_from_dict,
    workflow_from_dict,
    workflow_to_dict,
)
from lab_devices.experiment.workflow import LocalDecl, ParamDecl, RoleDecl

ROLES = {
    "od_meter_1": RoleDecl(type="densitometer"),
    "medium_pump": RoleDecl(type="pump", device="pump_2"),
}


def test_schema_version_is_two():
    assert SCHEMA_VERSION == 2


def test_v1_document_is_rejected_with_a_message_naming_the_remedy():
    """A v1 doc using groups or for_each cannot be lifted mechanically -- the types were
    never recorded. The message has to say so, or the author retries the same load."""
    with pytest.raises(WorkflowLoadError) as exc:
        workflow_from_dict({"schema_version": 1, "blocks": []})
    text = str(exc.value)
    assert "unsupported schema_version 1; expected 2" in text
    assert "cannot be migrated automatically" in text
    assert "design 2026-07-20 §7" in text


def test_roles_parse_before_blocks_so_a_role_resolves_to_a_device_type():
    """The ordering test: `device` holds a ROLE name, and the parse-time registry lookup
    needs its type. If blocks were still parsed inside the Workflow(...) call, this raises."""
    w = workflow_from_dict({
        "schema_version": 2,
        "roles": {"od_meter_1": {"type": "densitometer"}},
        "streams": {"od_1": {}},
        "blocks": [{"measure": {"device": "od_meter_1", "verb": "measure", "into": "od_1"}}],
    })
    assert w.roles == {"od_meter_1": RoleDecl(type="densitometer")}
    assert w.role_type("od_meter_1") == "densitometer"
    assert isinstance(w.blocks[0], B.Measure)
    assert w.blocks[0].device == "od_meter_1"


def test_a_role_declaration_may_bind_a_device_directly():
    w = workflow_from_dict({
        "schema_version": 2,
        "roles": {"medium_pump": {"type": "pump", "device": "pump_2"}},
        "blocks": [{"command": {"device": "medium_pump", "verb": "stop"}}],
    })
    assert w.roles["medium_pump"] == RoleDecl(type="pump", device="pump_2")


def test_undeclared_role_in_a_device_field_is_a_load_error():
    with pytest.raises(UnknownRoleError, match="ghost_pump"):
        workflow_from_dict({
            "schema_version": 2,
            "roles": {"medium_pump": {"type": "pump"}},
            "blocks": [{"command": {"device": "ghost_pump", "verb": "stop"}}],
        })


def test_a_role_body_verb_is_still_checked_against_the_declared_type():
    """The type comes from the declaration now, not from the id's suffix: a densitometer
    role cannot dispense."""
    with pytest.raises(WorkflowLoadError, match="densitometer"):
        workflow_from_dict({
            "schema_version": 2,
            "roles": {"od_meter_1": {"type": "densitometer"}},
            "blocks": [{"command": {"device": "od_meter_1", "verb": "dispense",
                                    "params": {"volume_ml": 1.0}}}],
        })


def test_unexpanded_hole_in_a_device_field_still_defers_the_lookup():
    """The `if "{" not in device` escape stays: a group body names a role via a hole."""
    b = block_from_dict({"measure": {"device": "{meter}", "verb": "measure", "into": "{od}"}},
                        ROLES)
    assert isinstance(b, B.Measure) and b.device == "{meter}"


def test_unknown_role_device_type_is_a_load_error():
    with pytest.raises(WorkflowLoadError, match="toaster"):
        workflow_from_dict({
            "schema_version": 2,
            "roles": {"breakfast": {"type": "toaster"}},
            "blocks": [],
        })


def test_typed_group_params_parse_in_authoring_order():
    w = workflow_from_dict({
        "schema_version": 2,
        "roles": {"od_meter_1": {"type": "densitometer"}},
        "groups": {"service": {
            "params": [
                {"name": "tube", "kind": "int"},
                {"name": "od", "kind": "stream"},
                {"name": "meter", "kind": "role", "device_type": "densitometer"},
            ],
            "body": [{"wait": {"duration": "1s"}}],
        }},
        "blocks": [],
    })
    params = w.groups["service"].params
    assert params == [
        ParamDecl(name="tube", kind="int"),
        ParamDecl(name="od", kind="stream"),
        ParamDecl(name="meter", kind="role", device_type="densitometer"),
    ]
    assert [p.name for p in params] == ["tube", "od", "meter"]


@pytest.mark.parametrize("params, match", [
    ([{"name": "tube", "kind": "integer"}], "unknown kind"),
    ([{"name": "meter", "kind": "role"}], "requires 'device_type'"),
    ([{"name": "meter", "kind": "role", "device_type": "toaster"}], "unknown device type"),
    ([{"name": "tube", "kind": "int", "device_type": "pump"}], "only allowed on kind 'role'"),
    ([{"kind": "int"}], "requires 'name'"),
    ([{"name": "tube"}], "requires 'kind'"),
    ([{"name": "tube", "kind": "int", "typo": 1}], "unknown key"),
    (["tube"], "must be an object"),
    ({"tube": "int"}, "must be a list"),
])
def test_malformed_param_declarations_rejected(params, match):
    with pytest.raises(WorkflowLoadError, match=match):
        workflow_from_dict({
            "schema_version": 2,
            "groups": {"service": {"params": params, "body": []}},
            "blocks": [],
        })


def test_group_locals_parse():
    w = workflow_from_dict({
        "schema_version": 2,
        "groups": {"service": {
            "params": [{"name": "tube", "kind": "int"}],
            "locals": {
                "c": {"kind": "binding", "init": "0"},
                "r": {"kind": "binding"},
                "c_series": {"kind": "stream", "units": "ug/mL", "persistence": "disk"},
            },
            "body": [{"wait": {"duration": "1s"}}],
        }},
        "blocks": [],
    })
    locals_ = w.groups["service"].locals
    assert locals_["c"] == LocalDecl(kind="binding", init="0")
    assert locals_["r"] == LocalDecl(kind="binding")
    assert locals_["c_series"] == LocalDecl(
        kind="stream", units="ug/mL", persistence="disk"
    )


@pytest.mark.parametrize("locals_, match", [
    ({"c": {"kind": "int"}}, "must be 'stream' or 'binding'"),
    ({"c": {"kind": "stream", "init": "0"}}, "'init' is only allowed on kind 'binding'"),
    ({"c": {"kind": "binding", "units": "AU"}}, "only allowed on kind 'stream'"),
    ({"c": {"kind": "binding", "init": "1 +"}}, "init"),
    ({"c": {}}, "requires 'kind'"),
    ({"c": {"kind": "binding", "typo": 1}}, "unknown key"),
    (["c"], "must be an object"),
])
def test_malformed_local_declarations_rejected(locals_, match):
    with pytest.raises(WorkflowLoadError, match=match):
        workflow_from_dict({
            "schema_version": 2,
            "groups": {"service": {"locals": locals_, "body": []}},
            "blocks": [],
        })


V2_DOC = {
    "schema_version": 2,
    "metadata": {"name": "typed", "author": "khamitov"},
    "persistence": {"default": "in_memory", "format": "jsonl"},
    "defaults": {"retry": {"attempts": 2, "backoff": "5s"}},
    "roles": {
        "od_meter_1": {"type": "densitometer"},
        "medium_pump": {"type": "pump", "device": "pump_2"},
    },
    "streams": {"od_1": {"units": "AU"}},
    "groups": {"service": {
        "params": [
            {"name": "tube", "kind": "int"},
            {"name": "meter", "kind": "role", "device_type": "densitometer"},
        ],
        "locals": {
            "c": {"kind": "binding", "init": "0"},
            "c_series": {"kind": "stream", "units": "ug/mL"},
        },
        "body": [{"measure": {"device": "{meter}", "verb": "measure", "into": "{od}"}}],
    }},
    "blocks": [
        {"measure": {"device": "od_meter_1", "verb": "measure", "into": "od_1"}},
        {"command": {"device": "medium_pump", "verb": "dispense",
                     "params": {"volume_ml": 0.5}}},
    ],
}


def test_v2_document_round_trips_byte_for_byte():
    assert workflow_to_dict(workflow_from_dict(V2_DOC)) == V2_DOC


def test_emitted_key_order_puts_roles_immediately_before_streams():
    """Dict equality does not check order, so the round-trip test above cannot see this."""
    out = workflow_to_dict(workflow_from_dict(V2_DOC))
    assert list(out) == ["schema_version", "metadata", "persistence", "defaults",
                         "roles", "streams", "groups", "blocks"]
    assert list(out["groups"]["service"]) == ["params", "locals", "body"]


def test_empty_roles_and_locals_are_omitted_from_the_emitted_document():
    doc = {
        "schema_version": 2,
        "persistence": {"default": "in_memory", "format": "jsonl"},
        "groups": {"noop": {"body": [{"wait": {"duration": "1s"}}]}},
        "blocks": [{"wait": {"duration": "1s"}}],
    }
    out = workflow_to_dict(workflow_from_dict(doc))
    assert "roles" not in out
    assert list(out["groups"]["noop"]) == ["body"]
    assert out == doc
```

- [ ] **Step 2: Run it and watch it fail**

```
.venv/bin/python -m pytest tests/test_experiment_serialize_v2.py::test_schema_version_is_two -v
```

Expected:

```
___________________________ test_schema_version_is_two _________________________

    def test_schema_version_is_two():
>       assert SCHEMA_VERSION == 2
E       assert 1 == 2

tests/test_experiment_serialize_v2.py:20: AssertionError
=========================== short test summary info ============================
FAILED tests/test_experiment_serialize_v2.py::test_schema_version_is_two - assert 1 == 2
============================== 1 failed in 0.03s ===============================
```

- [ ] **Step 3: Thread `roles` through the block builders**

In `src/lab_devices/experiment/serialize.py`, extend the imports (lines 11–21):

```python
from typing import Any, Callable, cast

from lab_devices.experiment.errors import ExpressionError, UnknownRoleError, WorkflowLoadError
from lab_devices.experiment.registry import DEVICE_TYPES, lookup
from lab_devices.experiment.workflow import (
    REFERENCE_KINDS,
    VALUE_KINDS,
    Defaults,
    Group,
    LocalDecl,
    Metadata,
    ParamDecl,
    ParamKind,
    Persistence,
    RoleDecl,
    StreamDecl,
    Workflow,
)
```

Set `SCHEMA_VERSION = 2` (line 23) and add beside it:

```python
_PARAM_KINDS: frozenset[str] = VALUE_KINDS | REFERENCE_KINDS
_PARAM_DECL_KEYS = frozenset({"name", "kind", "device_type"})
_LOCAL_DECL_KEYS = frozenset({"kind", "init", "units", "persistence"})
_LOCAL_KINDS = ("stream", "binding")
```

Replace `_children` (lines 34–37):

```python
def _children(raw: Any, ctx: str, roles: dict[str, RoleDecl]) -> list[B.Block]:
    if not isinstance(raw, list):
        raise WorkflowLoadError(f"{ctx} must be a list")
    return [block_from_dict(c, roles) for c in raw]
```

Replace `_command`/`_measure` (lines 127–143) and add the resolver above them:

```python
def _device_type(device: str, roles: dict[str, RoleDecl], ctx: str) -> str | None:
    """Role name -> declared device type (design 2026-07-20 §5.2). None means 'defer':
    an unexpanded `{hole}` is not a name yet, so the lookup waits for expansion."""
    if "{" in device:
        return None
    if device not in roles:
        raise UnknownRoleError(
            f"{ctx} names undeclared role {device!r}; declare it under the workflow's "
            f"'roles' section (design 2026-07-20 §5.1). Declared roles: {sorted(roles)}"
        )
    return roles[device].type


def _command(body: Any, timing: dict[str, Any], roles: dict[str, RoleDecl]) -> B.Block:
    device = _str(_req(body, "device", "command"), "command device")
    verb = _req(body, "verb", "command")
    dtype = _device_type(device, roles, "command device")
    if dtype is not None:
        lookup(dtype, verb)
    return B.Command(device=device, verb=verb, params=_checked_params(body, "command"), **timing)


def _measure(body: Any, timing: dict[str, Any], roles: dict[str, RoleDecl]) -> B.Block:
    device = _str(_req(body, "device", "measure"), "measure device")
    verb = body.get("verb", "measure")
    dtype = _device_type(device, roles, "measure device")
    if dtype is not None:
        lookup(dtype, verb)
    return B.Measure(
        device=device, verb=verb, into=_req(body, "into", "measure"),
        params=_checked_params(body, "measure"), **timing,
    )
```

Every remaining builder (`_compute`, `_record`, `_abort`, `_alarm`, `_operator_input`, `_wait`, `_serial`, `_parallel`, `_loop`, `_branch`, `_group_ref`, `_for_each`, lines 146–242) gains the same third parameter so `_BUILDERS` stays uniformly typed. Leaf builders ignore it; the four container builders forward it:

```python
def _compute(body: Any, timing: dict[str, Any], roles: dict[str, RoleDecl]) -> B.Block:
```
```python
def _serial(body: Any, timing: dict[str, Any], roles: dict[str, RoleDecl]) -> B.Block:
    children = _children(_req(body, "children", "serial"), "serial.children", roles)
    return B.Serial(children=children, **timing)


def _parallel(body: Any, timing: dict[str, Any], roles: dict[str, RoleDecl]) -> B.Block:
    return B.Parallel(
        children=_children(_req(body, "children", "parallel"), "parallel.children", roles),
        **timing,
    )
```
```python
        body=_children(_req(body, "body", "loop"), "loop.body", roles),        # in _loop
```
```python
    then = _children(_req(body, "then", "branch"), "branch.then", roles)       # in _branch
    else_ = _children(body["else"], "branch.else", roles) if "else" in body else None
```
```python
    children = _children(_req(body, "body", "for_each"), "for_each.body", roles)  # _for_each
```

Retype `_BUILDERS` (line 245) and `block_from_dict`'s tail (lines 263, 285):

```python
_BUILDERS: dict[str, Callable[[Any, dict[str, Any], dict[str, RoleDecl]], B.Block]] = {
```
```python
def block_from_dict(d: Any, roles: dict[str, RoleDecl] | None = None) -> B.Block:
    """Parse one block. `roles` supplies the declarations a `device:` field resolves
    against; omitting it means 'no roles declared' (design 2026-07-20 §5.3)."""
    roles = {} if roles is None else roles
```
```python
    return builder(d[key], timing, roles)
```

- [ ] **Step 4: Add the declaration parsers**

Add above `workflow_from_dict`:

```python
def _param_decls(raw: Any, ctx: str) -> list[ParamDecl]:
    """`params` is an ORDERED list of typed objects (design 2026-07-20 §2.1)."""
    if not isinstance(raw, list):
        raise WorkflowLoadError(f"{ctx} params must be a list of objects")
    out: list[ParamDecl] = []
    for i, item in enumerate(raw):
        where = f"{ctx} params[{i}]"
        p = _obj(item, where)
        unknown = sorted(set(p) - _PARAM_DECL_KEYS)
        if unknown:
            raise WorkflowLoadError(f"{where}: unknown key(s) {unknown}")
        name = _str(_req(p, "name", where), f"{where} name")
        kind = _str(_req(p, "kind", where), f"{where} kind")
        if kind not in _PARAM_KINDS:
            raise WorkflowLoadError(
                f"{ctx} param {name!r}: unknown kind {kind!r}; expected one of "
                f"{sorted(_PARAM_KINDS)}"
            )
        dtype = p.get("device_type")
        if kind == "role":
            if dtype is None:
                raise WorkflowLoadError(
                    f"{ctx} param {name!r}: kind 'role' requires 'device_type'"
                )
            dtype = _str(dtype, f"{ctx} param {name!r} device_type")
            if dtype not in DEVICE_TYPES:
                raise WorkflowLoadError(
                    f"{ctx} param {name!r}: unknown device type {dtype!r}; known types "
                    f"are {sorted(DEVICE_TYPES)}"
                )
        elif dtype is not None:
            raise WorkflowLoadError(
                f"{ctx} param {name!r}: 'device_type' is only allowed on kind 'role'"
            )
        out.append(ParamDecl(name=name, kind=cast(ParamKind, kind), device_type=dtype))
    return out


def _local_decls(raw: Any, ctx: str) -> dict[str, LocalDecl]:
    """`locals` are the streams and bindings a group owns (design 2026-07-20 §2.2)."""
    out: dict[str, LocalDecl] = {}
    for name, item in _obj(raw, f"{ctx} locals").items():
        where = f"{ctx} local {name!r}"
        local = _obj(item, where)
        unknown = sorted(set(local) - _LOCAL_DECL_KEYS)
        if unknown:
            raise WorkflowLoadError(f"{where}: unknown key(s) {unknown}")
        kind = _str(_req(local, "kind", where), f"{where} kind")
        if kind not in _LOCAL_KINDS:
            raise WorkflowLoadError(
                f"{where}: kind must be 'stream' or 'binding', got {kind!r} -- a local "
                f"value would just be a constant, which compute already expresses"
            )
        init = local.get("init")
        units = local.get("units")
        persistence = local.get("persistence")
        if kind == "binding":
            for key, value in (("units", units), ("persistence", persistence)):
                if value is not None:
                    raise WorkflowLoadError(
                        f"{where}: {key!r} is only allowed on kind 'stream'"
                    )
            if init is not None:
                init = _checked_expr(init, f"{where} init")
        else:
            if init is not None:
                raise WorkflowLoadError(f"{where}: 'init' is only allowed on kind 'binding'")
            if units is not None:
                units = _str(units, f"{where} units")
            if persistence is not None:
                persistence = _str(persistence, f"{where} persistence")
        out[name] = LocalDecl(
            kind=cast("Literal['stream', 'binding']", kind), init=init, units=units,
            persistence=persistence,
        )
    return out
```

Add `Literal` to the `typing` import for that cast.

- [ ] **Step 5: Restructure `workflow_from_dict`**

Replace lines 374–423 wholesale. `roles` is now a local built before any block exists, and `blocks` moves out of the constructor call:

```python
def workflow_from_dict(d: Any) -> Workflow:
    if not isinstance(d, dict):
        raise WorkflowLoadError("workflow must be an object")
    version = d.get("schema_version")
    if not isinstance(version, int) or isinstance(version, bool) or version != SCHEMA_VERSION:
        raise WorkflowLoadError(
            f"unsupported schema_version {version!r}; expected {SCHEMA_VERSION}. Workflows "
            f"using groups or for_each cannot be migrated automatically: their param types "
            f"were never recorded in v1 (design 2026-07-20 §7)"
        )
    md = _obj(d.get("metadata", {}), "metadata")
    metadata = Metadata(
        name=md.get("name"), author=md.get("author"), description=md.get("description")
    )
    pd = _obj(d.get("persistence", {}), "persistence")
    persistence = Persistence(
        default=pd.get("default", "in_memory"), format=pd.get("format", "jsonl")
    )
    dd = _obj(d.get("defaults", {}), "defaults")
    for key in dd:
        if key not in _DEFAULTS_KEYS:
            if key == "on_error":
                raise WorkflowLoadError(
                    "defaults.on_error is not allowed: a blanket on_error would silently "
                    "tolerate every failure (e.g. a missed drug injection) instead of just "
                    "the ones an author reviewed block by block; set on_error on the "
                    "individual blocks that should tolerate failure instead"
                )
            raise WorkflowLoadError(f"defaults: unknown key {key!r}")
    defaults = Defaults(
        retry=_retry(dd["retry"], "defaults.retry") if "retry" in dd else None
    )
    # roles BEFORE blocks (design 2026-07-20 §5.3): a `device:` field holds a ROLE name, and
    # _command/_measure resolve it to a device type for the parse-time registry lookup. Parsed
    # inside the Workflow(...) call, as blocks were, that type would not exist yet.
    roles: dict[str, RoleDecl] = {}
    for name, rv in _obj(d.get("roles", {}), "roles").items():
        r = _obj(rv, f"role {name!r}")
        rtype = _str(_req(r, "type", f"role {name!r}"), f"role {name!r} type")
        if rtype not in DEVICE_TYPES:
            raise WorkflowLoadError(
                f"role {name!r}: unknown device type {rtype!r}; known types are "
                f"{sorted(DEVICE_TYPES)}"
            )
        device = r.get("device")
        if device is not None:
            device = _str(device, f"role {name!r} device")
        roles[name] = RoleDecl(type=rtype, device=device)
    streams: dict[str, StreamDecl] = {}
    for name, sv in _obj(d.get("streams", {}), "streams").items():
        s = _obj(sv, f"stream {name!r}")
        streams[name] = StreamDecl(units=s.get("units"), persistence=s.get("persistence"))
    groups: dict[str, Group] = {}
    for name, gv in _obj(d.get("groups", {}), "groups").items():
        g = _obj(gv, f"group {name!r}")
        groups[name] = Group(
            name=name,
            body=_children(g.get("body", []), f"groups.{name}.body", roles),
            params=_param_decls(g.get("params", []), f"group {name!r}"),
            locals=_local_decls(g.get("locals", {}), f"group {name!r}"),
        )
    blocks = _children(d.get("blocks", []), "blocks", roles)
    return Workflow(
        schema_version=version, blocks=blocks, metadata=metadata, persistence=persistence,
        streams=streams, groups=groups, roles=roles, defaults=defaults,
    )
```

- [ ] **Step 6: Emit `roles`, typed params, and locals in contract key order**

Add the two dumpers above `workflow_to_dict`:

```python
def _param_decl_to_dict(p: ParamDecl) -> dict[str, Any]:
    body: dict[str, Any] = {"name": p.name, "kind": p.kind}
    if p.device_type is not None:
        body["device_type"] = p.device_type
    return body


def _local_decl_to_dict(local: LocalDecl) -> dict[str, Any]:
    body: dict[str, Any] = {"kind": local.kind}
    for key, value in (("init", local.init), ("units", local.units),
                       ("persistence", local.persistence)):
        if value is not None:
            body[key] = value
    return body
```

In `workflow_to_dict`, insert the `roles` block immediately before the `streams` block (i.e. after the `defaults` block at line 438) and replace the transitional groups emitter from Task 1:

```python
    if w.roles:
        out["roles"] = {
            name: ({"type": r.type} if r.device is None
                   else {"type": r.type, "device": r.device})
            for name, r in w.roles.items()
        }
```
```python
    if w.groups:
        groups_out: dict[str, Any] = {}
        for name, g in w.groups.items():
            body: dict[str, Any] = {}
            if g.params:
                body["params"] = [_param_decl_to_dict(p) for p in g.params]
            if g.locals:
                body["locals"] = {
                    ln: _local_decl_to_dict(local) for ln, local in g.locals.items()
                }
            body["body"] = [block_to_dict(c) for c in g.body]
            groups_out[name] = body
        out["groups"] = groups_out
```

- [ ] **Step 7: Run the new test file green**

```
.venv/bin/python -m pytest tests/test_experiment_serialize_v2.py -v
```

Expected: `33 passed`, including `test_roles_parse_before_blocks_so_a_role_resolves_to_a_device_type PASSED`, `test_emitted_key_order_puts_roles_immediately_before_streams PASSED`, and `test_v2_document_round_trips_byte_for_byte PASSED`.

- [ ] **Step 8: Migrate the two owned test files and the shared helpers**

Create `tests/experiment_role_helpers.py`:

```python
"""Test-only role synthesis. Engine tests name devices by the core id convention; v2
requires a declaration for each. This derives one so the suites keep loading -- it is
NOT the engine's rule, which reads workflow.roles[name].type and nothing else."""

from typing import Any

from lab_devices.experiment.registry import DEVICE_TYPES


def auto_roles(doc: Any) -> dict[str, dict[str, str]]:
    """Declare a role for every literal `device` name in `doc`, typed by its id suffix.
    Names whose suffix is not a known device type are skipped, so negative tests that
    target an unknown type still reach the diagnostic they were written for."""
    found: dict[str, dict[str, str]] = {}

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            device = node.get("device")
            if isinstance(device, str) and "{" not in device:
                dtype = device.rsplit("_", 1)[0]
                if dtype in DEVICE_TYPES:
                    found[device] = {"type": dtype}
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(doc)
    return found
```

In `tests/experiment_validate_helpers.py`, replace `wf` (lines 9–15):

```python
def wf(blocks, streams=None, groups=None, roles=None):
    doc = {
        "schema_version": 2,
        "streams": {name: {} for name in (streams or [])},
        "groups": groups or {},
        "blocks": blocks,
    }
    doc["roles"] = auto_roles(doc) if roles is None else roles
    return workflow_from_dict(doc)
```

and add `from tests.experiment_role_helpers import auto_roles` to its imports.

In `tests/experiment_run_helpers.py`, replace `make_workflow`'s body (lines 20–29):

```python
    doc: dict[str, Any] = {"schema_version": 2, "blocks": blocks}
    if streams is not None:
        doc["streams"] = streams
    if groups is not None:
        doc["groups"] = groups
    if persistence is not None:
        doc["persistence"] = persistence
    doc["roles"] = auto_roles(doc)
    workflow = workflow_from_dict(doc)
    assign_block_ids(workflow)
    return workflow
```

with the same import added.

Then migrate the two owned test files:

```
sed -i '' 's/"schema_version": 1,/"schema_version": 2,/g' \
    tests/test_experiment_serialize.py tests/test_experiment_workflow.py
sed -i '' -E 's/block_from_dict\((\{[^;]*)\)$/block_from_dict(\1, ROLES)/' \
    tests/test_experiment_serialize.py
```

The `sed` for `block_from_dict` catches only the single-line calls; fix the multi-line ones by hand (`test_measure_and_loop_nesting`, `test_branch_if_else_keyword_mapping`, `test_multiple_type_keys_rejected`, `test_malformed_params_rejected`, `test_missing_required_fields_rejected`, `test_block_round_trip`) and add to the top of `tests/test_experiment_serialize.py`:

```python
from lab_devices.experiment.workflow import RoleDecl

ROLES = {
    "pump_1": RoleDecl(type="pump"),
    "pump_2": RoleDecl(type="pump"),
    "valve_1": RoleDecl(type="valve"),
    "densitometer_1": RoleDecl(type="densitometer"),
}
_ROLES_DOC = {name: {"type": r.type} for name, r in ROLES.items()}
```

Every `workflow_from_dict({...})` literal in both files gains `"roles": _ROLES_DOC,` (in `test_experiment_workflow.py`, `"roles"` must sit between `"persistence"` and `"streams"` in `EXAMPLE`, since that test asserts an exact round trip). Update `test_bad_schema_version_rejected` to use `99`, and the `test_malformed_workflow_sections_rejected` parametrize list to `"schema_version": 2` throughout plus two new rows:

```python
    {"schema_version": 2, "roles": ["pump_1"], "blocks": []},
    {"schema_version": 2, "roles": {"pump_1": "pump"}, "blocks": []},
```

- [ ] **Step 9: Run the gate and confirm the residual red set is only what later tasks own**

```
.venv/bin/python -m pytest tests/test_experiment_serialize_v2.py \
    tests/test_experiment_serialize.py tests/test_experiment_workflow.py \
    tests/test_experiment_registry.py tests/test_experiment_param_types.py -q
.venv/bin/python -m mypy src/lab_devices
.venv/bin/python -m ruff check .
awk 'length>100 {print FILENAME": "FNR}' src/lab_devices/experiment/serialize.py \
    tests/test_experiment_serialize_v2.py tests/experiment_role_helpers.py
```

Expected: the five files report `N passed` with zero failures; mypy `Success: no issues found`; ruff `All checks passed!`; `awk` silent.

Then enumerate what is still red:

```
.venv/bin/python -m pytest -q 2>&1 | tail -40
```

Expected: failures confined to `test_experiment_expand*.py`, `test_experiment_foreach_*.py`, `test_experiment_validate_groups.py`, and `test_examples_morbidostat.py` — the untyped-`params`, scalar-`for_each`, and un-migrated-example suites that the expansion and validation tasks own (design §8: ~52 tests needing semantic rewrites). **Any failure outside those files is a regression from this task, not expected churn** — fix it before committing. Record the exact failing-test count in the commit body so the next task has a baseline to shrink.

- [ ] **Step 10: Commit**

```
git add src/lab_devices/experiment/serialize.py tests/test_experiment_serialize_v2.py \
        tests/test_experiment_serialize.py tests/test_experiment_workflow.py \
        tests/experiment_role_helpers.py tests/experiment_validate_helpers.py \
        tests/experiment_run_helpers.py
git commit -m "feat(experiment)!: schema_version 2 with roles, typed group params, and locals

roles parse before blocks and thread into _command/_measure so a role name resolves to a
device type at parse time (design 2026-07-20 §5.3). v1 documents are rejected with a
message naming why they cannot be migrated. Expansion suites remain red pending the
typed-substitution task."
```agentId: a9e81d0fc3719da1a (use SendMessage with to: 'a9e81d0fc3719da1a', summary: '<5-10 word recap>' to continue this agent)
<usage>subagent_tokens: 113457
tool_uses: 22
duration_ms: 460176</usage>

---

### Task 4: Kind-aware substitution

**Files:**
- Modify: `src/lab_devices/experiment/expand.py:1-19` (imports, `Env` alias, `_IDENT_RE`)
- Modify: `src/lab_devices/experiment/expand.py:29-55` (`_fmt` kept, `_interpolate`/`_substitute` rewritten)
- Modify: `src/lab_devices/experiment/expand.py:95-118` (`_envs` gets a temporary kind-inferring shim so the tree stays green until Task 6)
- Modify: `src/lab_devices/experiment/expand.py:206-250` (`_expand_group_ref` binds typed args)
- Modify: `tests/test_experiment_expand.py:7-12, 38-48, 50-61, 72-93, 117-129` (typed `params`, typed substitution assertions)
- Modify: `tests/test_experiment_expand_trace.py:70-105` (typed `params` in the two group fixtures)

**Interfaces:**

Consumes (landed in Tasks 1–3):
```python
from lab_devices.experiment.workflow import REFERENCE_KINDS, VALUE_KINDS, Workflow
# VALUE_KINDS: frozenset({"int", "number", "bool", "string"})
# REFERENCE_KINDS: frozenset({"role", "stream", "binding"})
```

Produces:
```python
Env = dict[str, tuple[str, Any]]  # name -> (kind, value); reference kinds carry the NAME as str

def _fmt(value: Any) -> str: ...                                    # unchanged
def _ident(value: Any) -> bool: ...
def _kind_ok(kind: str, value: Any) -> bool: ...
def _decls(raw: Any, where: str) -> list[tuple[str, str]]: ...
def _bind(decls: list[tuple[str, str]], supplied: dict[str, Any], where: str) -> Env: ...
def _interpolate(text: str, env: Env) -> Any: ...
def _substitute(node: Any, env: Env) -> Any: ...
def _infer_kind(value: Any) -> str: ...   # TEMPORARY shim, deleted in Task 6
```

- [ ] **Step 1: Write the failing test**

Add to `tests/test_experiment_expand.py` (top of file, after the existing `_wf` helper — and change `_wf` to emit `schema_version` 2):

```python
from lab_devices.experiment.expand import _substitute, expand_dict


def _wf(blocks, groups=None):
    d = {"schema_version": 2, "blocks": blocks}
    if groups is not None:
        d["groups"] = groups
    return d


def test_whole_string_value_hole_substitutes_a_typed_json_value():
    env = {"tube": ("int", 1), "gain": ("number", 2.5), "on": ("bool", True),
           "tag": ("string", "a")}
    node = {"position": "{tube}", "gain": "{gain}", "on": "{on}", "tag": "{tag}"}
    assert _substitute(node, env) == {"position": 1, "gain": 2.5, "on": True, "tag": "a"}


def test_whole_string_reference_hole_substitutes_the_name_string():
    env = {"od": ("stream", "od_1"), "meter": ("role", "od_meter_1"),
           "c": ("binding", "tube_1_c")}
    node = {"into": "{od}", "device": "{meter}", "value": "{c}"}
    assert _substitute(node, env) == {"into": "od_1", "device": "od_meter_1",
                                      "value": "tube_1_c"}


def test_embedded_value_hole_stringifies_via_fmt():
    env = {"tube": ("int", 2), "gain": ("number", 3.0), "on": ("bool", False)}
    node = ["tube {tube}: service", "g={gain}", "flag={on}", "{tube}{tube}"]
    assert _substitute(node, env) == ["tube 2: service", "g=3", "flag=false", "22"]


def test_reference_hole_glued_to_identifier_text_is_a_load_error():
    env = {"od": ("stream", "od_1")}
    for glued in ("od_{od}", "{od}_raw"):
        with pytest.raises(WorkflowLoadError, match="whole identifier"):
            _substitute({"into": glued}, env)


def test_reference_hole_inside_an_expression_is_legal():
    # The rule forbids CONCATENATION, not embedding: a stream reference legitimately sits
    # inside a larger expression string, which is where most of them live (design §3).
    env = {"od": ("stream", "od_1")}
    node = {"value": "count({od}, last=11min) > 0 and mean({od}, last=11min) > 2.0"}
    assert _substitute(node, env) == {
        "value": "count(od_1, last=11min) > 0 and mean(od_1, last=11min) > 2.0"
    }


def test_hole_absent_from_the_env_passes_through_untouched():
    # Increment 7 order-independence: an outer for_each/args pass, or the residual-hole
    # scan, owns this hole -- substitution must not consume or reject it.
    env = {"tube": ("int", 1)}
    assert _substitute({"into": "{od}", "d": "x_{tube}_{other}"}, env) == {
        "into": "{od}", "d": "x_1_{other}"}


def test_group_args_are_bound_by_declared_kind():
    out = expand_dict(_wf(
        [{"group_ref": {"name": "svc",
                        "args": {"tube": 3, "od": "od_3", "label": "left"}}}],
        groups={"svc": {"params": [{"name": "tube", "kind": "int"},
                                   {"name": "od", "kind": "stream"},
                                   {"name": "label", "kind": "string"}],
                        "body": [{"command": {"device": "valve_1", "verb": "set_position",
                                              "params": {"position": "{tube}"},
                                              }, "label": "{label} {tube}"},
                                 {"record": {"into": "{od}", "value": "1"}}]}},
    ))
    kids = out["blocks"][0]["serial"]["children"]
    assert kids[0]["command"]["params"]["position"] == 3   # int, not "3"
    assert kids[0]["label"] == "left 3"
    assert kids[1]["record"]["into"] == "od_3"


def test_group_arg_of_the_wrong_json_type_is_a_load_error():
    with pytest.raises(WorkflowLoadError, match="expects kind 'int'"):
        expand_dict(_wf([{"group_ref": {"name": "svc", "args": {"tube": "two"}}}],
                        groups={"svc": {"params": [{"name": "tube", "kind": "int"}],
                                        "body": []}}))


def test_group_arg_bool_is_not_an_int():
    with pytest.raises(WorkflowLoadError, match="expects kind 'int'"):
        expand_dict(_wf([{"group_ref": {"name": "svc", "args": {"tube": True}}}],
                        groups={"svc": {"params": [{"name": "tube", "kind": "int"}],
                                        "body": []}}))


def test_missing_group_arg_is_reported_per_param():
    with pytest.raises(WorkflowLoadError, match="missing 'od' \\(kind 'stream'\\)"):
        expand_dict(_wf([{"group_ref": {"name": "svc", "args": {"tube": 1}}}],
                        groups={"svc": {"params": [{"name": "tube", "kind": "int"},
                                                   {"name": "od", "kind": "stream"}],
                                        "body": []}}))


def test_extra_group_arg_is_reported_per_param():
    with pytest.raises(WorkflowLoadError, match="unknown name 'nope'"):
        expand_dict(_wf([{"group_ref": {"name": "svc", "args": {"tube": 1, "nope": 2}}}],
                        groups={"svc": {"params": [{"name": "tube", "kind": "int"}],
                                        "body": []}}))
```

Update the existing tests in the same file that the typed rules change:

```python
def test_object_items_multi_field():
    out = expand_dict(_wf([
        {"for_each": {"in": [{"t": 1, "p": 7}, {"t": 2, "p": 8}],
                      "body": [{"command": {"device": "valve_{t}", "verb": "set_position",
                                            "params": {"position": "{p}"}}}]}}
    ]))
    cmds = out["blocks"]
    assert cmds[0]["command"]["device"] == "valve_1"
    assert cmds[0]["command"]["params"]["position"] == 7  # typed value hole (design §3.1)
    assert cmds[1]["command"]["device"] == "valve_2"


def test_parametrized_group_ref_inlines_as_serial_carrying_on_error():
    out = expand_dict(_wf(
        [{"group_ref": {"name": "svc", "args": {"t": 2}}}, ],
        groups={"svc": {"params": [{"name": "t", "kind": "int"}],
                        "body": [{"measure": {"device": "densitometer_{t}",
                                              "verb": "measure", "into": "od_{t}"}}]}},
    ))
    del out
    out = expand_dict(_wf(
        [{"group_ref": {"name": "svc", "args": {"t": 2}}, "on_error": "continue"}],
        groups={"svc": {"params": [{"name": "t", "kind": "int"}],
                        "body": [{"measure": {"device": "densitometer_{t}",
                                              "verb": "measure", "into": "od_{t}"}}]}},
    ))
    wrap = out["blocks"][0]
    assert wrap["on_error"] == "continue"
    assert wrap["serial"]["children"][0]["measure"]["device"] == "densitometer_2"
    assert "groups" not in out  # parametrized group dropped after inlining


def test_for_each_over_group_ref_composition():
    out = expand_dict(_wf(
        [{"for_each": {"var": "t", "in": [1, 2, 3],
                       "body": [{"group_ref": {"name": "svc", "args": {"t": "{t}"}}}]}}],
        groups={"svc": {"params": [{"name": "t", "kind": "int"}],
                        "body": [{"measure": {"device": "densitometer_{t}",
                                              "verb": "measure", "into": "od_{t}"}}]}},
    ))
    devs = [b["serial"]["children"][0]["measure"]["device"] for b in out["blocks"]]
    assert devs == ["densitometer_1", "densitometer_2", "densitometer_3"]


def test_arity_mismatch_raises():
    with pytest.raises(WorkflowLoadError, match="missing 't'"):
        expand_dict(_wf([{"group_ref": {"name": "svc", "args": {"x": 1}}}],
                        groups={"svc": {"params": [{"name": "t", "kind": "int"}],
                                        "body": []}}))


def test_parametrized_group_body_may_contain_for_each():
    inner_cmd = {"command": {"device": "valve_{valve}", "verb": "set_position",
                             "params": {"position": "{valve}", "ml": "{volume}"}}}
    out = expand_dict(_wf(
        [{"group_ref": {"name": "dose", "args": {"volume": 5}}}],
        groups={"dose": {"params": [{"name": "volume", "kind": "int"}],
                         "body": [{"for_each": {"var": "valve", "in": [1, 2],
                                                "body": [inner_cmd]}}]}},
    ))
    cmds = out["blocks"][0]["serial"]["children"]
    assert [c["command"]["device"] for c in cmds] == ["valve_1", "valve_2"]
    assert [c["command"]["params"]["position"] for c in cmds] == [1, 2]
    assert [c["command"]["params"]["ml"] for c in cmds] == [5, 5]
```

Simplify `test_parametrized_group_ref_inlines_as_serial_carrying_on_error` to just the second half (the `del out` scaffolding above is redundant — keep only the `on_error` variant):

```python
def test_parametrized_group_ref_inlines_as_serial_carrying_on_error():
    out = expand_dict(_wf(
        [{"group_ref": {"name": "svc", "args": {"t": 2}}, "on_error": "continue"}],
        groups={"svc": {"params": [{"name": "t", "kind": "int"}],
                        "body": [{"measure": {"device": "densitometer_{t}",
                                              "verb": "measure", "into": "od_{t}"}}]}},
    ))
    wrap = out["blocks"][0]
    assert wrap["on_error"] == "continue"
    assert wrap["serial"]["children"][0]["measure"]["device"] == "densitometer_2"
    assert "groups" not in out  # parametrized group dropped after inlining
```

In `tests/test_experiment_expand_trace.py`, retype the two group fixtures (bodies otherwise unchanged):

```python
        "groups": {"service": {"params": [{"name": "tube", "kind": "int"}],
                               "body": [{"wait": {"duration": "{tube}s"}}]}},
```
```python
            "svc": {
                "params": [{"name": "tube", "kind": "int"}],
```

- [ ] **Step 2: Run and watch it fail**

```
.venv/bin/python -m pytest tests/test_experiment_expand.py -v
```

Expected — the new unit tests fail on the import, and every typed test fails because `params` is now a list of dicts:

```
ImportError while loading conftest ... no
E   ImportError: cannot import name '_substitute' from 'lab_devices.experiment.expand'
```

After the import exists but before the rewrite (run the file again once `_substitute` is exported unchanged), the substitution tests fail as:

```
FAILED tests/test_experiment_expand.py::test_whole_string_value_hole_substitutes_a_typed_json_value
  - TypeError: 'tuple' object ... AssertionError: assert {'position': "('int', 1)"} == {'position': 1}
FAILED tests/test_experiment_expand.py::test_embedded_reference_hole_is_a_load_error
  - Failed: DID NOT RAISE <class 'lab_devices.experiment.errors.WorkflowLoadError'>
FAILED tests/test_experiment_expand.py::test_group_args_are_bound_by_declared_kind
  - TypeError: unhashable type: 'dict'
FAILED tests/test_experiment_expand.py::test_missing_group_arg_is_reported_per_param
  - TypeError: unhashable type: 'dict'
```

(`set(args) != set(params)` at `expand.py:232` is what raises `TypeError: unhashable type: 'dict'` — the old untyped arity check cannot see typed declarations at all.)

- [ ] **Step 3: Minimal implementation**

In `src/lab_devices/experiment/expand.py`, replace lines 1–19's import block and add the new primitives:

```python
"""for_each / parametrized-group expansion (design 2026-07-15 §4, 2026-07-20 §3)."""

from __future__ import annotations

import copy
import re
from typing import Any

from lab_devices.experiment.errors import WorkflowLoadError
from lab_devices.experiment.serialize import (
    _BLOCK_KEYS,
    workflow_from_dict,
    workflow_to_dict,
)
from lab_devices.experiment.workflow import REFERENCE_KINDS, VALUE_KINDS, Workflow

# name -> (kind, value). Reference kinds carry the resolved NAME as a str.
Env = dict[str, tuple[str, Any]]

_HOLE_RE = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")
# Mirrors validate.py:256. Not imported: validate.py imports expand.py, so the dependency
# would be circular.
_IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
_ALL_KINDS = VALUE_KINDS | REFERENCE_KINDS
_EXPANSION_CAP = 10_000
_MAX_DEPTH = 64
```

(keep `_CHILD_LISTS` and `_FOR_EACH_FORBIDDEN` as they are)

Replace lines 29–55 (`_fmt` unchanged, `_interpolate`/`_substitute` rewritten) and add the binding helpers:

```python
def _fmt(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return str(int(value)) if value.is_integer() else repr(value)
    return str(value)


def _ident(value: Any) -> bool:
    return isinstance(value, str) and _IDENT_RE.fullmatch(value) is not None


def _kind_ok(kind: str, value: Any) -> bool:
    """JSON type of `value` against `kind` (design 2026-07-20 §2)."""
    if kind == "bool":
        return isinstance(value, bool)
    if kind == "int":
        return isinstance(value, int) and not isinstance(value, bool)
    if kind == "number":
        return isinstance(value, int | float) and not isinstance(value, bool)
    return isinstance(value, str)  # "string" and every reference kind carry a str


def _decls(raw: Any, where: str) -> list[tuple[str, str]]:
    """Read a `params`/`vars` list of ParamDecl objects into ordered (name, kind) pairs.

    expand_dict runs on raw JSON, before workflow_from_dict, so it cannot reuse the
    ParamDecl parsing in serialize.py -- it needs its own tolerant read of the same shape.
    """
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise WorkflowLoadError(f"{where} must be a list of declarations")
    out: list[tuple[str, str]] = []
    for item in raw:
        if not isinstance(item, dict):
            raise WorkflowLoadError(f"{where} entries must be objects, got {item!r}")
        name, kind = item.get("name"), item.get("kind")
        if not isinstance(name, str) or not isinstance(kind, str) or kind not in _ALL_KINDS:
            raise WorkflowLoadError(f"{where} entry {item!r} needs a 'name' and a valid 'kind'")
        out.append((name, kind))
    return out


def _bind(decls: list[tuple[str, str]], supplied: dict[str, Any], where: str) -> Env:
    """Exact-name match plus a per-cell kind check. Shared by group args and for_each rows."""
    declared = [n for n, _ in decls]
    extra = sorted(set(supplied) - set(declared))
    if extra:
        raise WorkflowLoadError(f"{where}: unknown name {extra[0]!r}; declared {declared}")
    env: Env = {}
    for name, kind in decls:
        if name not in supplied:
            raise WorkflowLoadError(f"{where}: missing {name!r} (kind {kind!r})")
        value = supplied[name]
        if not _kind_ok(kind, value):
            raise WorkflowLoadError(f"{where}: {name!r} expects kind {kind!r}, got {value!r}")
        env[name] = (kind, value)
    return env


_IDENT_CHAR_RE = re.compile(r"[A-Za-z0-9_]")


def _glued(text: str, m: re.Match[str]) -> bool:
    """True if a hole abuts identifier text, i.e. it would manufacture a name instead of
    referring to a declared one. `count({od}, last=5)` is fine -- `(` and `,` delimit it;
    `od_{od}` and `{od}_raw` are not (design 2026-07-20 §3)."""
    before = text[m.start() - 1] if m.start() > 0 else ""
    after = text[m.end()] if m.end() < len(text) else ""
    return bool(_IDENT_CHAR_RE.match(before) or _IDENT_CHAR_RE.match(after))


def _interpolate(text: str, env: Env) -> Any:
    """Substitute holes in one string (design 2026-07-20 §3). May return a non-string."""
    whole = _HOLE_RE.fullmatch(text)
    if whole is not None:
        name = whole.group(1)
        if name not in env:
            return text  # leave for an outer for_each/args pass, or the residual scan
        kind, value = env[name]
        if kind in VALUE_KINDS:
            return value  # typed JSON value: an int stays an int (design §3.1)
        return value  # reference kinds already carry the resolved name as a str

    def sub(m: re.Match[str]) -> str:
        name = m.group(1)
        if name not in env:
            return m.group(0)  # order-independence: not ours to bind
        kind, value = env[name]
        if kind in REFERENCE_KINDS and _glued(text, m):
            raise WorkflowLoadError(
                f"{kind} param {name!r} may not be concatenated with adjacent identifier text "
                f"in {text!r}: a reference must occupy a whole identifier "
                f"(design 2026-07-20 §3)"
            )
        return _fmt(value)

    return _HOLE_RE.sub(sub, text)


def _substitute(node: Any, env: Env) -> Any:
    """Deep-copy a JSON node, interpolating every string against env."""
    if isinstance(node, str):
        return _interpolate(node, env)
    if isinstance(node, list):
        return [_substitute(x, env) for x in node]
    if isinstance(node, dict):
        return {k: _substitute(v, env) for k, v in node.items()}
    return node
```

Add the temporary shim and rewire `_envs` (lines 95–118) so the untyped `for_each` path keeps working until Task 6 replaces it — every intermediate commit must be green:

```python
def _infer_kind(value: Any) -> str:
    """TEMPORARY bridge for the untyped for_each shorthand. Task 6 deletes this with `_envs`."""
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "number"
    return "string"


def _envs(body: dict[str, Any]) -> list[Env]:
    var = body.get("var")
    raw = body.get("in")
    if not isinstance(raw, list) or not raw:
        raise WorkflowLoadError("for_each 'in' must be a non-empty list")
    out: list[Env] = []
    if var is not None:
        if not isinstance(var, str):
            raise WorkflowLoadError("for_each 'var' must be a string")
        for item in raw:
            if isinstance(item, dict):
                raise WorkflowLoadError("for_each with 'var' requires scalar items")
            out.append({var: (_infer_kind(item), item)})
        return out
    keyset: set[str] | None = None
    for item in raw:
        if not isinstance(item, dict):
            raise WorkflowLoadError("for_each without 'var' requires object items")
        if keyset is None:
            keyset = set(item)
        elif set(item) != keyset:
            raise WorkflowLoadError("for_each object items must share one key set")
        out.append({k: (_infer_kind(v), v) for k, v in item.items()})
    return out
```

Replace the arity check in `_expand_group_ref` (lines 216–239):

```python
def _expand_group_ref(
    block: dict[str, Any],
    groups: dict[str, Any],
    counter: _Counter,
    depth: int,
    trace: dict[str, str],
    src: str,
    dst: str,
    base: int,
) -> list[Any]:
    # Caveat: a group `param` name must not collide with an inner for_each `var` --
    # the param would shadow the loop var (no enforcement here).
    body = block["group_ref"]
    if not isinstance(body, dict):
        trace[f"{dst}[{base}]"] = src
        return [block]
    name = body.get("name")
    raw_args = body.get("args")
    args: dict[str, Any] = raw_args if isinstance(raw_args, dict) else {}
    group = groups.get(name) if isinstance(name, str) else None
    gdict: dict[str, Any] = group if isinstance(group, dict) else {}
    decls = _decls(gdict.get("params"), f"group {name!r} params")
    if not decls and not args:
        trace[f"{dst}[{base}]"] = src
        return [block]  # plain group_ref: preserve the node (lazy inline)
    if group is None:
        raise WorkflowLoadError(f"group_ref {name!r}: unknown group")
    env = _bind(decls, args, f"group_ref {name!r} args")
    raw_body = group.get("body", [])
    if not isinstance(raw_body, list):
        raise WorkflowLoadError(f"group {name!r} body must be a list")
    substituted = [_substitute(b, env) for b in raw_body]
    trace[f"{dst}[{base}]"] = src
    inlined = _expand_blocks(
        substituted, groups, counter, depth + 1, trace,
        f"groups[{name!r}].body", f"{dst}[{base}].children",
    )
    wrapper: dict[str, Any] = {"serial": {"children": inlined}}
    for k in _BLOCK_KEYS:
        if k in block:
            wrapper[k] = copy.deepcopy(block[k])
    counter.bump(1)
    return [wrapper]
```

- [ ] **Step 4: Run to pass**

```
.venv/bin/python -m pytest tests/test_experiment_expand.py tests/test_experiment_expand_trace.py -v
```

Expected:

```
tests/test_experiment_expand.py::test_whole_string_value_hole_substitutes_a_typed_json_value PASSED
tests/test_experiment_expand.py::test_whole_string_reference_hole_substitutes_the_name_string PASSED
tests/test_experiment_expand.py::test_embedded_value_hole_stringifies_via_fmt PASSED
tests/test_experiment_expand.py::test_embedded_reference_hole_is_a_load_error PASSED
tests/test_experiment_expand.py::test_hole_absent_from_the_env_passes_through_untouched PASSED
tests/test_experiment_expand.py::test_group_args_are_bound_by_declared_kind PASSED
tests/test_experiment_expand.py::test_group_arg_of_the_wrong_json_type_is_a_load_error PASSED
tests/test_experiment_expand.py::test_group_arg_bool_is_not_an_int PASSED
tests/test_experiment_expand.py::test_missing_group_arg_is_reported_per_param PASSED
tests/test_experiment_expand.py::test_extra_group_arg_is_reported_per_param PASSED
tests/test_experiment_expand.py::test_object_items_multi_field PASSED
tests/test_experiment_expand.py::test_parametrized_group_body_may_contain_for_each PASSED
...
tests/test_experiment_expand_trace.py::test_parametrized_group_ref_body_traces_into_the_groups_dict PASSED
========================= 24 passed =========================
```

Then the gate:

```
.venv/bin/python -m pytest
.venv/bin/python -m mypy src/lab_devices
.venv/bin/python -m ruff check .
awk 'length>100 {print FILENAME": "FNR}' src/lab_devices/experiment/expand.py tests/test_experiment_expand.py
```

`awk` must print nothing; mypy must report `Success: no issues found`.

- [ ] **Step 5: Commit**

```
git add src/lab_devices/experiment/expand.py tests/test_experiment_expand.py \
        tests/test_experiment_expand_trace.py
git commit -m "feat(experiment)!: kind-aware substitution in expand

Env is now name -> (kind, value). A whole-string value hole substitutes as a
typed JSON value; a whole-string reference hole as its name; an embedded
reference hole is a load error (design 2026-07-20 §3). Group args bind against
typed ParamDecls with per-param arity errors. A hole absent from the running env
still passes through untouched, preserving Increment 7 order-independence."
```

---

### Task 5: Group locals

**Files:**
- Modify: `src/lab_devices/experiment/expand.py:76-86` (`_Counter` becomes `_Expansion`, gaining `seeds`/`streams`/`instances`)
- Modify: `src/lab_devices/experiment/expand.py:121-250` (thread `_Expansion` through `_expand_blocks`/`_expand_block`/`_expand_for_each`/`_expand_group_ref`)
- Modify: `src/lab_devices/experiment/expand.py:258-294` (`expand_dict_traced`: prepend seeds, shift the trace, merge streams, keep groups-with-locals out of the output)
- Create (in expand.py): `_shift_block_traces`, `_open_locals`
- Create: `tests/test_experiment_expand_locals.py`
- Modify: `tests/test_experiment_expand_trace.py` (append the seed-shift trace tests)

**Interfaces:**

Consumes: `Env`, `_substitute`, `_bind`, `_decls`, `_ident` (Task 4); `_expand_blocks`, `_BLOCK_KEYS`.

Produces:
```python
class _Expansion:
    n: int
    seeds: list[tuple[dict[str, Any], str]]   # (hoisted compute block, authored path)
    streams: dict[str, dict[str, Any]]        # qualified name -> StreamDecl JSON
    instances: dict[str, str]                 # qualified `as` -> the group that claimed it
    def bump(self, k: int) -> None: ...

def _shift_block_traces(trace: dict[str, str], k: int) -> dict[str, str]: ...
def _open_locals(gname: str, locals_: dict[str, Any], as_value: Any,
                 exp: _Expansion) -> Env: ...
```

- [ ] **Step 1: Write the failing test**

Create `tests/test_experiment_expand_locals.py`:

```python
"""Group locals: qualified naming, stream emission, init hoisting (design 2026-07-20 §2.2, §6)."""

import pytest

from lab_devices.experiment.errors import WorkflowLoadError
from lab_devices.experiment.expand import expand_dict


def _svc(locals_, body):
    return {"params": [{"name": "tube", "kind": "int"}], "locals": locals_, "body": body}


def test_locals_expand_to_qualified_names():
    out = expand_dict({
        "schema_version": 2,
        "groups": {"svc": _svc(
            {"c": {"kind": "binding"}, "c_series": {"kind": "stream", "units": "ug/mL"}},
            [{"compute": {"into": "{c}", "value": "1"}},
             {"record": {"into": "{c_series}", "value": "{c}"}}],
        )},
        "blocks": [{"group_ref": {"name": "svc", "as": "tube_1", "args": {"tube": 1}}}],
    })
    kids = out["blocks"][0]["serial"]["children"]
    assert kids[0]["compute"]["into"] == "tube_1_c"
    assert kids[1]["record"] == {"into": "tube_1_c_series", "value": "tube_1_c"}


def test_as_interpolates_from_the_call_site_env():
    out = expand_dict({
        "schema_version": 2,
        "groups": {"svc": _svc({"c": {"kind": "binding"}},
                               [{"compute": {"into": "{c}", "value": "{tube}"}}])},
        "blocks": [{"for_each": {"var": "t", "in": [1, 2], "body": [
            {"group_ref": {"name": "svc", "as": "tube_{t}", "args": {"tube": "{t}"}}}]}}],
    })
    intos = [b["serial"]["children"][0]["compute"]["into"] for b in out["blocks"]]
    assert intos == ["tube_1_c", "tube_2_c"]


def test_stream_locals_emit_stream_declarations():
    out = expand_dict({
        "schema_version": 2,
        "groups": {"svc": _svc(
            {"c_series": {"kind": "stream", "units": "ug/mL"},
             "r_series": {"kind": "stream", "units": "1/h", "persistence": "disk"}},
            [{"record": {"into": "{c_series}", "value": "1"}}],
        )},
        "blocks": [{"group_ref": {"name": "svc", "as": "t1", "args": {"tube": 1}}}],
    })
    assert out["streams"] == {"t1_c_series": {"units": "ug/mL"},
                              "t1_r_series": {"units": "1/h", "persistence": "disk"}}


def test_init_seeds_hoist_to_the_front_of_blocks_in_expansion_order():
    out = expand_dict({
        "schema_version": 2,
        "groups": {"svc": _svc(
            {"c": {"kind": "binding", "init": "0"},
             "contaminated": {"kind": "binding", "init": "false"},
             "r": {"kind": "binding"}},
            [{"compute": {"into": "{r}", "value": "{c} + {tube}"}}],
        )},
        "blocks": [{"for_each": {"var": "t", "in": [1, 2], "body": [
            {"group_ref": {"name": "svc", "as": "tube_{t}", "args": {"tube": "{t}"}}}]}}],
    })
    seeds = [b["compute"] for b in out["blocks"][:4]]
    assert seeds == [
        {"into": "tube_1_c", "value": "0"},
        {"into": "tube_1_contaminated", "value": "false"},
        {"into": "tube_2_c", "value": "0"},
        {"into": "tube_2_contaminated", "value": "false"},
    ]
    # `r` has no init, so it is declared-only -- no seed for it.
    assert len(out["blocks"]) == 6
    assert out["blocks"][4]["serial"]["children"][0]["compute"]["into"] == "tube_1_r"


def test_as_is_required_when_the_group_declares_locals():
    with pytest.raises(WorkflowLoadError, match="'as' is required"):
        expand_dict({
            "schema_version": 2,
            "groups": {"svc": _svc({"c": {"kind": "binding"}},
                                   [{"compute": {"into": "{c}", "value": "1"}}])},
            "blocks": [{"group_ref": {"name": "svc", "args": {"tube": 1}}}],
        })


def test_as_must_expand_to_an_identifier():
    with pytest.raises(WorkflowLoadError, match="must expand to an identifier"):
        expand_dict({
            "schema_version": 2,
            "groups": {"svc": _svc({"c": {"kind": "binding"}},
                                   [{"compute": {"into": "{c}", "value": "1"}}])},
            "blocks": [{"group_ref": {"name": "svc", "as": "tube 1", "args": {"tube": 1}}}],
        })


def test_a_bare_value_hole_as_is_not_an_identifier():
    # "{tube}" with tube: int substitutes to the JSON integer 1, which is not a name.
    with pytest.raises(WorkflowLoadError, match="must expand to an identifier"):
        expand_dict({
            "schema_version": 2,
            "groups": {"svc": _svc({"c": {"kind": "binding"}},
                                   [{"compute": {"into": "{c}", "value": "1"}}])},
            "blocks": [{"for_each": {"var": "t", "in": [1], "body": [
                {"group_ref": {"name": "svc", "as": "{t}", "args": {"tube": "{t}"}}}]}}],
        })


def test_duplicate_qualified_instance_name_is_a_load_error():
    with pytest.raises(WorkflowLoadError, match="duplicate instance name 'tube_1'"):
        expand_dict({
            "schema_version": 2,
            "groups": {"svc": _svc({"c": {"kind": "binding"}},
                                   [{"compute": {"into": "{c}", "value": "1"}}])},
            "blocks": [
                {"group_ref": {"name": "svc", "as": "tube_1", "args": {"tube": 1}}},
                {"group_ref": {"name": "svc", "as": "tube_1", "args": {"tube": 2}}},
            ],
        })


def test_a_local_kind_other_than_stream_or_binding_is_rejected():
    with pytest.raises(WorkflowLoadError, match="must be 'stream' or 'binding'"):
        expand_dict({
            "schema_version": 2,
            "groups": {"svc": _svc({"c": {"kind": "int"}},
                                   [{"compute": {"into": "{c}", "value": "1"}}])},
            "blocks": [{"group_ref": {"name": "svc", "as": "t1", "args": {"tube": 1}}}],
        })


def test_an_escaping_local_is_readable_from_a_top_level_expression():
    # examples/morbidostat.json gates a top-level abort on per-tube latches (design §2.2).
    out = expand_dict({
        "schema_version": 2,
        "groups": {"svc": _svc({"contaminated": {"kind": "binding", "init": "false"}},
                               [{"compute": {"into": "{contaminated}", "value": "true"}}])},
        "blocks": [
            {"for_each": {"var": "t", "in": [1, 2], "body": [
                {"group_ref": {"name": "svc", "as": "tube_{t}", "args": {"tube": "{t}"}}}]}},
            {"abort": {"if": "tube_1_contaminated and tube_2_contaminated", "message": "x"}},
        ],
    })
    assert out["blocks"][-1]["abort"]["if"] == "tube_1_contaminated and tube_2_contaminated"
    assert [b["compute"]["into"] for b in out["blocks"][:2]] == [
        "tube_1_contaminated", "tube_2_contaminated"]
```

Append to `tests/test_experiment_expand_trace.py` — the trace-shift tests, which are the subtle part:

```python
def test_hoisted_seeds_shift_block_trace_keys_and_trace_to_their_local_decl():
    wf = {
        "schema_version": 2,
        "groups": {
            "svc": {
                "params": [{"name": "tube", "kind": "int"}],
                "locals": {"c": {"kind": "binding", "init": "0"},
                           "hits": {"kind": "binding", "init": "1"}},
                "body": [{"compute": {"into": "{c}", "value": "{c} + {tube}"}}],
            }
        },
        "blocks": [
            {"group_ref": {"name": "svc", "as": "t1", "args": {"tube": 1}}},
            {"wait": {"duration": "9s"}},
        ],
    }
    expanded, trace = expand_dict_traced(wf)
    assert [next(iter(b)) for b in expanded["blocks"]] == [
        "compute", "compute", "serial", "wait"]
    assert expanded["blocks"][0]["compute"] == {"into": "t1_c", "value": "0"}
    assert expanded["blocks"][1]["compute"] == {"into": "t1_hits", "value": "1"}
    # Seeds trace to the declaration the author can edit, not to a block they never wrote.
    assert trace["blocks[0]"] == "groups['svc'].locals['c']"
    assert trace["blocks[1]"] == "groups['svc'].locals['hits']"
    # Everything the author DID write shifts right by the seed count.
    assert trace["blocks[2]"] == "blocks[0]"
    assert trace["blocks[3]"] == "blocks[1]"
    assert trace["blocks[2].children[0]"] == "groups['svc'].body[0]"


def test_seed_shift_composes_with_a_for_each_splice():
    wf = {
        "schema_version": 2,
        "groups": {
            "svc": {
                "params": [{"name": "tube", "kind": "int"}],
                "locals": {"c": {"kind": "binding", "init": "0"}},
                "body": [{"compute": {"into": "{c}", "value": "{tube}"}}],
            }
        },
        "blocks": [
            {"for_each": {"var": "t", "in": [1, 2], "body": [
                {"group_ref": {"name": "svc", "as": "tube_{t}", "args": {"tube": "{t}"}}}]}},
            {"wait": {"duration": "9s"}},
        ],
    }
    expanded, trace = expand_dict_traced(wf)
    # 2 seeds + 2 spliced serials + the trailing wait.
    assert len(expanded["blocks"]) == 5
    assert trace["blocks[0]"] == "groups['svc'].locals['c']"
    assert trace["blocks[1]"] == "groups['svc'].locals['c']"
    for i in (2, 3):
        assert trace[f"blocks[{i}]"] == "blocks[0].body[0]"
    assert trace["blocks[4]"] == "blocks[1]"


def test_seed_shift_leaves_group_body_trace_keys_alone():
    # Seeds prepend to top-level blocks only; `groups['x'].body[...]` keys must not move.
    wf = {
        "schema_version": 2,
        "groups": {
            "wash": {"body": [
                {"for_each": {"var": "i", "in": [1, 2],
                              "body": [{"wait": {"duration": "{i}s"}}]}},
                {"wait": {"duration": "9s"}},
            ]},
            "svc": {
                "params": [{"name": "tube", "kind": "int"}],
                "locals": {"c": {"kind": "binding", "init": "0"}},
                "body": [{"compute": {"into": "{c}", "value": "{tube}"}}],
            },
        },
        "blocks": [
            {"group_ref": {"name": "wash"}},
            {"group_ref": {"name": "svc", "as": "t1", "args": {"tube": 1}}},
        ],
    }
    expanded, trace = expand_dict_traced(wf)
    assert len(expanded["blocks"]) == 3  # 1 seed + 2 authored
    assert trace["groups['wash'].body[2]"] == "groups['wash'].body[1]"  # unshifted
    assert trace["blocks[1]"] == "blocks[0]"
    assert trace["blocks[2]"] == "blocks[1]"
```

- [ ] **Step 2: Run and watch it fail**

```
.venv/bin/python -m pytest tests/test_experiment_expand_locals.py -v
```

Expected — `locals` is ignored entirely today, so `{c}` never gets bound and the residual-hole backstop fires:

```
FAILED tests/test_experiment_expand_locals.py::test_locals_expand_to_qualified_names
  - lab_devices.experiment.errors.WorkflowLoadError: unbound hole '{c}' remains after expansion
FAILED tests/test_experiment_expand_locals.py::test_stream_locals_emit_stream_declarations
  - lab_devices.experiment.errors.WorkflowLoadError: unbound hole '{c_series}' remains after expansion
FAILED tests/test_experiment_expand_locals.py::test_as_is_required_when_the_group_declares_locals
  - lab_devices.experiment.errors.WorkflowLoadError: unbound hole '{c}' remains after expansion
FAILED tests/test_experiment_expand_locals.py::test_duplicate_qualified_instance_name_is_a_load_error
  - lab_devices.experiment.errors.WorkflowLoadError: unbound hole '{c}' remains after expansion
========================= 10 failed =========================
```

```
.venv/bin/python -m pytest tests/test_experiment_expand_trace.py -k "seed or hoisted" -v
```

```
FAILED tests/test_experiment_expand_trace.py::test_hoisted_seeds_shift_block_trace_keys_and_trace_to_their_local_decl
  - lab_devices.experiment.errors.WorkflowLoadError: unbound hole '{c}' remains after expansion
========================= 3 failed =========================
```

Note the last three failures are *not* the failures we ultimately care about — they are masked by the hole error. Confirm the shift is genuinely untested today by checking that no current test asserts a `blocks[i]` key against a seed-bearing document: `grep -c "locals" tests/test_experiment_expand_trace.py` returns `0` before this task.

- [ ] **Step 3: Minimal implementation**

Replace `_Counter` (lines 76–86) with `_Expansion`, and rename the parameter `counter: _Counter` -> `exp: _Expansion` (with `counter.bump` -> `exp.bump`) at every call site in `_expand_blocks`, `_expand_block`, `_expand_for_each`, `_expand_group_ref`, and `expand_dict_traced`:

```python
class _Expansion:
    """Mutable expansion state threaded through the recursion."""

    def __init__(self) -> None:
        self.n = 0
        self.seeds: list[tuple[dict[str, Any], str]] = []  # (compute block, authored path)
        self.streams: dict[str, dict[str, Any]] = {}       # qualified name -> StreamDecl JSON
        self.instances: dict[str, str] = {}                # qualified `as` -> claiming group

    def bump(self, k: int) -> None:
        self.n += k
        if self.n > _EXPANSION_CAP:
            raise WorkflowLoadError(
                f"for_each/group expansion exceeds {_EXPANSION_CAP} blocks"
            )
```

Add the shift helper next to `_residual_hole`:

```python
_BLOCKS_INDEX_RE = re.compile(r"\Ablocks\[(\d+)\]")


def _shift_block_traces(trace: dict[str, str], k: int) -> dict[str, str]:
    """Re-key top-level `blocks[i]...` entries after k init seeds are prepended.

    Hoisted seeds land at the FRONT of workflow['blocks'] (design 2026-07-20 §2.3), so every
    already-recorded expanded path `blocks[i]` -- and every path nested under it, e.g.
    `blocks[i].children[0]` -- becomes `blocks[i + k]`. Only the FIRST index moves: nesting
    below it is unaffected by a top-level prepend. Keys rooted at `groups['x'].body[...]`
    (the lazy-inline path) do not move at all. Authored paths -- the dict VALUES -- never
    move either: the author wrote no seeds, so nothing in the authored tree shifted.
    """
    if k == 0:
        return trace
    shifted: dict[str, str] = {}
    for key, authored in trace.items():
        m = _BLOCKS_INDEX_RE.match(key)
        if m is None:
            shifted[key] = authored
            continue
        shifted[f"blocks[{int(m.group(1)) + k}]{key[m.end():]}"] = authored
    return shifted
```

Add `_open_locals` above `_expand_group_ref`:

```python
def _open_locals(gname: str, locals_: dict[str, Any], as_value: Any, exp: _Expansion) -> Env:
    """Qualify one instance's locals as `{as}_{local}`, emitting streams and init seeds."""
    if as_value is not None and not _ident(as_value):
        raise WorkflowLoadError(
            f"group_ref {gname!r}: 'as' must expand to an identifier, got {as_value!r} "
            f"(design 2026-07-20 §6)"
        )
    if not locals_:
        return {}  # `as` is optional for a group with nothing to qualify
    if as_value is None:
        raise WorkflowLoadError(
            f"group_ref {gname!r}: 'as' is required because the group declares locals "
            f"(design 2026-07-20 §6)"
        )
    if as_value in exp.instances:
        raise WorkflowLoadError(
            f"group_ref {gname!r}: duplicate instance name {as_value!r}, already used by "
            f"group_ref {exp.instances[as_value]!r} (design 2026-07-20 §6)"
        )
    exp.instances[as_value] = gname
    env: Env = {}
    for lname, decl in locals_.items():
        if not isinstance(decl, dict):
            raise WorkflowLoadError(f"group {gname!r} local {lname!r} must be an object")
        kind = decl.get("kind")
        if kind not in ("stream", "binding"):
            raise WorkflowLoadError(
                f"group {gname!r} local {lname!r}: kind must be 'stream' or 'binding' "
                f"(design 2026-07-20 §2.2)"
            )
        qualified = f"{as_value}_{lname}"
        env[lname] = (kind, qualified)
        if kind == "stream":
            exp.streams[qualified] = {
                k: decl[k] for k in ("units", "persistence") if decl.get(k) is not None
            }
        elif decl.get("init") is not None:
            exp.seeds.append((
                {"compute": {"into": qualified, "value": decl["init"]}},
                f"groups[{gname!r}].locals[{lname!r}]",
            ))
    return env
```

In `_expand_group_ref`, read `locals`, include it in the plain-group_ref escape, and merge its env:

```python
    gdict: dict[str, Any] = group if isinstance(group, dict) else {}
    decls = _decls(gdict.get("params"), f"group {name!r} params")
    raw_locals = gdict.get("locals")
    locals_: dict[str, Any] = raw_locals if isinstance(raw_locals, dict) else {}
    if not decls and not args and not locals_:
        trace[f"{dst}[{base}]"] = src
        return [block]  # plain group_ref: preserve the node (lazy inline)
    if group is None:
        raise WorkflowLoadError(f"group_ref {name!r}: unknown group")
    env = _bind(decls, args, f"group_ref {name!r} args")
    env.update(_open_locals(name, locals_, body.get("as"), exp))
```

Rewrite `expand_dict_traced` (lines 258–294):

```python
def expand_dict_traced(workflow_dict: dict[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
    """expand_dict plus a source map: expanded structural path -> authored structural path.

    Studio validates the EXPANDED workflow, so its diagnostics carry expanded indices that do
    not match the authored tree; the map is what lets the builder resolve a diagnostic back to
    the block the author can actually edit (design 2026-07-16 §5.3). Many-to-one by nature:
    every for_each copy traces to the one authored body block, and every hoisted init seed
    traces to the `locals` entry that declared it.
    """
    out = copy.deepcopy(workflow_dict)
    groups = out.get("groups")
    groups = groups if isinstance(groups, dict) else {}
    exp = _Expansion()
    trace: dict[str, str] = {}
    for name, g in groups.items():  # expand for_each inside plain-group bodies (used lazily)
        if (isinstance(g, dict) and not g.get("params") and not g.get("locals")
                and isinstance(g.get("body"), list)):
            path = f"groups[{name!r}].body"
            g["body"] = _expand_blocks(g["body"], groups, exp, 0, trace, path, path)
    blocks = out.get("blocks")
    if isinstance(blocks, list):
        out["blocks"] = _expand_blocks(blocks, groups, exp, 0, trace, "blocks", "blocks")
    if exp.seeds:
        # Prepending shifts every expanded top-level index; the trace must move with it.
        trace = _shift_block_traces(trace, len(exp.seeds))
        for j, (_seed, authored) in enumerate(exp.seeds):
            trace[f"blocks[{j}]"] = authored
        out["blocks"] = [seed for seed, _ in exp.seeds] + list(out.get("blocks", []))
    if exp.streams:
        merged = dict(out.get("streams") or {})
        for qname, sdecl in exp.streams.items():
            if qname in merged:
                raise WorkflowLoadError(
                    f"group local emits stream {qname!r}, which is already declared "
                    f"(design 2026-07-20 §2.2)"
                )
            merged[qname] = sdecl
        out["streams"] = merged
    kept = {n: g for n, g in groups.items()
            if not (isinstance(g, dict) and (g.get("params") or g.get("locals")))}
    if kept:
        out["groups"] = kept
    else:
        out.pop("groups", None)
    if exp.n > 0:
        hole = _residual_hole(out.get("blocks", []))
        if hole is None:
            for g in kept.values():
                if isinstance(g, dict):
                    hole = _residual_hole(g.get("body", []))
                    if hole is not None:
                        break
        if hole is not None:
            raise WorkflowLoadError(f"unbound hole '{hole}' remains after expansion")
    return out, trace
```

Two ordering facts this relies on, worth keeping in mind while implementing:

1. `_shift_block_traces` must run **before** the seed keys are written, or `blocks[0]` (the first seed) would itself be shifted to `blocks[k]`.
2. Seeds from a group_ref reached through the *lazy* plain-group path still prepend to top-level `blocks` and still trace to `groups['<g>'].locals['<l>']` — correct, since an initializer must run before everything regardless of where its call site sits.

- [ ] **Step 4: Run to pass**

```
.venv/bin/python -m pytest tests/test_experiment_expand_locals.py tests/test_experiment_expand_trace.py -v
```

Expected:

```
tests/test_experiment_expand_locals.py::test_locals_expand_to_qualified_names PASSED
tests/test_experiment_expand_locals.py::test_as_interpolates_from_the_call_site_env PASSED
tests/test_experiment_expand_locals.py::test_stream_locals_emit_stream_declarations PASSED
tests/test_experiment_expand_locals.py::test_init_seeds_hoist_to_the_front_of_blocks_in_expansion_order PASSED
tests/test_experiment_expand_locals.py::test_as_is_required_when_the_group_declares_locals PASSED
tests/test_experiment_expand_locals.py::test_as_must_expand_to_an_identifier PASSED
tests/test_experiment_expand_locals.py::test_a_bare_value_hole_as_is_not_an_identifier PASSED
tests/test_experiment_expand_locals.py::test_duplicate_qualified_instance_name_is_a_load_error PASSED
tests/test_experiment_expand_locals.py::test_a_local_kind_other_than_stream_or_binding_is_rejected PASSED
tests/test_experiment_expand_locals.py::test_an_escaping_local_is_readable_from_a_top_level_expression PASSED
tests/test_experiment_expand_trace.py::test_hoisted_seeds_shift_block_trace_keys_and_trace_to_their_local_decl PASSED
tests/test_experiment_expand_trace.py::test_seed_shift_composes_with_a_for_each_splice PASSED
tests/test_experiment_expand_trace.py::test_seed_shift_leaves_group_body_trace_keys_alone PASSED
========================= 24 passed =========================
```

Mutation-verify the shift (it is the one thing here that can pass vacuously — every existing trace test uses a seedless document, so a no-op `_shift_block_traces` would leave the suite green). Temporarily change `_shift_block_traces` to `return trace` and re-run:

```
.venv/bin/python -m pytest tests/test_experiment_expand_trace.py -k seed -v
```

Must fail with:

```
FAILED tests/test_experiment_expand_trace.py::test_hoisted_seeds_shift_block_trace_keys_and_trace_to_their_local_decl
  - AssertionError: assert 'groups[\'svc\'].locals[\'c\']' == 'blocks[0]'
FAILED tests/test_experiment_expand_trace.py::test_seed_shift_composes_with_a_for_each_splice
  - AssertionError: assert 'groups[\'svc\'].locals[\'c\']' == 'blocks[0].body[0]'
```

Revert the mutation, then run the gate:

```
.venv/bin/python -m pytest
.venv/bin/python -m mypy src/lab_devices
.venv/bin/python -m ruff check .
awk 'length>100 {print FILENAME": "FNR}' src/lab_devices/experiment/expand.py \
    tests/test_experiment_expand_locals.py tests/test_experiment_expand_trace.py
```

- [ ] **Step 5: Commit**

```
git add src/lab_devices/experiment/expand.py tests/test_experiment_expand_locals.py \
        tests/test_experiment_expand_trace.py
git commit -m "feat(experiment): group locals with qualified naming and init hoisting

A group declares the streams and bindings it owns; a group_ref names the instance
with a required \`as\`, and locals expand to \`{as}_{local}\`. Stream locals emit
StreamDecls; binding locals with \`init\` hoist one compute to the front of blocks
in deterministic expansion order (design 2026-07-20 §2.2, §2.3, §6).

The trace map moves with the hoist: prepending k seeds shifts every expanded
\`blocks[i]\` key to \`blocks[i+k]\`, and each seed traces to the locals entry that
declared it -- so Studio still resolves a diagnostic to a block the author can edit."
```

---

### Task 6: Typed `for_each`

**Files:**
- Modify: `src/lab_devices/experiment/expand.py:95-118` (`_envs` rewritten; `_infer_kind` deleted)
- Modify: `src/lab_devices/experiment/expand.py:172-203` (`_expand_for_each` — signature of `_envs` only)
- Modify: `tests/test_experiment_expand.py:14-36, 38-48, 72-87, 96-115, 117-135` (shorthand -> typed rows)
- Modify: `tests/test_experiment_expand_trace.py` (all shorthand fixtures -> typed rows)
- Create: `tests/test_experiment_foreach_typed.py`

**Interfaces:**

Consumes: `_decls`, `_bind`, `Env` (Task 4).

Produces:
```python
def _envs(body: dict[str, Any]) -> list[Env]:
    """One Env per `in` row, bound against the declared `vars` (design 2026-07-20 §4)."""
```
Deleted: `_infer_kind` (the Task 4 shim).

- [ ] **Step 1: Write the failing test**

Create `tests/test_experiment_foreach_typed.py`:

```python
"""Typed for_each: `vars` declarations + typed `in` rows (design 2026-07-20 §4)."""

import pytest

from lab_devices.experiment.errors import WorkflowLoadError
from lab_devices.experiment.expand import expand_dict


def _wf(for_each_body):
    return {"schema_version": 2, "blocks": [{"for_each": for_each_body}]}


def test_typed_rows_bind_each_cell_by_declared_kind():
    out = expand_dict(_wf({
        "vars": [{"name": "tube", "kind": "int"},
                 {"name": "meter", "kind": "role", "device_type": "densitometer"},
                 {"name": "od", "kind": "stream"}],
        "in": [{"tube": 1, "meter": "od_meter_1", "od": "od_1"},
               {"tube": 2, "meter": "od_meter_2", "od": "od_2"}],
        "body": [{"measure": {"device": "{meter}", "verb": "measure", "into": "{od}"}},
                 {"command": {"device": "valve_1", "verb": "set_position",
                              "params": {"position": "{tube}"}}}],
    }))
    ms = [b for b in out["blocks"] if "measure" in b]
    cs = [b for b in out["blocks"] if "command" in b]
    assert [m["measure"]["device"] for m in ms] == ["od_meter_1", "od_meter_2"]
    assert [m["measure"]["into"] for m in ms] == ["od_1", "od_2"]
    assert [c["command"]["params"]["position"] for c in cs] == [1, 2]  # typed, not "1"


def test_scalar_var_shorthand_is_rejected():
    with pytest.raises(WorkflowLoadError, match="shorthand was removed"):
        expand_dict(_wf({"var": "t", "in": [1, 2],
                         "body": [{"wait": {"duration": "{t}s"}}]}))


def test_scalar_in_items_are_rejected():
    with pytest.raises(WorkflowLoadError, match="row 0 must be an object"):
        expand_dict(_wf({"vars": [{"name": "t", "kind": "int"}], "in": [1, 2],
                         "body": [{"wait": {"duration": "{t}s"}}]}))


def test_row_missing_a_declared_var_is_a_load_error():
    with pytest.raises(WorkflowLoadError, match="row 1: missing 'od' \\(kind 'stream'\\)"):
        expand_dict(_wf({
            "vars": [{"name": "tube", "kind": "int"}, {"name": "od", "kind": "stream"}],
            "in": [{"tube": 1, "od": "od_1"}, {"tube": 2}],
            "body": [{"record": {"into": "{od}", "value": "{tube}"}}],
        }))


def test_row_with_an_extra_key_is_a_load_error():
    with pytest.raises(WorkflowLoadError, match="row 0: unknown name 'port'"):
        expand_dict(_wf({
            "vars": [{"name": "tube", "kind": "int"}],
            "in": [{"tube": 1, "port": 5}],
            "body": [{"wait": {"duration": "{tube}s"}}],
        }))


def test_cell_of_the_wrong_json_type_is_a_load_error():
    with pytest.raises(WorkflowLoadError, match="row 1: 'tube' expects kind 'int', got '2'"):
        expand_dict(_wf({
            "vars": [{"name": "tube", "kind": "int"}],
            "in": [{"tube": 1}, {"tube": "2"}],
            "body": [{"wait": {"duration": "{tube}s"}}],
        }))


def test_reference_cell_may_not_be_glued_to_identifier_text_in_the_body():
    with pytest.raises(WorkflowLoadError, match="whole identifier"):
        expand_dict(_wf({
            "vars": [{"name": "od", "kind": "stream"}],
            "in": [{"od": "od_1"}],
            "body": [{"record": {"into": "{od}_raw", "value": "1"}}],
        }))


def test_vars_must_be_a_list_of_declarations():
    with pytest.raises(WorkflowLoadError, match="for_each 'vars' must be a list"):
        expand_dict(_wf({"vars": {"tube": "int"}, "in": [{"tube": 1}],
                         "body": [{"wait": {"duration": "1s"}}]}))


def test_an_unknown_kind_is_a_load_error():
    with pytest.raises(WorkflowLoadError, match="needs a 'name' and a valid 'kind'"):
        expand_dict(_wf({"vars": [{"name": "t", "kind": "integer"}], "in": [{"t": 1}],
                         "body": [{"wait": {"duration": "{t}s"}}]}))


def test_empty_in_is_still_rejected():
    with pytest.raises(WorkflowLoadError, match="'in' must be a non-empty list"):
        expand_dict(_wf({"vars": [{"name": "t", "kind": "int"}], "in": [],
                         "body": [{"wait": {"duration": "{t}s"}}]}))
```

Rewrite the shorthand fixtures in `tests/test_experiment_expand.py`:

```python
def test_for_each_scalar_splices_into_serial():
    out = expand_dict(_wf([
        {"serial": {"children": [
            {"for_each": {"vars": [{"name": "t", "kind": "int"}],
                          "in": [{"t": 1}, {"t": 2}, {"t": 3}],
                          "body": [{"wait": {"duration": "{t}s"}}]}}
        ]}}
    ]))
    kids = out["blocks"][0]["serial"]["children"]
    assert [k["wait"]["duration"] for k in kids] == ["1s", "2s", "3s"]


def test_for_each_in_parallel_yields_lanes():
    out = expand_dict(_wf([
        {"parallel": {"children": [
            {"for_each": {"vars": [{"name": "t", "kind": "int"}],
                          "in": [{"t": 1}, {"t": 2}],
                          "body": [{"measure": {"device": "densitometer_{t}",
                                                "verb": "measure", "into": "od_{t}"}}]}}
        ]}}
    ]))
    lanes = out["blocks"][0]["parallel"]["children"]
    assert [lane["measure"]["device"] for lane in lanes] == ["densitometer_1", "densitometer_2"]
    assert [lane["measure"]["into"] for lane in lanes] == ["od_1", "od_2"]


def test_object_items_multi_field():
    out = expand_dict(_wf([
        {"for_each": {"vars": [{"name": "t", "kind": "int"}, {"name": "p", "kind": "int"}],
                      "in": [{"t": 1, "p": 7}, {"t": 2, "p": 8}],
                      "body": [{"command": {"device": "valve_{t}", "verb": "set_position",
                                            "params": {"position": "{p}"}}}]}}
    ]))
    cmds = out["blocks"]
    assert cmds[0]["command"]["device"] == "valve_1"
    assert cmds[0]["command"]["params"]["position"] == 7  # typed value hole (design §3.1)
    assert cmds[1]["command"]["device"] == "valve_2"


def test_for_each_over_group_ref_composition():
    out = expand_dict(_wf(
        [{"for_each": {"vars": [{"name": "t", "kind": "int"}],
                       "in": [{"t": 1}, {"t": 2}, {"t": 3}],
                       "body": [{"group_ref": {"name": "svc", "args": {"t": "{t}"}}}]}}],
        groups={"svc": {"params": [{"name": "t", "kind": "int"}],
                        "body": [{"measure": {"device": "densitometer_{t}",
                                              "verb": "measure", "into": "od_{t}"}}]}},
    ))
    devs = [b["serial"]["children"][0]["measure"]["device"] for b in out["blocks"]]
    assert devs == ["densitometer_1", "densitometer_2", "densitometer_3"]


def test_unbound_hole_raises():
    with pytest.raises(WorkflowLoadError, match="hole"):
        expand_dict(_wf([{"for_each": {"vars": [{"name": "t", "kind": "int"}],
                                       "in": [{"t": 1}],
                                       "body": [{"wait": {"duration": "{nope}s"}}]}}]))


def test_forbidden_block_key_on_for_each_raises():
    with pytest.raises(WorkflowLoadError, match="block-level"):
        expand_dict(_wf([{"for_each": {"vars": [{"name": "t", "kind": "int"}],
                                       "in": [{"t": 1}],
                                       "body": [{"wait": {"duration": "1s"}}]},
                          "on_error": "continue"}]))


def test_expansion_cap_trips():
    with pytest.raises(WorkflowLoadError, match="exceeds"):
        expand_dict(_wf([{"for_each": {
            "vars": [{"name": "a", "kind": "int"}],
            "in": [{"a": i} for i in range(200)],
            "body": [{"for_each": {"vars": [{"name": "b", "kind": "int"}],
                                   "in": [{"b": i} for i in range(200)],
                                   "body": [{"wait": {"duration": "1s"}}]}}]}}]))


def test_parametrized_group_body_may_contain_for_each():
    inner_cmd = {"command": {"device": "valve_{valve}", "verb": "set_position",
                             "params": {"position": "{valve}", "ml": "{volume}"}}}
    out = expand_dict(_wf(
        [{"group_ref": {"name": "dose", "args": {"volume": 5}}}],
        groups={"dose": {"params": [{"name": "volume", "kind": "int"}],
                         "body": [{"for_each": {"vars": [{"name": "valve", "kind": "int"}],
                                                "in": [{"valve": 1}, {"valve": 2}],
                                                "body": [inner_cmd]}}]}},
    ))
    cmds = out["blocks"][0]["serial"]["children"]
    assert [c["command"]["device"] for c in cmds] == ["valve_1", "valve_2"]
    assert [c["command"]["params"]["position"] for c in cmds] == [1, 2]
    assert [c["command"]["params"]["ml"] for c in cmds] == [5, 5]


def test_residual_hole_after_expansion_raises():
    with pytest.raises(WorkflowLoadError, match="unbound hole"):
        expand_dict(_wf([{"for_each": {"vars": [{"name": "t", "kind": "int"}],
                                       "in": [{"t": 1}],
                                       "body": [{"wait": {"duration": "{nope}s"}}]}}]))
```

Delete `test_var_with_object_items_raises` (it asserted a shorthand-only error that no longer exists); `test_scalar_var_shorthand_is_rejected` in the new file replaces it.

In `tests/test_experiment_expand_trace.py`, apply the same mechanical conversion to every remaining shorthand fixture — `{"var": "X", "in": [a, b]}` becomes `{"vars": [{"name": "X", "kind": "int"}], "in": [{"X": a}, {"X": b}]}`:

```python
{"for_each": {"vars": [{"name": "t", "kind": "int"}], "in": [{"t": 1}, {"t": 2}],
              "body": [{"wait": {"duration": "1s"}}]}}
```
```python
{"for_each": {"vars": [{"name": "t", "kind": "int"}],
              "in": [{"t": 1}, {"t": 2}, {"t": 3}],
              "body": [{"wait": {"duration": "{t}s"}}]}}
```
```python
{"for_each": {"vars": [{"name": "t", "kind": "int"}], "in": [{"t": 1}, {"t": 2}],
              "body": [{"wait": {"duration": "{t}s"}}]}}
```
```python
{"for_each": {"vars": [{"name": "i", "kind": "int"}], "in": [{"i": 1}, {"i": 2}],
              "body": [{"wait": {"duration": "{i}s"}}]}}
```

Applies to `test_traced_output_matches_untraced`, `test_for_each_copies_all_trace_to_the_one_authored_body_block`, `test_blocks_after_a_splice_trace_to_their_shifted_authored_index`, `test_container_children_trace_through`, `test_nested_for_each_inside_a_parametrized_group_traces_to_the_group_body`, `test_plain_group_body_indices_shift_when_a_for_each_inside_it_splices`, `test_plain_group_ref_traces_itself_after_a_splice`, `test_malformed_block_traces_after_a_splice`, and `test_malformed_group_ref_body_traces_after_a_splice`. Every assertion in those tests stays byte-for-byte the same — only the fixture shape changes, which is exactly what makes them a regression oracle for the rewrite.

- [ ] **Step 2: Run and watch it fail**

```
.venv/bin/python -m pytest tests/test_experiment_foreach_typed.py -v
```

Expected — `_envs` still reads `var`/scalar `in` and knows nothing about `vars`:

```
FAILED tests/test_experiment_foreach_typed.py::test_typed_rows_bind_each_cell_by_declared_kind
  - lab_devices.experiment.errors.WorkflowLoadError: unbound hole '{meter}' remains after expansion
FAILED tests/test_experiment_foreach_typed.py::test_scalar_var_shorthand_is_rejected
  - Failed: DID NOT RAISE <class 'lab_devices.experiment.errors.WorkflowLoadError'>
FAILED tests/test_experiment_foreach_typed.py::test_row_missing_a_declared_var_is_a_load_error
  - lab_devices.experiment.errors.WorkflowLoadError: for_each object items must share one key set
FAILED tests/test_experiment_foreach_typed.py::test_row_with_an_extra_key_is_a_load_error
  - Failed: DID NOT RAISE <class 'lab_devices.experiment.errors.WorkflowLoadError'>
FAILED tests/test_experiment_foreach_typed.py::test_cell_of_the_wrong_json_type_is_a_load_error
  - Failed: DID NOT RAISE <class 'lab_devices.experiment.errors.WorkflowLoadError'>
FAILED tests/test_experiment_foreach_typed.py::test_vars_must_be_a_list_of_declarations
  - lab_devices.experiment.errors.WorkflowLoadError: unbound hole '{tube}' remains after expansion
========================= 8 failed, 2 passed =========================
```

The two passes are `test_scalar_in_items_are_rejected` and `test_empty_in_is_still_rejected`, which the old code happens to reject for different reasons — the `row 0 must be an object` message assertion will still need the rewrite to match. Confirm by running with `-k scalar_in`:

```
FAILED tests/test_experiment_foreach_typed.py::test_scalar_in_items_are_rejected
  - AssertionError: Regex pattern did not match.
     Regex: "row 0 must be an object"
     Input: "for_each without 'var' requires object items"
```

- [ ] **Step 3: Minimal implementation**

Replace `_envs` and delete `_infer_kind` (lines 95–118):

```python
def _envs(body: dict[str, Any]) -> list[Env]:
    """One Env per `in` row, bound against the declared `vars` (design 2026-07-20 §4).

    Replaces the untyped check that `in` object items merely shared one key set: rows are now
    checked against a declaration, so a missing or extra key is named rather than inferred.
    """
    if "var" in body:
        raise WorkflowLoadError(
            "for_each 'var' + scalar 'in' shorthand was removed in schema_version 2; declare "
            "'vars': [{'name': ..., 'kind': ...}] and give 'in' object rows "
            "(design 2026-07-20 §4)"
        )
    decls = _decls(body.get("vars"), "for_each 'vars'")
    raw = body.get("in")
    if not isinstance(raw, list) or not raw:
        raise WorkflowLoadError("for_each 'in' must be a non-empty list")
    out: list[Env] = []
    for r, row in enumerate(raw):
        if not isinstance(row, dict):
            raise WorkflowLoadError(f"for_each 'in' row {r} must be an object, got {row!r}")
        out.append(_bind(decls, row, f"for_each 'in' row {r}"))
    return out
```

`_expand_for_each` needs no change — `for env in _envs(body)` already yields the new `Env` and `_substitute` already takes it.

- [ ] **Step 4: Run to pass**

```
.venv/bin/python -m pytest tests/test_experiment_foreach_typed.py tests/test_experiment_expand.py tests/test_experiment_expand_trace.py -v
```

Expected:

```
tests/test_experiment_foreach_typed.py::test_typed_rows_bind_each_cell_by_declared_kind PASSED
tests/test_experiment_foreach_typed.py::test_scalar_var_shorthand_is_rejected PASSED
tests/test_experiment_foreach_typed.py::test_scalar_in_items_are_rejected PASSED
tests/test_experiment_foreach_typed.py::test_row_missing_a_declared_var_is_a_load_error PASSED
tests/test_experiment_foreach_typed.py::test_row_with_an_extra_key_is_a_load_error PASSED
tests/test_experiment_foreach_typed.py::test_cell_of_the_wrong_json_type_is_a_load_error PASSED
tests/test_experiment_foreach_typed.py::test_reference_cell_must_be_the_entire_string_in_the_body PASSED
tests/test_experiment_foreach_typed.py::test_vars_must_be_a_list_of_declarations PASSED
tests/test_experiment_foreach_typed.py::test_an_unknown_kind_is_a_load_error PASSED
tests/test_experiment_foreach_typed.py::test_empty_in_is_still_rejected PASSED
tests/test_experiment_expand.py::... PASSED (21 tests)
tests/test_experiment_expand_trace.py::... PASSED (14 tests)
========================= 45 passed =========================
```

Confirm `_infer_kind` is gone:

```
grep -n "_infer_kind" src/lab_devices/experiment/expand.py
```

must print nothing (exit 1).

Then the gate:

```
.venv/bin/python -m pytest
.venv/bin/python -m mypy src/lab_devices
.venv/bin/python -m ruff check .
awk 'length>100 {print FILENAME": "FNR}' src/lab_devices/experiment/expand.py \
    tests/test_experiment_foreach_typed.py tests/test_experiment_expand.py \
    tests/test_experiment_expand_trace.py
```

Note: `tests/test_experiment_foreach_serialize.py`, `test_experiment_foreach_validate.py`, `test_experiment_foreach_execute.py`, and the JSON fixtures still carry the shorthand and are migrated by the serialize/validate/examples tasks — expect failures there until those land, and do not "fix" them here.

- [ ] **Step 5: Commit**

```
git add src/lab_devices/experiment/expand.py tests/test_experiment_foreach_typed.py \
        tests/test_experiment_expand.py tests/test_experiment_expand_trace.py
git commit -m "feat(experiment)!: typed for_each rows, scalar shorthand removed

for_each declares \`vars\` (ParamDecls) and \`in\` is a table of typed rows. Each
row must supply exactly the declared names -- no missing, no extra -- and each
cell is checked against its var's kind, replacing the old check that object items
merely shared one key set. The \`var\` + scalar \`in\` shorthand is removed: it
cannot carry a kind (design 2026-07-20 §4).

BREAKING CHANGE: for_each blocks using \"var\" no longer load."
```agentId: a6c75781796df6b4a (use SendMessage with to: 'a6c75781796df6b4a', summary: '<5-10 word recap>' to continue this agent)
<usage>subagent_tokens: 92206
tool_uses: 11
duration_ms: 440293</usage>

---

### Task 7: Validation of typed declarations

**Files:**
- `src/lab_devices/experiment/validate.py` (modified — `_check_for_each_and_arity` deleted, replaced by `_check_declarations` and its helpers)
- `tests/test_experiment_validate_typed.py` (new)

**Interfaces:**

*Consumes* (all landed in Tasks 1–6, use verbatim):
```python
# lab_devices.experiment.workflow
ParamKind = Literal["int", "number", "bool", "string", "role", "stream", "binding"]
VALUE_KINDS: frozenset[str]      # {"int", "number", "bool", "string"}
REFERENCE_KINDS: frozenset[str]  # {"role", "stream", "binding"}

@dataclass(frozen=True)
class ParamDecl:
    name: str
    kind: ParamKind
    device_type: str | None = None

@dataclass(frozen=True)
class LocalDecl:
    kind: Literal["stream", "binding"]
    init: str | None = None
    units: str | None = None
    persistence: str | None = None

@dataclass(frozen=True)
class RoleDecl:
    type: str
    device: str | None = None

@dataclass
class Group:
    name: str
    body: list[Block] = field(default_factory=list)
    params: list[ParamDecl] = field(default_factory=list)
    locals: dict[str, LocalDecl] = field(default_factory=dict)

@dataclass
class Workflow:
    ...
    groups: dict[str, Group]
    roles: dict[str, RoleDecl]
    def role_type(self, role: str) -> str: ...   # raises UnknownRoleError

# lab_devices.experiment.blocks
@dataclass(kw_only=True)
class ForEach(BlockBase):
    body: list[Block] = field(default_factory=list)
    vars: list[ParamDecl] = field(default_factory=list)   # `var` is GONE (Task 6)
    items: list[dict[str, Any]] = field(default_factory=list)

# lab_devices.experiment.analyze
def references(expr: Expr) -> ExprRefs   # .bindings, .streams_windowed, .streams_counted
```
Already present in `validate.py` and reused unchanged: `_IDENT_RE`, `_RESERVED_NAMES`,
`parse_expression`, `Diagnostic`, `_iter_all_blocks`, `_check_groups`.

Note on the starting state: after Task 6, `_check_for_each_and_arity` is dead weight — it still
reads `Group.params` as a `list[str]` (`set(group.params)` now yields a set of `ParamDecl`
objects, so the arity comparison is unconditionally true) and still branches on the removed
`ForEach.var`. Task 7 deletes it outright rather than patching it.

*Produces* (new in `validate.py`):
```python
def _check_declarations(w: Workflow, out: list[Diagnostic]) -> bool
def _walk_decls(blocks: list[B.Block], prefix: str, w: Workflow,
                env: dict[str, ParamDecl], out: list[Diagnostic]) -> None
def _check_group_args(b: B.GroupRef, path: str, w: Workflow,
                      env: Mapping[str, ParamDecl], out: list[Diagnostic]) -> None
def _check_for_each(b: B.ForEach, path: str, w: Workflow,
                    env: Mapping[str, ParamDecl], out: list[Diagnostic]) -> None
def _check_typed_arg(decl: ParamDecl, value: object, ctx: str, w: Workflow,
                     env: Mapping[str, ParamDecl], out: list[Diagnostic]) -> None
def _check_decl_names(decls: list[ParamDecl], locals_: Mapping[str, LocalDecl], where: str,
                      env: Mapping[str, ParamDecl], out: list[Diagnostic]
                      ) -> dict[str, ParamDecl]
def _check_local_init(name: str, local: LocalDecl, where: str,
                      out: list[Diagnostic]) -> None
```
`_validate_macro_workflow` calls `_check_declarations` where it called
`_check_for_each_and_arity`; the boolean contract (`True` iff the doc is safe to expand) is
unchanged.

**Scope boundary — read before writing any check.** `_check_declarations` runs on the
**authored** document, before `expand_workflow`. Reference-kind arguments are therefore checked
against the **declared sections only**: `w.roles`, `w.streams`, and the enclosing binder
environment. Names the *expander* manufactures — a group local's qualified `{as}_{local}`, a
`for_each` copy's substituted stream — do not exist yet and are deliberately not consulted here;
they are covered by the existing post-expansion checks (`_check_record`, `_check_measure`,
`_check_streams_declared`, the residual-hole scan in `expand.py`) which run on the expanded doc
via `_validate_workflow(expanded, out)`. The consequence is a real, intended restriction: a
`stream`-kinded argument may name a section-declared stream or be a hole bound to an enclosing
declaration, but it may **not** be the literal spelling of another group's local
(`"tube_1_c_series"`) — that stream is not declared anywhere the author can point at. Step 4's
last test pins this as intended behaviour, not a bug.

---

- [ ] **Step 1 — per-param `group_ref` arity, and the walker that carries scope**

Write the failing test. Create `tests/test_experiment_validate_typed.py`:

```python
import pytest

from lab_devices.experiment.errors import ValidationError
from lab_devices.experiment.serialize import workflow_from_dict
from lab_devices.experiment.validate import validate

DEFAULT_ROLES = {
    "od_meter_1": {"type": "densitometer"},
    "od_meter_2": {"type": "densitometer"},
    "medium_pump": {"type": "pump"},
}


def wf2(blocks, *, streams=None, groups=None, roles=None):
    return workflow_from_dict({
        "schema_version": 2,
        "roles": DEFAULT_ROLES if roles is None else roles,
        "streams": {name: {} for name in (streams or [])},
        "groups": groups or {},
        "blocks": blocks,
    })


def diags(workflow):
    with pytest.raises(ValidationError) as exc:
        validate(workflow)
    return exc.value.diagnostics


def messages(workflow):
    return [d.message for d in diags(workflow)]


STOP_PUMP = {"command": {"device": "medium_pump", "verb": "stop"}}


def _svc(params, body=None):
    return {"svc": {"params": params, "body": body or [STOP_PUMP]}}


def test_group_ref_missing_arg_is_reported_per_param():
    w = wf2(
        [{"group_ref": {"name": "svc", "args": {"tube": 1}}}],
        groups=_svc([{"name": "tube", "kind": "int"},
                     {"name": "dose", "kind": "number"}]),
    )
    msgs = messages(w)
    assert any("missing argument 'dose' (number)" in m for m in msgs)
    assert not any("must match params" in m for m in msgs)


def test_group_ref_extra_arg_is_reported_per_arg():
    w = wf2(
        [{"group_ref": {"name": "svc", "args": {"tube": 1, "ghost": 2}}}],
        groups=_svc([{"name": "tube", "kind": "int"}]),
    )
    assert any("group_ref 'svc' has no parameter 'ghost'" in m for m in messages(w))


def test_group_ref_with_exact_args_is_clean():
    w = wf2(
        [{"group_ref": {"name": "svc", "args": {"tube": 1}}}],
        groups=_svc([{"name": "tube", "kind": "int"}]),
    )
    assert validate(w) is None


def test_for_each_block_level_fields_still_rejected():
    w = wf2([{"for_each": {"vars": [{"name": "t", "kind": "int"}],
                           "in": [{"t": 1}], "body": [STOP_PUMP]},
              "gap_after": "1s"}])
    assert any("may not carry block-level 'gap_after'" in m for m in messages(w))
```

Run it and see it fail:

```
.venv/bin/python -m pytest tests/test_experiment_validate_typed.py -v
```

Expected — the first two fail because the old checker still emits the set-difference message
(and, with `ParamDecl` objects in the set, emits it even for a correct call site), the third
fails because that spurious diagnostic makes `validate` raise:

```
tests/test_experiment_validate_typed.py::test_group_ref_missing_arg_is_reported_per_param FAILED
tests/test_experiment_validate_typed.py::test_group_ref_extra_arg_is_reported_per_arg FAILED
tests/test_experiment_validate_typed.py::test_group_ref_with_exact_args_is_clean FAILED
tests/test_experiment_validate_typed.py::test_for_each_block_level_fields_still_rejected PASSED

E       assert not True
E        +  where True = any(<generator object ...>)
=================== 3 failed, 1 passed in 0.42s ====================
```

Minimal implementation. In `validate.py`, delete `_check_for_each_and_arity` entirely and add,
in its place:

```python
def _check_group_args(
    b: B.GroupRef,
    path: str,
    w: Workflow,
    env: Mapping[str, ParamDecl],
    out: list[Diagnostic],
) -> None:
    """`args` must supply EXACTLY the declared params, reported one diagnostic per
    param (design 2026-07-20 §2.4). A set-difference message tells the author what the
    two sets are; a per-param message tells them what to type."""
    group = w.groups.get(b.name)
    if group is None:
        return  # unknown group: already diagnosed by _check_groups
    declared = {p.name: p for p in group.params}
    for name, decl in declared.items():
        if name not in b.args:
            out.append(Diagnostic(
                "group", path,
                f"group_ref {b.name!r} is missing argument {name!r} ({decl.kind})",
            ))
    for name in b.args:
        if name not in declared:
            out.append(Diagnostic(
                "group", path, f"group_ref {b.name!r} has no parameter {name!r}"
            ))


def _check_for_each(
    b: B.ForEach,
    path: str,
    w: Workflow,
    env: Mapping[str, ParamDecl],
    out: list[Diagnostic],
) -> None:
    for key, present in (("retry", b.retry is not None), ("on_error", b.on_error != "fail"),
                         ("gap_after", b.gap_after is not None),
                         ("start_offset", b.start_offset is not None)):
        if present:
            out.append(Diagnostic(
                "for_each", path,
                f"for_each may not carry block-level {key!r}; put it on the body blocks",
            ))
    if not b.body:
        out.append(Diagnostic("for_each", path, "for_each 'body' must be non-empty"))
    if not b.items:
        out.append(Diagnostic("for_each", path, "for_each 'in' must be non-empty"))
    if not b.vars:
        out.append(Diagnostic("for_each", path, "for_each 'vars' must be non-empty"))


def _walk_decls(
    blocks: list[B.Block],
    prefix: str,
    w: Workflow,
    env: dict[str, ParamDecl],
    out: list[Diagnostic],
) -> None:
    """Walk the AUTHORED tree carrying the declarations in scope. `_iter_all_blocks`
    cannot serve here: it is scope-blind, and every check below is about what a name
    means at the point it is written."""
    for i, b in enumerate(blocks):
        path = f"{prefix}[{i}]"
        if isinstance(b, B.ForEach):
            _check_for_each(b, path, w, env, out)
            inner = dict(env)
            _walk_decls(b.body, f"{path}.body", w, inner, out)
            continue
        if isinstance(b, B.GroupRef):
            _check_group_args(b, path, w, env, out)
        if isinstance(b, (B.Serial, B.Parallel)):
            _walk_decls(b.children, f"{path}.children", w, env, out)
        elif isinstance(b, B.Loop):
            _walk_decls(b.body, f"{path}.body", w, env, out)
        elif isinstance(b, B.Branch):
            _walk_decls(b.then, f"{path}.then", w, env, out)
            if b.else_ is not None:
                _walk_decls(b.else_, f"{path}.else", w, env, out)


def _check_declarations(w: Workflow, out: list[Diagnostic]) -> bool:
    """Every typed-declaration rule, on the authored doc (design 2026-07-20 §2, §4).
    True iff nothing new was found, i.e. the doc is safe to hand to the expander."""
    before = len(out)
    _walk_decls(w.blocks, "blocks", w, {}, out)
    for name, group in w.groups.items():
        where = f"groups[{name!r}]"
        env = {p.name: p for p in group.params}
        _walk_decls(group.body, f"{where}.body", w, env, out)
    return len(out) == before
```

Add the imports at the top of `validate.py`:

```python
from lab_devices.experiment.workflow import (
    REFERENCE_KINDS,
    LocalDecl,
    ParamDecl,
    Workflow,
)
```

Rewire the one call site in `_validate_macro_workflow`:

```python
    expandable = _check_declarations(workflow, out) and expandable
```

and update that function's docstring, replacing `_check_for_each_and_arity` with
`_check_declarations`.

Run to pass:

```
.venv/bin/python -m pytest tests/test_experiment_validate_typed.py -v
```

```
tests/test_experiment_validate_typed.py::test_group_ref_missing_arg_is_reported_per_param PASSED
tests/test_experiment_validate_typed.py::test_group_ref_extra_arg_is_reported_per_arg PASSED
tests/test_experiment_validate_typed.py::test_group_ref_with_exact_args_is_clean PASSED
tests/test_experiment_validate_typed.py::test_for_each_block_level_fields_still_rejected PASSED
=================== 4 passed in 0.40s ====================
```

Commit:

```
git add -A && git commit -m "feat(engine): report group_ref arity per param, on a scoped walker"
```

---

- [ ] **Step 2 — every `for_each` row supplies exactly the declared vars**

Write the failing test. Append to `tests/test_experiment_validate_typed.py`:

```python
def _fe(vars_, rows, body=None):
    return {"for_each": {"vars": vars_, "in": rows, "body": body or [STOP_PUMP]}}


def test_for_each_row_missing_a_declared_var():
    w = wf2([_fe([{"name": "t", "kind": "int"}, {"name": "d", "kind": "number"}],
                 [{"t": 1, "d": 0.5}, {"t": 2}])])
    assert any("'in' row 1 is missing 't'" not in m and "row 1 is missing 'd'" in m
               for m in messages(w))


def test_for_each_row_with_an_extra_key():
    w = wf2([_fe([{"name": "t", "kind": "int"}], [{"t": 1, "ghost": 9}])])
    assert any("'in' row 0 has no variable 'ghost'" in m for m in messages(w))


def test_for_each_row_must_be_an_object():
    w = wf2([_fe([{"name": "t", "kind": "int"}], [{"t": 1}, 2])])
    assert any("'in' row 1 must be an object" in m for m in messages(w))


def test_for_each_rows_matching_the_declaration_are_clean():
    w = wf2([_fe([{"name": "t", "kind": "int"}], [{"t": 1}, {"t": 2}])])
    assert validate(w) is None
```

Run it and see it fail:

```
.venv/bin/python -m pytest tests/test_experiment_validate_typed.py -k for_each_row -v
```

```
tests/test_experiment_validate_typed.py::test_for_each_row_missing_a_declared_var FAILED
tests/test_experiment_validate_typed.py::test_for_each_row_with_an_extra_key FAILED
tests/test_experiment_validate_typed.py::test_for_each_row_must_be_an_object FAILED

E           Failed: DID NOT RAISE <class 'lab_devices.experiment.errors.ValidationError'>
=================== 3 failed, 1 deselected in 0.38s ====================
```

Minimal implementation. Append to `_check_for_each`, after the `vars` emptiness check:

```python
    declared = {v.name: v for v in b.vars}
    for r, row in enumerate(b.items):
        if not isinstance(row, dict):
            out.append(Diagnostic(
                "for_each", path,
                f"for_each 'in' row {r} must be an object mapping every declared var to a "
                f"value, got {row!r}",
            ))
            continue
        for name in declared:
            if name not in row:
                out.append(Diagnostic(
                    "for_each", path, f"for_each 'in' row {r} is missing {name!r}"
                ))
        for name in row:
            if name not in declared:
                out.append(Diagnostic(
                    "for_each", path, f"for_each 'in' row {r} has no variable {name!r}"
                ))
```

Run to pass:

```
.venv/bin/python -m pytest tests/test_experiment_validate_typed.py -v
```

```
=================== 8 passed in 0.41s ====================
```

Commit:

```
git add -A && git commit -m "feat(engine): check every for_each row against its var declarations"
```

---

- [ ] **Step 3 — value-kind arguments match their kind's JSON type**

Write the failing test. Append:

```python
def test_int_param_rejects_a_float_literal():
    w = wf2(
        [{"group_ref": {"name": "svc", "args": {"tube": 1.5}}}],
        groups=_svc([{"name": "tube", "kind": "int"}]),
    )
    assert any("expected int for parameter 'tube', got 1.5" in m for m in messages(w))


def test_int_param_rejects_a_bool_literal():
    w = wf2(
        [{"group_ref": {"name": "svc", "args": {"tube": True}}}],
        groups=_svc([{"name": "tube", "kind": "int"}]),
    )
    assert any("expected int for parameter 'tube', got True" in m for m in messages(w))


def test_bool_param_rejects_an_int_literal():
    w = wf2(
        [{"group_ref": {"name": "svc", "args": {"flag": 1}}}],
        groups=_svc([{"name": "flag", "kind": "bool"}]),
    )
    assert any("expected bool for parameter 'flag', got 1" in m for m in messages(w))


def test_string_param_rejects_a_number():
    w = wf2(
        [{"group_ref": {"name": "svc", "args": {"label": 3}}}],
        groups=_svc([{"name": "label", "kind": "string"}]),
    )
    assert any("expected string for parameter 'label', got 3" in m for m in messages(w))


def test_number_param_accepts_an_int_literal():
    w = wf2(
        [{"group_ref": {"name": "svc", "args": {"dose": 2}}}],
        groups=_svc([{"name": "dose", "kind": "number"}]),
    )
    assert validate(w) is None


def test_for_each_cell_kind_is_checked_too():
    w = wf2([_fe([{"name": "t", "kind": "int"}], [{"t": 1}, {"t": "two"}])])
    assert any("expected int for parameter 't', got 'two'" in m for m in messages(w))
```

Run it and see it fail:

```
.venv/bin/python -m pytest tests/test_experiment_validate_typed.py -k "param_rejects or cell_kind" -v
```

```
tests/test_experiment_validate_typed.py::test_int_param_rejects_a_float_literal FAILED
tests/test_experiment_validate_typed.py::test_int_param_rejects_a_bool_literal FAILED
tests/test_experiment_validate_typed.py::test_bool_param_rejects_an_int_literal FAILED
tests/test_experiment_validate_typed.py::test_string_param_rejects_a_number FAILED
tests/test_experiment_validate_typed.py::test_for_each_cell_kind_is_checked_too FAILED

E           Failed: DID NOT RAISE <class 'lab_devices.experiment.errors.ValidationError'>
=================== 5 failed, 1 deselected in 0.39s ====================
```

Minimal implementation. Add above `_check_group_args`:

```python
def _value_matches(kind: str, value: object) -> bool:
    """JSON type agreement for a value kind (design 2026-07-20 §2). `bool` is checked
    before `int` throughout: in Python `True` IS an `int`, and an author who wrote
    `true` in an int slot made a real mistake."""
    if kind == "bool":
        return isinstance(value, bool)
    if kind == "string":
        return isinstance(value, str)
    if isinstance(value, bool):
        return False
    if kind == "int":
        return isinstance(value, int)
    return isinstance(value, (int, float))


def _check_typed_arg(
    decl: ParamDecl,
    value: object,
    ctx: str,
    w: Workflow,
    env: Mapping[str, ParamDecl],
    out: list[Diagnostic],
) -> None:
    """One `group_ref` arg or one `for_each` cell against its declaration."""
    if not _value_matches(decl.kind, value):
        out.append(Diagnostic(
            "params", ctx, f"expected {decl.kind} for parameter {decl.name!r}, got {value!r}"
        ))
```

Call it from `_check_group_args`, inside the `declared` loop:

```python
    for name, decl in declared.items():
        if name not in b.args:
            out.append(Diagnostic(
                "group", path,
                f"group_ref {b.name!r} is missing argument {name!r} ({decl.kind})",
            ))
        else:
            _check_typed_arg(decl, b.args[name], f"{path} arg {name!r}", w, env, out)
```

and from `_check_for_each`, after the extra-key loop:

```python
        for name, decl in declared.items():
            if name in row:
                _check_typed_arg(
                    decl, row[name], f"{path} in[{r}] {name!r}", w, env, out
                )
```

Run to pass:

```
.venv/bin/python -m pytest tests/test_experiment_validate_typed.py -v
```

```
=================== 14 passed in 0.44s ====================
```

Commit:

```
git add -A && git commit -m "feat(engine): check value-kind arguments against their JSON type"
```

---

- [ ] **Step 4 — reference-kind arguments: role, stream, binding**

Write the failing test. Append:

```python
def test_role_arg_must_name_a_declared_role():
    w = wf2(
        [{"group_ref": {"name": "svc", "args": {"meter": "od_meter_9"}}}],
        groups=_svc([{"name": "meter", "kind": "role",
                      "device_type": "densitometer"}]),
    )
    assert any("names undeclared role 'od_meter_9'" in m for m in messages(w))


def test_role_arg_device_type_must_match_the_declaration():
    w = wf2(
        [{"group_ref": {"name": "svc", "args": {"meter": "medium_pump"}}}],
        groups=_svc([{"name": "meter", "kind": "role",
                      "device_type": "densitometer"}]),
    )
    assert any(
        "role 'medium_pump' has type 'pump', but parameter 'meter' requires "
        "'densitometer'" in m
        for m in messages(w)
    )


def test_role_arg_naming_a_matching_role_is_clean():
    w = wf2(
        [{"group_ref": {"name": "svc", "args": {"meter": "od_meter_1"}}}],
        groups=_svc([{"name": "meter", "kind": "role",
                      "device_type": "densitometer"}]),
    )
    assert validate(w) is None


def test_stream_arg_must_name_a_declared_stream():
    w = wf2(
        [{"group_ref": {"name": "svc", "args": {"od": "od_9"}}}],
        streams=["od_1"],
        groups=_svc([{"name": "od", "kind": "stream"}]),
    )
    assert any("names undeclared stream 'od_9'" in m for m in messages(w))


def test_stream_arg_naming_a_declared_stream_is_clean():
    w = wf2(
        [{"group_ref": {"name": "svc", "args": {"od": "od_1"}}}],
        streams=["od_1"],
        groups=_svc([{"name": "od", "kind": "stream"}]),
    )
    assert validate(w) is None


def test_binding_arg_must_be_identifier_shaped():
    w = wf2(
        [{"group_ref": {"name": "svc", "args": {"c": "9lives"}}}],
        groups=_svc([{"name": "c", "kind": "binding"}]),
    )
    assert any("binding argument '9lives' is not a usable binding name" in m
               for m in messages(w))


def test_binding_arg_may_not_be_a_reserved_name():
    w = wf2(
        [{"group_ref": {"name": "svc", "args": {"c": "not"}}}],
        groups=_svc([{"name": "c", "kind": "binding"}]),
    )
    assert any("binding argument 'not' is not a usable binding name" in m
               for m in messages(w))


def test_binding_arg_may_not_collide_with_a_stream():
    w = wf2(
        [{"group_ref": {"name": "svc", "args": {"c": "od_1"}}}],
        streams=["od_1"],
        groups=_svc([{"name": "c", "kind": "binding"}]),
    )
    assert any("binding argument 'od_1' is already declared as a stream" in m
               for m in messages(w))


def test_reference_arg_must_be_a_string():
    w = wf2(
        [{"group_ref": {"name": "svc", "args": {"od": 3}}}],
        streams=["od_1"],
        groups=_svc([{"name": "od", "kind": "stream"}]),
    )
    assert any("stream argument must be a name string, got 3" in m for m in messages(w))


def test_stream_arg_may_not_name_another_groups_local_by_hand():
    """The scope boundary, pinned as intended behaviour: a group local's qualified name
    is manufactured by the expander and is not a declared stream at this point. Passing
    one by literal spelling is not expressible -- thread a hole instead."""
    groups = {
        "owner": {"locals": {"c_series": {"kind": "stream"}}, "body": [STOP_PUMP]},
        "svc": {"params": [{"name": "od", "kind": "stream"}], "body": [STOP_PUMP]},
    }
    w = wf2(
        [{"group_ref": {"name": "owner", "as": "tube_1"}},
         {"group_ref": {"name": "svc", "args": {"od": "tube_1_c_series"}}}],
        groups=groups,
    )
    assert any("names undeclared stream 'tube_1_c_series'" in m for m in messages(w))
```

Run it and see it fail:

```
.venv/bin/python -m pytest tests/test_experiment_validate_typed.py -k "role_arg or stream_arg or binding_arg or reference_arg" -v
```

```
tests/test_experiment_validate_typed.py::test_role_arg_must_name_a_declared_role FAILED
tests/test_experiment_validate_typed.py::test_role_arg_device_type_must_match_the_declaration FAILED
tests/test_experiment_validate_typed.py::test_role_arg_naming_a_matching_role_is_clean PASSED
tests/test_experiment_validate_typed.py::test_stream_arg_must_name_a_declared_stream FAILED
tests/test_experiment_validate_typed.py::test_stream_arg_naming_a_declared_stream_is_clean PASSED
tests/test_experiment_validate_typed.py::test_binding_arg_must_be_identifier_shaped FAILED
tests/test_experiment_validate_typed.py::test_binding_arg_may_not_be_a_reserved_name FAILED
tests/test_experiment_validate_typed.py::test_binding_arg_may_not_collide_with_a_stream FAILED
tests/test_experiment_validate_typed.py::test_reference_arg_must_be_a_string FAILED
tests/test_experiment_validate_typed.py::test_stream_arg_may_not_name_another_groups_local_by_hand FAILED

E           Failed: DID NOT RAISE <class 'lab_devices.experiment.errors.ValidationError'>
=================== 8 failed, 2 passed, ... ====================
```

(The two passing tests are the clean cases — they pass vacuously today and must keep passing.)

Minimal implementation. Replace `_check_typed_arg`'s body and add the three reference helpers:

```python
def _check_role_arg(
    decl: ParamDecl, value: str, ctx: str, w: Workflow, out: list[Diagnostic]
) -> None:
    role = w.roles.get(value)
    if role is None:
        out.append(Diagnostic(
            "declaration", ctx, f"role argument names undeclared role {value!r}"
        ))
    elif role.type != decl.device_type:
        out.append(Diagnostic(
            "declaration", ctx,
            f"role {value!r} has type {role.type!r}, but parameter {decl.name!r} "
            f"requires {decl.device_type!r}",
        ))


def _check_stream_arg(value: str, ctx: str, w: Workflow, out: list[Diagnostic]) -> None:
    if value not in w.streams:
        out.append(Diagnostic(
            "declaration", ctx, f"stream argument names undeclared stream {value!r}"
        ))


def _check_binding_arg(value: str, ctx: str, w: Workflow, out: list[Diagnostic]) -> None:
    """Bindings have no declaration section -- they are created by their writer
    (`compute.into`, `operator_input.name`), so shape and namespace disjointness are
    the only checks available (design 2026-07-20 §2). Existence stays the job of the
    path-sensitive 'may be read before it is written' rule."""
    if _IDENT_RE.fullmatch(value) is None or value in _RESERVED_NAMES:
        out.append(Diagnostic(
            "params", ctx, f"binding argument {value!r} is not a usable binding name"
        ))
    elif value in w.streams:
        out.append(Diagnostic(
            "declaration", ctx,
            f"binding argument {value!r} is already declared as a stream; a name is a "
            f"binding or a stream, never both",
        ))


def _check_typed_arg(
    decl: ParamDecl,
    value: object,
    ctx: str,
    w: Workflow,
    env: Mapping[str, ParamDecl],
    out: list[Diagnostic],
) -> None:
    """One `group_ref` arg or one `for_each` cell against its declaration. Reference
    kinds resolve against the DECLARED sections only -- see the scope note above."""
    if decl.kind in REFERENCE_KINDS:
        if not isinstance(value, str):
            out.append(Diagnostic(
                "params", ctx,
                f"{decl.kind} argument must be a name string, got {value!r}",
            ))
            return
        if decl.kind == "role":
            _check_role_arg(decl, value, ctx, w, out)
        elif decl.kind == "stream":
            _check_stream_arg(value, ctx, w, out)
        else:
            _check_binding_arg(value, ctx, w, out)
        return
    if not _value_matches(decl.kind, value):
        out.append(Diagnostic(
            "params", ctx, f"expected {decl.kind} for parameter {decl.name!r}, got {value!r}"
        ))
```

Run to pass:

```
.venv/bin/python -m pytest tests/test_experiment_validate_typed.py -v
```

```
=================== 24 passed in 0.51s ====================
```

Commit:

```
git add -A && git commit -m "feat(engine): check role, stream and binding arguments pre-expansion"
```

---

- [ ] **Step 5 — a hole-valued argument resolves its kind from the enclosing binder**

This is the step that makes Step 4 non-vacuous for real documents: inside a `for_each`, a
`group_ref` passes `{"od": "{od}"}`, and `"{od}"` is not a stream name — it is a reference to the
loop's `od` var. Kind agreement between the two declarations is the check.

Write the failing test. Append:

```python
def test_hole_arg_of_the_same_kind_is_clean():
    groups = _svc([{"name": "od", "kind": "stream"}])
    w = wf2(
        [_fe([{"name": "od", "kind": "stream"}],
             [{"od": "od_1"}],
             [{"group_ref": {"name": "svc", "args": {"od": "{od}"}}}])],
        streams=["od_1"],
        groups=groups,
    )
    assert validate(w) is None


def test_hole_arg_of_the_wrong_kind_is_diagnosed():
    groups = _svc([{"name": "od", "kind": "stream"}])
    w = wf2(
        [_fe([{"name": "t", "kind": "int"}],
             [{"t": 1}],
             [{"group_ref": {"name": "svc", "args": {"od": "{t}"}}}])],
        streams=["od_1"],
        groups=groups,
    )
    assert any("int variable 't' cannot bind a stream parameter" in m
               for m in messages(w))


def test_hole_arg_role_device_type_must_agree():
    groups = _svc([{"name": "meter", "kind": "role", "device_type": "densitometer"}])
    w = wf2(
        [_fe([{"name": "p", "kind": "role", "device_type": "pump"}],
             [{"p": "medium_pump"}],
             [{"group_ref": {"name": "svc", "args": {"meter": "{p}"}}}])],
        groups=groups,
    )
    assert any("role<pump> variable 'p' cannot bind a role<densitometer> parameter" in m
               for m in messages(w))


def test_embedded_hole_in_a_reference_arg_is_rejected():
    groups = _svc([{"name": "od", "kind": "stream"}])
    w = wf2(
        [_fe([{"name": "t", "kind": "int"}],
             [{"t": 1}],
             [{"group_ref": {"name": "svc", "args": {"od": "od_{t}"}}}])],
        streams=["od_1"],
        groups=groups,
    )
    assert any("must be a whole name or a whole hole" in m for m in messages(w))


def test_embedded_hole_in_a_value_arg_is_fine():
    groups = _svc([{"name": "label", "kind": "string"}])
    w = wf2(
        [_fe([{"name": "t", "kind": "int"}],
             [{"t": 1}],
             [{"group_ref": {"name": "svc", "args": {"label": "tube {t}: service"}}}])],
        streams=[],
        groups=groups,
    )
    assert validate(w) is None
```

Run it and see it fail:

```
.venv/bin/python -m pytest tests/test_experiment_validate_typed.py -k hole -v
```

`test_hole_arg_of_the_same_kind_is_clean` fails because Step 4 now reads `"{od}"` as a literal
stream name; the three negative tests fail because nothing checks kind agreement yet:

```
tests/test_experiment_validate_typed.py::test_hole_arg_of_the_same_kind_is_clean FAILED
tests/test_experiment_validate_typed.py::test_hole_arg_of_the_wrong_kind_is_diagnosed FAILED
tests/test_experiment_validate_typed.py::test_hole_arg_role_device_type_must_agree FAILED
tests/test_experiment_validate_typed.py::test_embedded_hole_in_a_reference_arg_is_rejected FAILED
tests/test_experiment_validate_typed.py::test_embedded_hole_in_a_value_arg_is_fine PASSED

E       lab_devices.experiment.errors.ValidationError: 1 validation error(s):
E         - [declaration] blocks[0].body[0] arg 'od': stream argument names undeclared
E           stream '{od}'
=================== 4 failed, 1 passed, ... ====================
```

Minimal implementation. Add the hole regexes next to `_IDENT_RE` in `validate.py`:

```python
_HOLE_RE = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")
_WHOLE_HOLE_RE = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}\Z")
```

Add a kind renderer and the hole arm, above `_check_typed_arg`:

```python
def _kind_text(decl: ParamDecl) -> str:
    return f"role<{decl.device_type}>" if decl.kind == "role" else decl.kind
```

and insert this as the FIRST thing `_check_typed_arg` does:

```python
    if isinstance(value, str):
        whole = _WHOLE_HOLE_RE.fullmatch(value)
        if whole is not None:
            inner = env.get(whole.group(1))
            if inner is None:
                return  # bound by nothing in scope: the residual-hole scan is the backstop
            if inner.kind != decl.kind or inner.device_type != decl.device_type:
                out.append(Diagnostic(
                    "params", ctx,
                    f"{_kind_text(inner)} variable {inner.name!r} cannot bind a "
                    f"{_kind_text(decl)} parameter",
                ))
            return
        if decl.kind in REFERENCE_KINDS and _HOLE_RE.search(value) is not None:
            out.append(Diagnostic(
                "params", ctx,
                f"{decl.kind} argument {value!r} embeds a hole; a reference argument must "
                f"be a whole name or a whole hole (design 2026-07-20 §3)",
            ))
            return
```

Populate the environment in `_walk_decls`'s `ForEach` arm — the `inner` dict built in Step 1 is
still a bare copy:

```python
        if isinstance(b, B.ForEach):
            _check_for_each(b, path, w, env, out)
            inner = dict(env)
            for v in b.vars:
                inner[v.name] = v
            _walk_decls(b.body, f"{path}.body", w, inner, out)
            continue
```

Run to pass:

```
.venv/bin/python -m pytest tests/test_experiment_validate_typed.py -v
```

```
=================== 29 passed in 0.55s ====================
```

Commit:

```
git add -A && git commit -m "feat(engine): resolve hole-valued arguments against the enclosing binder"
```

---

- [ ] **Step 6 — param and local names share one namespace**

Write the failing test. Append:

```python
def test_param_and_local_name_collision_is_rejected():
    groups = {"svc": {
        "params": [{"name": "c", "kind": "int"}],
        "locals": {"c": {"kind": "binding"}},
        "body": [STOP_PUMP],
    }}
    w = wf2([{"group_ref": {"name": "svc", "as": "t1", "args": {"c": 1}}}],
            groups=groups)
    assert any("'c' is declared as both a parameter and a local" in m
               for m in messages(w))


def test_duplicate_param_name_is_rejected():
    w = wf2(
        [{"group_ref": {"name": "svc", "args": {"t": 1}}}],
        groups=_svc([{"name": "t", "kind": "int"}, {"name": "t", "kind": "number"}]),
    )
    assert any("duplicate parameter name 't'" in m for m in messages(w))


def test_reserved_param_name_is_rejected():
    w = wf2(
        [{"group_ref": {"name": "svc", "args": {"not": 1}}}],
        groups=_svc([{"name": "not", "kind": "int"}]),
    )
    assert any("declared name 'not' is reserved" in m for m in messages(w))


def test_duplicate_for_each_var_name_is_rejected():
    w = wf2([_fe([{"name": "t", "kind": "int"}, {"name": "t", "kind": "int"}],
                 [{"t": 1}])])
    assert any("duplicate parameter name 't'" in m for m in messages(w))


def test_distinct_param_and_local_names_are_clean():
    groups = {"svc": {
        "params": [{"name": "tube", "kind": "int"}],
        "locals": {"c": {"kind": "binding", "init": "0"}},
        "body": [{"compute": {"into": "{c}", "value": "{c} + {tube}"}}],
    }}
    w = wf2([{"group_ref": {"name": "svc", "as": "t1", "args": {"tube": 1}}}],
            groups=groups)
    assert validate(w) is None
```

Run it and see it fail:

```
.venv/bin/python -m pytest tests/test_experiment_validate_typed.py -k "collision or duplicate or reserved" -v
```

```
tests/test_experiment_validate_typed.py::test_param_and_local_name_collision_is_rejected FAILED
tests/test_experiment_validate_typed.py::test_duplicate_param_name_is_rejected FAILED
tests/test_experiment_validate_typed.py::test_reserved_param_name_is_rejected FAILED
tests/test_experiment_validate_typed.py::test_duplicate_for_each_var_name_is_rejected FAILED

E           Failed: DID NOT RAISE <class 'lab_devices.experiment.errors.ValidationError'>
=================== 4 failed, ... ====================
```

Minimal implementation. Add `_check_decl_names` above `_walk_decls`:

```python
def _check_decl_names(
    decls: list[ParamDecl],
    locals_: Mapping[str, LocalDecl],
    where: str,
    env: Mapping[str, ParamDecl],
    out: list[Diagnostic],
) -> dict[str, ParamDecl]:
    """One binder's names (design 2026-07-20 §2.4). Params and locals share ONE
    namespace: both become `{name}` holes in the same body, so a collision has no
    meaningful resolution. Returns the names this binder introduces."""
    introduced: dict[str, ParamDecl] = {}
    for decl in decls:
        if _IDENT_RE.fullmatch(decl.name) is None:
            out.append(Diagnostic(
                "declaration", where, f"declared name {decl.name!r} is not an identifier"
            ))
        elif decl.name in _RESERVED_NAMES:
            out.append(Diagnostic(
                "declaration", where, f"declared name {decl.name!r} is reserved"
            ))
        if decl.name in introduced:
            out.append(Diagnostic(
                "declaration", where, f"duplicate parameter name {decl.name!r}"
            ))
        introduced[decl.name] = decl
    for name, local in locals_.items():
        if _IDENT_RE.fullmatch(name) is None:
            out.append(Diagnostic(
                "declaration", where, f"declared name {name!r} is not an identifier"
            ))
        elif name in _RESERVED_NAMES:
            out.append(Diagnostic(
                "declaration", where, f"declared name {name!r} is reserved"
            ))
        if name in introduced:
            out.append(Diagnostic(
                "declaration", where,
                f"{name!r} is declared as both a parameter and a local; params and locals "
                f"share one namespace (design 2026-07-20 §2.4)",
            ))
        introduced[name] = ParamDecl(name=name, kind=local.kind)
    return introduced
```

Route both binders through it. In `_walk_decls`'s `ForEach` arm:

```python
            inner = dict(env)
            inner.update(_check_decl_names(b.vars, {}, path, env, out))
```

and in `_check_declarations`'s group loop:

```python
    for name, group in w.groups.items():
        where = f"groups[{name!r}]"
        env = _check_decl_names(group.params, group.locals, where, {}, out)
        _walk_decls(group.body, f"{where}.body", w, env, out)
```

Run to pass:

```
.venv/bin/python -m pytest tests/test_experiment_validate_typed.py -v
```

```
=================== 34 passed in 0.58s ====================
```

Commit:

```
git add -A && git commit -m "feat(engine): enforce one namespace for group params and locals"
```

---

- [ ] **Step 7 — a shadowed enclosing variable is diagnosed**

`expand.py:216-217` carries this as a comment: *"a group `param` name must not collide with an
inner for_each `var` — the param would shadow the loop var (no enforcement here)."* The group's
argument env substitutes into the whole group body first, including the inner loop's `in` rows,
so the loop var never gets a turn. With both sides declared, the collision is now visible.

Write the failing test. Append:

```python
def test_for_each_var_shadowing_a_group_param_is_diagnosed():
    groups = {"svc": {
        "params": [{"name": "t", "kind": "int"}],
        "body": [_fe([{"name": "t", "kind": "int"}], [{"t": 1}, {"t": 2}])],
    }}
    w = wf2([{"group_ref": {"name": "svc", "args": {"t": 1}}}], groups=groups)
    assert any("'t' shadows an enclosing group parameter or for_each variable" in m
               for m in messages(w))


def test_for_each_var_shadowing_a_group_local_is_diagnosed():
    groups = {"svc": {
        "locals": {"c": {"kind": "binding", "init": "0"}},
        "body": [_fe([{"name": "c", "kind": "int"}], [{"c": 1}])],
    }}
    w = wf2([{"group_ref": {"name": "svc", "as": "t1"}}], groups=groups)
    assert any("'c' shadows an enclosing group parameter or for_each variable" in m
               for m in messages(w))


def test_nested_for_each_var_shadowing_is_diagnosed():
    inner = _fe([{"name": "t", "kind": "int"}], [{"t": 9}])
    w = wf2([_fe([{"name": "t", "kind": "int"}], [{"t": 1}], [inner])])
    assert any("'t' shadows an enclosing group parameter or for_each variable" in m
               for m in messages(w))


def test_distinct_nested_var_names_are_clean():
    inner = _fe([{"name": "u", "kind": "int"}], [{"u": 9}])
    w = wf2([_fe([{"name": "t", "kind": "int"}], [{"t": 1}], [inner])])
    assert validate(w) is None
```

Run it and see it fail:

```
.venv/bin/python -m pytest tests/test_experiment_validate_typed.py -k shadow -v
```

```
tests/test_experiment_validate_typed.py::test_for_each_var_shadowing_a_group_param_is_diagnosed FAILED
tests/test_experiment_validate_typed.py::test_for_each_var_shadowing_a_group_local_is_diagnosed FAILED
tests/test_experiment_validate_typed.py::test_nested_for_each_var_shadowing_is_diagnosed FAILED

E           Failed: DID NOT RAISE <class 'lab_devices.experiment.errors.ValidationError'>
=================== 3 failed, 1 passed, ... ====================
```

Minimal implementation. Append the shadow loop to `_check_decl_names`, just before `return`:

```python
    for name in introduced:
        if name in env:
            out.append(Diagnostic(
                "declaration", where,
                f"{name!r} shadows an enclosing group parameter or for_each variable of the "
                f"same name; the outer binding substitutes first and the inner one never "
                f"takes effect (design 2026-07-20 §2.4)",
            ))
    return introduced
```

Then delete the now-obsolete caveat comment at `expand.py:216-217` and replace it with a pointer:

```python
    # A group param / local shadowing an inner for_each var is DIAGNOSED by
    # validate._check_decl_names (design 2026-07-20 §2.4); it is no longer a silent hazard.
```

Run to pass:

```
.venv/bin/python -m pytest tests/test_experiment_validate_typed.py -v
```

```
=================== 38 passed in 0.61s ====================
```

Commit:

```
git add -A && git commit -m "feat(engine): diagnose a shadowed for_each variable"
```

---

- [ ] **Step 8 — a local's `init` is a constant expression only**

Design §2.3: the expander hoists one `compute` per initialized local to the very front of
`workflow.blocks`, so anything the initializer could read is guaranteed unwritten at that point.
Permitting a read would produce a read-before-write diagnostic blaming a block the author never
wrote at a position they never chose. Restricting `init` makes the hoist total and
order-insensitive.

Write the failing test. Append:

```python
def _local_group(init):
    return {"svc": {
        "locals": {"c": {"kind": "binding", "init": init}},
        "body": [{"compute": {"into": "{c}", "value": "{c} + 1"}}],
    }}


def test_local_init_may_not_reference_a_binding():
    w = wf2([{"group_ref": {"name": "svc", "as": "t1"}}],
            groups=_local_group("seed + 1"))
    msgs = messages(w)
    assert any("init must be a constant expression, but reads 'seed'" in m for m in msgs)


def test_local_init_may_not_call_a_stat():
    w = wf2([{"group_ref": {"name": "svc", "as": "t1"}}],
            streams=["od_1"],
            groups=_local_group("mean(od_1, last=5min)"))
    assert any("init must be a constant expression, but reads 'od_1'" in m
               for m in messages(w))


def test_local_init_may_not_count_a_stream():
    w = wf2([{"group_ref": {"name": "svc", "as": "t1"}}],
            streams=["od_1"],
            groups=_local_group("count(od_1) > 0"))
    assert any("init must be a constant expression, but reads 'od_1'" in m
               for m in messages(w))


def test_local_init_with_a_bad_expression_is_diagnosed():
    w = wf2([{"group_ref": {"name": "svc", "as": "t1"}}],
            groups=_local_group("0 +"))
    assert any("invalid init expression" in m for m in messages(w))


def test_constant_local_inits_are_clean():
    for init in ("0", "false", "2 * 3 + 1", "true and not false"):
        w = wf2([{"group_ref": {"name": "svc", "as": "t1"}}],
                groups=_local_group(init))
        assert validate(w) is None, init
```

Run it and see it fail:

```
.venv/bin/python -m pytest tests/test_experiment_validate_typed.py -k local_init -v
```

```
tests/test_experiment_validate_typed.py::test_local_init_may_not_reference_a_binding FAILED
tests/test_experiment_validate_typed.py::test_local_init_may_not_call_a_stat FAILED
tests/test_experiment_validate_typed.py::test_local_init_may_not_count_a_stream FAILED
tests/test_experiment_validate_typed.py::test_local_init_with_a_bad_expression_is_diagnosed FAILED

E           Failed: DID NOT RAISE <class 'lab_devices.experiment.errors.ValidationError'>
=================== 4 failed, 1 passed, ... ====================
```

Minimal implementation. Add `_check_local_init` above `_check_declarations`:

```python
def _check_local_init(
    name: str, local: LocalDecl, where: str, out: list[Diagnostic]
) -> None:
    """`init` must be a CONSTANT expression: literals and operators over them, with no
    stat calls, no stream references and no binding references (design 2026-07-20 §2.3).
    The initializer is hoisted ahead of every block in the document, so any data
    dependency it could express is guaranteed unwritten when it runs.

    Task 5's parser already rejects `init` on a stream-kinded local, so only the
    binding case reaches here."""
    if local.init is None:
        return
    try:
        expr = parse_expression(local.init)
    except ExpressionError as exc:
        out.append(Diagnostic("declaration", where, f"invalid init expression: {exc}"))
        return
    refs = references(expr)
    named = sorted(refs.bindings | refs.streams_windowed | refs.streams_counted)
    if named:
        reads = ", ".join(repr(n) for n in named)
        out.append(Diagnostic(
            "declaration", where,
            f"local {name!r} init must be a constant expression, but reads {reads}; the "
            f"initializer is hoisted ahead of every block, so nothing it could read is "
            f"written yet (design 2026-07-20 §2.3)",
        ))
```

Call it from `_check_declarations`'s group loop:

```python
    for name, group in w.groups.items():
        where = f"groups[{name!r}]"
        env = _check_decl_names(group.params, group.locals, where, {}, out)
        for local_name, local in group.locals.items():
            _check_local_init(
                local_name, local, f"{where}.locals[{local_name!r}]", out
            )
        _walk_decls(group.body, f"{where}.body", w, env, out)
```

Run to pass, then the full gate:

```
.venv/bin/python -m pytest tests/test_experiment_validate_typed.py -v
```

```
=================== 43 passed in 0.66s ====================
```

```
.venv/bin/python -m pytest
.venv/bin/python -m mypy src/lab_devices
.venv/bin/python -m ruff check .
awk 'length>100' src/lab_devices/experiment/validate.py tests/test_experiment_validate_typed.py
```

Expect a clean `pytest`, `Success: no issues found`, `All checks passed!`, and no `awk` output.

Commit:

```
git add -A && git commit -m "feat(engine): require group local init to be a constant expression"
```

---

### Task 8: Runtime role resolution and injectivity

**Files:**
- `src/lab_devices/experiment/context.py` (modified — `RunOptions.role_mapping`,
  `RunContext.role_devices`, `RunContext.device`)
- `src/lab_devices/experiment/run.py` (modified — `_resolve_roles`, `ExperimentRun.__init__`,
  `RunReport.role_devices`)
- `src/lab_devices/experiment/finalize.py` (modified — sweep type lookup)
- `src/lab_devices/experiment/execute.py` (modified — five registry call sites)
- `tests/experiment_run_helpers.py` (modified — `roles` kwarg on `make_workflow`)
- `tests/test_experiment_roles_runtime.py` (new)
- `tests/test_experiment_role_affinity.py` (new)

**Interfaces:**

*Consumes*:
```python
# lab_devices.experiment.workflow
@dataclass(frozen=True)
class RoleDecl:
    type: str
    device: str | None = None

class Workflow:
    roles: dict[str, RoleDecl]
    def role_type(self, role: str) -> str: ...   # raises UnknownRoleError

# lab_devices.experiment.errors
class UnknownRoleError(WorkflowLoadError): ...

# lab_devices.experiment.registry  (Task 2)
def lookup(dtype: str, verb: str) -> Trait
def mode_action(dtype: str, verb: str, params: Mapping[str, object]) -> ModeAction | None
# registry.device_type is DELETED
```
Task 2 re-signatured `lookup`/`mode_action` and, to keep every intermediate commit green,
routed all thirteen call sites in `serialize.py`, `validate.py`, `execute.py` and `finalize.py`
through the transitional shim `_legacy_ids.legacy_device_type` — the last surviving copy of the
`rsplit("_", 1)` convention. **Task 8 is the shim's executioner.** It converts every site to read
the declared type and then deletes `_legacy_ids.py` outright (Step 7). Until Step 7 lands, spec
§5.2's claim that the hack is gone is not yet true.

Verify the starting state before touching anything:

```
grep -rn "legacy_device_type" src/lab_devices/experiment/
```
Expected: the definition in `_legacy_ids.py` plus its call sites in `serialize.py`,
`validate.py`, `execute.py`, `finalize.py`.

*Produces*:
```python
# context.py
@dataclass
class RunOptions:
    ...
    role_mapping: dict[str, str] = field(default_factory=dict)

@dataclass
class RunContext:
    ...
    role_devices: dict[str, str] = field(default_factory=dict)

    def device(self, role: str) -> Device:
        """Resolve a ROLE to its LabClient handle. The one place a physical id is used."""
        if role not in self.devices:
            self.devices[role] = self.client.device(self.role_devices[role])
        return self.devices[role]

# run.py
def _resolve_roles(workflow: Workflow, mapping: dict[str, str]) -> dict[str, str]

@dataclass
class RunReport:
    ...
    role_devices: dict[str, str] = field(default_factory=dict)
```

**CRITICAL invariant — do not "fix" this into device ids.** `ctx.lock`, `Occupancy._slots`,
`ctx.touched`, `ctx.in_flight` and every event payload keep keying on the **role name**, in
exactly their current shape. Injectivity (§5.4) is what makes that sound: role names and device
ids are in bijection, so occupancy and affinity keyed by either yield identical behaviour, and
the role name is what the author wrote and what a diagnostic should say. Exactly **one** site
resolves to a physical id — `ctx.device(role)`, at the wire boundary. Step 5 pins this with a
test; if a later change makes it fail, the change is wrong, not the test.

---

- [ ] **Step 1 — `role_mapping`, `role_devices`, and `RunContext.device(role)`**

Write the failing test. First extend the shared helper, `tests/experiment_run_helpers.py`:

```python
def make_workflow(
    blocks: list[dict[str, Any]],
    *,
    streams: dict[str, Any] | None = None,
    groups: dict[str, Any] | None = None,
    persistence: dict[str, Any] | None = None,
    roles: dict[str, Any] | None = None,
) -> Workflow:
    doc: dict[str, Any] = {"schema_version": 2, "blocks": blocks}
    if streams is not None:
        doc["streams"] = streams
    if groups is not None:
        doc["groups"] = groups
    if persistence is not None:
        doc["persistence"] = persistence
    doc["roles"] = STANDARD_ROLES if roles is None else roles
    workflow = workflow_from_dict(doc)
    assign_block_ids(workflow)
    return workflow
```

and add, above it, the roster that matches `add_standard_devices` one-to-one (so every existing
executor test keeps its device names and gains an identity mapping):

```python
STANDARD_ROLES: dict[str, Any] = {
    "pump_1": {"type": "pump", "device": "pump_1"},
    "pump_2": {"type": "pump", "device": "pump_2"},
    "valve_1": {"type": "valve", "device": "valve_1"},
    "densitometer_1": {"type": "densitometer", "device": "densitometer_1"},
}
```

Now create `tests/test_experiment_roles_runtime.py`:

```python
import pytest

from lab_devices.experiment.context import RunContext, RunOptions
from lab_devices.experiment.state import RunState
from tests.experiment_run_helpers import add_standard_devices, make_workflow
from tests.fakeclock import FakeClock


def make_ctx(client, role_devices):
    return RunContext(
        client=client,
        workflow=make_workflow([]),
        state=RunState(),
        options=RunOptions(clock=FakeClock()),
        role_devices=dict(role_devices),
    )


def test_run_options_carries_a_role_mapping():
    options = RunOptions(role_mapping={"od_meter": "densitometer_1"})
    assert options.role_mapping == {"od_meter": "densitometer_1"}
    assert RunOptions().role_mapping == {}


async def test_context_device_resolves_a_role_to_its_physical_handle(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    ctx = make_ctx(client, {"od_meter": "densitometer_1"})
    device = ctx.device("od_meter")
    assert device.device_id == "densitometer_1"
    assert set(ctx.devices) == {"od_meter"}   # cached under the ROLE
    assert ctx.device("od_meter") is device   # one handle per role


async def test_context_device_raises_for_an_unmapped_role(fake_client):
    _, client = fake_client
    ctx = make_ctx(client, {})
    with pytest.raises(KeyError):
        ctx.device("od_meter")
```

Run it and see it fail:

```
.venv/bin/python -m pytest tests/test_experiment_roles_runtime.py -v
```

```
tests/test_experiment_roles_runtime.py::test_run_options_carries_a_role_mapping FAILED
tests/test_experiment_roles_runtime.py::test_context_device_resolves_a_role_to_its_physical_handle FAILED
tests/test_experiment_roles_runtime.py::test_context_device_raises_for_an_unmapped_role FAILED

E       TypeError: RunOptions.__init__() got an unexpected keyword argument 'role_mapping'
E       TypeError: RunContext.__init__() got an unexpected keyword argument 'role_devices'
=================== 3 failed in 0.35s ====================
```

Minimal implementation. In `context.py`, append to `RunOptions` (last field, so the
positional-construction sites elsewhere are unaffected):

```python
    role_mapping: dict[str, str] = field(default_factory=dict)
    # Role -> physical device id for THIS run (design 2026-07-20 §5.2). Overrides a role's
    # own `device:`. Resolved and checked for injectivity once, in run._resolve_roles.
```

Add the field to `RunContext`, next to `devices`:

```python
    role_devices: dict[str, str] = field(default_factory=dict)
```

and replace `RunContext.device`:

```python
    def device(self, role: str) -> Device:
        """Resolve a ROLE to its LabClient handle. The one place in the engine where a
        physical device id is used — the wire boundary (design 2026-07-20 §5.2). Every
        other structure (locks, occupancy, touched, in_flight, events) keys on the role
        name, which injectivity (§5.4) makes equivalent and which is what the author
        wrote."""
        if role not in self.devices:
            self.devices[role] = self.client.device(self.role_devices[role])
        return self.devices[role]
```

Run to pass:

```
.venv/bin/python -m pytest tests/test_experiment_roles_runtime.py -v
```

```
=================== 3 passed in 0.36s ====================
```

Commit:

```
git add -A && git commit -m "feat(engine): resolve roles to device handles in RunContext"
```

---

- [ ] **Step 2 — `_resolve_roles`, called before `validate()`**

Write the failing test. Append to `tests/test_experiment_roles_runtime.py`:

```python
from lab_devices.experiment.errors import UnknownRoleError, WorkflowLoadError
from lab_devices.experiment.run import ExperimentRun, _resolve_roles

TWO_PUMPS = {"left": {"type": "pump"}, "right": {"type": "pump"}}
STOP_BOTH = [{"command": {"device": "left", "verb": "stop"}},
             {"command": {"device": "right", "verb": "stop"}}]


def test_resolve_roles_prefers_the_mapping_over_the_declaration():
    w = make_workflow(STOP_BOTH, roles={"left": {"type": "pump", "device": "pump_1"},
                                        "right": {"type": "pump", "device": "pump_2"}})
    resolved = _resolve_roles(w, {"left": "valve_1"})
    assert resolved == {"left": "valve_1", "right": "pump_2"}


def test_resolve_roles_rejects_an_unbound_role():
    w = make_workflow(STOP_BOTH, roles=TWO_PUMPS)
    with pytest.raises(WorkflowLoadError, match="role 'left' is not bound to a device"):
        _resolve_roles(w, {"right": "pump_2"})


def test_resolve_roles_rejects_a_non_injective_mapping():
    w = make_workflow(STOP_BOTH, roles=TWO_PUMPS)
    with pytest.raises(WorkflowLoadError, match="must be injective"):
        _resolve_roles(w, {"left": "pump_1", "right": "pump_1"})


def test_resolve_roles_rejects_a_mapping_for_an_unknown_role():
    w = make_workflow(STOP_BOTH, roles=TWO_PUMPS)
    with pytest.raises(UnknownRoleError, match="ghost"):
        _resolve_roles(w, {"left": "pump_1", "right": "pump_2", "ghost": "valve_1"})


async def test_run_construction_rejects_a_non_injective_mapping(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    w = make_workflow(STOP_BOTH, roles=TWO_PUMPS)
    options = RunOptions(clock=FakeClock(),
                         role_mapping={"left": "pump_1", "right": "pump_1"})
    with pytest.raises(WorkflowLoadError, match="must be injective"):
        ExperimentRun(client, w, options=options)
    assert fake.calls == []  # nothing reached the wire


async def test_run_construction_accepts_distinct_devices(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    w = make_workflow(STOP_BOTH, roles=TWO_PUMPS)
    options = RunOptions(clock=FakeClock(),
                         role_mapping={"left": "pump_1", "right": "pump_2"})
    run = ExperimentRun(client, w, options=options)
    assert run._ctx.role_devices == {"left": "pump_1", "right": "pump_2"}
```

Run it and see it fail:

```
.venv/bin/python -m pytest tests/test_experiment_roles_runtime.py -k resolve_roles -v
```

```
E   ImportError: cannot import name '_resolve_roles' from 'lab_devices.experiment.run'
=================== 6 errors in 0.30s ====================
```

Minimal implementation. In `run.py`, import the two error classes and add above `RunReport`:

```python
def _resolve_roles(workflow: Workflow, mapping: dict[str, str]) -> dict[str, str]:
    """Role -> physical device id for one run (design 2026-07-20 §5.2, §5.4).

    `options.role_mapping` overrides a role's own `device:`; a role bound by neither is an
    error. The result is INJECTIVE by construction. That is load-bearing, not hygiene: the
    affinity and mode analyses intersect raw device strings and `Occupancy._slots` keys them,
    so two roles aliasing one device would pass every static check and then collide at run
    time on one (device, channel) slot — raising an InvariantViolationError that `_NEVER_RETRY`
    refuses to retry and `_tolerable` refuses to absorb. A statically clean workflow would die
    mid-run, unrecoverably. With injectivity, role names and device ids are in bijection and
    the static proof is sound by construction (§5.4).
    """
    for role in mapping:
        if role not in workflow.roles:
            raise UnknownRoleError(
                f"role_mapping names {role!r}, which is not a declared role; the workflow "
                f"declares {sorted(workflow.roles)}"
            )
    resolved: dict[str, str] = {}
    owner: dict[str, str] = {}
    for role, decl in workflow.roles.items():
        device = mapping.get(role, decl.device)
        if device is None:
            raise WorkflowLoadError(
                f"role {role!r} is not bound to a device: give it a 'device' in the "
                f"workflow's roles section, or supply one in RunOptions.role_mapping"
            )
        if device in owner:
            raise WorkflowLoadError(
                f"roles {owner[device]!r} and {role!r} both map to device {device!r}; the "
                f"role->device mapping must be injective (design 2026-07-20 §5.4)"
            )
        owner[device] = role
        resolved[role] = device
    return resolved
```

Rewire `ExperimentRun.__init__` — note `self._options` moves ABOVE the validation gate, because
the mapping it carries is now part of what gets checked:

```python
    def __init__(
        self, client: LabClient, workflow: Workflow, options: RunOptions | None = None
    ) -> None:
        self._options = options or RunOptions()
        # Resolution FIRST: a bad mapping is a fact about this run, not about the document,
        # and reporting it before the (slower, noisier) static pass keeps the two separable.
        role_devices = _resolve_roles(workflow, self._options.role_mapping)
        validate(workflow)  # the runtime's safety model IS the static proof (D6)
        workflow = expand_workflow(workflow)  # run the concrete tree (design 2026-07-15 §4.4)
        assign_block_ids(workflow)
        self._workflow = workflow
        state = RunState()
        for stream_name in workflow.streams:
            state.streams[stream_name] = Stream()  # pre-created: count()==0 (§3)
        self._ctx = RunContext(
            client=client, workflow=workflow, state=state, options=self._options,
            role_devices=role_devices,
        )
        self._task: asyncio.Task[object] | None = None
        self._started = False
        self._finalizing = False
        self.report: RunReport | None = None
        self._sinks: SinkSet | None = None
        self._flush_task: asyncio.Task[None] | None = None
        self._sinks_closed = False
```

Add to the `errors` import block in `run.py`:

```python
    UnknownRoleError,
    WorkflowLoadError,
```

Run to pass:

```
.venv/bin/python -m pytest tests/test_experiment_roles_runtime.py -v
```

```
=================== 9 passed in 0.44s ====================
```

Commit:

```
git add -A && git commit -m "feat(engine): resolve and injectivity-check roles at run start"
```

---

- [ ] **Step 3 — `RunReport.role_devices`**

The mapping is recorded once on the report rather than duplicated into every event payload
(design §5.2).

Write the failing test. Append to `tests/test_experiment_roles_runtime.py`:

```python
from tests.fakeclock import drive


async def test_report_records_the_role_mapping_once(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    w = make_workflow(
        [{"command": {"device": "left", "verb": "stop"}}],
        roles={"left": {"type": "pump", "device": "pump_1"}},
    )
    clock = FakeClock()
    run = ExperimentRun(client, w, options=RunOptions(clock=clock))
    report = await drive(clock, run.execute())
    assert report.status == "completed"
    assert report.role_devices == {"left": "pump_1"}
    payloads = [e.data for e in report.log.events if "device" in e.data]
    assert payloads and all(p["device"] == "left" for p in payloads)


async def test_failed_report_also_records_the_mapping(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    w = make_workflow(
        [{"command": {"device": "left", "verb": "stop"}}],
        roles={"left": {"type": "pump", "device": "pump_1"}},
        persistence={"default": "disk", "format": "jsonl"},
    )
    run = ExperimentRun(client, w, options=RunOptions(clock=FakeClock()))
    with pytest.raises(Exception):
        await run.execute()
    assert run.report is not None
    assert run.report.role_devices == {"left": "pump_1"}
```

Run it and see it fail:

```
.venv/bin/python -m pytest tests/test_experiment_roles_runtime.py -k report -v
```

```
tests/test_experiment_roles_runtime.py::test_report_records_the_role_mapping_once FAILED
tests/test_experiment_roles_runtime.py::test_failed_report_also_records_the_mapping FAILED

E       AttributeError: 'RunReport' object has no attribute 'role_devices'
=================== 2 failed, ... ====================
```

Minimal implementation. In `run.py`, add `field` to the dataclasses import and append the field
to `RunReport` — **last**, with a default, because the persistence-failure path constructs
`RunReport` positionally:

```python
    role_devices: dict[str, str] = field(default_factory=dict)
    # The role -> physical device id mapping this run used, recorded ONCE (design §5.2).
    # Events carry role names; this is where a reader turns one into hardware.
```

Set it at both construction sites. The early failure path:

```python
            self.report = RunReport(
                "failed", exc, (), ctx.state, ctx.log_sink,
                role_devices=dict(ctx.role_devices),
            )
```

and the normal one:

```python
        self.report = RunReport(
            status=status, error=error, finalize_errors=finalize_errors,
            state=ctx.state, log=sinks.log_sink,
            persistence_errors=sinks.persistence_errors(),
            tolerated_errors=tuple(ctx.tolerated),
            alarms=tuple(ctx.alarms),
            role_devices=dict(ctx.role_devices),
        )
```

Run to pass:

```
.venv/bin/python -m pytest tests/test_experiment_roles_runtime.py -v
```

```
=================== 11 passed in 0.49s ====================
```

Commit:

```
git add -A && git commit -m "feat(engine): record the role mapping on RunReport"
```

---

- [ ] **Step 4 — type lookups read `workflow.roles[...].type`**

Write the failing test. Append to `tests/test_experiment_roles_runtime.py` — a workflow whose
role names deliberately do **not** decode to a device type under the old `rsplit("_", 1)`
convention, which is what makes the test non-vacuous:

```python
OD_ROLES = {"culture_vessel": {"type": "densitometer", "device": "densitometer_1"}}


async def test_verbs_resolve_through_the_role_declaration(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    w = make_workflow(
        [{"measure": {"device": "culture_vessel", "verb": "measure", "into": "OD"}}],
        streams={"OD": {"units": "AU"}},
        roles=OD_ROLES,
    )
    clock = FakeClock()
    run = ExperimentRun(client, w, options=RunOptions(clock=clock))
    report = await drive(clock, run.execute())
    assert report.status == "completed"
    assert len(report.state.streams["OD"]) == 1  # result_field came from the registry


async def test_finalizer_sweeps_by_declared_type_not_by_id(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    w = make_workflow(
        [{"measure": {"device": "culture_vessel", "verb": "measure", "into": "OD"}}],
        streams={"OD": {}},
        roles=OD_ROLES,
    )
    clock = FakeClock()
    run = ExperimentRun(client, w, options=RunOptions(clock=clock))
    report = await drive(clock, run.execute())
    assert report.status == "completed"
    swept = [(dev, cmd) for dev, cmd, _ in fake.calls if dev == "densitometer_1"]
    assert ("densitometer_1", "stop_monitoring") in swept
    assert ("densitometer_1", "set_led") in swept
```

Run it and see it fail:

```
.venv/bin/python -m pytest tests/test_experiment_roles_runtime.py -k "resolve_through or sweeps_by" -v
```

```
tests/test_experiment_roles_runtime.py::test_verbs_resolve_through_the_role_declaration FAILED
tests/test_experiment_roles_runtime.py::test_finalizer_sweeps_by_declared_type_not_by_id FAILED

E   lab_devices.experiment.errors.UnknownVerbError: no registry entry for
E   device-type 'culture' verb 'measure'
=================== 2 failed in 0.31s ====================
```

That message is the whole point of the test: the shim reduces the role name
`culture_vessel` to `'culture'` by `rsplit("_", 1)`, which is not a device type at all. A role
name is not a device id and cannot be decoded into one — only the declaration knows.

```
```

Minimal implementation. In `finalize.py`, drop the `registry` import entirely and rewrite the
sweep loop (step 3 of `run_finalizer`). Note `ctx.touched` keeps iterating by **role**, and
`_issue`'s event payload keeps its `device=` key — its value is now the role name, which is what
the author wrote:

```python
    # 3. Unconditional idempotent safe-state sweep over every touched role. The role
    #    addresses the device; its DECLARED type selects the sweep verbs (design §5.2).
    for role in ctx.touched:
        decl = ctx.workflow.roles.get(role)
        if decl is None:  # unreachable for a validated workflow; the sweep must never raise
            continue
        for verb, params in _SWEEP.get(decl.type, ()):
            await _issue(ctx, role, verb, dict(params), "sweep_command", errors)
```

Rename `_issue`'s first parameter from `device_id` to `role` (body unchanged apart from the
name: `ctx.device(role)`, `ctx.lock(role)`, `device=role` in both `_emit` calls). Do the same
for step 1's loop variable, which iterates `ctx.in_flight` values — those are role names too.

In `execute.py`, convert the five sites:

```python
# _run_action, line ~209
    policy = _effective_retry(
        block, lookup(ctx.workflow.role_type(block.device), block.verb), ctx
    )

# _modes_a_stop_would_close, line ~267  (`device` here is a role name)
        stop_channels: frozenset[str] | None = lookup(
            ctx.workflow.role_type(device), "stop"
        ).channels

# _dispatch_action, lines ~368-370
    dtype = ctx.workflow.role_type(block.device)
    trait = lookup(dtype, block.verb)
    params = _resolve_params(block, trait, ctx)
    action = mode_action(dtype, block.verb, params)  # on RESOLVED values (D7)

# _run_measure, line ~630
    field_name = lookup(
        ctx.workflow.role_type(block.device), block.verb
    ).result_field
```

Everything downstream of these lines is untouched: `ctx.touched.setdefault(block.device)`,
`ctx.occupancy.acquire(block.device, ...)`, `ctx.lock(block.device)`, `ctx.in_flight[job.job_id]
= (block.device, job)`, `OpenMode(device=block.device, ...)` and every `_emit(..., device=
block.device)` all keep the role name.

Verify no `rsplit` convention survives anywhere:

```
grep -rn 'rsplit("_", 1)' src/lab_devices/
```

Expect no output.

Run to pass:

```
.venv/bin/python -m pytest tests/test_experiment_roles_runtime.py -v
```

```
=================== 13 passed in 0.57s ====================
```

Commit:

```
git add -A && git commit -m "feat(engine): read device types from role declarations at run time"
```

---

- [ ] **Step 5 — pin the role-keying invariant**

Write the test. Append to `tests/test_experiment_roles_runtime.py`:

```python
async def test_every_engine_structure_keys_on_the_role_name(fake_client):
    """The §5.2 invariant, pinned. If a later change makes this fail, the change is
    wrong: locks, occupancy, touched, in_flight and event payloads all key on the ROLE,
    and `ctx.device(role)` is the single site where a physical id appears."""
    fake, client = fake_client
    add_standard_devices(fake)
    w = make_workflow(
        [{"measure": {"device": "culture_vessel", "verb": "measure", "into": "OD"}}],
        streams={"OD": {}},
        roles=OD_ROLES,
    )
    clock = FakeClock()
    run = ExperimentRun(client, w, options=RunOptions(clock=clock))
    report = await drive(clock, run.execute())
    assert report.status == "completed"

    ctx = run._ctx
    assert list(ctx.touched) == ["culture_vessel"]
    assert set(ctx.locks) == {"culture_vessel"}
    assert set(ctx.devices) == {"culture_vessel"}   # handle cached under the role
    assert ctx.occupancy.busy_devices() == set()    # released, by role key
    assert ctx.role_devices == {"culture_vessel": "densitometer_1"}

    payloads = [e.data["device"] for e in report.log.events if "device" in e.data]
    assert payloads and set(payloads) == {"culture_vessel"}

    # ...and the wire, and only the wire, saw the physical id.
    assert ("densitometer_1", "measure") in [(d, c) for d, c, _ in fake.calls]
    assert not any(d == "culture_vessel" for d, _c, _p in fake.calls)


async def test_occupancy_slots_key_on_the_role_name(fake_client):
    from lab_devices.experiment import blocks as B
    from lab_devices.experiment.execute import _dispatch_action

    fake, client = fake_client
    add_standard_devices(fake)
    fake.hold_job("dispense")
    w = make_workflow([], roles={"feed": {"type": "pump", "device": "pump_2"}})
    ctx = RunContext(
        client=client, workflow=w, state=RunState(),
        options=RunOptions(clock=FakeClock()),
        role_devices={"feed": "pump_2"},
    )
    block = B.Command(device="feed", verb="dispense", params={"volume_ml": 1.0}, id="b0")
    task = asyncio.ensure_future(_dispatch_action(block, ctx, []))
    await ctx.options.clock.settle()
    assert ctx.occupancy.busy_devices() == {"feed"}
    assert ctx.occupancy.is_busy("feed") and not ctx.occupancy.is_busy("pump_2")
    task.cancel()
    try:
        await task
    except BaseException:
        pass
```

Add `import asyncio` to the test module's imports.

Run it:

```
.venv/bin/python -m pytest tests/test_experiment_roles_runtime.py -k "keys_on_the_role or slots_key" -v
```

Both should pass on the first run — Steps 1-4 already established the invariant, and these tests
exist to keep it. Confirm they are not vacuous by temporarily changing
`ctx.touched.setdefault(block.device)` in `execute.py` to
`ctx.touched.setdefault(ctx.role_devices[block.device])` and re-running:

```
E       assert ['densitometer_1'] == ['culture_vessel']
=================== 1 failed, 1 passed ====================
```

Revert the change and re-run to green:

```
=================== 2 passed in 0.38s ====================
```

Commit:

```
git add -A && git commit -m "test(engine): pin role-name keying across locks, occupancy and events"
```

---

- [ ] **Step 6 — affinity equivalence (design §10)**

The property §5.4 leans on: with an injective mapping, a workflow analysed by **role name** is
diagnosed identically to the same workflow analysed by **mapped device id**. And the converse —
a *non*-injective mapping is exactly where the two analyses diverge, which is why it is rejected.

Write the test. Create `tests/test_experiment_role_affinity.py`:

```python
import json

import pytest

from lab_devices.experiment.context import RunOptions
from lab_devices.experiment.errors import ValidationError, WorkflowLoadError
from lab_devices.experiment.run import ExperimentRun
from lab_devices.experiment.serialize import workflow_from_dict
from lab_devices.experiment.validate import validate
from tests.experiment_run_helpers import add_standard_devices
from tests.fakeclock import FakeClock, drive


def _doc(roles, lanes):
    return {
        "schema_version": 2,
        "roles": roles,
        "streams": {},
        "blocks": [{"parallel": {"children": lanes}}],
    }


def _dispense(role):
    return {"command": {"device": role, "verb": "dispense",
                        "params": {"volume_ml": 1.0}}}


def _rebind(doc, mapping):
    """The same document with every ROLE NAME replaced by its mapped device id --
    i.e. the document Studio used to hand the engine before roles moved in (§5.4)."""
    text = json.dumps(doc)
    for role, device in mapping.items():
        text = text.replace(f'"{role}"', f'"{device}"')
    rebound = json.loads(text)
    rebound["roles"] = {
        device: {"type": doc["roles"][role]["type"], "device": device}
        for role, device in mapping.items()
    }
    return rebound


def _diag_keys(doc):
    """Category+path of every diagnostic. Messages are excluded on purpose: they embed
    the device string, which is the one thing that legitimately differs."""
    try:
        validate(workflow_from_dict(doc))
    except ValidationError as exc:
        return sorted((d.category, d.path) for d in exc.diagnostics)
    return []


TWO_ROLES = {"left_feed": {"type": "pump", "device": "pump_1"},
             "right_feed": {"type": "pump", "device": "pump_2"}}
INJECTIVE = {"left_feed": "pump_1", "right_feed": "pump_2"}


def test_disjoint_lanes_agree_under_both_analyses():
    doc = _doc(TWO_ROLES, [_dispense("left_feed"), _dispense("right_feed")])
    assert _diag_keys(doc) == []
    assert _diag_keys(_rebind(doc, INJECTIVE)) == []


def test_conflicting_lanes_agree_under_both_analyses():
    doc = _doc(TWO_ROLES, [_dispense("left_feed"), _dispense("left_feed")])
    by_role = _diag_keys(doc)
    by_device = _diag_keys(_rebind(doc, INJECTIVE))
    assert by_role == by_device
    assert ("affinity", "blocks[0]") in by_role  # not vacuously equal: both DIAGNOSE


def test_a_non_injective_mapping_is_exactly_where_the_two_analyses_diverge(fake_client):
    """Two distinct roles, two disjoint lanes -- clean by role name. Alias them onto one
    device and the device-id analysis reports an affinity conflict the role-name analysis
    cannot see. That divergence is the runtime collision §5.4 describes, and it is why
    the mapping must be injective: _resolve_roles refuses it before validate() runs."""
    fake, client = fake_client
    add_standard_devices(fake)
    doc = _doc(TWO_ROLES, [_dispense("left_feed"), _dispense("right_feed")])
    aliased = {"left_feed": "pump_1", "right_feed": "pump_1"}

    assert _diag_keys(doc) == []
    assert ("affinity", "blocks[0]") in _diag_keys(_rebind(doc, aliased))

    with pytest.raises(WorkflowLoadError, match="must be injective"):
        ExperimentRun(client, workflow_from_dict(doc),
                      options=RunOptions(clock=FakeClock(), role_mapping=aliased))
    assert fake.calls == []


async def test_the_injective_mapping_of_that_same_workflow_runs(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    doc = _doc(TWO_ROLES, [_dispense("left_feed"), _dispense("right_feed")])
    clock = FakeClock()
    run = ExperimentRun(client, workflow_from_dict(doc),
                        options=RunOptions(clock=clock, role_mapping=INJECTIVE))
    report = await drive(clock, run.execute())
    assert report.status == "completed"
    assert report.role_devices == INJECTIVE
    dispensed = {d for d, c, _ in fake.calls if c == "dispense"}
    assert dispensed == {"pump_1", "pump_2"}
```

Run it:

```
.venv/bin/python -m pytest tests/test_experiment_role_affinity.py -v
```

```
tests/test_experiment_role_affinity.py::test_disjoint_lanes_agree_under_both_analyses PASSED
tests/test_experiment_role_affinity.py::test_conflicting_lanes_agree_under_both_analyses PASSED
tests/test_experiment_role_affinity.py::test_a_non_injective_mapping_is_exactly_where_the_two_analyses_diverge PASSED
tests/test_experiment_role_affinity.py::test_the_injective_mapping_of_that_same_workflow_runs PASSED
=================== 4 passed in 0.52s ====================
```

Confirm the equivalence tests are not vacuous by temporarily making `_footprint` key on the
declared type instead of the role (`found.update((w.role_type(b.device), ch) ...)` in
`validate.py`) and re-running:

```
E       assert [] == [('affinity', 'blocks[0]')]
=================== 2 failed, 2 passed ====================
```

Revert and re-run to green.

Now the full gate:

```
.venv/bin/python -m pytest
.venv/bin/python -m mypy src/lab_devices
.venv/bin/python -m ruff check .
awk 'length>100' src/lab_devices/experiment/context.py src/lab_devices/experiment/run.py \
    src/lab_devices/experiment/finalize.py src/lab_devices/experiment/execute.py \
    tests/test_experiment_roles_runtime.py tests/test_experiment_role_affinity.py
```

Expect a clean `pytest`, `Success: no issues found`, `All checks passed!`, and no `awk` output.

Commit:

```
git add -A && git commit -m "test(engine): prove role-name and device-id affinity analyses agree"
```agentId: a2b48e710585da28c (use SendMessage with to: 'a2b48e710585da28c', summary: '<5-10 word recap>' to continue this agent)
<usage>subagent_tokens: 143496
tool_uses: 23
duration_ms: 515214</usage>

- [ ] **Step 7 — delete the transitional shim**

Every type lookup now reads a declared type, so the last `rsplit("_", 1)` in the engine has no
callers. Delete it and prove it:

```bash
git rm src/lab_devices/experiment/_legacy_ids.py
grep -rn "legacy_device_type\|rsplit(\"_\", 1)" src/lab_devices/experiment/ ; echo "exit=$?"
```

Expected: no output, `exit=1` (grep found nothing). If any hit remains, that call site was
missed in Step 4 — fix it rather than keeping the shim.

Then run the whole engine gate:

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m mypy src/lab_devices
.venv/bin/python -m ruff check .
awk 'length>100 {print FILENAME":"FNR}' src/lab_devices/experiment/*.py tests/test_experiment_*.py
```

Expected: pytest `N passed`, mypy `Success: no issues found`, ruff `All checks passed!`, `awk`
silent.

- [ ] **Step 8 — Commit**

```bash
git add -A src/lab_devices/experiment tests/
git commit -m "refactor(experiment): resolve device types from role declarations

Deletes _legacy_ids.legacy_device_type, the last copy of the rsplit(\"_\", 1)
convention. Types now come from workflow.roles[...].type; a role name is not a
device id and was never decodable into one (design 2026-07-20 §5.2)."
```

---

### Task 9: Migrate the example workflows to schema 2

**Files:**

- `examples/morbidostat.json` — modify (envelope `roles` → `workflow.roles`; `schema_version` 1 → 2; typed `service` group with `locals`; typed `for_each` ×2; seeding `for_each` deleted; top-level abort renamed)
- `examples/morbidostat-demo-speed.json` — modify (identical structural migration; five pace-coupled constants keep their demo-speed values)
- `tests/test_examples_morbidostat.py` — modify (drop `_substitute`, thread `role_mapping`, rewrite the structural assertions at ~:300 and ~:310, rename group-local streams/bindings, shift two expanded block ids, add one hoisting test)

**Interfaces:** (all consumed, none defined — Tasks 1–8 own them)

```python
from lab_devices.experiment.expand import expand_dict          # dict -> dict, seeds now hoisted
from lab_devices.experiment.serialize import workflow_from_dict # SCHEMA_VERSION == 2
from lab_devices.experiment import RunOptions                   # .role_mapping: dict[str, str]
from lab_devices.experiment.workflow import Workflow            # .roles: dict[str, RoleDecl]
```

Two behaviours from the contract that this task is the first real consumer of:

1. **Value-kind whole-string holes substitute as typed JSON.** `{"position": "{tube}"}` with
   `tube: int = 1` emits `{"position": 1}` — the JSON integer, not `"1"`.
2. **Reference-kind holes must occupy a whole name.** In a plain name field (`device`, `into`,
   `args` values) the hole is the entire string. In an *expression* field the hole is a complete
   `NAME` token: `"count({od}, last=11min) > 0"` is legal because `{od}` is delimited by
   non-identifier characters; `"count(od_{od})"` is a load error because the hole is glued to
   identifier text. This is the same rule — "the hole may not be concatenated with adjacent
   identifier characters" — applied to the two kinds of slot. Task 3 implemented it; Task 9 is
   where the whole `service` body depends on it.

The IC50 assertion in `test_morbidostat_closes_the_loop` is this increment's regression oracle and
**must pass unchanged** — same 120 cycles, same drug/medium arm counts, same `0.5*IC50 < drug <
2.0*IC50` band, same `1e-9` agreement between the recorded concentration stream and the simulator.
Only the *names* it reads change (`c_series_1` → `tube_1_c_series`).

---

1. [ ] **RED — point the test at the migrated shape it does not yet have.** Rewrite the loader and
   the mapping plumbing in `tests/test_examples_morbidostat.py`. Delete `_substitute` entirely
   (lines 240–250) and replace `load` (lines 232–237) with:

   ```python
   def load(name: str) -> Any:
       doc = json.loads((EXAMPLES / name).read_text())
       workflow = json.loads(json.dumps(doc["workflow"]))
       workflow = expand_dict(workflow)  # for_each / service(tube, od) -> concrete instances
       return doc, workflow_from_dict(workflow)
   ```

   Roles are no longer rewritten to device ids in the document; the mapping is a run option. Add
   `role_mapping=MAPPING` to the `RunOptions(...)` of all five running tests
   (`test_example_loads_and_validates`, `test_morbidostat_closes_the_loop`,
   `test_morbidostat_survives_a_transient_device_fault`,
   `test_a_dead_sensor_does_not_latch_an_open_loop_injector`,
   `test_operator_emergency_stop_aborts_and_finalizes`,
   `test_contaminated_tube_is_alarmed_and_dropped_from_service`), e.g.:

   ```python
       run = ExperimentRun(
           LabClient("lab", 9000, http=_http(lab)),
           workflow,
           options=RunOptions(
               clock=clock,
               input_provider=answers,
               output_dir=tmp_path,
               role_mapping=MAPPING,
               job_poll_interval=0.05,
               job_poll_max=0.2,
           ),
       )
   ```

   `MAPPING` and `TUBE_OF_METER` keep their current values — `MAPPING` is now handed to the engine
   instead of applied to the document, and `TUBE_OF_METER` still keys on device ids because
   `FakeLab` lives past the wire boundary.

   Rewrite `test_example_loads_and_validates` to assert roles now live inside the workflow:

   ```python
   @pytest.mark.parametrize("name", ["morbidostat.json", "morbidostat-demo-speed.json"])
   def test_example_loads_and_validates(name: str) -> None:
       """Both shipped docs survive engine load + validation (ExperimentRun validates in ctor)."""
       doc, workflow = load(name)
       assert doc["doc_version"] == 1
       assert doc["workflow"]["schema_version"] == 2
       assert "roles" not in doc, "roles moved into the workflow (design 2026-07-20 §5.1)"
       assert set(workflow.roles) == set(MAPPING)
       assert workflow.role_type("od_meter_1") == "densitometer"
       assert workflow.role_type("drug_pump") == "pump"
       clock = FakeClock()
       lab = CultureLab(clock, {1: 0.05, 2: 0.05, 3: 0.05})
       client = LabClient("lab", 9000, http=_http(lab))
       ExperimentRun(  # validate() in __init__
           client, workflow, options=RunOptions(clock=clock, role_mapping=MAPPING)
       )
   ```

   Run and watch it fail on the *unmigrated* documents:

   ```
   .venv/bin/python -m pytest tests/test_examples_morbidostat.py -x -q
   ```

   Expected: a load failure naming the version remedy —
   `WorkflowLoadError: unsupported schema_version 1; expected 2. Workflows using groups or
   for_each cannot be migrated automatically: their param types were never recorded in v1
   (design 2026-07-20 §7)`.

2. [ ] **GREEN, part 1 — move `roles` into `examples/morbidostat.json` and bump the version.**
   Delete the top-level `"roles"` object (lines 5–33) from the envelope, leaving the envelope as
   `doc_version`, `name`, `description`, `workflow`. Inside `"workflow"`, set
   `"schema_version": 2` and insert `roles` between `defaults` and `streams` — the key order
   `workflow_to_dict` emits (contract: schema_version, metadata, persistence, defaults, roles,
   streams, groups, blocks), so a Studio round-trip is a no-op diff:

   ```json
       "defaults": {
         "retry": {
           "attempts": 3,
           "backoff": "2s"
         }
       },
       "roles": {
         "medium_pump": {
           "type": "pump"
         },
         "drug_pump": {
           "type": "pump"
         },
         "waste_pump": {
           "type": "pump"
         },
         "medium_valve": {
           "type": "valve"
         },
         "drug_valve": {
           "type": "valve"
         },
         "waste_valve": {
           "type": "valve"
         },
         "od_meter_1": {
           "type": "densitometer"
         },
         "od_meter_2": {
           "type": "densitometer"
         },
         "od_meter_3": {
           "type": "densitometer"
         }
       },
   ```

   No `device:` bindings: these documents are driven by Studio (or, in tests, by
   `RunOptions.role_mapping`), so the rig is not fixed. A standalone user of the published package
   supplies the mapping — the optional `device` field exists for fixed rigs and is exercised in
   `docs/workflow-schema.md` (Task 10), not here.

3. [ ] **GREEN, part 2 — shrink `streams` to the declared, non-local streams.** The six
   `c_series_N` / `r_series_N` declarations become group locals in step 4 and are emitted by the
   expander, so delete them. `streams` becomes exactly:

   ```json
       "streams": {
         "od_1": {
           "units": "AU"
         },
         "od_2": {
           "units": "AU"
         },
         "od_3": {
           "units": "AU"
         },
         "blank_1": {
           "units": "AU/s"
         },
         "blank_2": {
           "units": "AU/s"
         },
         "blank_3": {
           "units": "AU/s"
         }
       },
   ```

   `od_N` stays top-level because it is *passed into* the group as a `stream` param — the group
   reads a stream it does not own. `blank_N` stays because the blanks are one-shot setup, outside
   the group entirely. This is the split the kind system makes visible: owned → local, borrowed →
   param.

4. [ ] **GREEN, part 3 — retype the `service` group.** Replace the whole `"groups"` object
   (lines 89–255) with the following. Every reference in the body is now a hole; the only bare
   names left are the six global bindings the group legitimately reads from its enclosing scope
   (`od_min`, `od_thr`, `r_dil`, `dose_ml`, `drug_stock_x_mic`, `working_volume_ml`), which are
   real post-expansion identifiers and therefore invisible to the residual-hole scan.

   ```json
       "groups": {
         "service": {
           "params": [
             {
               "name": "tube",
               "kind": "int"
             },
             {
               "name": "od",
               "kind": "stream"
             }
           ],
           "locals": {
             "c": {
               "kind": "binding",
               "init": "0"
             },
             "contaminated": {
               "kind": "binding",
               "init": "false"
             },
             "alarmed": {
               "kind": "binding",
               "init": "false"
             },
             "r": {
               "kind": "binding"
             },
             "od_high": {
               "kind": "binding"
             },
             "c_series": {
               "kind": "stream",
               "units": "x_MIC"
             },
             "r_series": {
               "kind": "stream",
               "units": "per_hour"
             }
           },
           "body": [
             {
               "compute": {
                 "into": "{od_high}",
                 "value": "count({od}, last=11min) > 0 and mean({od}, last=11min) > 2.0"
               },
               "label": "tube {tube}: OD stuck high this cycle (contamination leg 1/2, freshness-guarded)"
             },
             {
               "compute": {
                 "into": "{contaminated}",
                 "value": "{contaminated} or ({od_high} and {c} >= drug_stock_x_mic * 0.99)"
               },
               "label": "tube {tube}: contamination latch - drug maxed AND OD still high -> stays contaminated forever"
             },
             {
               "alarm": {
                 "if": "{contaminated} and not {alarmed}",
                 "message": "tube {tube} contaminated - dropped from service"
               },
               "label": "tube {tube}: fire once, on the contamination edge"
             },
             {
               "compute": {
                 "into": "{alarmed}",
                 "value": "{alarmed} or {contaminated}"
               },
               "label": "tube {tube}: latch the alarm so it never refires"
             },
             {
               "branch": {
                 "if": "not {contaminated}",
                 "then": [
                   {
                     "branch": {
                       "if": "count({od}, last=11min) > 0 and last({od}) >= od_min",
                       "then": [
                         {
                           "compute": {
                             "into": "{r}",
                             "value": "24 * (mean({od}, last=5) - mean({od}, last=10)) / last({od})"
                           },
                           "label": "tube {tube}: specific growth rate (1/h)"
                         },
                         {
                           "record": {
                             "into": "{r_series}",
                             "value": "{r}"
                           },
                           "label": "tube {tube}: chart the growth rate"
                         },
                         {
                           "branch": {
                             "if": "last({od}) > od_thr and {r} > r_dil",
                             "then": [
                               {
                                 "command": {
                                   "device": "drug_valve",
                                   "verb": "set_position",
                                   "params": {
                                     "position": "{tube}",
                                     "rotation": "direct"
                                   }
                                 },
                                 "label": "drug line -> tube {tube}"
                               },
                               {
                                 "command": {
                                   "device": "drug_pump",
                                   "verb": "dispense",
                                   "params": {
                                     "volume_ml": "dose_ml",
                                     "speed_ml_min": 6.0,
                                     "direction": "forward"
                                   }
                                 },
                                 "label": "INJECT DRUG into tube {tube}"
                               },
                               {
                                 "compute": {
                                   "into": "{c}",
                                   "value": "{c} * working_volume_ml/(working_volume_ml + dose_ml) + drug_stock_x_mic * dose_ml/(working_volume_ml + dose_ml)"
                                 },
                                 "label": "tube {tube}: drug raised concentration"
                               }
                             ],
                             "else": [
                               {
                                 "command": {
                                   "device": "medium_valve",
                                   "verb": "set_position",
                                   "params": {
                                     "position": "{tube}",
                                     "rotation": "direct"
                                   }
                                 },
                                 "label": "medium line -> tube {tube}"
                               },
                               {
                                 "command": {
                                   "device": "medium_pump",
                                   "verb": "dispense",
                                   "params": {
                                     "volume_ml": "dose_ml",
                                     "speed_ml_min": 6.0,
                                     "direction": "forward"
                                   }
                                 },
                                 "label": "INJECT MEDIUM into tube {tube}"
                               },
                               {
                                 "compute": {
                                   "into": "{c}",
                                   "value": "{c} * working_volume_ml/(working_volume_ml + dose_ml)"
                                 },
                                 "label": "tube {tube}: medium diluted concentration"
                               }
                             ]
                           },
                           "label": "tube {tube}: growing above threshold -> drug, else medium"
                         },
                         {
                           "command": {
                             "device": "waste_valve",
                             "verb": "set_position",
                             "params": {
                               "position": "{tube}",
                               "rotation": "direct"
                             }
                           },
                           "label": "waste line -> tube {tube}"
                         },
                         {
                           "command": {
                             "device": "waste_pump",
                             "verb": "dispense",
                             "params": {
                               "volume_ml": "dose_ml * 1.5",
                               "speed_ml_min": 6.0,
                               "direction": "forward"
                             }
                           },
                           "label": "restore tube {tube} to V (over-draw; needle is at the V line)"
                         },
                         {
                           "record": {
                             "into": "{c_series}",
                             "value": "{c}"
                           },
                           "label": "tube {tube}: chart the drug-concentration sawtooth"
                         }
                       ]
                     },
                     "label": "tube {tube}: service (skipped entirely if this cycle produced NO reading - a dead sensor must never latch an open-loop injector - or while too dilute to read)"
                   }
                 ]
               },
               "label": "tube {tube}: service only while not contaminated (a contaminated tube receives no further drug or medium)"
             }
           ]
         }
       },
   ```

   Three things to note in the diff. `"position": "{tube}"` is unchanged *textually* but changes
   meaning: it now emits the JSON integer `1`, not the string `"1"` that survived only because
   `_check_param_value` re-parsed it as an expression. `"volume_ml": "dose_ml"` and
   `"dose_ml * 1.5"` are unchanged and stay strings — they are genuine expressions over a global
   binding, not holes. And the three device fields (`drug_valve`, `medium_valve`, `waste_valve`,
   plus the pumps) stay literal role names: they were never per-tube, so they never needed a
   `role` param.

5. [ ] **GREEN, part 4 — delete the seeding `for_each` from `blocks`.** Remove the entire block at
   lines 476–508 (the `for_each` over `[1, 2, 3]` emitting `c_{tube}`, `contaminated_{tube}`,
   `alarmed_{tube}`). Nothing replaces it in the document: the three `init` clauses in
   `locals` hoist nine `compute` blocks to the front of `workflow.blocks` at expand time, in
   instance-then-declaration order:

   ```
   blocks[0] tube_1_c            = "0"
   blocks[1] tube_1_contaminated = "false"
   blocks[2] tube_1_alarmed      = "false"
   blocks[3] tube_2_c            = "0"
   blocks[4] tube_2_contaminated = "false"
   blocks[5] tube_2_alarmed      = "false"
   blocks[6] tube_3_c            = "0"
   blocks[7] tube_3_contaminated = "false"
   blocks[8] tube_3_alarmed      = "false"
   blocks[9] the "morbidostat" serial (was blocks[0])
   ```

   After the deletion the setup serial's children are, in order: six `operator_input`s (0–5), the
   thermostat `parallel` (6), the blank `serial` (7), `cultures_ready` (8), the valve `serial` (9),
   the `working_volume_ml` `compute` (10), `emergency_stop` (11), and the ratchet `loop` (12). The
   ratchet moves from index 13 to index 12; the two indices the fault-tolerance test already pins
   (`setup[6]` thermostats, `setup[7]` blanks) are unaffected.

6. [ ] **GREEN, part 5 — rewrite the top-level abort and both `for_each` blocks.** Inside the
   ratchet loop, the second `abort` reads the three per-tube latches under their new qualified
   names:

   ```json
                 {
                   "abort": {
                     "if": "tube_1_contaminated and tube_2_contaminated and tube_3_contaminated",
                     "message": "all vials contaminated - nothing left to run"
                   },
                   "label": "whole-run abort: every tube has been dropped from service"
                 },
   ```

   This is the escaping-local case §2.2 exists to permit: a top-level expression reading a binding
   the group owns. Locals are namespaced, not private.

   The OD-read `for_each` (was lines 540–558) becomes a typed table whose `meter` column is a
   `role<densitometer>` — the `od_meter_{tube}` string surgery is gone, and the role name is now
   checkable against `workflow.roles` before expansion:

   ```json
                           {
                             "for_each": {
                               "vars": [
                                 {
                                   "name": "tube",
                                   "kind": "int"
                                 },
                                 {
                                   "name": "meter",
                                   "kind": "role",
                                   "device_type": "densitometer"
                                 },
                                 {
                                   "name": "od",
                                   "kind": "stream"
                                 }
                               ],
                               "in": [
                                 {
                                   "tube": 1,
                                   "meter": "od_meter_1",
                                   "od": "od_1"
                                 },
                                 {
                                   "tube": 2,
                                   "meter": "od_meter_2",
                                   "od": "od_2"
                                 },
                                 {
                                   "tube": 3,
                                   "meter": "od_meter_3",
                                   "od": "od_3"
                                 }
                               ],
                               "body": [
                                 {
                                   "measure": {
                                     "device": "{meter}",
                                     "verb": "measure",
                                     "into": "{od}"
                                   },
                                   "label": "tube {tube} OD (retried; a read that still fails costs this one sample, not the run)",
                                   "on_error": "continue"
                                 }
                               ]
                             }
                           }
   ```

   The service `for_each` (was lines 571–589) threads both the tube index and the tube's OD stream
   into the group, and names the instance with `as`:

   ```json
                 {
                   "for_each": {
                     "vars": [
                       {
                         "name": "tube",
                         "kind": "int"
                       },
                       {
                         "name": "od",
                         "kind": "stream"
                       }
                     ],
                     "in": [
                       {
                         "tube": 1,
                         "od": "od_1"
                       },
                       {
                         "tube": 2,
                         "od": "od_2"
                       },
                       {
                         "tube": 3,
                         "od": "od_3"
                       }
                     ],
                     "body": [
                       {
                         "group_ref": {
                           "name": "service",
                           "as": "tube_{tube}",
                           "args": {
                             "tube": "{tube}",
                             "od": "{od}"
                           }
                         },
                         "label": "tube {tube}: service"
                       }
                     ]
                   }
                 },
   ```

   `as: "tube_{tube}"` is an embedded value-kind hole, which is exactly why it is legal and why one
   call site yields three distinct instances (`tube_1`, `tube_2`, `tube_3`). The emitted streams
   are `tube_1_c_series`, `tube_1_r_series`, …; the emitted bindings are `tube_1_c`,
   `tube_1_contaminated`, `tube_1_alarmed`, `tube_1_r`, `tube_1_od_high`.

7. [ ] **GREEN, part 6 — migrate `examples/morbidostat-demo-speed.json` identically.** Its only
   differences from the faithful doc are five pace-coupled values and its prose; apply steps 2–6
   verbatim, substituting:

   | site | morbidostat.json | morbidostat-demo-speed.json |
   |---|---|---|
   | `defaults.retry.backoff` | `"2s"` | `"1s"` |
   | freshness window (3 occurrences: `od_high` compute ×2, service guard ×1) | `last=11min` | `last=45s` |
   | slope constant in the `{r}` compute | `24 * (...)` | `480 * (...)` |
   | `speed_ml_min` (3 dispenses) | `6.0` | `60.0` |
   | growth-phase `loop.pace` | `"1min"` | `"3s"` |
   | ratchet `loop.count` / `loop.pace` / label | `120` / `"12min"` / `"the ratchet: 120 growth cycles of 12min"` | `25` / `"60s"` / `"the ratchet: 25 growth cycles of 60s"` |

   The `metadata.description` and envelope `description` prose is untouched by this task — the
   pace-coupling narrative it carries is still accurate. Verify the two files stay structurally
   identical apart from those constants:

   ```
   diff <(python3 -c 'import json,sys;d=json.load(open("examples/morbidostat.json"));d.pop("description");d["workflow"]["metadata"].pop("description");print(json.dumps(d,indent=2,sort_keys=True))') \
        <(python3 -c 'import json,sys;d=json.load(open("examples/morbidostat-demo-speed.json"));d.pop("description");d["workflow"]["metadata"].pop("description");print(json.dumps(d,indent=2,sort_keys=True))')
   ```

   Expected: only the name, the backoff, the three freshness windows, the slope constant, the three
   `speed_ml_min`s, the two paces, the count, and the ratchet label differ — 15 changed lines, no
   structural hunks.

8. [ ] **GREEN, part 7 — rewrite the structural assertions in
   `test_example_declares_its_fault_tolerance`.** Replace the body from the `ratchet` lookup
   (currently line 284) through the group-body assertions (currently line 325) with:

   ```python
       # after the working-volume compute and the emergency_stop operator_input. The old
       # for_each seeding c/contaminated/alarmed is GONE — `locals.init` hoists those nine
       # computes to the front of blocks (test_group_local_seeds_are_hoisted).
       ratchet = setup[12]["loop"]
       assert not any("for_each" in b for b in setup[:12]), "no hand-written seeds survive"
       # The two whole-run aborts (operator emergency_stop; all three tubes contaminated) sit
       # at the very top of the cycle, before anything else happens this cycle. The second
       # reads three group-locals from OUTSIDE the group that owns them: locals are
       # namespaced, not private (design 2026-07-20 §2.2).
       assert ratchet["body"][0]["abort"]["if"] == "emergency_stop"
       assert ratchet["body"][1]["abort"]["if"] == (
           "tube_1_contaminated and tube_2_contaminated and tube_3_contaminated"
       )
       # The OD reads are ONE typed for_each lane, spliced to 3 concrete reads at expand time.
       # `meter` is a role<densitometer> column — the od_meter_{tube} string surgery is gone,
       # and each cell is checked against workflow.roles BEFORE expansion (design §4).
       reads_for_each = ratchet["body"][2]["loop"]["body"][0]["parallel"]["children"][0]["for_each"]
       assert reads_for_each["vars"] == [
           {"name": "tube", "kind": "int"},
           {"name": "meter", "kind": "role", "device_type": "densitometer"},
           {"name": "od", "kind": "stream"},
       ]
       assert reads_for_each["in"] == [
           {"tube": 1, "meter": "od_meter_1", "od": "od_1"},
           {"tube": 2, "meter": "od_meter_2", "od": "od_2"},
           {"tube": 3, "meter": "od_meter_3", "od": "od_3"},
       ]
       (read,) = reads_for_each["body"]
       assert read["on_error"] == "continue"
       assert read["measure"] == {"device": "{meter}", "verb": "measure", "into": "{od}"}

       # The three tube-service branches are one `service(tube, od)` group, called once per tube
       # by a typed for_each. `as` is required because the group declares locals, and it is an
       # embedded value-kind hole, which is how ONE call site yields three instances (§6).
       service_call = ratchet["body"][3]["for_each"]
       assert service_call["vars"] == [
           {"name": "tube", "kind": "int"},
           {"name": "od", "kind": "stream"},
       ]
       assert service_call["in"] == [
           {"tube": 1, "od": "od_1"},
           {"tube": 2, "od": "od_2"},
           {"tube": 3, "od": "od_3"},
       ]
       (call,) = service_call["body"]
       assert call["group_ref"] == {
           "name": "service",
           "as": "tube_{tube}",
           "args": {"tube": "{tube}", "od": "{od}"},
       }

       # The group's four kinds of thing, each now typed: a borrowed stream (`od`) and an int
       # index as params; the five bindings and two streams it OWNS as locals. Three of the
       # bindings carry the constant `init` that replaces the deleted seeding for_each.
       group = doc["workflow"]["groups"]["service"]
       assert group["params"] == [
           {"name": "tube", "kind": "int"},
           {"name": "od", "kind": "stream"},
       ]
       assert group["locals"] == {
           "c": {"kind": "binding", "init": "0"},
           "contaminated": {"kind": "binding", "init": "false"},
           "alarmed": {"kind": "binding", "init": "false"},
           "r": {"kind": "binding"},
           "od_high": {"kind": "binding"},
           "c_series": {"kind": "stream", "units": "x_MIC"},
           "r_series": {"kind": "stream", "units": "per_hour"},
       }
       # c_series/r_series are no longer hand-declared per tube: the expander emits them from
       # the local declarations, so only borrowed (od_N) and setup (blank_N) streams remain.
       assert set(doc["workflow"]["streams"]) == {
           "od_1", "od_2", "od_3", "blank_1", "blank_2", "blank_3",
       }

       # The service group leads with contamination bookkeeping (freshness-guarded OD-high
       # latch, sticky `contaminated` latch, fire-once alarm, sticky `alarmed` latch) and only
       # THEN the pre-existing freshness branch, now wrapped so a contaminated tube is dropped.
       # Every reference is a hole — including inside expression strings (design §3).
       window = FRESHNESS[name]
       service_body = group["body"]
       assert service_body[0]["compute"]["into"] == "{od_high}"
       assert service_body[0]["compute"]["value"] == (
           f"count({{od}}, last={window}) > 0 and mean({{od}}, last={window}) > 2.0"
       )
       assert service_body[1]["compute"]["into"] == "{contaminated}"
       assert service_body[2]["alarm"]["if"] == "{contaminated} and not {alarmed}"
       assert service_body[3]["compute"]["into"] == "{alarmed}"
       drop_branch = service_body[4]["branch"]
       assert drop_branch["if"] == "not {contaminated}"
       group_guard = drop_branch["then"][0]["branch"]["if"]
       assert group_guard.startswith(f"count({{od}}, last={window}) > 0 and ")
   ```

   And in the same test, the pump-retry sweep reads roles from inside the workflow (line 343):

   ```python
       roles = doc["workflow"]["roles"]
       assert not any(
           "retry" in b for b in _walk(doc["workflow"]["blocks"]) + group_blocks if "command" in b
           and roles.get(b["command"]["device"], {}).get("type") == "pump"
       )
   ```

9. [ ] **GREEN, part 8 — rename the group-local streams and bindings the running tests read, and
   shift the two expanded block ids.** In `test_morbidostat_closes_the_loop`:

   ```python
       for t, culture in ((1, t1), (3, t3)):
           c_series = report.state.streams[f"tube_{t}_c_series"].samples
           r_series = report.state.streams[f"tube_{t}_r_series"].samples
           assert len(c_series) == 120 and len(r_series) == 120, f"tube {t}: a serviced cycle records"
           assert abs(c_series[-1].value - culture.drug) < 1e-9, (
               f"tube {t}: recorded c {c_series[-1].value:.6f} != simulated drug {culture.drug:.6f}"
           )
       # Tube 2 (NOTHING arm on its early cycles) records only the cycles it was serviced on.
       assert 0 < len(report.state.streams["tube_2_c_series"].samples) < 120
       assert abs(report.state.streams["tube_2_c_series"].samples[-1].value - t2.drug) < 1e-9
   ```

   In `test_contaminated_tube_is_alarmed_and_dropped_from_service`:

   ```python
       assert report.state.bindings["tube_3_contaminated"] is True
       assert report.state.bindings["tube_1_contaminated"] is False
       assert report.state.bindings["tube_2_contaminated"] is False

       # --- one c_series sample per serviced cycle: recording stops exactly when service does ---
       assert len(report.state.streams["tube_3_c_series"].samples) == len(t3.injections)
   ```

   The `od_N` / `blank_N` reads are untouched — they are declared streams, not locals. In both
   `test_morbidostat_survives_a_transient_device_fault` and
   `test_a_dead_sensor_does_not_latch_an_open_loop_injector`, the od_3 read's expanded block id
   shifts by the nine hoisted seeds and by the deleted seed `for_each`:

   ```python
       od_3_read = "blocks[9].children[12].body[2].body[0].children[2]"
   ```

   (`blocks[0..8]` are the hoisted seeds; the setup serial is now `blocks[9]`; the ratchet is
   `children[12]` because the eleven-block seed `for_each` no longer expands ahead of it.)

10. [ ] **Add one test for the hoist itself** — the behaviour that replaced an authored block, so
    it needs its own oracle rather than riding on the IC50 test. Append to
    `tests/test_examples_morbidostat.py`:

    ```python
    @pytest.mark.parametrize("name", ["morbidostat.json", "morbidostat-demo-speed.json"])
    def test_group_local_seeds_are_hoisted(name: str) -> None:
        """`locals.init` replaces the hand-written seeding for_each (design 2026-07-20 §2.3).

        Nine constant computes — three initialized locals x three instances — land at the FRONT
        of blocks in instance-then-declaration order, before the setup serial that used to be
        blocks[0]. Order is what makes them safe: a hoisted initializer runs before every other
        block, so `init` is restricted to constant expressions and the hoist is total.
        """
        doc = json.loads((EXAMPLES / name).read_text())
        expanded = expand_dict(json.loads(json.dumps(doc["workflow"])))

        seeds = expanded["blocks"][:9]
        assert [b["compute"]["into"] for b in seeds] == [
            "tube_1_c", "tube_1_contaminated", "tube_1_alarmed",
            "tube_2_c", "tube_2_contaminated", "tube_2_alarmed",
            "tube_3_c", "tube_3_contaminated", "tube_3_alarmed",
        ]
        assert [b["compute"]["value"] for b in seeds] == ["0", "false", "false"] * 3
        assert expanded["blocks"][9]["serial"], "the authored tree follows the hoisted seeds"
        assert len(expanded["blocks"]) == 10

        # The two stream locals are emitted as real declarations, units carried across.
        assert expanded["streams"]["tube_1_c_series"] == {"units": "x_MIC"}
        assert expanded["streams"]["tube_3_r_series"] == {"units": "per_hour"}
        assert "c_series_1" not in expanded["streams"], "the old hand-written names are gone"

        # `position: "{tube}"` is a whole-string hole of an int param, so it substitutes as the
        # JSON integer — not the string "1" that only worked because validate re-parsed it.
        drug_valve = _walk(expanded["blocks"])
        positions = [
            b["command"]["params"]["position"]
            for b in drug_valve
            if "command" in b and b["command"]["verb"] == "set_position"
        ]
        assert all(isinstance(p, int) for p in positions), f"untyped position survived: {positions}"
        assert set(positions) == {0, 1, 2, 3}
    ```

11. [ ] **Verify the whole file, IC50 oracle included.**

    ```
    .venv/bin/python -m pytest tests/test_examples_morbidostat.py -q
    ```

    Expected: `11 passed` (the two parametrized structural tests → 4, the new hoisting test → 2,
    plus the five running tests), no warnings. Confirm specifically that the oracle ran and was
    not skipped or trivially satisfied:

    ```
    .venv/bin/python -m pytest tests/test_examples_morbidostat.py::test_morbidostat_closes_the_loop -q
    ```

    Expected: `1 passed`. Then mutation-check the oracle is not vacuous — temporarily change the
    `assert 0.5 * IC50 < culture.drug < 2.0 * IC50` bound to `0.5 * IC50 < culture.drug < 0.6 * IC50`
    and re-run; expected `1 failed` with `tube 1: drug 1.2…`. Revert.

12. [ ] **Run the full gate.**

    ```
    .venv/bin/python -m pytest -q
    .venv/bin/python -m mypy src/lab_devices
    .venv/bin/python -m ruff check .
    awk 'length>100 {print FILENAME":"FNR}' tests/test_examples_morbidostat.py
    ```

    Expected: all tests pass; `Success: no issues found`; `All checks passed!`; no `awk` output.
    Also confirm both examples round-trip byte-stably through the loader, so a Studio save is a
    no-op diff:

    ```
    .venv/bin/python -c "
    import json
    from lab_devices.experiment.serialize import workflow_from_dict, workflow_to_dict
    for n in ('morbidostat.json', 'morbidostat-demo-speed.json'):
        d = json.load(open('examples/' + n))['workflow']
        assert workflow_to_dict(workflow_from_dict(d)) == d, n
    print('round-trip stable')
    "
    ```

    Expected: `round-trip stable`.

---

### Task 10: Document the schema

**Files:**

- `docs/workflow-schema.md` — **create** (the repo's first maintained schema reference; today the
  schema exists only inside dated design specs under `docs/superpowers/specs/`, which are frozen
  historical records and are the wrong place to look up current syntax)
- `tests/test_docs_workflow_schema.py` — **create** (extracts and loads every JSON snippet in the
  reference, so it cannot rot)
- `docs/experiment-engine-limitations.md` — modify (§4 at :435–472 documents the untyped
  `params`/`args` as shipped; the summary table row for #4 says the same)

**Interfaces:**

```python
from lab_devices.experiment.expand import expand_dict
from lab_devices.experiment.serialize import workflow_from_dict
```

The extraction contract — write it into the doc itself so future editors follow it:

- A ` ```json ` fence is a **complete workflow document** and is loaded with `workflow_from_dict`
  and then with `workflow_from_dict(expand_dict(...))`.
- A ` ```jsonc ` fence is a **fragment** and must still be a syntactically valid, self-contained
  JSON *object* — so fragments are written as `{"locals": {…}}`, never as a bare key-value line.
- Any other fence (` ```text `, ` ```python `) is prose and is not extracted.

Task 10 has no production code, so its RED/GREEN loop runs on the extraction test: write the test
first against an absent doc, watch it fail on the missing file, then write the doc until it passes.

---

1. [ ] **RED — write the extraction test against a doc that does not exist yet.** Create
   `tests/test_docs_workflow_schema.py`:

   ```python
   """docs/workflow-schema.md is executable documentation.

   Every complete workflow in the reference is loaded through the real loader and the real
   expander, and every fragment is parsed as JSON. A reference nobody runs is a reference that
   silently stops describing the code; this is the check that stops that (design 2026-07-20 §8).
   """

   import json
   import re
   from pathlib import Path
   from typing import Any

   import pytest

   from lab_devices.experiment.expand import expand_dict
   from lab_devices.experiment.serialize import workflow_from_dict

   DOC = Path(__file__).resolve().parents[1] / "docs" / "workflow-schema.md"

   # ```json  -> a COMPLETE workflow document, loaded and expanded.
   # ```jsonc -> a fragment; must still be a self-contained, parseable JSON object.
   _FENCE = re.compile(r"^```(json|jsonc)\n(.*?)^```", re.MULTILINE | re.DOTALL)


   def _snippets(lang: str) -> list[tuple[int, str]]:
       text = DOC.read_text()
       out: list[tuple[int, str]] = []
       for match in _FENCE.finditer(text):
           if match.group(1) == lang:
               line = text.count("\n", 0, match.start()) + 1
               out.append((line, match.group(2)))
       return out


   def _ids(pairs: list[tuple[int, str]]) -> list[str]:
       return [f"L{line}" for line, _ in pairs]


   WORKFLOWS = _snippets("json")
   FRAGMENTS = _snippets("jsonc")


   def test_the_reference_actually_contains_examples() -> None:
       """Guard against a vacuous pass: an empty doc must not look like a green one."""
       assert DOC.exists(), "docs/workflow-schema.md is the repo's schema reference"
       assert len(WORKFLOWS) >= 6, f"only {len(WORKFLOWS)} complete workflows in the reference"
       assert len(FRAGMENTS) >= 4, f"only {len(FRAGMENTS)} fragments in the reference"


   @pytest.mark.parametrize("line,src", WORKFLOWS, ids=_ids(WORKFLOWS))
   def test_documented_workflow_loads(line: int, src: str) -> None:
       """Every ```json block is a whole document the shipped loader accepts."""
       doc: Any = json.loads(src)
       assert doc.get("schema_version") == 2, f"line {line}: reference examples are schema 2"
       workflow = workflow_from_dict(doc)
       assert workflow.schema_version == 2


   @pytest.mark.parametrize("line,src", WORKFLOWS, ids=_ids(WORKFLOWS))
   def test_documented_workflow_expands(line: int, src: str) -> None:
       """...and survives expansion, so documented groups/for_each are really expandable."""
       doc: Any = json.loads(src)
       workflow_from_dict(expand_dict(json.loads(json.dumps(doc))))


   @pytest.mark.parametrize("line,src", FRAGMENTS, ids=_ids(FRAGMENTS))
   def test_documented_fragment_is_valid_json(line: int, src: str) -> None:
       """Fragments are not whole documents, but they are still real JSON objects."""
       value: Any = json.loads(src)
       assert isinstance(value, dict), f"line {line}: write fragments as objects, not bare keys"
   ```

   Run it:

   ```
   .venv/bin/python -m pytest tests/test_docs_workflow_schema.py -q
   ```

   Expected: collection produces one test —
   `test_the_reference_actually_contains_examples` — which fails with
   `AssertionError: docs/workflow-schema.md is the repo's schema reference`
   (the parametrized tests collect zero cases because the file is absent).

2. [ ] **GREEN — write `docs/workflow-schema.md`, part 1: header, document shape, block grammar.**

   ````markdown
   # Workflow schema reference

   **Schema version: 2.** This is the maintained reference for the workflow JSON the experiment
   engine loads. Design specs under `docs/superpowers/specs/` are frozen records of *decisions*;
   this document describes the format *as it is now*. When the two disagree, this one is wrong and
   should be fixed — every ` ```json ` block below is loaded through `workflow_from_dict` and
   `expand_dict` by `tests/test_docs_workflow_schema.py`, so a stale example fails the suite.

   Editing convention: ` ```json ` fences are complete workflow documents and are executed by that
   test; ` ```jsonc ` fences are fragments and must still be self-contained JSON objects; anything
   else is prose.

   ## 1. Document shape

   A workflow is a single JSON object. Only `schema_version` and `blocks` are required.

   ```json
   {
     "schema_version": 2,
     "metadata": {
       "name": "Minimal",
       "author": "lab-devices",
       "description": "The smallest document the loader accepts."
     },
     "persistence": {"default": "in_memory", "format": "jsonl"},
     "defaults": {"retry": {"attempts": 3, "backoff": "2s"}},
     "roles": {"od_meter_1": {"type": "densitometer"}},
     "streams": {"od_1": {"units": "AU"}},
     "groups": {},
     "blocks": [
       {"measure": {"device": "od_meter_1", "verb": "measure", "into": "od_1"}}
     ]
   }
   ```

   | key | required | meaning |
   |---|---|---|
   | `schema_version` | yes | must be `2`; see §7 |
   | `metadata` | no | `name`, `author`, `description` — free text |
   | `persistence` | no | `default`: `"in_memory"` \| `"disk"`; `format`: `"jsonl"` \| `"csv"` |
   | `defaults` | no | `retry` only — a blanket `on_error` would make a missed injection silently survivable |
   | `roles` | no | named instrument slots (§5) |
   | `streams` | no | declared sample series; a block may only write a declared stream |
   | `groups` | no | reusable, parametrized block bodies (§3) |
   | `blocks` | yes | the ordered tree the run executes |

   `workflow_to_dict` emits these keys in exactly the order above, so a load/save round-trip of a
   hand-written document in this order is a no-op diff.

   ## 2. Block grammar

   A block is a JSON object with **exactly one** type key plus optional block-level keys. The type
   keys are:

   | type key | body | what it does |
   |---|---|---|
   | `command` | `device`, `verb`, `params` | one device verb, no result recorded |
   | `measure` | `device`, `verb`, `into` | one device verb whose reading appends to a stream |
   | `compute` | `into`, `value` | evaluates an expression into a binding |
   | `record` | `into`, `value` | appends a computed value to a declared stream |
   | `operator_input` | `name`, `type`, `prompt`, `min`, `max` | asks the operator; binds the answer |
   | `wait` | `duration` | sleeps |
   | `serial` | `children` | runs children in order |
   | `parallel` | `children` | runs children concurrently, one lane each |
   | `loop` | `body`, `count`, `pace` | repeats `body`; `pace` is a floor, not a deadline |
   | `branch` | `if`, `then`, `else` | conditional |
   | `abort` | `if`, `message` | stops the whole run (`AbortSignalError`, status `"aborted"`) |
   | `alarm` | `if`, `message` | flags and continues (`RunReport.alarms`) |
   | `for_each` | `vars`, `in`, `body` | splicing macro over a typed table (§4) |
   | `group_ref` | `name`, `as`, `args` | inlines a group body as one `serial` (§3) |

   Block-level keys, legal on any block alongside its type key:
   `label`, `gap_after`, `start_offset`, `retry`, `on_error`.

   ```json
   {
     "schema_version": 2,
     "roles": {"drug_pump": {"type": "pump"}, "od_meter_1": {"type": "densitometer"}},
     "streams": {"od_1": {"units": "AU"}},
     "blocks": [
       {
         "serial": {
           "children": [
             {"operator_input": {"name": "dose_ml", "type": "float", "prompt": "Dose (ml)?",
                                 "min": 0.1, "max": 5.0}},
             {"compute": {"into": "total_ml", "value": "0"}, "label": "seed the accumulator"},
             {
               "loop": {
                 "body": [
                   {"measure": {"device": "od_meter_1", "verb": "measure", "into": "od_1"},
                    "on_error": "continue",
                    "label": "a dropped read costs one sample, not the run"},
                   {
                     "branch": {
                       "if": "count(od_1, last=90s) > 0 and last(od_1) > 0.15",
                       "then": [
                         {"command": {"device": "drug_pump", "verb": "dispense",
                                      "params": {"volume_ml": "dose_ml", "speed_ml_min": 6.0,
                                                 "direction": "forward"}}},
                         {"compute": {"into": "total_ml", "value": "total_ml + dose_ml"}}
                       ]
                     }
                   },
                   {"alarm": {"if": "total_ml > 20", "message": "dose budget exceeded"}}
                 ],
                 "count": 10,
                 "pace": "60s"
               }
             }
           ]
         },
         "label": "a small controller"
       }
     ]
   }
   ```

   `retry` on a block (or `defaults.retry` for the document) is only ever applied to a verb the
   registry marks retry-safe: `dispense` takes a *relative* volume, so a retried dispense would
   double-dose, and no default will retry it.
   ````

3. [ ] **GREEN, part 2 — the kind system, group params, and locals.** Append:

   ````markdown
   ## 3. Groups: typed params and locals

   ### 3.1 The kind system

   One kind set is used identically by group params, group locals, and `for_each` vars.

   | kind | the argument is | checked before expansion |
   |---|---|---|
   | `int`, `number`, `bool`, `string` | a literal value | the JSON type matches the kind |
   | `role` | a declared role name | the role exists and `roles[r].type == device_type` |
   | `stream` | a declared stream name | the stream exists in `streams` |
   | `binding` | a binding name | identifier shape; must not collide with a stream |

   `int`/`number`/`bool`/`string` are **value kinds**; `role`/`stream`/`binding` are **reference
   kinds**. `device_type` is required on `role` and forbidden on every other kind, and must name a
   device type the verb registry knows (`pump`, `valve`, `densitometer`).

   `binding` is deliberately the weakest reference: bindings have no declaration section — they are
   created implicitly by their writer (`compute.into`, `operator_input.name`) — so a `binding`
   argument can be checked for shape and for stream-disjointness, not for existence. Existence
   stays the job of the path-sensitive analysis, which reports *"may be read before it is
   written"*. Group locals are how you get a **declared** binding.

   ### 3.2 `params`

   `params` is an **ordered list of objects** — the order is the authoring order, and it is the
   order Studio renders.

   ```jsonc
   {
     "params": [
       {"name": "tube",  "kind": "int"},
       {"name": "od",    "kind": "stream"},
       {"name": "meter", "kind": "role", "device_type": "densitometer"}
     ]
   }
   ```

   `group_ref.args` must supply **exactly** the declared names — no missing, no extra — and each
   argument is checked against its declared kind before anything is substituted.

   ### 3.3 `locals`

   A group declares the streams and bindings it **owns**. Without this, typing gets verbose fast:
   the morbidostat's `service` group would need nine explicit reference params, one per stream and
   binding it touches, threaded through every call site.

   ```jsonc
   {
     "locals": {
       "c":            {"kind": "binding", "init": "0"},
       "contaminated": {"kind": "binding", "init": "false"},
       "r":            {"kind": "binding"},
       "c_series":     {"kind": "stream", "units": "x_MIC"},
       "r_series":     {"kind": "stream", "units": "per_hour", "persistence": "disk"}
     }
   }
   ```

   - Only `stream` and `binding` are legal in `locals`. A local *value* would just be a constant,
     which `compute` already expresses.
   - A `stream` local may carry `units` and `persistence`; the expander copies them into the
     emitted declaration.
   - A `binding` local may carry `init`, an expression evaluated once. The expander hoists one
     `compute` per initialized local to the **front of `blocks`**, in deterministic expansion
     order.
   - **`init` must be a constant expression**: literals and operators over them. No `stat` calls,
     no stream references, no binding references. A hoisted initializer runs before every other
     block in the document, so any data dependency it could express is guaranteed unwritten at that
     point; restricting `init` makes the hoist total and order-insensitive.
   - Param names and local names share one namespace and may not collide. Both must match the
     identifier shape and must not be reserved names.

   **Locals are namespaced, not private.** They expand to ordinary top-level streams and bindings
   under a qualified name, and any expression anywhere in the document may read that name. This is
   required, not merely tolerated: `examples/morbidostat.json` aborts the whole run on
   `tube_1_contaminated and tube_2_contaminated and tube_3_contaminated`, reading three per-tube
   latches from outside the group that owns them. The point of locals is to stop the *author* doing
   name surgery, not to hide the resulting names from the rest of the document.

   ### 3.4 Holes: everything is `{name}`

   Inside a group body, params and locals are referenced as `{name}` in **every** position,
   including inside expression strings. There is no bare-name-in-expressions special case.
   Uniformity is what makes the post-expansion residual-hole scan a complete check: any name that
   is neither substituted nor a real identifier is caught by construction.

   ```jsonc
   {
     "compute": {
       "into": "{od_high}",
       "value": "count({od}, last=11min) > 0 and mean({od}, last=11min) > 2.0"
     }
   }
   ```

   Concatenation splits by kind:

   - **Reference kinds** may not be concatenated with adjacent identifier text. In a name field
     (`device`, `into`, an `args` value) the hole must be the entire string: `"{od}"` is legal,
     `"od_{od}"` and `"{od}_raw"` are load errors. In an expression the hole must be a complete
     `NAME` token: `"count({od}, last=5)"` is legal, `"count(od_{od})"` is not. This is the rule
     that guarantees a reference resolves to a name that provably exists in a declaration.
   - **Value kinds** interpolate anywhere: `"position": "{tube}"` and
     `"label": "tube {tube}: service"` are both fine.

   A **whole-string hole of a value kind substitutes as a typed JSON value**, not a string. With
   `tube: int = 1`, `{"position": "{tube}"}` yields `{"position": 1}` — the JSON integer. Embedded
   holes stringify, because the result is by definition a larger string.

   ### 3.5 `group_ref` and `as`

   ```jsonc
   {
     "group_ref": {
       "name": "service",
       "as": "tube_{tube}",
       "args": {"tube": "{tube}", "od": "{od}"}
     }
   }
   ```

   `as` is the instance name. Locals qualify as `{as}_{local}` — `tube_1_c`, `tube_1_c_series`.

   - `as` is **required** when the group declares locals, optional otherwise.
   - `as` is an ordinary string field, so value-kind holes interpolate into it. That is how one
     call site inside a `for_each` produces three distinct instances.
   - `as` must expand to a valid identifier, so qualified names are legal expression tokens.
   - A duplicate `as` after expansion is a load error: instance names are the identity of the
     emitted streams and bindings, and two instances sharing one would silently merge two tubes'
     data.

   Here is the whole mechanism in one loadable document — a group with both param kinds and both
   local kinds, called twice:

   ```json
   {
     "schema_version": 2,
     "roles": {
       "od_meter_1": {"type": "densitometer"},
       "od_meter_2": {"type": "densitometer"},
       "drug_pump": {"type": "pump"},
       "drug_valve": {"type": "valve"}
     },
     "streams": {"od_1": {"units": "AU"}, "od_2": {"units": "AU"}},
     "groups": {
       "service": {
         "params": [
           {"name": "tube", "kind": "int"},
           {"name": "od", "kind": "stream"}
         ],
         "locals": {
           "c": {"kind": "binding", "init": "0"},
           "c_series": {"kind": "stream", "units": "x_MIC"}
         },
         "body": [
           {"command": {"device": "drug_valve", "verb": "set_position",
                        "params": {"position": "{tube}", "rotation": "direct"}},
            "label": "drug line -> tube {tube}"},
           {"command": {"device": "drug_pump", "verb": "dispense",
                        "params": {"volume_ml": "1.0", "speed_ml_min": 6.0,
                                   "direction": "forward"}}},
           {"compute": {"into": "{c}", "value": "{c} * 12/13 + 10 * 1/13"},
            "label": "tube {tube}: concentration recursion"},
           {"record": {"into": "{c_series}", "value": "{c}"}},
           {"alarm": {"if": "count({od}, last=90s) > 0 and mean({od}, last=90s) > 2.0",
                      "message": "tube {tube}: OD stuck high"}}
         ]
       }
     },
     "blocks": [
       {"measure": {"device": "od_meter_1", "verb": "measure", "into": "od_1"}},
       {"measure": {"device": "od_meter_2", "verb": "measure", "into": "od_2"}},
       {"group_ref": {"name": "service", "as": "tube_1",
                      "args": {"tube": 1, "od": "od_1"}}},
       {"group_ref": {"name": "service", "as": "tube_2",
                      "args": {"tube": 2, "od": "od_2"}}},
       {"abort": {"if": "tube_1_c > 9.9 and tube_2_c > 9.9",
                  "message": "both tubes maxed out"}}
     ]
   }
   ```

   After expansion this document begins with two hoisted `compute` blocks — `tube_1_c = 0` and
   `tube_2_c = 0` — and declares two extra streams, `tube_1_c_series` and `tube_2_c_series`, both
   with `units: "x_MIC"`. The final `abort` reads two group locals from top level, which is the
   escaping-local case §3.3 permits on purpose.
   ````

4. [ ] **GREEN, part 3 — typed `for_each` and roles.** Append:

   ````markdown
   ## 4. `for_each`: a typed table

   `for_each` vars take the same declarations as group params, and `in` is a table of typed rows.
   It is a **splicing** macro: it copies `body` once per row and splices the copies into the
   *enclosing* block list, so `len(in) x len(body)` siblings appear where the `for_each` was. As
   the sole child of a `parallel` that means N concurrent lanes; inside a `serial`, N steps.

   ```jsonc
   {
     "for_each": {
       "vars": [
         {"name": "tube",  "kind": "int"},
         {"name": "meter", "kind": "role", "device_type": "densitometer"},
         {"name": "od",    "kind": "stream"}
       ],
       "in": [
         {"tube": 1, "meter": "od_meter_1", "od": "od_1"},
         {"tube": 2, "meter": "od_meter_2", "od": "od_2"},
         {"tube": 3, "meter": "od_meter_3", "od": "od_3"}
       ],
       "body": [
         {"measure": {"device": "{meter}", "verb": "measure", "into": "{od}"}}
       ]
     }
   }
   ```

   Every row must supply **exactly** the declared var names — a missing or extra key is a load
   error. The `role<densitometer>` column is the point of the shape: `od_meter_{tube}` was string
   surgery whose result was merely *hoped* to be a role name; a typed column is checked against the
   role declarations before a single copy is made.

   > **The scalar shorthand is removed.** `{"for_each": {"var": "tube", "in": [1, 2, 3], "body": …}}`
   > no longer loads. It cannot carry a kind, and keeping it would leave the untyped path alive
   > next to the typed one.

   Substitution is order-independent: a hole not in the running substitution's own environment
   passes through untouched rather than erroring, which is what lets a parametrized group body
   contain a nested `for_each`, and vice versa. The residual-hole scan after all expansion is the
   backstop. A group param that shadows an enclosing `for_each` var is now diagnosed rather than
   silently shadowing.

   ```json
   {
     "schema_version": 2,
     "roles": {
       "od_meter_1": {"type": "densitometer"},
       "od_meter_2": {"type": "densitometer"},
       "od_meter_3": {"type": "densitometer"}
     },
     "streams": {"od_1": {"units": "AU"}, "od_2": {"units": "AU"}, "od_3": {"units": "AU"}},
     "blocks": [
       {
         "parallel": {
           "children": [
             {
               "for_each": {
                 "vars": [
                   {"name": "tube", "kind": "int"},
                   {"name": "meter", "kind": "role", "device_type": "densitometer"},
                   {"name": "od", "kind": "stream"}
                 ],
                 "in": [
                   {"tube": 1, "meter": "od_meter_1", "od": "od_1"},
                   {"tube": 2, "meter": "od_meter_2", "od": "od_2"},
                   {"tube": 3, "meter": "od_meter_3", "od": "od_3"}
                 ],
                 "body": [
                   {"measure": {"device": "{meter}", "verb": "measure", "into": "{od}"},
                    "label": "tube {tube} OD",
                    "on_error": "continue"}
                 ]
               }
             }
           ]
         },
         "label": "read all three tubes at once"
       }
     ]
   }
   ```

   ## 5. Roles

   A role is a named instrument slot. **`device` fields hold role names, end to end** — through
   load, validation, expansion, and execution.

   ```json
   {
     "schema_version": 2,
     "roles": {
       "od_meter_1": {"type": "densitometer"},
       "medium_pump": {"type": "pump", "device": "pump_2"}
     },
     "streams": {"od_1": {"units": "AU"}},
     "blocks": [
       {"command": {"device": "medium_pump", "verb": "dispense",
                    "params": {"volume_ml": 1.0, "speed_ml_min": 6.0, "direction": "forward"}}},
       {"measure": {"device": "od_meter_1", "verb": "measure", "into": "od_1"}}
     ]
   }
   ```

   - `type` must be a device type the verb registry knows. It is what every *type* decision reads:
     which verbs exist, which are retry-safe, which open a mode, which the finalizer sweeps.
   - `device` is optional and binds the role directly. Supply it for a fixed rig so a standalone
     user of the published `bioexperiment-lab-devices` package need not pass a mapping; leave it
     out when a UI supplies the mapping per run (`RunOptions.role_mapping`).
   - Every role must be bound at run start, by `device` or by the mapping, or the run fails to
     start.
   - **The mapping must be injective.** Two roles resolving to one device id is an error, not a
     warning. A role denotes a distinct physical instrument, and the static affinity and
     mode-lifetime analyses intersect footprints by name: injectivity is what makes analysis over
     role names provably equivalent to analysis over device ids. Without it, two aliased roles pass
     every static check and then collide mid-run on one `(device, channel)` slot — an
     `InvariantViolationError` that is neither retried nor tolerated.

   Exactly one place resolves a role to a physical id: `RunContext.device(role)`, at the wire
   boundary. Locks, occupancy slots, and every event payload key on the **role name**, which is
   what the author wrote and what a diagnostic should say. The role→device mapping is recorded once
   on `RunReport.role_devices`.

   ```jsonc
   {
     "role_devices": {
       "od_meter_1": "densitometer_1",
       "medium_pump": "pump_2"
     }
   }
   ```
   ````

5. [ ] **GREEN, part 4 — the schema break and the migration story.** Append (this section is
   design §7 restated for a reader who has hit the error, not for a reviewer):

   ````markdown
   ## 6. Expressions, briefly

   Expression strings appear in `branch.if`, `abort.if`, `alarm.if`, `compute.value`,
   `record.value`, and in any device param slot. They evaluate numbers and booleans over bindings
   and over stream statistics: `last(s)`, `count(s)`, `mean(s)`, each optionally windowed by
   `last=N` (the last N **samples**) or `last=<duration>` (a **time** window, e.g. `last=11min`).

   The two windows are not interchangeable, and the difference is load-bearing. A sample window
   over an append-only stream always returns N values, reaching back across cycle boundaries if it
   must. A duration window can be **empty**, which is why a guard like `count(s, last=11min) > 0`
   proves a sample landed *recently* where `count(s) > 0` only proves one landed *ever* — the
   latter latches true forever and can leave a controller running open-loop on a dead sensor. There
   is no clock primitive and no way to derive a window from an enclosing loop's `pace`, so this
   coupling is manual and unchecked; see limitation #2 in
   [`experiment-engine-limitations.md`](experiment-engine-limitations.md).

   ## 7. Schema version 2 — what broke, and what to do

   `schema_version` must be `2`. A version-1 document is rejected at load with:

   ```text
   unsupported schema_version 1; expected 2. Workflows using groups or for_each cannot be
   migrated automatically: their param types were never recorded in v1
   (design 2026-07-20 §7)
   ```

   This is a deliberate hard break rather than a migration shim, and the message says why: the
   types are precisely the information v1 never wrote down.

   ### 7.1 What v1 looked like

   ```jsonc
   {
     "schema_version": 1,
     "groups": {"service": {"params": ["tube"], "body": []}},
     "blocks": [
       {"for_each": {"var": "tube", "in": [1, 2, 3],
                     "body": [{"group_ref": {"name": "service",
                                             "args": {"tube": "{tube}"}}}]}}
     ]
   }
   ```

   `params: ["tube"]` was a bare textual macro. In `examples/morbidostat.json` that single `tube`
   hole was simultaneously a stream-name suffix (`od_{tube}`), a binding-name suffix (`c_{tube}`),
   an `int` verb param (`position: "{tube}"`), and a device-role suffix (`od_meter_{tube}`) — four
   distinct things behind one untyped hole, and nothing checkable until after expansion.

   ### 7.2 Migrating by hand

   1. **`schema_version`: 1 → 2.**
   2. **Move `roles` into the workflow.** If your document came from Experiment Studio, its
      envelope held `roles` next to `workflow`; move that object inside `workflow`, between
      `defaults` and `streams`. This step is purely mechanical.
   3. **Type every group param.** `"params": ["tube"]` becomes a list of objects. Decide, per hole,
      which of the four things it was. A hole used as `position: "{tube}"` is `int`; a hole used as
      `od_{tube}` was a stream reference and should become a `stream` param (or a local, per step
      4); a hole used as `od_meter_{tube}` becomes a `role` param with a `device_type`.
   4. **Turn name surgery into locals.** Any binding or stream the group *creates* — `c_{tube}`,
      `contaminated_{tube}`, `c_series_{tube}` — becomes a local, and its hand-written top-level
      `streams` declaration is deleted. Any stream the group only *reads* stays a top-level
      declaration and becomes a `stream` param.
   5. **Fold accumulator seeds into `init`.** A `for_each` of `compute` blocks placed before the
      main loop purely to seed accumulators is deleted; put the constant in `locals.<name>.init`
      and let the expander hoist it. If the seed was not a constant, it was reading data that had
      not been written yet — fix that first.
   6. **Add `as` to every `group_ref`** that calls a group with locals, and expect names to change:
      `c_series_1` becomes `tube_1_c_series`. Update anything downstream that reads those columns.
   7. **Rewrite `for_each` to `vars` + row objects.** The scalar `"var"`/`"in": [1, 2, 3]`
      shorthand is gone.
   8. **Make every reference a whole hole**, including inside expressions: `c_{tube}` → `{c}`,
      `mean(od_{tube}, last=5)` → `mean({od}, last=5)`.

   `examples/morbidostat.json` is the worked example of all eight steps.

   ### 7.3 Stale drafts

   Experiment Studio persists an in-progress document to `localStorage`. A draft saved under v1 is
   discarded on load rather than restored, because a shallow shape check cannot tell a v1 body from
   a v2 one and would otherwise silently resurrect a document that no longer loads.
   ````

6. [ ] **Run the extraction test and fix whatever the doc got wrong.**

   ```
   .venv/bin/python -m pytest tests/test_docs_workflow_schema.py -q
   ```

   Expected: `17 passed` — the vacuity guard, plus 6 complete workflows × 2 (load + expand), plus 4
   fragments. If a snippet fails, the doc is wrong, not the test: fix the markdown. Confirm the
   test is not vacuous by mutating one snippet — change `"kind": "int"` to `"kind": "integer"` in
   the §3.5 worked example and re-run; expected `2 failed` naming that fence's line number with an
   unknown-kind load error. Revert.

7. [ ] **Update `docs/experiment-engine-limitations.md` §4.** Replace the shipped-note paragraph at
   lines 437–456 (which describes `{for_each: {var, in, body}}` and `params`/`args` as they shipped
   in Increment 7) with a note that supersedes it and points at the new reference:

   ```markdown
   **Shipped as `for_each` + parametrized groups** (Increment 7), then **re-shipped typed**
   (Increment 9, 2026-07-20). Designs:
   [`superpowers/specs/2026-07-15-experiment-orchestrator-7-parametrized-repetition-design.md`](superpowers/specs/2026-07-15-experiment-orchestrator-7-parametrized-repetition-design.md)
   and
   [`superpowers/specs/2026-07-20-typed-group-parameters-design.md`](superpowers/specs/2026-07-20-typed-group-parameters-design.md).
   Current syntax lives in [`workflow-schema.md`](workflow-schema.md) — read that, not this.

   Increment 7 shipped the macros untyped: `params` was a `list[str]` and `for_each` took a scalar
   `var` over a bare item list, so a hole was a bare textual macro interpolated into every string
   in the body. That worked and it scaled the control law from three hand-copied subtrees to one,
   which is what this limitation asked for. What it could not do was *check* anything: in
   `examples/morbidostat.json` the single `tube` param was simultaneously a stream suffix
   (`od_{tube}`), a binding suffix (`c_{tube}`), an `int` verb param (`position: "{tube}"`), and a
   role suffix (`od_meter_{tube}`), and none of those is a name until expansion has already
   produced one. A typo was not a load error; it was a residual-hole error at some expanded index,
   or a silently valid name that read another tube's data.

   Increment 9 gives each of those four things a kind. `params` is an ordered list of typed
   declarations, `for_each` takes `vars` + a typed row table (the scalar shorthand is removed), and
   `groups` gain `locals` — the streams and bindings a group owns, emitted under a qualified
   instance name (`tube_1_c_series`) and seeded by a constant `init` that the expander hoists,
   which is what deleted the doc's hand-written seeding `for_each`. Roles moved into the workflow
   in the same increment, so a `role<densitometer>` column replaces `od_meter_{tube}` string
   surgery. Everything is checked before expansion; `schema_version` is `2` and v1 documents using
   `groups` or `for_each` do not load, because their param types were never recorded.
   (Stream declarations are no longer hand-written per tube where a group owns them — that half of
   the old caveat is closed; streams a group merely *reads* are still declared explicitly.)
   ```

   Then update the #4 row of the summary table (line ~712) to match:

   ```markdown
   | 4 | ~~Groups not parametrized~~ | ~~Scaling past ~3 vials~~ | **SHIPPED 2026-07-15**, typed 2026-07-20 — `for_each` (typed row table) + typed group params, `locals`, engine-owned roles; see [`workflow-schema.md`](workflow-schema.md) |
   ```

   And append one paragraph to the prose block about #4 (line ~740), after the sentence ending
   "…fifteen hand-copied, byte-identical subtrees.":

   ```markdown
   **#4 was re-shipped typed** (Increment 9, 2026-07-20). The 2026-07-15 version bought the scale;
   it did not buy the safety, because an untyped hole is not a name until expansion makes one, and
   nothing can be checked before that. Kinds, group locals, and engine-owned roles close that gap:
   the four distinct things `{tube}` used to mean are now four declarations, each checked against
   the role, stream, and binding namespaces before a single copy is spliced. It also produced the
   repo's first maintained schema reference, [`workflow-schema.md`](workflow-schema.md) — until
   now the format was documented only inside dated design specs, which are records of decisions and
   go stale by design.
   ```

8. [ ] **Verify the docs and run the full gate.** Check the cross-links resolve and the reference
   is reachable:

   ```
   grep -c 'workflow-schema.md' docs/experiment-engine-limitations.md
   ls docs/workflow-schema.md
   ```

   Expected: `4`; the file listed.

   ```
   .venv/bin/python -m pytest -q
   .venv/bin/python -m mypy src/lab_devices
   .venv/bin/python -m ruff check .
   awk 'length>100 {print FILENAME":"FNR}' tests/test_docs_workflow_schema.py
   ```

   Expected: all tests pass; `Success: no issues found in N source files`; `All checks passed!`; no
   `awk` output. Markdown and JSON are exempt from the 100-column limit, so the reference's tables
   and snippets are not scanned.agentId: ad82a686b3bf866de (use SendMessage with to: 'ad82a686b3bf866de', summary: '<5-10 word recap>' to continue this agent)
<usage>subagent_tokens: 114625
tool_uses: 11
duration_ms: 434851</usage>