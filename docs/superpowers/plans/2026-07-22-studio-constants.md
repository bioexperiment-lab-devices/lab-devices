# Workflow Constants Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add editable, workflow-global, write-once **constants** to Experiment Studio — declared once, reused everywhere an expression is evaluated (guards, durations, counts, compute/record values, value-kind device params, group-call args).

**Architecture:** A constant is a named value seeded into `RunState.bindings` before any block runs, so the existing expression evaluator resolves it for free. First-class top-level `constants` map on the `Workflow` (additive within schema 3). Constants are evaluated in **declaration order** (a constant may reference only earlier constants), which gives cycle-freedom, runtime seed order, and single-pass type inference with no topological sort. The Studio gets an editable "Constants" palette section after Groups; value-kind params/group-args need no new UI because they already accept expression strings — constants just join the expression scope.

**Tech Stack:** Python 3 (engine + FastAPI backend), TypeScript/React/zustand (frontend), pytest, vitest.

## Global Constraints

- **`schema_version` stays 3.** `constants` is an additive optional top-level key; `workflow_to_dict` emits it only when non-empty so existing fixtures round-trip byte-for-byte. Do NOT change `SCHEMA_VERSION` (serialize.py:30).
- **Canonical key order** (both `workflow_to_dict` and `convert.ts::treeToDoc`): `schema_version, metadata, persistence, defaults, roles, streams, constants, groups, blocks`. `constants` sits **between `streams` and `groups`**.
- **Constants are immutable/write-once:** a `compute` / `operator_input` / group-local writing a constant's name is a validation error.
- **Declaration order:** a constant may reference only constants declared *earlier*; no streams, stream-window funcs, or runtime bindings. Forward/self/cyclic refs are errors.
- **JSON key is `as`; Python field is `as_`; TS field is `as`** (mirrors `Compute`/`ComputeBody`).
- **No rename in v1** — constants are add / edit-value / edit-unit / delete only.
- **Frontend control height:** every input/select/inline-button renders at 24px via `controlClass()` / `inlineButtonClass()`; icons via lucide + `IconButton`; no raw glyph buttons (webapp/frontend/CLAUDE.md).
- **Dark theme (shipped #73):** use plain palette classes only (`bg-slate-100`, `text-caption`, `text-red-600`, …) — the `:root[data-theme='dark']` remap handles dark mode. NO `dark:` variants, hex, or arbitrary values. `npm run capture` shoots both themes; probe R5 enforces AA on each. The `ConstantsPanel` classes are all already in the remap.
- **vitest is node-env, pure-functions-only** — no component rendering. Panels are verified by the probe harness, not vitest.

## Environment setup (once, before Task 1)

The worktree has no `.venv` / `node_modules`. From `/Users/khamit/lab-devices-constants`:

```bash
poetry install            # engine + backend deps, installs engine as -e .
cd webapp/frontend && npm ci
```

Test commands used below:
- Engine: `poetry run pytest tests/<file> -v` (from repo root)
- Backend: `cd webapp/backend && poetry run pytest tests/<file> -v`
- Frontend: `cd webapp/frontend && npx vitest run src/<file>` and `npx tsc -b` for typecheck

---

### Task 1: Engine — `ConstantDecl` model + `Workflow.constants`

**Files:**
- Modify: `src/lab_devices/experiment/workflow.py` (add dataclass after `RoleDecl` ~line 61; add field to `Workflow` ~line 89; add `ValueExpr` to the blocks import at line 8)
- Test: `tests/test_experiment_constants.py` (new)

**Interfaces:**
- Produces: `ConstantDecl(value: ValueExpr, as_: str | None = None)`; `Workflow.constants: dict[str, ConstantDecl]` defaulting to `{}`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_experiment_constants.py
from lab_devices.experiment.workflow import ConstantDecl, Workflow


def test_workflow_defaults_constants_to_empty():
    w = Workflow(schema_version=3)
    assert w.constants == {}


def test_constant_decl_holds_value_and_unit():
    c = ConstantDecl(value=37.0, as_="celsius")
    assert c.value == 37.0
    assert c.as_ == "celsius"

    d = ConstantDecl(value="DOSE * COUNT")
    assert d.value == "DOSE * COUNT"
    assert d.as_ is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `poetry run pytest tests/test_experiment_constants.py -v`
Expected: FAIL with `ImportError: cannot import name 'ConstantDecl'`

- [ ] **Step 3: Implement the model**

In `src/lab_devices/experiment/workflow.py`, change the blocks import (line 8):

```python
from lab_devices.experiment.blocks import Block, Retry, ValueExpr
```

Add after `RoleDecl` (after line 61):

```python
@dataclass(frozen=True)
class ConstantDecl:
    """A named, write-once, workflow-global value seeded into RunState.bindings before any
    block runs (constants design 2026-07-22). `value` is a literal or an expression over
    constants declared EARLIER; `as_` optionally asserts a unit (mirrors compute's `as`)."""

    value: ValueExpr
    as_: str | None = None
```

Add the field to `Workflow` (after `roles` at line 88):

```python
    constants: dict[str, ConstantDecl] = field(default_factory=dict)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `poetry run pytest tests/test_experiment_constants.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/lab_devices/experiment/workflow.py tests/test_experiment_constants.py
git commit -m "feat(engine): add ConstantDecl model + Workflow.constants"
```

---

### Task 2: Engine — parse & serialize `constants`

**Files:**
- Modify: `src/lab_devices/experiment/serialize.py` (`workflow_from_dict` ~line 565-590; `workflow_to_dict` ~line 628-648)
- Test: `tests/test_experiment_constants.py`; update `tests/test_experiment_serialize_v3.py` key-order test

**Interfaces:**
- Consumes: `ConstantDecl`, `Workflow.constants` (Task 1).
- Produces: `workflow_from_dict` parses `d["constants"]`; `workflow_to_dict` emits `out["constants"]` when non-empty, in canonical position.

- [ ] **Step 1: Write the failing round-trip test**

```python
# tests/test_experiment_constants.py  (append)
from lab_devices.experiment.serialize import workflow_from_dict, workflow_to_dict


def _doc(constants):
    return {"schema_version": 3, "persistence": {"default": "in_memory", "format": "jsonl"},
            "constants": constants, "blocks": []}


def test_constants_round_trip():
    doc = _doc({"MAX_TEMP": {"value": 37.0, "as": "celsius"},
               "DOSES": {"value": 3},
               "TOTAL_ML": {"value": "DOSES * 2"}})
    w = workflow_from_dict(doc)
    assert w.constants["MAX_TEMP"].value == 37.0
    assert w.constants["MAX_TEMP"].as_ == "celsius"
    assert w.constants["TOTAL_ML"].value == "DOSES * 2"
    out = workflow_to_dict(w)
    assert out["constants"] == doc["constants"]


def test_empty_constants_are_omitted():
    out = workflow_to_dict(workflow_from_dict(_doc({})))
    assert "constants" not in out
```

- [ ] **Step 2: Run to verify it fails**

Run: `poetry run pytest tests/test_experiment_constants.py::test_constants_round_trip -v`
Expected: FAIL — `w.constants` is empty (parser ignores the key).

- [ ] **Step 3: Implement parse**

In `workflow_from_dict`, immediately after the `streams` loop (after line 576, before the `groups` loop), add. Mirror the streams block's use of `_obj`, `_str`, `parse_unit`, and the local-init `_checked_expr` helper:

```python
    constants: dict[str, ConstantDecl] = {}
    for name, cv in _obj(d.get("constants", {}), "constants").items():
        c = _obj(cv, f"constant {name!r}")
        if "value" not in c:
            raise WorkflowLoadError(f"constant {name!r} must declare a `value`")
        value = c["value"]
        if isinstance(value, str):
            value = _checked_expr(value, f"constant {name!r} value")
        elif not isinstance(value, (int, float, bool)):
            raise WorkflowLoadError(
                f"constant {name!r} value must be a number, bool, or expression string"
            )
        as_ = c.get("as")
        if as_ is not None:
            as_ = _str(as_, f"constant {name!r} as")
            parse_unit(as_)  # validate the unit annotation now (raises UnitError on a bad unit)
        constants[name] = ConstantDecl(value=value, as_=as_)
```

Add `constants=constants` to the `Workflow(...)` constructor (line 587-590):

```python
    return Workflow(
        schema_version=version, blocks=blocks, metadata=metadata, persistence=persistence,
        streams=streams, constants=constants, groups=groups, roles=roles, defaults=defaults,
    )
```

Add `ConstantDecl` to the workflow import at the top of serialize.py (find the `from lab_devices.experiment.workflow import ...` line and add `ConstantDecl`). Confirm `_checked_expr` is the helper used by `_local_decls` for `init` (serialize.py ~line 500); if its name differs, use the same helper `_local_decls` calls.

- [ ] **Step 4: Implement serialize**

In `workflow_to_dict`, after the `if w.streams:` block (after line 633) and before the `if w.groups:` block, add:

```python
    if w.constants:
        out["constants"] = {
            name: ({"value": c.value} if c.as_ is None else {"value": c.value, "as": c.as_})
            for name, c in w.constants.items()
        }
```

- [ ] **Step 5: Update the key-order test**

In `tests/test_experiment_serialize_v3.py`, the `test_emitted_key_order_*` test (~line 222-227) asserts the full key list. It uses `V3_DOC`, which has no constants, so `constants` will NOT appear — leave that assertion as-is. Add a dedicated ordering test to `tests/test_experiment_constants.py`:

```python
def test_constants_key_sits_between_streams_and_groups():
    doc = {"schema_version": 3, "persistence": {"default": "in_memory", "format": "jsonl"},
           "streams": {"od": {"units": "unitless"}},
           "constants": {"K": {"value": 1}},
           "groups": {},
           "blocks": []}
    out = workflow_to_dict(workflow_from_dict(doc))
    keys = [k for k in out if k in ("streams", "constants", "groups")]
    assert keys == ["streams", "constants"]  # groups empty -> omitted; constants after streams
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `poetry run pytest tests/test_experiment_constants.py tests/test_experiment_serialize_v3.py tests/test_experiment_serialize.py -v`
Expected: PASS (existing serialize tests stay green — constants omitted when empty).

- [ ] **Step 7: Commit**

```bash
git add src/lab_devices/experiment/serialize.py tests/test_experiment_constants.py
git commit -m "feat(engine): parse and serialize the constants map"
```

---

### Task 3: Engine — type + unit inference for constants

**Files:**
- Modify: `src/lab_devices/experiment/validate.py` (`_collect_binding_types` ~line 642-670; add a `_constant_type` helper)
- Test: `tests/test_experiment_constants.py`

**Interfaces:**
- Consumes: `Workflow.constants`, `infer_type`, `ScalarType`, `UNKNOWN`, `_cast_unit`, `parse_expression`, `ExpressionError` (already imported in validate.py).
- Produces: constants appear in `binding_types(w)` with inferred `{base, unit}`; a compute referencing a constant type-checks against it.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_experiment_constants.py  (append)
from lab_devices.experiment.validate import binding_types


def test_constants_appear_in_binding_types_with_units():
    w = workflow_from_dict(_doc({"MAX_TEMP": {"value": 37.0, "as": "celsius"},
                                 "DOSES": {"value": 3}}))
    types = binding_types(w)
    assert types["DOSES"].base == "int"
    assert types["MAX_TEMP"].base == "number"
    from lab_devices.experiment.units import unit_str
    assert unit_str(types["MAX_TEMP"].unit) == "celsius"


def test_derived_constant_infers_from_earlier_constant():
    w = workflow_from_dict(_doc({"DOSES": {"value": 3}, "TOTAL": {"value": "DOSES * 2"}}))
    assert binding_types(w)["TOTAL"].base == "int"
```

- [ ] **Step 2: Run to verify it fails**

Run: `poetry run pytest tests/test_experiment_constants.py::test_constants_appear_in_binding_types_with_units -v`
Expected: FAIL with `KeyError: 'DOSES'` (constants not in the type env).

- [ ] **Step 3: Implement**

In `validate.py`, add a helper above `_collect_binding_types`:

```python
def _constant_type(
    decl: ConstantDecl, types: Mapping[str, BindingType], stream_units: Mapping[str, Unit]
) -> BindingType:
    """Inferred type of one constant: literals map by Python type, expressions infer against the
    constants declared before them; an `as` cast asserts the unit (constants design §5)."""
    value = decl.value
    if isinstance(value, str):
        try:
            inferred = infer_type(parse_expression(value), types, stream_units).type
        except ExpressionError:
            inferred = UNKNOWN
    elif isinstance(value, bool):          # bool is an int subclass — check first
        inferred = ScalarType("bool")
    elif isinstance(value, int):
        inferred = ScalarType("int")
    else:                                   # float
        inferred = ScalarType("number")
    cast = _cast_unit(decl.as_)
    if cast is not None:
        inferred = ScalarType(inferred.base, cast)
    return inferred
```

In `_collect_binding_types`, seed constants FIRST (right after `types: dict[str, BindingType] = {}` and the `record` def, before the `for _, b in _iter_all_blocks(w):` loop):

```python
    for name, decl in w.constants.items():
        types[name] = _constant_type(decl, types, stream_units)
```

Ensure `ConstantDecl` is imported in validate.py (add to its `from lab_devices.experiment.workflow import ...` line).

- [ ] **Step 4: Run tests to verify they pass**

Run: `poetry run pytest tests/test_experiment_constants.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/lab_devices/experiment/validate.py tests/test_experiment_constants.py
git commit -m "feat(engine): infer base+unit types for constants"
```

---

### Task 4: Engine — validation rules (identifier, earlier-only, static-only, immutability, collision)

**Files:**
- Modify: `src/lab_devices/experiment/validate.py` (add `_check_constants`; call it in `_validate_workflow` ~line 1605; extend `_check_namespaces` ~line 1144-1177)
- Test: `tests/test_experiment_constants.py`

**Interfaces:**
- Consumes: `references`, `parse_expression`, `ExpressionError`, `Diagnostic` (imported). Uses `w.constants`, `w.streams`, block iteration.
- Produces: `_check_constants(w, out)` appends diagnostics; `_check_namespaces` gains constant-vs-stream and constant-vs-binding-writer checks.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_experiment_constants.py  (append)
import pytest
from lab_devices.experiment.validate import validate
from lab_devices.experiment.errors import ValidationError


def _messages(doc):
    try:
        validate(workflow_from_dict(doc))
    except ValidationError as exc:
        return [d.message for d in exc.diagnostics]
    return []


def test_constant_bad_identifier_rejected():
    msgs = _messages(_doc({"1bad": {"value": 1}}))
    assert any("identifier" in m for m in msgs)


def test_constant_forward_reference_rejected():
    # TOTAL declared before DOSES -> forward ref
    msgs = _messages(_doc({"TOTAL": {"value": "DOSES * 2"}, "DOSES": {"value": 3}}))
    assert any("DOSES" in m and "earlier" in m for m in msgs)


def test_constant_self_reference_rejected():
    msgs = _messages(_doc({"X": {"value": "X + 1"}}))
    assert any("'X'" in m and "earlier" in m for m in msgs)


def test_constant_reading_stream_rejected():
    doc = {"schema_version": 3, "persistence": {"default": "in_memory", "format": "jsonl"},
           "streams": {"od": {"units": "unitless"}},
           "constants": {"K": {"value": "mean(od, 5min)"}}, "blocks": []}
    msgs = _messages(doc)
    assert any("static" in m or "stream" in m for m in msgs)


def test_compute_writing_constant_name_rejected():
    doc = {"schema_version": 3, "persistence": {"default": "in_memory", "format": "jsonl"},
           "constants": {"K": {"value": 1}},
           "blocks": [{"compute": {"into": "K", "value": 2}}]}
    msgs = _messages(doc)
    assert any("'K'" in m and "constant" in m for m in msgs)


def test_constant_name_colliding_with_stream_rejected():
    doc = {"schema_version": 3, "persistence": {"default": "in_memory", "format": "jsonl"},
           "streams": {"od": {"units": "unitless"}},
           "constants": {"od": {"value": 1}}, "blocks": []}
    msgs = _messages(doc)
    assert any("'od'" in m for m in msgs)


def test_valid_derived_constants_pass():
    doc = _doc({"DOSES": {"value": 3}, "ML_PER_DOSE": {"value": 2.5},
                "TOTAL_ML": {"value": "DOSES * ML_PER_DOSE"}})
    assert _messages(doc) == []
```

- [ ] **Step 2: Run to verify they fail**

Run: `poetry run pytest tests/test_experiment_constants.py -k "rejected or valid_derived" -v`
Expected: FAIL (no such validation yet; several return `[]`).

- [ ] **Step 3: Implement `_check_constants`**

Add to `validate.py` (near `_check_local_init`). First add a module-level identifier regex if one is not already present (search for an existing `re.compile(r"...identifier..."`); reuse it if found, otherwise add):

