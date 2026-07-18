# Canvas Visual Language (W14) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make deeply-nested experiment workflows readable at a glance by encoding construct identity, nesting depth, device role, and "stands for something absent" on four channels that do not compete with the existing state palette.

**Architecture:** Four pure modules (`constructTint.ts`, `roleColors.ts`, `roleColorStorage.ts`, and new exports in `summary.ts`) hold every decision; `Canvas.tsx` and the Palette's roles section consume them. Hue stays reserved for state (blue/red/amber/emerald) — construct identity rides on container border + header fill, depth on a neutral interior zebra, role on a saturated swatch, absence on a CSS hatch.

**Tech Stack:** React 19.2, Vite 8, Tailwind 4, Zustand + zundo, vitest 4 (node env), oxlint, lucide-react.

**Spec:** `docs/superpowers/specs/2026-07-18-canvas-visual-language-design.md`

## Global Constraints

- **Tailwind class names must appear as complete literal strings in source.** Tailwind 4 scans source text; `` `bg-${color}` `` produces no CSS. Every colour class in the ramp and the tint maps is written out in full.
- **A class baked into a helper is un-overridable by concatenation, for every property.** Helpers must *select* exactly one class per property and return it. Never `helperClass() + ' border-blue-500'`. This trap has shipped twice: W11 on `width`, W12 on `text` colour (`IconButton`'s appended `text-blue-700` lost silently to a baked-in `text-slate-500` — equal specificity, same `@layer utilities`, slate sorts later).
- **vitest runs in node env.** Pure functions only — no component rendering, no jsdom, no `@testing-library`, no `localStorage`. DOM truth is verified by the probe harness (`npm run capture`).
- **Tests are colocated**: `src/builder/foo.ts` → `src/builder/foo.test.ts`.
- **tsconfig is strict with `erasableSyntaxOnly` and `verbatimModuleSyntax`** — type-only imports must use `import type`.
- **No document-format change.** `docToTree`/`treeToDoc` are untouched; open+save stays a byte no-op (W9-settled).
- **Text colour rules** (`webapp/frontend/CLAUDE.md`): meaning-carrying secondary text is `text-caption` (slate-600); `text-hint` (slate-500) is incidental only and measures under 4.5:1 on tinted canvas.
- **Icons stay lucide-only**; `∀`, `R×N`, `⤳`, `×N`, `●` remain typographic.
- **Every commit message ends with:**
  ```
  Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01Sja96BZrnZvKJUKU11cw3e
  ```
- **Gate before PR:** `cd webapp/frontend && npm run lint && npm run typecheck && npm test -- --run && npm run build`.

---

### Task 1: Construct tint and depth tokens (pure)

**Files:**
- Create: `webapp/frontend/src/builder/constructTint.ts`
- Test: `webapp/frontend/src/builder/constructTint.test.ts`

**Interfaces:**
- Consumes: `FlowKind`, `BlockNode` from `./tree`.
- Produces: `isFlowKind(kind: BlockNode['kind']): kind is FlowKind`; `cardBorderClass(opts: { kind: BlockNode['kind']; selected: boolean }): string`; `headerFillClass(kind: BlockNode['kind']): string`; `interiorFillClass(depth: number): string`; `CONSTRUCT_CHROME`.

- [ ] **Step 1: Write the failing test**

Create `webapp/frontend/src/builder/constructTint.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import {
  CONSTRUCT_CHROME,
  cardBorderClass,
  headerFillClass,
  interiorFillClass,
  isFlowKind,
} from './constructTint'
import type { FlowKind } from './tree'

describe('isFlowKind', () => {
  it('accepts exactly the five container kinds', () => {
    for (const k of ['serial', 'parallel', 'branch', 'loop', 'for_each'] as const) {
      expect(isFlowKind(k)).toBe(true)
    }
    for (const k of ['command', 'measure', 'wait', 'operator_input', 'compute',
                     'record', 'abort', 'alarm', 'group_ref'] as const) {
      expect(isFlowKind(k)).toBe(false)
    }
  })
})

describe('CONSTRUCT_CHROME', () => {
  // Loop and for_each were byte-identical before this increment; they are the pair
  // most confused at depth, so their hues must be maximally distant, not merely distinct.
  it('gives every construct a distinct border and header', () => {
    const borders = Object.values(CONSTRUCT_CHROME).map((c) => c.border)
    const headers = Object.values(CONSTRUCT_CHROME).map((c) => c.header)
    expect(new Set(borders).size).toBe(5)
    expect(new Set(headers).size).toBe(5)
  })

  // Reserved-hue exclusion (spec §2.1): blue=selection, red=error, amber=warning,
  // emerald=valid. A tint drawn from those families would collide with state.
  it('avoids every reserved state hue', () => {
    const reserved = ['blue', 'indigo', 'sky', 'red', 'rose', 'amber', 'orange',
                      'yellow', 'emerald', 'green']
    for (const { border, header } of Object.values(CONSTRUCT_CHROME)) {
      for (const family of reserved) {
        expect(border).not.toContain(`-${family}-`)
        expect(header).not.toContain(`-${family}-`)
      }
    }
  })
})

describe('cardBorderClass', () => {
  it('emits exactly one border class', () => {
    const cls = cardBorderClass({ kind: 'loop', selected: false })
    expect(cls.split(/\s+/).filter((c) => c.startsWith('border-'))).toHaveLength(1)
  })

  it('gives leaves the neutral card border', () => {
    expect(cardBorderClass({ kind: 'command', selected: false })).toBe('border-slate-300')
  })

  it('gives containers their construct border', () => {
    expect(cardBorderClass({ kind: 'loop', selected: false })).toBe('border-fuchsia-200')
    expect(cardBorderClass({ kind: 'for_each', selected: false })).toBe('border-lime-200')
  })

  // Selection must SELECT the blue border, not append it: an appended class would be an
  // equal-specificity sibling of the construct border and the cascade would decide by
  // stylesheet order, not by intent (W12's text-colour trap, generalised).
  it('selection replaces the construct border for every kind', () => {
    for (const k of ['serial', 'parallel', 'branch', 'loop', 'for_each', 'command'] as const) {
      expect(cardBorderClass({ kind: k, selected: true })).toBe('border-blue-500')
    }
  })
})

describe('headerFillClass', () => {
  it('tints container headers and leaves leaves untinted', () => {
    expect(headerFillClass('branch')).toBe('bg-violet-50')
    expect(headerFillClass('command')).toBe('')
  })
})

describe('interiorFillClass', () => {
  // The ramp excludes bg-white on purpose: leaf cards are white, so a white interior
  // would leave a card visible only by its 1px border at every other level.
  it('alternates between the two slate steps and never emits white', () => {
    expect(interiorFillClass(1)).toBe('bg-slate-50')
    expect(interiorFillClass(2)).toBe('bg-slate-100')
    expect(interiorFillClass(3)).toBe('bg-slate-50')
    expect(interiorFillClass(4)).toBe('bg-slate-100')
    for (let d = 1; d <= 12; d++) expect(interiorFillClass(d)).not.toBe('bg-white')
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd webapp/frontend && npm test -- --run src/builder/constructTint.test.ts`
Expected: FAIL — `Failed to resolve import "./constructTint"`.

- [ ] **Step 3: Write the implementation**

Create `webapp/frontend/src/builder/constructTint.ts`:

```ts
/** Construct identity, nesting depth, and how they stay out of the state palette's way
 * (design 2026-07-18-canvas-visual-language §3.1, §3.2).
 *
 * Every colour reaching the canvas before this module meant STATE, never identity: blue is
 * selection and legal drop target, red is error and illegal drop, amber is warning, emerald
 * is valid. A Scratch-style hue-per-family scheme would therefore put category colour in
 * direct competition with error colour — a red-tinted Safety block beside a red-bordered
 * broken block is a canvas that can no longer say *something is wrong here*. So hue stays
 * reserved for state, and construct identity rides on the container card's ALREADY EXISTING
 * border and header row. Nothing new is drawn; an existing stroke is recoloured.
 *
 * Every class below is written out in full. Tailwind 4 scans source text, so an interpolated
 * `bg-${family}-50` would compile to no CSS at all.
 */
import type { BlockNode, FlowKind } from './tree'

/** Keyed by FlowKind, so adding a sixth container kind to tree.ts fails to compile here
 * rather than rendering it as an untinted lookalike of `serial`. */
export const CONSTRUCT_CHROME: Record<FlowKind, { border: string; header: string }> = {
  // Sequential is the baseline construct and gets the quietest treatment — a tint on the
  // most common container would be noise, not signal.
  serial: { border: 'border-slate-300', header: 'bg-slate-50' },
  parallel: { border: 'border-teal-200', header: 'bg-teal-50' },
  branch: { border: 'border-violet-200', header: 'bg-violet-50' },
  // loop and for_each carried BYTE-IDENTICAL container classes before this increment
  // ('ml-2 border-l-2 border-slate-200 px-2 pb-2' for both), so they are the pair a reader
  // most often confuses. Their hues are deliberately the furthest apart in this map.
  loop: { border: 'border-fuchsia-200', header: 'bg-fuchsia-50' },
  for_each: { border: 'border-lime-200', header: 'bg-lime-50' },
}

const NEUTRAL_BORDER = 'border-slate-300'
const SELECTED_BORDER = 'border-blue-500'

export function isFlowKind(kind: BlockNode['kind']): kind is FlowKind {
  return kind in CONSTRUCT_CHROME
}

/** The card's single border class.
 *
 * Selection SELECTS rather than appends. `border-blue-500` and `border-fuchsia-200` are
 * equal-specificity utilities in the same `@layer utilities` block, so appending would let
 * the compiled stylesheet's declaration order decide which wins — the exact defect that
 * shipped in W12, where an appended `text-blue-700` lost to a baked-in `text-slate-500` and
 * the active-scope highlight never rendered while looking perfect in source. Returning one
 * class means there is no cascade fight to lose, which is strictly stronger than winning it.
 */
export function cardBorderClass(opts: {
  kind: BlockNode['kind']
  selected: boolean
}): string {
  if (opts.selected) return SELECTED_BORDER
  return isFlowKind(opts.kind) ? CONSTRUCT_CHROME[opts.kind].border : NEUTRAL_BORDER
}

/** Header-row fill for containers; empty string for leaves, which stay `bg-white`. */
export function headerFillClass(kind: BlockNode['kind']): string {
  return isFlowKind(kind) ? CONSTRUCT_CHROME[kind].header : ''
}

/** Container interior fill, alternating by depth parity. The outermost container's
 * interior is depth 1.
 *
 * Parity, not a monotone ramp: a ramp runs out of usable range in four levels, and nesting
 * here routinely goes deeper. `bg-white` is deliberately NOT in the rotation — leaf cards
 * are white, so a white interior would leave a card distinguishable only by its 1px border
 * at every other level. `bg-slate-100` matching the canvas backdrop is harmless: the canvas
 * is depth 0 and can never be adjacent to a depth-2 interior.
 */
export function interiorFillClass(depth: number): string {
  return depth % 2 === 1 ? 'bg-slate-50' : 'bg-slate-100'
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd webapp/frontend && npm test -- --run src/builder/constructTint.test.ts`
Expected: PASS, 9 tests.

- [ ] **Step 5: Commit**

```bash
git add webapp/frontend/src/builder/constructTint.ts webapp/frontend/src/builder/constructTint.test.ts
git commit -m "$(cat <<'EOF'
feat(studio): construct tint and depth tokens

Pure module holding construct-keyed container chrome and the depth
zebra. Hues avoid blue/red/amber/green so construct identity never
competes with the state palette.

cardBorderClass selects one border class rather than appending, so
selection cannot lose a cascade fight to a construct tint.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Sja96BZrnZvKJUKU11cw3e
EOF
)"
```

---

### Task 2: Wire construct tints and the depth zebra into the canvas

**Files:**
- Modify: `webapp/frontend/src/builder/Canvas.tsx` (`BlockView` 179-277, `ContainerBody` 279-310, `BranchLanes` 448-521)

**Interfaces:**
- Consumes: `cardBorderClass`, `headerFillClass`, `interiorFillClass`, `isFlowKind` from Task 1.
- Produces: `DepthContext` (module-private) — every container body provides `depth + 1`.

- [ ] **Step 1: Add the depth context and import the tokens**

In `webapp/frontend/src/builder/Canvas.tsx`, add to the import block:

```tsx
import {
  cardBorderClass,
  headerFillClass,
  interiorFillClass,
  isFlowKind,
} from './constructTint'
```

Directly below the existing `DiagContext` declaration (line 16), add:

```tsx
/** Nesting depth of the list currently being rendered. 0 is the canvas backdrop; the
 * outermost container's interior is 1. Only ContainerBody and BranchLanes provide it —
 * BlockList is depth-transparent, so a container's own card sits at its PARENT's depth
 * and only its interior descends. */
const DepthContext = createContext(0)
```

- [ ] **Step 2: Replace BlockView's card and header classes**

In `BlockView`, replace the `isContainer` derivation (lines 191-192) with:

```tsx
  const isContainer = isFlowKind(node.kind)
```

Replace the card `className` expression (lines 201-209) with:

```tsx
      className={
        // min-w-0: a card that sits in a flex lane/branch-arm must be able to shrink to its
        // container instead of forcing it wide (flex min-width:auto is the classic culprit
        // behind a card painting past its box — audit F11). The lane/arm containers no longer
        // clip (the Canvas is the single scroller), so this is what keeps a card honest.
        //
        // The border comes from cardBorderClass, which SELECTS exactly one class: containers
        // wear their construct tint, leaves stay slate-300, and selection replaces both. The
        // selection ring is `ring-2` rather than W13's `ring-1` because a canvas of tinted
        // borders makes a 1px ring too easy to lose — the ring, not the border, is now the
        // load-bearing selection cue.
        'min-w-0 rounded border bg-white text-sm shadow-sm ' +
        cardBorderClass({ kind: node.kind, selected }) + ' ' +
        (selected ? 'ring-2 ring-blue-400 ' : '') +
        (isDragging ? 'opacity-40' : '')
      }
```

Replace the header row `className` (line 214) with:

```tsx
        className={
          'flex min-w-0 cursor-grab items-center gap-1 rounded-t px-2 py-1 ' +
          headerFillClass(node.kind)
        }
```

- [ ] **Step 3: Replace ContainerBody with depth-aware, uniformly-boxed bodies**

Replace the whole of `ContainerBody` (lines 279-310) with:

```tsx
/** A container's interior. Every construct now gets the same treatment — a depth-keyed
 * neutral fill on the region that used to be pure padding — so containment reads as filled
 * AREAS rather than as strokes you have to count.
 *
 * The `ml-2 border-l-2 border-slate-200` rule that loop and for_each carried before this
 * increment is gone. It was a second vertical line drawn 8px inside the card border that was
 * already there: a stroke without a fact. Both constructs are now told apart by their border
 * and header hue instead (constructTint.ts), which is why they no longer need to be — and no
 * longer are — byte-identical. */
function ContainerBody({ node }: { node: BlockNode }) {
  const depth = useContext(DepthContext) + 1
  const fill = interiorFillClass(depth)
  const body = (() => {
    switch (node.kind) {
      case 'serial':
        return <BlockList parentUid={node.uid} slot="children" items={node.children} />
      case 'parallel':
        return <ParallelLanes node={node} />
      case 'loop':
        return <BlockList parentUid={node.uid} slot="body" items={node.body} />
      case 'for_each':
        return <BlockList parentUid={node.uid} slot="body" items={node.body} />
      case 'branch':
        return <BranchLanes node={node} />
      default:
        return null
    }
  })()
  if (body === null) return null
  return (
    <DepthContext.Provider value={depth}>
      <div className={`rounded-b px-2 pb-2 ${fill}`}>{body}</div>
    </DepthContext.Provider>
  )
}
```

- [ ] **Step 4: Give branch arms a real box**

`branch` arms have had no container at all — no border, no background, just a 10px uppercase caption and an 8px gap. In `BranchLanes`, replace the outer row and both arm wrappers. Replace line 470 (`<div className="flex gap-2 px-2 pb-2">`) with:

```tsx
    <div className="flex gap-2">
```

(The padding and fill now come from `ContainerBody`'s wrapper, so this row must not add its own.)

Replace the THEN arm wrapper (line 471) with:

```tsx
      <div className="min-w-48 flex-initial rounded border border-violet-200 px-1 pb-1">
```

Replace the ELSE arm wrapper (line 475) with:

```tsx
      <div className="min-w-48 flex-initial rounded border border-violet-200 px-1 pb-1">
```

Leave every existing comment in `BranchLanes` in place — the `flex-initial` block documents a measured regression (an empty ELSE arm claiming 427px to hold an 80px button) that no committed fixture can catch, and it must survive this edit.

- [ ] **Step 5: Strip the now-duplicated padding from ParallelLanes' caller**

`ContainerBody` already supplies `px-2 pb-2`, so no change is needed inside `ParallelLanes` itself. Verify by reading `ParallelLanes` (line 312) that its root is `<div className="flex items-stretch">` with no padding of its own. If it has any, leave it — `items-stretch` governs lane height and is unrelated.

- [ ] **Step 6: Typecheck, lint, and run the suite**

Run: `cd webapp/frontend && npm run typecheck && npm run lint && npm test -- --run`
Expected: typecheck clean; lint exits 0 (2 known fast-refresh warnings are pre-existing); all tests pass.

- [ ] **Step 7: Verify in a real browser against both fixtures**

Run: `cd webapp/frontend && npm run capture`
Expected: capture completes; screenshots written. Then open the torture fixture and confirm by eye at 1440px:
- a `loop` and a `for_each` at the same depth are now visibly different;
- branch THEN/ELSE arms have visible boxes;
- nesting alternates slate-50 / slate-100 with white cards contrasting at every level.

**If the probe reports new contrast violations on the tinted headers, do not proceed** — report the measured ratios. Five new tinted surfaces each need re-checking; `text-hint` already measures under 4.5:1 on `bg-slate-100`.

- [ ] **Step 8: Commit**

```bash
git add webapp/frontend/src/builder/Canvas.tsx
git commit -m "$(cat <<'EOF'
feat(studio): tint containers by construct, shade interiors by depth

Container cards take their construct's border and header hue; the
interior region that was pure padding takes a depth-keyed neutral fill,
so containment reads as filled areas instead of counted strokes.

Drops loop/for_each's shared 'ml-2 border-l-2' rule: it drew a second
vertical line inside the card border that was already there. The two
constructs are now told apart by hue instead of being byte-identical.

Branch arms get a real box for the first time. Selection moves to ring-2
so it still wins against a canvas of tinted borders.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Sja96BZrnZvKJUKU11cw3e
EOF
)"
```

---

### Task 3: Role colour ramp and assignment (pure)

**Files:**
- Create: `webapp/frontend/src/builder/roleColors.ts`
- Test: `webapp/frontend/src/builder/roleColors.test.ts`

**Interfaces:**
- Produces: `ROLE_SWATCH_CLASSES` (readonly 8-tuple of full `bg-*` class strings); `roleColorKey(name: string, type: string): string`; `assignRoleColors(roles: Record<string, { type: string }>, overrides: Record<string, string | null>): Record<string, string | null>`.

- [ ] **Step 1: Write the failing test**

Create `webapp/frontend/src/builder/roleColors.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import { ROLE_SWATCH_CLASSES, assignRoleColors, roleColorKey } from './roleColors'

const roles = (...entries: [string, string][]) =>
  Object.fromEntries(entries.map(([name, type]) => [name, { type }]))

describe('ROLE_SWATCH_CLASSES', () => {
  it('is eight distinct, fully-written-out background classes', () => {
    expect(ROLE_SWATCH_CLASSES).toHaveLength(8)
    expect(new Set(ROLE_SWATCH_CLASSES).size).toBe(8)
    // Tailwind 4 scans source text: an interpolated class compiles to no CSS at all.
    for (const c of ROLE_SWATCH_CLASSES) expect(c).toMatch(/^bg-[a-z]+-\d{3}$/)
  })

  it('avoids every reserved state hue', () => {
    const reserved = ['blue', 'indigo', 'sky', 'red', 'rose', 'amber', 'orange',
                      'yellow', 'emerald', 'green']
    for (const c of ROLE_SWATCH_CLASSES) {
      for (const family of reserved) expect(c).not.toContain(`-${family}-`)
    }
  })
})

describe('roleColorKey', () => {
  it('keys on type and name together', () => {
    expect(roleColorKey('pump1', 'pump')).toBe('pump:pump1')
  })

  it('separates same-named roles of different types', () => {
    expect(roleColorKey('x', 'pump')).not.toBe(roleColorKey('x', 'sensor'))
  })
})

describe('assignRoleColors', () => {
  it('assigns from the ramp in declaration order', () => {
    const got = assignRoleColors(roles(['a', 'pump'], ['b', 'pump'], ['c', 'sensor']), {})
    expect(got).toEqual({
      a: ROLE_SWATCH_CLASSES[0],
      b: ROLE_SWATCH_CLASSES[1],
      c: ROLE_SWATCH_CLASSES[2],
    })
  })

  it('wraps to the start of the ramp past the eighth role', () => {
    const nine: [string, string][] = Array.from({ length: 9 }, (_, i) => [`r${i}`, 'pump'])
    const got = assignRoleColors(roles(...nine), {})
    expect(got.r8).toBe(ROLE_SWATCH_CLASSES[0])
  })

  it('lets an override replace the auto-assigned colour', () => {
    const got = assignRoleColors(roles(['a', 'pump']), {
      'pump:a': ROLE_SWATCH_CLASSES[5],
    })
    expect(got.a).toBe(ROLE_SWATCH_CLASSES[5])
  })

  // A null override is "the user removed this role's colour" and must render as today's
  // plain white card — it is NOT the same as having no entry, which means "never touched".
  it('treats a null override as explicitly colourless', () => {
    const got = assignRoleColors(roles(['a', 'pump'], ['b', 'pump']), { 'pump:a': null })
    expect(got.a).toBeNull()
    expect(got.b).toBe(ROLE_SWATCH_CLASSES[1])
  })

  // Auto-assignment is positional, so clearing one role must not renumber the others.
  it('does not shift other roles when one is cleared', () => {
    const all = assignRoleColors(roles(['a', 'pump'], ['b', 'pump'], ['c', 'pump']), {})
    const cleared = assignRoleColors(
      roles(['a', 'pump'], ['b', 'pump'], ['c', 'pump']),
      { 'pump:b': null },
    )
    expect(cleared.a).toBe(all.a)
    expect(cleared.c).toBe(all.c)
  })

  it('ignores overrides whose role no longer exists', () => {
    const got = assignRoleColors(roles(['a', 'pump']), { 'pump:gone': ROLE_SWATCH_CLASSES[3] })
    expect(got).toEqual({ a: ROLE_SWATCH_CLASSES[0] })
  })

  it('returns an empty map for an empty roles record', () => {
    expect(assignRoleColors({}, {})).toEqual({})
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd webapp/frontend && npm test -- --run src/builder/roleColors.test.ts`
Expected: FAIL — `Failed to resolve import "./roleColors"`.

- [ ] **Step 3: Write the implementation**

Create `webapp/frontend/src/builder/roleColors.ts`:

```ts
/** Per-role swatch colours (design 2026-07-18-canvas-visual-language §3.3).
 *
 * User-settled 2026-07-18: colours are auto-assigned from a fixed ramp in role-declaration
 * order, every command and measure of a role shares its colour, the assignment persists
 * keyed by role type + name, and the user may edit a colour or remove it entirely (a role
 * with no colour renders exactly as cards did before this increment — plain white).
 *
 * Swatches sit at full -500/-600 saturation against the construct tints' pale -50/-200
 * (constructTint.ts). That saturation gap is what keeps the two systems legible as separate
 * languages rather than one muddle, and a small solid swatch reads conventionally as a
 * LEGEND KEY rather than a status — which is what keeps it from competing with the
 * border-and-background state palette.
 */

/** Written out in full: Tailwind 4 scans source text, so `bg-${family}-500` yields no CSS.
 *
 * Same reserved-hue exclusion as the construct tints — no blue/indigo/sky (selection), no
 * red/rose (error), no amber/orange/yellow (warning), no emerald/green (valid). `lime` and
 * `cyan` take the -600 step because their -500 steps are too light to read as a solid key
 * at swatch size. */
export const ROLE_SWATCH_CLASSES = [
  'bg-teal-500',
  'bg-violet-500',
  'bg-fuchsia-500',
  'bg-lime-600',
  'bg-cyan-600',
  'bg-purple-500',
  'bg-pink-500',
  'bg-stone-500',
] as const

export type RoleSwatchClass = (typeof ROLE_SWATCH_CLASSES)[number]

/** Persistence key. Type is part of it so `pump:x` and `sensor:x` are different roles —
 * a bare name would let a rename-and-retype silently inherit the old colour. */
export function roleColorKey(name: string, type: string): string {
  return `${type}:${name}`
}

/** Resolve every declared role to a swatch class, or to null for "no colour".
 *
 * Auto-assignment is POSITIONAL — index into the ramp by declaration order — so clearing
 * one role's colour must not renumber its neighbours. That is why an override is applied
 * over the positional result rather than removing the role from the numbering.
 *
 * `overrides` distinguishes three states: a class means the user picked it, an explicit
 * `null` means the user removed the colour, and an absent key means untouched (auto).
 */
export function assignRoleColors(
  roles: Record<string, { type: string }>,
  overrides: Record<string, string | null>,
): Record<string, string | null> {
  const out: Record<string, string | null> = {}
  Object.entries(roles).forEach(([name, { type }], i) => {
    const key = roleColorKey(name, type)
    out[name] = key in overrides
      ? overrides[key]
      : ROLE_SWATCH_CLASSES[i % ROLE_SWATCH_CLASSES.length]
  })
  return out
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd webapp/frontend && npm test -- --run src/builder/roleColors.test.ts`
Expected: PASS, 10 tests.

- [ ] **Step 5: Commit**

```bash
git add webapp/frontend/src/builder/roleColors.ts webapp/frontend/src/builder/roleColors.test.ts
git commit -m "$(cat <<'EOF'
feat(studio): role colour ramp and positional assignment

Eight fully-written-out swatch classes drawn from the same reserved-hue
exclusion list as the construct tints, auto-assigned by declaration
order and keyed by type:name.

Assignment is positional and overrides apply on top, so clearing one
role's colour does not renumber its neighbours.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Sja96BZrnZvKJUKU11cw3e
EOF
)"
```

---

### Task 4: localStorage persistence for role colours

**Files:**
- Create: `webapp/frontend/src/builder/roleColorStorage.ts`
- Create: `webapp/frontend/src/stores/roleColorStore.ts`
- Test: `webapp/frontend/src/builder/roleColorStorage.test.ts`

**Interfaces:**
- Consumes: `ROLE_SWATCH_CLASSES` from Task 3.
- Produces: `ROLE_COLOR_STORAGE_KEY`; `parseOverrides(raw: string | null): Record<string, string | null>`; `serializeOverrides(o: Record<string, string | null>): string`; `useRoleColorStore` with `{ overrides, setColor(key, cls), clearColor(key), resetColor(key) }`.

- [ ] **Step 1: Write the failing test**

Create `webapp/frontend/src/builder/roleColorStorage.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import { parseOverrides, serializeOverrides } from './roleColorStorage'
import { ROLE_SWATCH_CLASSES } from './roleColors'

describe('parseOverrides', () => {
  it('returns an empty map for absent storage', () => {
    expect(parseOverrides(null)).toEqual({})
  })

  // Role colour is a reading aid, never document state. Corrupt storage must degrade to
  // "everything auto-assigned", never throw and take the canvas down with it.
  it('returns an empty map for unparseable JSON', () => {
    expect(parseOverrides('{not json')).toEqual({})
  })

  it('returns an empty map for JSON that is not an object', () => {
    expect(parseOverrides('[1,2,3]')).toEqual({})
    expect(parseOverrides('"a string"')).toEqual({})
    expect(parseOverrides('null')).toEqual({})
  })

  it('keeps class strings and explicit nulls', () => {
    const raw = JSON.stringify({ 'pump:a': ROLE_SWATCH_CLASSES[2], 'pump:b': null })
    expect(parseOverrides(raw)).toEqual({ 'pump:a': ROLE_SWATCH_CLASSES[2], 'pump:b': null })
  })

  // A colour class that is not in the ramp would render as an unknown Tailwind class —
  // i.e. no background at all — which looks identical to "cleared" but is not.
  it('drops values that are neither null nor a ramp class', () => {
    const raw = JSON.stringify({ 'pump:a': 'bg-red-500', 'pump:b': 42, 'pump:c': null })
    expect(parseOverrides(raw)).toEqual({ 'pump:c': null })
  })

  // Stale keys are inert BY DESIGN and must not be pruned: a rename followed by an undo
  // has to recover the original colour (spec §5).
  it('keeps keys for roles that no longer exist', () => {
    const raw = JSON.stringify({ 'pump:deleted': ROLE_SWATCH_CLASSES[1] })
    expect(parseOverrides(raw)).toEqual({ 'pump:deleted': ROLE_SWATCH_CLASSES[1] })
  })
})

describe('serializeOverrides', () => {
  it('round-trips through parseOverrides', () => {
    const o = { 'pump:a': ROLE_SWATCH_CLASSES[0], 'sensor:b': null }
    expect(parseOverrides(serializeOverrides(o))).toEqual(o)
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd webapp/frontend && npm test -- --run src/builder/roleColorStorage.test.ts`
Expected: FAIL — `Failed to resolve import "./roleColorStorage"`.

- [ ] **Step 3: Write the pure storage module**

Create `webapp/frontend/src/builder/roleColorStorage.ts`:

```ts
/** Reading and writing the role-colour overrides (design §5).
 *
 * User-settled 2026-07-18: these live in browser localStorage keyed by `type:name`, NOT in
 * the document. Role colour is a per-user reading aid, so a colleague opening the same doc
 * on the shared stack sees different colours and the assignment does not survive a new
 * machine — both accepted. Nothing here is exported, imported, validated, or sent to the
 * backend, which is what keeps this increment frontend-only.
 *
 * Parsing is total: every failure degrades to "no overrides", i.e. everything auto-assigned
 * from the ramp. Corrupt storage must never be able to take the canvas down.
 */
import { ROLE_SWATCH_CLASSES } from './roleColors'

export const ROLE_COLOR_STORAGE_KEY = 'studio.roleColors.v1'

const RAMP: readonly string[] = ROLE_SWATCH_CLASSES

export function parseOverrides(raw: string | null): Record<string, string | null> {
  if (raw === null) return {}
  let parsed: unknown
  try {
    parsed = JSON.parse(raw)
  } catch {
    return {}
  }
  if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) return {}
  const out: Record<string, string | null> = {}
  for (const [key, value] of Object.entries(parsed as Record<string, unknown>)) {
    // A value outside the ramp would compile to no Tailwind class, rendering as no
    // background at all — indistinguishable on screen from "cleared", but not the same
    // state. Dropping it re-auto-assigns, which is the honest recovery.
    if (value === null) out[key] = null
    else if (typeof value === 'string' && RAMP.includes(value)) out[key] = value
  }
  return out
}

export function serializeOverrides(o: Record<string, string | null>): string {
  return JSON.stringify(o)
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd webapp/frontend && npm test -- --run src/builder/roleColorStorage.test.ts`
Expected: PASS, 8 tests.

- [ ] **Step 5: Write the store**

Create `webapp/frontend/src/stores/roleColorStore.ts`:

```ts
/** Role-colour overrides, persisted to localStorage.
 *
 * Deliberately a SEPARATE store from docStore: role colour is view state, never document
 * state, so it must not enter the zundo snapshot (the same family as `selectedUid` and
 * `scope`, W9-settled). Undo must not undo a colour choice, and a colour choice must not
 * make the document dirty.
 *
 * Stale keys are never garbage-collected — a rename followed by an undo has to recover the
 * original colour (design §5).
 */
import { create } from 'zustand'
import {
  ROLE_COLOR_STORAGE_KEY,
  parseOverrides,
  serializeOverrides,
} from '../builder/roleColorStorage'

function load(): Record<string, string | null> {
  try {
    return parseOverrides(localStorage.getItem(ROLE_COLOR_STORAGE_KEY))
  } catch {
    // Private-mode / disabled storage: colours degrade to auto-assigned for the session.
    return {}
  }
}

function save(o: Record<string, string | null>): void {
  try {
    localStorage.setItem(ROLE_COLOR_STORAGE_KEY, serializeOverrides(o))
  } catch {
    // Quota or disabled storage — the in-memory value still drives this session's render.
  }
}

type RoleColorState = {
  overrides: Record<string, string | null>
  /** Pin a role to a specific ramp class. */
  setColor: (key: string, cls: string) => void
  /** Explicit "no colour" — renders as a plain white card, as before this increment. */
  clearColor: (key: string) => void
  /** Forget the override entirely, returning the role to positional auto-assignment. */
  resetColor: (key: string) => void
}

export const useRoleColorStore = create<RoleColorState>((set) => ({
  overrides: load(),
  setColor: (key, cls) =>
    set((s) => {
      const next = { ...s.overrides, [key]: cls }
      save(next)
      return { overrides: next }
    }),
  clearColor: (key) =>
    set((s) => {
      const next = { ...s.overrides, [key]: null }
      save(next)
      return { overrides: next }
    }),
  resetColor: (key) =>
    set((s) => {
      const next = { ...s.overrides }
      delete next[key]
      save(next)
      return { overrides: next }
    }),
}))
```

- [ ] **Step 6: Typecheck and run the full suite**

Run: `cd webapp/frontend && npm run typecheck && npm test -- --run`
Expected: typecheck clean, all tests pass.

- [ ] **Step 7: Commit**

```bash
git add webapp/frontend/src/builder/roleColorStorage.ts webapp/frontend/src/builder/roleColorStorage.test.ts webapp/frontend/src/stores/roleColorStore.ts
git commit -m "$(cat <<'EOF'
feat(studio): persist role colours to localStorage

Separate store from docStore: role colour is view state, so it stays out
of the zundo snapshot and never makes the document dirty.

Parsing is total — corrupt storage, non-object JSON, and out-of-ramp
values all degrade to auto-assignment rather than throwing. Stale keys
are kept on purpose so rename-then-undo recovers the original colour.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Sja96BZrnZvKJUKU11cw3e
EOF
)"
```

---

### Task 5: Structured summary segments

**Files:**
- Modify: `webapp/frontend/src/builder/summary.ts`
- Modify: `webapp/frontend/src/builder/summary.test.ts`

**Interfaces:**
- Produces: `type SummarySegment = { text: string; role: 'subject' | 'verb' | 'detail' | 'marker' }`; `blockSummaryParts(node: BlockNode): SummarySegment[]`. `blockSummary` becomes the join of the parts and its output must not change by a single byte.

- [ ] **Step 1: Write the failing test**

Append to `webapp/frontend/src/builder/summary.test.ts`:

```ts
import { blockSummaryParts } from './summary'

describe('blockSummaryParts', () => {
  // blockSummary feeds the `title` attribute, the drag overlay and WorkflowSnapshot. If the
  // join ever drifts from the string those three silently disagree with the card.
  it('joins to exactly the legacy summary for every kind', () => {
    for (const node of ALL_KIND_FIXTURES) {
      expect(blockSummaryParts(node).map((s) => s.text).join('')).toBe(blockSummary(node))
    }
  })

  it('splits a command into role, verb and params', () => {
    const node = ALL_KIND_FIXTURES.find((n) => n.kind === 'command')!
    const parts = blockSummaryParts(node)
    expect(parts.filter((p) => p.role === 'subject').map((p) => p.text)).toEqual(['pump1'])
    expect(parts.filter((p) => p.role === 'verb').map((p) => p.text)).toEqual(['dispense'])
  })

  it('marks the fault marker as its own segment', () => {
    const node = { ...ALL_KIND_FIXTURES.find((n) => n.kind === 'command')!,
                   onError: 'continue' as const }
    const marker = blockSummaryParts(node).filter((p) => p.role === 'marker')
    expect(marker).toHaveLength(1)
    expect(marker[0].text).toContain('⤳')
  })

  it('emits no marker segment when neither retry nor on_error is set', () => {
    const node = ALL_KIND_FIXTURES.find((n) => n.kind === 'wait')!
    expect(blockSummaryParts(node).filter((p) => p.role === 'marker')).toHaveLength(0)
  })
})
```

`ALL_KIND_FIXTURES` must be a `BlockNode[]` covering all 14 kinds, with the `command` fixture using device `pump1` and verb `dispense`. If `summary.test.ts` already defines per-kind fixtures, reuse them and export a combined array; if not, build one at the top of the file using `newPaletteNode` from `./tree` for the 11 palette kinds plus hand-written `command`, `measure` and `group_ref` nodes. Read the existing file first and follow whatever fixture style it already uses.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd webapp/frontend && npm test -- --run src/builder/summary.test.ts`
Expected: FAIL — `blockSummaryParts is not exported`.

- [ ] **Step 3: Implement parts as the single source of truth**

In `webapp/frontend/src/builder/summary.ts`, add above `blockSummary`:

```ts
/** A run of summary text tagged by what it is, so the canvas can give the three facts on a
 * card different weights instead of rendering `pump1 · dispense (volume=5)` as one
 * undifferentiated slate run (design §3.4).
 *
 * `subject` is the actor (a device role, or the target of a compute/record); `verb` is what
 * happens; `detail` is everything else including separators; `marker` is the fault-tolerance
 * suffix. Separators live in `detail` segments so the join reproduces the legacy string
 * byte-for-byte — `blockSummary` is that join, so there is exactly one source of truth. */
export type SummarySegment = {
  text: string
  role: 'subject' | 'verb' | 'detail' | 'marker'
}

const seg = (text: string, role: SummarySegment['role']): SummarySegment => ({ text, role })

/** Segments whose concatenation IS `blockSummary(node)`. Pinned by test. */
export function blockSummaryParts(node: BlockNode): SummarySegment[] {
  const marker = faultMarker(node)
  const tail: SummarySegment[] = marker ? [seg(marker, 'marker')] : []
  const parts = (): SummarySegment[] => {
    switch (node.kind) {
      case 'command': {
        const params = formatParams(node.params)
        return [
          seg(node.device, 'subject'),
          seg(' · ', 'detail'),
          seg(node.verb, 'verb'),
          ...(params ? [seg(` (${params})`, 'detail')] : []),
        ]
      }
      case 'measure':
        return [
          seg(node.device, 'subject'),
          seg(' · ', 'detail'),
          seg(node.verb, 'verb'),
          seg(` → ${node.into || '?'}`, 'detail'),
        ]
      case 'wait':
        return [seg('wait', 'verb'), seg(` ${node.duration}`, 'detail')]
      case 'operator_input':
        return [
          seg('input', 'verb'),
          seg(' ', 'detail'),
          seg(node.name, 'subject'),
          seg(` (${node.inputType})`, 'detail'),
        ]
      case 'serial':
        return [seg('Serial', 'verb'), seg(` · ${node.children.length}`, 'detail')]
      case 'parallel':
        return [seg('Parallel', 'verb'), seg(` · ${node.children.length} lanes`, 'detail')]
      case 'loop':
        return node.mode === 'count'
          ? [seg('Loop', 'verb'), seg(` ×${node.count}`, 'detail')]
          : [seg('Loop until', 'verb'), seg(` ${node.until || '…'}`, 'detail')]
      case 'branch':
        return [seg('If', 'verb'), seg(` ${node.condition || '…'}`, 'detail')]
      case 'compute':
        return [
          seg(node.into || '?', 'subject'),
          seg(` = ${String(node.value) || '…'}`, 'detail'),
        ]
      case 'record':
        return [
          seg(node.into || '?', 'subject'),
          seg(` ← ${String(node.value) || '…'}`, 'detail'),
        ]
      case 'abort':
        return [seg('Abort if', 'verb'), seg(` ${node.condition || '…'}`, 'detail')]
      case 'alarm':
        return [seg('Alarm if', 'verb'), seg(` ${node.condition || '…'}`, 'detail')]
      case 'for_each':
        return node.var !== null
          ? [
              seg('For each', 'verb'),
              seg(' ', 'detail'),
              seg(node.var, 'subject'),
              seg(` in [${node.items.join(', ')}]`, 'detail'),
            ]
          : [seg('For each', 'verb'), seg(` of ${node.items.length} items`, 'detail')]
      case 'group_ref': {
        const args = formatParams(node.args)
        return [
          seg(node.name || '?', 'subject'),
          ...(args ? [seg(`(${args})`, 'detail')] : []),
        ]
      }
    }
  }
  return [...parts(), ...tail]
}
```

Then replace the entire body of `blockSummary` with:

```ts
export function blockSummary(node: BlockNode): string {
  return blockSummaryParts(node)
    .map((s) => s.text)
    .join('')
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd webapp/frontend && npm test -- --run src/builder/summary.test.ts`
Expected: PASS. **Every pre-existing `blockSummary` assertion must still pass unchanged** — if any fails, the parts are wrong, not the old test.

- [ ] **Step 5: Render the parts with weight on the canvas**

In `Canvas.tsx`, add `blockSummaryParts` to the existing `./summary` import, and replace the summary span (line 236) with:

```tsx
        <span title={blockSummary(node)} className="max-w-80 truncate">
          {blockSummaryParts(node).map((s, i) => (
            <span
              key={i}
              className={
                s.role === 'subject'
                  ? 'font-medium text-slate-900'
                  : s.role === 'verb'
                    ? 'text-slate-700'
                    : 'text-caption'
              }
            >
              {s.text}
            </span>
          ))}
        </span>
```

The `title` keeps the joined string, so the full text stays reachable when `truncate` ellipsizes (audit rule R2).

- [ ] **Step 6: Typecheck, lint, and run the full suite**

Run: `cd webapp/frontend && npm run typecheck && npm run lint && npm test -- --run`
Expected: all clean.

- [ ] **Step 7: Commit**

```bash
git add webapp/frontend/src/builder/summary.ts webapp/frontend/src/builder/summary.test.ts webapp/frontend/src/builder/Canvas.tsx
git commit -m "$(cat <<'EOF'
feat(studio): give card summaries typographic hierarchy

blockSummaryParts returns the summary as tagged segments and
blockSummary becomes their join, so there is one source of truth and
the title attribute, drag overlay and WorkflowSnapshot cannot drift.

Canvas renders role, verb and params at three weights instead of one
undifferentiated slate run, separating three facts without spending
any colour.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Sja96BZrnZvKJUKU11cw3e
EOF
)"
```

---

### Task 6: Role swatches on canvas cards

**Files:**
- Modify: `webapp/frontend/src/builder/Canvas.tsx` (`BlockView`)

**Interfaces:**
- Consumes: `assignRoleColors`, `roleColorKey` from Task 3; `useRoleColorStore` from Task 4.
- Produces: `useRoleColor(node)` — module-private hook returning the swatch class or null.

- [ ] **Step 1: Add the hook**

In `Canvas.tsx`, add imports:

```tsx
import { assignRoleColors } from './roleColors'
import { useRoleColorStore } from '../stores/roleColorStore'
```

Add above `BlockView`:

```tsx
/** The swatch class for a block's device role, or null when the block has no role or the
 * user cleared that role's colour. Resolved from the doc's roles rather than stored on the
 * block, so every command and measure of a role shares one colour by construction. */
function useRoleColor(node: BlockNode): string | null {
  const roles = useDocStore((s) => s.roles)
  const overrides = useRoleColorStore((s) => s.overrides)
  const assigned = useMemo(() => assignRoleColors(roles, overrides), [roles, overrides])
  if (node.kind !== 'command' && node.kind !== 'measure') return null
  return assigned[node.device] ?? null
}
```

- [ ] **Step 2: Render the swatch**

In `BlockView`, after the `const isContainer = ...` line add:

```tsx
  const swatch = useRoleColor(node)
```

Then insert the swatch immediately before `<KindIcon kind={node.kind} />` (line 228):

```tsx
        {swatch && (
          <span
            aria-hidden
            className={`h-2.5 w-2.5 shrink-0 rounded-sm ${swatch}`}
          />
        )}
```

`aria-hidden` because the role name is already in the summary text beside it — the swatch is redundant colour, never the sole carrier of the fact. That is also what keeps it from failing the colour-only-encoding accessibility rule.

- [ ] **Step 3: Typecheck, lint, run the suite**

Run: `cd webapp/frontend && npm run typecheck && npm run lint && npm test -- --run`
Expected: all clean.

- [ ] **Step 4: Verify in a browser**

Run: `cd webapp/frontend && npm run capture`
Then open `morbidostat.json` and confirm every command/measure card for the same role wears the same swatch, and that two different roles differ.

- [ ] **Step 5: Commit**

```bash
git add webapp/frontend/src/builder/Canvas.tsx
git commit -m "$(cat <<'EOF'
feat(studio): role swatches on command and measure cards

Colour is resolved from the doc's roles rather than stored per block, so
every action of a role shares one swatch by construction.

The swatch is aria-hidden: the role name is already in the summary text
beside it, so colour is never the sole carrier of the fact.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Sja96BZrnZvKJUKU11cw3e
EOF
)"
```

---

### Task 7: Role colour editing in the Roles section

**Files:**
- Modify: `webapp/frontend/src/builder/Palette.tsx` (the roles section — locate the per-device-type block that renders role badges and the pencil/cross `IconButton`s, W13 §3.3)

**Interfaces:**
- Consumes: `ROLE_SWATCH_CLASSES`, `roleColorKey` from Task 3; `useRoleColorStore` from Task 4.

- [ ] **Step 1: Read the roles section first**

Run: `cd webapp/frontend && grep -n "badgeClass\|IconButton\|selectedRole\|roleGroups" src/builder/Palette.tsx`

Identify the badge row that already carries the selected role's rename (pencil) and delete (cross) `IconButton`s. The colour control joins that row as a third action. Do not restructure the row.

- [ ] **Step 2: Add the colour control**

Add imports to `Palette.tsx`:

```tsx
import { Palette as PaletteIcon } from 'lucide-react'
import { ROLE_SWATCH_CLASSES, roleColorKey } from './roleColors'
import { useRoleColorStore } from '../stores/roleColorStore'
```

Add this component to `Palette.tsx`:

```tsx
/** Colour control for the selected role: a popover of the eight ramp swatches plus a
 * "no colour" choice. Uses `useDismissable` for outside-click/Esc, the same as every other
 * popover here — a popover that cannot be dismissed was finding #6 of the W11 round. */
function RoleColorPicker({ name, type }: { name: string; type: string }) {
  const [open, setOpen] = useState(false)
  const ref = useDismissable(open, () => setOpen(false))
  const setColor = useRoleColorStore((s) => s.setColor)
  const clearColor = useRoleColorStore((s) => s.clearColor)
  const key = roleColorKey(name, type)
  return (
    <span ref={ref} className="relative inline-flex">
      <IconButton
        icon={PaletteIcon}
        label={`Colour for ${name}`}
        onClick={(e) => {
          e.stopPropagation()
          setOpen((v) => !v)
        }}
      />
      {open && (
        <span className="absolute right-0 top-6 z-10 flex w-max flex-wrap gap-1 rounded border border-slate-300 bg-white p-1 shadow-lg">
          {ROLE_SWATCH_CLASSES.map((cls) => (
            <button
              key={cls}
              title={cls}
              aria-label={cls}
              onClick={() => {
                setColor(key, cls)
                setOpen(false)
              }}
              className={`h-4 w-4 rounded-sm ${cls}`}
            />
          ))}
          <button
            onClick={() => {
              clearColor(key)
              setOpen(false)
            }}
            className={inlineButtonClass({ subtle: true })}
          >
            no colour
          </button>
        </span>
      )}
    </span>
  )
}
```

If `useDismissable`, `IconButton`, `inlineButtonClass` or `useState` are not already imported in `Palette.tsx`, add them.

- [ ] **Step 3: Mount it in the badge row**

Render `<RoleColorPicker name={selectedRole} type={block.type} />` immediately before the existing pencil `IconButton` in the selected-role action group, using whatever local variable names that file already uses for the selected role and its device type.

- [ ] **Step 4: Typecheck, lint, run the suite**

Run: `cd webapp/frontend && npm run typecheck && npm run lint && npm test -- --run`
Expected: all clean.

- [ ] **Step 5: Verify persistence in a browser**

Run: `cd webapp/frontend && npm run dev`, open a doc with roles, change a role's colour, confirm every card for that role updates, then **reload the page** and confirm the colour survived. Choose "no colour" and confirm those cards render plain white as before. Confirm undo (Ctrl-Z) does **not** revert a colour change and that the unsaved `●` does not appear.

- [ ] **Step 6: Commit**

```bash
git add webapp/frontend/src/builder/Palette.tsx
git commit -m "$(cat <<'EOF'
feat(studio): let users pick or clear a role's colour

Adds a swatch popover to the selected role's action row, alongside
rename and delete. "No colour" renders that role's cards plain white,
as before this increment.

Colour changes are view state: they persist across reloads, do not
enter undo, and do not mark the document dirty.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Sja96BZrnZvKJUKU11cw3e
EOF
)"
```

---

### Task 8: Hatching for scope and group_ref

**Files:**
- Modify: `webapp/frontend/src/index.css`
- Modify: `webapp/frontend/src/builder/Canvas.tsx` (`Canvas`, `ScopeSwitcher`, `BlockView`)

**Interfaces:**
- Produces: `bg-hatch` and `edge-hatch` Tailwind utilities.

- [ ] **Step 1: Add the utilities**

Append to `webapp/frontend/src/index.css`:

```css
/* "Stands for something that is not shown here" — the ONLY meaning hatching carries
   (design §3.5). Used in exactly two places: the canvas backdrop while editing a group
   body (a subroutine, not the main workflow) and a group_ref card's left edge (a leaf
   that expands to a whole subtree rendered nowhere on screen). Not a decoration: adding
   a third hatched surface for any other reason dilutes it back to noise.

   Both are low-coverage slate-200 on a light ground, chosen so text over them still
   clears AA — verify with the probe, not by eye, whenever either is moved. */
