# Element Library Taxonomy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Re-cut the Builder palette's Structure/Control/Repeat block sections into Flow/Data/Pause/Safety, and move `group_ref` out of the block sections into per-group draggable chips in the Groups panel.

**Architecture:** Presentation-only change. The twelve block kinds, their JSON serialization, the engine AST, and every saved document are untouched — only which section a chip appears in, what the sections are called, and where a `group_ref` is dragged from. The kind types in `tree.ts` are renamed to match the new sections (their old names are the source of the confusion being fixed), and the chip arrays move to a pure `paletteSections.ts` module so they can be unit-tested without rendering React.

**Tech Stack:** TypeScript, React 19, @dnd-kit/core, zustand, vitest (node env), Tailwind 4, lucide-react.

**Spec:** `docs/superpowers/specs/2026-07-18-element-library-taxonomy-design.md`

## Global Constraints

Every task's requirements implicitly include these. Sources: `webapp/frontend/CLAUDE.md` and the spec.

- **All work happens in `webapp/frontend/`.** Run every command from that directory.
- **Icons come from `lucide-react` only.** An icon-only action must render through `IconButton` (`src/ui/IconButton.tsx`) — it is what enforces the ≥24×24px hit area, contrast, and `title`/`aria-label`. No raw glyph characters for interactive controls.
- **Controls on a shared visual line must agree in height to within 1px.** The probe's R4 `sibling-height-mismatch` rule (`tools/probe.mjs`) enforces this. `IconButton` renders at 24px, so anything placed beside one must too.
- **Never concatenate a width class.** `controlClass({ width: 'w-28' })`, not `controlClass() + ' w-28'` — `w-full` sorts last in the compiled stylesheet and silently wins.
- **Text colors:** `text-caption` (slate-600) for meaning-carrying secondary text; `text-hint` (slate-500) for incidental placeholder/empty-state text.
- **vitest runs in a node environment.** Pure functions only — no component rendering, no jsdom, no `@testing-library`. A test must never import a `.tsx` file.
- **No persisted format changes.** If `convert.test.ts` or `tree.test.ts` needs editing to pass, the change has leaked past presentation and is wrong.
- **Commit after every task.** Conventional Commits; scope `studio`.

## File Structure

| File | Status | Responsibility |
|---|---|---|
| `src/builder/tree.ts` | Modify | Kind types renamed to match sections; gains `newGroupRefNode`. |
| `src/builder/dnd.ts` | Modify | `palette-structure` → `palette-block`; new `palette-group` payload variant. |
| `src/builder/BuilderTab.tsx` | Modify | `BLOCK_TITLES` rename; drag-overlay and drop arms for `palette-group`. |
| `src/builder/paletteSections.ts` | **Create** | The four block sections as plain data. No React — this is what makes the partition test possible. |
| `src/builder/paletteSections.test.ts` | **Create** | Asserts the sections partition `PaletteKind` minus `group_ref`. |
| `src/builder/Palette.tsx` | Modify | Renders the four sections from `BLOCK_SECTIONS`; `GroupsPanel` gains draggable per-group chips. |
| `src/builder/tree.test.ts` | Modify | Adds `newGroupRefNode` coverage. |

Task order is chosen so the app never regresses: the payload plumbing lands first (Task 1), the Groups panel gains its chips second (Task 2), and only then do the block sections drop the now-redundant `Group ref` chip (Task 3).

---

### Task 1: Drag payload plumbing

Renames the `palette-structure` drag source to `palette-block` and adds a `palette-group` variant carrying a group name. Adds `newGroupRefNode` to `tree.ts` so the drop handler has a tested, pure constructor to call. After this task the UI is unchanged; the new payload exists but nothing emits it yet.

**Files:**
- Modify: `webapp/frontend/src/builder/tree.ts` (add `newGroupRefNode` after `newPaletteNode`, ~line 378)
- Modify: `webapp/frontend/src/builder/dnd.ts:5-9`
- Modify: `webapp/frontend/src/builder/BuilderTab.tsx:25,44-60,120-123`
- Modify: `webapp/frontend/src/builder/Palette.tsx:183,197,211`
- Test: `webapp/frontend/src/builder/tree.test.ts`