```python
import re  # if not already imported
_CONSTANT_NAME_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*$")


def _check_constants(w: Workflow, out: list[Diagnostic]) -> None:
    """Constants are static and declaration-ordered (constants design §5): a valid identifier,
    referencing only constants declared EARLIER, never a stream/window/runtime binding."""
    seen: set[str] = set()
    for name, decl in w.constants.items():
        where = f"constants[{name!r}]"
        if not _CONSTANT_NAME_RE.match(name):
            out.append(Diagnostic("declaration", where,
                                   f"constant name {name!r} must be an identifier"))
        if isinstance(decl.value, str):
            try:
                expr = parse_expression(decl.value)
            except ExpressionError as exc:
                out.append(Diagnostic("declaration", where,
                                      f"invalid constant expression: {exc}"))
                seen.add(name)
                continue
            refs = references(expr)
            bad_streams = sorted(refs.streams_windowed | refs.streams_counted)
            if bad_streams:
                reads = ", ".join(repr(n) for n in bad_streams)
                out.append(Diagnostic("declaration", where,
                    f"constant {name!r} must be static, but reads stream(s) {reads}; a constant "
                    f"is evaluated before any block runs (constants design §5)"))
            for b in sorted(refs.bindings):
                if b not in seen:
                    out.append(Diagnostic("declaration", where,
                        f"constant {name!r} references {b!r}, which is not a constant declared "
                        f"earlier; constants are evaluated top-to-bottom (constants design §5)"))
        seen.add(name)
```

