# Experiment Studio W12 — UI Improvements Round 2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the four hand-found UI issues from `docs/ui-improvements-2/improvements.md`: joined panels → separate boxes; roles section → grouped by device type with radio badges; two-row header → single row with underline tabs; parallel lanes → genuinely empty-able containers.

**Architecture:** Spec `docs/superpowers/specs/2026-07-18-experiment-studio-ui-improvements-2-design.md`. Frontend-only. Lane auto-wrap lives in the pure tree layer (`tree.ts`) so insert/move/duplicate share one code path and stay single-undo-step. Roles grouping is a pure helper consumed by a new `RolesSection` component. The header refactor kills the `h-[calc(100vh-9rem)]` magic number via an `h-screen` flex column.

**Tech Stack:** React 19.2, Vite 8, Tailwind 4, zustand+zundo, dnd-kit, vitest 4 (node env — pure functions ONLY), oxlint, lucide-react, playwright (committed probe harness in `webapp/frontend/tools/`).

## Global Constraints

Copied from `webapp/frontend/CLAUDE.md` and the spec — every task implicitly includes these:

- **Icons:** interactive icons from **lucide-react** only, rendered via `IconButton` (or `iconButtonClass()` for anchors). No raw glyph characters for interactive controls. Semantic notation stays typographic: `∀`, `R×N`, `⤳`, `×N`, `●`.
- **Control height:** every input/select/inline button is 24px via `controlClass()` / `inlineButtonClass()` (and the new `badgeClass()`) from `src/ui/controls.ts`. Height lives in that module and nowhere else. **Pass `width` as an option; never concatenate a width class** (appended widths silently lose the cascade to `w-full`). Margins may be appended.
- **Text colors:** meaning-carrying secondary text = `text-caption` (slate-600); incidental placeholder/empty-state text = `text-hint` (slate-500). Never `text-slate-400` or lighter on meaning-carrying text. On `bg-slate-100` use `text-caption` even for incidental text.
- **vitest runs in node env:** pure functions only. No component rendering, no jsdom, no @testing-library. DOM truth comes from the probe harness (`npm run capture`).
- **Tab accessible names** must remain exactly `1 Devices`, `2 Builder`, `3 Run`, `4 Records` (mono digit span + label) — the capture harness and preprod recipes select on `/^2\s*Builder$/`.
- **Byte round-trip:** `docToTree`/`treeToDoc` (`convert.ts`) must NOT be touched — open+save stays a byte no-op.
- **Gates** (run from repo root unless noted): frontend `cd webapp/frontend && npm run lint && npm run typecheck && npm test -- --run && npm run build`; backend `cd webapp/backend && .venv/bin/python -m pytest -q && .venv/bin/python -m mypy && .venv/bin/python -m ruff check .` (mypy takes NO path arg). Five known pre-existing oxlint fast-refresh warnings are expected — IconButton, StreamChart, ScrollX, TabShell, icons — exit 0.
- **Commits:** conventional-commit subjects. Every commit message ends with:

  ```
  Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_015wMTqGaisQrX91x2zceo8S
  ```
- **Working directory:** the worktree `/Users/khamit/lab-devices/.claude/worktrees/ui-improvements-2` (branch `worktree-ui-improvements-2`). All paths below are relative to it.

---

### Task 1: Lane auto-wrap in the pure tree layer

A parallel's `children` are its lanes. The builder's new contract (spec §3.4): every lane authored through the UI is a serial container. The wrap lives in `insertNode` — `moveNode` and `duplicateNode` both funnel through it, so all three get the behavior from one code path and each store action stays a single zundo snapshot.

**Files:**
- Modify: `webapp/frontend/src/builder/tree.ts` (insertNode, ~line 228; new `wrapAsLane` near `newPaletteNode`, ~line 339)
- Test: `webapp/frontend/src/builder/tree.test.ts` (append)

**Interfaces:**
- Produces: `wrapAsLane(node: BlockNode): BlockNode` — exported from `tree.ts`. Returns `node` unchanged when `node.kind === 'serial'`; otherwise a fresh plain serial (`label`/`gapAfter`/`startOffset` null, new uid) whose `children` is `[node]`.
- Produces: `insertNode` now wraps via `wrapAsLane` **iff** the target parent is a `parallel` and the slot is `children`. Root inserts and every other slot are byte-identical to before.

- [ ] **Step 1: Write the failing tests**

