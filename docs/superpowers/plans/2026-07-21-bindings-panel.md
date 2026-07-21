# Bindings Panel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a read-only "Bindings" section to the Builder's left palette that lists every binding in the current editing scope with its inferred type+unit, writer(s), and reader(s), and lets the user click a row to jump to the writing block.

**Architecture:** The engine already infers each binding's type; expose it via a public `binding_types(w)` wrapper, serialize it additively into the existing `/api/validate` response (which the frontend already fetches reactively), stash it in `useDocStore`, and render it in a new `BindingsPanel` fed by pure, unit-tested derivation helpers over the active tree.

**Tech Stack:** Python 3.11+ (engine + FastAPI backend), React 19 + TypeScript + Zustand + Tailwind 4 (frontend). Tests: pytest (engine/backend), vitest node-env (frontend pure functions only).

## Global Constraints

- **No schema change.** `schema_version` stays 3; `doc_version` stays 1. The `/api/validate` `binding_types` key is purely additive.
- **Do not change `validate_doc`'s signature** (`list[dict[str, str]]`) — 11 tests in `webapp/backend/tests/test_docs_store.py` assert it. Add a sibling function instead.
- **Frontend never re-implements the type lattice** (`builder/expr/analyze.ts:1-3` bans it). Types come only from the backend response.
- **Frontend conventions** (`webapp/frontend/CLAUDE.md`): interactive icons via lucide-react; icon-only actions via `IconButton` (≥24px); no raw glyph characters for interactive controls (prose dashes `—` and the `×N` count marker are allowed as text); truncating spans must set `title`; meaning-carrying secondary text uses `text-caption` (slate-600), incidental uses `text-hint` (slate-500); never concatenate a width/color onto a helper's output; Tailwind classes must be complete literals.
- **Frontend tests run in node env** — pure functions only, no component rendering. DOM wiring is verified by `npm run capture` (probe), not unit tests.
- **Commit conventions:** conventional commits (`feat(studio): …`). Each commit body ends with:
  ```
  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01JeRL4DvYxE5i9bVUFYhwBL
  ```
- **Local test runner:** the pyenv/poetry shim is broken on this machine; use the standalone venv at `/private/tmp/claude-501/-Users-khamit-lab-devices/04b15fd8-a9da-4fe7-8276-9b6947ea31b0/scratchpad/venv`. Shorthand below: `$VENV/bin/<tool>`. Frontend uses `npm` in `webapp/frontend`.

---

### Task 1: Engine — public `binding_types(w)` and exports

**Files:**
- Modify: `src/lab_devices/experiment/validate.py` (add public wrapper after `_collect_binding_types`, ~line 671)
- Modify: `src/lab_devices/experiment/__init__.py` (export `binding_types`, `unit_str`)
- Test: `tests/test_experiment_binding_types.py` (append 3 tests)

**Interfaces:**
- Produces: `binding_types(w: Workflow) -> dict[str, BindingType]` where `BindingType = ScalarType(base: str, unit: Unit)`; `unit_str(u: Unit) -> str` (already exists in `units.py`, newly exported).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_experiment_binding_types.py`:

```python
from lab_devices.experiment import binding_types, unit_str


def test_binding_types_reports_operator_input_and_compute_bases() -> None:
    types = binding_types(wf([
        {"operator_input": {"name": "n", "type": "int"}},
        {"compute": {"into": "x", "value": "1.5"}},
        {"compute": {"into": "flag", "value": "count(s) > 0"}},
    ], streams=["s"]))
    assert types["n"].base == "int"
    assert types["x"].base == "number"
    assert types["flag"].base == "bool"


def test_binding_types_honors_as_unit_cast() -> None:
    types = binding_types(wf([
        {"compute": {"into": "rate", "value": "1", "as": "AU/s"}},
    ]))
    assert types["rate"].base == "int"
    assert unit_str(types["rate"].unit) == "AU/s"


def test_binding_types_joins_multiple_writers_to_number() -> None:
    types = binding_types(wf([
        {"compute": {"into": "y", "value": "1"}},    # int
        {"compute": {"into": "y", "value": "1.5"}},  # number
    ]))
    assert types["y"].base == "number"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `$VENV/bin/pytest tests/test_experiment_binding_types.py -q`
Expected: FAIL with `ImportError: cannot import name 'binding_types'`.

- [ ] **Step 3: Add the public wrapper**

In `src/lab_devices/experiment/validate.py`, immediately after `_collect_binding_types` (after its `return types` at ~line 670), add:

