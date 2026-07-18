# Element library taxonomy — design

**Date:** 2026-07-18
**Status:** approved (pending spec review)
**Scope:** the block-chip sections of the Builder palette (`webapp/frontend/src/builder/Palette.tsx`) and the kind types they are built from (`tree.ts`).

## 1. Problem

The palette's three block sections are not a taxonomy. They are a deposition record — three
layers laid down by three increments, each coherent alone and incoherent together:

| Section | Chips | Arrived in |
|---|---|---|
| Structure | serial, parallel, loop, branch, wait, operator_input | Increment 3 (builder UI) |
| Control | compute, record, alarm, abort | Increment 8 (engine parity) |
| Repeat | for_each, group_ref | Increment 9 (repetition) |

Four defects follow from that history.

**D1 — `loop` and `for_each` are separated twins.** Both are bounded repetition over a body.
They sit in different sections only because `for_each` shipped six increments later. An author
looking for "do this for each tube" has no reason to search somewhere other than where "do this
5 times" lives.

**D2 — "Repeat" contains something that does not repeat.** `group_ref` is a call to a named,
parametrized sub-procedure: no body, no iteration. It is filed under Repeat because it shipped
in the increment titled *parametrized repetition*. Meanwhile a **Groups** section already exists
lower in the same palette, listing the declared groups — which is where authors look for them.

**D3 — "Control" is the wrong word and the word is already taken.** In ordinary programming
vocabulary "control flow" means branch and loop, both of which are in *Structure*. The code
already knows the real unifying idea: `tree.ts:11` documents `ControlKind` as *"Leaf blocks that
act on run state rather than on a device."* That is "run state", not "control".

**D4 — "Structure" is three unrelated things.** `serial`/`parallel` are pure composition with no
behaviour of their own; `loop`/`branch` decide what runs; `wait`/`operator_input` have no child
slots at all and therefore structure nothing — one blocks on the clock, the other on a human.

The two axes that actually exist in the model are:

- **Does the block hold other blocks?** `serial`, `parallel`, `loop`, `branch`, `for_each` have
  child slots (`tree.ts:157` `childSlots`); nothing else does. This is the drag-and-drop
  affordance — it tells an author whether something can be dropped inside.
- **What does the block act on?** A device, run state, the clock, the operator, or the run's fate.

Neither axis is what the current three sections encode.

## 2. Settled decisions

| # | Decision | Rationale |
|---|---|---|
| S1 | Four sections: **Flow**, **Data**, **Pause**, **Safety** | Every name is unambiguous; no bucket exceeds five chips. Costs one section header (palette goes from 7 to 8 sections including Roles/Manage roles/Streams/Groups). |
| S2 | Engineering register for labels | Short enough for the 256px palette column (`w-64`, `Palette.tsx:176`) and consistent with the vocabulary already used in the Inspector and the design docs. |
| S3 | `group_ref` leaves the block sections; the Groups section renders **one draggable chip per declared group** | The Groups panel already lists them. Dragging `dilute (tube)` directly beats dragging a blank `Group ref` and then selecting the group in the Inspector. |
| S4 | The kind types are renamed to match the sections | The current names are the source of D3: `ControlKind` is documented as meaning something other than what it is called. Blast radius is three lines in `tree.ts` plus their only consumer, `Palette.tsx`. |

## 3. The new taxonomy

```
FLOW      [Serial] [Parallel] [Branch] [Loop] [For each]
DATA      [Compute] [Record]
PAUSE     [Wait] [Operator input]
SAFETY    [Alarm] [Abort]
…
GROUPS    [dilute (tube)]  [sample (tube, ml)]      ← draggable, one per declared group
```

**Flow** — everything that holds a body and decides what runs, in what order, and how many
times. Chip order is a deliberate progression: composition (`serial`, `parallel`), then decision
(`branch`), then repetition (`loop`, `for_each`). This is exactly the set with child slots, so
the section boundary coincides with the drop affordance.

**Data** — blocks that write run state: `compute` writes a binding, `record` writes to a declared
stream. This is the honest name for what `ControlKind` was documented as meaning.

**Pause** — blocks whose whole purpose is to not proceed yet: `wait` blocks on the clock,
`operator_input` blocks on a human.

**Safety** — blocks that change the run's fate: `alarm` flags and continues, `abort` stops.

