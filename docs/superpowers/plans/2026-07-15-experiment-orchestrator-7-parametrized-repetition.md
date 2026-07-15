# Parametrized Repetition (`for_each` + parametrized groups) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close limitations doc #4 — let a workflow write a repeated subtree once and expand it per vial — by adding a `for_each` splicing macro and parametrized groups, unified under one substitution engine.

**Architecture:** Both surfaces are first-class in the authored AST (they round-trip unchanged, so the source stays DRY), but `validate()` and `ExperimentRun` operate on an **internally expanded copy** produced by a new `expand.py`. Once `for_each tube in [1,2,3]` becomes concrete `od_1/od_2/od_3`, every existing path-sensitive analysis (affinity, accumulator seeding, freshness guards, modes) runs on real names with no new analysis logic. Studio lands at the Increment-6 boundary: runnable + viewable, not canvas-editable.

**Tech Stack:** Python 3.14, `lab_devices.experiment` (dataclass AST, pure-JSON serialize, static validator, async executor), pytest, mypy, ruff. Studio backend (FastAPI, `experiment_studio`), Studio frontend (React/TS, Vitest).

**Design spec:** `docs/superpowers/specs/2026-07-15-experiment-orchestrator-7-parametrized-repetition-design.md`

## Global Constraints

- Python 3.14; run tools via `.venv/bin/python` (bare `python` lacks deps).
- **Gate, every task:** `.venv/bin/python -m pytest`, `.venv/bin/python -m mypy src/lab_devices` (scope `src/lab_devices` ONLY — never pass `tests`), `.venv/bin/python -m ruff check .`, and `awk 'length>100 {print FILENAME":"NR}' src/lab_devices/experiment/*.py tests/test_experiment_*.py` (must print nothing).
- Source modules: `from __future__ import annotations` + a one-line docstring citing the design §. Tests are flat `tests/test_experiment_*.py`, **no** `from __future__ import`.
- Studio backend gate: `cd webapp/backend && .venv/bin/python -m pytest && .venv/bin/python -m mypy experiment_studio && .venv/bin/python -m ruff check .`. Studio frontend gate: `cd webapp/frontend && npm run test && npm run build`.
- Interpolation delimiter is `{name}`; the expression grammar never uses `{`/`}` (verified in `expr.py`), so it is unambiguous.
- Commit after each task. Branch is `feat/experiment-orchestrator-7-parametrized-repetition` (already created; the design spec is committed on it).

---

## File Structure

**Engine (new):**
- `src/lab_devices/experiment/expand.py` — substitution + `expand_dict` + `expand_workflow`.

**Engine (modified):**
- `src/lab_devices/experiment/blocks.py` — `ForEach` block, `GroupRef.args`.
- `src/lab_devices/experiment/workflow.py` — `Group.params`.
- `src/lab_devices/experiment/serialize.py` — `_for_each` builder, `ForEach`/`args`/`params` dump-load, `_BUILDERS`, templated-device load tolerance.
- `src/lab_devices/experiment/validate.py` — macro detection, pre-expansion gates, expand-then-check.
- `src/lab_devices/experiment/run.py` — expand before `assign_block_ids`/execute.
- `src/lab_devices/experiment/__init__.py` — export `ForEach`.

**Example (modified):**
- `examples/morbidostat.json`, `examples/morbidostat-demo-speed.json`, `examples/README.md`.
- `tests/test_examples_morbidostat.py` — expand before role substitution.

**Studio backend (modified):**
- `webapp/backend/experiment_studio/roles.py` — `for_each` in `_CHILD_LISTS`; expand-before-substitute helper.
- `webapp/backend/experiment_studio/api/*` — call the expand helper in validate/run.

**Studio frontend (modified):**
- `webapp/frontend/src/builder/convert.ts` — `for_each` explicit known-unsupported message.

**Docs (modified):**
- `docs/experiment-engine-limitations.md`, `docs/superpowers/specs/2026-07-07-experiment-orchestrator-design.md`.

---

## Task 1: AST + serialization for `for_each`, group `params`, `group_ref` args

**Files:**
- Modify: `src/lab_devices/experiment/blocks.py`
- Modify: `src/lab_devices/experiment/workflow.py`
- Modify: `src/lab_devices/experiment/serialize.py`
- Modify: `src/lab_devices/experiment/__init__.py`
- Test: `tests/test_experiment_foreach_serialize.py` (new)

**Interfaces:**
- Produces: `B.ForEach(var: str | None, items: list, body: list[Block], **BlockBase)`;
  `B.GroupRef(name, args: dict[str, ValueExpr])`; `Group(name, body, params: list[str])`.
- Produces: `serialize` round-trips `for_each` (`{var?, in, body}`), `group_ref` `args`, group `params`.

- [ ] **Step 1: Write the failing round-trip tests**

Create `tests/test_experiment_foreach_serialize.py`:

```python
from lab_devices.experiment import blocks as B
from lab_devices.experiment.serialize import (
    block_from_dict, block_to_dict, workflow_from_dict, workflow_to_dict,
)


def _roundtrip_block(d):
    assert block_to_dict(block_from_dict(d)) == d


def test_for_each_scalar_shorthand_roundtrips():
    d = {"for_each": {"var": "tube", "in": [1, 2, 3],
                      "body": [{"measure": {"device": "densitometer_{tube}",
                                            "verb": "measure", "into": "od_{tube}"}}]}}
    _roundtrip_block(d)
    block = block_from_dict(d)
    assert isinstance(block, B.ForEach)
    assert block.var == "tube" and block.items == [1, 2, 3]


def test_for_each_object_items_roundtrip():
    d = {"for_each": {"in": [{"tube": 1, "port": 5}, {"tube": 2, "port": 6}],
                      "body": [{"wait": {"duration": "1s"}}]}}
    _roundtrip_block(d)


def test_for_each_label_roundtrips_var_omitted_for_object_items():
    d = {"for_each": {"in": [{"t": 1}], "body": [{"wait": {"duration": "1s"}}]},
         "label": "per tube"}
    _roundtrip_block(d)


def test_group_ref_args_roundtrips():
    d = {"group_ref": {"name": "service", "args": {"tube": "{t}"}}}
    _roundtrip_block(d)
    assert block_from_dict(d).args == {"tube": "{t}"}


def test_plain_group_ref_has_empty_args():
    d = {"group_ref": {"name": "setup"}}
    _roundtrip_block(d)
    assert block_from_dict(d).args == {}


def test_group_params_roundtrip_in_workflow():
    doc = {"schema_version": 1,
           "groups": {"service": {"params": ["tube"],
                                  "body": [{"wait": {"duration": "1s"}}]}},
           "blocks": [{"group_ref": {"name": "service", "args": {"tube": 1}}}]}
    assert workflow_to_dict(workflow_from_dict(doc)) == {
        "schema_version": 1,
        "persistence": {"default": "in_memory", "format": "jsonl"},
        "groups": {"service": {"params": ["tube"],
                               "body": [{"wait": {"duration": "1s"}}]}},
        "blocks": [{"group_ref": {"name": "service", "args": {"tube": 1}}}],
    }
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_experiment_foreach_serialize.py -q`
Expected: FAIL (`ForEach` undefined / `args` unknown / round-trip mismatch).