Call it in `_validate_workflow` next to the other declaration checks (after the `_check_namespaces(...)` call, ~line 1605):

```python
    _check_constants(workflow, out)
```

- [ ] **Step 4: Implement the namespace/immutability checks**

In `_check_namespaces` (validate.py ~line 1172, after the existing `compute_names & input_names` block), add:

```python
    const_names = set(w.constants)
    for n in sorted(const_names & declared):
        out.append(Diagnostic("declaration", "names",
            f"name {n!r} is used as both a constant and a stream"))
    for n in sorted(const_names & binding_names):
        out.append(Diagnostic("declaration", "bindings",
            f"{n!r} is a constant and cannot also be written by compute or operator_input; "
            f"constants are write-once (constants design §5)"))
```

(`binding_names = input_names | compute_names` and `declared = set(w.streams)` already exist in that function.)

- [ ] **Step 5: Run tests to verify they pass**

Run: `poetry run pytest tests/test_experiment_constants.py -v`
Expected: PASS. Then run the full validate suite to confirm no regressions:
Run: `poetry run pytest tests/test_experiment_validate.py tests/test_experiment_units_validate.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/lab_devices/experiment/validate.py tests/test_experiment_constants.py
git commit -m "feat(engine): validate constants (identifier, earlier-only, static, immutable)"
```