The `wait`/`operator_input` and `alarm`/`abort` pairs were considered as one "Run control"
section. They are kept apart because "pause and continue" and "flag or stop" are different
enough that a single label for both has to be abstract, and abstraction is what produced D3.

## 4. Model changes (`tree.ts`)

Replace lines 8–13:

```ts
export type FlowKind = 'serial' | 'parallel' | 'branch' | 'loop' | 'for_each'
/** Leaf blocks that write run state rather than acting on a device (Increment 6). */
export type DataKind = 'compute' | 'record'
/** Leaf blocks that hold the run until the clock or the operator releases it. */
export type PauseKind = 'wait' | 'operator_input'
/** Leaf blocks that change the run's fate (Increment 8): alarm flags, abort stops. */
export type SafetyKind = 'alarm' | 'abort'
/** Every kind `newPaletteNode` can construct. `group_ref` is in the union but has no
 * section of its own — it is dragged from the Groups panel (design §6). */
export type PaletteKind = FlowKind | DataKind | PauseKind | SafetyKind | 'group_ref'
```

`StructureKind`, `ControlKind`, and `RepeatKind` are deleted. They have exactly two consumers —
`Palette.tsx:6` (chip array types) and the `PaletteKind` union on `tree.ts:13` — both rewritten
here. `PaletteKind` keeps the same member set, so `newPaletteNode` (`tree.ts:341`), the
`BlockNode` union, `childSlots`, `replaceSlot`, and every store operation are untouched.

The retained note on `DataKind`/`SafetyKind` must preserve the fact currently carried by
`ControlKind`'s comment: none of these takes `retry` — retry is command/measure only
(design 2026-07-14 §2.1).

## 5. Palette changes (`Palette.tsx`)

The three chip arrays become four, typed by the new kinds, and move out of `Palette.tsx` into a
new pure module `src/builder/paletteSections.ts`. The extraction is what makes §9's partition
test possible: `vitest` runs in a node environment with no rendering, so a test cannot import
`Palette.tsx` (React, dnd-kit, and the zustand stores come with it) — but it can import plain
data. The four arrays are exported individually and as an ordered `BLOCK_SECTIONS` list that
`Palette` maps over.

```ts
const FLOW: Array<{ kind: FlowKind; title: string }> = [
  { kind: 'serial', title: 'Serial' },
  { kind: 'parallel', title: 'Parallel' },
  { kind: 'branch', title: 'Branch' },
  { kind: 'loop', title: 'Loop' },
  { kind: 'for_each', title: 'For each' },
]
const DATA: Array<{ kind: DataKind; title: string }> = [ /* Compute, Record */ ]
const PAUSE: Array<{ kind: PauseKind; title: string }> = [ /* Wait, Operator input */ ]
const SAFETY: Array<{ kind: SafetyKind; title: string }> = [ /* Alarm, Abort */ ]
```

All four render through the same `Chip`, the same payload source, and — once chip `id`s become
`palette-block-${kind}` — the same `id` scheme, leaving `title` and the array as the only
differences between them. They collapse into one `BlockSection` helper taking `{ title, items }`:
four near-identical 12-line JSX blocks (`Palette.tsx:177-218`) is the kind of duplication that let
the current sections drift apart in the first place.

`palette-block-${kind}` stays unique across the palette because the four arrays partition the
kinds, which §9's unit test enforces.