```python
def binding_types(w: Workflow) -> dict[str, BindingType]:
    """Public: inferred (base, unit) of every binding in `w`, in document order — operator
    inputs from their declared `type`, compute bindings from their `value` expression (an `as`
    cast overrides the derived unit); a name written more than once takes the join of its
    writers. Group-local bindings are concretely typed only on an EXPANDED workflow (their
    per-instance qualified names); on a raw macro workflow they resolve to `unknown`."""
    return _collect_binding_types(w, _stream_units(w))
```

- [ ] **Step 4: Export from the package**

In `src/lab_devices/experiment/__init__.py`, change the validate import (line 98) to add `binding_types`:

```python
from lab_devices.experiment.validate import binding_types, load_and_validate, validate
```

Add a units import after it (new line):

```python
from lab_devices.experiment.units import unit_str
```

In `__all__`, add `"binding_types"` to the first analysis group (line 112-113) and `"unit_str"` to it too, e.g. change the line beginning `"BindingType", ...` to include both names:

```python
    "BindingType", "Diagnostic", "ExprRefs", "ExprType", "TypeReport",
    "ValidationError", "binding_types", "infer_type", "load_and_validate",
    "references", "unit_str", "validate",
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `$VENV/bin/pytest tests/test_experiment_binding_types.py -q`
Expected: PASS (6 tests total — 3 old + 3 new).

- [ ] **Step 6: Type-check and lint**

Run: `$VENV/bin/mypy && $VENV/bin/ruff check .` (from repo root)
Expected: `Success: no issues found` and `All checks passed!`.

- [ ] **Step 7: Commit**

```bash
git add src/lab_devices/experiment/validate.py src/lab_devices/experiment/__init__.py tests/test_experiment_binding_types.py
git commit -m "$(cat <<'EOF'
feat(experiment): public binding_types() inference accessor

Expose the engine's per-binding (base, unit) inference and unit_str for
surfacing to the web layer. Additive; no behaviour change.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01JeRL4DvYxE5i9bVUFYhwBL
EOF
)"
```

---

### Task 2: Backend — serialize `binding_types` into `/api/validate`

**Files:**
- Modify: `webapp/backend/experiment_studio/docs_store.py` (imports + new `binding_types_for_doc`)
- Modify: `webapp/backend/experiment_studio/api/validate.py` (add response key)
- Test: `webapp/backend/tests/test_validate_api.py` (update 9 exact-equality tests, add 2)

**Interfaces:**
- Consumes: `binding_types`, `unit_str` from `lab_devices.experiment` (Task 1).
- Produces: `binding_types_for_doc(doc: ExperimentDoc) -> dict[str, dict[str, str]]`; the `/api/validate` response gains `"binding_types": {name: {"base": str, "unit": str}}`.

- [ ] **Step 1: Write the failing tests**

In `webapp/backend/tests/test_validate_api.py`, add (near the bottom):

```python
async def test_validate_returns_binding_types(client: httpx.AsyncClient) -> None:
    workflow = {
        "schema_version": 3,
        "blocks": [
            {"operator_input": {"name": "n", "type": "int"}},
            {"compute": {"into": "rate", "value": "1", "as": "AU/s"}},
        ],
    }
    resp = await client.post("/api/validate", json=_doc(workflow))
    body = resp.json()
    assert body["binding_types"]["n"] == {"base": "int", "unit": "unitless"}
    assert body["binding_types"]["rate"] == {"base": "int", "unit": "AU/s"}