@utility bg-hatch {
  background-image: repeating-linear-gradient(
    45deg,
    transparent 0 5px,
    var(--color-slate-200) 5px 6px
  );
}

@utility edge-hatch {
  background-image: repeating-linear-gradient(
    45deg,
    var(--color-slate-300) 0 2px,
    transparent 2px 5px
  );
  background-size: 5px 100%;
  background-repeat: repeat-y;
  background-position: left top;
}
```

- [ ] **Step 2: Hatch the canvas backdrop while in a group scope**

In `Canvas`, read the scope and select the backdrop class. Add near the other selectors:

```tsx
  const scope = useDocStore((s) => s.scope)
```

Replace the scroller `className` (line 56) with:

```tsx
          className={
            // Editing a group body was pixel-identical to editing the main workflow — the
            // only cue was the value in a dropdown. The hatch says "this is a subroutine"
            // without stealing any content space.
            'h-full overflow-auto p-4 ' +
            (scope === null ? 'bg-slate-100' : 'bg-slate-100 bg-hatch')
          }
```

- [ ] **Step 3: Give the scope switcher a solid strip when in a group**

Text must not sit directly on the hatch. Replace `ScopeSwitcher`'s root `className` (line 115) with:

```tsx
      className={
        'mb-2 flex flex-wrap items-center gap-2 rounded px-2 py-1 text-xs ' +
        (scope === null ? '' : 'bg-white shadow-sm')
      }