The comment block at `Palette.tsx:30-33` (explaining that `for_each`'s `∀` cannot be confused
with `loop`'s Repeat icon, and that Repeat chips share the Structure payload source) is deleted:
both facts stop being surprising once the two chips are in the same section on the same source.
The icon distinction itself stays — `KindIcon` is unchanged, since no block kind changes.

## 6. Groups section (`Palette.tsx`, `GroupsPanel`)

`GroupsPanel` (`Palette.tsx:125`) currently renders each group as a jump button, a params
caption, and a delete `IconButton`. It gains a drag affordance on the same row: the group's
name+params becomes a draggable `Chip` with `id` `palette-group-${name}` — unique because group
names are already unique keys of the store's `groups` record, and disjoint from the block chips'
`palette-block-` prefix. The jump and delete actions stay as explicit buttons beside it.

Click and drag don't conflict on this row because they don't live on the same element: the
chip itself carries only the drag listeners (`useDraggable`) and has no `onClick` at all. The
jump action that used to be the chip's click handler moved to its own `Pencil` `IconButton`
beside the chip, so a press-and-release on the chip is simply a drag that never left the
ground — there is nothing on that element to disambiguate it from.

A hint line — "Drag a group onto the canvas to call it." — sits under the populated list, because
the affordance is otherwise undiscoverable once no `Group ref` chip advertises it. It goes under
the *list*, not in the empty state: with no groups declared there is nothing to drag, so the same
sentence there would be noise. The empty state keeps its current copy.

**`renameGroup` stays unwired.** It already exists on the store with no UI, and nothing in this
change calls for one.

## 7. Drag payload (`dnd.ts`, `BuilderTab.tsx`)

`palette-structure` is renamed to `palette-block` — "structure" no longer names anything — and a
variant is added for group chips:

```ts
export type DragPayload =
  | { source: 'palette-block'; kind: PaletteKind }
  | { source: 'palette-group'; name: string }
  | { source: 'palette-verb'; role: string; verb: string; verbKind: 'command' | 'measure' }
  | { source: 'canvas'; uid: string }
```

`palette-group` carries only the group name; `args` is left empty for the Inspector to fill, the
same as today's blank `Group ref`. It is a distinct source rather than a `PaletteKind` carrying a
name because `newPaletteNode` takes a kind and nothing else, and widening it to take an optional
payload for one case would push a group-shaped parameter through every unrelated call.

In `BuilderTab.tsx`:

- `STRUCTURE_TITLES` (line 25) is renamed `BLOCK_TITLES` and derived from `BLOCK_SECTIONS`
  (`paletteSections.ts`) instead of hand-maintained, so it can never disagree with the palette's
  own chip titles. It therefore covers only the eleven kinds `BLOCK_SECTIONS` lists, not
  `group_ref` — the `palette-group` arm below supplies that label itself, from the group's own
  name rather than a fixed "Group ref" string.
- `dragOverlayInfo` (line 44) gains a `palette-group` arm returning
  `{ label: name, kind: 'group_ref' }`, so a dragged group shows the group-ref icon and its own
  name rather than the generic "Group ref".
- `onDragEnd` (line 120) gains a `palette-group` arm inserting `newGroupRefNode(name)` — a
  dedicated constructor (`tree.ts`) rather than `{ ...newPaletteNode('group_ref'), name }`, for
  the same reason `palette-group` is its own `DragPayload` variant above: `newPaletteNode`
  takes a kind and nothing else, so the group-shaped parameter gets its own constructor
  instead of being pushed through every unrelated `newPaletteNode` call.

The two `payload.source === 'palette-structure'` comparisons (lines 45 and 120) become
`'palette-block'`.

## 8. Compatibility

No persisted format changes. Section membership is presentation only: the twelve block kinds,
their JSON serialization (`convert.ts`), the engine AST, and every saved document are untouched.
There is no migration.

## 9. Testing

`vitest` runs in a node environment with no component rendering (`webapp/frontend/CLAUDE.md`),
so the palette's sections cannot be asserted directly. Coverage is therefore:

- **Type-level** — the rewritten `PaletteKind` must still admit exactly the twelve kinds
  `newPaletteNode` handles. `tsc` enforces this: `newPaletteNode`'s `switch` is exhaustive over
  `PaletteKind` with no `default`, so a dropped member fails the build and an added one fails the
  return-type check.
- **Unit** — `paletteSections.test.ts` asserts the four chip arrays partition `PaletteKind` minus
  `group_ref`: no kind appearing twice, none missing, and `group_ref` in no section. This is the
  regression guard for the actual defect being fixed — a kind silently landing in the wrong
  section, in two sections, or in none.
- **Existing** — `tree.test.ts` and `convert.test.ts` must pass unchanged; if either needs
  editing, the change has leaked past presentation and the design is wrong.
- **Probe** — `npm run capture` against a real doc, per `webapp/frontend/CLAUDE.md`, since the
  Groups rows gain a control on a shared visual line and R4 (`sibling-height-mismatch`) is the
  rule that catches a chip whose height disagrees with the `IconButton`s beside it.

## 10. Out of scope

- Renaming or re-icon-ing any block kind.
- The Roles, Manage roles, and Streams sections.
- Group rename UI.
- Search or filtering over the palette.
- Any change to how the canvas renders blocks.