Append to `webapp/frontend/src/builder/tree.test.ts` (match the file's existing describe/it style and helpers; the code below is self-contained if none fit):

```ts
describe('wrapAsLane', () => {
  it('passes a serial through unchanged (same object)', () => {
    const s = newPaletteNode('serial')
    expect(wrapAsLane(s)).toBe(s)
  })
  it('wraps a non-serial in a fresh plain serial', () => {
    const w = newPaletteNode('wait')
    const lane = wrapAsLane(w)
    expect(lane.kind).toBe('serial')
    if (lane.kind !== 'serial') return
    expect(lane.children).toEqual([w])
    expect(lane.label).toBeNull()
    expect(lane.uid).not.toBe(w.uid)
  })
})

describe('lane auto-wrap on insert/move/duplicate', () => {
  it('insertNode into parallel children wraps a non-serial block', () => {
    const p = newPaletteNode('parallel') // seeds two empty serial lanes
    const w = newPaletteNode('wait')
    const out = insertNode([p], w, { parentUid: p.uid, slot: 'children', index: 2 })
    const par = out[0]
    if (par.kind !== 'parallel') throw new Error('expected parallel')
    expect(par.children).toHaveLength(3)
    expect(par.children[2].kind).toBe('serial')
    const lane = par.children[2]
    if (lane.kind !== 'serial') return
    expect(lane.children.map((c) => c.uid)).toEqual([w.uid])
  })
  it('insertNode into parallel children passes a serial through as the lane', () => {
    const p = newPaletteNode('parallel')
    const s = newPaletteNode('serial')
    const out = insertNode([p], s, { parentUid: p.uid, slot: 'children', index: 0 })
    const par = out[0]
    if (par.kind !== 'parallel') throw new Error('expected parallel')
    expect(par.children[0].uid).toBe(s.uid)
  })
  it('insertNode into a serial slot does NOT wrap', () => {
    const s = newPaletteNode('serial')
    const w = newPaletteNode('wait')
    const out = insertNode([s], w, { parentUid: s.uid, slot: 'children', index: 0 })
    const ser = out[0]
    if (ser.kind !== 'serial') throw new Error('expected serial')
    expect(ser.children[0].uid).toBe(w.uid)
  })
  it('moveNode of a block from inside a lane to lane level wraps it and keeps the source lane', () => {
    const p = newPaletteNode('parallel')
    const w = newPaletteNode('wait')
    const seeded = insertNode(
      [p],
      w,
      { parentUid: (p as { children: BlockNode[] }).children[0].uid, slot: 'children', index: 0 },
    )
    const out = moveNode(seeded, w.uid, { parentUid: p.uid, slot: 'children', index: 2 })
    const par = out[0]
    if (par.kind !== 'parallel') throw new Error('expected parallel')
    expect(par.children).toHaveLength(3) // lane 1 (now empty) survives, new lane appended
    const first = par.children[0]
    if (first.kind !== 'serial') throw new Error('expected serial lane')
    expect(first.children).toHaveLength(0)
    const moved = par.children[2]
    if (moved.kind !== 'serial') throw new Error('expected wrapped lane')
    expect(moved.children.map((c) => c.uid)).toEqual([w.uid])
  })
  it('duplicateNode of a bare-block lane wraps the clone', () => {
    const p = newPaletteNode('parallel')
    const cmd = newVerbNode('pump', 'dispense', { kind: 'command', params: {} } as VerbSpec)
    if (p.kind !== 'parallel') throw new Error('expected parallel')
    const tree: BlockNode[] = [{ ...p, children: [cmd] }]
    const [out] = duplicateNode(tree, cmd.uid)
    const par = out[0]
    if (par.kind !== 'parallel') throw new Error('expected parallel')
    expect(par.children).toHaveLength(2)
    expect(par.children[0].uid).toBe(cmd.uid) // original untouched
    expect(par.children[1].kind).toBe('serial') // clone wrapped
  })
})
```

Adjust imports at the top of the test file to include `wrapAsLane`, `insertNode`, `moveNode`, `duplicateNode`, `newPaletteNode`, `newVerbNode`, and the `BlockNode`/`VerbSpec` types as needed (check what the file already imports first). If `VerbSpec` needs more required fields, copy a minimal valid literal from an existing test in the file.

- [ ] **Step 2: Run tests to verify the new ones fail**

Run: `cd webapp/frontend && npx vitest run src/builder/tree.test.ts`
Expected: FAIL — `wrapAsLane is not exported` (and/or wrap assertions failing).

- [ ] **Step 3: Implement**

In `webapp/frontend/src/builder/tree.ts`, add above `insertNode`:

```ts
/** A parallel's `children` ARE its lanes, and every lane authored through the UI is a
 * serial container (spec 2026-07-18 §3.4) — so anything landing on a parallel's
 * `children` slot that isn't already a serial gets wrapped in a fresh plain one. Living
 * here (not in onDragEnd) means insertNode/moveNode/duplicateNode all share the one code
 * path, each store action stays a single zundo snapshot, and duplicating a legacy
 * bare-block lane normalizes the copy for free. Imported docs are untouched: docToTree
 * builds children directly and never calls this. */
export function wrapAsLane(node: BlockNode): BlockNode {
  if (node.kind === 'serial') return node
  return { uid: newUid(), label: null, gapAfter: null, startOffset: null, kind: 'serial', children: [node] }
}
```

Then in `insertNode`, change the insertion branch:

```ts
      if (n.uid === at.parentUid && slot === at.slot) {
        const toInsert = n.kind === 'parallel' && slot === 'children' ? wrapAsLane(node) : node
        list.splice(clampIndex(at.index, list.length), 0, toInsert)
        inserted = true
      }
```

(Root-level branch at the top of `insertNode` stays untouched — the root list is never a parallel's children.)

- [ ] **Step 4: Run the full frontend unit suite**

Run: `cd webapp/frontend && npm test -- --run`
Expected: all pass (256 existing + 6 new).

- [ ] **Step 5: Commit**

```bash
git add webapp/frontend/src/builder/tree.ts webapp/frontend/src/builder/tree.test.ts
git commit -m "feat(studio): auto-wrap non-serial drops at parallel lane level (W12 §3.4)"
```

---

### Task 2: Unwrap serial lanes in ParallelLanes

**Files:**
- Modify: `webapp/frontend/src/builder/Canvas.tsx` (`ParallelLanes`, lines ~312-373; imports)

**Interfaces:**
- Consumes: `faultMarker` from `./summary` (returns `' R×N ⤳'`-style string with a leading space, empty when neither set), `BlockList`, `DiagContext`, `blockDraggableId`, `IconButton`, existing docStore actions.
- Produces: a `Lane` component local to Canvas.tsx. A `serial` child of a parallel renders as the lane itself (header = handle); any other kind keeps today's card-in-lane rendering. No export changes.

- [ ] **Step 1: Implement the Lane component and rewire ParallelLanes**

In `webapp/frontend/src/builder/Canvas.tsx`:

1. Add `faultMarker` to the `./summary` import (line ~8: `import { blockSummary, faultMarker } from './summary'`).
2. Replace the whole `ParallelLanes` function with:

```tsx
function ParallelLanes({ node }: { node: ParallelNode }) {
  const insertBlock = useDocStore((s) => s.insertBlock)
  return (
    // No nested overflow here: the Canvas is the only horizontal scroller, so a wide lane
    // widens the canvas's content and scrolls THERE instead of being clipped inside this box.
    //
    // Lanes are `flex-initial` for the same reason the branch arms are (see BranchLanes): a
    // grow factor makes an EMPTY lane claim an equal share of whatever space is left, which is
    // finding #5b's "free space on one side, hidden content on the other" in a different
    // container. Sizing to content also keeps the "+ lane" button next to the last lane rather
    // than shoved to the far edge by the lanes' growth.
    <div className="flex items-stretch">
      <DropSlot
        at={{ parentUid: node.uid, slot: 'children', index: 0 }}
        horizontal
        hint={node.children.length === 0}
      />
      {node.children.map((lane, i) => (
        <Fragment key={lane.uid}>
          <Lane lane={lane} index={i} />
          <DropSlot at={{ parentUid: node.uid, slot: 'children', index: i + 1 }} horizontal hint={false} />
        </Fragment>
      ))}
      <button
        title="Add lane"
        onClick={(e) => {
          e.stopPropagation()
          insertBlock(newPaletteNode('serial'), {
            parentUid: node.uid,
            slot: 'children',
            index: node.children.length,
          })
        }}
        // `stretch` instead of the 24px token: this button runs the full height of the lanes
        // beside it, which is why it is the one sanctioned height exception (controls.ts).
        // `m-1` is the button's existing inset from the lane row, and it is a margin — not a
        // width or a colour — so nothing in the helper competes with it in the cascade.
        className={inlineButtonClass({ subtle: true, stretch: true }) + ' m-1'}
      >
        <Plus size={12} aria-hidden className="mr-0.5" />lane
      </button>
    </div>
  )
}

/** One lane of a Parallel. A `serial` child IS the lane (spec §3.4): its children render
 * directly in the lane box and this header row is the serial's handle — click selects it
 * (the Inspector edits its label/on_error there), drag moves/reorders it, and its label,
 * fault markers and diagnostics show here, since there is no card to carry them. Emptying
 * a lane therefore never destroys it; the ✕ (empty lanes only) and select+Delete stay the
 * explicit removal paths. Any other kind is a legacy/imported bare-block lane and keeps
 * the card rendering — both committed fixtures contain such lanes (spec §5). */
function Lane({ lane, index }: { lane: BlockNode; index: number }) {
  const select = useDocStore((s) => s.select)
  const selected = useDocStore((s) => s.selectedUid === lane.uid)
  const removeBlock = useDocStore((s) => s.removeBlock)
  const duplicateBlock = useDocStore((s) => s.duplicateBlock)
  const diags = useContext(DiagContext).get(lane.uid) ?? []
  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({
    id: blockDraggableId(lane.uid),
    data: { source: 'canvas', uid: lane.uid } satisfies DragPayload,
  })
  if (lane.kind !== 'serial') {
    return (
      <div className="min-w-48 flex-initial rounded border border-dashed border-slate-200 p-1">
        <div className="flex h-6 items-center px-1 text-[10px] uppercase text-caption">
          lane {index + 1}
        </div>
        <BlockView node={lane} />
      </div>
    )
  }
  const marker = faultMarker(lane).trim()
  return (
    <div
      id={`block-${lane.uid}`}
      ref={setNodeRef}
      onClick={(e) => {
        e.stopPropagation()
        select(lane.uid)
      }}
      className={
        'min-w-48 flex-initial rounded border border-dashed p-1 ' +
        (selected ? 'border-blue-500 ring-1 ring-blue-300 ' : 'border-slate-200 ') +
        (isDragging ? 'opacity-40' : '')
      }
    >
      <div
        {...listeners}
        {...attributes}
        className="flex h-6 min-w-0 cursor-grab items-center gap-1 px-1 text-[10px] uppercase text-caption"
      >
        <span className="shrink-0">lane {index + 1}</span>
        {lane.label && (
          // max-w-40 for the same intrinsic-width reason as BlockView's label span: under the
          // canvas's width:max-content a nowrap span contributes its FULL untruncated width.
          <span title={lane.label} className="max-w-40 truncate normal-case italic">
            “{lane.label}”
          </span>
        )}
        {marker && <span className="shrink-0 normal-case">{marker}</span>}
        <span className="ml-auto flex items-center gap-1">
          {diags.length > 0 && (
            <span
              title={diags.map((d) => d.message).join('\n')}
              className="rounded-full bg-red-600 px-1.5 text-[10px] font-bold normal-case text-white"
            >
              {diags.length}
            </span>
          )}
          <IconButton
            icon={Copy}
            label="Duplicate lane"
            onClick={(e) => {
              e.stopPropagation()
              duplicateBlock(lane.uid)
            }}
          />
          {lane.children.length === 0 && (
            <IconButton
              icon={X}
              label="Remove lane"
              destructive
              onClick={(e) => {
                e.stopPropagation()
                removeBlock(lane.uid)
              }}
            />
          )}
        </span>
      </div>
      <BlockList parentUid={lane.uid} slot="children" items={lane.children} />
    </div>
  )
}
```

Notes for the implementer:
- The old `isEmptyLane` helper and the `removeBlock`/`insertBlock` reads at the top of the old `ParallelLanes` are superseded — delete what's no longer referenced.
- `id={`block-${lane.uid}`}` is REQUIRED: ProblemsPanel's scroll-to-block targets that id, and the serial no longer renders a BlockView card that would carry it.
- The lane keeps `min-w-48 flex-initial` (W11 §4.2 — no grow factor; see the comment kept above).
- `BlockList` already renders a "drop here" hint DropSlot when `items` is empty — that is the empty lane's body.

- [ ] **Step 2: Gates**

Run: `cd webapp/frontend && npm run lint && npm run typecheck && npm test -- --run && npm run build`
Expected: all pass (2 known fast-refresh warnings OK).

- [ ] **Step 3: Commit**

```bash
git add webapp/frontend/src/builder/Canvas.tsx
git commit -m "feat(studio): render serial-under-parallel as the lane itself (W12 §3.4)"
```

---

### Task 3: `roleGroups` pure helper + `badgeClass` control token

**Files:**
- Create: `webapp/frontend/src/builder/roleGroups.ts`
- Test: `webapp/frontend/src/builder/roleGroups.test.ts`
- Modify: `webapp/frontend/src/ui/controls.ts` (append `badgeClass`)
- Test: `webapp/frontend/src/ui/controls.test.ts` (append)

**Interfaces:**
- Consumes: `Catalog` type from `../types/catalog` (`catalog.device_types: Record<string, Record<string, VerbSpec>>`).
- Produces: `RoleTypeGroup { type: string; known: boolean; roles: string[] }`; `roleGroups(roles, catalog): RoleTypeGroup[]`; `effectiveSelection(roles: string[], current: string | null): string | null`; `badgeClass(opts?: { active?: boolean }): string`.

- [ ] **Step 1: Write the failing tests**

`webapp/frontend/src/builder/roleGroups.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import { effectiveSelection, roleGroups } from './roleGroups'
import type { Catalog } from '../types/catalog'

const catalog = {
  device_types: { pump: {}, densitometer: {}, thermostat: {} },
} as unknown as Catalog

describe('roleGroups', () => {
  it('emits every catalog type in catalog order, with roles in doc order', () => {
    const groups = roleGroups(
      { od: { type: 'densitometer' }, drug_b: { type: 'pump' }, drug_a: { type: 'pump' } },
      catalog,
    )
    expect(groups.map((g) => g.type)).toEqual(['pump', 'densitometer', 'thermostat'])
    expect(groups[0]).toEqual({ type: 'pump', known: true, roles: ['drug_b', 'drug_a'] })
    expect(groups[1].roles).toEqual(['od'])
    expect(groups[2]).toEqual({ type: 'thermostat', known: true, roles: [] })
  })
  it('appends unknown types cited by roles, flagged and in first-appearance order', () => {
    const groups = roleGroups(
      { x: { type: 'zz_gone' }, y: { type: 'aa_gone' } },
      catalog,
    )
    expect(groups.slice(3)).toEqual([
      { type: 'zz_gone', known: false, roles: ['x'] },
      { type: 'aa_gone', known: false, roles: ['y'] },
    ])
  })
  it('with a null catalog, groups only what the roles cite, all unknown', () => {
    expect(roleGroups({ p: { type: 'pump' } }, null)).toEqual([
      { type: 'pump', known: false, roles: ['p'] },
    ])
  })
})

describe('effectiveSelection', () => {
  it('keeps the current pick while it exists', () => {
    expect(effectiveSelection(['a', 'b'], 'b')).toBe('b')
  })
  it('falls back to the first role when the pick is gone (deleted/renamed)', () => {
    expect(effectiveSelection(['a', 'b'], 'zz')).toBe('a')
  })
  it('is null for an empty role list', () => {
    expect(effectiveSelection([], null)).toBeNull()
  })
})
```

Append to `webapp/frontend/src/ui/controls.test.ts` (match its existing style):

```ts
describe('badgeClass', () => {
  it('always carries the control-height token', () => {
    expect(badgeClass()).toContain('h-6')
    expect(badgeClass({ active: true })).toContain('h-6')
  })
  it('active swaps hover treatment for the selected treatment', () => {
    expect(badgeClass({ active: true })).toContain('bg-blue-100')
    expect(badgeClass()).not.toContain('bg-blue-100')
  })
})
```

(Add `badgeClass` to that file's import from `./controls`.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd webapp/frontend && npx vitest run src/builder/roleGroups.test.ts src/ui/controls.test.ts`
Expected: FAIL — module/exports not found.

- [ ] **Step 3: Implement**

`webapp/frontend/src/builder/roleGroups.ts`:

```ts
/** Pure grouping for the palette's Roles section (spec §3.3): one entry per catalog
 * device type in catalog order — a type with no roles still gets a block, so the user
 * sees what the lab offers and can create the first role in place — then one entry per
 * unknown type cited by the doc's roles (first-appearance order, rendered amber by the
 * consumer). A null catalog (still loading, or errored) yields only the cited types, all
 * flagged unknown, rather than pretending to know their verbs. */
import type { Catalog } from '../types/catalog'

export interface RoleTypeGroup {
  type: string
  known: boolean
  roles: string[]
}

export function roleGroups(
  roles: Record<string, { type: string }>,
  catalog: Catalog | null,
): RoleTypeGroup[] {
  const known = new Set(Object.keys(catalog?.device_types ?? {}))
  const byType = new Map<string, string[]>([...known].map((t) => [t, []]))
  for (const [name, def] of Object.entries(roles)) {
    const list = byType.get(def.type)
    if (list) list.push(name)
    else byType.set(def.type, [name])
  }
  return [...byType.entries()].map(([type, rs]) => ({ type, known: known.has(type), roles: rs }))
}

/** Which badge is active inside a type block: the current pick while it still exists,
 * else the first role, else null. Pure so the fallback-on-delete rule is testable. */
export function effectiveSelection(roles: string[], current: string | null): string | null {
  if (current !== null && roles.includes(current)) return current
  return roles[0] ?? null
}
```

Append to `webapp/frontend/src/ui/controls.ts`:

```ts
/** Radio-style badge buttons (the Roles section's role picker). Borderless — they read as
 * selectable chips, not push buttons — but they carry CONTROL_H because they share a
 * visual row with 24px IconButtons (rename/delete), and the probe's
 * sibling-height-mismatch rule holds every such row to ≤1px. */
export function badgeClass(opts: { active?: boolean } = {}): string {
  return (
    `${CONTROL_H} inline-flex items-center rounded px-1.5 font-mono text-xs ` +
    (opts.active ? 'bg-blue-100 text-blue-700' : 'text-slate-700 hover:bg-slate-200')
  ).trim()
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd webapp/frontend && npx vitest run src/builder/roleGroups.test.ts src/ui/controls.test.ts`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add webapp/frontend/src/builder/roleGroups.ts webapp/frontend/src/builder/roleGroups.test.ts webapp/frontend/src/ui/controls.ts webapp/frontend/src/ui/controls.test.ts
git commit -m "feat(studio): roleGroups pure helper + badgeClass control token (W12 §3.3)"
```

---

### Task 4: RolesSection UI — type-grouped roles, selected-role actions, Manage roles removed

**Files:**
- Create: `webapp/frontend/src/builder/Chip.tsx` (moved out of Palette.tsx — RolesSection needs it and a Palette↔RolesSection import cycle is avoidable)
- Create: `webapp/frontend/src/builder/RolesSection.tsx`
- Modify: `webapp/frontend/src/builder/Palette.tsx` (remove `Chip`, `AddRoleForm`, the old Roles listing, the whole `Manage roles` section and the `RolesPanel` import; render `<RolesSection />`)
- Delete: `webapp/frontend/src/builder/RolesPanel.tsx`
- Modify: `webapp/frontend/src/stores/docStore.ts` (comment only, line ~75: `RolesPanel` → `RolesSection`)

**Interfaces:**
- Consumes: `roleGroups`/`effectiveSelection`/`RoleTypeGroup` (Task 3), `badgeClass`/`controlClass`/`inlineButtonClass`, `IconButton`, `KindIcon`, `useDismissable` from `../ui/useDismissable` (same `(active, onDismiss) => ref` usage as Canvas's ScopeSwitcher), docStore `renameRole`/`removeRole`/`addRole`/`focusedRole`, catalogStore.
- Produces: `Chip` exported from `./Chip` (exact same props/behavior as the current Palette-local one); `RolesSection` exported from `./RolesSection`.

- [ ] **Step 1: Move Chip**

Create `webapp/frontend/src/builder/Chip.tsx` with the existing implementation (cut from Palette.tsx lines 39-57, plus its `useDraggable`/`DragPayload`/`ReactNode` imports; add `export`):

```tsx
import type { ReactNode } from 'react'
import { useDraggable } from '@dnd-kit/core'
import type { DragPayload } from './dnd'

/** Draggable palette chip (structure kinds and role verbs). Unchanged from its former
 * Palette-local self; it lives alone so Palette and RolesSection can both import it
 * without a component-level cycle. */
export function Chip(props: { id: string; payload: DragPayload; children: ReactNode }) {
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
        (isDragging ? 'opacity-40' : 'hover:border-slate-400')
      }
    >
      {props.children}
    </div>
  )
}
```

- [ ] **Step 2: Create RolesSection**

`webapp/frontend/src/builder/RolesSection.tsx`:

```tsx
import { useEffect, useRef, useState } from 'react'
import { Pencil, Plus, X } from 'lucide-react'
import { useCatalogStore } from '../stores/catalogStore'
import { useDocStore } from '../stores/docStore'
import type { Catalog } from '../types/catalog'
import { effectiveSelection, roleGroups, type RoleTypeGroup } from './roleGroups'
import { Chip } from './Chip'
import { KindIcon } from '../ui/icons'
import { badgeClass, controlClass, inlineButtonClass } from '../ui/controls'
import { IconButton } from '../ui/IconButton'
import { useDismissable } from '../ui/useDismissable'

/** The Roles section, grouped by device type (spec §3.3): per type, radio-style role
 * badges, rename/delete acting on the selected role, the selected role's verb chips
 * rendered ONCE, and an in-place add form whose type is implied by the block — which is
 * what removed both the old type <select> (the horizontal-overflow culprit) and the
 * separate "Manage roles" section. */
export function RolesSection() {
  const catalog = useCatalogStore((s) => s.catalog)
  const roles = useDocStore((s) => s.roles)
  const groups = roleGroups(roles, catalog)
  if (groups.length === 0) {
    return <p className="px-1 text-xs text-hint">no device types in the catalog yet</p>
  }
  return (
    <div className="space-y-2">
      {groups.map((g) => (
        <RoleTypeBlock key={g.type} group={g} catalog={catalog} />
      ))}
    </div>
  )
}

function RoleTypeBlock({ group, catalog }: { group: RoleTypeGroup; catalog: Catalog | null }) {
  const renameRole = useDocStore((s) => s.renameRole)
  const removeRole = useDocStore((s) => s.removeRole)
  const focusedRole = useDocStore((s) => s.focusedRole)
  const [picked, setPicked] = useState<string | null>(null)
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState('')
  const [error, setError] = useState<string | null>(null)
  const cancelled = useRef(false)
  const selected = effectiveSelection(group.roles, picked)

  // A Problems-row click names a role (docStore.focusedRole). When it is one of ours,
  // make it the active badge — so the highlight and the verb chips agree on which role is
  // in view — and scroll it into view, the same jump treatment blocks get from the panel.
  useEffect(() => {
    if (focusedRole !== null && group.roles.includes(focusedRole)) {
      setPicked(focusedRole)
      document
        .getElementById(`role-${focusedRole}`)
        ?.scrollIntoView({ behavior: 'smooth', block: 'center' })
    }
  }, [focusedRole, group.roles])

  const startRename = () => {
    if (!selected) return
    setEditing(true)
    setDraft(selected)
    setError(null)
    cancelled.current = false
  }
  const commitRename = () => {
    if (!selected) return
    const err = draft && draft !== selected ? renameRole(selected, draft) : null
    setError(err)
    if (err === null) {
      setEditing(false)
      if (draft) setPicked(draft)
    }
  }

  const verbs = group.known ? (catalog?.device_types[group.type] ?? {}) : null
  return (
    <div className="rounded border border-slate-200 bg-white p-1.5">
      <p className="mb-1 text-xs font-semibold text-slate-600">
        {group.type}
        {!group.known && <span className="ml-1 font-normal text-amber-600">— unknown device type</span>}
      </p>
      {group.roles.length === 0 ? (
        <p className="mb-1 px-1 text-xs text-hint">no roles yet — add one to use this device</p>
      ) : (
        <div className="mb-1 flex flex-wrap items-center gap-1">
          {group.roles.map((name) =>
            editing && name === selected ? (
              <input
                key={name}
                autoFocus
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                onBlur={() => {
                  if (cancelled.current) {
                    cancelled.current = false
                    return
                  }
                  commitRename()
                }}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') commitRename()
                  if (e.key === 'Escape') {
                    cancelled.current = true
                    setEditing(false)
                  }
                }}
                className={controlClass({ mono: true, width: 'w-28' })}
              />
            ) : (
              <button
                key={name}
                id={`role-${name}`}
                onClick={() => {
                  setPicked(name)
                  setEditing(false)
                  setError(null)
                }}
                className={
                  badgeClass({ active: name === selected }) +
                  (focusedRole === name ? ' ring-2 ring-amber-400' : '')
                }
              >
                {name}
              </button>
            ),
          )}
          <span className="ml-auto flex items-center">
            <IconButton icon={Pencil} label="Rename selected role" onClick={startRename} />
            <IconButton
              icon={X}
              label="Delete selected role"
              destructive
              onClick={() => {
                if (!selected) return
                const err = removeRole(selected)
                setError(err)
                if (err === null) setPicked(null)
              }}
            />
          </span>
        </div>
      )}
      {error && <p className="mb-1 text-xs text-red-600">{error}</p>}
      {selected !== null && verbs !== null && (
        <div className="flex flex-wrap gap-1">
          {Object.entries(verbs).map(([verb, spec]) => (
            <Chip
              key={verb}
              id={`palette-verb-${selected}-${verb}`}
              payload={{ source: 'palette-verb', role: selected, verb, verbKind: spec.kind }}
            >
              <KindIcon kind={spec.kind === 'measure' ? 'measure' : 'command'} className="mr-1" />
              {verb}
            </Chip>
          ))}
        </div>
      )}
      <AddRoleForm type={group.type} onAdded={setPicked} />
    </div>
  )
}