**Interfaces:**
- Consumes: `newPaletteNode(kind: PaletteKind): BlockNode`, `BlockNode`, `GroupRefNode` from `tree.ts`.
- Produces:
  - `newGroupRefNode(name: string): BlockNode` — a `group_ref` node with the given `name`, empty `args`, and a fresh uid. Used by Task 2's drop handling.
  - `DragPayload` variant `{ source: 'palette-group'; name: string }` — emitted by Task 2's group chips.
  - `DragPayload` variant `{ source: 'palette-block'; kind: PaletteKind }` — emitted by Task 3's block chips.

- [ ] **Step 1: Write the failing test**

Add to `webapp/frontend/src/builder/tree.test.ts`. Add `newGroupRefNode` to the existing import block from `'./tree'`, and add `type GroupRefNode` to the type imports:

```ts
describe('newGroupRefNode', () => {
  it('builds a group_ref carrying the given name and no args', () => {
    const node = newGroupRefNode('dilute') as GroupRefNode
    expect(node.kind).toBe('group_ref')
    expect(node.name).toBe('dilute')
    expect(node.args).toEqual({})
  })

  it('gives each call a distinct uid', () => {
    expect(newGroupRefNode('dilute').uid).not.toBe(newGroupRefNode('dilute').uid)
  })

  it('starts with the NodeBase defaults every block shares', () => {
    const node = newGroupRefNode('dilute')
    expect(node.label).toBeNull()
    expect(node.gapAfter).toBeNull()
    expect(node.startOffset).toBeNull()
  })
})
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd webapp/frontend && npx vitest run src/builder/tree.test.ts -t newGroupRefNode`
Expected: FAIL — `newGroupRefNode` is not exported from `./tree` (TypeScript/import error).

- [ ] **Step 3: Implement `newGroupRefNode`**

In `src/builder/tree.ts`, immediately after `newPaletteNode` (which currently ends at line 378), add:

```ts
/** A `group_ref` pre-filled with the group being called. `newPaletteNode` takes a kind and
 * nothing else, so the Groups panel's per-group chips (design 2026-07-18 §6) get their own
 * constructor rather than pushing a group-shaped optional parameter through every unrelated
 * `newPaletteNode` call. `args` is left empty for the Inspector to fill, exactly as a blank
 * `Group ref` behaved before. */
export function newGroupRefNode(name: string): BlockNode {
  return { ...nodeBase(), kind: 'group_ref', name, args: {} }
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd webapp/frontend && npx vitest run src/builder/tree.test.ts -t newGroupRefNode`
Expected: PASS — 3 tests.

- [ ] **Step 5: Rename the payload source and add the group variant**

Replace `src/builder/dnd.ts:5-9` with:

```ts
export type DragPayload =
  | { source: 'palette-block'; kind: PaletteKind }
  | { source: 'palette-group'; name: string }
  | { source: 'palette-verb'; role: string; verb: string; verbKind: 'command' | 'measure' }
  | { source: 'canvas'; uid: string }
```

- [ ] **Step 6: Run typecheck to see exactly which consumers break**

Run: `cd webapp/frontend && npm run typecheck`
Expected: FAIL — errors in `Palette.tsx` (three `source: 'palette-structure'` literals, lines 183, 197, 211) and `BuilderTab.tsx` (comparisons at lines 45 and 120). This is the failing-test step for a type-level change: the compiler is the test.

- [ ] **Step 7: Update `BuilderTab.tsx`**

Rename the constant at line 25 from `STRUCTURE_TITLES` to `BLOCK_TITLES`. **Its twelve entries are unchanged** — `group_ref` stays in the map, because the drag overlay still needs a fallback label for it.

In `dragOverlayInfo` (line 44), change the first arm and add the group arm:

```ts
  if (payload.source === 'palette-block') {
    return { label: BLOCK_TITLES[payload.kind] ?? payload.kind, kind: payload.kind }
  }
  // A dragged group shows its own name rather than the generic "Group ref" — the whole point
  // of per-group chips (design 2026-07-18 §6) is that the author picked a specific group.
  if (payload.source === 'palette-group') {
    return { label: payload.name, kind: 'group_ref' }
  }
```

In `onDragEnd` (line 120), change the block arm and add the group arm:

