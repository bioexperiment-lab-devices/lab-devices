# Experiment Studio W8 — control blocks + live-chart fold

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `compute`, `record`, `abort`, and `alarm` first-class in the Studio builder canvas, and fix the reducer so a `record` stream charts *during* a run.

**Architecture:** Four new leaf `BlockNode` variants extend the existing `NodeBase`, so `label`/`gap_after`/`start_offset` and the whole drag/drop/undo machinery come free — none has child slots, so `childSlots`/`replaceSlot` are untouched. They reuse the existing palette drag path via a widened kind union (`PaletteKind = StructureKind | ControlKind`). The reducer fix is a one-condition fold, independent of everything else, and ships first.

**Tech Stack:** React 19.2, Vite 8, Tailwind 4, vitest 4 (node env, TZ=UTC), zustand + zundo, TypeScript strict (`erasableSyntaxOnly`, `verbatimModuleSyntax`), oxlint.

**Spec:** [`docs/superpowers/specs/2026-07-16-experiment-studio-engine-parity-design.md`](../specs/2026-07-16-experiment-studio-engine-parity-design.md) §4 (W8). This plan implements §4 only; §5 (W9, repetition) is a separate plan.

## Global Constraints

- **Frontend gate (all of it must pass):** `cd webapp/frontend && npm run lint && npm run typecheck && npm test -- --run && npm run build`. Two known oxlint fast-refresh warnings are expected; exit code is still 0.
- **Do not touch the engine or the backend in W8.** `roles.py` is already at grammar parity (`roles.py:23` names compute/record/abort/alarm in `_LEAF_BLOCKS`) and there is a parity test at `webapp/backend/tests/test_roles.py:166`. If a backend test fails, you broke something — stop and report.
- **Emission rules mirror the engine serializer exactly** (`convert.ts:1-4`): omit empty `params`, omit null timing keys, `on_error` emitted **only** when it is `'continue'`, `else` omitted (not null) when absent.
- **`retry` is command/measure only** (engine design 2026-07-14 §2.1). None of the four new blocks gets a retry section. `Inspector.tsx:121` already gates this correctly — do not widen it.
- **`abort` must not offer `on_error`.** The engine forbids `on_error: "continue"` on an abort. Do not add a frontend check for the *tolerant-ancestor* rule — the backend validator owns it (spec §4.2).
- TypeScript strict everywhere. No `any`. No non-null assertions (`!`) — the codebase uses `??` and explicit narrowing.
- Commit after every task with the shown message.

---

### Task 1: Fold `sample_recorded` into the live chart

**Files:**
- Modify: `webapp/frontend/src/run/reducer.ts:46`
- Test: `webapp/frontend/src/run/reducer.test.ts`

**Interfaces:**
- Consumes: nothing (independent bug fix — ships first).
- Produces: nothing consumed by later tasks.

**Context:** `reducer.ts:46` folds only `measure_recorded` into `feed.samples`. A `record` block emits `sample_recorded` (engine `execute.py:691`) carrying the identical `{stream, value}` payload. `RunView.tsx:29-42` charts `feed.samples`, so a computed stream is currently invisible on the live chart, though it charts fine post-run via the CSV path (`records.py:193-211`). This is the spec §1.1 regression.

- [ ] **Step 1: Write the failing test**

Add to `webapp/frontend/src/run/reducer.test.ts`, inside the existing `describe('applyMessage', ...)`. Reuse the file's existing `ev(seq, kind, data, ts)` and `feedAll(msgs)` helpers (defined at the top of the file) — do not hand-roll message literals:

```ts
  it('folds sample_recorded (record blocks) into samples like measure_recorded', () => {
    const s = feedAll([
      ev(0, 'run_started', {}, 0),
      ev(1, 'measure_recorded', { stream: 'od_1', value: 0.4 }, 5),
      ev(2, 'sample_recorded', { stream: 'c_series_1', value: 1.25 }, 6),
      ev(3, 'sample_recorded', { stream: 'c_series_1', value: 1.4 }, 12),
    ])
    expect(s.samples.od_1).toEqual({ t: [5], v: [0.4] })
    expect(s.samples.c_series_1).toEqual({ t: [6, 12], v: [1.25, 1.4] })
  })
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd webapp/frontend && npm test -- --run reducer`
Expected: FAIL — `s.samples.c_series_1` is `undefined` (the key is never created).

- [ ] **Step 3: Write minimal implementation**

In `webapp/frontend/src/run/reducer.ts`, change line 46 from `if (msg.kind === 'measure_recorded') {` to:

```ts
  // Both carry {stream, value}: `measure_recorded` from a device read (execute.py:647),
  // `sample_recorded` from a `record` block's computed sample (execute.py:691). A stream is
  // measure XOR record in the engine, so the two can never collide on one series.
  if (msg.kind === 'measure_recorded' || msg.kind === 'sample_recorded') {
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd webapp/frontend && npm test -- --run reducer`
Expected: PASS, and every pre-existing reducer test still passes.

- [ ] **Step 5: Commit**

```bash
git add webapp/frontend/src/run/reducer.ts webapp/frontend/src/run/reducer.test.ts
git commit -m "fix(studio-frontend): chart record streams live (fold sample_recorded)"
```

---

### Task 2: Doc types and tree nodes for the four control blocks

**Files:**
- Modify: `webapp/frontend/src/types/doc.ts:55-82`
- Modify: `webapp/frontend/src/builder/tree.ts:8`, `:78-88`, `:288-312`
- Test: `webapp/frontend/src/builder/tree.test.ts`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `ComputeBody {into: string; value: ParamValue}`, `RecordBody {into: string; value: ParamValue}`, `AbortBody {if: string; message: string}`, `AlarmBody {if: string; message: string}` in `types/doc.ts`; `BlockJson` gains optional `compute`/`record`/`abort`/`alarm`.
  - `ComputeNode`, `RecordNode`, `AbortNode`, `AlarmNode` on the `BlockNode` union in `tree.ts`.
  - `ControlKind = 'compute' | 'record' | 'abort' | 'alarm'`; `PaletteKind = StructureKind | ControlKind`.
  - `newPaletteNode(kind: PaletteKind): BlockNode` — **renamed from `newStructureNode`**; all call sites updated in Task 6.

