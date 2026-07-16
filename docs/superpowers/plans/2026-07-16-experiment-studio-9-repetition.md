# Experiment Studio W9 — repetition (for_each + parametrized groups)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `for_each` and parametrized `groups`/`group_ref` first-class in the Studio builder canvas, so `examples/morbidostat.json` — the flagship — opens, renders, and round-trips for the first time.

**Architecture:** `for_each` becomes an ordinary container node (`childSlots` gains its `body` slot, and drag/drop/duplicate/undo follow for free). `groups` become a second editing scope: the store holds `groups` beside `tree`, and the canvas renders whichever scope is selected. Because the backend validates the *expanded* workflow, diagnostics carry expanded indices that do not match the authored tree — so `expand.py` gains a **source map** (expanded path → authored path) that `docs_store` applies before diagnostics leave the backend.

**Tech Stack:** Python 3.14 (engine + backend), React 19.2, Vite 8, Tailwind 4, vitest 4 (node env, TZ=UTC), zustand + zundo, TypeScript strict (`erasableSyntaxOnly`, `verbatimModuleSyntax`), oxlint.

**Spec:** [`docs/superpowers/specs/2026-07-16-experiment-studio-engine-parity-design.md`](../specs/2026-07-16-experiment-studio-engine-parity-design.md) **§5** (W9). §4 (W8) shipped in PR #28 (`93a0d1d`).

## Global Constraints

- **Engine gate:** `.venv/bin/python -m pytest -q && .venv/bin/python -m mypy && .venv/bin/python -m ruff check . && awk 'length>100' over changed src+tests`. **`mypy` scope is `src/lab_devices` ONLY — never pass `tests`.** Engine source modules start with `from __future__ import annotations` + a one-line docstring citing the design §.
- **Backend gate:** `cd webapp/backend && .venv/bin/python -m pytest -q && .venv/bin/python -m mypy && .venv/bin/python -m ruff check .` — **`mypy` takes NO path argument.**
- **Frontend gate:** `cd webapp/frontend && npm run lint && npm run typecheck && npm test -- --run && npm run build`. Two known oxlint fast-refresh warnings expected; exit 0.
- **`expand_dict`'s existing signature must not change.** `runner.py:296` and `expand_workflow` (`expand.py:240`) keep calling it. Only `docs_store.py:164` moves to the traced sibling.
- **Behaviour-preserving on the engine.** W9 adds a trace; it must not change what `expand_dict` *produces*. The existing engine suite (722+) is the guard.
- **`for_each` may not carry `retry`/`on_error`/`gap_after`/`start_offset`** (`expand.py:26` `_FOR_EACH_FORBIDDEN`) — it is a splice, so there is no single runtime block for such a key to attach to. The Inspector must not offer them.
- TypeScript strict. No `any`. No non-null assertions (`!`).
- Commit after every task with the shown message.

---

### Task 1: `expand_dict_traced` — the source map

**Files:**
- Modify: `src/lab_devices/experiment/expand.py`
- Test: `tests/test_experiment_expand_trace.py` (new)

**Interfaces:**
- Consumes: nothing.
- Produces: `expand_dict_traced(workflow_dict: dict[str, Any]) -> tuple[dict[str, Any], dict[str, str]]` — the expanded workflow **plus** a trace mapping **expanded structural path → authored structural path**. `expand_dict(d)` keeps its exact current signature and behaviour (it becomes `expand_dict_traced(d)[0]`).

**Context.** `docs_store.validate_doc` expands *before* validating (`docs_store.py:164`), so `validate()` sees a macro-free workflow and every structural path it emits is an **expanded** path. An authored `for_each` at `blocks[0]` producing 3 siblings makes expanded `blocks[2]` a copy of its body — while authored `blocks[2]` is an unrelated block. Without a map, the frontend resolves the diagnostic onto the **wrong block** and highlights it, which is strictly worse than not resolving it.

The path grammar is the validator's own (`validate.py:44-64`): `blocks[i]`, `.children[j]`, `.body[k]`, `.then[k]`, `.else[k]`, and `groups['name'].body[i]` for group bodies. **The type key never appears** — a `for_each` body block is `blocks[0].body[0]` (`validate.py:58` yields `f"{path}.body"`), the same spelling a `loop` body uses.

Mapping is **many-to-one** and that is correct: all three `for_each` copies trace to the one authored body block, because that is the one place the author can edit.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_experiment_expand_trace.py`. No `from __future__` import in test files; imports at top (ruff's default select includes E402/F401).

```python
"""Source-map tests for expand_dict_traced (design 2026-07-16 §5.3)."""

from lab_devices.experiment.expand import expand_dict, expand_dict_traced


def test_traced_output_matches_untraced():
    wf = {
        "schema_version": 1,
        "blocks": [{"for_each": {"var": "t", "in": [1, 2], "body": [{"wait": {"duration": "1s"}}]}}],
    }
    expanded, _ = expand_dict_traced(wf)
    assert expanded == expand_dict(wf)


def test_for_each_copies_all_trace_to_the_one_authored_body_block():
    wf = {
        "schema_version": 1,
        "blocks": [
            {"for_each": {"var": "t", "in": [1, 2, 3], "body": [{"wait": {"duration": "{t}s"}}]}}
        ],
    }
    expanded, trace = expand_dict_traced(wf)
    assert len(expanded["blocks"]) == 3
    for i in range(3):
        assert trace[f"blocks[{i}]"] == "blocks[0].body[0]"


def test_blocks_after_a_splice_trace_to_their_shifted_authored_index():
    wf = {
        "schema_version": 1,
        "blocks": [
            {"for_each": {"var": "t", "in": [1, 2], "body": [{"wait": {"duration": "{t}s"}}]}},
            {"wait": {"duration": "9s"}},
        ],
    }
    expanded, trace = expand_dict_traced(wf)
    assert len(expanded["blocks"]) == 3
    # The trailing wait is authored blocks[1] but lands at expanded blocks[2].
    assert trace["blocks[2]"] == "blocks[1]"


def test_container_children_trace_through():
    wf = {
        "schema_version": 1,
        "blocks": [
            {
                "parallel": {
                    "children": [
                        {"for_each": {"var": "t", "in": [1, 2], "body": [{"wait": {"duration": "{t}s"}}]}}
                    ]
                }
            }
        ],
    }
    expanded, trace = expand_dict_traced(wf)
    lanes = expanded["blocks"][0]["parallel"]["children"]
    assert len(lanes) == 2  # sole child of a parallel -> N lanes
    assert trace["blocks[0]"] == "blocks[0]"
    for i in range(2):
        assert trace[f"blocks[0].children[{i}]"] == "blocks[0].children[0].body[0]"