```ts
    if (payload.source === 'palette-block') {
      s.insertBlock(newPaletteNode(payload.kind), at)
      return
    }
    if (payload.source === 'palette-group') {
      s.insertBlock(newGroupRefNode(payload.name), at)
      return
    }
```

Add `newGroupRefNode` to the existing import from `'./tree'` on line 15.

- [ ] **Step 8: Update the three payload literals in `Palette.tsx`**

At lines 183, 197, and 211, change `source: 'palette-structure'` to `source: 'palette-block'`. Leave everything else in the file alone — the sections themselves are Task 3.

- [ ] **Step 9: Run the full gate**

Run: `cd webapp/frontend && npm run typecheck && npm test && npm run lint`
Expected: typecheck clean, all vitest suites PASS, oxlint clean.

- [ ] **Step 10: Commit**

```bash
cd webapp/frontend && git add src/builder/tree.ts src/builder/tree.test.ts src/builder/dnd.ts src/builder/BuilderTab.tsx src/builder/Palette.tsx
git commit -m "refactor(studio): rename palette-structure drag source to palette-block

Adds a palette-group payload variant and newGroupRefNode so the Groups
panel can emit a pre-filled group_ref. No UI change yet."
```

---

### Task 2: Per-group draggable chips in the Groups panel

Turns each row of `GroupsPanel` into a draggable chip that inserts a call to that specific group. After this task a `group_ref` can be created two ways — from the Groups panel and from the old `Repeat` section — which Task 3 resolves by deleting the latter.

**Files:**
- Modify: `webapp/frontend/src/builder/Palette.tsx:39-57` (`Chip`), `:119-168` (`GroupsPanel`)

**Interfaces:**
- Consumes: `DragPayload` variant `{ source: 'palette-group'; name: string }` (Task 1); `Chip`, `IconButton`, `KindIcon`.
- Produces: nothing later tasks depend on.

**Why there is no vitest step in this task:** `GroupsPanel` is a React component, and vitest runs in a node environment with no rendering (Global Constraints). Its verification is the typecheck/lint gate plus the probe capture, which is the harness that covers DOM wiring in this repo.

- [ ] **Step 1: Give `Chip` an optional className**

`Chip` currently hardcodes its classes. The group chip must render at 24px because it sits on a shared visual line with two `IconButton`s and probe rule R4 flags sibling heights that disagree by more than 1px. Replace `Chip` (lines 39-57) with:

```tsx
function Chip(props: { id: string; payload: DragPayload; className?: string; children: ReactNode }) {
  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({
    id: props.id,
    data: props.payload,
  })
  return (
    <div
      ref={setNodeRef}
      {...listeners}
      {...attributes}
      className={
        'flex cursor-grab select-none items-center rounded border border-slate-300 bg-white px-2 py-1 text-xs shadow-sm ' +
        (isDragging ? 'opacity-40' : 'hover:border-slate-400') +
        (props.className ? ' ' + props.className : '')
      }
    >
      {props.children}
    </div>
  )
}
```

- [ ] **Step 2: Rewrite the `GroupsPanel` list rows**

Replace the `<ul>` block in `GroupsPanel` (lines 139-167) with:

```tsx
  return (
    <>
      <ul className="space-y-1">
        {entries.map(([name, group]) => (
          <li key={name} className="flex items-center gap-1 text-sm">
            <Chip
              id={`palette-group-${name}`}
              payload={{ source: 'palette-group', name }}
              className="h-6"
            >
              <KindIcon kind="group_ref" className="mr-1" />
              <span className="font-mono">{name}</span>
              <span className="ml-1 text-caption">({group.params.join(', ')})</span>
            </Chip>
            <IconButton
              icon={Pencil}
              label="Edit this group's body"
              className={scope === name ? 'text-blue-700' : ''}
              onClick={() => setScope(name)}
            />
            <IconButton
              icon={X}
              label="Delete group"
              destructive
              className="ml-auto"
              onClick={() => setError(removeGroup(name))}
            />
          </li>
        ))}
        {error && <li className="text-xs text-red-600">{error}</li>}
      </ul>
      <p className="px-1 pt-1 text-xs text-hint">Drag a group onto the canvas to call it.</p>
    </>
  )
```