```

and add `const scope = useDocStore((s) => s.scope)` — it is already read in that component, so reuse the existing binding rather than adding a second one.

- [ ] **Step 4: Hatch the group_ref card's left edge**

In `BlockView`, extend the card `className` expression from Task 2 by adding one selected class:

```tsx
        'min-w-0 rounded border bg-white text-sm shadow-sm ' +
        cardBorderClass({ kind: node.kind, selected }) + ' ' +
        (node.kind === 'group_ref' ? 'edge-hatch pl-1.5 ' : '') +
        (selected ? 'ring-2 ring-blue-400 ' : '') +
        (isDragging ? 'opacity-40' : '')
```

- [ ] **Step 5: Typecheck, lint, build, run the suite**

Run: `cd webapp/frontend && npm run typecheck && npm run lint && npm test -- --run && npm run build`
Expected: all clean. The build must succeed — a malformed `@utility` block fails at compile time, not at runtime.

- [ ] **Step 6: Verify the hatch does not break contrast**

Run: `cd webapp/frontend && npm run capture`
Expected: contrast rule stays at its established residual count. **The probe uses pixel readback, so a hatched backdrop behind text is exactly the case it will catch.** If any new violation lands on text over `bg-hatch`, reduce the hatch's coverage or move the text onto the solid strip from Step 3 — do not suppress the rule.

- [ ] **Step 7: Commit**

```bash
git add webapp/frontend/src/index.css webapp/frontend/src/builder/Canvas.tsx
git commit -m "$(cat <<'EOF'
feat(studio): hatch group scope and group_ref cards