async def test_binding_types_empty_when_doc_fails_to_load(client: httpx.AsyncClient) -> None:
    # unknown device type -> WorkflowLoadError -> no types, but diagnostics still returned
    resp = await client.post("/api/validate", json=load_fixture("invalid-roles.json"))
    body = resp.json()
    assert body["binding_types"] == {}
    assert body["ok"] is False and body["diagnostics"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run (from `webapp/backend`): `$VENV/bin/pytest tests/test_validate_api.py -q -k binding_types`
Expected: FAIL with `KeyError: 'binding_types'`.

- [ ] **Step 3: Add `binding_types_for_doc`**

In `webapp/backend/experiment_studio/docs_store.py`, extend the engine import block (lines 16-21) to add `binding_types` and `unit_str`:

```python
from lab_devices.experiment import (
    ValidationError,
    WorkflowLoadError,
    binding_types,
    unit_str,
    validate,
    workflow_from_dict,
)
```

Add this function immediately after `validate_doc` (after its `return []` at ~line 271):

```python
def binding_types_for_doc(doc: ExperimentDoc) -> dict[str, dict[str, str]]:
    """Inferred type of every binding, keyed by name, as {"base", "unit"} for the Bindings
    panel. Runs the same expand -> parse pipeline as `validate_doc`; on any load error the map
    is empty (the panel then shows names/writers/readers from the tree and dashes for type).
    Keys are the expanded/qualified names the engine type-checks — root bindings plus
    per-instance group-locals like `tube_A_c`; the frontend matches by name and ignores the rest."""
    try:
        expanded, _ = expand_dict_traced(doc.workflow)
        workflow = workflow_from_dict(expanded)
    except WorkflowLoadError:
        return {}
    return {
        name: {"base": t.base, "unit": unit_str(t.unit)}
        for name, t in binding_types(workflow).items()
    }
```

- [ ] **Step 4: Wire it into the endpoint**

Replace `webapp/backend/experiment_studio/api/validate.py` body:

```python
"""Stateless draft-validation endpoint. See webapp design §4.3, §6."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from experiment_studio.docs_store import ExperimentDoc, binding_types_for_doc, validate_doc

router = APIRouter()


@router.post("/validate")
def validate_document(doc: ExperimentDoc) -> dict[str, Any]:
    diagnostics = validate_doc(doc)
    return {
        "ok": not diagnostics,
        "diagnostics": diagnostics,
        "binding_types": binding_types_for_doc(doc),
    }
```

- [ ] **Step 5: Update the 9 exact-equality tests**

In `webapp/backend/tests/test_validate_api.py`, add `"binding_types": {}` to the expected dicts of the **no-binding** tests: `test_valid_doc_is_clean` (line 21), `test_doc_level_diagnostics` (line 50-62), `test_engine_diagnostics_pass_through_with_structural_paths` (line 70-78), `test_schema_three_is_accepted` (line 91), `test_distinct_roles_of_same_type_are_clean` (line 136), `test_for_each_typed_role_var_validates_clean` (line 174), `test_malformed_for_each_yields_expansion_diagnostic` (line 187-191). Example for `test_valid_doc_is_clean`:

```python
    assert resp.json() == {"ok": True, "diagnostics": [], "binding_types": {}}
```

For the **two binding-bearing** tests, replace whole-dict equality with contract checks.

`test_valid_control_blocks_doc_is_clean` (lines 24-27):

```python
async def test_valid_control_blocks_doc_is_clean(client: httpx.AsyncClient) -> None:
    resp = await client.post("/api/validate", json=load_fixture("valid-control-blocks.json"))
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True and body["diagnostics"] == []
    # emergency_stop is an operator_input bool; V/c are numeric-literal computes the engine
    # does not type (it only types string-valued computes), so they may be absent.
    assert body["binding_types"]["emergency_stop"] == {"base": "bool", "unit": "unitless"}
```

`test_morbidostat_example_is_clean` (lines 30-42) — keep the docstring, change the assertion:

```python
    doc = json.loads((EXAMPLES / "morbidostat.json").read_text())
    resp = await client.post("/api/validate", json=doc)
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True and body["diagnostics"] == []
    assert body["binding_types"]["working_volume_ml"] == {"base": "int", "unit": "unitless"}
    assert body["binding_types"]["od_min"] == {"base": "number", "unit": "unitless"}
```

- [ ] **Step 6: Run the whole validate-api suite**

Run (from `webapp/backend`): `$VENV/bin/pytest tests/test_validate_api.py -q`
Expected: PASS (all tests, including the 2 new).

- [ ] **Step 7: Full backend gate**

Run (from `webapp/backend`): `$VENV/bin/pytest -q && $VENV/bin/mypy && $VENV/bin/ruff check .`
Expected: all pass (`168 + 2` tests, mypy clean, ruff clean).

- [ ] **Step 8: Commit**

```bash
git add webapp/backend/experiment_studio/docs_store.py webapp/backend/experiment_studio/api/validate.py webapp/backend/tests/test_validate_api.py
git commit -m "$(cat <<'EOF'
feat(studio): surface inferred binding types in /api/validate

Additive binding_types map ({name: {base, unit}}) alongside diagnostics,
computed from the same expanded workflow. Empty on load errors.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01JeRL4DvYxE5i9bVUFYhwBL
EOF
)"
```

---

### Task 3: Frontend — carry `binding_types` through the reactive validate pipeline

**Files:**
- Modify: `webapp/frontend/src/types/doc.ts` (add `BindingTypeJson`, extend `ValidateResponse`)
- Modify: `webapp/frontend/src/stores/docStore.ts` (add `bindingTypes` field + setter + init + clear)
- Modify: `webapp/frontend/src/builder/useValidation.ts` (set it from the response)

**Interfaces:**
- Produces: `BindingTypeJson = { base: string; unit: string }`; `useDocStore` gains `bindingTypes: Record<string, BindingTypeJson>` and `setBindingTypes(types)`; the validate `.then` populates it.

- [ ] **Step 1: Extend the response type**

In `webapp/frontend/src/types/doc.ts`, after the `Diagnostic` interface (line 201), add and extend:

```ts
export interface BindingTypeJson {
  base: string
  unit: string
}

export interface ValidateResponse {
  ok: boolean
  diagnostics: Diagnostic[]
  binding_types?: Record<string, BindingTypeJson>
}
```

(Replace the existing `ValidateResponse` at lines 203-206.)

- [ ] **Step 2: Add store field, setter, init, and clear**

In `webapp/frontend/src/stores/docStore.ts`:

- Add `BindingTypeJson` to the type import from `'../types/doc'` (the existing import that brings in `ParamDeclJson`, `LocalDeclJson`, etc.).
- After `diagnostics: MappedDiagnostic[]` (line 92) add: `bindingTypes: Record<string, BindingTypeJson>`
- After `setDiagnostics: (diags: MappedDiagnostic[]) => void` (line 119) add: `setBindingTypes: (types: Record<string, BindingTypeJson>) => void`
- After `diagnostics: [],` in the initial state (line 242) add: `bindingTypes: {},`
- After `setDiagnostics: (diagnostics) => set({ diagnostics }),` (line 424) add: `setBindingTypes: (bindingTypes) => set({ bindingTypes }),`
- After `diagnostics: [],` inside `loadDoc`'s `setState` (line 537) add: `bindingTypes: {},`

- [ ] **Step 3: Populate it from the validate response**

In `webapp/frontend/src/builder/useValidation.ts`, inside the `.then((resp) => {…})` block, after `state.setDiagnostics(...)` (line 30), add:

```ts
          state.setBindingTypes(resp.binding_types ?? {})
```

- [ ] **Step 4: Type-check**

Run (from `webapp/frontend`): `npm run typecheck`
Expected: no errors.

- [ ] **Step 5: Run frontend tests (regression)**

Run (from `webapp/frontend`): `npm test`
Expected: PASS (721 tests — nothing broken by the additive field).

- [ ] **Step 6: Commit**

```bash
git add webapp/frontend/src/types/doc.ts webapp/frontend/src/stores/docStore.ts webapp/frontend/src/builder/useValidation.ts
git commit -m "$(cat <<'EOF'
feat(studio): carry binding_types through the validate pipeline

Extend ValidateResponse and stash the map in docStore.bindingTypes,
populated by the existing debounced validate effect.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01JeRL4DvYxE5i9bVUFYhwBL
EOF
)"
```

---

### Task 4: Frontend — pure binding-index derivation helpers

**Files:**
- Create: `webapp/frontend/src/builder/bindings.ts`
- Test: `webapp/frontend/src/builder/bindings.test.ts`

**Interfaces:**
- Consumes: `visitNodes`, `BlockNode` (`./tree`); `collectBindings` (`./refs`); `hole`, `scopeBindingNames` (`./scopeRefs`); `parseExpression`, `Expr` (`./expr/parse`); `GroupDef` (`./convert`); `BindingTypeJson` (`../types/doc`).
- Produces:
  - `WriterKind = 'operator_input' | 'compute'`
  - `WriterRef = { kind: WriterKind; uid: string; label: string | null }`
  - `ReaderRef = { uid: string; label: string | null; field: string }`
  - `BindingRow = { name: string; type: BindingTypeJson | null; writers: WriterRef[]; readers: ReaderRef[]; decl: 'param' | 'local' | null }`
  - `collectBindingWriters(tree): Record<string, WriterRef[]>`
  - `bindingReferences(text, names: ReadonlySet<string>): string[]`
  - `collectBindingReaders(tree, names: ReadonlySet<string>): Record<string, ReaderRef[]>`
  - `groupBindingDeclKinds(group): Record<string, 'param' | 'local'>`
  - `bindingIndex(tree, group, bindingTypes): BindingRow[]`

- [ ] **Step 1: Write the failing tests**

Create `webapp/frontend/src/builder/bindings.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import type { BlockNode } from './tree'
import {
  bindingIndex,
  bindingReferences,
  collectBindingReaders,
  collectBindingWriters,
} from './bindings'

const base = (uid: string, label: string | null = null) => ({
  uid,
  label,
  gapAfter: null,
  startOffset: null,
})
const oi = (uid: string, name: string): BlockNode =>
  ({ ...base(uid), kind: 'operator_input', name, inputType: 'int', prompt: null, min: null, max: null, choices: null })
const cmp = (uid: string, into: string, value: string, label: string | null = null): BlockNode =>
  ({ ...base(uid, label), kind: 'compute', into, value })
const branch = (uid: string, condition: string): BlockNode =>
  ({ ...base(uid), kind: 'branch', condition, then: [], else: null })

describe('collectBindingWriters', () => {
  it('records operator_input and compute writers, keeping multiples', () => {
    const tree = [oi('u1', 'n'), cmp('u2', 'x', '1'), cmp('u3', 'x', '2')]
    const w = collectBindingWriters(tree)
    expect(w['n']).toEqual([{ kind: 'operator_input', uid: 'u1', label: null }])
    expect(w['x'].map((r) => r.uid)).toEqual(['u2', 'u3'])
  })
})

describe('bindingReferences', () => {
  it('returns only known bare names referenced by the expression', () => {
    const names = new Set(['x', 'y'])
    expect(bindingReferences('x + z', names).sort()).toEqual(['x'])
    expect(bindingReferences('x + y', names).sort()).toEqual(['x', 'y'])
  })
  it('matches {hole} names by delimited substring and ignores unknown holes', () => {
    const names = new Set(['{c}'])
    expect(bindingReferences('{c} * working_volume_ml', names)).toEqual(['{c}'])
    expect(bindingReferences('{contaminated}', names)).toEqual([])
  })
})

describe('collectBindingReaders', () => {
  it('finds reads across compute value and branch condition', () => {
    const tree = [cmp('u1', 'x', '1'), cmp('u2', 'y', 'x + 1'), branch('u3', 'x > 0')]
    const readers = collectBindingReaders(tree, new Set(['x', 'y']))
    expect(readers['x'].map((r) => `${r.uid}:${r.field}`).sort()).toEqual(['u2:value', 'u3:condition'])
    expect(readers['y']).toBeUndefined()
  })
})

describe('bindingIndex', () => {
  it('merges writers, readers and types in document order', () => {
    const tree = [oi('u1', 'n'), cmp('u2', 'x', 'n + 1')]
    const rows = bindingIndex(tree, null, { n: { base: 'int', unit: 'unitless' } })
    expect(rows.map((r) => r.name)).toEqual(['n', 'x'])
    const n = rows[0]
    expect(n.type).toEqual({ base: 'int', unit: 'unitless' })
    expect(n.writers.map((w) => w.uid)).toEqual(['u1'])
    expect(n.readers.map((r) => r.uid)).toEqual(['u2'])
    expect(rows[1].type).toBeNull()
  })

  it('tags a declared-but-unwritten group binding param/local', () => {
    const group = {
      params: [{ name: 'p', kind: 'binding' as const }],
      locals: { c: { kind: 'binding' as const, init: '0' } },
      body: [],
    }
    const rows = bindingIndex([], group, {})
    const byName = Object.fromEntries(rows.map((r) => [r.name, r]))
    expect(byName['{p}'].decl).toBe('param')
    expect(byName['{c}'].decl).toBe('local')
  })
})
```

- [ ] **Step 2: Run tests to verify they fail**

Run (from `webapp/frontend`): `npm test -- bindings`
Expected: FAIL (cannot resolve `./bindings`).

- [ ] **Step 3: Implement the helpers**

Create `webapp/frontend/src/builder/bindings.ts`:

```ts
/** Read-only derivations for the Bindings palette panel (design 2026-07-21). Pure so they are
 * node-env unit-testable; the panel component subscribes to the store and calls these. A binding
 * is written by operator_input/compute and read by any expression; type+unit comes from the
 * backend (this file never re-implements the lattice — analyze.ts:1-3). */
import type { BindingTypeJson } from '../types/doc'
import type { GroupDef } from './convert'
import { collectBindings } from './refs'
import { hole, scopeBindingNames } from './scopeRefs'
import { parseExpression, type Expr } from './expr/parse'
import { visitNodes, type BlockNode } from './tree'

export type WriterKind = 'operator_input' | 'compute'
export interface WriterRef {
  kind: WriterKind
  uid: string
  label: string | null
}
export interface ReaderRef {
  uid: string
  label: string | null
  field: string
}
export interface BindingRow {
  name: string
  type: BindingTypeJson | null
  writers: WriterRef[]
  readers: ReaderRef[]
  /** Set only when the name has NO writer block: a group binding param/local (no canvas block
   * to jump to). null otherwise. */
  decl: 'param' | 'local' | null
}

/** Which block(s) write each binding. operator_input.name / compute.into; a name may have
 * several compute writers, all kept in document order. */
export function collectBindingWriters(tree: BlockNode[]): Record<string, WriterRef[]> {
  const out: Record<string, WriterRef[]> = {}
  visitNodes(tree, (node) => {
    const name =
      node.kind === 'operator_input' ? node.name : node.kind === 'compute' ? node.into : null
    if (name === null || name === '') return
    ;(out[name] ??= []).push({ kind: node.kind as WriterKind, uid: node.uid, label: node.label })
  })
  return out
}

function collectBindingNodeNames(ast: Expr, out: Set<string>): void {
  switch (ast.t) {
    case 'binding':
      out.add(ast.name)
      return
    case 'unary':
      collectBindingNodeNames(ast.operand, out)
      return
    case 'binary':
      collectBindingNodeNames(ast.left, out)
      collectBindingNodeNames(ast.right, out)
      return
    default:
      return
  }
}

/** Which of `names` a single expression references. Bare names come from the parser; {hole}
 * names (group-body templates the tokenizer cannot lex) are matched as exact delimited
 * substrings. Only names in `names` are returned, so stream holes never masquerade as bindings. */
export function bindingReferences(text: string, names: ReadonlySet<string>): string[] {
  const found = new Set<string>()
  const res = parseExpression(text)
  if (res.ok) {
    const bare = new Set<string>()
    collectBindingNodeNames(res.ast, bare)
    for (const n of bare) if (names.has(n)) found.add(n)
  }
  for (const n of names) {
    if (n.startsWith('{') && n.endsWith('}') && text.includes(n)) found.add(n)
  }
  return [...found]
}

/** Every expression-bearing text field on a node that can reference a binding. gap_after /
 * start_offset are out of scope for v1. */
function exprFields(node: BlockNode): Array<[string, string]> {
  const out: Array<[string, string]> = []
  const push = (field: string, v: unknown): void => {
    if (typeof v === 'string' && v.trim() !== '') out.push([field, v])
  }
  switch (node.kind) {
    case 'compute':
    case 'record':
      push('value', node.value)
      break
    case 'branch':
      push('condition', node.condition)
      break
    case 'loop':
      push('count', node.count)
      push('until', node.until)
      push('pace', node.pace)
      break
    case 'abort':
    case 'alarm':
      push('condition', node.condition)
      break
    case 'command':
    case 'measure':
      for (const [k, v] of Object.entries(node.params)) push(`params.${k}`, v)
      break
    default:
      break
  }
  return out
}

/** Which block(s) read each of `names`, across every expression-bearing field. */
export function collectBindingReaders(
  tree: BlockNode[],
  names: ReadonlySet<string>,
): Record<string, ReaderRef[]> {
  const out: Record<string, ReaderRef[]> = {}
  visitNodes(tree, (node) => {
    for (const [field, text] of exprFields(node)) {
      for (const name of bindingReferences(text, names)) {
        ;(out[name] ??= []).push({ uid: node.uid, label: node.label, field })
      }
    }
  })
  return out
}

/** {hole} name -> whether it is a binding PARAM or a binding LOCAL of the group. Tags
 * declared-but-unwritten bindings. Empty at the workflow scope. */
export function groupBindingDeclKinds(group: GroupDef | null): Record<string, 'param' | 'local'> {
  const out: Record<string, 'param' | 'local'> = {}
  if (group === null) return out
  for (const p of group.params) {
    if (p.kind !== 'role' && p.kind !== 'stream') out[hole(p.name)] = 'param'
  }
  for (const [name, l] of Object.entries(group.locals)) {
    if (l.kind === 'binding') out[hole(name)] = 'local'
  }
  return out
}

/** The active scope's bindings, merged for the panel — exactly the set the expression editor
 * offers: collectBindings(tree) then the group's binding params/locals ({holes}), in that order.
 * Type comes from `bindingTypes` by exact name (concrete root bindings match; {holes} do not, so
 * they show no type). `decl` is set only when a name has no writer block. */
export function bindingIndex(
  tree: BlockNode[],
  group: GroupDef | null,
  bindingTypes: Record<string, BindingTypeJson>,
): BindingRow[] {
  const writers = collectBindingWriters(tree)
  const declKind = groupBindingDeclKinds(group)
  const order: string[] = []
  const seen = new Set<string>()
  for (const n of [...collectBindings(tree), ...scopeBindingNames(group)]) {
    if (!seen.has(n)) {
      seen.add(n)
      order.push(n)
    }
  }
  const names = new Set(order)
  const readers = collectBindingReaders(tree, names)
  return order.map((name) => {
    const w = writers[name] ?? []
    return {
      name,
      type: bindingTypes[name] ?? null,
      writers: w,
      readers: readers[name] ?? [],
      decl: w.length === 0 ? (declKind[name] ?? null) : null,
    }
  })
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run (from `webapp/frontend`): `npm test -- bindings`
Expected: PASS (all `bindings.test.ts` cases).

- [ ] **Step 5: Lint + typecheck**

Run (from `webapp/frontend`): `npm run lint && npm run typecheck`
Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add webapp/frontend/src/builder/bindings.ts webapp/frontend/src/builder/bindings.test.ts
git commit -m "$(cat <<'EOF'
feat(studio): pure binding-index derivations for the Bindings panel

collectBindingWriters/Readers, bindingReferences (bare + {hole}), and
bindingIndex merging writers/readers/type per active scope. Node-tested.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01JeRL4DvYxE5i9bVUFYhwBL
EOF
)"
```

---

### Task 5: Frontend — `BindingsPanel` component + palette mount

**Files:**
- Create: `webapp/frontend/src/builder/BindingsPanel.tsx`
- Modify: `webapp/frontend/src/builder/Palette.tsx` (import + `<Section>` after Groups)

**Interfaces:**
- Consumes: `bindingIndex`, `BindingRow`, `WriterRef`, `WriterKind` (`./bindings`); `useActiveTree`, `useDocStore` (`../stores/docStore`); `useScopeRefs` (`./scopeRefs`); `KindIcon` (`../ui/icons`); `IconButton` (`../ui/IconButton`); store `select`, `setScope`, `scrollToBlock`, `bindingTypes`.

- [ ] **Step 1: Create the component**

Create `webapp/frontend/src/builder/BindingsPanel.tsx`:

```tsx
import { useMemo, useState } from 'react'
import { ChevronDown, ChevronRight } from 'lucide-react'
import { useActiveTree, useDocStore } from '../stores/docStore'
import { useScopeRefs } from './scopeRefs'
import { bindingIndex, type BindingRow, type WriterKind, type WriterRef } from './bindings'
import { KindIcon } from '../ui/icons'
import { IconButton } from '../ui/IconButton'

const WRITER_NOUN: Record<WriterKind, string> = { operator_input: 'input', compute: 'compute' }

function writerLabel(w: WriterRef): string {
  return w.label ? `${WRITER_NOUN[w.kind]} · ${w.label}` : WRITER_NOUN[w.kind]
}

function TypeBadge({ type }: { type: BindingRow['type'] }) {
  if (type === null) return <span className="shrink-0 text-xs text-hint">—</span>
  const showUnit = type.unit !== 'unitless' && (type.base === 'int' || type.base === 'number')
  return (
    <span
      className="shrink-0 rounded bg-slate-100 px-1 text-xs text-caption"
      title={showUnit ? `${type.base} in ${type.unit}` : type.base}
    >
      {type.base}
      {showUnit && <span className="text-hint">{`<${type.unit}>`}</span>}
    </span>
  )
}

function WriterIndicator({ row }: { row: BindingRow }) {
  if (row.writers.length === 0) {
    return row.decl ? (
      <span className="shrink-0 rounded bg-slate-100 px-1 text-xs text-caption">{row.decl}</span>
    ) : null
  }
  return (
    <span className="flex shrink-0 items-center gap-0.5" title={row.writers.map(writerLabel).join(', ')}>
      <KindIcon kind={row.writers[0].kind} />
      {row.writers.length > 1 && <span className="text-xs text-caption">×{row.writers.length}</span>}
    </span>
  )
}

/** Read-only overview of the active scope's bindings (design 2026-07-21). Names/writers/readers
 * come from the tree; type+unit from docStore.bindingTypes. Clicking a row (or a child) selects
 * and scrolls to that block, reusing ProblemsPanel's setScope -> select -> scrollToBlock order. */
export function BindingsPanel() {
  const { scope, group } = useScopeRefs()
  const activeTree = useActiveTree()
  const bindingTypes = useDocStore((s) => s.bindingTypes)
  const select = useDocStore((s) => s.select)
  const setScope = useDocStore((s) => s.setScope)
  const scrollToBlock = useDocStore((s) => s.scrollToBlock)
  const [expanded, setExpanded] = useState<Set<string>>(new Set())

  const rows = useMemo(
    () => bindingIndex(activeTree, group, bindingTypes),
    [activeTree, group, bindingTypes],
  )

  const jump = (uid: string): void => {
    setScope(scope) // rows are all in the active scope; keeps the ProblemsPanel navigation shape
    select(uid)
    scrollToBlock(uid)
  }
  const toggle = (name: string): void =>
    setExpanded((prev) => {
      const next = new Set(prev)
      if (next.has(name)) next.delete(name)
      else next.add(name)
      return next
    })

  if (rows.length === 0) {
    return (
      <p className="px-1 text-xs text-hint">
        No bindings in this scope yet — created by operator_input and compute blocks.
      </p>
    )
  }

  return (
    <ul className="space-y-1">
      {rows.map((row) => {
        const hasDetail = row.writers.length > 0 || row.readers.length > 0
        const isOpen = expanded.has(row.name)
        return (
          <li key={row.name}>
            <div className="flex items-center gap-1 text-sm">
              {hasDetail ? (
                <IconButton
                  icon={isOpen ? ChevronDown : ChevronRight}
                  label={isOpen ? 'Hide writers and readers' : 'Show writers and readers'}
                  onClick={() => toggle(row.name)}
                />
              ) : (
                <span className="inline-block h-6 w-6 shrink-0" aria-hidden />
              )}
              <button
                type="button"
                title={row.writers.length > 0 ? 'Go to where this binding is written' : row.name}
                disabled={row.writers.length === 0}
                onClick={() => row.writers[0] && jump(row.writers[0].uid)}
                className="flex min-w-0 flex-1 items-center gap-1 text-left enabled:hover:underline disabled:cursor-default"
              >
                <span className="min-w-0 flex-1 truncate font-mono text-caption" title={row.name}>
                  {row.name}
                </span>
              </button>
              <TypeBadge type={row.type} />
              <WriterIndicator row={row} />
            </div>
            {isOpen && hasDetail && (
              <ul className="ml-6 mt-0.5 space-y-0.5">
                {row.writers.map((w, i) => (
                  <li key={`w${i}`}>
                    <button
                      type="button"
                      onClick={() => jump(w.uid)}
                      className="flex w-full items-center gap-1 text-left text-xs text-caption hover:underline"
                    >
                      <KindIcon kind={w.kind} />
                      <span className="min-w-0 truncate">{writerLabel(w)}</span>
                    </button>
                  </li>
                ))}
                {row.readers.map((r, i) => (
                  <li key={`r${i}`}>
                    <button
                      type="button"
                      onClick={() => jump(r.uid)}
                      className="flex w-full items-center gap-1 text-left text-xs text-hint hover:underline"
                    >
                      <span className="min-w-0 truncate">read by {r.label ?? r.field}</span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </li>
        )
      })}
    </ul>
  )
}
```

- [ ] **Step 2: Mount it in the palette**

In `webapp/frontend/src/builder/Palette.tsx`, add the import after the `StreamsPanel` import (line 8):

```tsx
import { BindingsPanel } from './BindingsPanel'
```

And add a section after the Groups `<Section>` (after line 137, before the closing `</aside>`):

```tsx
      <Section title="Bindings" defaultOpen={false}>
        <BindingsPanel />
      </Section>
```

- [ ] **Step 3: Typecheck, lint, build**

Run (from `webapp/frontend`): `npm run typecheck && npm run lint && npm run build`
Expected: build succeeds (tsc clean, vite bundles).

- [ ] **Step 4: Run frontend tests**

Run (from `webapp/frontend`): `npm test`
Expected: PASS (existing 721 + new bindings tests; nothing regressed).

- [ ] **Step 5: Commit**

```bash
git add webapp/frontend/src/builder/BindingsPanel.tsx webapp/frontend/src/builder/Palette.tsx
git commit -m "$(cat <<'EOF'
feat(studio): read-only Bindings section in the Builder palette

Scope-aware list of bindings with inferred type+unit, writer/reader
drill-down, and click-to-jump to the writing block.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01JeRL4DvYxE5i9bVUFYhwBL
EOF
)"
```

---

### Task 6: Full verification (all CI gates)

**Files:** none (verification only).

- [ ] **Step 1: Engine gate**

Run (repo root): `$VENV/bin/pytest tests/ -q && $VENV/bin/mypy && $VENV/bin/ruff check .`
Expected: all pass.

- [ ] **Step 2: Backend gate**

Run (from `webapp/backend`): `$VENV/bin/pytest -q && $VENV/bin/mypy && $VENV/bin/ruff check .`
Expected: all pass.

- [ ] **Step 3: Frontend gate**

Run (from `webapp/frontend`): `npm run lint && npm test && npm run build`
Expected: all pass.

- [ ] **Step 4: Visual probe (best-effort, not a CI gate)**

If a lab + both servers are available, run (from `webapp/frontend`): `npm run capture` against a doc containing bindings (e.g. morbidostat) and confirm the probe reports no new `sibling-height-mismatch` (R4) or `text-contrast` (R5) findings for the Bindings section. If servers are unavailable, note it — CI does not run this.

- [ ] **Step 5: Push and open the PR** (see the session's PR/CI/merge flow).

---

## Notes carried from the spec (known, intentional limitations)

- **Type at group scope:** group-body bindings are `{hole}` names that don't match the backend's expanded keys, so their type shows `—`. This is correct — template holes are typed per instance, not per authored hole.
- **Readers at group scope:** hole reads are matched by delimited substring; bare top-level reads inside an unparseable hole expression are not attributed (and aren't listed at group scope anyway). Root scope is fully covered by the parser.
- **Numeric-literal computes** (`compute into V value 12`) are not typed by the engine (it only types string-valued computes), so they show `—`. Pre-existing engine behavior, surfaced as-is.
- **Re-clicking the same writer** is a no-op (`scrollToUid` isn't reset); clicking a different row always works. Acceptable for v1.
