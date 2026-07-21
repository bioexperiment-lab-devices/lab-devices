# Human-readable block names in the run log

**Date:** 2026-07-21
**Status:** Design approved, ready for planning
**Branch:** `feat/run-log-block-names`

## Problem

Every run-log line that belongs to a block currently ends with the block's raw
structural id in brackets — e.g.

```
+00:12  block started              [blocks[1].children[0]]
+00:13  od = 0.5321                [blocks[1].children[0]]
```

`blocks[1].children[0]` is a validator diagnostic path (`assign_block_ids`,
`run.py`). It is machine-precise but tells an operator nothing about *which*
step of their experiment just ran. The log is the primary at-a-glance view of a
live run, so this is where a readable name matters most.

## Goal

Render each block-scoped log line with the block's **human-readable name**:

- the block's user-typed **`label`** nickname when one is set, otherwise
- the derived **`blockSummary`** (`pump1 · dispense (volume=5)`, `wait 30s`,
  `For each tube, od × 3`) — the same one-liner the canvas and the record's
  `WorkflowSnapshot` already show.

```
+00:12  block started   — pump1 · dispense (volume=5)
+00:13  od = 0.5321      — densitometer1 · read → od
+00:20  block started   — “drug pulse”          (user label)
```

Both surfaces — the **live run screen** (`RunView`) and the **record viewer**
(`RecordViewer`) — through the shared `EventLog` component. Correct for **every**
block, including `for_each` / parametrized-group copies.

### Non-goals (YAGNI)

- **Clickability.** Names are plain text in this increment. The resolver hands
  back the authored block's `uid`, so a follow-up can make the name select the
  block with no rework — but that is out of scope here.
- **Disambiguating `for_each` copies by bound values.** Every expanded copy of an
  authored body block resolves to the *same* authored name (all three tube copies
  read `densitometer1 · read → od`). This is accepted, not a limitation to fix.
- **Server-side name computation.** No Python port of `blockSummary`. The summary
  stays the single TypeScript source of truth; the engine only ships the authored
  *path*, and the frontend derives the name from the node it already renders.

## Key insight — the source map already exists

The hard part looks like the expanded-vs-authored mismatch: run-event `block_id`s
are assigned on the **expanded** tree (`run.py:137-138`, after `expand_workflow`
unrolls `for_each` and inlines parametrized groups), so they live in a different
path space than the authored Builder tree. That problem is **already solved**:

- `expand_dict_traced` (`expand.py`) returns a `trace: {expanded_path →
  authored_path}` map, built as expansion walks (`trace[f"{dst}[{base}]"] = src`).
- `docs_store._remap` already consumes that trace to translate expanded
  *validator diagnostics* back onto editable blocks for the Studio Problems panel.
- The engine's `assign_block_ids` produces paths that are **exactly the `trace`
  keys** (both derive from the same expansion), so `trace.get(block_id)` yields
  the authored path.
- The frontend's `resolveDiagnosticPath` (`builder/paths.ts`) **already reads**
  that authored-path grammar — `blocks[i]…`, `groups['name'].body[i]…`, and the
  compound `blocks[i]->name.body[j]` form.

So this feature reuses proven machinery at both ends. `trace.get(block_id)` is
sufficient — run `block_id`s are clean structural paths with no diagnostic
suffix, so we do **not** need to port `_remap` into the engine.

## Design

### 1. Engine — carry the authored path, attach it centrally

`src/lab_devices/experiment/`

- **`run.py`**: expand with the trace retained. Add `expand_workflow_traced(w)
  -> (Workflow, dict[str, str])` (an AST-level sibling of `expand_workflow` that
  threads `expand_dict_traced` instead of `expand_dict`). In `ExperimentRun.
  __init__`, call it, then `assign_block_ids(workflow)`, then pass the trace to
  `RunContext` as `source_map`.
- **`context.py`**: `RunContext` gains a `source_map: dict[str, str]` (default
  `{}`). `RunContext.emit` attaches the authored path when a `block_id` is
  present:

  ```python
  def emit(self, kind, block_id=None, **data):
      source_path = self.source_map.get(block_id) if block_id is not None else None
      self.log_sink.emit(RunEvent(self.clock.now(), kind, block_id, source_path, dict(data)))
  ```

  This is the **single choke point** every block-scoped event already flows
  through (`execute.py`, `finalize.py`, `run.py` all call `ctx.emit(kind,
  block.id, …)`), so all of `block_started` / `block_finished` /
  `measure_recorded` / `binding_computed` / `sample_recorded` / `mode_opened` /
  … get `source_path` with **no per-call-site edits**. Lifecycle events
  (`run_started`, `paused`, …) pass `block_id=None` → `source_path=None`, as
  desired.

Because the trace and the `block_id`s come from the *same* expansion object,
they are guaranteed consistent — no cross-layer key-matching risk. Pure-engine /
CLI runs get named logs too, and the persisted `run_log.jsonl` becomes
self-describing.

### 2. Event contract — `source_path` as a first-class field

`source_path` is modeled alongside `block_id`, not stuffed into the free-form
`data` bag (keeps `data` clean and avoids perturbing engine tests that assert
exact `event.data`). Touch points, all trivial:

- `runlog.py`: `RunEvent` dataclass gains `source_path: str | None = None`.
- `persist.py` `run_event_to_dict` — **the single serializer feeding both the
  persisted `run_log.jsonl` and the live WS envelope** (`sinks.TeeRunLogSink.
  emit` spreads `run_event_to_dict(event)` into the WS message). Adding
  `source_path` here covers **both** the log and the live stream in one edit.
