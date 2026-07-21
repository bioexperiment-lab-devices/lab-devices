# Human-readable block names in the run log — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the raw `[blocks[i].children[j]]` suffix on each run-log line with the block's human-readable name — its user-typed `label` if set, else the derived `blockSummary` — on both the live run screen and the record viewer, correct for `for_each`/parametrized-group copies.

**Architecture:** The engine already builds an expanded→authored source map (`expand_dict_traced`'s `trace`) whose keys are exactly the `block_id`s `assign_block_ids` emits. Retain that trace at run time, and have `RunContext.emit` attach the authored path as a new first-class `RunEvent.source_path`. The frontend resolves that path against the authored doc tree (which it already renders as the record snapshot) via the existing `resolveDiagnosticPath` machinery, and derives the name from the resolved node. No new translation logic, no Python port of `blockSummary`.

**Tech Stack:** Python 3.11 (engine, `pytest`, `mypy --strict`), TypeScript/React + Zustand (webapp frontend, `vitest`, `tsc -b`, `oxlint`), FastAPI (webapp backend, `pytest`).

## Global Constraints

- **Engine `RunEvent` field order:** append `source_path` as the LAST dataclass field (after `data`, default `None`) so the ~9 existing 4-positional `RunEvent(ts, kind, block_id, data)` constructions in tests keep binding `data` correctly. `emit` passes `source_path` by keyword.
- **Wire order:** `run_event_to_dict` emits `source_path` right after `block_id` in the dict (readable jsonl / WS order), independent of dataclass field order.
- **`resolveDiagnosticPath` behavior is pinned** by `webapp/frontend/src/builder/paths.test.ts` (exact `.toEqual({uid,role,param,scope,field})`). Any refactor MUST keep every existing assertion green.
- **Frontend testing rule** (`webapp/frontend/CLAUDE.md`): vitest runs in node env — pure functions only, no component rendering/jsdom. DOM wiring (EventLog rendering) is verified by `npm run build` (typecheck) + the UI-audit probe (`npm run capture`), not vitest.
- **Icons/controls/colour rules** in `webapp/frontend/CLAUDE.md` apply, but this feature adds only muted text (`text-caption`) — no new icons, controls, or canvas colours.
- **Never blank:** the resolved name falls back label → summary → raw structural path, and finally the raw `block_id`. A log line never loses its block identifier.
- Commit after each task. One branch `feat/run-log-block-names`, one PR.

---

## File Structure

**Engine (`src/lab_devices/experiment/`)**
- `runlog.py` — `RunEvent` gains `source_path`.
- `persist.py` — `run_event_to_dict` + `CsvRunLogSink` serialize `source_path`.
- `expand.py` — new `expand_workflow_traced` (AST expansion + trace).
- `context.py` — `RunContext.source_map`; `emit` attaches `source_path`.
- `run.py` — expand-with-trace, pass `source_map` to `RunContext`.

**Frontend (`webapp/frontend/src/`)**
- `types/runs.ts` — `source_path` on `RunEventMsg` and `RecordEvent`.
- `builder/paths.ts` — extract `resolveStructuralNode`; add `resolveDiagnosticNode`.
- `run/blockName.ts` (new) — pure `blockName(event, tree, groups)`.
- `run/EventLog.tsx` — `LogEvent.source_path`; `nameFor` prop; render name.
- `records/RecordViewer.tsx` — build tree/groups from `detail.doc`, pass `nameFor`.
- `stores/runStore.ts` — stash `doc`; `RunView.tsx` — build tree/groups, pass `nameFor`.

**Tests**
- `tests/test_experiment_persist.py` (update), `tests/test_experiment_runlog_source_path.py` (new), `webapp/backend/tests/test_sinks.py` (update).
- `webapp/frontend/src/builder/paths.test.ts` (add cases), `webapp/frontend/src/run/blockName.test.ts` (new).

---

## Task 1: `source_path` on the engine event contract

**Files:**
- Modify: `src/lab_devices/experiment/runlog.py:9-16`
- Modify: `src/lab_devices/experiment/persist.py:26-33` (`run_event_to_dict`), `:121-133` (`CsvRunLogSink`)
- Test: `tests/test_experiment_persist.py`

**Interfaces:**
- Produces: `RunEvent(timestamp, kind, block_id=None, data={}, source_path=None)` (frozen dataclass, `source_path` last). `run_event_to_dict(event) -> {"timestamp", "kind", "block_id", "source_path", "data"}`.

- [ ] **Step 1: Update the persist round-trip test to expect `source_path`**

In `tests/test_experiment_persist.py`, find the assertion on `run_event_to_dict` output (around the `RunEvent(12.5, "measure_recorded", "blocks[0]", {...})` case) and add the key. Add a new assertion for a set `source_path`:

```python
def test_run_event_to_dict_includes_source_path():
    from lab_devices.experiment.runlog import RunEvent
    from lab_devices.experiment.persist import run_event_to_dict
    ev = RunEvent(12.5, "block_started", "blocks[3]", source_path="blocks[2].body[0]")
    assert run_event_to_dict(ev) == {
        "timestamp": 12.5,
        "kind": "block_started",
        "block_id": "blocks[3]",
        "source_path": "blocks[2].body[0]",
        "data": {},
    }
```

Also update any existing `run_event_to_dict` equality in this file to include `"source_path": None` (e.g. the `measure_recorded` case, which constructs `RunEvent(12.5, "measure_recorded", "blocks[0]", {"stream": "OD", "value": 0.5})` — with `source_path` appended last, that 4th positional still binds `data`, so the expected dict just gains `"source_path": None`).

- [ ] **Step 2: Run it to verify it fails**

Run: `pytest tests/test_experiment_persist.py -v`
Expected: FAIL — `TypeError: __init__() got an unexpected keyword argument 'source_path'` and/or dict-mismatch on the missing key.

- [ ] **Step 3: Add the field to `RunEvent`**

In `src/lab_devices/experiment/runlog.py`, append `source_path` as the last field (keeps 4-positional constructions valid):

```python
@dataclass(frozen=True)
class RunEvent:
    """One observable executor event; timestamps come from the run clock."""

    timestamp: float
    kind: str
    block_id: str | None = None
    data: dict[str, Any] = field(default_factory=dict)
    source_path: str | None = None  # authored structural path (engine source map); None off-block
```

- [ ] **Step 4: Serialize it in `run_event_to_dict` and the CSV sink**

In `src/lab_devices/experiment/persist.py`, `run_event_to_dict` (emit `source_path` right after `block_id`):

```python
def run_event_to_dict(event: RunEvent) -> dict[str, Any]:
    """Lossless dict form of a RunEvent for jsonl / the csv data column (design 5 §7)."""
    return {
        "timestamp": event.timestamp,
        "kind": event.kind,
        "block_id": event.block_id,
        "source_path": event.source_path,
        "data": event.data,
    }
```

And `CsvRunLogSink` (columns + row):

```python
class CsvRunLogSink(_CsvWriter):
    """Run log as csv; the event data dict is JSON-encoded into one column (design 5 §7)."""

    def __init__(self, path: Path) -> None:
        super().__init__(path, ["timestamp", "kind", "block_id", "source_path", "data"])

    def emit(self, event: RunEvent) -> None:
        self._write_row([
            repr(event.timestamp),
            event.kind,
            event.block_id or "",
            event.source_path or "",
            json.dumps(event.data),
        ])
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_experiment_persist.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/lab_devices/experiment/runlog.py src/lab_devices/experiment/persist.py tests/test_experiment_persist.py
git commit -m "feat(experiment): source_path field on RunEvent + serializers"
```

---

## Task 2: Emit the authored `source_path` from the engine

**Files:**
- Modify: `src/lab_devices/experiment/expand.py:530-532` (add `expand_workflow_traced`)
- Modify: `src/lab_devices/experiment/context.py:53-72` (`source_map` field), `:103-104` (`emit`)
- Modify: `src/lab_devices/experiment/run.py:137-146`
- Test: `tests/test_experiment_runlog_source_path.py` (new)

**Interfaces:**
- Consumes: `expand_dict_traced`, `workflow_to_dict`, `workflow_from_dict` (existing in `expand.py`); `RunEvent.source_path` (Task 1).
- Produces: `expand_workflow_traced(w: Workflow) -> tuple[Workflow, dict[str, str]]`. `RunContext.source_map: dict[str, str]`. Every block-scoped emitted event carries `source_path == source_map.get(block_id)`.

- [ ] **Step 1: Write the failing integration test**

Create `tests/test_experiment_runlog_source_path.py`. It runs a workflow with a `for_each` (2 rows) plus a plain block against a fake/mock lab, captures emitted events via an in-memory sink, and asserts authored source paths. Model it on the existing `tests/test_experiment_runlog_inputs.py` harness (same fixtures/mock client). Concretely:

```python
import pytest
from lab_devices.experiment.runlog import InMemoryRunLog

# Reuse this module's existing helpers for building a Workflow + mock LabClient.
# (See tests/test_experiment_runlog_inputs.py for the established pattern.)

@pytest.mark.asyncio
async def test_source_path_maps_expanded_events_to_authored_blocks(...):
    # A workflow whose top-level blocks are:
    #   [0] for_each over 2 rows, body = [ measure/command block ]
    #   [1] a plain block
    sink = InMemoryRunLog()
    # ... build workflow + run it with options.log_sink = sink ...

    by_kind = {}
    for e in sink.events:
        by_kind.setdefault(e.kind, []).append(e)

    started = by_kind["block_started"]
    # Two for_each copies BOTH trace to the single authored body block:
    forEachCopies = [e for e in started if e.source_path == "blocks[0].body[0]"]
    assert len(forEachCopies) == 2
    # The plain block (authored blocks[1], expanded blocks[2]) traces to its authored path:
    assert any(e.source_path == "blocks[1]" for e in started)

    # Lifecycle events carry no source_path:
    assert all(e.source_path is None for e in by_kind["run_started"])
```

Fill the workflow-construction and run harness from `test_experiment_runlog_inputs.py`. If a parametrized group is easy to include with that harness, add a second assertion that an inlined group-body event's `source_path` is a `groups[...]`/compound authored path; otherwise leave the for_each+plain case (it exercises index-shift, the core risk).

- [ ] **Step 2: Run it to verify it fails**

Run: `pytest tests/test_experiment_runlog_source_path.py -v`
Expected: FAIL — every `source_path` is `None` (engine doesn't attach it yet).

- [ ] **Step 3: Add `expand_workflow_traced`**

In `src/lab_devices/experiment/expand.py`, beside `expand_workflow`:

```python
def expand_workflow_traced(w: Workflow) -> tuple[Workflow, dict[str, str]]:
    """expand_workflow plus the expanded->authored source map (see expand_dict_traced).

    The trace keys are exactly the structural paths assign_block_ids assigns on the
    expanded tree, so RunContext can name any run event's authored block by
    source_map.get(block_id). Many-to-one: every for_each copy traces to its one
    authored body block."""
    expanded, trace = expand_dict_traced(workflow_to_dict(w))
    return workflow_from_dict(expanded), trace
```

- [ ] **Step 4: Thread the trace into `RunContext`**

In `src/lab_devices/experiment/context.py`, add a field to the `RunContext` dataclass (near `log_sink`, `:71`):

```python
    source_map: dict[str, str] = field(default_factory=dict)
    # expanded block_id -> authored structural path (expand_workflow_traced). emit() names
    # each block-scoped event's authored block from this; {} means "no naming" (source_path None).
```

And update `emit` (`:103-104`):

```python
    def emit(self, kind: str, block_id: str | None = None, **data: Any) -> None:
        source_path = self.source_map.get(block_id) if block_id is not None else None
        self.log_sink.emit(
            RunEvent(self.clock.now(), kind, block_id, dict(data), source_path=source_path)
        )
```

- [ ] **Step 5: Expand-with-trace in `ExperimentRun`**

In `src/lab_devices/experiment/run.py`, change the import (`:24`) from `expand_workflow` to `expand_workflow_traced`, then in `ExperimentRun.__init__` replace `:137-138`:

```python
        workflow, trace = expand_workflow_traced(workflow)  # run the concrete tree (design 2026-07-15 §4.4)
        assign_block_ids(workflow)
```

and pass the trace into the `RunContext(...)` construction (`:143-146`):

```python
        self._ctx = RunContext(
            client=client, workflow=workflow, state=state, options=self._options,
            role_devices=role_devices, source_map=trace,
        )
```

- [ ] **Step 6: Run the new test + the engine suite**

Run: `pytest tests/test_experiment_runlog_source_path.py tests/test_experiment_runlog_inputs.py tests/test_experiment_persist.py -v`
Expected: PASS.
Run: `pytest tests/ -q`
Expected: PASS (no regressions from the new field/emit).

- [ ] **Step 7: Typecheck**

Run: `mypy src/lab_devices`
Expected: no errors.

- [ ] **Step 8: Commit**

```bash
git add src/lab_devices/experiment/expand.py src/lab_devices/experiment/context.py src/lab_devices/experiment/run.py tests/test_experiment_runlog_source_path.py
git commit -m "feat(experiment): emit authored source_path per block-scoped run event"
```

---

## Task 3: Fix the WS-sink test for the new field

**Files:**
- Modify: `webapp/backend/tests/test_sinks.py:12` and any assertion on the emitted message shape.

**Interfaces:**
- Consumes: `run_event_to_dict` now includes `source_path` (Task 1), so `TeeRunLogSink.emit` messages gain the key automatically.

- [ ] **Step 1: Run the backend sink test to see the break**

Run: `pytest webapp/backend/tests/test_sinks.py -v`
Expected: FAIL — the emitted-message assertion is missing `"source_path"` (the tee spreads `run_event_to_dict`, which now includes it).

- [ ] **Step 2: Update the expected message shape**

In `webapp/backend/tests/test_sinks.py`, wherever a full event message is asserted, add `"source_path": None` (the helper `RunEvent(ts, kind, "blocks[0]", {"k": "v"})` leaves `source_path` defaulted). If the test asserts a subset via `toMatchObject`-style key checks, no change is needed — only exact-dict assertions do.

- [ ] **Step 3: Run to verify pass**

Run: `pytest webapp/backend/tests/ -q`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add webapp/backend/tests/test_sinks.py
git commit -m "test(studio): expect source_path in tee-sink event messages"
```

---

## Task 4: `resolveDiagnosticNode` — resolve a path to its node

**Files:**
- Modify: `webapp/frontend/src/builder/paths.ts:109-156`
- Test: `webapp/frontend/src/builder/paths.test.ts`

**Interfaces:**
- Consumes: existing `resolveTail`, `quotedGroupHeadEnd`, `GROUP_SEGMENT_RE`, `GROUP_HEAD_RE`, `BLOCKS_RE`, `ROLE_RE`, `PARAM_RE`.
- Produces: `resolveDiagnosticNode(tree: BlockNode[], groups: GroupsMap, path: string): BlockNode | null`. `resolveDiagnosticPath` keeps its exact `{uid, role, param, scope, field}` contract.

- [ ] **Step 1: Add failing tests for `resolveDiagnosticNode`**

In `webapp/frontend/src/builder/paths.test.ts`, import `resolveDiagnosticNode` and add (reusing the file's existing `tree` / `groups` fixtures):

```ts
describe('resolveDiagnosticNode', () => {
  it('returns the node for a main-tree path', () => {
    expect(resolveDiagnosticNode(tree, {}, 'blocks[0].children[1].body[0]')?.uid).toBe('w2')
  })
  it('returns the node for a group-scope path', () => {
    // uses the same `groups` fixture the resolveDiagnosticPath group tests use
    expect(resolveDiagnosticNode([], groups, "groups['service'].body[0]")?.uid)
      .toBe(resolveDiagnosticPath([], groups, "groups['service'].body[0]").uid)
  })
  it('returns null for an unresolvable or role path', () => {
    expect(resolveDiagnosticNode(tree, {}, 'blocks[9]')).toBeNull()
    expect(resolveDiagnosticNode(tree, {}, "roles['Feed_Pump']")).toBeNull()
  })
})
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd webapp/frontend && npx vitest run src/builder/paths.test.ts`
Expected: FAIL — `resolveDiagnosticNode is not a function`.

- [ ] **Step 3: Refactor — extract node resolution, add the new export**

In `webapp/frontend/src/builder/paths.ts`, replace the body of `resolveDiagnosticPath` (`:109-156`) with a version that delegates structural resolution to a shared helper, and add `resolveDiagnosticNode`. Behavior of `resolveDiagnosticPath` is unchanged.

```ts
/** Structural (suffix-stripped) path -> {node, scope}. Shared by resolveDiagnosticPath
 * (for its uid) and resolveDiagnosticNode. Mirrors the three head forms the file documents. */
function resolveStructuralNode(
  tree: BlockNode[],
  groups: GroupsMap,
  structural: string,
): { node: BlockNode | null; scope: string | null } {
  const headEnd = quotedGroupHeadEnd(structural)
  const arrowTail = structural.slice(headEnd).lastIndexOf('->')
  const arrowIndex = arrowTail === -1 ? -1 : arrowTail + headEnd
  if (arrowIndex !== -1) {
    const segMatch = GROUP_SEGMENT_RE.exec(structural.slice(arrowIndex + 2))
    if (!segMatch) return { node: null, scope: null }
    const [, name, tail] = segMatch
    return { node: resolveTail(groups[name]?.body ?? null, tail), scope: name }
  }
  const groupHeadMatch = GROUP_HEAD_RE.exec(structural)
  if (groupHeadMatch) {
    const name = groupHeadMatch[1] ?? groupHeadMatch[2]
    return { node: resolveTail(groups[name]?.body ?? null, groupHeadMatch[3]), scope: name }
  }
  const blocksMatch = BLOCKS_RE.exec(structural)
  if (!blocksMatch) return { node: null, scope: null }
  return { node: resolveTail(tree, blocksMatch[1]), scope: null }
}

export function resolveDiagnosticPath(tree: BlockNode[], groups: GroupsMap, path: string): ResolvedPath {
  const roleMatch = ROLE_RE.exec(path)
  if (roleMatch) return { ...NONE, role: roleMatch[1] ?? roleMatch[2] }

  const headEnd = quotedGroupHeadEnd(path)
  const spaceIndex = path.indexOf(' ', headEnd)
  const structural = spaceIndex === -1 ? path : path.slice(0, spaceIndex)
  const suffix = spaceIndex === -1 ? '' : path.slice(spaceIndex + 1)
  const paramMatch = PARAM_RE.exec(suffix)
  const param = paramMatch ? (paramMatch[1] ?? paramMatch[2]) : null
  const field = suffix === '' ? null : suffix

  const { node, scope } = resolveStructuralNode(tree, groups, structural)
  return { uid: node?.uid ?? null, role: null, param, scope, field }
}

/** The node a diagnostic/source path addresses (or null). Same resolution as
 * resolveDiagnosticPath, returning the block instead of only its uid — used to name run-log
 * events by the authored block's label/summary. */
export function resolveDiagnosticNode(
  tree: BlockNode[],
  groups: GroupsMap,
  path: string,
): BlockNode | null {
  if (ROLE_RE.test(path)) return null
  const headEnd = quotedGroupHeadEnd(path)
  const spaceIndex = path.indexOf(' ', headEnd)
  const structural = spaceIndex === -1 ? path : path.slice(0, spaceIndex)
  return resolveStructuralNode(tree, groups, structural).node
}
```

Keep the existing explanatory comments in `resolveDiagnosticPath` by relocating the relevant ones (compound/group/opaque-head notes) onto `resolveStructuralNode`.

- [ ] **Step 4: Run the whole paths suite**

Run: `cd webapp/frontend && npx vitest run src/builder/paths.test.ts`
Expected: PASS — new `resolveDiagnosticNode` cases AND every pre-existing `resolveDiagnosticPath` assertion.

- [ ] **Step 5: Commit**

```bash
git add webapp/frontend/src/builder/paths.ts webapp/frontend/src/builder/paths.test.ts
git commit -m "feat(studio): resolveDiagnosticNode — resolve a source path to its block"
```

---

## Task 5: `source_path` types + the `blockName` helper

**Files:**
- Modify: `webapp/frontend/src/types/runs.ts:31-38` (`RunEventMsg`), `:48-54` (`RecordEvent`)
- Create: `webapp/frontend/src/run/blockName.ts`
- Test: `webapp/frontend/src/run/blockName.test.ts`

**Interfaces:**
- Consumes: `resolveDiagnosticNode` (Task 4); `blockSummary` (`builder/summary.ts`); `BlockNode` (`builder/tree.ts`); `GroupsMap` (`builder/paths.ts`).
- Produces: `blockName(event, tree, groups): { text: string; path: string | null } | null` where `event: { block_id: string | null; source_path?: string | null }`, `tree: BlockNode[] | null`, `groups: GroupsMap | null`.

- [ ] **Step 1: Add `source_path` to the wire types**

In `webapp/frontend/src/types/runs.ts`, add `source_path: string | null` to `RunEventMsg` (after `block_id`) and to `RecordEvent` (after `block_id`):

```ts
export interface RunEventMsg {
  type: 'event'
  seq: number
  timestamp: number
  kind: string
  block_id: string | null
  source_path: string | null
  data: Record<string, unknown>
}
```
```ts
export interface RecordEvent {
  timestamp: number
  kind: string
  block_id: string | null
  source_path: string | null
  data: Record<string, unknown>
}
```

- [ ] **Step 2: Write failing `blockName` tests**

Create `webapp/frontend/src/run/blockName.test.ts`. Build a tiny authored tree with `blockToNode`/`docToTree` or hand-built `BlockNode`s (mirror the fixtures in `summary.test.ts`). Cover: label wins; summary fallback; a `for_each` copy's authored path resolves to the body node's summary; unresolvable → raw path; null path → null; no tree → raw path.

```ts
import { describe, expect, it } from 'vitest'
import { blockName } from './blockName'
import { docToTree } from '../builder/convert'
import type { ExperimentDocJson } from '../types/doc'

// Minimal schema-3 doc: one command block with a label, one wait without.
const doc: ExperimentDocJson = { /* doc_version:1, workflow: {schema_version:3, blocks:[
  { command: { device:'pump1', verb:'dispense', params:{ volume:5 } }, label:'drug pulse' },
  { wait: { duration: '30s' } },
], roles:{ pump1:{ type:'pump' } }, streams:{} } , name:'t' */ } as ExperimentDocJson

const ev = (source_path: string | null, block_id: string | null = source_path) =>
  ({ block_id, source_path })

describe('blockName', () => {
  it('prefers the user label when set', () => {
    const { tree, groups } = docToTree(doc)
    expect(blockName(ev('blocks[0]'), tree, groups)?.text).toBe('drug pulse')
  })
  it('falls back to the derived summary', () => {
    const { tree, groups } = docToTree(doc)
    expect(blockName(ev('blocks[1]'), tree, groups)?.text).toBe('wait 30s')
  })
  it('returns the raw path when unresolvable', () => {
    const { tree, groups } = docToTree(doc)
    expect(blockName(ev('blocks[9]'), tree, groups)).toEqual({ text: 'blocks[9]', path: 'blocks[9]' })
  })
  it('uses block_id when source_path is absent', () => {
    const { tree, groups } = docToTree(doc)
    expect(blockName(ev(null, 'blocks[0]'), tree, groups)?.text).toBe('drug pulse')
  })
  it('returns null when there is no path at all', () => {
    const { tree, groups } = docToTree(doc)
    expect(blockName(ev(null, null), tree, groups)).toBeNull()
  })
  it('returns the raw path when no tree is available', () => {
    expect(blockName(ev('blocks[0]'), null, null)).toEqual({ text: 'blocks[0]', path: 'blocks[0]' })
  })
})
```

Flesh out the `doc` literal to a valid schema-3 document (see `summary.test.ts` / `convert.test.ts` for the exact shape). Add a `for_each` case if convenient: an authored `for_each` body block, asserting `blockName(ev('blocks[0].body[0]'), …)` resolves to that body block's summary.

- [ ] **Step 3: Run to verify it fails**

Run: `cd webapp/frontend && npx vitest run src/run/blockName.test.ts`
Expected: FAIL — `Cannot find module './blockName'`.

- [ ] **Step 4: Implement `blockName`**

Create `webapp/frontend/src/run/blockName.ts`:

```ts
/** Human-readable name for a run-log event's block: the user's label if set, else the derived
 * blockSummary, resolved from the event's authored source_path (engine source map) against the
 * authored doc tree. Falls back to the raw structural path so a line never loses its block id. */
import { resolveDiagnosticNode, type GroupsMap } from '../builder/paths'
import { blockSummary } from '../builder/summary'
import type { BlockNode } from '../builder/tree'

export interface NamedBlock {
  text: string
  path: string | null
}

export function blockName(
  event: { block_id: string | null; source_path?: string | null },
  tree: BlockNode[] | null,
  groups: GroupsMap | null,
): NamedBlock | null {
  const path = event.source_path ?? event.block_id
  if (path === null || path === undefined) return null
  if (tree !== null && groups !== null) {
    const node = resolveDiagnosticNode(tree, groups, path)
    if (node !== null) return { text: node.label ?? blockSummary(node), path }
  }
  return { text: path, path }
}
```

- [ ] **Step 5: Run to verify it passes + typecheck**

Run: `cd webapp/frontend && npx vitest run src/run/blockName.test.ts`
Expected: PASS.
Run: `cd webapp/frontend && npm run typecheck`
Expected: no errors (types wired; no consumers yet perturbed).

- [ ] **Step 6: Commit**

```bash
git add webapp/frontend/src/types/runs.ts webapp/frontend/src/run/blockName.ts webapp/frontend/src/run/blockName.test.ts
git commit -m "feat(studio): source_path wire types + blockName resolver"
```

---

## Task 6: Render names in `EventLog` + wire the record viewer

**Files:**
- Modify: `webapp/frontend/src/run/EventLog.tsx:8-13` (`LogEvent`), `:37` (props), `:59-68` (render)
- Modify: `webapp/frontend/src/records/RecordViewer.tsx:13,138`

**Interfaces:**
- Consumes: `blockName` (Task 5); `docToTree` (`builder/convert.ts`); `detail.doc: ExperimentDocJson | null`.
- Produces: `EventLog` accepts optional `nameFor?: (e: LogEvent) => NamedBlock | null`. When present, renders the name; when absent, the legacy `[block_id]` bracket.

- [ ] **Step 1: Extend `LogEvent` and add the `nameFor` prop**

In `webapp/frontend/src/run/EventLog.tsx`, add `source_path` to `LogEvent` and a `nameFor` prop, and render the resolved name in place of the bracket (`:59-68`):

```tsx
import type { NamedBlock } from './blockName'

export interface LogEvent {
  timestamp: number
  kind: string
  block_id: string | null
  source_path: string | null
  data: Record<string, unknown>
}
```

Change the component signature and the per-line render:

```tsx
export function EventLog(props: {
  events: ReadonlyArray<LogEvent>
  origin: number | null
  rev: number
  nameFor?: (e: LogEvent) => NamedBlock | null
}) {
  // ...unchanged setup...
  {shown.map((e, i) => {
    const named = props.nameFor?.(e) ?? null
    return (
      <div key={`${props.events.length - shown.length + i}`} className="flex gap-2 py-px">
        <span className="w-20 shrink-0 text-right text-caption">
          {props.origin !== null ? `+${formatElapsed(e.timestamp - props.origin)}` : ''}
        </span>
        <span className={`min-w-0 flex-1 ${KIND_COLOR[e.kind] ?? 'text-slate-700'}`}>
          {describeEvent(e)}
          {named
            ? <span title={named.path ?? undefined} className="ml-1 text-caption">— {named.text}</span>
            : e.block_id !== null && <span className="ml-1 text-caption">[{e.block_id}]</span>}
        </span>
      </div>
    )
  })}
```

- [ ] **Step 2: Typecheck to catch the RunEventMsg/RecordEvent assignability**

Run: `cd webapp/frontend && npm run typecheck`
Expected: no errors — `RunEventMsg` and `RecordEvent` now both carry `source_path`, so passing `feed.events` / `events` to `EventLog` still satisfies `LogEvent[]`.

- [ ] **Step 3: Wire the record viewer**

In `webapp/frontend/src/records/RecordViewer.tsx`, import `docToTree` and `blockName`, build the tree/groups once from `detail.doc` (guard the throw), and pass `nameFor`. Add near the other imports:

```tsx
import { docToTree } from '../builder/convert'
import { blockName } from '../run/blockName'
```

After `detail`/`events`/`streams` are known non-null (before the return), compute:

```tsx
  const resolved = (() => {
    if (detail.doc === null) return null
    try {
      const { tree, groups } = docToTree(detail.doc)
      return { tree, groups }
    } catch {
      return null // malformed snapshot: EventLog falls back to raw ids
    }
  })()
```

Then change the `EventLog` usage (`:138`):

```tsx
      <EventLog
        events={events}
        origin={events.length > 0 ? events[0].timestamp : null}
        rev={0}
        nameFor={(e) => blockName(e, resolved?.tree ?? null, resolved?.groups ?? null)}
      />
```

- [ ] **Step 4: Typecheck + build + probe capture**

Run: `cd webapp/frontend && npm run typecheck && npm run test`
Expected: PASS (existing `reducer.test.ts`, `describeEvent.test.ts`, etc. unaffected — base text unchanged).
Run: `cd webapp/frontend && npm run capture` (per `webapp/frontend/CLAUDE.md`, verify no probe regressions on a real doc; the record viewer's event log now shows names).
Expected: probe passes (no new contrast/height violations — names use `text-caption`, an approved token).

- [ ] **Step 5: Commit**

```bash
git add webapp/frontend/src/run/EventLog.tsx webapp/frontend/src/records/RecordViewer.tsx
git commit -m "feat(studio): render block names in the record-viewer run log"
```

---

## Task 7: Wire the live run screen

**Files:**
- Modify: `webapp/frontend/src/stores/runStore.ts:31-55` (state), `:104-125` (`adopt`), `:226-235` (`dismiss`)
- Modify: `webapp/frontend/src/run/RunView.tsx:44-56,136`
- Test: `webapp/frontend/src/stores/runStore.test.ts` (if present) — assert `doc` is stashed on adopt.

**Interfaces:**
- Consumes: `getRecord(id).doc` (already fetched in `adopt` for `streamUnits`); `docToTree`, `blockName`.
- Produces: `RunUiState.doc: ExperimentDocJson | null`. `RunView` passes `nameFor` to `EventLog`.

- [ ] **Step 1: Add `doc` to the run store**

In `webapp/frontend/src/stores/runStore.ts`:

- Add to `RunUiState` (`:41`, beside `streamUnits`): `doc: ExperimentDocJson | null`
- In `adopt` (`:122-124`), stash the doc alongside `streamUnits`:

```tsx
    return getRecord(payload.record_id)
      .then((d) => set({ streamUnits: unitsOf(d.doc), doc: d.doc }))
      .catch(() => set({ streamUnits: {}, doc: null }))
```

- Initialize `doc: null` in the store's returned initial state (`:137`) and reset it in both the `adopt` `set({...})` (`:105-119`, add `doc: null` so a stale doc never bleeds across runs before the fetch resolves) and `dismiss` (`:229-234`, add `doc: null`).

- [ ] **Step 2: If a runStore test exists, assert the stash (else skip)**

If `webapp/frontend/src/stores/runStore.test.ts` exists and mocks `getRecord`, add an assertion that after `attach()`/`adopt`, `useRunStore.getState().doc` equals the mocked `d.doc`. If no such test/harness exists, skip — `adopt` is covered by the store's existing attach tests, and the doc stash is type-checked.

Run (if added): `cd webapp/frontend && npx vitest run src/stores/runStore.test.ts`
Expected: PASS.

- [ ] **Step 3: Pass `nameFor` from `RunView`**

In `webapp/frontend/src/run/RunView.tsx`, read `doc` from the store, resolve the tree/groups (guarded), and pass `nameFor`:

```tsx
import { docToTree } from '../builder/convert'
import { blockName } from './blockName'
```

Inside `RunView` (after the existing `useRunStore` selectors):

```tsx
  const doc = useRunStore((s) => s.doc)
  const resolved = useMemo(() => {
    if (doc === null) return null
    try {
      const { tree, groups } = docToTree(doc)
      return { tree, groups }
    } catch {
      return null
    }
  }, [doc])
```

(Add `useMemo` to the existing `react` import.) Then the `EventLog` usage (`:136`):

```tsx
      <EventLog
        events={feed.events}
        origin={feed.origin}
        rev={feed.rev}
        nameFor={(e) => blockName(e, resolved?.tree ?? null, resolved?.groups ?? null)}
      />
```

- [ ] **Step 4: Typecheck + tests + build**

Run: `cd webapp/frontend && npm run typecheck && npm run test`
Expected: PASS.
Run: `cd webapp/frontend && npm run build`
Expected: clean build.

- [ ] **Step 5: Commit**

```bash
git add webapp/frontend/src/stores/runStore.ts webapp/frontend/src/run/RunView.tsx
git commit -m "feat(studio): render block names on the live run screen"
```

---

## Task 8: Full-suite verification

**Files:** none (verification only).

- [ ] **Step 1: Engine + backend + frontend suites**

Run: `pytest tests/ -q`
Run: `pytest webapp/backend/tests/ -q`
Run: `mypy src/lab_devices`
Run: `cd webapp/frontend && npm run typecheck && npm run test && npm run lint && npm run build`
Expected: all green.

- [ ] **Step 2: Manual smoke (optional, if a lab/preprod is available)**

Per the memory's capture recipe, a live event-log check needs both servers. If unavailable, the probe capture in Task 6/7 plus the unit tests are the verification of record. Note in the PR that a live for_each run was/was not smoke-tested.

- [ ] **Step 3: Push and open the PR** (handled by the executing session, not a code change).

---

## Self-Review

**Spec coverage:**
- Name = label else summary → Task 5 `blockName` (label ?? blockSummary). ✓
- Both surfaces → Task 6 (record), Task 7 (live). ✓
- Correct for for_each/param groups → Tasks 1-2 (engine source_path via trace), Task 2 test. ✓
- First-class `source_path` field → Task 1. ✓
- Single serializer covers jsonl + WS → Task 1 (`run_event_to_dict`), Task 3 (sink test). ✓
- Fallback label→summary→raw, never blank → Task 5 `blockName`, Task 6 render. ✓
- Back-compat old records (no source_path) → Task 5 (`source_path ?? block_id`, best-effort resolve). ✓
- Clickability deferred; uid available → `resolveDiagnosticNode` returns the node (Task 4). ✓

**Placeholder scan:** the only deliberately-templated content is the Task 2 workflow-construction harness and the Task 5 `doc` literal, both pointing at the exact existing files to copy the shape from (`test_experiment_runlog_inputs.py`, `summary.test.ts`/`convert.test.ts`). No `TODO`/`TBD`/"add error handling".

**Type consistency:** `NamedBlock` (Task 5) is the return type used by `EventLog.nameFor` (Task 6) and both call sites (Tasks 6, 7). `resolveDiagnosticNode` signature matches its use in `blockName`. `RunEvent.source_path` (last field, keyword-passed) is consistent across Tasks 1-2. `source_path: string | null` on `RunEventMsg`/`RecordEvent`/`LogEvent` is consistent across Tasks 5-6.