---

### Task 5: Engine — seed constants into RunState before blocks

**Files:**
- Modify: `src/lab_devices/experiment/run.py` (`ExperimentRun.__init__`, after stream pre-creation ~line 141-143; add imports for `evaluate`/`parse_expression`)
- Test: `tests/test_experiment_constants.py` (a real run; reuse the run helpers already used by other run tests)

**Interfaces:**
- Consumes: `Workflow.constants`, `RunState.bind`, `evaluate`, `parse_expression`.
- Produces: at run start, every constant is bound in `RunState.bindings`; derived constants resolve against earlier ones.

- [ ] **Step 1: Write the failing test**

Model this on an existing run test (see `tests/test_experiment_run.py` / `tests/experiment_run_helpers.py` for the harness that drives a workflow with a fake clock/devices). The behavioral assertion: a `branch` whose condition reads a constant takes the expected arm, and a derived constant resolves.

```python
# tests/test_experiment_constants.py  (append)
from tests.experiment_run_helpers import run_workflow_doc  # existing helper; adjust name to match repo


def test_constant_is_bound_before_blocks_and_derives():
    # THRESHOLD=10, LIMIT=THRESHOLD*2=20 ; a compute copies LIMIT into a binding we can read back.
    doc = {"schema_version": 3, "persistence": {"default": "in_memory", "format": "jsonl"},
           "constants": {"THRESHOLD": {"value": 10}, "LIMIT": {"value": "THRESHOLD * 2"}},
           "blocks": [{"compute": {"into": "seen_limit", "value": "LIMIT"}}]}
    result = run_workflow_doc(doc)
    assert result.state.bindings["THRESHOLD"] == 10
    assert result.state.bindings["LIMIT"] == 20
    assert result.state.bindings["seen_limit"] == 20
```

If `run_workflow_doc` does not exist under that name, use whatever helper `tests/test_experiment_run.py` uses to execute a doc and expose final `RunState`; the assertion set is what matters.

- [ ] **Step 2: Run to verify it fails**

Run: `poetry run pytest tests/test_experiment_constants.py::test_constant_is_bound_before_blocks_and_derives -v`
Expected: FAIL — `seen_limit` compute raises `unbound binding 'LIMIT'` (constants not seeded).

- [ ] **Step 3: Implement seeding**

In `run.py`, add imports near the other engine imports:

```python
from lab_devices.experiment.evaluate import evaluate
from lab_devices.experiment.expr import parse_expression
```

In `ExperimentRun.__init__`, right after the stream pre-creation loop (after `state.streams[stream_name] = Stream()`, ~line 143):

```python
        # Seed constants before any block runs, in declaration order so a derived constant sees
        # its (earlier) dependencies (constants design §5). Constant expressions reference only
        # other constants, so `now` is irrelevant — pass 0.0.
        for const_name, decl in workflow.constants.items():
            value = decl.value
            if isinstance(value, str):
                value = evaluate(parse_expression(value), state, 0.0)
            state.bind(const_name, value)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `poetry run pytest tests/test_experiment_constants.py -v`
Expected: PASS

- [ ] **Step 5: Run the broader engine suite**

Run: `poetry run pytest tests/ -q`
Expected: PASS (no regressions across engine tests).

- [ ] **Step 6: Commit**

```bash
git add src/lab_devices/experiment/run.py tests/test_experiment_constants.py
git commit -m "feat(engine): seed constants into RunState before blocks"
```

---

### Task 6: Backend — constants survive expand and reach `/api/validate`

**Files:**
- Verify/modify: `src/lab_devices/experiment/expand.py` (ensure `expand_dict_traced` preserves the top-level `constants` key)
- Test: `webapp/backend/tests/test_validate_api.py` (add cases) and/or `tests/test_experiment_expand.py`

**Interfaces:**
- Consumes: `expand_dict_traced`, `validate_doc`, `binding_types_for_doc` (unchanged signatures).
- Produces: a doc with constants validates cleanly and its constants appear in the `/validate` `binding_types`.

- [ ] **Step 1: Write the failing test**

```python
# webapp/backend/tests/test_validate_api.py  (append a test; reuse the module's TestClient fixture)
def test_validate_surfaces_constants(client):   # adjust fixture name to the module's convention
    doc = {"doc_version": 1, "name": "c", "description": None,
           "workflow": {"schema_version": 3,
                        "persistence": {"default": "in_memory", "format": "jsonl"},
                        "constants": {"MAX_TEMP": {"value": 37.0, "as": "celsius"}},
                        "blocks": []}}
    resp = client.post("/validate", json=doc)
    body = resp.json()
    assert body["ok"] is True
    assert body["binding_types"]["MAX_TEMP"] == {"base": "number", "unit": "celsius"}
```

- [ ] **Step 2: Run to verify it fails or passes**

Run: `cd webapp/backend && poetry run pytest tests/test_validate_api.py::test_validate_surfaces_constants -v`
Expected: If `expand_dict_traced` drops the key → FAIL (`binding_types` missing `MAX_TEMP`). If it already passes, constants ride through expand for free — record that and skip Step 3.

- [ ] **Step 3: If failing, make expand preserve constants**

Open `src/lab_devices/experiment/expand.py`, find `expand_dict_traced`, and confirm the output dict is built from a copy of the input (so unknown top-level keys carry through). If it constructs `out` from scratch, add `constants` to the passthrough (mirror how `roles`/`streams` are carried). Add a focused engine test:

```python
# tests/test_experiment_expand.py  (append)
from lab_devices.experiment.expand import expand_dict_traced