Two utilities carrying one meaning: this stands for something not shown
here. The canvas backdrop hatches while editing a group body, which was
previously pixel-identical to editing the main workflow, and a group_ref
card's left edge hatches because it is a leaf that expands to a subtree
rendered nowhere on screen.

The scope switcher gets a solid strip so its text never sits on the
hatch.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Sja96BZrnZvKJUKU11cw3e
EOF
)"
```

---

### Task 9: Probe verification and project-rule update

**Files:**
- Modify: `webapp/frontend/tools/capture.mjs`
- Modify: `webapp/frontend/CLAUDE.md`
- Create: `docs/visual-language/after/` (screenshots)

- [ ] **Step 1: Make the capture harness actually render what this increment changed**

Read `webapp/frontend/tools/capture.mjs` and confirm its state list includes a state that (a) opens a document nested at least **three** containers deep, and (b) switches into a **group scope**. If either is missing, add it.

This is not optional diligence. W12 shipped a probe rule that reported clean on rows that **never mounted**, because the harness never opened the panel it measured — the plan read as though it had been verified. A depth-zebra rule that only ever sees depth 1 is the same defect.

- [ ] **Step 2: Run the probe self-test, then the capture**

Run: `cd webapp/frontend && npm run probe:selftest && npm run capture`
Expected: self-test passes; capture writes screenshots for every state/viewport combination.

- [ ] **Step 3: Record the results**

Copy the capture output into `docs/visual-language/after/` and write a short `docs/visual-language/after/README.md` stating, with measured numbers: the contrast-rule count before and after, the `sibling-height-mismatch` count (must be 0), and the viewports covered.

If any count regressed, **stop and report it** rather than recording it as acceptable.

- [ ] **Step 4: Generalise the cascade rule in the project rules**

In `webapp/frontend/CLAUDE.md`, the "Control height" section documents the select-don't-append rule for **widths** only. That narrowness is exactly why W12 reintroduced the same bug in **colour**. Add a new top-level section:

```markdown
## Colour