**Context:** `abort`/`alarm` use `if` in JSON but `condition` on the node, mirroring the existing `BranchNode.condition` ↔ `branch.if` convention (`convert.ts:141`, `tree.ts:73`). `value` is `ParamValue` (`number | string | boolean`) because the engine's `ValueExpr` is `str | int | float | bool` (`blocks.py:8`) — a compute value may be a bare literal, not only an expression string.

- [ ] **Step 1: Write the failing test**

Add to `webapp/frontend/src/builder/tree.test.ts`:

```ts
it('creates control-block nodes with no child slots', () => {
  for (const kind of ['compute', 'record', 'abort', 'alarm'] as const) {
    const node = newPaletteNode(kind)
    expect(node.kind).toBe(kind)
    expect(childSlots(node)).toEqual([])
    expect(node.label).toBeNull()
  }
})

it('seeds control blocks with empty, author-fillable fields', () => {
  expect(newPaletteNode('compute')).toMatchObject({ into: '', value: '' })
  expect(newPaletteNode('record')).toMatchObject({ into: '', value: '' })
  expect(newPaletteNode('abort')).toMatchObject({ condition: '', message: '' })
  expect(newPaletteNode('alarm')).toMatchObject({ condition: '', message: '' })
})
```

Update the existing `tree.test.ts` import to pull `newPaletteNode` instead of `newStructureNode`, and rename every existing `newStructureNode(` call in that file to `newPaletteNode(`.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd webapp/frontend && npm test -- --run tree`
Expected: FAIL — `newPaletteNode` is not exported.

- [ ] **Step 3: Write the implementation**

In `webapp/frontend/src/types/doc.ts`, add after `GroupRefBody` (`:55-57`):

```ts
/** compute binds a scalar into RunState.bindings; record appends a numeric sample to a
 * DECLARED stream. Both carry a ValueExpr (engine blocks.py:8 — str | int | float | bool),
 * so a bare literal is as legal as an expression string. */
export interface ComputeBody {
  into: string
  value: ParamValue
}

export interface RecordBody {
  into: string
  value: ParamValue
}

/** abort raises AbortSignalError (run status 'aborted'); alarm flags and continues. Both
 * require a non-empty message (engine design 2026-07-16 §2.1/§2.2). */
export interface AbortBody {
  if: string
  message: string
}

export interface AlarmBody {
  if: string
  message: string
}
```

And extend `BlockJson` (`:67-82`) with four keys after `group_ref`:

```ts
  compute?: ComputeBody
  record?: RecordBody
  abort?: AbortBody
  alarm?: AlarmBody
```

In `webapp/frontend/src/builder/tree.ts`, replace line 8 with:

```ts
export type StructureKind = 'serial' | 'parallel' | 'loop' | 'branch' | 'wait' | 'operator_input'
/** Leaf blocks that act on run state rather than on a device (Increments 6 and 8). None
 * takes retry — retry is command/measure only (design 2026-07-14 §2.1). */
export type ControlKind = 'compute' | 'record' | 'abort' | 'alarm'
export type PaletteKind = StructureKind | ControlKind
```

Add the four node interfaces after `BranchNode` (`:76`):

```ts
export interface ComputeNode extends NodeBase {
  kind: 'compute'
  into: string
  value: ParamValue
}

export interface RecordNode extends NodeBase {
  kind: 'record'
  into: string
  value: ParamValue
}

/** `condition` mirrors BranchNode.condition: the JSON key is `if` (a reserved word), and
 * convert.ts is the single place that translates. */
export interface AbortNode extends NodeBase {
  kind: 'abort'
  condition: string
  message: string
}

export interface AlarmNode extends NodeBase {
  kind: 'alarm'
  condition: string
  message: string
}
```

Extend the union (`:78-86`):

```ts
export type BlockNode =
  | CommandNode
  | MeasureNode
  | OperatorInputNode
  | WaitNode
  | SerialNode
  | ParallelNode
  | LoopNode
  | BranchNode
  | ComputeNode
  | RecordNode
  | AbortNode
  | AlarmNode
```

Rename `newStructureNode` to `newPaletteNode`, widen its parameter, and add the four cases:

```ts
export function newPaletteNode(kind: PaletteKind): BlockNode {
  const base = nodeBase()
  switch (kind) {
    case 'serial':
      return { ...base, kind, children: [] }
    case 'parallel':
      // Parallelism should be immediately visible (S1): start with two empty lanes.
      return {
        ...base,
        kind,
        children: [
          { ...nodeBase(), kind: 'serial', children: [] },
          { ...nodeBase(), kind: 'serial', children: [] },
        ],
      }
    case 'loop':
      return { ...base, kind, mode: 'count', count: 2, until: '', check: 'after', pace: null, body: [] }
    case 'branch':
      return { ...base, kind, condition: '', then: [], else: [] }
    case 'wait':
      return { ...base, kind, duration: '1s' }
    case 'operator_input':
      return { ...base, kind, name: 'value', inputType: 'float', prompt: null, min: null, max: null, choices: null }
    case 'compute':
    case 'record':
      return { ...base, kind, into: '', value: '' }
    case 'abort':
    case 'alarm':
      return { ...base, kind, condition: '', message: '' }
  }
}
```

`childSlots` (`:107-124`) already returns `[]` via its `default:` arm — do **not** add cases for the new kinds.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd webapp/frontend && npm test -- --run tree`
Expected: PASS. `npm run typecheck` will still fail — `newStructureNode` call sites in `BuilderTab.tsx:15,99` and `Canvas.tsx:8,195` are fixed in Task 6, and `convert.ts`/`summary.ts` are non-exhaustive until Tasks 3–4. That is expected; do not fix them here.