/** "+ add role" reveal form. The type is implied by the enclosing block, so the row is
 * just name + Add — which is precisely what removed the old three-control row that
 * overflowed the 256px palette (finding 2's screenshot). Same dismiss-on-outside-click
 * boundary reasoning as Canvas's ScopeSwitcher: the trigger unmounts while the form is
 * open, so wrapping the form row alone is correct. */
function AddRoleForm({ type, onAdded }: { type: string; onAdded: (name: string) => void }) {
  const addRole = useDocStore((s) => s.addRole)
  const [adding, setAdding] = useState(false)
  const [name, setName] = useState('')
  const [error, setError] = useState<string | null>(null)
  const close = () => {
    setAdding(false)
    setName('')
    setError(null)
  }
  const addingRef = useDismissable(adding, close)
  const add = () => {
    if (!name) return
    const err = addRole(name, type)
    setError(err)
    if (err === null) {
      onAdded(name)
      close()
    }
  }
  if (!adding) {
    return (
      <button onClick={() => setAdding(true)} className={inlineButtonClass({ subtle: true }) + ' mt-1'}>
        <Plus size={12} aria-hidden className="mr-0.5" />add role
      </button>
    )
  }
  return (
    <div ref={addingRef} className="mt-1 space-y-1">
      <div className="flex items-center gap-1">
        <input
          autoFocus
          value={name}
          placeholder="role name"
          onChange={(e) => setName(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') add()
            if (e.key === 'Escape') close()
          }}
          className={controlClass({ mono: true, width: 'w-28' })}
        />
        <button onClick={add} className={inlineButtonClass()}>
          Add
        </button>
      </div>
      {error && <p className="text-xs text-red-600">{error}</p>}
    </div>
  )
}
```

Check `useDismissable`'s actual signature in `src/ui/useDismissable.ts` before wiring (expected `(active: boolean, onDismiss: () => void)` returning a div ref, as ScopeSwitcher uses it) — if it differs, follow the real API.

- [ ] **Step 3: Rewire Palette, delete RolesPanel**

In `webapp/frontend/src/builder/Palette.tsx`:
- Remove the local `Chip` (import it from `./Chip`), the local `AddRoleForm`, the `RolesPanel` import, and the `useDocStore` roles read if now unused.
- Replace the `Roles` and `Manage roles` sections with:

```tsx
      <Section title="Roles">
        {catalogError && <p className="text-xs text-red-600">catalog unavailable: {catalogError}</p>}
        <RolesSection />
      </Section>