- [ ] **Step 3: Add the AST nodes**

In `src/lab_devices/experiment/blocks.py`, add `args` to `GroupRef` and a `ForEach` block, and add `ForEach` to the `Block` union:

```python
@dataclass(kw_only=True)
class GroupRef(BlockBase):
    name: str
    args: dict[str, ValueExpr] = field(default_factory=dict)


@dataclass(kw_only=True)
class ForEach(BlockBase):
    body: list[Block] = field(default_factory=list)
    var: str | None = None
    items: list[ValueExpr | dict[str, ValueExpr]] = field(default_factory=list)
```

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
    | ForEach
)
```

In `src/lab_devices/experiment/workflow.py`, add `params` to `Group`:

```python
@dataclass
class Group:
    name: str
    body: list[Block] = field(default_factory=list)
    params: list[str] = field(default_factory=list)
```

In `src/lab_devices/experiment/__init__.py`, add `ForEach` to the imports from `blocks` and to `__all__` (alongside `GroupRef`).

- [ ] **Step 4: Add serialization (load + dump)**

In `src/lab_devices/experiment/serialize.py`:

Add the `for_each` builder (place near `_group_ref`):

```python
def _for_each(body: Any, timing: dict[str, Any]) -> B.Block:
    if not isinstance(body, dict):
        raise WorkflowLoadError("for_each requires an object body")
    items = _req(body, "in", "for_each")
    if not isinstance(items, list):
        raise WorkflowLoadError("for_each 'in' must be a list")
    children = _children(_req(body, "body", "for_each"), "for_each.body")
    var = body.get("var")
    if var is not None and not isinstance(var, str):
        raise WorkflowLoadError(f"for_each 'var' must be a string, got {var!r}")
    return B.ForEach(var=var, items=items, body=children, **timing)
```

Extend `_group_ref` to carry `args`:

```python
def _group_ref(body: Any, timing: dict[str, Any]) -> B.Block:
    args = body.get("args", {})
    if not isinstance(args, dict):
        raise WorkflowLoadError("group_ref args must be an object")
    return B.GroupRef(name=_req(body, "name", "group_ref"), args=dict(args), **timing)
```

Register in `_BUILDERS`:

```python
    "group_ref": _group_ref,
    "for_each": _for_each,
    "compute": _compute,
    "record": _record,
```

Add dump cases in `_dump_body` (replace the `GroupRef` case, add a `ForEach` case):

```python
    if isinstance(b, B.GroupRef):
        body = {"name": b.name}
        if b.args:
            body["args"] = dict(b.args)
        return "group_ref", body
    if isinstance(b, B.ForEach):
        body = {}
        if b.var is not None:
            body["var"] = b.var
        body["in"] = list(b.items)
        body["body"] = [block_to_dict(c) for c in b.body]
        return "for_each", body
```

Carry group `params` through `workflow_from_dict` (the groups loop) and `workflow_to_dict`:

In `workflow_from_dict`, replace the groups loop:

```python
    groups: dict[str, Group] = {}
    for name, gv in _obj(d.get("groups", {}), "groups").items():
        g = _obj(gv, f"group {name!r}")
        params = g.get("params", [])
        if not isinstance(params, list) or not all(isinstance(p, str) for p in params):
            raise WorkflowLoadError(f"group {name!r} params must be a list of strings")
        groups[name] = Group(
            name=name, body=_children(g.get("body", []), f"groups.{name}.body"),
            params=list(params),
        )
```

In `workflow_to_dict`, replace the groups dump:

```python
    if w.groups:
        out["groups"] = {
            name: ({"params": list(g.params)} if g.params else {})
                  | {"body": [block_to_dict(c) for c in g.body]}
            for name, g in w.groups.items()
        }