def test_expand_preserves_constants():
    doc = {"schema_version": 3, "persistence": {"default": "in_memory", "format": "jsonl"},
           "constants": {"K": {"value": 1}}, "blocks": []}
    expanded, _ = expand_dict_traced(doc)
    assert expanded["constants"] == {"K": {"value": 1}}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd webapp/backend && poetry run pytest tests/test_validate_api.py -v` and `poetry run pytest tests/test_experiment_expand.py -v`
Expected: PASS. Confirm the pre-existing 7 exact-equality `/validate` tests stay green (their docs are constant-free).

- [ ] **Step 5: Commit**

```bash
git add webapp/backend/tests/test_validate_api.py tests/test_experiment_expand.py src/lab_devices/experiment/expand.py
git commit -m "test(backend): constants validate and surface in binding_types"
```

---

### Task 7: Frontend — doc types

**Files:**
- Modify: `webapp/frontend/src/types/doc.ts` (add `ConstantDeclJson`; add `constants` to `WorkflowJson`)

**Interfaces:**
- Produces: `ConstantDeclJson { value: ParamValue; as?: string | null }`; `WorkflowJson.constants?: Record<string, ConstantDeclJson>`.

- [ ] **Step 1: Add the types**

In `webapp/frontend/src/types/doc.ts`, after `ComputeBody` (~line 111), add:

```ts
/** A workflow-global, write-once constant (constants design 2026-07-22). `value` mirrors
 * ComputeBody.value (literal or expression string); `as` optionally asserts a unit. */
export interface ConstantDeclJson {
  value: ParamValue
  as?: string | null
}
```

In `WorkflowJson` (~line 166-175), add after `streams`:

```ts
  constants?: Record<string, ConstantDeclJson>
```

- [ ] **Step 2: Typecheck**

Run: `cd webapp/frontend && npx tsc -b`
Expected: PASS (no consumers yet).

- [ ] **Step 3: Commit**

```bash
git add webapp/frontend/src/types/doc.ts
git commit -m "feat(studio): ConstantDeclJson + WorkflowJson.constants type"
```

---

### Task 8: Frontend — convert.ts JSON↔node

**Files:**
- Modify: `webapp/frontend/src/builder/convert.ts` (`DocContent` type ~line 37-67; `docToTree` ~line 78-123; `treeToDoc` ~line 267-285)
- Test: `webapp/frontend/src/builder/convert.test.ts`

**Interfaces:**
- Consumes: `ConstantDeclJson` (Task 7).
- Produces: `DocContent.constants?: Record<string, ConstantDeclJson>`; `docToTree` reads `wf.constants`; `treeToDoc` emits `constants` between `streams` and `groups`.

- [ ] **Step 1: Write the failing round-trip test**

```ts
// webapp/frontend/src/builder/convert.test.ts  (append; follow the file's existing import style)
it('round-trips constants and places the key between streams and groups', () => {
  const doc = {
    doc_version: 1, name: 'c', description: null,
    workflow: {
      schema_version: 3,
      persistence: { default: 'in_memory', format: 'jsonl' },
      streams: { od: { units: 'unitless' } },
      constants: { MAX: { value: 37, as: 'celsius' }, DERIVED: { value: 'MAX * 2' } },
      blocks: [],
    },
  }
  const back = treeToDoc(docToTree(doc as never))
  expect(back.workflow.constants).toEqual(doc.workflow.constants)
  const keys = Object.keys(back.workflow).filter((k) => ['streams', 'constants', 'groups'].includes(k))
  expect(keys).toEqual(['streams', 'constants'])
})
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd webapp/frontend && npx vitest run src/builder/convert.test.ts`
Expected: FAIL — `constants` undefined on the round-tripped workflow.

- [ ] **Step 3: Implement**

In `convert.ts`, add to `DocContent` (near `streams`):

```ts
  constants?: Record<string, import('../types/doc').ConstantDeclJson>
```

In `docToTree`, after reading `streams` into the result, add a passthrough (constants are a plain record, no node translation):

```ts
  const constants = wf.constants
```

and include `constants` in the returned `DocContent` object.

In `treeToDoc`, insert into the `workflow` object literal between `streams` and the groups spread (matching the engine's canonical order):

```ts
    streams,
    ...(content.constants !== undefined && Object.keys(content.constants).length > 0
      ? { constants: content.constants }
      : {}),
    ...(groups !== undefined ? { groups } : {}),
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd webapp/frontend && npx vitest run src/builder/convert.test.ts`
Expected: PASS (the golden byte-exact test stays green — its fixtures have no constants).

- [ ] **Step 5: Commit**

```bash
git add webapp/frontend/src/builder/convert.ts webapp/frontend/src/builder/convert.test.ts
git commit -m "feat(studio): carry constants through convert.ts"
```

---

### Task 9: Frontend — expression-aware reference counter

**Files:**
- Modify: `webapp/frontend/src/builder/bindings.ts` (export a `countBindingRefs`)
- Test: `webapp/frontend/src/builder/bindings.test.ts`

**Interfaces:**
- Consumes: `exprFields`, `bindingReferences` (in bindings.ts), `visitNodes` (tree.ts).
- Produces: `countBindingRefs(tree: BlockNode[], name: string): number` — how many expression fields cite `name`.

- [ ] **Step 1: Write the failing test**

```ts
// webapp/frontend/src/builder/bindings.test.ts  (append)
import { countBindingRefs } from './bindings'

it('counts expression fields that reference a name', () => {
  const tree = [
    { uid: '1', kind: 'compute', into: 'x', value: 'K + 1' },
    { uid: '2', kind: 'branch', condition: 'K > 0', then: [], else: [] },
    { uid: '3', kind: 'wait', duration: '5min' },
  ] as never
  expect(countBindingRefs(tree, 'K')).toBe(2)
  expect(countBindingRefs(tree, 'Z')).toBe(0)
})
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd webapp/frontend && npx vitest run src/builder/bindings.test.ts`
Expected: FAIL — `countBindingRefs` not exported.

- [ ] **Step 3: Implement**

In `bindings.ts` add (ensure `visitNodes` is imported from `./tree`):

```ts
/** How many expression-bearing fields in `tree` reference the bare name `name`. Used by the
 * constants delete-refusal check — constants live in the binding namespace and are cited inside
 * expression strings, not structural node fields (constants design §7). */