```

(import `RolesSection` from `./RolesSection`; `Streams` and `Groups` sections stay as they are).

Then: `git rm webapp/frontend/src/builder/RolesPanel.tsx`

In `webapp/frontend/src/stores/docStore.ts` line ~75, update the comment `// Which role RolesPanel should scroll to…` → `// Which role RolesSection should scroll to…` (behavioral contract unchanged).

- [ ] **Step 4: Gates**

Run: `cd webapp/frontend && npm run lint && npm run typecheck && npm test -- --run && npm run build`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add -A webapp/frontend/src
git commit -m "feat(studio): type-grouped Roles section, selected-role actions, drop Manage roles (W12 §3.3)"
```

---

### Task 5: Separate panel boxes

**Files:**
- Modify: `webapp/frontend/src/builder/BuilderTab.tsx` (line ~139)
- Modify: `webapp/frontend/src/builder/Palette.tsx` (root `<aside>` class)
- Modify: `webapp/frontend/src/builder/Canvas.tsx` (wrapper div class, line ~55)
- Modify: `webapp/frontend/src/builder/Inspector.tsx` (root `<aside>` class, line ~71)

**Interfaces:** class-string changes only; no API changes.

- [ ] **Step 1: Apply the four class changes**

`BuilderTab.tsx` — the panels row loses its shared box (each panel now brings its own):

```tsx
        <div className="flex min-h-0 flex-1 gap-2">