- Construct tints, role swatches and state colours are three separate languages and must
  not be mixed. Hue (blue/red/amber/emerald) is reserved for **state**: selection, error,
  warning, valid. Construct identity uses the pale tints in `src/builder/constructTint.ts`;
  device roles use the saturated ramp in `src/builder/roleColors.ts`. Both deliberately
  exclude every reserved family. Adding a canvas colour outside those two modules is how
  the error language stops being readable.
- **Any class baked into a helper is un-overridable by concatenation — for every property,
  not just width.** `cardBorderClass` and friends *select* and return exactly one class per
  property. Never `helperClass() + ' border-blue-500'`: equal-specificity utilities in the
  same `@layer utilities` block are decided by declaration order in the compiled stylesheet,
  not by class-string order. W11 hit this on `width`, W12 hit it on `text` colour, where an
  appended `text-blue-700` lost to a baked-in `text-slate-500` and the highlight never
  rendered while looking perfect in source.
- **Tailwind class names must be complete literals in source.** Tailwind 4 scans source
  text; `` `bg-${family}-500` `` compiles to no CSS at all.
- Hatching (`bg-hatch`, `edge-hatch` in `index.css`) means exactly one thing: *this stands
  for something not shown here*. It has two sanctioned uses — group scope and `group_ref`.
  A third dilutes it to decoration.