export function countBindingRefs(tree: BlockNode[], name: string): number {
  const names = new Set([name])
  let count = 0
  visitNodes(tree, (node) => {
    for (const [, text] of exprFields(node)) {
      if (bindingReferences(text, names).length > 0) count++
    }
  })
  return count
}
```

If `exprFields` is not currently exported/module-visible where you place this, keep the function in the same file so it sees `exprFields` directly.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd webapp/frontend && npx vitest run src/builder/bindings.test.ts`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add webapp/frontend/src/builder/bindings.ts webapp/frontend/src/builder/bindings.test.ts
git commit -m "feat(studio): countBindingRefs for constant reference scans"
```

---

### Task 10: Frontend — docStore constants state + actions

**Files:**
- Modify: `webapp/frontend/src/stores/docStore.ts` (state field; enumeration sites `selectContent`, `snapshotOf`, `emptyContent`, `partialize`, `loadDoc` normalize, initial state; actions + interface)
- Test: `webapp/frontend/src/stores/docStore.test.ts`

**Interfaces:**
- Consumes: `ConstantDeclJson` (Task 7), `countBindingRefs` (Task 9).
- Produces: store field `constants: Record<string, ConstantDeclJson>`; actions `addConstant(name, value, unit?) => string | null`, `setConstantValue(name, value) => void`, `setConstantUnit(name, unit) => void`, `removeConstant(name) => string | null`.

- [ ] **Step 1: Write the failing test**

```ts
// webapp/frontend/src/stores/docStore.test.ts  (append; mirror the 'stream lifecycle' test)
describe('constants lifecycle', () => {
  it('adds, edits, refuses dup, refuses delete-while-referenced, then deletes', () => {
    const s = store()  // the file's existing store() helper after newDoc()
    expect(s().addConstant('MAX', 37)).toBeNull()
    expect(s().constants.MAX).toEqual({ value: 37 })
    expect(s().addConstant('MAX', 1)).toMatch(/already exists/)
    expect(s().addConstant('1bad', 1)).toMatch(/identifier/)

    s().setConstantUnit('MAX', 'celsius')
    expect(s().constants.MAX).toEqual({ value: 37, as: 'celsius' })
    s().setConstantValue('MAX', 'OTHER * 2')
    expect(s().constants.MAX.value).toBe('OTHER * 2')

    // reference it from a compute, then deletion must be refused
    s().addBlockAtEnd?.({ kind: 'compute', into: 'y', value: 'MAX + 1' } as never)
    // (use whatever the test file uses to seed a referencing block; see the group-delete test)
    expect(s().removeConstant('MAX')).toMatch(/used by/)
  })
})
```

Adapt the referencing-block insertion to match how `docStore.test.ts`'s `removeGroup`-refusal test seeds a referencing node.

- [ ] **Step 2: Run to verify it fails**

Run: `cd webapp/frontend && npx vitest run src/stores/docStore.test.ts`
Expected: FAIL — `addConstant` undefined.

- [ ] **Step 3: Implement state + enumeration**

In `docStore.ts`:

Add the regex near the other name regexes (~line 30-41):

```ts
const CONSTANT_NAME_RE = /^[A-Za-z_][A-Za-z0-9_]*$/
```

Add to `DocSnapshot` (~line 43-69), after `streams`:

```ts
  constants: Record<string, ConstantDeclJson>
```

Add `constants: {}` to: the initial-state spread (~line 231-236), `emptyContent` (~line 163-170). Add `constants` handling to `selectContent` (~line 127-137) so it feeds `treeToDoc`, to `snapshotOf` (~line 145-156) so edits dirty the doc, to `partialize` (~line 435-448) so constant edits are undoable, and to `loadDoc`'s `normalized` defaulting (~line 512-547) as `constants: doc.workflow.constants ?? {}` (via the `DocContent` produced by `docToTree`). Import `ConstantDeclJson` and `countBindingRefs`.

- [ ] **Step 4: Implement actions**

Add signatures to the store interface (~line 103-117):

```ts
  addConstant: (name: string, value: ParamValue, unit?: string | null) => string | null
  setConstantValue: (name: string, value: ParamValue) => void
  setConstantUnit: (name: string, unit: string | null) => void
  removeConstant: (name: string) => string | null
```

Add the bodies (near the stream actions ~line 316-355):

```ts
      addConstant: (name, value, unit) => {
        if (!CONSTANT_NAME_RE.test(name)) return `constant name must be an identifier`
        if (name in get().constants) return `constant '${name}' already exists`
        const decl: ConstantDeclJson = unit ? { value, as: unit } : { value }
        set((s) => ({ constants: { ...s.constants, [name]: decl } }))
        return null
      },

      setConstantValue: (name, value) =>
        set((s) => ({
          constants: name in s.constants
            ? { ...s.constants, [name]: { ...s.constants[name], value } }
            : s.constants,
        })),

      setConstantUnit: (name, unit) =>
        set((s) => ({
          constants: name in s.constants
            ? { ...s.constants, [name]: { ...s.constants[name], as: unit ?? undefined } }
            : s.constants,
        })),

      removeConstant: (name) => {
        const { tree, groups } = get()
        let refs = countBindingRefs(tree, name)
        for (const g of Object.values(groups)) refs += countBindingRefs(g.body, name)
        if (refs > 0) return `constant '${name}' is used by ${refs} block${refs === 1 ? '' : 's'}`
        set((s) => ({ constants: removeKey(s.constants, name) }))
        return null
      },
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd webapp/frontend && npx vitest run src/stores/docStore.test.ts`
Expected: PASS. Also add `constants` to the existing round-trip and dirty-check tests if the file asserts full-doc equality (mirror how `groups` was added to them).

- [ ] **Step 6: Commit**

```bash
git add webapp/frontend/src/stores/docStore.ts webapp/frontend/src/stores/docStore.test.ts
git commit -m "feat(studio): constants state + add/edit/remove actions in docStore"
```

---

### Task 11: Frontend — constants join the expression scope

**Files:**
- Modify: `webapp/frontend/src/builder/ExpressionEditor.tsx` (scope assembly ~line 43, 57-63)
- Verify: `webapp/frontend/src/builder/Inspector.tsx` `ParamInput` / `ArgField` route their expression inputs through the same scope (grep for `ExpressionInput` and where it builds `ExprScope`)
- Test: `webapp/frontend/src/builder/expr/complete.test.ts`, `webapp/frontend/src/builder/expr/analyze.test.ts`

**Interfaces:**
- Consumes: `docStore.constants`.
- Produces: constant names present in `ExprScope.bindings` for every expression editor, so autocomplete offers them and the "unknown binding" check accepts them.

- [ ] **Step 1: Write the failing tests**

```ts
// webapp/frontend/src/builder/expr/complete.test.ts  (append)
it('completes a constant name from scope.bindings', () => {
  const scope = { streams: [], bindings: ['FEED_RATE'] }
  const items = completionsAt('FEED', 4, scope)   // match the file's completionsAt signature
  expect(items.some((i) => i.label === 'FEED_RATE' && i.kind === 'binding')).toBe(true)
})
```

```ts
// webapp/frontend/src/builder/expr/analyze.test.ts  (append)
it('does not flag a constant in scope as an unknown binding', () => {
  const res = analyzeExpression('FEED_RATE * 2', { streams: [], bindings: ['FEED_RATE'] })
  expect(res.diagnostics.some((d) => /unknown binding/.test(d.message))).toBe(false)
})
```

These pass if the analyzers already treat `scope.bindings` uniformly (likely). Their purpose is to lock the contract; the real wiring is in ExpressionEditor. If they already pass, keep them as regression guards and proceed to Step 3.

- [ ] **Step 2: Run the tests**

Run: `cd webapp/frontend && npx vitest run src/builder/expr/complete.test.ts src/builder/expr/analyze.test.ts`
Expected: PASS (they assert the pure-analyzer contract constants rely on).

- [ ] **Step 3: Wire constants into the editor scope**

In `ExpressionEditor.tsx`, add a store subscription next to the existing `streams` one (~line 43):

```ts
  const constants = useDocStore((s) => s.constants)