Three things changed and each matters:
- The group name stopped being the scope-switch button and became the drag chip. The switch action moved to an explicit `Pencil` `IconButton`, because a control cannot advertise both "drag me" and "click me" with one affordance. Active scope is now shown by that button turning blue rather than the name.
- `className="h-6"` on the chip is the R4 requirement from Step 1.
- The hint line is what makes the drag affordance discoverable, since after Task 3 no `Group ref` chip advertises it any more.

- [ ] **Step 3: Add the `Pencil` import**

On line 3, extend the `lucide-react` import: `import { ChevronDown, ChevronRight, Pencil, X } from 'lucide-react'`.

- [ ] **Step 4: Update the empty state**

`GroupsPanel`'s early return (lines 132-138) keeps its existing copy — with no groups declared there is nothing to drag, so the drag hint would be noise. Leave it as-is. **Do not edit lines 132-138.**

- [ ] **Step 5: Run the gate**

Run: `cd webapp/frontend && npm run typecheck && npm test && npm run lint`
Expected: typecheck clean, all suites PASS, oxlint clean.

- [ ] **Step 6: Commit**

```bash
cd webapp/frontend && git add src/builder/Palette.tsx
git commit -m "feat(studio): drag a declared group from the Groups panel to call it

Each Groups row is now a draggable chip inserting a group_ref for that
specific group. Scope switching moves to an explicit pencil button, since
one control cannot advertise both drag and click."
```

---

### Task 3: The four block sections

Renames the kind types to match the sections, extracts the chip arrays into a pure module, and replaces the three `Structure`/`Control`/`Repeat` sections with four: Flow, Data, Pause, Safety. This is the task the whole change exists for.

**Files:**
- Modify: `webapp/frontend/src/builder/tree.ts:8-13`
- Create: `webapp/frontend/src/builder/paletteSections.ts`
- Create: `webapp/frontend/src/builder/paletteSections.test.ts`
- Modify: `webapp/frontend/src/builder/Palette.tsx:6,14-37,177-218`

**Interfaces:**
- Consumes: `PaletteKind` and `newPaletteNode` from `tree.ts`; `Chip`, `Section`, `KindIcon` from `Palette.tsx`; the `palette-block` payload (Task 1).
- Produces:
  - `FlowKind`, `DataKind`, `PauseKind`, `SafetyKind`, `PaletteKind` from `tree.ts`. `StructureKind`, `ControlKind`, and `RepeatKind` are **deleted**.
  - `BlockChip` (`{ kind: PaletteKind; title: string }`), `FLOW`, `DATA`, `PAUSE`, `SAFETY`, and `BLOCK_SECTIONS` (`Array<{ title: string; items: readonly BlockChip[] }>`) from `paletteSections.ts`.

- [ ] **Step 1: Write the failing test**

Create `webapp/frontend/src/builder/paletteSections.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import { BLOCK_SECTIONS } from './paletteSections'
import { newPaletteNode, type PaletteKind } from './tree'

/** Every kind `newPaletteNode` can construct. Hand-maintained: TypeScript cannot enumerate a
 * union at runtime. Adding a member to `PaletteKind` means adding it here AND to a section —
 * which is exactly the decision this suite exists to force. */
const ALL_KINDS: PaletteKind[] = [
  'serial', 'parallel', 'branch', 'loop', 'for_each',
  'compute', 'record',
  'wait', 'operator_input',
  'alarm', 'abort',
  'group_ref',
]

const listed = (): PaletteKind[] => BLOCK_SECTIONS.flatMap((s) => s.items.map((i) => i.kind))

describe('palette block sections', () => {
  it('covers every palette kind except group_ref', () => {
    expect([...listed()].sort()).toEqual(ALL_KINDS.filter((k) => k !== 'group_ref').sort())
  })

  it('never lists a kind in two sections', () => {
    const kinds = listed()
    expect(new Set(kinds).size).toBe(kinds.length)
  })

  it('keeps group_ref out of the block sections', () => {
    expect(listed()).not.toContain('group_ref')
  })

  it('groups loop and for_each together', () => {
    const section = (k: PaletteKind) => BLOCK_SECTIONS.find((s) => s.items.some((i) => i.kind === k))?.title
    expect(section('loop')).toBe('Flow')
    expect(section('for_each')).toBe('Flow')
  })

  it('gives every chip a non-empty title and a constructible kind', () => {
    for (const s of BLOCK_SECTIONS) {
      expect(s.title).not.toBe('')
      for (const item of s.items) {
        expect(item.title).not.toBe('')
        expect(newPaletteNode(item.kind).kind).toBe(item.kind)
      }
    }
  })
})
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd webapp/frontend && npx vitest run src/builder/paletteSections.test.ts`
Expected: FAIL — cannot resolve `./paletteSections`.