def test_parametrized_group_ref_body_traces_into_the_groups_dict():
    wf = {
        "schema_version": 1,
        "groups": {"service": {"params": ["tube"], "body": [{"wait": {"duration": "{tube}s"}}]}},
        "blocks": [{"group_ref": {"name": "service", "args": {"tube": 1}}}],
    }
    expanded, trace = expand_dict_traced(wf)
    # A parametrized group_ref inlines as a single Serial carrying the ref's block-level keys.
    assert "serial" in expanded["blocks"][0]
    assert trace["blocks[0]"] == "blocks[0]"
    assert trace["blocks[0].children[0]"] == "groups['service'].body[0]"


def test_nested_for_each_inside_a_parametrized_group_traces_to_the_group_body():
    wf = {
        "schema_version": 1,
        "groups": {
            "svc": {
                "params": ["tube"],
                "body": [{"for_each": {"var": "i", "in": [1, 2], "body": [{"wait": {"duration": "{i}s"}}]}}],
            }
        },
        "blocks": [{"group_ref": {"name": "svc", "args": {"tube": 1}}}],
    }
    expanded, trace = expand_dict_traced(wf)
    kids = expanded["blocks"][0]["serial"]["children"]
    assert len(kids) == 2
    for i in range(2):
        assert trace[f"blocks[0].children[{i}]"] == "groups['svc'].body[0].body[0]"


def test_plain_group_body_indices_shift_when_a_for_each_inside_it_splices():
    wf = {
        "schema_version": 1,
        "groups": {
            "wash": {
                "body": [
                    {"for_each": {"var": "i", "in": [1, 2], "body": [{"wait": {"duration": "{i}s"}}]}},
                    {"wait": {"duration": "9s"}},
                ]
            }
        },
        "blocks": [{"group_ref": {"name": "wash"}}],
    }
    expanded, trace = expand_dict_traced(wf)
    # A plain (param-less) group_ref is preserved for lazy inlining, but its body IS expanded.
    assert "group_ref" in expanded["blocks"][0]
    assert len(expanded["groups"]["wash"]["body"]) == 3
    assert trace["groups['wash'].body[2]"] == "groups['wash'].body[1]"


def test_a_macro_free_workflow_traces_every_block_to_itself():
    wf = {
        "schema_version": 1,
        "blocks": [{"serial": {"children": [{"wait": {"duration": "1s"}}]}}],
    }
    _, trace = expand_dict_traced(wf)
    assert trace["blocks[0]"] == "blocks[0]"
    assert trace["blocks[0].children[0]"] == "blocks[0].children[0]"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_experiment_expand_trace.py -q`
Expected: FAIL — `ImportError: cannot import name 'expand_dict_traced'`.

- [ ] **Step 3: Implement the trace**

Thread two path prefixes and a trace dict through the existing single walk. **No second pass, and do not stamp provenance into the JSON** — `workflow_from_dict` would reject an unknown key.

The threading rule: `_expand_blocks` knows each output block's expanded index as it splices; `_expand_block` knows the authored path it came from. So `_expand_blocks` passes `src` (authored list prefix), `dst` (expanded list prefix) and `base` (the index its first output lands at).

Add a trace carrier beside the existing `_Counter`, and give the four walk functions the new parameters. Concretely:

```python
def _expand_blocks(
    blocks: list[Any],
    groups: dict[str, Any],
    counter: _Counter,
    depth: int,
    trace: dict[str, str],
    src: str,
    dst: str,
    base: int = 0,
) -> list[Any]:
    out: list[Any] = []
    for i, block in enumerate(blocks):
        out.extend(
            _expand_block(block, groups, counter, depth, trace, f"{src}[{i}]", dst, base + len(out))
        )
    return out


def _expand_block(
    block: Any,
    groups: dict[str, Any],
    counter: _Counter,
    depth: int,
    trace: dict[str, str],
    src: str,
    dst: str,
    base: int,
) -> list[Any]:
    if depth > _MAX_DEPTH:
        raise WorkflowLoadError("for_each/group expansion nested too deeply (recursion?)")
    key = _type_key(block)
    if key is None:
        trace[f"{dst}[{base}]"] = src
        return [block]  # malformed; workflow_from_dict reports it
    if key == "for_each":
        return _expand_for_each(block, groups, counter, depth, trace, src, dst, base)
    if key == "group_ref":
        return _expand_group_ref(block, groups, counter, depth, trace, src, dst, base)
    trace[f"{dst}[{base}]"] = src
    body = block[key]
    if isinstance(body, dict):
        for child_key in _CHILD_LISTS.get(key, ()):
            children = body.get(child_key)
            if isinstance(children, list):
                body[child_key] = _expand_blocks(
                    children, groups, counter, depth, trace,
                    f"{src}.{child_key}", f"{dst}[{base}].{child_key}",
                )
    return [block]
```

`_expand_for_each` keeps its existing validation and `_envs` logic; only the recursion changes — every copy of the template comes from the **authored** `{src}.body`, and the copies land in the **enclosing** list at `dst`, continuing from `base`:

```python
    out: list[Any] = []
    for env in _envs(body):
        substituted = [_substitute(b, env) for b in tmpl]
        out.extend(
            _expand_blocks(
                substituted, groups, counter, depth + 1, trace,
                f"{src}.body", dst, base + len(out),
            )
        )
    counter.bump(len(out))
    return out
```

`_expand_group_ref` keeps its existing validation. The plain (param-less) early-returns record the ref itself; the inlined case records the wrapper at `dst[base]` and traces the inlined body **into the groups dict**:

```python
    if not params and not args:
        trace[f"{dst}[{base}]"] = src
        return [block]  # plain group_ref: preserve the node (lazy inline)
    ...
    substituted = [_substitute(b, dict(args)) for b in group_body]
    trace[f"{dst}[{base}]"] = src
    inlined = _expand_blocks(
        substituted, groups, counter, depth + 1, trace,
        f"groups[{name!r}].body", f"{dst}[{base}].children",
    )
    wrapper: dict[str, Any] = {"serial": {"children": inlined}}
```

(The `group is None` early-return at the top of the non-plain path raises, so it needs no trace entry.)

Then split `expand_dict`:

```python
def expand_dict(workflow_dict: dict[str, Any]) -> dict[str, Any]:
    """Splice for_each, inline parametrized group_refs, interpolate holes. Pure JSON."""
    return expand_dict_traced(workflow_dict)[0]