```

Update the `scope` memo (~line 57-63) to union constant names into `bindings`:

```ts
  const scope = useMemo<ExprScope>(
    () => ({
      streams: scopeStreamNames(streams, group),
      bindings: Array.from(
        new Set([...collectBindings(activeTree), ...scopeBindingNames(group), ...Object.keys(constants)]),
      ),
    }),
    [streams, group, activeTree, constants],
  )
```

- [ ] **Step 4: Verify param/group-arg editors inherit the scope**

Grep: `cd webapp/frontend && grep -rn "ExpressionInput\|ExprScope" src/builder/Inspector.tsx`. Confirm `ParamInput` and `ArgField` render their expression field through `ExpressionEditor` (or a wrapper that reuses the same scope memo). If either builds its own `ExprScope.bindings`, apply the same `...Object.keys(constants)` union there. Document the finding in the commit message.

- [ ] **Step 5: Typecheck + run**

Run: `cd webapp/frontend && npx tsc -b && npx vitest run src/builder/expr`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add webapp/frontend/src/builder/ExpressionEditor.tsx webapp/frontend/src/builder/expr
git commit -m "feat(studio): constants autocomplete and type-check in every expression field"
```

---

### Task 12: Frontend — ConstantsPanel + palette wiring

**Files:**
- Create: `webapp/frontend/src/builder/ConstantsPanel.tsx`
- Modify: `webapp/frontend/src/builder/Palette.tsx` (import + a `<Section title="Constants">` after Groups ~line 138)

**Interfaces:**
- Consumes: `docStore` constants actions (Task 10), `docStore.bindingTypes` (existing), `ExpressionEditor` (Task 11), `controlClass`/`inlineButtonClass`, `IconButton`.
- Produces: an editable Constants section in the palette. No vitest (probe territory).

- [ ] **Step 1: Implement ConstantsPanel**

Model on `StreamsPanel.tsx`. Name is a fixed label (no rename). Value uses `ExpressionEditor` with a coerce-on-commit; unit is a text input; a small type badge reads `bindingTypes[name]`; delete surfaces the refusal reason.

```tsx
// webapp/frontend/src/builder/ConstantsPanel.tsx
import { useState } from 'react'
import { X } from 'lucide-react'
import { useDocStore } from '../stores/docStore'
import { ExpressionEditor } from './ExpressionEditor'
import { controlClass, inlineButtonClass } from '../ui/controls'
import { IconButton } from '../ui/IconButton'
import type { ParamValue } from '../types/doc'

function coerceConstantValue(text: string): ParamValue {
  const s = text.trim()
  if (/^-?\d+$/.test(s)) return Number(s)
  if (/^-?\d+\.\d+$/.test(s)) return Number(s)
  if (s === 'true') return true
  if (s === 'false') return false
  return text
}

const valueText = (v: ParamValue): string =>
  typeof v === 'number' || typeof v === 'boolean' ? String(v) : v

function TypeBadge({ name }: { name: string }) {
  const t = useDocStore((s) => s.bindingTypes[name])
  if (!t) return null
  const showUnit = t.unit !== 'unitless' && (t.base === 'int' || t.base === 'number')
  return (
    <span className="shrink-0 rounded bg-slate-100 px-1 text-xs text-caption"
      title={showUnit ? `${t.base} in ${t.unit}` : t.base}>
      {t.base}{showUnit && <span className="text-hint">{`<${t.unit}>`}</span>}
    </span>
  )
}

export function ConstantsPanel() {
  const constants = useDocStore((s) => s.constants)
  const addConstant = useDocStore((s) => s.addConstant)
  const setConstantValue = useDocStore((s) => s.setConstantValue)
  const setConstantUnit = useDocStore((s) => s.setConstantUnit)
  const removeConstant = useDocStore((s) => s.removeConstant)
  const [newName, setNewName] = useState('')
  const [newValue, setNewValue] = useState('')
  const [error, setError] = useState<string | null>(null)

  const add = (): void => {
    if (!newName.trim()) return
    const err = addConstant(newName.trim(), coerceConstantValue(newValue))
    setError(err)
    if (!err) { setNewName(''); setNewValue('') }
  }

  return (
    <div className="space-y-1">
      {Object.keys(constants).length === 0 && (
        <p className="px-1 text-xs text-hint">
          No constants yet — declare a reusable value below.
        </p>
      )}
      <ul className="space-y-1">
        {Object.entries(constants).map(([name, decl]) => (
          <li key={name} className="flex items-center gap-1 text-sm">
            <span className="min-w-0 shrink-0 truncate font-mono text-caption" title={name}>{name}</span>
            <div className="min-w-0 flex-1">
              <ExpressionEditor
                value={valueText(decl.value)}
                expected="any"
                placeholder="value or expression"
                onCommit={(t) => setConstantValue(name, coerceConstantValue(t))}
              />
            </div>
            <input
              value={decl.as ?? ''}
              placeholder="unit"
              onChange={(e) => setConstantUnit(name, e.target.value || null)}
              className={controlClass({ width: 'w-14' })}
            />
            <TypeBadge name={name} />
            <IconButton icon={X} label="Delete constant" destructive
              onClick={() => setError(removeConstant(name))} />
          </li>
        ))}
      </ul>
      <div className="flex items-center gap-1">
        <input value={newName} placeholder="name" onChange={(e) => setNewName(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && add()}
          className={controlClass({ mono: true, width: 'w-24' })} />
        <input value={newValue} placeholder="value" onChange={(e) => setNewValue(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && add()}
          className={controlClass({ width: 'w-20' })} />
        <button onClick={add} className={inlineButtonClass()}>Add</button>
      </div>
      {error && <p className="text-xs text-red-600">{error}</p>}
    </div>
  )
}
```