- `persist.py` CSV writer (separate `["timestamp", "kind", "block_id", "data"]`
  column list, secondary export) — add `source_path` for parity.
- `webapp/frontend/src/types/runs.ts`: `RunEventMsg` and `RecordEvent` gain
  `source_path: string | null`.
- `EventLog.LogEvent`: gains `source_path: string | null`.

### 3. Frontend — resolve the path to a name

`webapp/frontend/src/`

- **`builder/paths.ts`**: add `resolveDiagnosticNode(tree, groups, path):
  BlockNode | null` — the same resolution `resolveDiagnosticPath` already
  performs, returning the node instead of only its `uid`. (`resolveDiagnosticPath`
  keeps returning the `uid`; the node variant is what naming needs, and the `uid`
  it also exposes is what a future clickable version will use.)
- **`run/blockName.ts`** (new, pure, tested):

  ```ts
  export function blockName(
    event: { block_id: string | null; source_path: string | null },
    tree: BlockNode[] | null,
    groups: GroupsMap | null,
  ): { text: string; path: string | null } | null
  ```

  Logic — resolution order **label → summary → raw path**, never blank:
  1. `path = event.source_path ?? event.block_id`; if `null`, return `null`.
  2. If `tree` and `groups` are present, `node = resolveDiagnosticNode(tree,
     groups, path)`; if resolved, return `{ text: node.label ?? blockSummary(node),
     path }`.
  3. Otherwise (no tree, or unresolvable) return `{ text: path, path }` — the raw
     structural path, never worse than today.
- **`run/EventLog.tsx`**: stays presentation-only. Accepts a
  `nameFor?: (e: LogEvent) => { text: string; path: string | null } | null`
  prop from its parent. Renders the resolved name in place of the `[block_id]`
  bracket:

  ```tsx
  {name && <span title={name.path ?? undefined} className="ml-1 text-caption">— {name.text}</span>}
  ```

  `title={name.path}` keeps the structural path available on hover for power
  users. When no `nameFor` is supplied it falls back to today's `[block_id]`
  bracket (used by any caller that has no tree).

### 4. Wiring the authored tree on both surfaces

- **`RecordViewer`**: already builds the authored tree via `docToTree(doc)` for
  `WorkflowSnapshot`. Build it once (memoized), derive `groups`, and pass
  `nameFor = (e) => blockName(e, tree, groups)` to `EventLog`.
- **`RunView` / `runStore`**: the store already fetches the record on start
  (`getRecord(payload.record_id)`, used today for `streamUnits`). Also stash
  `d.doc` (add `doc: ExperimentDocJson | null` to the store). `RunView` builds
  the tree from it (guarding `docToTree` errors → `blockName` falls back to the
  raw path) and passes the same `nameFor` to `EventLog`.

## Fallbacks & back-compat

- **Resolution order**: label → summary → raw path. Never blank.
- **Old records** (jsonl written before this change, no `source_path`):
  `blockName` best-effort-resolves the raw `block_id` (exact for non-expanding
  workflows — including plain `Loop`s like the morbidostat example; only
  `for_each` / parametrized-group runs miss), else shows the raw id. No worse
  than today anywhere; no migration.
- **Tree unavailable** (doc failed to load / parse): raw-path fallback.

## Testing

- **Engine** (`tests/`): a run with a `for_each` over 2 rows plus a plain block
  asserts emitted events carry the authored `source_path` — both `for_each`
  copies → `blocks[i].body[0]`, the plain block → `blocks[j]` — and that a
  lifecycle event (`run_started`) carries `source_path=None`. Add a
  parametrized-group case (inlined body block resolves to a `groups[…]`/compound
  authored path the frontend grammar reads). Extends
  `test_experiment_runlog_inputs.py` or a new `test_experiment_runlog_source_path.py`.
  Update any engine test asserting full `RunEvent` equality / jsonl round-trip
  for the new field.
- **Frontend** (`webapp/frontend`, vitest, pure): `blockName` tests — label
  present → label; no label → summary; a `for_each` copy's authored path resolves
  to the body node's summary; unresolvable path → raw fallback; `null` path →
  `null`. `describeEvent` tests are untouched (base text unchanged). DOM wiring
  (EventLog rendering the name) is covered by the UI-audit probe harness per the
  frontend testing rules, not jsdom.

## Files touched (summary)

**Engine**
- `src/lab_devices/experiment/run.py` — `expand_workflow_traced`, pass trace.
- `src/lab_devices/experiment/context.py` — `source_map`, `emit` attaches
  `source_path`.
- `src/lab_devices/experiment/runlog.py` — `RunEvent` gains `source_path`.
- `src/lab_devices/experiment/persist.py` — `run_event_to_dict` (covers jsonl
  **and** WS) + CSV column list include `source_path`. No separate WS edit
  needed: `TeeRunLogSink.emit` already spreads `run_event_to_dict`.

**Frontend**
- `webapp/frontend/src/types/runs.ts` — `source_path` on `RunEventMsg` /
  `RecordEvent`.
- `webapp/frontend/src/builder/paths.ts` — `resolveDiagnosticNode`.
- `webapp/frontend/src/run/blockName.ts` (new) + `blockName.test.ts`.
- `webapp/frontend/src/run/EventLog.tsx` — `nameFor` prop, render name.
- `webapp/frontend/src/records/RecordViewer.tsx` — pass `nameFor`.
- `webapp/frontend/src/run/RunView.tsx` + `webapp/frontend/src/stores/runStore.ts`
  — stash `doc`, build tree, pass `nameFor`.