```

- [ ] **Step 5: Run the full gate**

Run: `cd webapp/frontend && npm run lint && npm run typecheck && npm test -- --run && npm run build`
Expected: all pass.

Also run the backend suite, which this increment does not touch but which the gate covers:
Run: `cd webapp/backend && .venv/bin/python -m pytest -q && .venv/bin/python -m mypy && .venv/bin/python -m ruff check .`
Expected: all pass. (`mypy` takes no path argument.)

- [ ] **Step 6: Commit**

```bash
git add webapp/frontend/tools/capture.mjs webapp/frontend/CLAUDE.md docs/visual-language/
git commit -m "$(cat <<'EOF'
docs(studio): probe evidence and colour project rules

Capture harness gains a deep-nesting and a group-scope state, without
which the depth zebra and the scope hatch would have been reported clean
by rules that never saw them — W12's vacuous-probe defect.

CLAUDE.md gains a Colour section generalising the select-don't-append
rule from widths to every property, which is the narrowness that let
W12 reintroduce the same bug in text colour.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Sja96BZrnZvKJUKU11cw3e
EOF
)"
```

---

## Self-review

**Spec coverage:**

| Spec section | Task |
|---|---|
| §3.1 construct border + header | 1, 2 |
| §3.1 selection strengthens to `ring-2` | 2 |
| §3.2 depth zebra, slate-50/slate-100 | 1, 2 |
| §3.2 branch arms gain a box | 2 |
| §3.3 role swatches, 8-colour ramp, declaration order, wrap | 3 |
| §3.3 edit / clear to white | 7 |
| §3.4 `blockSummaryParts`, join equals legacy, weights | 5 |
| §3.5 group-scope hatch, `group_ref` edge | 8 |
| §4 select-don't-append, literal classes, node-env tests | 1, 3, 9 |
| §5 localStorage, `type:name` key, stale keys inert | 4 |
| §7 verification, fixtures, probe not vacuous | 2, 6, 9 |

No spec requirement is unassigned.

**Placeholder scan:** none. Task 5 Step 1 and Task 7 Steps 1/3 direct the implementer to read an existing file before editing — that is a real instruction with a stated command, not a deferred decision.

**Type consistency:** `cardBorderClass`/`headerFillClass`/`interiorFillClass`/`isFlowKind` (Task 1) are consumed with those exact names in Task 2. `ROLE_SWATCH_CLASSES`/`roleColorKey`/`assignRoleColors` (Task 3) match their use in Tasks 4, 6, 7. `useRoleColorStore`'s `setColor`/`clearColor`/`resetColor` (Task 4) match Task 7. `SummarySegment['role']` values `subject`/`verb`/`detail`/`marker` (Task 5 Step 3) match the three branches rendered in Step 5 — `marker` falls to the `text-caption` default, which is intended.

**Known risk carried into execution:** Task 2 Step 7 and Task 8 Step 6 are the two places where a measured probe result can veto the design's colour choices. Both say to report rather than suppress. `bg-lime-50` and `bg-teal-50` are the likeliest to need a step darker for header text to clear AA.