Confirm `ExpressionEditor`'s prop names (`value`/`onCommit`/`expected`/`placeholder`) match its signature (ExpressionEditor.tsx:36-41); adjust if the export differs. Confirm `controlClass` accepts `{ mono, width }` (it does per StreamsPanel usage).

- [ ] **Step 2: Wire into the palette**

In `Palette.tsx`, add the import (near line 9):

```tsx
import { ConstantsPanel } from './ConstantsPanel'
```

Insert after the Groups `<Section>` (after line 138):

```tsx
      <Section title="Constants" defaultOpen={false}>
        <ConstantsPanel />
      </Section>
```

- [ ] **Step 3: Typecheck + build**

Run: `cd webapp/frontend && npx tsc -b && npm run build`
Expected: PASS

- [ ] **Step 4: Visual/probe check**

Run the app against a doc with a couple of constants and confirm the section renders, edits persist, delete-while-referenced is refused. Use the probe capture harness (`npm run capture`) per webapp/frontend/CLAUDE.md to verify control heights and contrast on the new row.

- [ ] **Step 5: Commit**

```bash
git add webapp/frontend/src/builder/ConstantsPanel.tsx webapp/frontend/src/builder/Palette.tsx
git commit -m "feat(studio): editable Constants palette section after Groups"
```

---

### Task 13: Docs + demonstrative fixture

**Files:**
- Modify: `docs/workflow-schema.md` (add a "Constants" subsection)
- Create: `webapp/fixtures/valid-constants.json` (a small doc: a literal, a unit'd literal, a derived constant, used in a guard + a compute)
- Test: a backend test that loads the fixture through `/validate` and asserts `ok: true` with expected `binding_types`

**Interfaces:**
- Consumes: everything above.
- Produces: authored documentation + a green end-to-end fixture.

- [ ] **Step 1: Write the fixture**

```json
{
  "doc_version": 1,
  "name": "Constants demo",
  "description": "Reusable typed constants used across a guard and a compute.",
  "workflow": {
    "schema_version": 3,
    "persistence": { "default": "in_memory", "format": "jsonl" },
    "constants": {
      "MAX_TEMP": { "value": 37.0, "as": "celsius" },
      "DOSES": { "value": 3 },
      "TOTAL_ML": { "value": "DOSES * 2.5" }
    },
    "blocks": [
      { "compute": { "into": "planned_ml", "value": "TOTAL_ML" } },
      { "alarm": { "if": "planned_ml > 10", "message": "dose too large" } }
    ]
  }
}
```

- [ ] **Step 2: Write the failing test**

```python
# webapp/backend/tests/test_validate_api.py  (append)
import json, pathlib
def test_valid_constants_fixture(client):
    doc = json.loads((pathlib.Path(__file__).parents[2] / "fixtures" / "valid-constants.json").read_text())
    body = client.post("/validate", json=doc).json()
    assert body["ok"] is True
    assert body["binding_types"]["TOTAL_ML"]["base"] == "number"
    assert body["binding_types"]["MAX_TEMP"] == {"base": "number", "unit": "celsius"}
```

Adjust the relative path to the repo's `webapp/fixtures` from the backend test dir.

- [ ] **Step 3: Run to verify it passes**

Run: `cd webapp/backend && poetry run pytest tests/test_validate_api.py::test_valid_constants_fixture -v`
Expected: PASS

- [ ] **Step 4: Document**

Add a "Constants" subsection to `docs/workflow-schema.md` (no schema-version change): the `constants` map shape (`{ value, as? }`), the declaration-order/earlier-only rule, immutability, and that constants are usable in every expression slot plus value-kind params and group args (not string params). Keep the existing §7 "Schema version 3" history intact.

- [ ] **Step 5: Commit**

```bash
git add docs/workflow-schema.md webapp/fixtures/valid-constants.json webapp/backend/tests/test_validate_api.py
git commit -m "docs(studio): document constants + end-to-end fixture"
```

---

## Final verification

- [ ] Engine: `poetry run pytest tests/ -q` — all green.
- [ ] Backend: `cd webapp/backend && poetry run pytest -q` — all green (the 7 exact-equality `/validate` tests included).
- [ ] Frontend: `cd webapp/frontend && npx tsc -b && npx vitest run && npm run build` — all green.
- [ ] Frontend probe: `npm run capture` against a doc with constants — control heights (R4) and contrast (R5) pass on the new row.
- [ ] Manual: declare `FEED_RATE = 2.5 <mL/min>`, reference it in a device numeric param and in a loop `until` guard; confirm autocomplete offers it and validation is clean.

## Self-Review notes (author)

- **Spec coverage:** every settled decision maps to a task — model (T1), schema round-trip (T2), typing (T3), validation rules incl. immutability (T4), runtime seed (T5), backend surface (T6), FE types/convert/store/scope/panel (T7-T12), docs+fixture (T13). "Also parameter fields" is covered by T11 (scope union) + the T11 Step-4 verification, per the research finding that value-kind params already accept expression strings.
- **Type consistency:** `ConstantDecl.value: ValueExpr` / `.as_` (Python) ↔ `ConstantDeclJson.value: ParamValue` / `.as` (TS); actions named `addConstant/setConstantValue/setConstantUnit/removeConstant` consistently across T10 and T12; `countBindingRefs` defined in T9 and consumed in T10.
- **Known verification points (not placeholders):** the exact helper name `_checked_expr` (T2 Step 3), whether `expand_dict_traced` already preserves the key (T6 Step 2 branches on it), and whether `ParamInput`/`ArgField` build their own scope (T11 Step 4) are each written as an explicit check with a defined action for either outcome.
