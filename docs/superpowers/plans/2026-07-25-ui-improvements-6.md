# UI improvements 6 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix seven Experiment Studio Builder defects reported after PR #81 — the vertical
counterpart of #81's horizontal lane rule, plus four palette fixes — and ship a demo
fixture that makes the canvas-geometry ones reproducible.

**Architecture:** One new concept, the **chip band**: the vertical region a lane's cards
occupy (first card's top edge → last card's bottom edge), excluding the `LANE N`/`then`/
`else` label row and the 12px drop-slot gaps that bracket the cards. Three things fill it —
the "drop here" hint, `+ lane`, `+ add else` — all by the same mechanism (`flex-1` inside a
stretched column), not by three sets of hand-tuned margins. The tokens live in
`src/builder/laneLayout.ts`, which already owns the lane arithmetic and has a test pinning
it to `CONTROL_H_PX`. The palette fixes are independent and touch one file each.

**Tech Stack:** React 19, TypeScript, Tailwind 4, zustand, dnd-kit, vitest (node env),
Playwright (capture harness only).

**Spec:** `docs/superpowers/specs/2026-07-25-ui-improvements-6-design.md`

## Global Constraints

Copied from `webapp/frontend/CLAUDE.md`. Every task's requirements implicitly include these.

- **Tailwind class names must be complete literals in source.** Tailwind 4 scans source
  text; `` `min-h-${n}` `` compiles to no CSS at all.
- **Helpers SELECT exactly one class per property, never append.** Equal-specificity
  utilities in one `@layer utilities` block are decided by compiled order, not string
  order. `controlClass({ width: 'w-28' })`, never `controlClass() + ' w-28'`.
- **Control height lives only in `src/ui/controls.ts`.** Every input/select/inline button is
  24px (`CONTROL_H` / `CONTROL_H_PX = 24`). `stretch: true` is the one sanctioned exception
  and *replaces* the height class.
- **Every `<button>` renders at ≥24×24px** (probe rule `tiny-target`).
- **Every truncating element carries its own `title`** (probe rule `truncate-without-title`).
- **No `dark:` variants, hex, or arbitrary colour values.** Dark theme is a palette remap in
  `index.css`. Arbitrary *spacing* values are not banned, but prefer scale tokens.
- **Interactive icons come from lucide-react via `IconButton`.** No raw glyph characters for
  interactive controls.
- **vitest runs in a node env**: pure functions only. No component rendering, no jsdom, no
  @testing-library. DOM wiring is verified by the Playwright probe harness, not unit tests.
- Working tree: `/Users/khamit/lab-devices-ui6`, branch `fix/ui-improvements-6`.
  All paths below are relative to `webapp/frontend/` unless they start with `webapp/`.

**Already resolved — do not re-litigate:** `min-h-8.5` *does* compile under Tailwind 4,
verified by building with the class present and grepping the emitted CSS:
`min-h-8\.5{min-height:calc(var(--spacing) * 8.5)}` = 34px. Use the token form, not
`min-h-[34px]`.

**Measured baseline** (real app, `examples/morbidostat.json` + the demo doc):
leaf card 34px · vertical `DropSlot` 12px (8px box + 2×2px margin) · lane top → first card
40px · "drop here" 42px tall starting 28px down · palette `scrollWidth` 254 → 437 with one
long stream name.

---

### Task 1: Chip-band tokens

**Files:**
- Modify: `src/builder/laneLayout.ts`
- Test: `src/builder/laneLayout.test.ts`

**Interfaces:**
- Consumes: `CONTROL_H`, `CONTROL_H_PX` from `src/ui/controls.ts` (already imported by the test).
- Produces: `CHIP_H_PX: number`, `CHIP_MIN_H: string`, `CHIP_GAP: string`,
  `CHIP_GAP_PX: number`, `LANE_LABEL_H: string`, `DROP_SLOT_V: string` — all exported from
  `src/builder/laneLayout.ts`. Tasks 4 and 5 import them.

- [ ] **Step 1: Widen the test's `px()` helper to accept fractional suffixes**

`src/builder/laneLayout.test.ts` currently parses only integers, so `my-0.5` and
`min-h-8.5` would throw on the `!` non-null assertion. Replace the helper:

```ts
/** Tailwind's spacing unit is 4px, so `mt-7` is 28px and `my-0.5` is 2px. The tokens are
 * literals because the class scanner cannot see a template string, which is why this test
 * checks the arithmetic behind them rather than generating them from it. */
const px = (cls: string): number => Number(cls.match(/-([\d.]+)$/)![1]) * 4
```

- [ ] **Step 2: Write the failing tests**

Append to `src/builder/laneLayout.test.ts`, and add the new names plus `CONTROL_H` to the
existing imports at the top of the file:

```ts
describe('chip band tokens', () => {
  it('derives a chip band's floor from the control token', () => {
    // A leaf card is its header's one CONTROL_H row inside `py-1`, plus the card's 1px
    // border top and bottom. Anything standing in for a card — the "drop here" hint,
    // "+ lane", "+ add else" — is at least this tall, so if the control token moves this
    // fails and the floor must move with it.
    const CARD_HEADER_PAD_PX = 4 // the header's py-1
    const CARD_BORDER_PX = 1
    expect(CHIP_H_PX).toBe(CONTROL_H_PX + 2 * CARD_HEADER_PAD_PX + 2 * CARD_BORDER_PX)
    expect(px(CHIP_MIN_H)).toBe(CHIP_H_PX)
  })

  it('reproduces a vertical drop slot's air with margins of its own', () => {
    // The empty-list hint IS the leading DropSlot, so there is no earlier sibling to supply
    // the 12px above it: it has to carry that air itself. Margins do not collapse inside a
    // flex container, so 12 + 34 + 12 reproduces a one-card lane's slot+card+slot exactly.
    const [slotMargin, slotBox] = DROP_SLOT_V.split(' ')
    expect(CHIP_GAP_PX).toBe(px(slotBox) + 2 * px(slotMargin))
    expect(px(CHIP_GAP)).toBe(CHIP_GAP_PX)
  })

  it('pins the lane label row to the control token', () => {
    // ChipBand reproduces this row invisibly so "+ lane" starts where a lane's cards do.
    expect(LANE_LABEL_H).toBe(CONTROL_H)
  })
})
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `npm test -- laneLayout`
Expected: FAIL — `CHIP_H_PX`, `CHIP_MIN_H`, `CHIP_GAP`, `CHIP_GAP_PX`, `LANE_LABEL_H`,
`DROP_SLOT_V` are not exported.

- [ ] **Step 4: Add the tokens**

Append to `src/builder/laneLayout.ts`:

```ts
/** A leaf card's height: the header's one CONTROL_H row inside `py-1`, plus the card's 1px
 * border top and bottom (measured 34px on the real app). Everything that stands in for a
 * card inside a lane is at least this tall, so an empty lane beside a one-card lane reads
 * as the same box rather than as a taller, looser one. */
export const CHIP_H_PX = 34
export const CHIP_MIN_H = 'min-h-8.5'

/** A vertical DropSlot's own box and margins, owned here so the filler that REPLACES the
 * slots can reproduce them. Before this, BranchLanes carried a hand-copied `my-0.5 h-2`
 * spacer with a comment telling the next reader to keep it in sync by hand. */
export const DROP_SLOT_V = 'my-0.5 h-2'

/** The air a vertical DropSlot occupies above and below a card. The empty-list hint IS the
 * leading slot, so it has no earlier sibling to supply this and must carry it as margin. */
export const CHIP_GAP_PX = 12
export const CHIP_GAP = 'my-3'

/** The `LANE N` / `then` / `else` row above a lane's cards — one CONTROL_H, inside the
 * lane's padding. ChipBand (Canvas.tsx) reproduces it invisibly so a control that sits
 * OUTSIDE any lane still starts where the lanes' cards start. */
export const LANE_LABEL_H = 'h-6'
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `npm test -- laneLayout`
Expected: PASS (6 tests — 3 existing, 3 new).

- [ ] **Step 6: Commit**

```bash
git add src/builder/laneLayout.ts src/builder/laneLayout.test.ts
git commit -m "feat(studio): chip-band layout tokens"
```

---

### Task 2: A shrinkable inline button

**Files:**
- Modify: `src/ui/controls.ts`
- Test: `src/ui/controls.test.ts`

**Interfaces:**
- Produces: `inlineButtonClass({ shrinkable: true })` — selects `min-w-0 max-w-full` in
  place of the baked `shrink-0`. Task 8 consumes it.

- [ ] **Step 1: Write the failing tests**

Append to `src/ui/controls.test.ts`:

```ts
describe('inline button shrinkable', () => {
  it('swaps shrink-0 for a shrinkable box instead of emitting both', () => {
    // A button that sizes to its content cannot be capped by appending a width: the row it
    // sits in overflows instead. `shrinkable` SELECTS the shrinkable box, so there is only
    // ever one sizing rule in the output and no cascade fight to lose.
    const cls = inlineButtonClass({ shrinkable: true })
    expect(cls).toContain('min-w-0')
    expect(cls).toContain('max-w-full')
    expect(cls.split(/\s+/)).not.toContain('shrink-0')
  })

  it('leaves every other caller unshrinkable', () => {
    expect(inlineButtonClass().split(/\s+/)).toContain('shrink-0')
    expect(inlineButtonClass({ subtle: true }).split(/\s+/)).toContain('shrink-0')
  })

  it('keeps a shrinkable button on the height token', () => {
    expect(heights(inlineButtonClass({ shrinkable: true }))).toEqual([CONTROL_H])
  })
})
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `npm test -- controls`
Expected: FAIL — the class still contains `shrink-0` and lacks `min-w-0`.

- [ ] **Step 3: Add the option**

In `src/ui/controls.ts`, extend `inlineButtonClass`'s options type with
`shrinkable?: boolean` and move `shrink-0` out of the shared literal:

```ts
export function inlineButtonClass(
  opts: {
    subtle?: boolean
    danger?: boolean
    active?: boolean
    width?: string
    stretch?: boolean
    shrinkable?: boolean
  } = {},
): string {
  return (
    `${opts.stretch ? 'self-stretch' : CONTROL_H} ${opts.width ? opts.width + ' ' : ''}` +
    'inline-flex items-center justify-center rounded border px-2 text-xs ' +
    // `shrinkable` is for a button whose LABEL is user data (a stream name), where sizing to
    // content lets one long value push the 256px palette into horizontal scroll — measured
    // 254 -> 437px scrollWidth. It SELECTS the shrinkable box rather than appending one, for
    // the same cascade reason as `width`; the caller puts a `truncate` span with its own
    // `title` inside, which is also what the probe's truncate-without-title rule requires.
    (opts.shrinkable ? 'min-w-0 max-w-full ' : 'shrink-0 ') +
    'disabled:opacity-40 ' +
    // ... variant selection below is unchanged
```

Leave the `subtle`/`active`/`danger` ternary exactly as it is.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `npm test -- controls`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/ui/controls.ts src/ui/controls.test.ts
git commit -m "feat(studio): shrinkable inline button variant"
```

---

### Task 3: Delete the leaf card's 24px spacer

**Files:**
- Modify: `src/builder/Canvas.tsx` (in `BlockView`, the `isContainer` ternary)

**Interfaces:**
- Consumes: nothing. Produces: nothing. Standalone.

- [ ] **Step 1: Replace the ternary with a conditional**

In `src/builder/Canvas.tsx`, `BlockView`'s header currently renders:

```tsx
        {isContainer ? (
          <IconButton
            icon={collapsed ? ChevronRight : ChevronDown}
            label={collapsed ? 'Expand' : 'Collapse'}
            onClick={(e) => {
              e.stopPropagation()
              toggleCollapsed(node.uid)
            }}
          />
        ) : (
          <span aria-hidden className="h-6 w-6 shrink-0" />
        )}
```

Replace with:

```tsx
        {/* No placeholder for a leaf. Reserving the chevron's 24px on every leaf card put its
            icon in the same column as a container's chevron, which bought a rhythm nobody
            asked for at the price of 24px of horizontal space on every leaf — and leaves are
            the majority of cards. Leaf content now starts at the card's padding edge. */}
        {isContainer && (
          <IconButton
            icon={collapsed ? ChevronRight : ChevronDown}
            label={collapsed ? 'Expand' : 'Collapse'}
            onClick={(e) => {
              e.stopPropagation()
              toggleCollapsed(node.uid)
            }}
          />
        )}
```

- [ ] **Step 2: Typecheck and build**

Run: `npm run typecheck && npm run lint`
Expected: clean. (`isContainer` is still used by the `!collapsed && isContainer` branches
below, so no unused-variable warning.)

- [ ] **Step 3: Commit**

```bash
git add src/builder/Canvas.tsx
git commit -m "fix(studio): drop the 24px chevron placeholder from leaf cards"
```

---

### Task 4: The stretch chain and the "drop here" band

**Files:**
- Modify: `src/builder/DropSlot.tsx`
- Modify: `src/builder/Canvas.tsx` (`BlockList`, `Lane`, `BranchLanes`)

**Interfaces:**
- Consumes: `CHIP_GAP`, `CHIP_MIN_H`, `DROP_SLOT_V` from Task 1.
- Produces: a `Lane` and branch arms that are `flex flex-col`, and a `BlockList` that fills
  them. Task 5 relies on the arms being flex columns.

- [ ] **Step 1: Make the vertical DropSlot use the shared token**

In `src/builder/DropSlot.tsx`, add `CHIP_GAP`, `CHIP_MIN_H` and `DROP_SLOT_V` to the
existing `laneLayout` import, and in the non-hint return replace the literal
`'my-0.5 h-2 '` with `` `${DROP_SLOT_V} ` ``:

```tsx
        (horizontal
          ? `self-stretch ${divider ? `flex justify-center ${LANE_GUTTER_W}` : LANE_EDGE_W} `
          : `${DROP_SLOT_V} `) +
```

- [ ] **Step 2: Give the hint the chip band**

Replace the `if (hint)` block's `className` in `src/builder/DropSlot.tsx`. Note `py-3` is
gone (it made the box 42px against a 34px card) and the box now centres its text itself:

```tsx
  if (hint) {
    return (
      <div
        ref={setNodeRef}
        className={
          // The hint stands in for a lane's CARDS, so it is sized and placed like them
          // (spec 3.4): at least one card tall, carrying the 12px a DropSlot would put above
          // and below a card, and growing to fill whatever the tallest sibling lane sets.
          // It IS the leading slot (index 0), so nothing earlier can supply that air.
          `flex flex-1 items-center justify-center rounded border border-dashed px-2 ` +
          `text-center text-xs ${CHIP_GAP} ${CHIP_MIN_H} ` +
          // A horizontal hint is the empty state of a parallel's lane row, and that row's body
          // has no horizontal padding of its own (the gutters supply it), so the hint carries
          // its own 8px. A vertical hint's padding still comes from the parent body.
          (horizontal ? 'mx-2 ' : '') +
          (highlight
            ? // Already opaque (bg-blue-50 fully paints the box), so this branch never
              // needs the hatch backing below regardless of scope.
              'border-blue-400 bg-blue-50 text-blue-500'
            : // Same reasoning as ScopeSwitcher's strip (Canvas.tsx): "drop here" must not
              // sit directly on the canvas hatch, so it goes solid white whenever a group
              // scope is active.
              'border-slate-300 text-caption' + (scope === null ? '' : ' bg-white shadow-sm'))
        }
      >
        drop here
      </div>
    )
  }
```

- [ ] **Step 3: Let `BlockList` fill a flex column**

In `src/builder/Canvas.tsx`, `BlockList`'s root:

```tsx
  return (
    // `min-h-0 flex-1` is what lets an empty list's hint span a taller sibling lane. It is
    // inert in this component's other parents (a loop's body, the canvas root): flex-basis
    // does not apply to a block-level child of a block-level box.
    <div className="flex min-h-0 flex-1 flex-col">
```

- [ ] **Step 4: Make `Lane` a flex column**

In `src/builder/Canvas.tsx`, `Lane`'s outer `className`, change
`` `min-w-48 flex-initial rounded ${LANE_PAD} ` `` to:

```tsx
        `flex min-w-48 flex-initial flex-col rounded ${LANE_PAD} ` +
```

and add `shrink-0` to the lane's handle row so the label cannot be compressed:

```tsx
        className="flex h-6 min-w-0 shrink-0 cursor-grab items-center gap-1 px-1 text-[10px] uppercase text-caption"
```

- [ ] **Step 5: Make the branch arms flex columns**

In `src/builder/Canvas.tsx`, `BranchLanes` — both arms:

```tsx
      <div className={`flex min-w-48 flex-initial flex-col ${LANE_PAD}`}>
```

and add `shrink-0` to all three label rows (`then`, and both `else` variants), e.g.:

```tsx
        <p className="flex h-6 shrink-0 items-center px-1 text-[10px] uppercase text-caption">then</p>
```

- [ ] **Step 6: Verify against the real app**

Start the servers (backend from the primary checkout is fine — this change is frontend-only):

```bash
# terminal A, once
cd /Users/khamit/lab-devices/webapp/backend && STUDIO_DATA_DIR=data .venv/bin/python -m uvicorn --factory experiment_studio.app:create_app --port 8000
# terminal B
cd /Users/khamit/lab-devices-ui6/webapp/frontend && npm install && npm run dev
```

Load a doc with a parallel whose lanes differ in height (Task 9's fixture, or
`examples/morbidostat.json` plus a hand-emptied lane) and confirm in the browser:

1. An empty lane's "drop here" **starts at the same y** as a sibling lane's first card.
2. It **ends at the same y** as the tallest sibling lane's last card.
3. A one-card lane beside an empty lane gives a 34px hint, not 42px.

Expected measurement (DevTools): hint `getBoundingClientRect().height` equals the tallest
lane's cards-plus-gaps span; hint top equals a sibling card's top.

- [ ] **Step 7: Commit**

```bash
git add src/builder/DropSlot.tsx src/builder/Canvas.tsx
git commit -m "fix(studio): size and place \"drop here\" like the cards it stands in for"
```

---

### Task 5: `ChipBand`, `+ lane` and `+ add else`

**Files:**
- Modify: `src/builder/Canvas.tsx` (new `ChipBand`, `ParallelLanes`, `BranchLanes`)

**Interfaces:**
- Consumes: `CHIP_GAP`, `LANE_LABEL_H`, `LANE_PAD` from Task 1; the flex-column arms from
  Task 4.
- Produces: `ChipBand({ children, className })` — local to `Canvas.tsx`.

- [ ] **Step 1: Add the `ChipBand` component**

In `src/builder/Canvas.tsx`, above `ParallelLanes`:

```tsx
/** A column OUTSIDE any lane that reproduces a lane's vertical geometry, so its child fills
 * exactly the band a lane's CARDS occupy: the lane's own padding, then the invisible
 * counterpart of the `LANE N` label row, then the band, bracketed by the air a vertical
 * DropSlot puts above and below a card.
 *
 * Two things need it, and neither lives inside a `Lane` so neither inherits any of it: the
 * "+ lane" button, and the lane row's own empty state (a parallel whose lanes have all been
 * deleted), which has no lanes to align with but still has "+ lane" beside it. Expressed as
 * geometry rather than as a hand-tuned `mt-10 mb-4`, so it tracks the tokens. */
function ChipBand({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <div className={`flex flex-col ${LANE_PAD} ` + (className ?? '')}>
      <span aria-hidden className={`shrink-0 ${LANE_LABEL_H}`} />
      <div className={`flex min-h-0 flex-1 items-stretch ${CHIP_GAP}`}>{children}</div>
    </div>
  )
}
```

Add `ReactNode` to the `react` type import at the top of the file:
`import { Fragment, createContext, ..., type ReactNode } from 'react'`.

- [ ] **Step 2: Put `+ lane` and the empty-row hint in the band**

In `ParallelLanes`, replace the empty-state slot and the button:

```tsx
      {node.children.length === 0 ? (
        <ChipBand>
          <DropSlot at={{ parentUid: node.uid, slot: 'children', index: 0 }} horizontal hint />
        </ChipBand>
      ) : (
        // The append slot doubles as the divider that gives "+ lane" a compartment of its own.
        <DropSlot
          at={{ parentUid: node.uid, slot: 'children', index: node.children.length }}
          horizontal
          hint={false}
          divider
        />
      )}
      {/* `mr-2` gives the row the same 8px right edge the leading gutter gives it on the left;
          the band supplies everything vertical. `stretch` in a flex ROW is full height at
          content width — this button must NOT take a `width`, or it stops fitting its label. */}
      <ChipBand className="mr-2">
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
          className={inlineButtonClass({ subtle: true, stretch: true })}
        >
          <Plus size={12} aria-hidden className="mr-0.5" />lane
        </button>
      </ChipBand>
```

- [ ] **Step 3: Put `+ add else` in the band**

In `BranchLanes`, the `node.else === null` arm. Replace the whole
`<div className="flex flex-col">…</div>` wrapper — including the `my-0.5 h-2` spacer and the
comment above it, both of which this token replaces — with:

```tsx
            {/* The same band the THEN arm's cards occupy (spec 3.5). This replaces a
                hand-copied `my-0.5 h-2` spacer whose comment asked the next reader to keep it
                in sync with DropSlot by hand; CHIP_GAP is that sync. */}
            <div className={`flex min-h-0 flex-1 items-stretch ${CHIP_GAP}`}>
              <button
                onClick={(e) => {
                  e.stopPropagation()
                  patchBlock(node.uid, { else: [] })
                }}
                // Same control as the Inspector's "+ add else lane" (Inspector.tsx), routed
                // through the same helper so a change to the subtle variant reaches both.
                // No `width`: the button fits its label and the band gives it its height.
                className={inlineButtonClass({ subtle: true, stretch: true })}
              >
                <Plus size={12} aria-hidden className="mr-0.5" />add else
              </button>
            </div>
```

Keep the `<p>…else…</p>` label row above it exactly as Task 4 left it.

- [ ] **Step 4: Verify against the real app**

With the dev server from Task 4 running and the same doc loaded, confirm:

1. `+ lane` starts and ends on the same lines as the lanes' cards — **not** at the top of
   the `LANE N` label row, and **not** at the bottom of the container's padding.
2. `+ lane` is as wide as its label, not stretched.
3. `+ add else` is as tall as the THEN arm's cards-plus-gaps span, as wide as its label, and
   left-aligned in the ELSE arm.
4. A parallel with every lane deleted shows the hint and `+ lane` aligned with each other.

- [ ] **Step 5: Typecheck, lint, test**

Run: `npm run typecheck && npm run lint && npm test`
Expected: all clean.

- [ ] **Step 6: Commit**

```bash
git add src/builder/Canvas.tsx
git commit -m "fix(studio): align \"+ lane\" and \"+ add else\" to the chip band"
```

---

### Task 6: Constants add-form row order

**Files:**
- Modify: `src/builder/ConstantsPanel.tsx` (the create form only — the edit rows are already
  stacked and were not reported)

**Interfaces:** standalone.

- [ ] **Step 1: Reorder the form**

Replace the create-form block (the `<div className="space-y-1">` after the `<ul>`) with:

```tsx
      {/* Create form mirrors the stacked edit rows, with `Add` as the LAST control the user
          reaches rather than the second (#2): name, then a full-width expression editor for
          the value, then unit + Add. ExpressionEditor commits on blur/Enter into newValue;
          pressing Add (or Enter in the name/unit input) creates the constant. */}
      <div className="space-y-1">
        <input
          value={newName}
          placeholder="name"
          onChange={(e) => setNewName(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && add()}
          className={controlClass({ mono: true, width: 'w-full' })}
        />
        <ExpressionEditor
          value={newValue}
          expected="any"
          placeholder="value or expression"
          onCommit={(t) => setNewValue(t)}
        />
        <div className="flex items-center gap-1">
          <input
            value={newUnit}
            placeholder="unit"
            onChange={(e) => setNewUnit(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && add()}
            className={controlClass({ width: 'w-20' })}
          />
          <button onClick={add} className={inlineButtonClass()}>
            Add
          </button>
        </div>
      </div>
```

- [ ] **Step 2: Verify in the browser**

Open the palette's Constants section. Confirm: row 1 is a full-width `name`, row 2 is the
expression editor with its ƒ button, row 3 is `unit` + `Add`. Type a name, an expression and
a unit, press Add — the constant appears with its unit, and all three inputs clear.

- [ ] **Step 3: Commit**

```bash
git add src/builder/ConstantsPanel.tsx
git commit -m "fix(studio): put Add last in the constants create form"
```

---

### Task 7: Role controls inside the active badge

**Files:**
- Modify: `src/builder/RolesSection.tsx` (`RoleTypeBlock`'s `badge()`, its control cluster,
  the verb-chip row, and `RoleColorPicker`)
- Modify: `webapp/frontend/CLAUDE.md` (record the swatch-trigger exception to the icon rule)

**Interfaces:**
- Consumes: `iconButtonClass` from `src/ui/IconButton.tsx` (already exported; currently used
  by the anchor exception).
- Produces: `RoleColorPicker({ name, type, swatch })` — the added `swatch: string | null`
  prop is the role's assigned swatch class, or null when the role has no colour.

- [ ] **Step 1: Make the colour picker's trigger the swatch**

In `src/builder/RolesSection.tsx`, change `RoleColorPicker`'s signature and its trigger.
Add `iconButtonClass` to the `../ui/IconButton` import, and drop the now-unused
`Palette as PaletteIcon` from the `lucide-react` import.

```tsx
function RoleColorPicker({
  name,
  type,
  swatch,
}: {
  name: string
  type: string
  swatch: string | null
}) {
```

and replace the `<IconButton icon={PaletteIcon} … />` trigger with:

```tsx
      {/* The swatch IS the trigger: a colour control that looks like a colour. It borrows
          `iconButtonClass` for the 24px hit area rather than being 10px of clickable square
          (probe rule `tiny-target`), and carries its own title/aria-label — a colour value is
          not a Lucide icon, so IconButton cannot render it. See frontend/CLAUDE.md. */}
      <button
        type="button"
        title={`Colour for ${name}`}
        aria-label={`Colour for ${name}`}
        onClick={(e) => {
          e.stopPropagation()
          setOpen((v) => !v)
        }}
        className={iconButtonClass()}
      >
        {/* A role with NO colour is a distinct state from one whose colour is auto-assigned
            (roleColorStore.ts: an explicit null override vs. an absent key), so it needs a
            visible target of its own — a hollow ring, not a missing square. SELECTED, not
            appended: only one paint rule is ever emitted. */}
        <span
          aria-hidden
          className={'h-2.5 w-2.5 rounded-sm ' + (swatch ?? 'border border-slate-400')}
        />
      </button>
```

- [ ] **Step 2: Rebuild `badge()` so the active badge carries its own controls**

Replace `RoleTypeBlock`'s `badge` with:

```tsx
  // One badge renderer shared by the top-level and this-group rows. `title` rides the
  // truncating span (not the button) so the ellipsis element carries its own hover text — the
  // probe's truncate-without-title rule checks exactly that. A group param is rendered font-mono
  // to read as the {hole} it is, and never swaps into the rename input (isParam guard).
  const badge = (name: string) => {
    const isParam = paramNames.has(name)
    const active = name === selected
    const focusRing = focusedRole === name ? ' ring-2 ring-amber-400' : ''
    if (editing && active && !isParam) {
      return (
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
      )
    }
    // The ACTIVE badge holds the controls that act on it (#5): rename/delete used to sit in a
    // right-aligned cluster below the row, acting on "whichever badge is selected" with nothing
    // on screen tying the two together. It is a <span>, not a <button>, because a button may not
    // contain buttons — it keeps `badgeClass` so both states are the same 24px box, and the name
    // span inherits the click that used to belong to the whole badge. A group param ({hole}) is
    // authored in the group's Params panel and never gets controls.
    if (active && !isParam) {
      return (
        <span key={name} id={`role-${name}`} className={badgeClass({ active: true }) + focusRing}>
          <RoleColorPicker name={name} type={group.type} swatch={assigned[name] ?? null} />
          <span className="mx-1 min-w-0 truncate" title={name}>
            {name}
          </span>
          <IconButton icon={Pencil} label={`Rename ${name}`} onClick={startRename} />
          <IconButton
            icon={X}
            label={`Delete ${name}`}
            destructive
            onClick={() => {
              const err = removeRole(name)
              setError(err)
              if (err === null) setPicked(null)
            }}
          />
        </span>
      )
    }
    return (
      <button
        key={name}
        id={`role-${name}`}
        onClick={() => {
          setPicked(name)
          setEditing(false)
          setError(null)
        }}
        className={badgeClass({ active }) + focusRing}
      >
        {assigned[name] && (
          <span aria-hidden className={`mr-1 h-2.5 w-2.5 shrink-0 rounded-sm ${assigned[name]}`} />
        )}
        <span className={'min-w-0 truncate' + (isParam ? ' font-mono' : '')} title={name}>
          {name}
        </span>
      </button>
    )
  }
```

- [ ] **Step 3: Delete the detached control cluster**

In `RoleTypeBlock`'s badge row, remove the entire block that starts with the
`{/* rename/delete/colour act on `selected` … */}` comment and renders
`{group.roles.length > 0 && !selectedIsParam && (<span className="ml-auto …">…</span>)}`.
The row becomes:

```tsx
      <div className="mb-1 flex flex-wrap items-center gap-1">
        {topRoles.map((name) => badge(name))}
        <AddRoleForm type={group.type} onAdded={setPicked} />
      </div>
```

`selectedIsParam` is now unreferenced — delete its `const` and the comment above it.

- [ ] **Step 4: Add the hairline above the verb chips**

```tsx
      {selected !== null && verbs !== null && (
        // The roles a type has and the verbs you can drag from it are two different kinds of
        // thing stacked in one card (#6). The verb row only renders when a role is SELECTED,
        // and a selection implies the type has roles, so "if any roles exist" and "this row is
        // rendering" are the same condition — no extra guard.
        <div className="flex flex-wrap gap-1 border-t border-slate-200 pt-1.5">
```

- [ ] **Step 5: Record the swatch-trigger exception**

In `webapp/frontend/CLAUDE.md`, under `## Icons`, after the "Anchor exception" bullet:

```markdown
- Value exception: a control whose affordance IS a value rather than an icon (the Roles
  section's colour swatch, which opens the colour menu) uses `iconButtonClass()` from
  src/ui/IconButton.tsx to get the same 24px hit area and focus ring, plus explicit `title`
  and `aria-label`. It renders the value, not a Lucide glyph — this is not a licence for
  raw glyph buttons, which stay banned.
```

- [ ] **Step 6: Typecheck, lint, test**

Run: `npm run typecheck && npm run lint && npm test`
Expected: clean. A leftover `PaletteIcon` or `selectedIsParam` import/binding fails lint —
that is the check that Steps 1 and 3 were completed.

- [ ] **Step 7: Verify in the browser**

1. Click a role badge: it grows to hold `[swatch] name ✎ ✕`; no cluster below the row.
2. Click the swatch: the colour popover opens. Pick "no colour": the swatch becomes a
   hollow ring and still opens the popover.
3. Click ✎: the badge swaps to the rename input. Esc cancels, Enter commits.
4. Click ✕: the role is deleted, or an error appears under the row.
5. A device type with roles shows a hairline above its verb chips; one with no roles shows
   no chips and no hairline.
6. Inside a group scope, a `{param}` badge still shows no controls.

- [ ] **Step 8: Commit**

```bash
git add src/builder/RolesSection.tsx webapp/frontend/CLAUDE.md
git commit -m "fix(studio): move role controls into the active badge"
```

---

### Task 8: Cap the stream name's width

**Files:**
- Modify: `src/builder/StreamsPanel.tsx`

**Interfaces:**
- Consumes: `inlineButtonClass({ shrinkable: true })` from Task 2.

- [ ] **Step 1: Make the name button shrinkable and truncating**

In `src/builder/StreamsPanel.tsx`, replace the rename trigger button:

```tsx
              <button
                title="Rename stream"
                onClick={() => {
                  setEditing(name)
                  setDraft(name)
                  setError(null)
                  cancelled.current = false
                }}
                // Sizing to content let one long name push the 256px palette into horizontal
                // scroll (#7 — measured 254 -> 437px scrollWidth). Both inputs in this panel
                // were already capped at w-24; the display button was not. Capping the input's
                // maxLength instead would not help: names arrive from imported docs too, so it
                // is the RENDER that has to be bounded.
                className={inlineButtonClass({ shrinkable: true })}
              >
                <span className="min-w-0 truncate" title={name}>
                  {name}
                </span>
              </button>
```

- [ ] **Step 2: Verify the measurement**

With the dev server running, open the palette's Streams section and add a stream named
`optical_density_channel_three_normalised_long`. In the DevTools console:

```js
const a = document.querySelector('aside'); ({ client: a.clientWidth, scroll: a.scrollWidth })
```

Expected: `scroll === client` (254 = 254). Before this change it was 437 vs 254. The name
must ellipsize with its full text on hover.

- [ ] **Step 3: Commit**

```bash
git add src/builder/StreamsPanel.tsx
git commit -m "fix(studio): stop a long stream name widening the palette"
```

---

### Task 9: Demo fixture and capture state

**Files:**
- Create: `webapp/fixtures/ui-improvements-6.json`
- Modify: `webapp/frontend/tools/capture.mjs`

**Interfaces:**
- Consumes: nothing from earlier tasks. Produces a capture state named `ui-improvements-6`.

- [ ] **Step 1: Write the fixture**

Create `webapp/fixtures/ui-improvements-6.json`. Schema notes confirmed against the running
backend: empty `serial` children, an empty `loop` body and `else: []` all validate; **a
literal `"else": null` is rejected** ("branch.else must be a list") — the Studio's "no else
arm" state is expressed by *omitting* the key.

```json
{
  "doc_version": 1,
  "name": "UI improvements 6 — lane geometry",
  "description": "Boundary fixture for the chip band (design 2026-07-25). Every construct that has to fill the band a lane's cards occupy appears here at least once, beside a sibling that actually holds cards, so an empty band can be compared against a populated one. Also carries the palette's overflow cases: a long stream name, a long role name, a device type with no roles, and constants with and without units.",
  "workflow": {
    "schema_version": 3,
    "metadata": { "author": "ui-improvements-6", "description": "lane geometry" },
    "constants": {
      "SETTLE_S": { "value": 5 },
      "MAX_TEMP": { "value": 37.0, "as": "celsius" }
    },
    "roles": {
      "od_a": { "type": "densitometer" },
      "od_b": { "type": "densitometer" },
      "pump_a": { "type": "pump" },
      "role_with_a_deliberately_overlong_name_for_badge_truncation": { "type": "pump" }
    },
    "streams": {
      "od_1": { "units": "AU" },
      "optical_density_channel_three_normalised_long": { "units": "AU" }
    },
    "blocks": [
      {
        "parallel": {
          "children": [
            {
              "serial": { "children": [{ "alarm": { "if": "true", "message": "one chip lane" } }] },
              "label": "one chip"
            },
            { "serial": { "children": [] }, "label": "empty lane" },
            {
              "serial": {
                "children": [
                  { "measure": { "device": "od_a", "verb": "measure", "into": "od_1" } },
                  { "command": { "device": "pump_a", "verb": "dispense", "params": { "volume_ml": 1.0 } } },
                  {
                    "parallel": {
                      "children": [
                        { "serial": { "children": [{ "command": { "device": "pump_a", "verb": "stop", "params": {} } }] } },
                        { "serial": { "children": [] } }
                      ]
                    },
                    "label": "nested: the band must work at depth"
                  },
                  { "wait": { "duration": "5s" } }
                ]
              },
              "label": "tall lane"
            }
          ]
        },
        "label": "one chip | empty | tall"
      },
      {
        "branch": {
          "if": "true",
          "then": [
            { "measure": { "device": "od_b", "verb": "measure", "into": "od_1" } },
            { "command": { "device": "pump_a", "verb": "rotate", "params": { "direction": "forward", "speed_ml_min": 1.0 } } }
          ]
        },
        "label": "else absent: the \"+ add else\" band"
      },
      {
        "branch": {
          "if": "true",
          "then": [{ "abort": { "if": "false", "message": "never" } }],
          "else": []
        },
        "label": "else empty: the else-arm hint band"
      },
      { "loop": { "count": 2, "body": [] }, "label": "empty body: a band with no sibling to stretch to" },
      { "operator_input": { "name": "confirm_ready", "type": "bool", "prompt": "Ready?" } },
      { "compute": { "into": "planned_ml", "value": "SETTLE_S * 2" } },
      { "record": { "into": "optical_density_channel_three_normalised_long", "value": "planned_ml" } }
    ]
  }
}
```

- [ ] **Step 2: Verify the fixture validates**

With the backend running:

```bash
curl -s -X POST http://127.0.0.1:8000/api/validate -H 'content-type: application/json' \
  -d @webapp/fixtures/ui-improvements-6.json
```

Expected: `{"ok":true,"diagnostics":[], ...}`. If a verb's params are wrong the response
names the block path and the missing/unknown param — fix and re-run until clean. Do not
move on with a red fixture: a doc that fails validation still renders, so the capture would
pass while the fixture silently means something else.

- [ ] **Step 3: Add the capture state**

In `webapp/frontend/tools/capture.mjs`, add to `FIXTURES`:

```js
  uiSix: path.join(repoRoot, 'webapp/fixtures/ui-improvements-6.json'),
```

and append to `states`:

```js
  {
    name: 'ui-improvements-6',
    description:
      'the chip-band fixture: a parallel whose lanes are 1 chip / empty / tall-with-a-nested-' +
      'parallel, a branch with no else arm, a branch with an empty else arm, and an empty loop ' +
      'body — every filler that has to span the band a lane\'s cards occupy, each beside a ' +
      'sibling that actually holds cards. The Roles and Streams sections are opened and a role ' +
      'selected so the rebuilt badge (swatch trigger + rename/delete inside the active badge) ' +
      'and the capped stream name actually mount: R4 cannot report on a row that never renders.',
    setup: async (page) => {
      await gotoBuilder(page)
      await importDoc(page, FIXTURES.uiSix)
      await page.getByRole('button', { name: 'Streams', exact: true }).click()
      await page.locator('[id="role-od_a"]').click()
      await page.waitForTimeout(200)
      // Assert the state actually mounted, or this is a vacuous clean pass.
      if ((await page.getByRole('button', { name: 'Colour for od_a' }).count()) !== 1) {
        throw new Error('the active role badge did not mount its swatch trigger')
      }
    },
  },
```

- [ ] **Step 4: Run the capture**

```bash
cd /Users/khamit/lab-devices-ui6/webapp/frontend
npm run build
node tools/capture.mjs --out /tmp/ui6-after
```

Expected: PNGs for every state × viewport × theme, plus `probe.json`. Open
`/tmp/ui6-after/probe.json` and confirm the `ui-improvements-6` state's violations array
is empty for R2 (`truncate-without-title`), R3 (`tiny-target`) and R4
(`sibling-height-mismatch`).

- [ ] **Step 5: Commit**

```bash
git add webapp/fixtures/ui-improvements-6.json webapp/frontend/tools/capture.mjs
git commit -m "test(studio): chip-band demo fixture and capture state"
```

---

### Task 10: Full verification sweep and PR

**Files:** none modified (a fix here goes back into the task that owns it).

- [ ] **Step 1: Run every frontend gate**

```bash
cd /Users/khamit/lab-devices-ui6/webapp/frontend
npm run lint && npm test && npm run build
```

Expected: all clean. Do not proceed on a red gate.

- [ ] **Step 2: Capture both themes and read every rule**

```bash
node tools/capture.mjs --out /tmp/ui6-after --theme both
```

Read `/tmp/ui6-after/probe.json` in full. R5 (`text-contrast`) and R6
(`control-wrapper-gap`) must be **unchanged** from before this branch — nothing here
touches paint or textarea metrics, so a new hit in either means something went wrong.
R1 (`clipped-overflow`) must not gain a hit from the shrinkable stream button.

- [ ] **Step 3: Capture the "before" for comparison**

```bash
cd /Users/khamit/lab-devices  # the primary checkout, still on main
# with its own dev server on :5173 and the fixture copied in from the branch
node webapp/frontend/tools/capture.mjs --out /tmp/ui6-before
```

Note in the PR body which states moved and why. Every leaf card's left edge shifts 24px
this round (Task 3) — expected, not a regression.

- [ ] **Step 4: Push and open the PR**

```bash
cd /Users/khamit/lab-devices-ui6
git push -u origin fix/ui-improvements-6
gh pr create --title "fix(studio): UI improvements 6 — chip band, role badge controls, palette overflow" --body "..."
```

The body states each of the seven defects, the measurement that proved it, and the fix.

- [ ] **Step 5: Wait for CI, then merge**

```bash
gh pr checks --watch
gh pr merge --squash
```

---

## Self-review

**Spec coverage.** Spec §3.2 tokens → Task 1. §3.3 stretch chain → Task 4 steps 3-5. §3.4
hint → Task 4 step 2. §3.5 `+ lane` / `+ add else` → Task 5. §3.6 leaf spacer → Task 3.
§4.1 constants → Task 6. §4.2 role badge → Task 7 steps 1-3. §4.3 hairline → Task 7 step 4.
§4.4 stream width → Tasks 2 and 8. §5 fixture → Task 9. §6 verification → Task 10.
§7 risk 1 (`min-h-8.5`) → resolved before the plan, recorded in Global Constraints.

**Type consistency.** `RoleColorPicker` gains `swatch: string | null` in Task 7 step 1 and
is called with `swatch={assigned[name] ?? null}` in step 2 — `assigned` is
`Record<string, string>`, so the `?? null` is what makes the types meet. `ChipBand` is
declared with `{ children: ReactNode; className?: string }` in Task 5 step 1 and called
both ways (bare, and with `className="mr-2"`) in step 2. `inlineButtonClass`'s new
`shrinkable` is added in Task 2 and consumed only in Task 8.

**Ordering.** Tasks 1 and 2 are pure and must land first (4, 5 and 8 import from them).
3-5 all touch `Canvas.tsx` and must run in order. 6, 7, 8 are independent of each other.
9 depends on nothing but is most useful after 5. 10 is last.