```

- [ ] **Step 5: Add templated-device load tolerance**

In `serialize.py`, guard the eager `lookup` in `_command` and `_measure` so a templated device (containing `{`) is not type-checked at load (it is verified post-expansion). Replace the `lookup(...)` calls:

```python
def _command(body: Any, timing: dict[str, Any]) -> B.Block:
    device = _str(_req(body, "device", "command"), "command device")
    verb = _req(body, "verb", "command")
    if "{" not in device:
        lookup(device, verb)
    return B.Command(device=device, verb=verb, params=_checked_params(body, "command"), **timing)
```

```python
def _measure(body: Any, timing: dict[str, Any]) -> B.Block:
    device = _str(_req(body, "device", "measure"), "measure device")
    verb = body.get("verb", "measure")
    if "{" not in device:
        lookup(device, verb)
    return B.Measure(
        device=device, verb=verb, into=_req(body, "into", "measure"),
        params=_checked_params(body, "measure"), **timing,
    )
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_experiment_foreach_serialize.py -q`
Expected: PASS. Then run the full gate (pytest, mypy `src/lab_devices`, ruff, awk).

- [ ] **Step 7: Commit**

```bash
git add src/lab_devices/experiment/blocks.py src/lab_devices/experiment/workflow.py \
        src/lab_devices/experiment/serialize.py src/lab_devices/experiment/__init__.py \
        tests/test_experiment_foreach_serialize.py
git commit -m "feat(experiment): AST + serialization for for_each, group params, group_ref args"
```

---

## Task 2: The expansion engine (`expand.py`)

**Files:**
- Create: `src/lab_devices/experiment/expand.py`
- Test: `tests/test_experiment_expand.py` (new)

**Interfaces:**
- Consumes: `serialize._BLOCK_KEYS`, `serialize.workflow_from_dict`, `serialize.workflow_to_dict`.
- Produces: `expand_dict(workflow_dict: dict) -> dict` (pure JSON; no `lookup`), and
  `expand_workflow(w: Workflow) -> Workflow`. Both raise `WorkflowLoadError` on malformed macros,
  recursion depth, or the expansion cap.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_experiment_expand.py`:

```python
import pytest

from lab_devices.experiment.errors import WorkflowLoadError
from lab_devices.experiment.expand import expand_dict


def _wf(blocks, groups=None):
    d = {"schema_version": 1, "blocks": blocks}
    if groups is not None:
        d["groups"] = groups
    return d


def test_for_each_scalar_splices_into_serial():
    out = expand_dict(_wf([
        {"serial": {"children": [
            {"for_each": {"var": "t", "in": [1, 2, 3],
                          "body": [{"wait": {"duration": "{t}s"}}]}}
        ]}}
    ]))
    kids = out["blocks"][0]["serial"]["children"]
    assert [k["wait"]["duration"] for k in kids] == ["1s", "2s", "3s"]


def test_for_each_in_parallel_yields_lanes():
    out = expand_dict(_wf([
        {"parallel": {"children": [
            {"for_each": {"var": "t", "in": [1, 2],
                          "body": [{"measure": {"device": "densitometer_{t}",
                                                "verb": "measure", "into": "od_{t}"}}]}}
        ]}}
    ]))
    lanes = out["blocks"][0]["parallel"]["children"]
    assert [l["measure"]["device"] for l in lanes] == ["densitometer_1", "densitometer_2"]
    assert [l["measure"]["into"] for l in lanes] == ["od_1", "od_2"]


def test_object_items_multi_field():
    out = expand_dict(_wf([
        {"for_each": {"in": [{"t": 1, "p": 7}, {"t": 2, "p": 8}],
                      "body": [{"command": {"device": "valve_{t}", "verb": "set_position",
                                            "params": {"position": "{p}"}}}]}}
    ]))
    cmds = out["blocks"]
    assert cmds[0]["command"]["device"] == "valve_1"
    assert cmds[0]["command"]["params"]["position"] == "7"
    assert cmds[1]["command"]["device"] == "valve_2"


def test_parametrized_group_ref_inlines_as_serial_carrying_on_error():
    out = expand_dict(_wf(
        [{"group_ref": {"name": "svc", "args": {"t": 2}}, "on_error": "continue"}],
        groups={"svc": {"params": ["t"],
                        "body": [{"measure": {"device": "densitometer_{t}",
                                              "verb": "measure", "into": "od_{t}"}}]}},
    ))
    wrap = out["blocks"][0]
    assert wrap["on_error"] == "continue"
    assert wrap["serial"]["children"][0]["measure"]["device"] == "densitometer_2"
    assert "groups" not in out  # parametrized group dropped after inlining


def test_plain_group_ref_left_as_node_and_group_kept():
    out = expand_dict(_wf(
        [{"group_ref": {"name": "setup"}}],
        groups={"setup": {"body": [{"wait": {"duration": "1s"}}]}},
    ))
    assert out["blocks"][0] == {"group_ref": {"name": "setup"}}
    assert out["groups"] == {"setup": {"body": [{"wait": {"duration": "1s"}}]}}


def test_for_each_over_group_ref_composition():
    out = expand_dict(_wf(
        [{"for_each": {"var": "t", "in": [1, 2, 3],
                       "body": [{"group_ref": {"name": "svc", "args": {"t": "{t}"}}}]}}],
        groups={"svc": {"params": ["t"],
                        "body": [{"measure": {"device": "densitometer_{t}",
                                              "verb": "measure", "into": "od_{t}"}}]}},
    ))
    devs = [b["serial"]["children"][0]["measure"]["device"] for b in out["blocks"]]
    assert devs == ["densitometer_1", "densitometer_2", "densitometer_3"]


def test_unbound_hole_raises():
    with pytest.raises(WorkflowLoadError, match="hole"):
        expand_dict(_wf([{"for_each": {"var": "t", "in": [1],
                                       "body": [{"wait": {"duration": "{nope}s"}}]}}]))


def test_arity_mismatch_raises():
    with pytest.raises(WorkflowLoadError, match="must match params"):
        expand_dict(_wf([{"group_ref": {"name": "svc", "args": {"x": 1}}}],
                        groups={"svc": {"params": ["t"], "body": []}}))


def test_var_with_object_items_raises():
    with pytest.raises(WorkflowLoadError, match="scalar items"):
        expand_dict(_wf([{"for_each": {"var": "t", "in": [{"t": 1}],
                                       "body": [{"wait": {"duration": "1s"}}]}}]))


def test_forbidden_block_key_on_for_each_raises():
    with pytest.raises(WorkflowLoadError, match="block-level"):
        expand_dict(_wf([{"for_each": {"var": "t", "in": [1],
                                       "body": [{"wait": {"duration": "1s"}}]},
                          "on_error": "continue"}]))


def test_expansion_cap_trips():
    with pytest.raises(WorkflowLoadError, match="exceeds"):
        expand_dict(_wf([{"for_each": {
            "var": "a", "in": list(range(200)),
            "body": [{"for_each": {"var": "b", "in": list(range(200)),
                                   "body": [{"wait": {"duration": "1s"}}]}}]}}]))
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_experiment_expand.py -q`
Expected: FAIL (`No module named 'lab_devices.experiment.expand'`).

- [ ] **Step 3: Write `expand.py`**

Create `src/lab_devices/experiment/expand.py`:

```python
"""for_each / parametrized-group expansion (design 2026-07-15 §4)."""

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
from lab_devices.experiment.workflow import Workflow

_HOLE_RE = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")
_EXPANSION_CAP = 10_000
_MAX_DEPTH = 64
_CHILD_LISTS: dict[str, tuple[str, ...]] = {
    "serial": ("children",),
    "parallel": ("children",),
    "loop": ("body",),
    "branch": ("then", "else"),
}
_FOR_EACH_FORBIDDEN = ("retry", "on_error", "gap_after", "start_offset")


def _fmt(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return str(int(value)) if value.is_integer() else repr(value)
    return str(value)


def _interpolate(text: str, env: dict[str, Any]) -> str:
    def sub(m: re.Match[str]) -> str:
        name = m.group(1)
        if name not in env:
            raise WorkflowLoadError(f"for_each/args hole '{{{name}}}' has no binding")
        return _fmt(env[name])

    return _HOLE_RE.sub(sub, text)


def _substitute(node: Any, env: dict[str, Any]) -> Any:
    """Deep-copy a JSON node, interpolating every string against env."""
    if isinstance(node, str):
        return _interpolate(node, env)
    if isinstance(node, list):
        return [_substitute(x, env) for x in node]
    if isinstance(node, dict):
        return {k: _substitute(v, env) for k, v in node.items()}
    return node


class _Counter:
    def __init__(self) -> None:
        self.n = 0

    def bump(self, k: int) -> None:
        self.n += k
        if self.n > _EXPANSION_CAP:
            raise WorkflowLoadError(
                f"for_each/group expansion exceeds {_EXPANSION_CAP} blocks"
            )


def _type_key(block: Any) -> str | None:
    if not isinstance(block, dict):
        return None
    keys = [k for k in block if k not in _BLOCK_KEYS]
    return keys[0] if len(keys) == 1 else None


def _envs(body: dict[str, Any]) -> list[dict[str, Any]]:
    var = body.get("var")
    raw = body.get("in")
    if not isinstance(raw, list) or not raw:
        raise WorkflowLoadError("for_each 'in' must be a non-empty list")
    out: list[dict[str, Any]] = []
    if var is not None:
        if not isinstance(var, str):
            raise WorkflowLoadError("for_each 'var' must be a string")
        for item in raw:
            if isinstance(item, dict):
                raise WorkflowLoadError("for_each with 'var' requires scalar items")
            out.append({var: item})
        return out
    keyset: set[str] | None = None
    for item in raw:
        if not isinstance(item, dict):
            raise WorkflowLoadError("for_each without 'var' requires object items")
        if keyset is None:
            keyset = set(item)
        elif set(item) != keyset:
            raise WorkflowLoadError("for_each object items must share one key set")
        out.append(dict(item))
    return out


def _expand_blocks(
    blocks: list[Any], groups: dict[str, Any], counter: _Counter, depth: int
) -> list[Any]:
    out: list[Any] = []
    for block in blocks:
        out.extend(_expand_block(block, groups, counter, depth))
    return out


def _expand_block(
    block: Any, groups: dict[str, Any], counter: _Counter, depth: int
) -> list[Any]:
    if depth > _MAX_DEPTH:
        raise WorkflowLoadError("for_each/group expansion nested too deeply (recursion?)")
    key = _type_key(block)
    if key is None:
        return [block]  # malformed; workflow_from_dict reports it
    if key == "for_each":
        return _expand_for_each(block, groups, counter, depth)
    if key == "group_ref":
        return _expand_group_ref(block, groups, counter, depth)
    body = block[key]
    if isinstance(body, dict):
        for child_key in _CHILD_LISTS.get(key, ()):
            children = body.get(child_key)
            if isinstance(children, list):
                body[child_key] = _expand_blocks(children, groups, counter, depth)
    return [block]


def _expand_for_each(
    block: dict[str, Any], groups: dict[str, Any], counter: _Counter, depth: int
) -> list[Any]:
    for k in _FOR_EACH_FORBIDDEN:
        if k in block:
            raise WorkflowLoadError(
                f"for_each may not carry block-level {k!r}; put it on the body blocks"
            )
    body = block["for_each"]
    if not isinstance(body, dict):
        raise WorkflowLoadError("for_each requires an object body")
    tmpl = body.get("body")
    if not isinstance(tmpl, list) or not tmpl:
        raise WorkflowLoadError("for_each 'body' must be a non-empty list")
    out: list[Any] = []
    for env in _envs(body):
        substituted = [_substitute(b, env) for b in tmpl]
        out.extend(_expand_blocks(substituted, groups, counter, depth + 1))
    counter.bump(len(out))
    return out


def _expand_group_ref(
    block: dict[str, Any], groups: dict[str, Any], counter: _Counter, depth: int
) -> list[Any]:
    body = block["group_ref"]
    if not isinstance(body, dict):
        return [block]
    name = body.get("name")
    args = body.get("args") if isinstance(body.get("args"), dict) else {}
    group = groups.get(name) if isinstance(name, str) else None
    params = list(group.get("params", [])) if isinstance(group, dict) else []
    if not params and not args:
        return [block]  # plain group_ref: preserve the node (lazy inline)
    if group is None:
        raise WorkflowLoadError(f"group_ref {name!r}: unknown group")
    if set(args) != set(params):
        raise WorkflowLoadError(
            f"group_ref {name!r}: args {sorted(args)} must match params {sorted(params)}"
        )
    raw_body = group.get("body", [])
    if not isinstance(raw_body, list):
        raise WorkflowLoadError(f"group {name!r} body must be a list")
    substituted = [_substitute(b, dict(args)) for b in raw_body]
    inlined = _expand_blocks(substituted, groups, counter, depth + 1)
    wrapper: dict[str, Any] = {"serial": {"children": inlined}}
    for k in _BLOCK_KEYS:
        if k in block:
            wrapper[k] = copy.deepcopy(block[k])
    counter.bump(1)
    return [wrapper]


def expand_dict(workflow_dict: dict[str, Any]) -> dict[str, Any]:
    """Splice for_each, inline parametrized group_refs, interpolate holes. Pure JSON."""
    out = copy.deepcopy(workflow_dict)
    groups = out.get("groups")
    groups = groups if isinstance(groups, dict) else {}
    counter = _Counter()
    for g in groups.values():  # expand for_each inside plain-group bodies (used lazily)
        if isinstance(g, dict) and not g.get("params") and isinstance(g.get("body"), list):
            g["body"] = _expand_blocks(g["body"], groups, counter, 0)
    blocks = out.get("blocks")
    if isinstance(blocks, list):
        out["blocks"] = _expand_blocks(blocks, groups, counter, 0)
    kept = {n: g for n, g in groups.items()
            if not (isinstance(g, dict) and g.get("params"))}
    if kept:
        out["groups"] = kept
    else:
        out.pop("groups", None)
    return out


def expand_workflow(w: Workflow) -> Workflow:
    """AST-level expansion, for validate() and ExperimentRun (concrete-typed ASTs only)."""
    return workflow_from_dict(expand_dict(workflow_to_dict(w)))
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_experiment_expand.py -q`
Expected: PASS. Then the full gate.

- [ ] **Step 5: Commit**

```bash
git add src/lab_devices/experiment/expand.py tests/test_experiment_expand.py
git commit -m "feat(experiment): for_each / parametrized-group expansion engine"
```

---

## Task 3: Validator — macro detection, pre-expansion gates, expand-then-check

**Files:**
- Modify: `src/lab_devices/experiment/validate.py`
- Test: `tests/test_experiment_foreach_validate.py` (new)

**Interfaces:**
- Consumes: `expand.expand_workflow`, `B.ForEach`, `B.GroupRef.args`, `Group.params`.
- Produces: `validate(w)` handles macro docs by expanding then running every existing concrete
  check on the expansion; legacy docs (no macros) validate exactly as before.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_experiment_foreach_validate.py`:

```python
import pytest

from lab_devices.experiment.errors import ValidationError
from lab_devices.experiment.serialize import workflow_from_dict
from lab_devices.experiment.validate import validate


def _validate(doc):
    validate(workflow_from_dict(doc))


def _messages(exc):
    return [d.message for d in exc.value.diagnostics]


_GROUP_OD = {"svc": {"params": ["t"], "body": [
    {"measure": {"device": "densitometer_{t}", "verb": "measure", "into": "od_{t}"}}]}}


def test_for_each_of_reads_over_distinct_devices_is_clean():
    _validate({
        "schema_version": 1,
        "streams": {"od_1": {}, "od_2": {}, "od_3": {}},
        "blocks": [{"parallel": {"children": [
            {"for_each": {"var": "t", "in": [1, 2, 3],
                          "body": [{"measure": {"device": "densitometer_{t}",
                                                "verb": "measure", "into": "od_{t}"}}]}}]}}],
    })


def test_for_each_of_reads_over_one_shared_device_is_affinity_error():
    with pytest.raises(ValidationError) as exc:
        _validate({
            "schema_version": 1,
            "streams": {"od_1": {}},
            "blocks": [{"parallel": {"children": [
                {"for_each": {"var": "t", "in": [1, 2],
                              "body": [{"measure": {"device": "densitometer_1",
                                                    "verb": "measure", "into": "od_1"}}]}}]}}],
        })
    assert any("both command device" in m for m in _messages(exc))


def test_for_each_seeded_accumulator_is_clean():
    _validate({
        "schema_version": 1,
        "streams": {},
        "blocks": [
            {"for_each": {"var": "t", "in": [1, 2],
                          "body": [{"compute": {"into": "c_{t}", "value": "0"}}]}},
            {"loop": {"count": 2, "body": [
                {"for_each": {"var": "t", "in": [1, 2],
                              "body": [{"compute": {"into": "c_{t}",
                                                    "value": "c_{t} * 0.9"}}]}}]}},
        ],
    })


def test_for_each_unseeded_accumulator_is_read_before_write():
    with pytest.raises(ValidationError) as exc:
        _validate({
            "schema_version": 1,
            "blocks": [{"loop": {"count": 2, "body": [
                {"for_each": {"var": "t", "in": [1, 2],
                              "body": [{"compute": {"into": "c_{t}",
                                                    "value": "c_{t} * 0.9"}}]}}]}}],
        })
    assert any("read before it is written" in m for m in _messages(exc))


def test_group_arity_mismatch_is_diagnosed():
    with pytest.raises(ValidationError) as exc:
        _validate({"schema_version": 1, "streams": {"od_1": {}}, "groups": _GROUP_OD,
                   "blocks": [{"group_ref": {"name": "svc", "args": {"x": 1}}}]})
    assert any("must match params" in m for m in _messages(exc))


def test_for_each_forbidden_block_key_is_diagnosed():
    with pytest.raises(ValidationError) as exc:
        _validate({"schema_version": 1,
                   "blocks": [{"for_each": {"var": "t", "in": [1],
                                            "body": [{"wait": {"duration": "1s"}}]},
                               "on_error": "continue"}]})
    assert any("block-level" in m for m in _messages(exc))


def test_parametrized_group_expands_and_validates_streams():
    with pytest.raises(ValidationError) as exc:
        _validate({"schema_version": 1, "groups": _GROUP_OD,  # od_{t} not declared
                   "blocks": [{"for_each": {"var": "t", "in": [1, 2],
                               "body": [{"group_ref": {"name": "svc",
                                                       "args": {"t": "{t}"}}}]}}]})
    assert any("undeclared stream" in m for m in _messages(exc))


def test_recursive_parametrized_group_is_caught():
    with pytest.raises(ValidationError) as exc:
        _validate({"schema_version": 1,
                   "groups": {"a": {"params": ["t"],
                                    "body": [{"group_ref": {"name": "a", "args": {"t": "{t}"}}}]}},
                   "blocks": [{"group_ref": {"name": "a", "args": {"t": 1}}}]})
    assert any("recursive group" in m for m in _messages(exc))
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_experiment_foreach_validate.py -q`
Expected: FAIL (macro docs not yet handled; several will error at load or mis-validate).

- [ ] **Step 3: Refactor `validate()` and add the gates**

In `src/lab_devices/experiment/validate.py`:

Add the import:

```python
from lab_devices.experiment.expand import expand_workflow
```

Add a `ForEach` recursion arm to `_iter_blocks` (so gate iteration reaches for_each bodies):

```python
        elif isinstance(b, B.Branch):
            yield from _iter_blocks(b.then, f"{path}.then")
            if b.else_ is not None:
                yield from _iter_blocks(b.else_, f"{path}.else")
        elif isinstance(b, B.ForEach):
            yield from _iter_blocks(b.body, f"{path}.body")
```

Add macro detection and the new gates (place near `_check_groups`):

```python
def _uses_macros(w: Workflow) -> bool:
    if any(g.params for g in w.groups.values()):
        return True
    for _, b in _iter_all_blocks(w):
        if isinstance(b, B.ForEach):
            return True
        if isinstance(b, B.GroupRef) and b.args:
            return True
    return False


def _check_for_each_and_arity(w: Workflow, out: list[Diagnostic]) -> bool:
    ok = True
    for path, b in _iter_all_blocks(w):
        if isinstance(b, B.ForEach):
            for key, present in (("retry", b.retry is not None), ("on_error", b.on_error != "fail"),
                                 ("gap_after", b.gap_after is not None),
                                 ("start_offset", b.start_offset is not None)):
                if present:
                    out.append(Diagnostic(
                        "for_each", path,
                        f"for_each may not carry block-level {key!r}; put it on the body blocks",
                    ))
                    ok = False
            if not b.body:
                out.append(Diagnostic("for_each", path, "for_each 'body' must be non-empty"))
                ok = False
            if not b.items:
                out.append(Diagnostic("for_each", path, "for_each 'in' must be non-empty"))
                ok = False
            scalar = [i for i in b.items if not isinstance(i, dict)]
            objects = [i for i in b.items if isinstance(i, dict)]
            if b.var is not None and objects:
                out.append(Diagnostic("for_each", path, "for_each with 'var' requires scalar items"))
                ok = False
            if b.var is None and scalar:
                out.append(Diagnostic(
                    "for_each", path, "for_each without 'var' requires object items"))
                ok = False
        elif isinstance(b, B.GroupRef):
            group = w.groups.get(b.name)
            params = set(group.params) if group is not None else set()
            if group is not None and set(b.args) != params:
                out.append(Diagnostic(
                    "group", path,
                    f"group_ref {b.name!r}: args {sorted(b.args)} must match params "
                    f"{sorted(params)}",
                ))
                ok = False
    return ok
```

Refactor `validate()` to branch on macros:

```python
def validate(workflow: Workflow) -> None:
    """Statically validate a loaded workflow (design §11 phase 2, rules §12).

    Macro docs (for_each / parametrized groups) are expanded first and every concrete
    check runs on the expansion; legacy docs validate in place, unchanged.
    """
    out: list[Diagnostic] = []
    if not _uses_macros(workflow):
        _validate_workflow(workflow, out)
    else:
        _validate_macro_workflow(workflow, out)
    if out:
        raise ValidationError(out)


def _validate_workflow(workflow: Workflow, out: list[Diagnostic]) -> None:
    expandable = _check_groups(workflow, out)
    _check_defaults(workflow, out)
    _check_namespaces(workflow, out)
    binding_types = _collect_binding_types(workflow)
    for path, block in _iter_all_blocks(workflow):
        _check_block(block, path, workflow, binding_types, out)
    if expandable:
        _analyze_paths(workflow, out)


def _validate_macro_workflow(workflow: Workflow, out: list[Diagnostic]) -> None:
    expandable = _check_groups(workflow, out)
    expandable = _check_for_each_and_arity(workflow, out) and expandable
    _check_defaults(workflow, out)
    if not expandable:
        return
    try:
        expanded = expand_workflow(workflow)
    except WorkflowLoadError as exc:
        out.append(Diagnostic("expansion", "blocks", str(exc)))
        return
    _validate_workflow(expanded, out)
```

Note: `_validate_macro_workflow` calls `_validate_workflow` on the expansion, which itself may
re-run `_check_groups` (harmless — no macros remain, so `_uses_macros` was true only for the
authored doc; the expansion has no ForEach/args/params and passes those checks trivially). Add the
`WorkflowLoadError` import if not present:

```python
from lab_devices.experiment.errors import (
    Diagnostic,
    ExpressionError,
    UnknownVerbError,
    ValidationError,
    WorkflowLoadError,
)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_experiment_foreach_validate.py -q`
Expected: PASS. Then run the **whole** validator suite to confirm no legacy regression:
`.venv/bin/python -m pytest tests/test_experiment_validate_faults.py tests/test_experiment_on_error.py -q`
Then the full gate.

- [ ] **Step 5: Commit**

```bash
git add src/lab_devices/experiment/validate.py tests/test_experiment_foreach_validate.py
git commit -m "feat(experiment): validate for_each/parametrized groups via expand-then-check"
```

---

## Task 4: Execution — run the expanded workflow

**Files:**
- Modify: `src/lab_devices/experiment/run.py`
- Test: `tests/test_experiment_foreach_execute.py` (new)

**Interfaces:**
- Consumes: `expand.expand_workflow`.
- Produces: `ExperimentRun` validates the authored workflow, then executes its expansion;
  `assign_block_ids` numbers the expanded tree. Plain-group behavior/ids unchanged.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_experiment_foreach_execute.py`:

```python
import asyncio

from lab_devices.experiment import ExperimentRun, RunOptions
from lab_devices.experiment.serialize import workflow_from_dict
from tests.fakeclock import FakeClock, drive
from tests.fakelab import FakeLab


def _run(doc):
    workflow = workflow_from_dict(doc)
    lab = FakeLab()
    for i in (1, 2, 3):
        lab.add_device(f"densitometer_{i}", "densitometer")
    clock = FakeClock()
    run = ExperimentRun(lab.client(), workflow, RunOptions(clock=clock))
    report = drive(run.execute(), clock)
    return run, report


def test_for_each_drives_three_distinct_devices():
    run, report = _run({
        "schema_version": 1,
        "streams": {"od_1": {}, "od_2": {}, "od_3": {}},
        "blocks": [{"parallel": {"children": [
            {"for_each": {"var": "t", "in": [1, 2, 3],
                          "body": [{"measure": {"device": "densitometer_{t}",
                                                "verb": "measure", "into": "od_{t}"}}]}}]}}],
    })
    assert report.status == "completed"
    for i in (1, 2, 3):
        assert len(report.state.streams[f"od_{i}"].samples) == 1


def test_parametrized_group_per_tube_accumulator_does_not_cross_contaminate():
    run, report = _run({
        "schema_version": 1,
        "streams": {},
        "groups": {"seed": {"params": ["t"],
                            "body": [{"compute": {"into": "c_{t}", "value": "{t} * 10"}}]}},
        "blocks": [{"for_each": {"var": "t", "in": [1, 2, 3],
                    "body": [{"group_ref": {"name": "seed", "args": {"t": "{t}"}}}]}}],
    })
    assert report.status == "completed"
    assert report.state.bindings["c_1"] == 10
    assert report.state.bindings["c_2"] == 20
    assert report.state.bindings["c_3"] == 30


def test_expanded_block_ids_are_positional_and_stable():
    run, report = _run({
        "schema_version": 1, "streams": {"od_1": {}, "od_2": {}},
        "blocks": [{"serial": {"children": [
            {"for_each": {"var": "t", "in": [1, 2],
                          "body": [{"measure": {"device": "densitometer_{t}",
                                                "verb": "measure", "into": "od_{t}"}}]}}]}}],
    })
    ids = [b.id for b in run._workflow.blocks[0].children]  # type: ignore[attr-defined]
    assert ids == ["blocks[0].children[0]", "blocks[0].children[1]"]
```

(If `FakeLab.add_device` / `.client()` / `RunOptions(clock=...)` differ, mirror the exact
constructor usage in `tests/test_examples_morbidostat.py` and `tests/fakelab.py`.)

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_experiment_foreach_execute.py -q`
Expected: FAIL (executor meets a `ForEach` node / stream `od_1` not created because expansion
never ran).

- [ ] **Step 3: Expand before execution in `run.py`**

In `src/lab_devices/experiment/run.py`, add the import and expand in `__init__`:

```python
from lab_devices.experiment.expand import expand_workflow
```

Replace the head of `ExperimentRun.__init__` (the `validate` + `assign_block_ids` lines):

```python
        validate(workflow)  # the runtime's safety model IS the static proof (D6)
        workflow = expand_workflow(workflow)  # run the concrete tree (design 2026-07-15 §4.4)
        assign_block_ids(workflow)
        self._workflow = workflow
```

`workflow.streams` is unchanged by expansion, so the stream pre-creation loop below stays correct.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_experiment_foreach_execute.py -q`
Expected: PASS. Then run the executor + example suites to confirm no regression:
`.venv/bin/python -m pytest tests/test_experiment_retry.py tests/test_examples_morbidostat.py -q`
Then the full gate.

- [ ] **Step 5: Commit**

```bash
git add src/lab_devices/experiment/run.py tests/test_experiment_foreach_execute.py
git commit -m "feat(experiment): execute the expanded workflow (for_each / parametrized groups)"
```

---

## Task 5: Rewrite the morbidostat example with `service(tube)` + `for_each`

**Files:**
- Modify: `examples/morbidostat.json`, `examples/morbidostat-demo-speed.json`
- Modify: `tests/test_examples_morbidostat.py`
- Create: `tests/fixtures/morbidostat_expansion.json` (golden expected expansion — optional helper)
- Modify: `examples/README.md`

**Interfaces:**
- Consumes: `expand.expand_dict` (in the test, before role substitution).
- Produces: DRY example docs whose expansion reproduces the current three-tube behavior.

- [ ] **Step 1: Capture the current expansion as a golden baseline**

Before editing the JSON, snapshot the *current* three-tube workflow so the rewrite can be proven
behavior-preserving. Add a helper test that will guard the rewrite:

In `tests/test_examples_morbidostat.py`, add near the top-level helpers:

```python
from lab_devices.experiment.expand import expand_dict
```

Add a test that asserts the rewritten doc expands to the same *service logic* as before. The most
robust invariant that survives the `Serial`-wrapper difference (a parametrized `group_ref` inlines
as a `Serial`, §4.1) is: **the fully role-substituted, expanded workflow drives the control loop to
the same IC50 fixed point.** That is already asserted by the existing integration test — so the
rewrite's proof is that the existing integration test passes unchanged after Steps 3–4.

- [ ] **Step 2: Update the loader to expand before role substitution**

In `tests/test_examples_morbidostat.py`, change `_load` so expansion runs before `_substitute`:

```python
def _load(name: str) -> tuple[dict[str, Any], Any]:
    doc = json.loads((EXAMPLES / name).read_text())
    workflow = json.loads(json.dumps(doc["workflow"]))
    workflow = expand_dict(workflow)          # for_each / service(tube) -> concrete roles
    _substitute(workflow["blocks"])           # role name -> device id
    return doc, workflow_from_dict(workflow)
```

If `_substitute` walks only `blocks`/`children`/`body`/`then`/`else`, it now sees no `for_each`
(expansion removed them) and no `group_ref` into a parametrized group (inlined) — so it needs **no**
new recursion arm. Confirm by running the existing integration test after Step 4.

- [ ] **Step 3: Rewrite `examples/morbidostat.json`**

Transform the workflow (`doc["workflow"]`) as follows, leaving `roles`, `streams`, `defaults`,
`persistence`, `metadata`, and every constant/prose unchanged:

1. **Add a `service` group** (top-level `workflow.groups`) parametrized by `tube`, whose body is the
   current tube-1 service `branch` (lines ~379–498) with every `1` index replaced by `{tube}`:
   device `od_meter_{tube}`; streams `od_{tube}`, `r_series_{tube}`, `c_series_{tube}`; bindings
   `c_{tube}`, `r_{tube}`; the freshness guard `count(od_{tube}, last=11min) > 0 and last(od_{tube})
   >= od_min`; the growth-rate and concentration expressions with `{tube}`; and the three valve
   `set_position` params `"position": "{tube}"` (string form — evaluates to the integer). Example
   group shell:

```json
"groups": {
  "service": {
    "params": ["tube"],
    "body": [
      { "compute": {"into": "r_{tube}",
        "value": "24 * (mean(od_{tube}, last=5) - mean(od_{tube}, last=10)) / last(od_{tube})"},
        "label": "tube {tube}: specific growth rate (1/h)" },
      { "record": {"into": "r_series_{tube}", "value": "r_{tube}"},
        "label": "tube {tube}: chart the growth rate" },
      { "branch": {"if": "last(od_{tube}) > od_thr and r_{tube} > r_dil",
        "then": [ ...drug arm: set_position position "{tube}", dispense, compute c_{tube} ... ],
        "else": [ ...medium arm... ]},
        "label": "tube {tube}: growing above threshold -> drug, else medium" },
      { "command": {"device": "waste_valve", "verb": "set_position",
        "params": {"position": "{tube}", "rotation": "direct"}}, "label": "waste line -> tube {tube}" },
      { "command": {"device": "waste_pump", "verb": "dispense",
        "params": {"volume_ml": "dose_ml * 1.5", "speed_ml_min": 6.0, "direction": "forward"}},
        "label": "restore tube {tube} to V" },
      { "record": {"into": "c_series_{tube}", "value": "c_{tube}"},
        "label": "tube {tube}: chart the drug-concentration sawtooth" }
    ]
  }
}
```

   Wrap the whole `service` body under the freshness guard by making the group body a single
   top-level `branch` on `count(od_{tube}, last=11min) > 0 and last(od_{tube}) >= od_min` whose
   `then` is the list above (mirroring the current per-tube service `branch`).

2. **Replace the three `compute c_1/c_2/c_3 = 0` seeds** with one `for_each`:

```json
{ "for_each": {"var": "tube", "in": [1, 2, 3],
    "body": [{"compute": {"into": "c_{tube}", "value": "0"},
              "label": "tube {tube}: drug concentration starts at 0"}]} }
```

3. **Replace the OD-read `parallel`'s three lanes** with a single `for_each` child:

```json
{ "parallel": {"children": [
    { "for_each": {"var": "tube", "in": [1, 2, 3],
        "body": [{"measure": {"device": "od_meter_{tube}", "verb": "measure",
                              "into": "od_{tube}"},
                  "label": "tube {tube} OD (retried; a failed read costs one sample)",
                  "on_error": "continue"}]} }
  ]}, "label": "read all three tubes at once" }
```

4. **Replace the three tube-service `branch` blocks** in the loop body with one `for_each` calling
   the group:

```json
{ "for_each": {"var": "tube", "in": [1, 2, 3],
    "body": [{"group_ref": {"name": "service", "args": {"tube": "{tube}"}},
              "label": "tube {tube}: service"}]} }
```

Leave the thermostat `parallel`, the blank `serial`, the valve home/configure `serial`, the
`working_volume_ml` compute, and the end-of-cycle valve-park `parallel` **unchanged** (they are not
per-tube-parametrized in a way #4 targets; the thermostats reference `od_meter_1/2/3` and the parks
reference the shared valves — a follow-up could `for_each` the thermostats, but keep this rewrite
minimal and behavior-preserving).

- [ ] **Step 4: Rewrite `examples/morbidostat-demo-speed.json`** identically, keeping its own
  pace-coupled constants (slope constant, `last=45s` freshness window, pump speed, count/pace).

- [ ] **Step 5: Run the example integration test (the behavior-preservation proof)**

Run: `.venv/bin/python -m pytest tests/test_examples_morbidostat.py -q`
Expected: PASS — the control loop still pins each culture at its IC50, proving the expansion is
behavior-identical. If a role fails to map, confirm `_substitute` runs *after* `expand_dict` and
that every `{tube}` device resolved to a declared role (`od_meter_1/2/3`).

- [ ] **Step 6: Update `examples/README.md`**

Add a short subsection describing the `service(tube)` macro and the `for_each` scaffolding, and note
that scaling to 15 vials now means `"in": [1, …, 15]` plus 15×N stream declarations — the control
law is written once. Keep the existing derivation prose.

- [ ] **Step 7: Commit**

```bash
git add examples/morbidostat.json examples/morbidostat-demo-speed.json examples/README.md \
        tests/test_examples_morbidostat.py
git commit -m "example(morbidostat): parametrize tube service with for_each + service(tube) group"
```

---

## Task 6: Studio backend — grammar parity + expand before role substitution

**Files:**
- Modify: `webapp/backend/experiment_studio/roles.py`
- Modify: the Studio validate/run pipeline (the module that calls `roles.substitute` before handing
  a workflow to the engine — locate via `grep -rn "roles.substitute\|placeholder_ids\|expand" webapp/backend/experiment_studio`).
- Test: `webapp/backend/tests/test_roles.py`, and the relevant pipeline test.

**Interfaces:**
- Consumes: engine `expand_dict` (import `from lab_devices.experiment.expand import expand_dict`).
- Produces: role substitution recurses `for_each` bodies; the pipeline expands before substituting;
  the grammar-parity test includes `for_each`.

- [ ] **Step 1: Write the failing tests**

In `webapp/backend/tests/test_roles.py`, extend the parity test and add a for_each recursion test:

```python
def test_walker_grammar_matches_engine_serializer() -> None:
    covered = (
        set(roles._DEVICE_BLOCKS) | set(roles._CHILD_LISTS) | set(roles._LEAF_BLOCKS)
    )
    assert covered == set(serialize._BUILDERS)
    assert set(roles._DEVICE_BLOCKS) == {"command", "measure"}
    assert roles._CHILD_LISTS == {
        "serial": ("children",),
        "parallel": ("children",),
        "loop": ("body",),
        "branch": ("then", "else"),
        "for_each": ("body",),
    }


def test_substitute_recurses_for_each_bodies() -> None:
    wf = {"blocks": [{"for_each": {"var": "t", "in": [1],
                                   "body": [{"measure": {"device": "od", "verb": "measure",
                                                         "into": "x"}}]}}]}
    out, diags = roles.substitute(wf, {"od": "densitometer_1"})
    lane = out["blocks"][0]["for_each"]["body"][0]
    assert lane["measure"]["device"] == "densitometer_1"
    assert diags == []
```

- [ ] **Step 2: Run to verify failure**

Run: `cd webapp/backend && .venv/bin/python -m pytest tests/test_roles.py -q`
Expected: FAIL (`for_each` not in `_CHILD_LISTS`; walker skips its body).

- [ ] **Step 3: Add `for_each` to the walker grammar**

In `webapp/backend/experiment_studio/roles.py`, add `for_each` to `_CHILD_LISTS`:

```python
_CHILD_LISTS: dict[str, tuple[str, ...]] = {
    "serial": ("children",),
    "parallel": ("children",),
    "loop": ("body",),
    "branch": ("then", "else"),
    "for_each": ("body",),
}
```

`group_ref` stays in `_LEAF_BLOCKS` (its `args` are data, not a child list). The engine serializer
now has `for_each` in `_BUILDERS`, so the parity assertion balances.

- [ ] **Step 4: Expand before role substitution in the pipeline**

In the validate/run pipeline module (found in Step's grep), before the `roles.substitute(...)` call,
expand the workflow dict so templated roles become concrete:

```python
from lab_devices.experiment.expand import expand_dict
...
workflow = expand_dict(workflow)      # for_each / service(tube) -> concrete roles (design §9)
substituted, diags = roles.substitute(workflow, mapping)
```

Wrap the `expand_dict` call in a `try/except WorkflowLoadError` that surfaces the message as a
validation diagnostic (mirror how the pipeline already reports engine load errors), so a malformed
macro does not 500.

- [ ] **Step 5: Run to verify pass + full backend gate**

Run: `cd webapp/backend && .venv/bin/python -m pytest -q && .venv/bin/python -m mypy experiment_studio && .venv/bin/python -m ruff check .`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add webapp/backend/experiment_studio/roles.py webapp/backend/tests/test_roles.py \
        webapp/backend/experiment_studio/api
git commit -m "feat(studio-backend): for_each grammar parity + expand before role substitution"
```

---

## Task 7: Studio frontend — graceful, specific degrade for `for_each`

**Files:**
- Modify: `webapp/frontend/src/builder/convert.ts`
- Test: `webapp/frontend/src/builder/convert.test.ts`

**Interfaces:**
- Produces: a `for_each` (or parametrized-group) doc throws a *specific* `DocConvertError` that
  `WorkflowSnapshot.tsx` already catches and renders — no crash; run/chart/event-log unaffected.

- [ ] **Step 1: Write the failing test**

In `webapp/frontend/src/builder/convert.test.ts`, add:

```ts
it('reports for_each as a specific unsupported-in-builder message', () => {
  const doc = { doc_version: 1, roles: {}, workflow: { schema_version: 1, blocks: [
    { for_each: { var: 't', in: [1, 2], body: [{ wait: { duration: '1s' } }] } },
  ] } }
  expect(() => docToContent(doc as never)).toThrow(/for_each .*not .*supported .*builder/i)
})
```

(Use whatever the module's top-level convert entry is — `docToContent` / `docToBuilder`; mirror the
existing `groups are not supported` test in the same file.)

- [ ] **Step 2: Run to verify failure**

Run: `cd webapp/frontend && npm run test -- convert`
Expected: FAIL (generic `unsupported block type 'for_each'` message, not the specific one).

- [ ] **Step 3: Add the specific message**

In `webapp/frontend/src/builder/convert.ts`, in `blockToNode`, add a `for_each` case before the
`default:` throw:

```ts
    case 'for_each':
      throw new DocConvertError(
        'for_each is not yet supported in the builder (author it as JSON; it runs and charts)',
      )
```

`WorkflowSnapshot.tsx` already catches `DocConvertError` and renders the message (verify by reading
it); no other change is needed. Run/chart/event-log read from the backend `/streams` and events, not
`convert.ts`, so they are unaffected.

- [ ] **Step 4: Run to verify pass + frontend gate**

Run: `cd webapp/frontend && npm run test && npm run build`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add webapp/frontend/src/builder/convert.ts webapp/frontend/src/builder/convert.test.ts
git commit -m "feat(studio-frontend): specific graceful message for for_each docs in the builder"
```

---

## Task 8: Documentation

**Files:**
- Modify: `docs/experiment-engine-limitations.md`
- Modify: `docs/superpowers/specs/2026-07-07-experiment-orchestrator-design.md`

- [ ] **Step 1: Rewrite limitations #4 to "SHIPPED"**

In `docs/experiment-engine-limitations.md`, section **4** ("Groups are not parametrized"): change
the heading to `## 4. Groups are not parametrized — **SHIPPED (2026-07-15)**`, keep the motivation
prose, and add a "What shipped" paragraph describing `for_each` (splicing macro, objects + scalar
shorthand, first-class + expand-internally) and parametrized groups (`params`/`args`, inlined as a
`Serial`), citing the design spec. Update the summary table row #4 to strike the limitation and name
the feature. Update the closing summary paragraph: the 15-vial version is now expressible; note
`defaults.retry` had bought *retry policy* at scale, and #4 now buys the *control law* at scale.

- [ ] **Step 2: Amend the parent design spec**

In `docs/superpowers/specs/2026-07-07-experiment-orchestrator-design.md`: §5 (block taxonomy) add
`for_each`; §12 (groups) add `params`/`args` and the expand-then-validate model; §15
(serialization) add the `for_each` / `args` / `params` forms.

- [ ] **Step 3: Commit**

```bash
git add docs/experiment-engine-limitations.md \
        docs/superpowers/specs/2026-07-07-experiment-orchestrator-design.md
git commit -m "docs: mark limitations #4 shipped; amend parent spec for parametrized repetition"
```

---

## Task 9: Preprod validation on `windows_arm64_test_client`

**Files:** none (validation only; records findings).

- [ ] **Step 1: Run the rewritten demo-speed example on real hardware**

SSH `khamit@111.88.145.138`, docker exec into the jupyter container, and drive
`morbidostat-demo-speed.json` (25 cycles) against `windows_arm64_test_client` **through the engine
directly** (per the established preprod recipe — role mapping to the 7 real devices, `ExperimentRun`,
FakeClock not used; real clock). Follow the recipe in the `preprod-test-setup` memory.

- [ ] **Step 2: Confirm and record**

Confirm: (1) the `for_each`-expanded, `service(tube)`-driven workflow runs end to end on real
densitometers/pumps/valves; (2) per-tube streams (`od_i`, `c_series_i`, `r_series_i`) populate
independently; (3) the run completes with the expected per-tube run-log events and no expansion or
validation error. As in prior runs, the simulator reads absorbance 0.0 so the dosing arms may not
fire — record what was actually exercised (setup, thermostats, per-tube measurement, freshness
guard, branching, expansion) versus not (pump/valve dosing).

- [ ] **Step 3: Record the results** in the PR description and update the
  `experiment-orchestrator-increments` memory with the Increment-7 outcome.

---

## Self-Review

**Spec coverage:**
- §2 both primitives → Tasks 1 (AST), 2 (expand), 5 (example uses both). ✓
- §3 substitution (objects + scalar shorthand, `{name}`) → Task 2. ✓
- §4 first-class + expand-internally (validate + run) → Tasks 1, 3, 4. ✓
- §4.5 expansion cap → Task 2 (`_Counter`, `_MAX_DEPTH`). ✓
- §5 schema/serialization + load tolerance → Task 1. ✓
- §6 validation rules (arity, shape, forbidden keys, inherited concrete checks) → Task 3. ✓
- §7 testing → each task's tests + Task 5 integration. ✓
- §8 example rewrite + behavior-preservation → Task 5. ✓
- §9 Studio (backend parity + expand-before-substitute; frontend graceful) → Tasks 6, 7. ✓
- §10 out of scope — respected (no builder authoring; streams stay explicit). ✓
- §11 docs → Task 8. ✓
- §10 preprod → Task 9. ✓

**Placeholder scan:** Example JSON in Task 5 is given as a transformation recipe + concrete
fragments (the full 800-line doc is mechanically derived from the current one); every engine/test
step has complete code. No TBD/TODO.

**Type consistency:** `expand_dict(dict)->dict`, `expand_workflow(Workflow)->Workflow`,
`B.ForEach(var, items, body)`, `B.GroupRef(name, args)`, `Group(name, body, params)` are used
consistently across Tasks 1–6. `_CHILD_LISTS` for `for_each` is `("body",)` in both engine
(`expand.py`) and Studio (`roles.py`).

**Note for the implementer:** Task 5's example rewrite is the one non-mechanical task — verify each
`{tube}` substitution against the current tube-1/2/3 blocks, and rely on the existing integration
test (`test_examples_morbidostat.py`) as the behavior-preservation gate. If the golden-fixture
approach is preferred over the integration-test proof, generate the fixture with
`expand_dict(json.load(open('examples/morbidostat.json'))['workflow'])` and assert equality.