```

(was `"flex min-h-0 flex-1 overflow-hidden rounded-lg border border-slate-200 bg-white"`)

`Palette.tsx` root aside — `border-r` → own rounded box:

```tsx
    <aside className="w-64 shrink-0 space-y-2 overflow-y-auto rounded-lg border border-slate-200 bg-slate-50 p-2">
```

`Canvas.tsx` — the `relative` wrapper becomes the canvas's box; `overflow-hidden` is what clips the slate scroller (and the ScrollFades overlays) to the rounded corner:

```tsx
      <div className="relative min-w-0 flex-1 overflow-hidden rounded-lg border border-slate-200">
```

`Inspector.tsx` root aside — `border-l` → own rounded box:

```tsx
    <aside className="flex w-80 shrink-0 flex-col overflow-y-auto rounded-lg border border-slate-200 bg-slate-50 p-3">
```

- [ ] **Step 2: Gates**

Run: `cd webapp/frontend && npm run lint && npm run typecheck && npm test -- --run && npm run build`
Expected: all pass.

- [ ] **Step 3: Commit**

```bash
git add webapp/frontend/src/builder/BuilderTab.tsx webapp/frontend/src/builder/Palette.tsx webapp/frontend/src/builder/Canvas.tsx webapp/frontend/src/builder/Inspector.tsx
git commit -m "feat(studio): separate rounded boxes for palette/canvas/inspector (W12 §3.1)"
```

---

### Task 6: Single-row header with underline tabs + h-screen refactor

**Files:**
- Modify: `webapp/frontend/src/shell/TabShell.tsx` (full component body)
- Modify: `webapp/frontend/src/builder/BuilderTab.tsx` (line ~130: the calc)

**Interfaces:**
- `TabShell` props unchanged (`active/onSelect/statusLine/lab/children`); `TABS`/`Tab` exports unchanged.
- Tab buttons keep accessible names `1 Devices` … `4 Records` exactly (digit span + label).

- [ ] **Step 1: Rewrite TabShell**

Replace the `TabShell` function body in `webapp/frontend/src/shell/TabShell.tsx`:

```tsx
export function TabShell(props: {
  active: Tab
  onSelect: (tab: Tab) => void
  statusLine: string
  lab: string | null
  children: ReactNode
}) {
  return (
    // h-screen flex column (not min-h-screen + page scroll): <main> owns the scrolling, so
    // nothing downstream needs to know the header's height — this is what retired
    // BuilderTab's h-[calc(100vh-9rem)], which hard-coded the old two-row header.
    <div className="flex h-screen flex-col bg-slate-100 text-slate-900">
      <header className="flex shrink-0 items-stretch gap-6 border-b border-slate-200 bg-white px-6">
        <h1 className="self-center py-3 text-lg font-semibold">Experiment Studio</h1>
        {/* items-stretch + border-b-2 on each tab: the buttons run the full header height,
            so the active tab's underline sits ON the header's own border — reading as an
            attached tab, not a floating pill. */}
        <nav className="flex items-stretch gap-1">
          {TABS.map((tab, i) => (
            <button
              key={tab}
              onClick={() => props.onSelect(tab)}
              className={
                'inline-flex items-center border-b-2 px-3 text-sm transition-colors ' +
                (tab === props.active
                  ? 'border-slate-900 font-medium text-slate-900'
                  : 'border-transparent text-slate-600 hover:border-slate-300 hover:text-slate-900')
              }
            >
              <span className="mr-1.5 font-mono text-xs opacity-60">{i + 1}</span>
              {tab}
            </button>
          ))}
        </nav>
        <span className="ml-auto flex min-w-0 items-center gap-3 self-center py-3">
          <span
            className={
              'shrink-0 rounded-full px-2 py-0.5 text-xs ' +
              (props.lab ? 'bg-blue-100 text-blue-700' : 'bg-slate-100 text-caption')
            }
          >
            {props.lab ? `lab: ${props.lab}` : 'no lab selected'}
          </span>
          {/* truncate + title: a long health string must shorten, not wrap the single row
              at 1024px (spec §3.2). min-w-0 on the parent is what lets it shrink. */}
          <span title={props.statusLine} className="truncate text-xs text-hint">
            {props.statusLine}
          </span>
        </span>
      </header>
      <main className="min-h-0 flex-1 overflow-y-auto p-6">{props.children}</main>
    </div>
  )
}
```

- [ ] **Step 2: Retire the magic height in BuilderTab**

`webapp/frontend/src/builder/BuilderTab.tsx` line ~130:

```tsx
    <div className="flex h-full flex-col gap-2">