def expand_dict_traced(workflow_dict: dict[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
    """expand_dict plus a source map: expanded structural path -> authored structural path.

    Studio validates the EXPANDED workflow, so its diagnostics carry expanded indices that do
    not match the authored tree; the map is what lets the builder resolve a diagnostic back to
    the block the author can actually edit (design 2026-07-16 §5.3). Many-to-one by nature:
    every for_each copy traces to the one authored body block.
    """
```

Move the existing `expand_dict` body into `expand_dict_traced`, adding `trace: dict[str, str] = {}` and passing `trace`, `src`, `dst` at both call sites — the plain-group-body loop uses `src = dst = f"groups[{name!r}].body"`, and the top-level blocks use `src = dst = "blocks"`. Return `(out, trace)`.

Note the plain-group-body loop currently iterates `groups.values()`; it needs the **name** for the path, so iterate `groups.items()`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_experiment_expand_trace.py -q`
Expected: PASS (8 tests).

Then prove behaviour preservation — this is the load-bearing check:

Run: `.venv/bin/python -m pytest -q`
Expected: the full engine suite (722+) still passes. **If any pre-existing expansion test fails, you changed what `expand_dict` produces — that is a defect, not an acceptable diff.**

- [ ] **Step 5: Commit**

```bash
git add src/lab_devices/experiment/expand.py tests/test_experiment_expand_trace.py
git commit -m "feat(experiment): expand_dict_traced emits an expanded->authored source map"
```

---

### Task 2: `docs_store` remaps diagnostics to authored paths

**Files:**
- Modify: `webapp/backend/experiment_studio/docs_store.py:22`, `:160-185` (`validate_doc`)
- Test: `webapp/backend/tests/test_docs_store.py` (or the existing validate test module — follow whichever already covers `validate_doc`)

**Interfaces:**
- Consumes: `expand_dict_traced` (Task 1).
- Produces: `validate_doc` returning diagnostics whose structural paths are **authored** paths.

**Context.** `validate_doc` runs `role_diagnostics` → `expand_dict` → `roles_mod.substitute` → `workflow_from_dict` → `validate`. Everything downstream of the expand walks the **expanded** doc, so both the `substitute` role diagnostics and the `validate` diagnostics carry expanded paths. Both get remapped.

A diagnostic path is a **structural prefix plus an optional context suffix**: `blocks[0].body[3] alarm if`, `blocks[2] param 'volume_ml'`, `blocks[1] compute value`. Remap the **prefix only** and re-attach the suffix untouched. An unmapped path passes through unchanged rather than being dropped — a path we cannot map is still better than no path.

- [ ] **Step 1: Write the failing test**

Read the existing `validate_doc` tests first and match their fixture style. Add:

```python
def test_a_diagnostic_inside_a_for_each_body_reports_the_authored_path():
    doc = ExperimentDoc.model_validate(
        {
            "doc_version": 1,
            "name": "macro",
            "description": None,
            "roles": {"od_meter": {"type": "densitometer"}},
            "workflow": {
                "schema_version": 1,
                "metadata": {"name": "macro"},
                "streams": {"od_1": {"units": None}, "od_2": {"units": None}},
                "blocks": [
                    {
                        "for_each": {
                            "var": "t",
                            "in": [1, 2],
                            "body": [
                                {"measure": {"device": "od_meter", "verb": "measure", "into": "od_{t}"}},
                                # `nope` is not a declared stream, binding, or function -> one
                                # diagnostic per COPY at expanded blocks[1] and blocks[3], both
                                # authored at blocks[0].body[1].
                                {"branch": {"if": "nope > 1", "then": []}},
                            ],
                        }
                    }
                ],
            },
        }
    )
    diags = validate_doc(doc)
    assert diags, "expected the bad expression to produce a diagnostic"
    paths = {d["path"] for d in diags}
    # Authored, not expanded: every copy points at the one block the author can edit.
    assert paths == {"blocks[0].body[1] branch if"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd webapp/backend && .venv/bin/python -m pytest tests/ -q -k authored_path`
Expected: FAIL — the paths come back as expanded indices (`blocks[1] branch if`, `blocks[3] branch if`).

- [ ] **Step 3: Implement**

Change the import at `docs_store.py:22` to `from lab_devices.experiment.expand import expand_dict_traced`, and add a module-level helper plus the rewrite in `validate_doc`:

```python
# A diagnostic path is a structural prefix plus an optional context suffix the validator
# appends (" branch if", " param 'x'", " compute value"). Only the prefix is a path; the
# suffix is prose. Split on the first space — no structural token contains one.
def _remap(path: str, trace: dict[str, str]) -> str:
    prefix, sep, suffix = path.partition(" ")
    mapped = trace.get(prefix)
    if mapped is None:
        return path  # unmappable: a raw path beats no path (design §5.3)
    return mapped + sep + suffix
```

In `validate_doc`, take the trace from the expand, and route every diagnostic list produced downstream of it through `_remap`. The `role_diagnostics` call happens **before** the expand and its paths are `roles['x']` — leave those alone.

Deduplicate after remapping: `for_each` makes N copies of one authored block, so N identical diagnostics collapse to one. Preserve order (first occurrence wins) — the existing tests assert on diagnostic order in places.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd webapp/backend && .venv/bin/python -m pytest -q && .venv/bin/python -m mypy && .venv/bin/python -m ruff check .`
Expected: all pass, 148+ tests.

- [ ] **Step 5: Commit**

```bash
git add webapp/backend/experiment_studio/docs_store.py webapp/backend/tests/
git commit -m "feat(studio-backend): report diagnostics at authored paths, not expanded ones"
```

---

### Task 3: Doc types and tree nodes for `for_each` and `group_ref`

**Files:**
- Modify: `webapp/frontend/src/types/doc.ts:55-57` (`GroupRefBody`), `:89-97` (`WorkflowJson`), `BlockJson`
- Modify: `webapp/frontend/src/builder/tree.ts` — node interfaces, union, `childSlots`, `replaceSlot`, `newPaletteNode`
- Test: `webapp/frontend/src/builder/tree.test.ts`

**Interfaces:**
- Produces:
  - `types/doc.ts`: `GroupRefBody {name: string; args?: Record<string, ParamValue>}` (**`args` is missing today** — engine `blocks.py:91` has it); `ForEachBody {var?: string; in: Array<ParamValue | Record<string, ParamValue>>; body: BlockJson[]}`; `GroupJson {params?: string[]; body: BlockJson[]}`; `WorkflowJson.groups?: Record<string, GroupJson>` (was `Record<string, unknown>`); `BlockJson` gains `for_each?: ForEachBody`.
  - `tree.ts`: `ForEachNode {kind:'for_each'; var: string | null; items: Array<ParamValue | Record<string, ParamValue>>; body: BlockNode[]}`; `GroupRefNode {kind:'group_ref'; name: string; args: Record<string, ParamValue>}`; both on the `BlockNode` union. `ControlKind` unchanged; add `RepeatKind = 'for_each' | 'group_ref'` and widen `PaletteKind`.
  - `childSlots` gains `case 'for_each': return [['body', node.body]]`; `replaceSlot` handles it.

**Context.** The JSON key is `in`; the node field is `items` — `in` is a reserved word in JS and unusable as a plain property in some positions, and `convert.ts` is already the single translation point for exactly this kind of mismatch (`branch.if` ↔ `condition`, `abort.if` ↔ `condition`).

Once `childSlots`/`replaceSlot` know the `body` slot, drag/drop, `findNode`, `duplicateNode`, `withFreshUids`, `moveNode`, and undo all work with **no further change** — that is the whole reason `for_each` is modelled as an ordinary container.

- [ ] **Step 1: Write the failing test**

```ts
it('gives for_each a body child slot so the tree ops reach into it', () => {
  const node = newPaletteNode('for_each') as ForEachNode
  expect(node.kind).toBe('for_each')
  expect(node.var).toBe('tube')
  expect(node.items).toEqual([1, 2, 3])
  expect(childSlots(node).map(([slot]) => slot)).toEqual(['body'])
  const wait = newPaletteNode('wait')
  const withChild = replaceSlot(node, 'body', [wait]) as ForEachNode
  expect(withChild.body).toEqual([wait])
  expect(findNode([withChild], wait.uid)).toBe(wait)
})

it('creates a group_ref with no child slots', () => {
  const node = newPaletteNode('group_ref')
  expect(node.kind).toBe('group_ref')
  expect(node).toMatchObject({ name: '', args: {} })
  expect(childSlots(node)).toEqual([])
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd webapp/frontend && npm test -- --run tree`
Expected: FAIL — `newPaletteNode` rejects `'for_each'`.

- [ ] **Step 3: Implement**

Add to `types/doc.ts` (near `GroupRefBody`):

```ts
/** for_each is a SPLICING macro: it copies `body` once per item and splices the copies into the
 * ENCLOSING list, so mode is inherited — sole child of a parallel becomes N lanes; inside a
 * serial, an N-step sequence (engine design 2026-07-15 §2). The JSON key is `in`; the node
 * field is `items` (convert.ts translates, as it already does for branch.if <-> condition). */
export interface ForEachBody {
  var?: string
  in: Array<ParamValue | Record<string, ParamValue>>
  body: BlockJson[]
}

export interface GroupJson {
  params?: string[]
  body: BlockJson[]
}
```

Extend `GroupRefBody` with `args?: Record<string, ParamValue>`, add `for_each?: ForEachBody` to `BlockJson`, and retype `WorkflowJson.groups` to `Record<string, GroupJson>`.

In `tree.ts`, add the two node interfaces, extend the union, add `RepeatKind`/widen `PaletteKind`, add the `childSlots` and `replaceSlot` arms, and add `newPaletteNode` cases:

```ts
    case 'for_each':
      // Seeded with a concrete example rather than blanks: an empty `in` is a load error
      // (expand.py:99 "for_each 'in' must be a non-empty list"), so a freshly-dragged empty
      // for_each would make the whole doc unsavable until filled.
      return { ...base, kind, var: 'tube', items: [1, 2, 3], body: [] }
    case 'group_ref':
      return { ...base, kind, name: '', args: {} }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd webapp/frontend && npm test -- --run tree`
Expected: PASS. Typecheck will be red until Task 4/5 make `convert.ts`/`summary.ts` exhaustive — expected, do not fix those here.

- [ ] **Step 5: Commit**

```bash
git add webapp/frontend/src/types/doc.ts webapp/frontend/src/builder/tree.ts webapp/frontend/src/builder/tree.test.ts
git commit -m "feat(studio-frontend): tree + doc types for for_each and group_ref"
```

---

### Task 4: `convert.ts` — `for_each`, `group_ref`, and `groups`

**Files:**
- Modify: `webapp/frontend/src/builder/convert.ts` — `DocContent`, `docToTree`, `blockToNode`, `treeToDoc`, `nodeToBlock`
- Test: `webapp/frontend/src/builder/convert.test.ts`

**Interfaces:**
- Consumes: Task 3's types.
- Produces: `DocContent` gains `groups: Record<string, {params: string[]; body: BlockNode[]}>`. `docToTree` no longer throws on `groups`/`for_each`/`group_ref`; `treeToDoc` emits `groups` (omitted entirely when empty, so a group-less doc round-trips byte-identically to today).

**Context.** `convert.ts:52-54` currently hard-rejects any doc with non-empty `groups`. That rejection is what makes `examples/morbidostat.json` unopenable. Removing it is the point of W9.

Emission rules still mirror the engine serializer: omit empty `params`/`args`, omit `var` when absent, omit `groups` when empty, `on_error` only when `'continue'`.

- [ ] **Step 1: Write the failing tests**

```ts
describe('repetition blocks', () => {
  const doc = (workflow: Partial<WorkflowJson>): ExperimentDocJson => ({
    doc_version: 1,
    name: 'macro',
    description: null,
    roles: {},
    workflow: {
      schema_version: 1,
      metadata: { name: 'macro' },
      persistence: { default: 'in_memory', format: 'jsonl' },
      streams: {},
      blocks: [],
      ...workflow,
    } as WorkflowJson,
  })

  it('round-trips a for_each with scalar items', () => {
    const input = doc({
      blocks: [{ for_each: { var: 'tube', in: [1, 2, 3], body: [{ wait: { duration: '{tube}s' } }] } }],
    })
    expect(JSON.stringify(treeToDoc(docToTree(input)))).toBe(JSON.stringify(input))
  })

  it('round-trips a for_each with object items and no var', () => {
    const input = doc({
      blocks: [{ for_each: { in: [{ tube: 1, port: 2 }], body: [{ wait: { duration: '{tube}s' } }] } }],
    })
    expect(JSON.stringify(treeToDoc(docToTree(input)))).toBe(JSON.stringify(input))
  })

  it('round-trips parametrized groups and a group_ref with args', () => {
    const input = doc({
      groups: { service: { params: ['tube'], body: [{ wait: { duration: '{tube}s' } }] } },
      blocks: [{ group_ref: { name: 'service', args: { tube: 1 } } }],
    })
    expect(JSON.stringify(treeToDoc(docToTree(input)))).toBe(JSON.stringify(input))
  })

  it('round-trips a plain param-less group_ref unchanged', () => {
    const input = doc({
      groups: { wash: { body: [{ wait: { duration: '1s' } }] } },
      blocks: [{ group_ref: { name: 'wash' } }],
    })
    expect(JSON.stringify(treeToDoc(docToTree(input)))).toBe(JSON.stringify(input))
  })

  it('parses a for_each into a node with a body slot', () => {
    const tree = docToTree(
      doc({ blocks: [{ for_each: { var: 't', in: [1], body: [{ wait: { duration: '1s' } }] } }] }),
    ).tree
    expect(tree[0]).toMatchObject({ kind: 'for_each', var: 't', items: [1] })
    expect((tree[0] as ForEachNode).body).toHaveLength(1)
  })

  it('omits groups entirely when the doc has none', () => {
    const out = treeToDoc(docToTree(doc({ blocks: [{ wait: { duration: '1s' } }] })))
    expect('groups' in out.workflow).toBe(false)
  })
})
```

**Also delete** the now-false pre-existing tests asserting `docToTree` throws for `for_each` and for non-empty `groups` — the behaviour they pin is exactly what this task changes. (Task 3 of W8 set the precedent: it deleted the equivalent `abort`/`alarm` tests.) Leave any test pinning an unknown block type's generic error.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd webapp/frontend && npm test -- --run convert`
Expected: FAIL — `DocConvertError: workflow groups are not supported in the builder (v2 backlog)`.

- [ ] **Step 3: Implement**

- Delete the `groups` guard at `convert.ts:52-54` and the `for_each`/`group_ref` throwing arms.
- `docToTree`: build `groups` from `wf.groups ?? {}`, mapping each `{params, body}` to `{params: params ?? [], body: body.map(blockToNode)}`.
- `blockToNode`: add
  ```ts
      case 'for_each': {
        const b = block.for_each as ForEachBody
        return { ...base, kind, var: b.var ?? null, items: [...b.in], body: (b.body ?? []).map(blockToNode) }
      }
      case 'group_ref': {
        const b = block.group_ref as GroupRefBody
        return { ...base, kind, name: b.name, args: { ...(b.args ?? {}) } }
      }
  ```
- `nodeToBlock`: add the mirrored arms — emit `var` only when non-null, `args` only when non-empty. The `never` guard (added in W8) stays and will now compile.
- `treeToDoc`: emit `workflow.groups` only when `Object.keys(content.groups).length > 0`; per group emit `params` only when non-empty. **Key order matters** — `groups` sits between `streams` and `blocks` in `WorkflowJson`; place the assignment so the emitted key order matches the engine serializer and the fixtures.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd webapp/frontend && npm test -- --run convert`
Expected: PASS, including the pre-existing golden and control-block fixture round-trips.

- [ ] **Step 5: Commit**

```bash
git add webapp/frontend/src/builder/convert.ts webapp/frontend/src/builder/convert.test.ts
git commit -m "feat(studio-frontend): convert for_each, group_ref and groups"
```

---

### Task 5: Canvas summaries and container rendering

**Files:**
- Modify: `webapp/frontend/src/builder/summary.ts`
- Modify: `webapp/frontend/src/builder/Canvas.tsx:62` (the container test), `:131-153` (`ContainerBody`)
- Test: `webapp/frontend/src/builder/summary.test.ts`

**Interfaces:**
- Produces: `blockSummary` arms for `for_each` and `group_ref`; `for_each` renders as a container with its body nested once.

**Context.** Spec §5.1/P4: **authored view only** — one card showing var + items with the body nested once, matching the engine's DRY-source model. No expansion preview.

Glyphs: `∀` for `for_each`, `⧉` for `group_ref`. **`∀` is deliberate: unlike `⟳`, it cannot be confused with the loop's `↻`** — `summary.ts:13-20` records that two near-identical arrows side by side were unreadable, which is why the retry marker became `R×N`.

- [ ] **Step 1: Write the failing test**

Reuse the module-scope `base` (**no `uid`**); do not redeclare it.

```ts
  it('summarises repetition blocks', () => {
    expect(
      blockSummary({ uid: 'u', kind: 'for_each', var: 'tube', items: [1, 2, 3], body: [], ...base }),
    ).toBe('∀ For each tube in [1, 2, 3]')
    expect(
      blockSummary({ uid: 'u', kind: 'for_each', var: null, items: [{ tube: 1 }, { tube: 2 }], body: [], ...base }),
    ).toBe('∀ For each of 2 items')
    expect(blockSummary({ uid: 'u', kind: 'group_ref', name: 'service', args: { tube: 1 }, ...base })).toBe(
      '⧉ service(tube=1)',
    )
    expect(blockSummary({ uid: 'u', kind: 'group_ref', name: 'wash', args: {}, ...base })).toBe('⧉ wash')
  })
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd webapp/frontend && npm test -- --run summary`
Expected: FAIL — `undefined` for the new kinds.

- [ ] **Step 3: Implement**

In `summary.ts`, reuse the existing `formatParams` helper for `group_ref` args (it already renders `k=v, …` and truncates at 2):

```ts
    case 'for_each':
      return (
        (node.var !== null
          ? `∀ For each ${node.var} in [${node.items.join(', ')}]`
          : `∀ For each of ${node.items.length} items`) + marker
      )
    case 'group_ref': {
      const args = formatParams(node.args)
      return `⧉ ${node.name || '?'}${args ? `(${args})` : ''}${marker}`
    }
```

In `Canvas.tsx`, add `'for_each'` to the container test at `:62` and give `ContainerBody` a `for_each` arm rendering its `body` list (mirror the `loop` arm — same single-slot shape).

- [ ] **Step 4: Run test to verify it passes**

Run: `cd webapp/frontend && npm test -- --run summary && npm run typecheck`
Expected: tests PASS; typecheck should now be clean (Tasks 3-5 together close the union).

- [ ] **Step 5: Commit**

```bash
git add webapp/frontend/src/builder/summary.ts webapp/frontend/src/builder/summary.test.ts webapp/frontend/src/builder/Canvas.tsx
git commit -m "feat(studio-frontend): render for_each as an authored container; group_ref card"
```

---

### Task 6: `docStore` — groups and the scope switcher

**Files:**
- Modify: `webapp/frontend/src/stores/docStore.ts`
- Test: `webapp/frontend/src/stores/docStore.test.ts`

**Interfaces:**
- Produces: `DocSnapshot` gains `groups: Record<string, {params: string[]; body: BlockNode[]}>`. `EditorState` gains `scope: string | null` (`null` = main workflow) and `setScope(name: string | null)`, `addGroup(name) => string | null`, `renameGroup(from, to) => string | null`, `removeGroup(name) => string | null`, `setGroupParams(name, params)`.
- Every existing block op (`insertBlock`, `moveBlock`, `removeBlock`, `duplicateBlock`, `patchBlock`) operates on **the active scope's** list.

**Context.** This is the task with real design content; read spec §5.2 before starting.

- `groups` and `tree` are both **document** fields → both belong in the zundo snapshot. `scope` is **view state** → it must **not** be, exactly like `selectedUid` (`docStore.ts:1-3` states the rule).
- Because `scope` is not snapshotted, undoing an edit made in another scope while viewing this one is possible. **The store switches scope to follow the undone edit** rather than applying it invisibly.
- **Deleting a group that a `group_ref` still cites is refused**, reusing the `countRoleRefs`/`countStreamRefs` pattern. The count must span the main tree **and every group body** (a group can call another group).
- Group names: reuse `ROLE_NAME_RE`-style validation — a group name is interpolated into `{holes}`, so it must be an identifier. Refuse duplicates.

- [ ] **Step 1: Write the failing tests**

Follow the file's existing store-test style (`store()` helper). Cover at minimum:

```ts
it('inserts blocks into the active scope, not the main tree', () => { /* addGroup, setScope, insertBlock, assert groups.svc.body has it and tree does not */ })
it('refuses to delete a group a group_ref still cites', () => { /* assert removeGroup returns an error string and the group survives */ })
it('allows deleting a group once its last group_ref is gone', () => {})
it('counts group_refs inside OTHER group bodies, not just the main tree', () => {})
it('refuses a duplicate or non-identifier group name', () => {})
it('keeps scope out of the undo snapshot', () => { /* edit in a group, setScope back to main, undo, assert the group edit reverted */ })
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd webapp/frontend && npm test -- --run docStore`
Expected: FAIL — `addGroup`/`setScope` are not functions.

- [ ] **Step 3: Implement**

Add `countGroupRefs(tree: BlockNode[], name: string): number` to `refs.ts` (pure, testable — put its test in `refs.test.ts`), and have `removeGroup` sum it across the main tree and all group bodies.

Refactor the block ops to read/write the active list via one private helper rather than duplicating the scope check five times — e.g. `activeList(state)` / `setActiveList(state, list)`. Keep the existing in-place-mutability + rev-counter contract (W5-settled).

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd webapp/frontend && npm test -- --run docStore && npm test -- --run refs && npm run typecheck`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add webapp/frontend/src/stores/docStore.ts webapp/frontend/src/stores/docStore.test.ts webapp/frontend/src/builder/refs.ts webapp/frontend/src/builder/refs.test.ts
git commit -m "feat(studio-frontend): groups in the doc store + an editing scope"
```

---

### Task 7: Scope switcher UI, palette chips, Inspector forms

**Files:**
- Modify: `webapp/frontend/src/builder/Canvas.tsx` (scope selector header), `Palette.tsx` (Repeat chips + a Groups section), `Inspector.tsx` (`ForEachForm`, `GroupRefForm`, group params), `BuilderTab.tsx` (`STRUCTURE_TITLES`), `dnd.ts` (payload)
- Test: none new (React glue — the W3-W8 convention; Task 9 verifies in a real browser)

**Interfaces:**
- Consumes: Task 6's store API.
- Produces: the scope selector; `∀ For each` and `⧉ Group ref` palette chips; Inspector forms.

**Context.**

- Scope selector (spec §5.2), rendered above the canvas:
  ```
  Editing: [ Main workflow ▾ ]   ├ Main workflow   ├ service(tube)   └ + New group…
  ```
- **`ForEachForm` must NOT render `retry`, `on_error`, `gap_after`, or `start_offset`.** `expand.py:26` `_FOR_EACH_FORBIDDEN` rejects all four (`"for_each may not carry block-level {k!r}; put it on the body blocks"`) — the macro is a splice, so there is no single runtime block for such a key to attach to. `label` **is** allowed. In `BlockForm`, this means the Timing & label section's `gapAfter`/`startOffset` rows and the On-error row all need the same suppression the `abort` case already has.
- `items` are edited as a JSON array in a `TextAreaField`, validated client-side against the engine's rules (`expand.py:95-118`): non-empty list; all scalars when `var` is set; all objects sharing one key set when it is not. This is a **fast-feedback mirror, not a second opinion** — the backend stays authoritative, so on ambiguity, accept and let the diagnostic speak.
- `GroupRefForm`: `name` is a picker over declared groups; `args` are the keys of that group's `params` (so the arity is right by construction — `expand.py:190` rejects a mismatch).

- [ ] **Step 1: Widen the palette**

Add `RepeatKind` chips to `Palette.tsx` under a **Repeat** section (`∀ For each`, `⧉ Group ref`), reusing `Chip` and the existing `palette-structure` payload source. Extend `STRUCTURE_TITLES` in `BuilderTab.tsx` with `for_each: 'For each'`, `group_ref: 'Group ref'`.

- [ ] **Step 2: Add the scope selector**

Render it in `Canvas.tsx` above the block list, driven by `scope`/`setScope`/`addGroup` from the store. Selecting a group swaps the rendered list; `+ New group…` prompts for a name and reports `addGroup`'s error string inline (the `AddRoleForm` pattern in `Palette.tsx:55-97` is the precedent).

- [ ] **Step 3: Add the Inspector forms**

`KIND_TITLES` gains `for_each: 'For each'`, `group_ref: 'Group ref'`. `KindBody` gains both arms. Suppress the four forbidden block-level rows for `for_each`.

- [ ] **Step 4: Run the gate**

Run: `cd webapp/frontend && npm run lint && npm run typecheck && npm test -- --run`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add webapp/frontend/src/builder/
git commit -m "feat(studio-frontend): scope switcher, repeat chips, for_each/group_ref forms"
```

---

### Task 8: `paths.ts` — scope resolution and the context suffix

**Files:**
- Modify: `webapp/frontend/src/builder/paths.ts`
- Modify: `webapp/frontend/src/builder/ProblemsPanel.tsx` (click-through), `RolesPanel.tsx` (role focus)
- Test: `webapp/frontend/src/builder/paths.test.ts`

**Interfaces:**
- Produces: `ResolvedPath` gains `scope: string | null`. `resolveDiagnosticPath(tree, groups, path)` — signature widens to take the groups map.

**Context — two distinct bugs, both fixed here (spec §5.4).**

1. **Group-scope paths never resolved.** The backend emits `groups['service'].body[0]` (`validate.py:63-64`, `roles.py:71`), but the regex at `paths.ts:29` only accepts a `blocks[i]` prefix. With Task 2's source map, a diagnostic on a parametrized group's body now legitimately reports that form — so it must resolve, and clicking it must switch scope.
2. **Context-suffixed paths never resolved** (found by W8's final whole-branch review; **pre-existing on `main`**). The validator appends a context suffix to expression diagnostics — `blocks[0] compute value`, `blocks[4].body[3] alarm if`, `blocks[0] branch if` — but the regex only strips a ` param 'x'` suffix, so all of these resolve to `uid: null`: the Problems row's button is disabled (`ProblemsPanel.tsx:32`) and the canvas card gets no highlight. **Fix: strip any trailing context suffix, not just ` param`.** Keep extracting `param` specifically where present, since `MappedDiagnostic.param` is consumed.

Also: `MappedDiagnostic.role` is written today and **read by nothing** — role diagnostics land unclickable. Wire it to focus the offending role in `RolesPanel`, since this file is being rewritten anyway.

**Carried forward from Task 2's review (compound `->` paths).** A diagnostic path may be compound: `blocks[0].body[0]->mygroup.body[0] compute value`, or even doubly so: `blocks[0]->g1.body[0]->g2.body[0] compute value`. This arises whenever a validate-phase walk crosses from a `group_ref` call site into a **plain** (non-parametrized) group's body (`validate.py:894`, `:940`). `_remap` (Task 2) now remaps **every** `->`-separated segment, not just the call-site head — a plain group's body is expanded **in place** (`expand.py:270-274`), so an index inside it (e.g. from a `for_each` living directly in the group's own body) is an expanded index too, and needs the same trace lookup the head gets. The **authored, editable** location for such a diagnostic is **inside the (innermost) group definition** — i.e. it should resolve to the group's body and switch the canvas to that group's scope, which is where the author can actually fix it. The call-site prefix before the first `->` is context, not the edit target.

**Important for the parser: a compound path's group segments name the group BARE, not `groups['name']`-wrapped.** `_remap_group_segment` (Task 2) preserves the bare spelling `validate.py:894`/`:940` already uses — it maps only the `.body[i]` suffix of each segment, translating into the trace's `groups['name'].body[i]` key form internally and back out to `name.body[i]` bare. So the emitted path looks like `blocks[0]->g1.body[0]` or `blocks[0]->g1.body[0]->g2.body[0]` (bare `g1`, `g2`), **never** `blocks[0]->groups['g1'].body[0]`. This is distinct from point 1 above, where a **direct** (non-compound) group-scope diagnostic — no `->` involved — is emitted in the `groups['name'].body[i]` form. `paths.ts` must therefore handle two different group-name spellings depending on position: `groups['name']`-wrapped when the path starts there, bare `name` after a `->`. When resolving a compound path to a scope, translate each bare `->name.body[i]` segment into that group's scope rather than reusing the `groups[...]` regex used for point 1 — and for a multi-segment path, the scope that matters is the **last** (innermost) segment's group, since that is where the diagnostic's editable location lives. This is a **third, independent** parsing requirement on `resolveDiagnosticPath` alongside the quote-style caveat below (Task 1's review) — a single path may need a `->` split, a bare-vs-`groups[...]` spelling switch per segment, and a quote-tolerant `groups[...]` match where that form does appear.

**Caveat from Task 1's review: group-name quoting is data-dependent.** The `groups['name'].body[i]` prefix is built with `f"groups[{name!r}].body"` (`expand.py`, and identically in `validate.py:64` and `roles.py:71` — same expression, so all three agree by construction). Python's `repr()` picks the quote style per string: `repr("x")` gives `groups['x']` (single quotes), but `repr("o'brien")` gives `groups["o'brien"]` (Python flips to double quotes when the string contains a single quote and no double quote). The `paths.ts` parser must accept **both** `groups['name']` and `groups["name"]` — a group name containing an apostrophe is a realistic authored value, not just a theoretical edge case.

- [ ] **Step 1: Write the failing tests**

```ts
it('resolves a context-suffixed expression path onto the block', () => {
  // Pre-existing gap: only " param 'x'" was stripped, so these all returned uid null.
  for (const suffix of ['compute value', 'branch if', 'alarm if', 'record value', 'loop until']) {
    expect(resolveDiagnosticPath(tree, {}, `blocks[0] ${suffix}`).uid).toBe(tree[0].uid)
  }
})

it('still extracts the param name from a param path', () => {
  const r = resolveDiagnosticPath(tree, {}, "blocks[0] param 'volume_ml'")
  expect(r).toMatchObject({ uid: tree[0].uid, param: 'volume_ml' })
})

it('resolves a group body path to the group scope', () => {
  const groups = { service: { params: ['tube'], body: [waitNode] } }
  expect(resolveDiagnosticPath([], groups, "groups['service'].body[0]")).toMatchObject({
    uid: waitNode.uid,
    scope: 'service',
  })
})

it('resolves a for_each body path through the body slot', () => {
  // childSlots now returns for_each's body, so no path logic changes — this pins it.
  expect(resolveDiagnosticPath([forEachNode], {}, 'blocks[0].body[0]').uid).toBe(innerNode.uid)
})

it('returns uid null for an out-of-range index rather than the wrong block', () => {
  expect(resolveDiagnosticPath(tree, {}, 'blocks[99]').uid).toBeNull()
})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd webapp/frontend && npm test -- --run paths`
Expected: FAIL — context-suffixed paths return `uid: null`; the groups argument does not exist.

- [ ] **Step 3: Implement**

Split the suffix off first, then match the structural prefix; resolve a `groups['name'].body` prefix against `groups[name].body` with `scope: name`, and `blocks` against the main tree with `scope: null`. Everything below the first token already works via `childSlots`, which Task 3 taught about `for_each`.

Update `mapDiagnostics`' callers to pass `groups`, and make `ProblemsPanel`'s row click `setScope(d.scope)` before selecting the uid.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd webapp/frontend && npm test -- --run paths && npm run typecheck && npm test -- --run`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add webapp/frontend/src/builder/paths.ts webapp/frontend/src/builder/paths.test.ts webapp/frontend/src/builder/ProblemsPanel.tsx webapp/frontend/src/builder/RolesPanel.tsx
git commit -m "feat(studio-frontend): resolve group-scope and context-suffixed diagnostic paths"
```

---

### Task 9: The morbidostat opens — acceptance

**Files:**
- Test: `webapp/frontend/src/builder/convert.test.ts`
- Test: `webapp/backend/tests/` (validate pin, mirroring `valid-control-blocks.json`'s)

**Interfaces:**
- Consumes: everything above.
- Produces: the W9 acceptance test.

**Context.** This is spec §8's W9 acceptance and the reason the increment exists: `examples/morbidostat.json` uses `groups` **and** `for_each`, and has never been openable in the builder. Since W7 it imports, saves, lists, runs, and charts while `docToTree` throws — rendered as an **emerald note, never a red error** (the W7 §7 contract). After W9 it opens, and that note disappears for this doc while the mechanism stays for genuinely unopenable ones.

- [ ] **Step 1: Write the test**

```ts
it('opens examples/morbidostat.json and round-trips it byte-for-byte', () => {
  // The W9 acceptance (spec §8): the flagship uses groups + for_each and has never been
  // openable in the builder. Byte comparison, not toEqual — deep-equal is blind to key order
  // and to 6.0 vs 6 (the W7 trap; morbidostat.json carries 11 such literals).
  const input = JSON.parse(
    readFileSync(new URL('../../../../examples/morbidostat.json', import.meta.url), 'utf8'),
  ) as ExperimentDocJson
  const content = docToTree(input)
  expect(Object.keys(content.groups)).toContain('service')
  expect(JSON.stringify(treeToDoc(content))).toBe(JSON.stringify(input))
})
```

Check the relative path resolves from `webapp/frontend/src/builder/` to `examples/` and correct it if not.

- [ ] **Step 2: Run it**

Run: `cd webapp/frontend && npm test -- --run convert`

**If the byte comparison fails, read the diff before touching anything.** A `6.0` → `6` normalisation is **JavaScript's number model** (`JSON.parse` collapses them) and is semantically nil — the engine's `"number"` kind passes `int|float` through with no coercion (`execute.py:144`). If that is the only difference, the honest fix is to assert against a JS-normalised baseline (`JSON.stringify(JSON.parse(raw))`) and **say so in a comment**, rather than to pretend byte-identity that JavaScript cannot deliver. A **key-order** difference is a real defect in `treeToDoc` — fix the emission order.

- [ ] **Step 3: Add the backend validate pin**

Mirror the `valid-control-blocks.json` pin added in W8 (`webapp/backend/tests/test_validate_api.py`): assert `examples/morbidostat.json` validates with zero diagnostics through `validate_doc`. This pins the source map's behaviour on the real flagship, not just on synthetic fixtures.

- [ ] **Step 4: Run both gates**

Run: `cd webapp/frontend && npm run lint && npm run typecheck && npm test -- --run && npm run build`
Run: `cd webapp/backend && .venv/bin/python -m pytest -q && .venv/bin/python -m mypy && .venv/bin/python -m ruff check .`
Run: `.venv/bin/python -m pytest -q && .venv/bin/python -m mypy && .venv/bin/python -m ruff check .` (engine, from the repo root)

- [ ] **Step 5: Commit**

```bash
git add webapp/frontend/src/builder/convert.test.ts webapp/backend/tests/
git commit -m "test(studio): the morbidostat example opens in the builder (W9 acceptance)"
```

---

### Task 10: Real-browser verification

**Files:** scratchpad only — commit nothing.

**Context.** The W5 recipe: `webapp/backend/tests/devserver.py` + `npm run dev`, seed via `POST /api/experiments`, drive with a scratchpad playwright script. After `page.reload()` the app lands on the **Devices** tab.

- [ ] **Step 1: Seed and open `examples/morbidostat.json`**

- [ ] **Step 2: Verify — report each PASS/FAIL with the actual text observed**

- It **opens** — no `DocConvertError` note (it never has before).
- The scope selector lists **Main workflow** and **service(tube)**; selecting `service(tube)` renders the group body.
- A `for_each` renders as `∀ For each tube in [1, 2, 3]` with its body nested **once** (not expanded).
- A `group_ref` renders as `⧉ service(tube=1)`.
- Selecting a `for_each` shows **no** On-error / Gap-after / Start-offset rows.
- **The source map end to end:** break an expression **inside the `service` group body** (e.g. change a `compute` value to `nope > 1`), save, and confirm the Problems panel row **clicks through to the offending block in the `service` scope** — not to an unrelated block in the main tree, and not to a disabled row. This is the single most valuable check in the task; it is what P3 bought.
- Save, reload, reopen: unchanged.

- [ ] **Step 3: Screenshot both scopes; report paths. Kill the servers. Confirm `git status` clean.**

---

### Task 11: Preprod real-hardware validation

**Context.** Per spec §9 and the W8 precedent (`.superpowers/sdd/preprod-w8-report.md` — read it first; it records the approach and the traps).

**The rig:** `ssh khamit@111.88.145.138`, drive one script through `docker exec -i lab-bridge-jupyter-1 python -`. Roster: `densitometer_1..3`, `pump_1..3`, `valve_1..3` on `windows_arm64_test_client`.

**Approach note from W8:** `lab-bridge-studio-1` is pinned at `experiment-studio:0.3.0`, whose bundled library predates these blocks; **do not repin or redeploy it for a frontend PR.** W8 upgraded `lab-bridge-jupyter-1`'s `lab_devices` to 0.6.0 and drove the engine directly. **W9 differs: it changes the engine** (`expand_dict_traced`), so install the branch's engine into jupyter rather than released 0.6.0.

- [ ] **Step 1: Prove W9's engine change is behaviour-preserving on real hardware**

Run the existing `examples/morbidostat-demo-speed.json` (or the Increment-7 purpose-built `for_each`+`step(tube)` doc — see the ledger) against the real rig with the branch's engine. It must behave exactly as Increment 7 recorded: the `service` group inlines, `for_each`-in-parallel drives three real densitometers concurrently, per-tube accumulators stay independent. **W9 adds a trace; it must not change what expansion produces.**

- [ ] **Step 2: Prove the source map on the real doc**

Call `expand_dict_traced` on `examples/morbidostat.json` and assert every trace value is a path that actually exists in the **authored** document, and that the `service` group's inlined blocks trace into `groups['service'].body[...]`.

- [ ] **Step 3: Report to `.superpowers/sdd/preprod-w9-report.md`**

Honest gaps carry forward: the sim densitometers read OD **0.0**, so dosing arms and contamination predicates cannot fire. Do not weaken anything to force them.

---

## Definition of done

- All 11 tasks committed.
- Engine gate green: `pytest`, `mypy src/lab_devices`, `ruff`, `awk 'length>100'`. **The existing 722+ engine tests must pass unchanged** — W9 adds a trace, it does not change expansion output.
- Backend and frontend gates green.
- **`examples/morbidostat.json` opens in the builder**, renders `service(tube)` in the scope switcher, round-trips, and a diagnostic in the group body clicks through to the authored block in the group scope (spec §8, W9 acceptance).
- Preprod validated per §9.
- **Squash-merge** — Tasks 3-4 leave typecheck transiently red, exactly as W8 did.