- [ ] **Step 5: Commit**

```bash
git add webapp/frontend/src/types/doc.ts webapp/frontend/src/builder/tree.ts webapp/frontend/src/builder/tree.test.ts
git commit -m "feat(studio-frontend): tree + doc types for compute/record/abort/alarm"
```

---

### Task 3: `convert.ts` round-trip and an exhaustive `nodeToBlock`

**Files:**
- Modify: `webapp/frontend/src/builder/convert.ts:5-16` (imports), `:89-158` (`blockToNode`), `:190-241` (`nodeToBlock`)
- Test: `webapp/frontend/src/builder/convert.test.ts`

**Interfaces:**
- Consumes: `ComputeNode`/`RecordNode`/`AbortNode`/`AlarmNode` and the `*Body` types from Task 2.
- Produces: `docToTree`/`treeToDoc` handling all twelve kinds; `nodeToBlock` made exhaustive via a `never` check.

**Context:** `nodeToBlock` is a `switch` with no `default`. It is safe today only because `BlockNode` cannot represent the newer kinds; now that the union has grown, a missing arm would silently emit a block with **zero type keys**, which the engine rejects at `serialize.py:277` with a message that blames the document rather than the builder (spec §6). The `never` check turns the next omission into a compile error.

- [ ] **Step 1: Write the failing test**

Add to `webapp/frontend/src/builder/convert.test.ts`:

```ts
describe('control blocks', () => {
  const doc = (blocks: BlockJson[]): ExperimentDocJson => ({
    doc_version: 1,
    name: 'control',
    description: null,
    roles: {},
    workflow: {
      schema_version: 1,
      metadata: { name: 'control' },
      persistence: { default: 'in_memory', format: 'jsonl' },
      streams: { c_series: { units: null } },
      blocks,
    },
  })

  const BLOCKS: BlockJson[] = [
    { compute: { into: 'c', value: 'c * 0.9' } },
    { record: { into: 'c_series', value: 'c' } },
    { abort: { if: 'emergency_stop', message: 'operator emergency stop' } },
    { alarm: { if: 'od > 2.0', message: 'tube 1 contaminated' }, on_error: 'continue' },
  ]

  it('round-trips every control block byte-for-byte', () => {
    const input = doc(BLOCKS)
    expect(treeToDoc(docToTree(input))).toEqual(input)
  })

  it('parses control blocks into their node shapes', () => {
    const tree = docToTree(doc(BLOCKS)).tree
    expect(tree[0]).toMatchObject({ kind: 'compute', into: 'c', value: 'c * 0.9' })
    expect(tree[1]).toMatchObject({ kind: 'record', into: 'c_series', value: 'c' })
    expect(tree[2]).toMatchObject({
      kind: 'abort',
      condition: 'emergency_stop',
      message: 'operator emergency stop',
    })
    expect(tree[3]).toMatchObject({ kind: 'alarm', condition: 'od > 2.0', onError: 'continue' })
  })

  it('keeps a literal compute value a number, not a string', () => {
    const tree = docToTree(doc([{ compute: { into: 'V', value: 12 } }])).tree
    expect((tree[0] as ComputeNode).value).toBe(12)
    expect(nodeToBlock(tree[0])).toEqual({ compute: { into: 'V', value: 12 } })
  })
})
```

Add `ComputeNode` to the `./tree` type import at the top of the file.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd webapp/frontend && npm test -- --run convert`
Expected: FAIL — `DocConvertError: unsupported block type 'compute' in the builder`.

- [ ] **Step 3: Write the implementation**

In `convert.ts`, extend the type import (`:5-16`) with `AbortBody`, `AlarmBody`, `ComputeBody`, `RecordBody` (keep the list alphabetical, matching the existing style).

Replace the `case 'for_each':` / `case 'abort': case 'alarm':` block (`:147-155`) with arms for the four supported kinds, keeping `for_each` and `group_ref` degrading:

```ts
    case 'compute': {
      const b = block.compute as ComputeBody
      return { ...base, kind, into: b.into, value: b.value }
    }
    case 'record': {
      const b = block.record as RecordBody
      return { ...base, kind, into: b.into, value: b.value }
    }
    case 'abort': {
      const b = block.abort as AbortBody
      return { ...base, kind, condition: b.if, message: b.message }
    }
    case 'alarm': {
      const b = block.alarm as AlarmBody
      return { ...base, kind, condition: b.if, message: b.message }
    }
    case 'for_each':
      throw new DocConvertError(
        'for_each is not yet supported in the builder (author it as JSON; it runs and charts)',
      )
    case 'group_ref':
      throw new DocConvertError(
        'group_ref is not yet supported in the builder (author it as JSON; it runs and charts)',
      )
    default:
      throw new DocConvertError(`unsupported block type '${kind}' in the builder`)