```

(was `"flex h-[calc(100vh-9rem)] flex-col gap-2"`.)

Verify nothing else assumes page-level scroll: `grep -rn "100vh\|min-h-screen" webapp/frontend/src/` must return nothing after this change.

- [ ] **Step 3: Gates**

Run: `cd webapp/frontend && npm run lint && npm run typecheck && npm test -- --run && npm run build`
Expected: all pass.

- [ ] **Step 4: Commit**

```bash
git add webapp/frontend/src/shell/TabShell.tsx webapp/frontend/src/builder/BuilderTab.tsx
git commit -m "feat(studio): single-row header with underline tabs; h-screen layout (W12 §3.2)"
```

---

### Task 7: Probe/capture verification, evidence, scripted behavior checks

The committed W11 harness is the DOM-truth gate (frontend CLAUDE.md): re-run it against the changed app, hold the zero-violation baseline, and land before/after evidence plus behavior spot checks a static screenshot can't see.

**Files:**
- Create: `docs/ui-improvements-2/after/` (PNGs + `probe.json` from the capture run)
- Create (scratchpad only, NOT committed): `<scratchpad>/w12-checks.mjs`

**Interfaces:**
- Consumes: `npm run capture -- --out <dir>` (drives Builder states over the two fixtures at 1024/1440/1920; needs dev server on :5173 proxying /api to :8000), `npm run probe:selftest`.

- [ ] **Step 1: Backend venv + servers**

```bash
cd webapp/backend && uv venv && uv pip install -e '.[dev]'
```

Then in background terminals (see `webapp/frontend/tools/README.md` for the harness's own prerequisites — follow it if it differs):

```bash
cd webapp/backend && .venv/bin/python tests/devserver.py   # backend on :8000
cd webapp/frontend && npm run dev                          # vite on :5173
```

- [ ] **Step 2: Probe selftest, then capture**

```bash
cd webapp/frontend && npm run probe:selftest
npm run capture -- --out /private/tmp/claude-501/-Users-khamit-lab-devices/4bf1934c-805c-4545-b5d9-6f1b386307e9/scratchpad/w12-capture
```

Expected: selftest green; capture writes PNGs + `probe.json`.

- [ ] **Step 3: Hold the zero baseline**

```bash
python3 - <<'EOF'
import json
v = json.load(open('/private/tmp/claude-501/-Users-khamit-lab-devices/4bf1934c-805c-4545-b5d9-6f1b386307e9/scratchpad/w12-capture/probe.json'))
print(json.dumps(v, indent=1)[:2000])
EOF
```

Expected: **0 violations** across all state/viewport combos (W11 closed at 0). Any violation = fix the UI (or, if the rule itself is provably wrong, fix the rule with a selftest trap) before proceeding.

- [ ] **Step 4: Scripted behavior checks**

Write `<scratchpad>/w12-checks.mjs` (playwright, `chromium.launch()`, base `http://localhost:5173`) covering, in order:

1. **Roles**: go to Builder; in the first type block with ≥0 roles use `+ add role` to create `spot_a`, then create `spot_b`; click badge `spot_b`; drag the first verb chip onto the canvas root drop slot; assert the created block's header text starts with `spot_b ·`. Then rename `spot_b`→`spot_c` via the pencil (assert canvas header now `spot_c ·`), delete `spot_c` via the ✕ (assert it's gone; `spot_a` becomes selected).
2. **Lanes**: drag the `Parallel` chip onto the canvas; assert the parallel card contains 2 lane headers (`text=lane 1`, `text=lane 2`) and **no** `Serial ·` card text inside it; drag a `Wait` chip into lane 1's "drop here"; assert lane 1 now shows the wait card and still shows its `lane 1` header; delete the wait card via its ✕; assert `lane 1` header still present (lane survived emptying); drag a `Wait` chip onto the horizontal drop slot after lane 2 → assert 3 lane headers exist and the walkthrough shows the wait INSIDE lane 3 (auto-wrap), not as a bare card between lanes.
3. **Header**: `page.setViewportSize({width:1024,height:720})`; assert `header` bounding-box height < 64px and that the four tab buttons and the lab pill are all within the viewport width (no wrap: every tab's y-center equals the title's y-center ±2px).

Drag recipe (the W3-proven pattern — dnd-kit needs it): `page.mouse.down()` on the chip center → move 12px → move to target in ~10 steps → `page.mouse.up()` → `page.waitForTimeout(400)`.