- [ ] **Step 3: Rewrite the kind types**

Replace `src/builder/tree.ts:8-13` with:

```ts
/** Blocks that hold a body and decide what runs, in what order, and how many times. This is
 * exactly the set with child slots (`childSlots` below), so the palette's Flow section and the
 * drop affordance coincide (design 2026-07-18 §3). */
export type FlowKind = 'serial' | 'parallel' | 'branch' | 'loop' | 'for_each'
/** Leaf blocks that write run state rather than acting on a device (Increment 6). */
export type DataKind = 'compute' | 'record'
/** Leaf blocks that hold the run until the clock or the operator releases it. */
export type PauseKind = 'wait' | 'operator_input'
/** Leaf blocks that change the run's fate (Increment 8): alarm flags and continues, abort stops. */
export type SafetyKind = 'alarm' | 'abort'
/** Every kind `newPaletteNode` can construct. None of Data/Pause/Safety takes `retry` — retry is
 * command/measure only (design 2026-07-14 §2.1). `group_ref` is in the union but has no section
 * of its own: it is dragged from the Groups panel (design 2026-07-18 §6). */
export type PaletteKind = FlowKind | DataKind | PauseKind | SafetyKind | 'group_ref'
```

- [ ] **Step 4: Create the sections module**

Create `webapp/frontend/src/builder/paletteSections.ts`:

```ts
/** The palette's block-chip sections (design 2026-07-18 §3).
 *
 * Plain data in its own module so `paletteSections.test.ts` can assert the partition: vitest
 * runs in a node env with no rendering (webapp/frontend/CLAUDE.md), so a test cannot import
 * Palette.tsx — React, dnd-kit, and the zustand stores come with it.
 *
 * Chip order within Flow is a deliberate progression: composition, then decision, then
 * repetition. */
import type { DataKind, FlowKind, PauseKind, SafetyKind, PaletteKind } from './tree'

export interface BlockChip {
  kind: PaletteKind
  title: string
}

export const FLOW: Array<{ kind: FlowKind; title: string }> = [
  { kind: 'serial', title: 'Serial' },
  { kind: 'parallel', title: 'Parallel' },
  { kind: 'branch', title: 'Branch' },
  { kind: 'loop', title: 'Loop' },
  { kind: 'for_each', title: 'For each' },
]

export const DATA: Array<{ kind: DataKind; title: string }> = [
  { kind: 'compute', title: 'Compute' },
  { kind: 'record', title: 'Record' },
]

export const PAUSE: Array<{ kind: PauseKind; title: string }> = [
  { kind: 'wait', title: 'Wait' },
  { kind: 'operator_input', title: 'Operator input' },
]

export const SAFETY: Array<{ kind: SafetyKind; title: string }> = [
  { kind: 'alarm', title: 'Alarm' },
  { kind: 'abort', title: 'Abort' },
]

export const BLOCK_SECTIONS: Array<{ title: string; items: readonly BlockChip[] }> = [
  { title: 'Flow', items: FLOW },
  { title: 'Data', items: DATA },
  { title: 'Pause', items: PAUSE },
  { title: 'Safety', items: SAFETY },
]
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `cd webapp/frontend && npx vitest run src/builder/paletteSections.test.ts`
Expected: PASS — 5 tests.

- [ ] **Step 6: Render the four sections in `Palette.tsx`**

Delete the `STRUCTURE`, `CONTROL`, and `REPEAT` arrays (lines 14-37) **including the four-line comment block above `REPEAT`** — both facts it explains (that `∀` cannot be confused with the Repeat icon, and that Repeat chips share the Structure payload source) stop being surprising once the two chips sit in the same section on the same source.

Change the type import on line 6 to pull the section data instead of the old kind types:

```ts
import { BLOCK_SECTIONS, type BlockChip } from './paletteSections'
```

Add a `BlockSection` helper next to `Section`:

```tsx
/** All four block sections differ only by title and contents, so they render through one
 * helper. Four near-identical JSX blocks is what let Structure/Control/Repeat drift apart
 * independently in the first place (design 2026-07-18 §5). */