```

In `nodeToBlock` (`:190-241`), add four arms before the closing brace of the switch:

```ts
    case 'compute':
      out.compute = { into: node.into, value: node.value }
      break
    case 'record':
      out.record = { into: node.into, value: node.value }
      break
    case 'abort':
      out.abort = { if: node.condition, message: node.message }
      break
    case 'alarm':
      out.alarm = { if: node.condition, message: node.message }
      break
    default: {
      // Exhaustiveness guard: a BlockNode kind with no arm here would emit a block with
      // zero type keys, which the engine rejects at serialize.py:277 blaming the document
      // rather than the builder. Keep this a compile error instead (design §6).
      const unreachable: never = node
      throw new DocConvertError(`unserializable block node ${JSON.stringify(unreachable)}`)
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd webapp/frontend && npm test -- --run convert`
Expected: PASS, including the pre-existing golden-fixture round-trip test.

- [ ] **Step 5: Commit**

```bash
git add webapp/frontend/src/builder/convert.ts webapp/frontend/src/builder/convert.test.ts
git commit -m "feat(studio-frontend): convert control blocks; make nodeToBlock exhaustive"
```

---

### Task 4: Canvas summaries for the control blocks

**Files:**
- Modify: `webapp/frontend/src/builder/summary.ts:28-52`
- Test: `webapp/frontend/src/builder/summary.test.ts`

**Interfaces:**
- Consumes: the node types from Task 2.
- Produces: `blockSummary` arms for all twelve kinds.

**Context:** `summary.ts:13-20` records why `R×N` was chosen over a circular arrow: `↻ Loop ×3 ↻2` put two near-identical arrows side by side and was unreadable. **No new glyph may reintroduce an arrow collision** — hence `ƒ`, `✎`, `⛔`, `⚠`, none of which is an arrow. `blockSummary` has no `default` arm, so a missing case is already a compile error once the union grows.

- [ ] **Step 1: Write the failing test**

Add to `webapp/frontend/src/builder/summary.test.ts`:

Add these inside the existing `describe('blockSummary', ...)`. The file already declares `const base = { label: null, gapAfter: null, startOffset: null }` at module scope (note: **no `uid`**) — reuse it and supply `uid` inline. Do **not** redeclare `base`; that is a TypeScript redeclaration error.

```ts
  it('summarises control blocks', () => {
    expect(blockSummary({ uid: 'u', kind: 'compute', into: 'c', value: 'c * 0.9', ...base })).toBe(
      'ƒ c = c * 0.9',
    )
    expect(blockSummary({ uid: 'u', kind: 'record', into: 'c_series', value: 'c', ...base })).toBe(
      '✎ c_series ← c',
    )
    expect(
      blockSummary({ uid: 'u', kind: 'abort', condition: 'estop', message: 'stop', ...base }),
    ).toBe('⛔ Abort if estop')
    expect(
      blockSummary({ uid: 'u', kind: 'alarm', condition: 'od > 2', message: 'bad', ...base }),
    ).toBe('⚠ Alarm if od > 2')
  })

  it('shows a placeholder for an unfilled control block and keeps the fault marker', () => {
    expect(blockSummary({ uid: 'u', kind: 'compute', into: '', value: '', ...base })).toBe('ƒ ? = …')
    expect(
      blockSummary({
        uid: 'u',
        kind: 'alarm',
        condition: 'x',
        message: 'm',
        onError: 'continue',
        ...base,
      }),
    ).toBe('⚠ Alarm if x ⤳')
  })
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd webapp/frontend && npm test -- --run summary`
Expected: FAIL — `blockSummary` returns `undefined` for the new kinds.

- [ ] **Step 3: Write the implementation**

In `summary.ts`, add four cases to `blockSummary` before the closing brace, mirroring the existing `|| '…'` / `|| '?'` placeholder idiom used by `measure` (`:36`) and `branch` (`:50`):

```ts
    case 'compute':
      return `ƒ ${node.into || '?'} = ${String(node.value) || '…'}${marker}`
    case 'record':
      return `✎ ${node.into || '?'} ← ${String(node.value) || '…'}${marker}`
    case 'abort':
      return `⛔ Abort if ${node.condition || '…'}${marker}`
    case 'alarm':
      return `⚠ Alarm if ${node.condition || '…'}${marker}`
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd webapp/frontend && npm test -- --run summary`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add webapp/frontend/src/builder/summary.ts webapp/frontend/src/builder/summary.test.ts
git commit -m "feat(studio-frontend): canvas summaries for control blocks"
```

---

### Task 5: Reference plumbing — compute bindings and record streams

**Files:**
- Modify: `webapp/frontend/src/builder/refs.ts:31-37` (`countStreamRefs`), `:39-43` (`renameStreamRefs`), `:45-55` (`collectBindings`)
- Modify: `webapp/frontend/src/builder/fields.tsx:169`
- Test: `webapp/frontend/src/builder/refs.test.ts`

**Interfaces:**
- Consumes: the node types from Task 2.
- Produces: `countStreamRefs`/`renameStreamRefs` counting and rewriting `record.into`; `collectBindings` collecting `compute.into`.

**Context (two latent bugs that go live the moment control blocks are authorable — spec §4.4):**
1. `collectBindings` collects only `operator_input` names, but a `compute.into` is a binding readable by later expressions (engine `blocks.py:96`). Without this, `exprHelp` omits exactly the bindings the author just created.
2. `countStreamRefs` counts only `measure` blocks. `docStore.removeStream` refuses deletion while references exist — so a stream fed only by a `record` block reports **0 references** and is silently deleted, orphaning the block. `renameStreamRefs` has the same hole: renaming a record-only stream would leave the `record.into` pointing at a stream that no longer exists.

- [ ] **Step 1: Write the failing test**

Add to `webapp/frontend/src/builder/refs.test.ts`:

The file already declares `const base = { label: null, gapAfter: null, startOffset: null }` at module scope (**no `uid`**) plus `cmd`/`meas` factories — reuse `base` and add two factories beside them. Do **not** redeclare `base`. Extend the `./tree` type import with `ComputeNode` and `RecordNode`, and the `./refs` import with `streamSources` (used in Task 8).

```ts
const rec = (uid: string, into: string): RecordNode => ({
  uid, kind: 'record', into, value: 'c', ...base,
})
const comp = (uid: string, into: string, value: string): ComputeNode => ({
  uid, kind: 'compute', into, value, ...base,
})
```

Then, as new `it` blocks in the existing `describe`:

```ts
  it('counts a record block as a stream reference', () => {
    const t: BlockNode[] = [rec('r1', 'c_series')]
    expect(countStreamRefs(t, 'c_series')).toBe(1)
    expect(countStreamRefs(t, 'other')).toBe(0)
  })

  it('renames record stream references', () => {
    const out = renameStreamRefs([rec('r1', 'c_series')], 'c_series', 'conc')
    expect((out[0] as RecordNode).into).toBe('conc')
  })

  it('collects compute targets as bindings alongside operator inputs', () => {
    const t: BlockNode[] = [
      {
        uid: 'oi1', kind: 'operator_input', name: 'od_min', inputType: 'float',
        prompt: null, min: null, max: null, choices: null, ...base,
      },
      comp('k1', 'c', '0'),
      comp('k2', 'c', 'c * 0.9'),
    ]
    // 'c' is written by two computes (the seed-then-accumulate idiom) and must de-duplicate.
    expect(collectBindings(t)).toEqual(['od_min', 'c'])
  })
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd webapp/frontend && npm test -- --run refs`
Expected: FAIL — `countStreamRefs` returns 0; `collectBindings` returns `['od_min']`.

- [ ] **Step 3: Write the implementation**

In `refs.ts`, replace `countStreamRefs`, `renameStreamRefs`, and `collectBindings`:

```ts
/** A stream is written by `measure` XOR `record` (engine Increment 6). Both must count, or
 * deleting a record-only stream reports 0 refs and silently orphans the record block. */
export function countStreamRefs(tree: BlockNode[], stream: string): number {
  let count = 0
  visitNodes(tree, (node) => {
    if ((node.kind === 'measure' || node.kind === 'record') && node.into === stream) count++
  })
  return count
}

export function renameStreamRefs(tree: BlockNode[], from: string, to: string): BlockNode[] {
  return mapNodes(tree, (node) =>
    (node.kind === 'measure' || node.kind === 'record') && node.into === from
      ? { ...node, into: to }
      : node,
  )
}

/** Bindings are written by `operator_input` and by `compute` (engine blocks.py:96) — both
 * land in the same RunState.bindings namespace, so expression help must offer both. The
 * seed-then-accumulate idiom writes one name from several computes, hence the de-dup. */
export function collectBindings(tree: BlockNode[]): string[] {
  const seen = new Set<string>()
  const out: string[] = []
  visitNodes(tree, (node) => {
    const name =
      node.kind === 'operator_input' ? node.name : node.kind === 'compute' ? node.into : null
    if (name && !seen.has(name)) {
      seen.add(name)
      out.push(name)
    }
  })
  return out
}
```

In `fields.tsx:169`, the help popover label is now wrong — `collectBindings` no longer returns operator inputs only. Change:

```tsx
          <p className="font-semibold text-slate-600">Bindings (operator inputs)</p>
```

to:

```tsx
          <p className="font-semibold text-slate-600">Bindings</p>
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd webapp/frontend && npm test -- --run refs && npm test -- --run exprHelp`
Expected: PASS both.

- [ ] **Step 5: Commit**

```bash
git add webapp/frontend/src/builder/refs.ts webapp/frontend/src/builder/refs.test.ts webapp/frontend/src/builder/fields.tsx
git commit -m "feat(studio-frontend): count record stream refs; collect compute bindings"
```

---

### Task 6: Palette chips and drag wiring

**Files:**
- Modify: `webapp/frontend/src/builder/dnd.ts:3-8`
- Modify: `webapp/frontend/src/builder/Palette.tsx:5`, `:10-17`, `:104-119`
- Modify: `webapp/frontend/src/builder/BuilderTab.tsx:15`, `:33-35`, `:98-99`
- Modify: `webapp/frontend/src/builder/Canvas.tsx:8`, `:195`
- Modify: `webapp/frontend/src/stores/docStore.test.ts:3`, `:43`, `:52`, `:58`, `:212`, `:214`
- Test: `webapp/frontend/src/builder/dnd.test.ts`, `webapp/frontend/src/stores/docStore.test.ts` (existing tests must keep passing)

**Interfaces:**
- Consumes: `PaletteKind`, `ControlKind`, `newPaletteNode` from Task 2.
- Produces: a **Control** palette section whose chips drop real nodes onto the canvas.

**Context:** The four leaves reuse the existing `palette-structure` drag path rather than adding a second one — only the kind union widens. The wire string `'palette-structure'` is deliberately **not** renamed: it is an internal dnd-kit `data` discriminator, `dnd.test.ts` may assert it, and renaming buys nothing.

- [ ] **Step 1: Widen the drag payload**

In `dnd.ts`, change the import on line 3 and the payload on line 6:

```ts
import type { PaletteKind, SlotRef } from './tree'

export type DragPayload =
  | { source: 'palette-structure'; kind: PaletteKind }
```

- [ ] **Step 2: Add the Control palette section**

In `Palette.tsx`, change the import on line 5 to `import type { ControlKind, StructureKind } from './tree'`, and add after the `STRUCTURE` array (`:10-17`):

```tsx
const CONTROL: Array<{ kind: ControlKind; title: string; icon: string }> = [
  { kind: 'compute', title: 'Compute', icon: 'ƒ' },
  { kind: 'record', title: 'Record', icon: '✎' },
  { kind: 'alarm', title: 'Alarm', icon: '⚠' },
  { kind: 'abort', title: 'Abort', icon: '⛔' },
]
```

Add a `Section` after the existing Structure section (`:106-119`), reusing `Chip` unchanged:

```tsx
      <Section title="Control">
        <div className="flex flex-wrap gap-1">
          {CONTROL.map((c) => (
            <Chip
              key={c.kind}
              id={`palette-control-${c.kind}`}
              payload={{ source: 'palette-structure', kind: c.kind }}
            >
              <span className="mr-1 opacity-60">{c.icon}</span>
              {c.title}
            </Chip>
          ))}
        </div>
      </Section>
```

- [ ] **Step 3: Update the three files that still call `newStructureNode`**

Task 2 renamed `newStructureNode` → `newPaletteNode` without a back-compat alias. **Confirm the full set before editing** — the original plan text said "two call sites" and was wrong, which left `docStore.test.ts` red with no owner:

```bash
grep -rn "newStructureNode" webapp/frontend/src/
```

Expect exactly three files: `BuilderTab.tsx`, `Canvas.tsx`, and `stores/docStore.test.ts`. In `docStore.test.ts` the change is purely mechanical — the import on `:3` and the five calls at `:43`, `:52`, `:58`, `:212`, `:214` become `newPaletteNode`, with no other edit. Those four tests are currently **failing at runtime** (`TypeError: newStructureNode is not a function`); this step is what makes them green again. Unlike the `tsc`-only breaks Task 2 deliberately left, that one is a real test failure.

In `BuilderTab.tsx`: line 15 becomes `import { findNode, newPaletteNode, newVerbNode } from './tree'`; line 99 becomes `s.insertBlock(newPaletteNode(payload.kind), at)`.

`STRUCTURE_TITLES` (`:24-31`, used by `dragLabel` at `:34` for the drag overlay) is already typed `Record<string, string>` with a `?? payload.kind` fallback, so it needs **no retype** — only four entries, so a dragged chip reads "Compute" rather than "compute":

```ts
const STRUCTURE_TITLES: Record<string, string> = {
  serial: 'Serial',
  parallel: 'Parallel',
  loop: 'Loop',
  branch: 'Branch',
  wait: 'Wait',
  operator_input: 'Operator input',
  compute: 'Compute',
  record: 'Record',
  abort: 'Abort',
  alarm: 'Alarm',
}
```

In `Canvas.tsx`: line 8 becomes `import { newPaletteNode, type BlockNode, type BranchNode, type ParallelNode } from './tree'`; line 195 becomes `insertBlock(newPaletteNode('serial'), {`.

- [ ] **Step 4: Run the full frontend gate**

Run: `cd webapp/frontend && npm run typecheck && npm test -- --run`
Expected: PASS — this is the first task at which typecheck is clean again (Task 2 knowingly left it red).

- [ ] **Step 5: Commit**

```bash
git add webapp/frontend/src/builder/dnd.ts webapp/frontend/src/builder/Palette.tsx webapp/frontend/src/builder/BuilderTab.tsx webapp/frontend/src/builder/Canvas.tsx
git commit -m "feat(studio-frontend): Control palette section for compute/record/abort/alarm"
```

---

### Task 7: Inspector editors

**Files:**
- Modify: `webapp/frontend/src/builder/Inspector.tsx:29-38` (`KIND_TITLES`), `:72-124` (`BlockForm`), `:235-253` (`KindBody`)
- Test: none (React glue; the pure helpers it calls are already covered — this matches the existing W3–W6 convention of not component-testing the Inspector)

**Interfaces:**
- Consumes: `ComputeNode`, `RecordNode`, `AbortNode`, `AlarmNode` from Task 2; `patchBlock` from `docStore`.
- Produces: editors for all four kinds; `abort` renders **no** On-error row.

**Context:** `record.into` is a **picker over declared streams**, not free text — the engine requires the stream to be declared, and a typo would otherwise surface only at validation. `abort` gets no On-error control: the engine forbids `on_error: "continue"` on an abort, so the only non-default value always produces an invalid document (spec §4.2).

- [ ] **Step 1: Add the titles**

In `Inspector.tsx`, extend `KIND_TITLES` (`:29-38`):

```ts
  compute: 'Compute',
  record: 'Record',
  abort: 'Abort',
  alarm: 'Alarm',
```

- [ ] **Step 2: Suppress the On-error row for `abort`**

In `BlockForm` (`:72-124`), the On-error `FieldRow` at `:111-120` is currently unconditional. Wrap it:

```tsx
      {node.kind !== 'abort' && (
        <FieldRow label="On error">
          <select
            value={node.onError ?? 'fail'}
            onChange={(e) => patchBlock(node.uid, { onError: e.target.value as 'fail' | 'continue' })}
            className="w-full rounded border border-slate-300 px-1 py-0.5 text-xs"
          >
            <option value="fail">fail (stop the run)</option>
            <option value="continue">continue (tolerate the failure)</option>
          </select>
        </FieldRow>
      )}
```

Add this comment directly above the wrapped row:

```tsx
      {/* abort forbids on_error: "continue" — tolerating a safety stop is a contradiction
          (engine design 2026-07-16 §2.1), so the control is omitted rather than offered and
          rejected. The related rule (an abort may have no tolerant ANCESTOR) is the backend
          validator's; it surfaces as a diagnostic, not as a second frontend opinion. */}
```

- [ ] **Step 3: Add the four `KindBody` arms and their forms**

In `KindBody` (`:235-253`):

```tsx
    case 'compute':
    case 'record':
      return <ValueForm node={node} />
    case 'abort':
    case 'alarm':
      return <ConditionForm node={node} />
```

Add these two components after `BranchForm` (find it; place them adjacent to the other `*Form` components):

```tsx
/** compute writes a binding; record appends to a DECLARED stream — hence the picker rather
 * than a text field: an undeclared name is a validation error the author would otherwise
 * only meet at save time. */
function ValueForm({ node }: { node: ComputeNode | RecordNode }) {
  const patchBlock = useDocStore((s) => s.patchBlock)
  const streams = useDocStore((s) => s.streams)
  const streamNames = Object.keys(streams)
  return (
    <div>
      {node.kind === 'compute' ? (
        <FieldRow label="Into (binding)" required>
          <TextField
            mono
            value={node.into}
            onCommit={(v) => patchBlock(node.uid, { into: v })}
            placeholder="c_1"
          />
        </FieldRow>
      ) : (
        <FieldRow label="Into (stream)" required>
          <select
            value={node.into}
            onChange={(e) => patchBlock(node.uid, { into: e.target.value })}
            className="w-full rounded border border-slate-300 px-1 py-0.5 font-mono text-xs"
          >
            <option value="">stream…</option>
            {streamNames.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
          {streamNames.length === 0 && (
            <p className="mt-1 text-xs text-amber-600">
              No streams declared — add one in the Streams panel.
            </p>
          )}
        </FieldRow>
      )}
      <FieldRow label="Value" required>
        <ExpressionInput
          value={String(node.value)}
          onCommit={(v) => patchBlock(node.uid, { value: v })}
        />
      </FieldRow>
    </div>
  )
}

function ConditionForm({ node }: { node: AbortNode | AlarmNode }) {
  const patchBlock = useDocStore((s) => s.patchBlock)
  return (
    <div>
      <FieldRow label="If" required>
        <ExpressionInput
          value={node.condition}
          onCommit={(v) => patchBlock(node.uid, { condition: v })}
          placeholder="contaminated_1"
        />
      </FieldRow>
      <FieldRow label="Message" required>
        <TextField
          value={node.message}
          onCommit={(v) => patchBlock(node.uid, { message: v })}
          placeholder={node.kind === 'abort' ? 'why the run must stop' : 'what to flag'}
        />
      </FieldRow>
      <p className="mt-1 text-xs text-slate-400">
        {node.kind === 'abort'
          ? 'True stops the run: devices are swept safe and the run ends "aborted".'
          : 'True flags the run and continues. Fires every time it holds — latch it with a compute if you want it once.'}
      </p>
    </div>
  )
}
```

Extend the `./tree` type import at the top of `Inspector.tsx` with `AbortNode`, `AlarmNode`, `ComputeNode`, `RecordNode`.

- [ ] **Step 4: Run the frontend gate**

Run: `cd webapp/frontend && npm run typecheck && npm run lint && npm test -- --run`
Expected: PASS (two known oxlint fast-refresh warnings, exit 0).

- [ ] **Step 5: Commit**

```bash
git add webapp/frontend/src/builder/Inspector.tsx
git commit -m "feat(studio-frontend): Inspector editors for compute/record/abort/alarm"
```

---

### Task 8: Stream source tags in the Streams panel

**Files:**
- Modify: `webapp/frontend/src/builder/StreamsPanel.tsx:4-5` (the stale comment), and the `<li>` row
- Test: `webapp/frontend/src/builder/refs.test.ts`

**Interfaces:**
- Consumes: `countStreamRefs` (Task 5), `visitNodes` from `tree.ts`.
- Produces: `streamSources(tree: BlockNode[]): Record<string, 'measure' | 'record'>` exported from `refs.ts`.

**Context:** The engine enforces a stream is `measure` XOR `record` (Increment 6 disjointness). Surfacing the writer at authoring time makes that rule visible where it is violated, rather than at validation. Put the pure function in `refs.ts` so it is testable; `StreamsPanel` stays glue.

- [ ] **Step 1: Write the failing test**

Add to `webapp/frontend/src/builder/refs.test.ts`:

Reuse the `meas` factory the file already declares and the `rec` factory added in Task 5:

```ts
  it('reports which block kind writes each stream', () => {
    const t: BlockNode[] = [meas('m1', 'od_meter', 'od'), rec('r1', 'c_series')]
    expect(streamSources(t)).toEqual({ od: 'measure', c_series: 'record' })
  })

  it('omits streams nothing writes', () => {
    expect(streamSources([])).toEqual({})
  })
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd webapp/frontend && npm test -- --run refs`
Expected: FAIL — `streamSources` is not exported.

- [ ] **Step 3: Write the implementation**

Append to `refs.ts`:

```ts
/** Which block kind writes each stream. The engine enforces measure XOR record per stream
 * (Increment 6), so a stream has at most one writer kind; on a doc that violates it, first
 * writer seen wins and the backend validator reports the real error. */
export function streamSources(tree: BlockNode[]): Record<string, 'measure' | 'record'> {
  const out: Record<string, 'measure' | 'record'> = {}
  visitNodes(tree, (node) => {
    if ((node.kind === 'measure' || node.kind === 'record') && node.into && !(node.into in out)) {
      out[node.into] = node.kind
    }
  })
  return out
}
```

In `StreamsPanel.tsx`, replace the stale comment (`:4-5`) with:

```tsx
/** Streams are name + units only (settled decision S5) — per-stream persistence is carried
 * opaquely through convert.ts but has no UI, and the backend forces disk persistence on
 * every run. The source tag shows the stream's writer: measure XOR record (Increment 6). */
```

Add the import `import { streamSources } from './refs'`, and inside the component (beside the other `useDocStore` selectors, ~`:7-11`):

```tsx
  const tree = useDocStore((s) => s.tree)
  const sources = streamSources(tree)
```

Then insert the tag into the `<li>` (`:39`) **between the name button/input and the units input** — i.e. directly after the `{editing === name ? (...) : (...)}` ternary closes at `:74` and before the units `<input>` at `:75`:

```tsx
            <span
              title={
                sources[name] === undefined
                  ? 'No block writes this stream'
                  : `Written by a ${sources[name]} block`
              }
              className="shrink-0 rounded bg-slate-200 px-1 text-xs text-slate-500"
            >
              {sources[name] ?? 'unused'}
            </span>
```

The `title` is not decoration: an `unused` tag with no explanation reads as an error rather than as information (the same readability failure the W7 review caught, where a bare `truncate` hid the note explaining a success).

- [ ] **Step 4: Run test to verify it passes**

Run: `cd webapp/frontend && npm test -- --run refs && npm run typecheck`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add webapp/frontend/src/builder/refs.ts webapp/frontend/src/builder/refs.test.ts webapp/frontend/src/builder/StreamsPanel.tsx
git commit -m "feat(studio-frontend): show each stream's writer (measure/record/unused)"
```

---

### Task 9: End-to-end fixture and full gate

**Files:**
- Create: `webapp/fixtures/valid-control-blocks.json`
- Modify: `webapp/frontend/src/builder/convert.test.ts`

**Interfaces:**
- Consumes: everything above.
- Produces: a committed fixture proving a control-block document survives the full round trip.

**Context:** The W7 review found that deep-equal is **blind to `6.0` vs `6` and to key order** — a `toEqual` round-trip test can pass while the emitted bytes differ. The existing golden test compares parsed objects; this one additionally pins key order via `JSON.stringify`, which is what actually reaches the backend.

- [ ] **Step 1: Create the fixture**

Create `webapp/fixtures/valid-control-blocks.json`. Key order must match `treeToDoc`'s emission order exactly (`doc_version`, `name`, `description`, `roles`, `workflow`; and within workflow: `schema_version`, `metadata`, `persistence`, `streams`, `blocks`):

```json
{
  "doc_version": 1,
  "name": "Control blocks",
  "description": "Exercises compute, record, abort and alarm end to end.",
  "roles": {
    "od_meter": { "type": "densitometer" }
  },
  "workflow": {
    "schema_version": 1,
    "metadata": { "name": "Control blocks" },
    "persistence": { "default": "in_memory", "format": "jsonl" },
    "streams": {
      "od": { "units": "AU" },
      "c_series": { "units": "mg/L" }
    },
    "blocks": [
      { "compute": { "into": "V", "value": 12 } },
      { "compute": { "into": "c", "value": 0 } },
      { "operator_input": { "name": "emergency_stop", "type": "bool" } },
      { "abort": { "if": "emergency_stop", "message": "operator emergency stop" } },
      {
        "loop": {
          "body": [
            { "measure": { "device": "od_meter", "verb": "measure", "into": "od" }, "on_error": "continue" },
            { "compute": { "into": "c", "value": "c * V / (V + 1)" } },
            { "record": { "into": "c_series", "value": "c" } },
            { "alarm": { "if": "count(od, last=45s) > 0 and last(od) > 2.0", "message": "tube contaminated" } }
          ],
          "count": 3,
          "pace": "60s"
        }
      }
    ]
  }
}
```

- [ ] **Step 2: Write the failing test**

Add to `convert.test.ts`:

```ts
it('round-trips the control-blocks fixture with identical bytes', () => {
  const input = fixture('valid-control-blocks')
  // Deep-equal is blind to 6.0 vs 6 and to key order (W7 review); compare serialised bytes,
  // which is what actually reaches the backend.
  expect(JSON.stringify(treeToDoc(docToTree(input)))).toBe(JSON.stringify(input))
})
```

- [ ] **Step 3: Run test to verify it passes**

Run: `cd webapp/frontend && npm test -- --run convert`
Expected: PASS. **If it fails on key order**, fix the *fixture*'s key order to match `treeToDoc`'s emission order — do not reorder `treeToDoc`, whose order mirrors the engine serializer.

- [ ] **Step 4: Run the complete gate**

Run: `cd webapp/frontend && npm run lint && npm run typecheck && npm test -- --run && npm run build`
Expected: all pass (two known oxlint fast-refresh warnings, exit 0).

Then confirm nothing upstream broke:

Run: `cd webapp/backend && .venv/bin/python -m pytest -q && .venv/bin/python -m mypy && .venv/bin/python -m ruff check .`
Expected: all pass, 147+ tests. (`mypy` takes **no** path argument.)

- [ ] **Step 5: Commit**

```bash
git add webapp/fixtures/valid-control-blocks.json webapp/frontend/src/builder/convert.test.ts
git commit -m "test(studio-frontend): byte-exact round-trip fixture for control blocks"
```

---

### Task 10: Real-browser verification

**Files:**
- Create: scratchpad playwright script (not committed)

**Interfaces:**
- Consumes: everything above.
- Produces: evidence the canvas actually authors a runnable control-block document.

**Context:** The proven W5 recipe (memory: *experiment-studio-increments*): run `webapp/backend/tests/devserver.py` + `npm run dev`, seed a doc via `POST /api/experiments`, drive with a scratchpad playwright script. No drags are needed to verify Inspector/summary rendering — seed the doc and open it.

- [ ] **Step 1: Start the dev stack**

```bash
cd webapp/backend && .venv/bin/python tests/devserver.py &
cd webapp/frontend && npm run dev &
```

- [ ] **Step 2: Seed the fixture and open it in the builder**

`POST` `webapp/fixtures/valid-control-blocks.json` to `/api/experiments`, then open the builder and load it via the Load dialog.

- [ ] **Step 3: Verify, and capture evidence**

Confirm all of the following, and screenshot the canvas:
- The doc **opens** (no `DocConvertError` note).
- Canvas shows `ƒ V = 12`, `ƒ c = 0`, `⛔ Abort if emergency_stop`, and inside the loop `✎ c_series ← c` and `⚠ Alarm if …`.
- Selecting the **abort** block shows **no On-error row**; selecting the **alarm** block **does**.
- Selecting the **record** block shows a stream *picker* listing `od` and `c_series`.
- The expression help popover (`ƒ` button) lists `V` and `c` under **Bindings**.
- Streams panel tags `od` as `measure` and `c_series` as `record`.
- `POST /api/validate` for the doc returns `ok: true`.
- Save, reload the page, reopen: the doc is unchanged.

- [ ] **Step 4: Report**

Report what was observed. **If any check fails, stop and report rather than patching over it** — a failure here means an earlier task's deliverable is wrong.

- [ ] **Step 5: Commit**

Nothing to commit (scratchpad only). Confirm `git status` is clean.

---

## Definition of done

- All ten tasks committed.
- Frontend gate green: `npm run lint && npm run typecheck && npm test -- --run && npm run build`.
- Backend gate green (unchanged by this work): `pytest`, `mypy` (no path arg), `ruff check .`.
- A canvas-authored document containing `compute`, `record`, `abort`, and `alarm` saves, validates, and round-trips byte-for-byte (spec §8, W8 acceptance).
- A `record` stream appears on the **live** chart during a run (spec §8; Task 1 is the regression test).
- **Deferred to W9 by design:** `for_each`, `groups`/`group_ref`, the diagnostic source map, and `paths.ts` group-scope resolution. `examples/morbidostat.json` still does not open in the builder after W8 — that is W9's acceptance criterion, not this plan's.