Run: `node <scratchpad>/w12-checks.mjs`
Expected: script prints `ALL CHECKS PASS` (make it exit non-zero otherwise).

- [ ] **Step 5: Commit the evidence**

```bash
mkdir -p docs/ui-improvements-2/after
cp <scratchpad>/w12-capture/*.png <scratchpad>/w12-capture/probe.json docs/ui-improvements-2/after/
git add docs/ui-improvements-2/after
git commit -m "docs: W12 after-evidence — capture screenshots + zero-violation probe run"
```

---

### Task 8: Full gates, PR, merge, release

- [ ] **Step 1: Full gates, both languages**

```bash
cd webapp/backend && .venv/bin/python -m pytest -q && .venv/bin/python -m mypy && .venv/bin/python -m ruff check .
cd ../frontend && npm run lint && npm run typecheck && npm test -- --run && npm run build && npm run probe:selftest
```

Expected: all green (backend suite unaffected but run anyway, per spec §5).

- [ ] **Step 2: Push and open the PR**

```bash
git push -u origin worktree-ui-improvements-2
gh pr create --base main --title "feat(studio): UI improvements round 2 — panel boxes, tabbed header, typed roles, empty lanes (W12)" --body "$(cat <<'EOF'
Implements docs/superpowers/specs/2026-07-18-experiment-studio-ui-improvements-2-design.md — the four hand-found issues in docs/ui-improvements-2/improvements.md:

1. Palette/Canvas/Inspector are separate rounded boxes (were one box with divider lines).
2. Roles grouped by device type: radio badges, selected-role rename/delete (Manage roles section removed), verb chips rendered once, in-block add form (kills the horizontal overflow).
3. Single-row header with underline tabs; h-screen layout retires the h-[calc(100vh-9rem)] magic number.
4. A serial under a parallel renders AS the lane: lanes can be empty, emptying never destroys them, lane-level drops auto-wrap in the pure tree layer (single undo step). Legacy bare-block lanes (both committed fixtures have them) keep card rendering.

Evidence: docs/ui-improvements-2/after/ (capture at 1024/1440/1920, probe.json at 0 violations). Frontend 265+ tests; backend suite green.

🤖 Generated with [Claude Code](https://claude.com/claude-code)

https://claude.ai/code/session_015wMTqGaisQrX91x2zceo8S
EOF
)"
```

- [ ] **Step 3: CI green, merge**

```bash
gh pr checks --watch
gh pr merge --squash --delete-branch
```

(Standing user authorization 2026-07-18 covers the merge — no permission prompt needed. Squash-merge is the repo convention; main is protected, so merge via PR only.)

- [ ] **Step 4: Release**

After the squash lands, release-please opens/updates the release PR (expected version **0.9.0** — feat bump from 0.8.1):

```bash
gh pr list --search "chore(main): release" --state open
gh pr merge <release-pr-number> --squash   # or --merge if the repo's release PR convention differs — check how #34 was merged
gh run watch                                # release build: tag v0.9.0, image + PyPI publish
```

Verify the image exists: `docker manifest inspect ghcr.io/bioexperiment-lab-devices/experiment-studio:v0.9.0` (or check the package page via `gh api`).

---

### Task 9: Preprod deploy + smoke (orchestrator-run, not subagent)

Standing authorization: preprod (`ssh khamit@111.88.145.138`) and `/Users/khamit/lab_devices_server` tooling may be used without asking; `windows_arm64_test_client` is ours for testing.

- [ ] **Step 1: Check the lab_devices_server working tree**

```bash
git -C /Users/khamit/lab_devices_server status --short
```

**If dirty with the user's edits (last known: `scripts/images.sh`, `tests/integration/test_images_cli.bats`): STOP this task and surface to the user — do not commit/stash/work around their changes.** If clean, continue.

- [ ] **Step 2: Bump the studio pin (their W10-proven two-PR recipe)**

```bash
cd /Users/khamit/lab_devices_server
task images:bump -- studio 0.9.0        # edits compose/images.yaml (NOT pins.yaml)
```

Open a `chore:` pin-bump PR; then an **empty** `feat: ship experiment-studio 0.9.0 to the stack` PR (a chore-only bump is release-please-hidden and the deploy job runs only on released==true). Merge both, then merge their release PR (auto-merge is NOT pre-armed there). CI deploys the stack — the studio pin is stack-side, so no laptop `task deploy` is needed (that is only for authelia config).

- [ ] **Step 3: Smoke against the deployed studio**

Via the proven in-network path:

```bash
ssh khamit@111.88.145.138 docker exec -i lab-bridge-jupyter-1 python - <<'EOF'
import json, urllib.request
h = json.load(urllib.request.urlopen('http://studio:8000/api/health', timeout=10))
print('health:', h)
assert '0.9.0' in json.dumps(h), 'expected 0.9.0 deployed'
page = urllib.request.urlopen('http://studio:8000/', timeout=10).read().decode()
assert 'Experiment Studio' in page
print('SMOKE OK')
EOF
```

Expected: `SMOKE OK` with the new version in the health payload. Optionally exercise a device roster call against `windows_arm64_test_client` for real-lab confirmation. Report results (and the W11→W12 pin jump 0.8.0→0.9.0 closing the stale-pin blocker) to the user.