function BlockSection(props: { title: string; items: readonly BlockChip[] }) {
  return (
    <Section title={props.title}>
      <div className="flex flex-wrap gap-1">
        {props.items.map((item) => (
          <Chip
            key={item.kind}
            id={`palette-block-${item.kind}`}
            payload={{ source: 'palette-block', kind: item.kind }}
          >
            <KindIcon kind={item.kind} className="mr-1" />
            {item.title}
          </Chip>
        ))}
      </div>
    </Section>
  )
}
```

Replace the three `<Section title="Structure">` / `"Control"` / `"Repeat"` blocks (lines 177-218) with:

```tsx
      {BLOCK_SECTIONS.map((s) => (
        <BlockSection key={s.title} title={s.title} items={s.items} />
      ))}
```

Leave the `Roles`, `Manage roles`, `Streams`, and `Groups` sections untouched.

- [ ] **Step 7: Run the full gate**

Run: `cd webapp/frontend && npm run typecheck && npm test && npm run lint && npm run build`
Expected: typecheck clean, all suites PASS, oxlint clean, vite build succeeds.

If `tree.test.ts` or `convert.test.ts` fails, stop — per Global Constraints that means the change leaked past presentation.

- [ ] **Step 8: Commit**

```bash
cd webapp/frontend && git add src/builder/tree.ts src/builder/paletteSections.ts src/builder/paletteSections.test.ts src/builder/Palette.tsx
git commit -m "feat(studio): re-cut palette into Flow/Data/Pause/Safety

Structure/Control/Repeat recorded which increment shipped each block, not
what the blocks do: loop and for_each were separated twins, Repeat held a
non-repeater, and Control named something other than control flow. Kind
types are renamed to match, and the chip arrays move to a pure module so
the partition is unit-tested."
```

---

### Task 4: Verify in the running app

The three tasks above are covered by typecheck, vitest, and lint — none of which renders a pixel. This task confirms the palette actually looks and behaves right, and that the new Groups rows pass the probe's height rule.

**Files:** none modified unless a defect is found.

- [ ] **Step 1: Run the probe capture**

Run: `cd webapp/frontend && npm run capture`
Expected: no `sibling-height-mismatch` (R4) findings on the Groups rows. R4 is the rule that catches a group chip whose height disagrees with the `IconButton`s beside it — the specific risk introduced in Task 2.

If R4 fires on a Groups row, the `h-6` from Task 2 Step 2 is missing or being overridden; fix it and re-run before continuing.

- [ ] **Step 2: Drive the app**

Use the `verify` skill to exercise the change end-to-end. Confirm, in a running Studio:
1. The palette shows **Flow, Data, Pause, Safety** — and no Structure, Control, or Repeat.
2. Flow contains Serial, Parallel, Branch, Loop, For each — `loop` and `for_each` adjacent.
3. There is **no `Group ref` chip** anywhere in the block sections.
4. Declaring a group, then dragging its chip from the Groups panel onto the canvas, inserts a `group_ref` **already naming that group** — the Inspector shows the name pre-filled, not blank.
5. Clicking the pencil button on a Groups row still switches the editing scope to that group's body, and the button reads blue while that scope is active.
6. Dragging a group shows the group's own name in the drag overlay, not "Group ref".
7. Undo/redo still works across a group-chip drop.

- [ ] **Step 3: Commit any fixes**

If Steps 1-2 found defects, fix them, re-run `npm run typecheck && npm test && npm run lint && npm run capture`, and commit with a `fix(studio):` message. If nothing was found, skip this step — do not create an empty commit.

---

## Completion

After Task 4, use `superpowers:finishing-a-development-branch`. The user has pre-authorized opening the PR and merging it once all work is done.
