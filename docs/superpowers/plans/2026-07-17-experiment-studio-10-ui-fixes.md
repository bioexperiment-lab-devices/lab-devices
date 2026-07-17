# Experiment Studio W10 — UI-audit fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix all 24 findings of `docs/ui-audit/2026-07-17.md` plus dialog accessibility, per the spec `docs/superpowers/specs/2026-07-17-experiment-studio-ui-fixes-design.md`.

**Architecture:** A small `src/ui/` module (IconButton + a block-kind→Lucide icon map) replaces every raw glyph control; two Tailwind 4 `@utility` text tokens replace the failing caption colors; per-finding behavioral fixes extract their decision logic into pure functions for node-env vitest. Verification is a full re-run of the audit's mechanical probe.

**Tech Stack:** React 19 + TypeScript strict, Tailwind 4 (oklch output!), lucide-react (new dep), zustand, dnd-kit, uPlot, vitest 4 (node env — NO jsdom, NO @testing-library/react), oxlint.

## Global Constraints

- All frontend paths below are relative to `webapp/frontend/` unless they start with `docs/`, `src/lab_devices/`, or `webapp/backend/`.
- **Icon rule (user-settled, spec §3):** interactive icons come from `lucide-react` only; no raw glyph characters for interactive controls. Semantic notation stays typographic: `∀` (for_each), `R×N`, `⤳`, `×N`, the `●` unsaved dot, `…`, prose dashes/arrows.
- **Vitest is node-env.** Never render React components in tests; test pure functions only. Do NOT add jsdom or @testing-library/react.
- **Every behavioral test must be mutation-verified:** written first and seen failing (TDD), or demonstrated to fail with the fix reverted. A test that passes both ways is vacuous.
- **Do not change contrast by eye.** Tailwind 4 emits `oklch()`; the probe (Task 12) is the referee. The default replacements are `slate-400/300 → text-caption (slate-600)` for meaning-carrying text and `text-hint (slate-500)` for incidental text.
- Frontend gates: `cd webapp/frontend && npm run lint && npm run typecheck && npm test -- --run && npm run build` (2 known oxlint fast-refresh warnings are OK, exit 0).
- Backend gates (Task 11 only; no backend code changes expected): `cd webapp/backend && .venv/bin/python -m pytest -q && .venv/bin/python -m mypy && .venv/bin/python -m ruff check .` (mypy takes NO path argument).
- Commit after every task with a conventional-commit message; the branch is `feat/experiment-studio-ui-fixes`.
- tsconfig uses `erasableSyntaxOnly` + `verbatimModuleSyntax`: use `import type` for type-only imports.

---

### Task 1: Foundation — lucide-react, text tokens, ui/ primitives, frontend CLAUDE.md

**Files:**
- Modify: `package.json` (via npm install)
- Modify: `src/index.css`
- Create: `src/ui/IconButton.tsx`
- Create: `src/ui/icons.tsx`
- Create: `webapp/frontend/CLAUDE.md` (repo path `webapp/frontend/CLAUDE.md`)

**Interfaces:**
- Produces: `IconButton` component — `{ icon: LucideIcon; label: string; onClick: (e: React.MouseEvent<HTMLButtonElement>) => void; destructive?: boolean; disabled?: boolean; className?: string }`, renders a 24×24 button (`h-6 w-6`) with a 14px icon, `title` + `aria-label` = label.
- Produces: `iconButtonClass(destructive?: boolean): string` — the same classes as a string, for `<a>` elements that must look like an IconButton.
- Produces: `BLOCK_ICONS: Record<BlockNode['kind'], LucideIcon | null>` and `KindIcon` component — `{ kind: BlockNode['kind']; className?: string }`. `for_each` maps to `null` and KindIcon renders a typographic `∀` for it.
- Produces: `@utility text-caption` (slate-600) and `@utility text-hint` (slate-500) usable as Tailwind classes.

- [ ] **Step 1: Install lucide-react**

Run: `cd webapp/frontend && npm install lucide-react`
Expected: `lucide-react` appears in `package.json` dependencies; lockfile updated.

- [ ] **Step 2: Add the text tokens and the scroll-shadow utility to `src/index.css`**

Replace the file content (currently just the tailwind import) with:

```css
@import 'tailwindcss';

/* Meaning-carrying secondary text (audit finding 1): captions, section headers,
   timestamps, lane/branch labels. slate-600 clears 4.5:1 on white, slate-50 and
   slate-100 backgrounds; the old slate-400 measured 2.4-2.6:1. */
@utility text-caption {
  color: var(--color-slate-600);
}

/* Incidental text only (placeholders, empty-state hints). slate-500 — verify against
   the probe wherever the background is tinted; prefer text-caption when in doubt. */
@utility text-hint {
  color: var(--color-slate-500);
}

/* Pure-CSS horizontal scroll shadow (Lea Verou technique) for overflowing lane
   strips: edge shadows appear only when content extends past that edge. */
@utility scroll-x-shadow {
  background:
    linear-gradient(to right, white 30%, rgb(255 255 255 / 0)) left / 40px 100%,
    linear-gradient(to left, white 30%, rgb(255 255 255 / 0)) right / 40px 100%,
    linear-gradient(to right, rgb(0 0 0 / 0.14), rgb(0 0 0 / 0)) left / 14px 100%,
    linear-gradient(to left, rgb(0 0 0 / 0.14), rgb(0 0 0 / 0)) right / 14px 100%;
  background-repeat: no-repeat;
  background-attachment: local, local, scroll, scroll;
}
```

- [ ] **Step 3: Create `src/ui/IconButton.tsx`**

```tsx
import type { MouseEvent } from 'react'
import type { LucideIcon } from 'lucide-react'

/** The one component for per-row/per-card icon actions (spec §3). Contract:
 * ≥24×24px hit area (h-6 w-6), 14px icon, resting slate-500, hover slate-700
 * (destructive: red-600), focus-visible ring, title+aria-label always set.
 * Raw glyph characters for interactive controls are banned — see CLAUDE.md. */

export function iconButtonClass(destructive = false): string {
  return (
    'inline-flex h-6 w-6 shrink-0 items-center justify-center rounded text-slate-500 ' +
    'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-400 ' +
    'disabled:opacity-40 ' +
    (destructive
      ? 'hover:bg-red-50 hover:text-red-600 '
      : 'hover:bg-slate-200 hover:text-slate-700 ')
  )
}

export function IconButton(props: {
  icon: LucideIcon
  label: string
  onClick: (e: MouseEvent<HTMLButtonElement>) => void
  destructive?: boolean
  disabled?: boolean
  className?: string
}) {
  const { icon: Icon, label, onClick, destructive, disabled, className } = props
  return (
    <button
      type="button"
      title={label}
      aria-label={label}
      disabled={disabled}
      onClick={onClick}
      className={iconButtonClass(destructive) + (className ?? '')}
    >
      <Icon size={14} aria-hidden />
    </button>
  )
}
```

- [ ] **Step 4: Create `src/ui/icons.tsx`**

```tsx
import {
  AlignJustify,
  CircleDot,
  Columns2,
  Group,
  Keyboard,
  OctagonX,
  Pencil,
  Play,
  Repeat,
  Split,
  SquareFunction,
  Timer,
  TriangleAlert,
  type LucideIcon,
} from 'lucide-react'
import type { BlockNode } from '../builder/tree'

/** Block-kind → Lucide icon (spec §3). One map feeds the canvas cards, the palette
 * chips and the record snapshot, so the same kind always wears the same mark.
 * for_each is null: ∀ has no Lucide equivalent and stays typographic (settled 6). */
export const BLOCK_ICONS: Record<BlockNode['kind'], LucideIcon | null> = {
  command: Play,
  measure: CircleDot,
  wait: Timer,
  operator_input: Keyboard,
  serial: AlignJustify,
  parallel: Columns2,
  loop: Repeat,
  branch: Split,
  compute: SquareFunction,
  record: Pencil,
  abort: OctagonX,
  alarm: TriangleAlert,
  for_each: null,
  group_ref: Group,
}

/** abort keeps its heavier red mark (audit settled-item 5); alarm stays amber. */
const KIND_COLOR: Partial<Record<BlockNode['kind'], string>> = {
  abort: 'text-red-600',
  alarm: 'text-amber-600',
}

export function KindIcon(props: { kind: BlockNode['kind']; className?: string }) {
  const { kind, className } = props
  const color = KIND_COLOR[kind] ?? 'text-slate-500'
  const cls = `shrink-0 ${color} ${className ?? ''}`
  const Icon = BLOCK_ICONS[kind]
  if (Icon === null) {
    return (
      <span aria-hidden className={cls}>
        ∀
      </span>
    )
  }
  return <Icon size={14} aria-hidden className={cls} />
}
```

- [ ] **Step 5: Create `webapp/frontend/CLAUDE.md`**

```markdown
# Experiment Studio frontend — project rules

## Icons

- Interactive icons come from **lucide-react** only (`src/ui/icons.tsx` maps block
  kinds; `src/ui/IconButton.tsx` is the only way to render an icon-only action —
  it enforces the ≥24×24px hit area, contrast, and title/aria-label).
- Brand marks, if ever needed, come from **Simple Icons** (https://simpleicons.org).
- **No raw glyph characters for interactive controls** (no ✕ ⧉ ✎ ▾ ↻ ⭳ buttons).
  Semantic notation stays typographic: `∀` (for_each), `R×N` retry marker, `⤳`
  tolerated-error marker, `×N` loop count, the `●` unsaved dot, ellipses, prose
  dashes.

## Text colors

- Meaning-carrying secondary text uses `text-caption` (slate-600); incidental
  placeholder/empty-state text uses `text-hint` (slate-500). Raw `text-slate-400`
  or lighter on text that carries meaning fails the audit's AA gate — don't
  reintroduce it (docs/ui-audit/2026-07-17.md, finding 1).

## Testing

- vitest runs in node env: pure functions only, no component rendering, no jsdom,
  no @testing-library. DOM wiring is verified by the UI-audit probe harness
  (docs/superpowers/plans/2026-07-17-experiment-studio-ui-audit.md, Task 2).
```

- [ ] **Step 6: Gates and commit**

Run: `cd webapp/frontend && npm run lint && npm run typecheck && npm test -- --run && npm run build`
Expected: all pass (nothing imports the new module yet).

```bash
git add webapp/frontend/package.json webapp/frontend/package-lock.json webapp/frontend/src/index.css webapp/frontend/src/ui webapp/frontend/CLAUDE.md
git commit -m "feat(studio): icon system foundation — lucide-react, IconButton, kind icons, text tokens"
```

---

### Task 2: De-glyph blockSummary; render KindIcon on cards, chips and snapshots

**Files:**
- Modify: `src/builder/summary.ts`
- Modify: `src/builder/summary.test.ts`
- Modify: `src/builder/__tests__/torture.test.ts` (only if it asserts glyph prefixes — check)
- Modify: `src/builder/Canvas.tsx:198`
- Modify: `src/builder/Palette.tsx:10-32,180,194,208,236`
- Modify: `src/records/WorkflowSnapshot.tsx:12-18`

**Interfaces:**
- Consumes: `KindIcon`, `BLOCK_ICONS` from `../ui/icons` (Task 1).
- Produces: `blockSummary(node): string` — same signature, but WITHOUT the leading glyph (e.g. `'feed_pump · stop R×3'`, `'Loop ×3'`, `'For each tube in [1, 2, 3]'`). `faultMarker` unchanged.

- [ ] **Step 1: Update `summary.test.ts` expectations first (TDD)**

In `src/builder/summary.test.ts`, strip the leading glyph and space from every expected string. Examples of the transformation (apply to ALL cases in the file):

```ts
// before → after
'▸ feed_pump · stop R×3'        → 'feed_pump · stop R×3'
'⏱ wait 1s ⤳'                   → 'wait 1s ⤳'
'◉ od_meter · measure → od R×2 ⤳' → 'od_meter · measure → od R×2 ⤳'
'↻ Loop ×3 R×2'                 → 'Loop ×3 R×2'
'ƒ ? = …'                       → '? = …'
'∀ For each tube in [1, 2, 3]'  → 'For each tube in [1, 2, 3]'
'⧉ wash'                        → 'wash'
```

Keep the mid-string notation intact: `→` in measure, `R×N`, `⤳`, `×N`, `∀`-less "For each" wording. `branch` becomes `If …`, `abort` → `Abort if …`, `alarm` → `Alarm if …`, `serial` → `Serial · N`, `parallel` → `Parallel · N lanes`.

- [ ] **Step 2: Run tests, verify they fail**

Run: `cd webapp/frontend && npx vitest run src/builder/summary.test.ts`
Expected: FAIL — actual strings still carry glyphs.

- [ ] **Step 3: Strip the glyph prefixes in `summary.ts`**

In `blockSummary` remove the leading glyph + space from every case (`▸ `, `◉ `, `⏱ `, `⌨ `, `≡ `, `∥ `, `↻ `, `⑂ `, `ƒ `, `✎ `, `⛔ `, `⚠ `, `∀ `, `⧉ `). The `branch` case becomes `` `If ${node.condition || '…'}${marker}` ``; keep everything else about each string identical. Update the file-top comment and the `faultMarker` doc-comment reference (`the Loop block already renders with ↻` → `the Loop card already renders a Repeat icon`).

- [ ] **Step 4: Run tests, verify they pass; check torture.test.ts**

Run: `cd webapp/frontend && npx vitest run src/builder`
Expected: summary tests PASS. If `__tests__/torture.test.ts` fails on glyph assertions, update those expectations the same way.

- [ ] **Step 5: Render KindIcon beside the summary**

`src/builder/Canvas.tsx` — in `BlockView`, line 198 area, add the icon before the summary span (Task 3 adds the `title`; leave it if you're doing this first):

```tsx
<KindIcon kind={node.kind} />
<span className="truncate">{blockSummary(node)}</span>
```

Import: `import { KindIcon } from '../ui/icons'`.

`src/records/WorkflowSnapshot.tsx` — in `NodeCard`, make the text row an icon+text flex:

```tsx
<p className="flex items-center gap-1 text-xs">
  <KindIcon kind={node.kind} />
  <span>
    {blockSummary(node)}
    {node.label !== null && <span className="ml-1 text-slate-400">“{node.label}”</span>}
    {timing && <span className="ml-1 text-[10px] text-slate-400">{timing}</span>}
  </span>
</p>
```

`src/builder/Palette.tsx` — delete the `icon: string` fields from `STRUCTURE`, `CONTROL`, `REPEAT` (keep `kind`/`title`) and render via the shared map so every chip wears the same mark as its card:

```tsx
// each chip body changes from
<span className="mr-1 opacity-60">{s.icon}</span>{s.title}
// to
<KindIcon kind={s.kind} className="mr-1" />{s.title}
```

For the verb chips at `Palette.tsx:236`, replace `{spec.kind === 'measure' ? '◉' : '▸'}` with:

```tsx
<KindIcon kind={spec.kind === 'measure' ? 'measure' : 'command'} className="mr-1" />
```

(Chip children render inside a flex-friendly `div`; add `flex items-center` to the Chip root className so icon and text align: `'flex cursor-grab select-none items-center rounded …'`.)

`src/builder/BuilderTab.tsx:50` (drag overlay label) needs no change — it renders the de-glyphed text.

- [ ] **Step 6: Gates and commit**

Run: `cd webapp/frontend && npm run lint && npm run typecheck && npm test -- --run && npm run build`
Expected: PASS.

```bash
git add webapp/frontend/src
git commit -m "feat(studio): block-kind Lucide icons on cards, chips and snapshots; de-glyph blockSummary"
```

---

### Task 3: Canvas — action IconButtons, captions, truncation titles, badge (F1-F4, F12)

**Files:**
- Modify: `src/builder/Canvas.tsx`
- Modify: `src/builder/DropSlot.tsx:25`

**Interfaces:**
- Consumes: `IconButton` from `../ui/IconButton`; `ChevronDown`, `ChevronRight`, `Copy`, `X`, `Plus` from `lucide-react`.

- [ ] **Step 1: Collapse toggle (F3 — the 5.7px control)**

In `BlockView` (`Canvas.tsx:187-197`), replace the `▸/▾` button with:

```tsx
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

- [ ] **Step 2: Summary/label titles (F4) and caption color (F1)**

Lines 198-199 become (icon from Task 2 stays first):

```tsx
<span title={blockSummary(node)} className="truncate">{blockSummary(node)}</span>
{node.label && (
  <span title={node.label} className="truncate text-xs italic text-caption">“{node.label}”</span>
)}
```

- [ ] **Step 3: Duplicate/Delete IconButtons (F2)**

Replace the two glyph buttons (`⧉` at :209-218, `✕` at :219-228) with:

```tsx
<IconButton
  icon={Copy}
  label="Duplicate"
  onClick={(e) => {
    e.stopPropagation()
    duplicateBlock(node.uid)
  }}
/>
<IconButton
  icon={X}
  label="Delete"
  destructive
  onClick={(e) => {
    e.stopPropagation()
    removeBlock(node.uid)
  }}
/>
```

- [ ] **Step 4: Badge (F12), collapsed hint, empty-canvas hint, ScopeSwitcher**

- Badge at :204: `bg-red-500` → `bg-red-600`. Keep `text-[10px] font-bold text-white`. (Task 12's probe verifies ≥4.5:1; if it reports red-600 short, darken to `bg-red-700` in the fix wave.)
- `…collapsed…` at :233: `text-slate-400` → `text-hint`.
- Empty-canvas hint at :45: `text-slate-400` → `text-hint`.
- ScopeSwitcher "Editing:" span at :85: `text-slate-500` → `text-caption`; the `cancel` button at :125 `text-slate-400 hover:text-slate-600` → `text-caption hover:text-slate-800`.
- `+ New group…` button at :131-137: replace the literal `+ ` with a `Plus` icon: `<Plus size={12} aria-hidden className="mr-0.5 inline" />New group…` and `text-slate-500` → `text-caption`.

- [ ] **Step 5: Lane/branch captions (F1) and lane/else remove buttons (F2)**

- `lane {i + 1}` caption row at :286: `text-slate-400` → `text-caption`.
- `then` / `else` captions at :329 and :345: `text-slate-400` → `text-caption`.
- The lane `✕` (:289-298) and else `✕` (:348-357) become IconButtons:

```tsx
<IconButton icon={X} label="Remove lane" destructive onClick={(e) => { e.stopPropagation(); removeBlock(lane.uid) }} />
```

```tsx
<IconButton icon={X} label="Remove else" destructive onClick={(e) => { e.stopPropagation(); patchBlock(node.uid, { else: null }) }} />
```

- `+ add else` (:334-341) and `+ lane` (:306-319): replace the literal `+` with `<Plus size={12} aria-hidden className="mr-0.5 inline" />` and `text-slate-400` → `text-caption` (the `+ lane` button is restructured further in Task 4 — if Task 4 already landed, only the color/icon change applies).

- [ ] **Step 6: DropSlot hint (F2 contrast share)**

`DropSlot.tsx:25`: non-highlight classes `'border-slate-200 text-slate-300'` → `'border-slate-300 text-hint'`.

- [ ] **Step 7: Gates and commit**

Run: `cd webapp/frontend && npm run lint && npm run typecheck && npm test -- --run && npm run build`
Expected: PASS.

```bash
git add webapp/frontend/src
git commit -m "fix(studio): canvas action targets, caption contrast, truncation titles (audit F1-F4, F12)"
```

---

### Task 4: Lane strip — kill the click-stealer (F11) + overflow affordance (settled-10)

This is a **reproduce-first** task (superpowers:systematic-debugging): the audit proved the defect behaviorally but not its CSS mechanism. Do not apply the candidate fix until you have reproduced the overlap and can name its cause.

**Files:**
- Modify: `src/builder/Canvas.tsx` (`ParallelLanes` :272-322, `BranchLanes` :324-366, `BlockView` root)
- Fixtures: `webapp/fixtures/ui-audit-torture.json` (read-only), devserver `webapp/backend/tests/devserver.py`

**Interfaces:**
- Consumes: the W5 UI-testing recipe (memory/plan): devserver + `npm run dev` + scratchpad playwright; seed docs via `POST /api/experiments`.

- [ ] **Step 1: Reproduce the audit's overlap**

Launch the devserver + Vite dev server. Seed the torture fixture. Script (scratchpad playwright, viewport **1280×800**) the audit's `inspector/loop` state: open the torture doc in the Builder, select the Loop block that sits beside/after a Parallel. At each of the Loop card's Duplicate/Delete icon centres run `document.elementFromPoint(x, y)`.
Expected reproduction: it returns the "+ lane" (Add lane) button, not the icon's own button. Record which ancestor overflows (walk `el.scrollWidth > el.clientWidth` up the chain) — the suspected mechanism is a flex child without `min-w-0` (branch arms at :328/:332 have `min-w-48 flex-1` but NO `min-w-0`, so a wide parallel inside an arm forces the arm past its container, and `BranchLanes` has NO overflow clip).

- [ ] **Step 2: Apply the containment fix**

Guided by Step 1's evidence, the candidate fix (adjust if the evidence disagrees, and say so in the ledger):

- `BranchLanes` root (:327): `"flex gap-2 px-2 pb-2"` → `"flex gap-2 overflow-x-auto px-2 pb-2"` — a too-wide arm now scrolls inside the branch card instead of painting past it. Keep the arms' `min-w-48 flex-1` exactly as they are (that min-width is the design floor; the *container* scrolling is what contains the overflow).
- `BlockView` root div (`Canvas.tsx:172-184`): add `min-w-0` to its className so a card inside a lane/arm can shrink to its flex container instead of forcing the container wide (flex `min-width:auto` is the usual culprit behind painted-over siblings).
- `ParallelLanes` strip (:277): `"flex items-stretch overflow-x-auto"` → `"flex items-stretch overflow-x-auto scroll-x-shadow"` (affordance, Task 1's utility).
- The "+ lane" button (:316): className gains `bg-white` and keeps `shrink-0` — after containment it cannot sit over a sibling; the opaque background is belt-and-braces.

- [ ] **Step 3: Behavioral proof (the audit's own acceptance)**

Re-run the Step 1 script. Expected:
1. `document.elementFromPoint` at each icon centre returns that icon's own `<button>`.
2. A scripted click on the Loop's Duplicate icon **duplicates the Loop subtree** (total block count grows by the subtree size), does NOT add an empty lane.
3. The parallel strip still scrolls horizontally at 1024×720 (8-lane torture state) and hidden lanes are reachable by scrolling.

Save the script to the scratchpad; paste its final assertions + output into the task ledger.

- [ ] **Step 4: Gates and commit**

Run: `cd webapp/frontend && npm run lint && npm run typecheck && npm test -- --run && npm run build`
Expected: PASS.

```bash
git add webapp/frontend/src
git commit -m "fix(studio): contain lane-strip overflow — '+ lane' no longer steals card-icon clicks (audit F11)"
```

---

### Task 5: Inspector — gap_after eligibility (F5), shared stream picker (F15), captions

**Files:**
- Modify: `src/builder/Inspector.tsx`
- Create: `src/builder/inspectorRules.ts`
- Create: `src/builder/inspectorRules.test.ts`
- Create: `src/builder/StreamIntoPicker.tsx`

**Interfaces:**
- Produces: `gapAfterEligible(kind: BlockNode['kind'], parentKind: BlockNode['kind'] | null): boolean`.
- Produces: `StreamIntoPicker` component — `{ value: string; onPick: (name: string) => void }`; renders the picker + inline "+ new stream…" mini-form over `useDocStore` streams.
- Engine facts (verified 2026-07-17): `expand.py:182-186` forbids `gap_after` only on the for_each block itself — its error says "put it on the body blocks"; `_expand_for_each` (`expand.py:195`) copies body blocks whole, so their `gap_after` survives splicing; `execute.py:451 execute_blocks` honors `gap_after` for serial, loop body, branch arms and group bodies. Parallel children have no "next in list", so `gap_after` stays hidden there.

- [ ] **Step 1: Write the failing test**

`src/builder/inspectorRules.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import { gapAfterEligible } from './inspectorRules'

describe('gapAfterEligible', () => {
  it('is true wherever the engine honors gap_after (execute.py:451 shared runner)', () => {
    expect(gapAfterEligible('wait', null)).toBe(true) // top level
    expect(gapAfterEligible('wait', 'serial')).toBe(true)
    expect(gapAfterEligible('abort', 'loop')).toBe(true) // audit F5: loop body child
    expect(gapAfterEligible('wait', 'branch')).toBe(true) // audit F5: then/else child
    expect(gapAfterEligible('wait', 'for_each')).toBe(true) // expand.py: "put it on the body blocks"
  })
  it('is false where the engine rejects or ignores it', () => {
    expect(gapAfterEligible('for_each', null)).toBe(false) // validate.py rejects on the block itself
    expect(gapAfterEligible('for_each', 'serial')).toBe(false)
    expect(gapAfterEligible('wait', 'parallel')).toBe(false) // lanes have no "next"
  })
})
```

- [ ] **Step 2: Run it, verify it fails**

Run: `cd webapp/frontend && npx vitest run src/builder/inspectorRules.test.ts`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Implement `src/builder/inspectorRules.ts`**

```ts
import type { BlockNode } from './tree'

/** Where the "Gap after" row shows (audit F5). The engine honors gap_after through the
 * one shared runner (execute.py:451) for serial, loop body, branch arms, group bodies —
 * and for for_each BODY children, whose keys survive splicing (expand.py:195; the
 * engine's own error for gap_after on the for_each block says "put it on the body
 * blocks"). It is meaningless only on a parallel child (no next-in-list), and rejected
 * on the for_each block itself (validate.py:117-120). */
export function gapAfterEligible(
  kind: BlockNode['kind'],
  parentKind: BlockNode['kind'] | null,
): boolean {
  return kind !== 'for_each' && parentKind !== 'parallel'
}
```

- [ ] **Step 4: Run tests, verify pass; wire into BlockForm**

`Inspector.tsx:131` becomes:

```ts
const showGapAfter = gapAfterEligible(node.kind, parentKind)
```

(import `gapAfterEligible`; keep `showStartOffset` exactly as is — the audit refuted changing it). Update the comment at :129-130 to point at `inspectorRules.ts`.

- [ ] **Step 5: Extract `StreamIntoPicker` (F15)**

Create `src/builder/StreamIntoPicker.tsx` by MOVING `IntoPicker`'s body out of `Inspector.tsx:387-449`, generalized to a controlled value/onPick pair and without the FieldRow wrapper:

```tsx
import { useState } from 'react'
import { useDocStore } from '../stores/docStore'

/** Picker over declared streams + inline "+ new stream…" creation (audit F15: one
 * affordance for Measure AND Record — record.into stays a picker, never free text,
 * per the W8-settled decision). */
export function StreamIntoPicker(props: { value: string; onPick: (name: string) => void }) {
  const { value, onPick } = props
  const streams = useDocStore((s) => s.streams)
  const addStream = useDocStore((s) => s.addStream)
  const [adding, setAdding] = useState(false)
  const [name, setName] = useState('')
  const [units, setUnits] = useState('')
  const [error, setError] = useState<string | null>(null)
  const names = Object.keys(streams)
  const create = () => {
    const err = addStream(name, units || null)
    setError(err)
    if (!err) {
      onPick(name)
      setAdding(false)
      setName('')
      setUnits('')
    }
  }
  return (
    <>
      <select
        value={adding ? '__new__' : value}
        onChange={(e) => {
          if (e.target.value === '__new__') setAdding(true)
          else {
            setAdding(false)
            onPick(e.target.value)
          }
        }}
        className="w-full rounded border border-slate-300 px-1 py-0.5 text-xs"
      >
        {value === '' && !adding && <option value="">— pick a stream —</option>}
        {names.map((n) => (
          <option key={n} value={n}>
            {n}
          </option>
        ))}
        <option value="__new__">+ new stream…</option>
      </select>
      {adding && (
        <div className="mt-1 flex items-center gap-1">
          <input
            value={name}
            placeholder="name"
            onChange={(e) => setName(e.target.value)}
            className="w-20 rounded border border-slate-300 px-1 py-0.5 font-mono text-xs"
          />
          <input
            value={units}
            placeholder="units"
            onChange={(e) => setUnits(e.target.value)}
            className="w-14 rounded border border-slate-300 px-1 py-0.5 text-xs"
          />
          <button onClick={create} className="rounded bg-slate-200 px-2 py-0.5 text-xs hover:bg-slate-300">
            Add
          </button>
        </div>
      )}
      {error && <p className="text-[10px] text-red-600">{error}</p>}
    </>
  )
}
```

In `Inspector.tsx`:
- `IntoPicker` (measure) becomes a thin wrapper — delete the old body:

```tsx
function IntoPicker({ node }: { node: MeasureNode }) {
  const patchBlock = useDocStore((s) => s.patchBlock)
  return (
    <FieldRow label="Into stream" required>
      <StreamIntoPicker value={node.into} onPick={(name) => patchBlock(node.uid, { into: name })} />
    </FieldRow>
  )
}
```

- `ValueForm`'s record branch (:746-764) becomes the same picker with the same label (the amber "No streams declared" hint is superseded by the inline creator — delete it):

```tsx
<FieldRow label="Into stream" required>
  <StreamIntoPicker value={node.into} onPick={(v) => patchBlock(node.uid, { into: v })} />
</FieldRow>
```

- [ ] **Step 6: Caption colors + small controls (F1 Inspector share)**

- Section header `Timing & label` (:137-139): `text-slate-400` → `text-caption`.
- `Params` h3 (:463) and `Args` h3 (:921): `text-slate-400` → `text-caption`.
- Serial/parallel body hints (:321, :323), DocProperties/GroupProperties/GroupRefForm/ForEachForm hint paragraphs (`:97-98`, `:115-119`, `:794-798`, `:871-874`, `:915-918`): `text-slate-400` → `text-caption`.
- Unknown-param remove `✕` (:480-486) → `<IconButton icon={X} label="Remove unknown param" destructive onClick={() => setParam(name, undefined)} />`.
- The bool `ƒ` expression-mode button (:526-533) → `<IconButton icon={SquareFunction} label="Use an expression" onClick={() => setExprMode(true)} className="border border-slate-300" />`.
- Locked-retry hint (:269-271): `text-slate-400` → `text-hint`.

- [ ] **Step 7: Gates and commit**

Run: `cd webapp/frontend && npm run lint && npm run typecheck && npm test -- --run && npm run build`
Expected: PASS, including the new inspectorRules tests.

```bash
git add webapp/frontend/src
git commit -m "fix(studio): gap_after authorable under loop/branch/for_each; shared Into-stream picker (audit F5, F15)"
```

---

### Task 6: Palette panels — AddRoleForm size (F13), per-row role errors (F18), streams filter (F10) + unused tag (F16)

**Files:**
- Modify: `src/builder/Palette.tsx`
- Modify: `src/builder/RolesPanel.tsx`
- Modify: `src/builder/StreamsPanel.tsx`
- Create: `src/builder/streamFilter.ts`
- Create: `src/builder/streamFilter.test.ts`

**Interfaces:**
- Produces: `filterStreamNames(names: string[], query: string): string[]` — case-insensitive substring, empty query returns all.

- [ ] **Step 1: Failing test for the stream filter**

`src/builder/streamFilter.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import { filterStreamNames } from './streamFilter'

describe('filterStreamNames', () => {
  const names = ['od_01', 'od_02', 'c_series', 'pump_rate']
  it('matches case-insensitive substrings', () => {
    expect(filterStreamNames(names, 'OD')).toEqual(['od_01', 'od_02'])
    expect(filterStreamNames(names, 'seri')).toEqual(['c_series'])
  })
  it('returns all for an empty/whitespace query', () => {
    expect(filterStreamNames(names, '')).toEqual(names)
    expect(filterStreamNames(names, '  ')).toEqual(names)
  })
  it('returns empty when nothing matches', () => {
    expect(filterStreamNames(names, 'zzz')).toEqual([])
  })
})
```

Run: `npx vitest run src/builder/streamFilter.test.ts` — Expected: FAIL (module missing).

- [ ] **Step 2: Implement `src/builder/streamFilter.ts`**

```ts
/** StreamsPanel filter (audit F10): a 30+ stream doc needs a way to narrow the flat
 * list. Same semantics as LoadDialog's search — case-insensitive substring. */
export function filterStreamNames(names: string[], query: string): string[] {
  const q = query.trim().toLowerCase()
  if (q === '') return names
  return names.filter((n) => n.toLowerCase().includes(q))
}
```

Run the test again — Expected: PASS.

- [ ] **Step 3: Wire the filter + unused tag + IconButton into StreamsPanel**

In `StreamsPanel.tsx`:
- Add state `const [query, setQuery] = useState('')` and render above the `ul` (inside the top-level `space-y-1` div):

```tsx
<input
  value={query}
  placeholder="filter streams…"
  onChange={(e) => setQuery(e.target.value)}
  className="w-full rounded border border-slate-300 px-2 py-1 text-xs"
/>
```

- List only the matches, keeping the full map shape: `{filterStreamNames(Object.keys(streams), query).map((name) => { const s = streams[name]; return (...) })}`. When `query` is non-empty and nothing matches render `<li className="text-xs text-hint">no streams match</li>`.
- **F16** — the source tag (:79-88): make `unused` distinct:

```tsx
className={
  'shrink-0 rounded px-1 text-xs ' +
  (sources[name] === undefined ? 'bg-amber-100 text-amber-700' : 'bg-slate-200 text-slate-600')
}
```

(note the neutral tag's text also darkens slate-500 → slate-600 for the F1 sweep).
- Delete `✕` (:95-101) → `<IconButton icon={X} label="Delete stream" destructive className="ml-auto" onClick={() => setError(removeStream(name))} />`.

- [ ] **Step 4: F13 — AddRoleForm control size**

`Palette.tsx:86-107` — bring the three controls to the chip standard:
- role-name input: `px-1 py-0.5` → `px-2 py-1`
- type select: `px-1 py-0.5` → `px-2 py-1`
- Add button: `px-2 py-0.5` → `px-2 py-1`

Also in `Palette.tsx`:
- Section toggle `−/+` span (:63) → `{open ? <ChevronDown size={14} aria-hidden /> : <ChevronRight size={14} aria-hidden />}` (imports from lucide-react).
- GroupsPanel delete `✕` (:151-157) → `<IconButton icon={X} label="Delete group" destructive className="ml-auto" onClick={() => setError(removeGroup(name))} />`; the `(params)` span (:148) `text-slate-400` → `text-caption`; empty-groups hint (:129) → `text-hint`; role line `· {def.type}` (:221) `text-slate-400` → `text-caption`.

- [ ] **Step 5: F18 — RolesPanel errors under the failing row**

Restructure the error state from `string | null` to `{ role: string; message: string } | null`:

```tsx
const [error, setError] = useState<{ role: string; message: string } | null>(null)

const commitRename = (from: string) => {
  const err = draft && draft !== from ? renameRole(from, draft) : null
  setError(err === null ? null : { role: from, message: err })
  if (!err) setEditing(null)
}
```

Each `li` becomes a column so the error can sit under its own row (keep `id`, the focus ring classes move to the inner row div):

```tsx
<li key={name} id={`role-${name}`} className="text-sm">
  <div
    className={
      'flex items-center gap-1 rounded ' +
      (focusedRole === name ? 'ring-2 ring-amber-400 bg-amber-50' : '')
    }
  >
    {/* existing rename-input / name-button, type span */}
    <IconButton
      icon={X}
      label="Delete role"
      destructive
      className="ml-auto"
      onClick={() => {
        const err = removeRole(name)
        setError(err === null ? null : { role: name, message: err })
      }}
    />
  </div>
  {error?.role === name && <p className="mt-0.5 text-xs text-red-600">{error.message}</p>}
</li>
```

Delete the old shared `{error && <li …>}` slot at :93. The `role.type` span (:83) `text-slate-400` → `text-caption`; the empty-roles hint (:35) → `text-hint`.

Mutation-check (manual, no component tests): with the fix reverted the error renders after the LAST row; with it, under the ACTING row — verify in the Task 12 probe pass or a quick dev-server click; note it in the ledger.

- [ ] **Step 6: Gates and commit**

Run: `cd webapp/frontend && npm run lint && npm run typecheck && npm test -- --run && npm run build`
Expected: PASS.

```bash
git add webapp/frontend/src
git commit -m "fix(studio): streams filter + unused tint, per-row role errors, palette control sizing (audit F10, F13, F16, F18)"
```

---

### Task 7: DevicesTab — error/discovery states (F6-F9, F23)

**Files:**
- Modify: `src/devices/DevicesTab.tsx`

**Interfaces:**
- Consumes: `IconButton`/`iconButtonClass` not needed here; `RefreshCw` from `lucide-react`.
- `useLabsStore` fields used: `labsError`, `selected`, `loadingLabs`, `discovering`, `devices`, `devicesError`, `refreshLabs()`, `refreshDevices()`.

- [ ] **Step 1: F7 — retry inside the roster error banner**

`:41-45` becomes:

```tsx
{s.labsError && (
  <p className="mb-2 rounded border border-red-200 bg-red-50 p-2 text-xs text-red-700">
    roster unreachable: {s.labsError}{' '}
    <button onClick={() => void s.refreshLabs()} className="underline">
      retry
    </button>
  </p>
)}
```

- [ ] **Step 2: F23 — labs refresh gets the same bordered affordance as Devices**

`:33-39` becomes (identical classes to the devices Refresh at :88-94, plus the icon):

```tsx
<button
  onClick={() => void s.refreshLabs()}
  disabled={s.loadingLabs}
  className="flex items-center gap-1 rounded border border-slate-300 bg-white px-2 py-1 text-xs hover:bg-slate-100 disabled:opacity-40"
>
  <RefreshCw size={12} aria-hidden />
  {s.loadingLabs ? 'Refreshing…' : 'Refresh'}
</button>
```

Give the devices Refresh (:88-94) the same icon+gap treatment so the two are visually identical.

- [ ] **Step 3: F9 — offline gets a label and a darker dot**

The dot span (:61-66): `bg-slate-300` → `bg-slate-500` for offline (emerald online unchanged; keep the `title`). After the host:port line, add a persistent label for offline labs — restructure the name block (:67-72):

```tsx
<span className="min-w-0 flex-1">
  <span className="flex items-center gap-1">
    <span className="min-w-0 truncate">{lab.name}</span>
    {!lab.online && (
      <span className="shrink-0 rounded bg-slate-200 px-1 text-[10px] uppercase text-slate-600">
        offline
      </span>
    )}
  </span>
  <span className="block truncate text-xs text-caption">
    {lab.host}:{lab.port}
  </span>
</span>
```

- [ ] **Step 4: F6 — the central panel acknowledges the roster failure**

`:79-82` becomes:

```tsx
{s.selected === null ? (
  s.labsError !== null ? (
    <p className="rounded border border-red-200 bg-red-50 p-8 text-center text-sm text-red-700">
      The lab roster is unreachable, so there are no labs to pick. Use the sidebar’s
      Refresh to retry once the connection is back.
    </p>
  ) : (
    <p className="rounded border border-dashed border-slate-300 bg-white p-8 text-center text-sm text-hint">
      Pick a lab to see its devices.
    </p>
  )
) : ( … )}
```

- [ ] **Step 5: F8 — rediscovery is visible beyond the button label**

Around the device table (`:113-160`), add an in-flight banner and dim the table:

```tsx
{s.discovering && (
  <p className="mb-2 rounded border border-blue-200 bg-blue-50 p-2 text-xs text-blue-700">
    Rediscovering devices — this takes a few seconds; the table below is the previous
    enumeration.
  </p>
)}
{s.devices !== null && (
  <div className={s.discovering ? 'pointer-events-none opacity-50' : ''}>
    <table …>…</table>
  </div>
)}
```

- [ ] **Step 6: caption sweep for this file**

`no labs in the roster` (:47) → `text-hint`; table header row (:116) `text-slate-400` → `text-caption`; `loading devices…` (:112) → `text-hint`; `no devices attached` (:128) → `text-hint`; port/connected `—` dashes (:137-141) `text-slate-400` → `text-caption`.

- [ ] **Step 7: Gates and commit**

Run: `cd webapp/frontend && npm run lint && npm run typecheck && npm test -- --run && npm run build`
Expected: PASS.

```bash
git add webapp/frontend/src
git commit -m "fix(studio): DevicesTab error/discovery affordances — central error copy, roster retry, dimmed rediscovery, offline labels (audit F6-F9, F23)"
```

---

### Task 8: Toolbar (F14), Preflight (F22), chart ticks (F17), EventLog caption

**Files:**
- Modify: `src/builder/Toolbar.tsx`
- Modify: `src/run/PreflightPanel.tsx`
- Modify: `src/run/preflight.ts` + its test file (`src/run/preflight.test.ts` — extend; check the actual name with `ls src/run/*.test.ts`)
- Modify: `src/records/format.ts`
- Create or extend: `src/records/format.test.ts`
- Modify: `src/charts/StreamChart.tsx:38`
- Modify: `src/run/EventLog.tsx:61`

**Interfaces:**
- Produces: `dedupeConsecutive(labels: string[]): string[]` in `src/records/format.ts`.
- Produces: `unmappedCount(rows: MappingRow[]): number` in `src/run/preflight.ts` (`MappingRow` is the existing row type returned by `buildMappingRows` — `selected: string | null` is the field that matters).

- [ ] **Step 1: Failing tests for the two pure functions**

`src/records/format.test.ts` (create if absent, else append):

```ts
import { describe, expect, it } from 'vitest'
import { dedupeConsecutive } from './format'

describe('dedupeConsecutive', () => {
  it('blanks repeated neighbours, keeps the first of each run (audit F17)', () => {
    expect(dedupeConsecutive(['0s', '0s', '0s', '1s', '1s', '2s'])).toEqual([
      '0s', '', '', '1s', '', '2s',
    ])
  })
  it('leaves already-unique labels alone', () => {
    expect(dedupeConsecutive(['0s', '5s', '10s'])).toEqual(['0s', '5s', '10s'])
  })
  it('handles empty input', () => {
    expect(dedupeConsecutive([])).toEqual([])
  })
})
```

In the preflight test file:

```ts
import { unmappedCount } from './preflight'

describe('unmappedCount', () => {
  it('counts rows without a device (audit F22)', () => {
    const rows = [
      { role: 'a', type: 't', options: [], selected: 'dev1' },
      { role: 'b', type: 't', options: [], selected: null },
      { role: 'c', type: 't', options: [], selected: null },
    ]
    expect(unmappedCount(rows as never)).toBe(2)
    expect(unmappedCount([] as never)).toBe(0)
  })
})
```

(Adapt the row literal to the real `MappingRow` shape in `src/run/preflight.ts` — add missing fields rather than casting if the type complains beyond `options`.)

Run: `npx vitest run src/records/format.test.ts src/run` — Expected: FAIL (functions missing).

- [ ] **Step 2: Implement both functions**

`src/records/format.ts` — append:

```ts
/** uPlot renders ~20 sub-second ticks on a young run's 0-2s domain; formatElapsed
 * floors them all to '0s'/'1s' (audit F17). Blank the repeats, keep the first. */
export function dedupeConsecutive(labels: string[]): string[] {
  return labels.map((l, i) => (i > 0 && labels[i - 1] === l ? '' : l))
}
```

`src/run/preflight.ts` — append (match the file's exported row type name):

```ts
/** How many roles still lack a device — shown beside the green check so "workflow
 * valid" can't read as "ready to start" while Start stays disabled (audit F22). */
export function unmappedCount(rows: MappingRow[]): number {
  return rows.filter((r) => r.selected === null).length
}
```

Run the tests again — Expected: PASS.

- [ ] **Step 3: Wire F17 into StreamChart**

`StreamChart.tsx:38`:

```ts
{ ...AXIS, values: (_u, ticks) => dedupeConsecutive(ticks.map((t) => formatElapsed(t))) },
```

(import `dedupeConsecutive` next to `formatElapsed`).

- [ ] **Step 4: Wire F22 into PreflightPanel**

`:172-175` becomes:

```tsx
<div className="text-xs">
  {validating && <span className="text-hint">validating…</span>}
  {clean && !validating && (
    <>
      <span className="inline-flex items-center gap-1 text-emerald-700">
        <Check size={14} aria-hidden /> workflow valid
      </span>
      {doc !== null && !mappingComplete(rows) && (
        <p className="mt-1 text-amber-700">
          {unmappedCount(rows)} role{unmappedCount(rows) === 1 ? '' : 's'} unmapped — Start
          stays disabled until every role has a device.
        </p>
      )}
    </>
  )}
</div>
```

(imports: `Check` from lucide-react; `unmappedCount` from `./preflight`.) Also the `Role mapping` header (:148) `text-slate-500` → `text-caption`; `this experiment defines no roles` (:149) → `text-hint`; row type span (:153) `text-slate-400` → `text-caption`; diagnostics path span (:181) `text-slate-400` → `text-caption`.

- [ ] **Step 5: F14 — Toolbar chip + dot; undo/redo icons**

`Toolbar.tsx`:
- ValidationChip (:33): `text-slate-500` → `text-slate-700`.
- Unsaved dot (:165): `text-amber-500` → `text-amber-600`.
- Undo/redo buttons (:178-183): replace `↶`/`↷` with `<Undo2 size={14} aria-hidden />` / `<Redo2 size={14} aria-hidden />`; add `aria-label="Undo"` / `aria-label="Redo"` (they keep `buttonClass` and their `title`s).

- [ ] **Step 6: EventLog timestamp caption (F1 share)**

`EventLog.tsx:61`: timestamp span `text-slate-400` → `text-caption`. Also the truncation note (:54) and `no events yet` (:58) → `text-hint`; the `[{block_id}]` suffix (:66) `text-slate-400` → `text-caption`.

- [ ] **Step 7: Gates and commit**

Run: `cd webapp/frontend && npm run lint && npm run typecheck && npm test -- --run && npm run build`
Expected: PASS.

```bash
git add webapp/frontend/src
git commit -m "fix(studio): toolbar/preflight state signals, chart tick dedupe, log caption contrast (audit F14, F17, F22 + F1 share)"
```

---

### Task 9: Records — table icons + titles (F2, F4), fatal error in red (F24)

**Files:**
- Modify: `src/records/RecordsTable.tsx`
- Modify: `src/records/RecordViewer.tsx`

**Interfaces:**
- Consumes: `IconButton`, `iconButtonClass` (Task 1); `ArrowLeft`, `Download`, `Pencil`, `X` from `lucide-react`.

- [ ] **Step 1: RecordsTable — NameCell (F4 preprod title + F2 icon)**

- Open button (:56): add `title={props.row.name}`.
- Rename `✎` (:59-70) → `<IconButton icon={Pencil} label="Rename record" onClick={() => { setDraft(props.row.name); setEditing(true); setError(null); cancelled.current = false }} />`.

- [ ] **Step 2: RecordsTable — row actions**

- Download `⬇` anchor (:122-128) →

```tsx
<a
  href={recordDownloadUrl(row.id)}
  title="Download zip"
  aria-label="Download zip"
  className={iconButtonClass() + 'mr-1'}
>
  <Download size={14} aria-hidden />
</a>
```

- Delete `✕` (:129-138) → `<IconButton icon={X} label="Delete record" destructive onClick={() => { if (!window.confirm(\`Delete record '${row.name}' and its artifacts?\`)) return; void remove(row.id).then(setRowError) }} />`.
- Wrap the two in a `<span className="inline-flex items-center justify-end gap-1">` inside the td so the 24px targets align.
- Caption sweep: `loading records…` (:93) and `refreshing…` (:144) → `text-hint`; header row (:102) stays slate-500 → `text-caption`.

- [ ] **Step 3: RecordViewer — split the report box (F24)**

Replace the single amber box (:82-101) with a red fatal box + an amber non-fatal box:

```tsx
{detail.report !== null && detail.report.error !== null && (
  <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-xs text-red-700">
    <p>error: {detail.report.error}</p>
  </div>
)}
{detail.report !== null &&
  (detail.report.finalize_errors.length > 0 ||
    detail.report.persistence_errors.length > 0 ||
    detail.report.diagnostics.length > 0) && (
  <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs text-amber-800">
    {detail.report.finalize_errors.map((e, i) => (
      <p key={`f${i}`}>finalize: {e}</p>
    ))}
    {detail.report.persistence_errors.map((e, i) => (
      <p key={`p${i}`}>persistence: {e}</p>
    ))}
    {detail.report.diagnostics.map((d, i) => (
      <p key={`d${i}`}>
        <span className="font-mono">{d.category} {d.path}</span> {d.message}
      </p>
    ))}
  </div>
)}
```

(The red family matches `RunView.tsx:103`'s live rendering and the `failed` StatusChip; tolerated_errors / alarms panels below stay amber — do not touch them.)

- [ ] **Step 4: RecordViewer — back link + captions + title**

- `← records` (:60-65) → `<button onClick={() => useRecordsStore.getState().open(null)} className="inline-flex items-center gap-1 text-xs text-slate-600 hover:underline"><ArrowLeft size={12} aria-hidden /> records</button>`.
- Record name `p.truncate` (:67): add `title={detail.name}`.
- Meta line (:68), `Workflow snapshot` header (:137), roles legend (:139-141): `text-slate-400`/`text-slate-500` → `text-caption`.
- `loading record…` (:41) → `text-hint`.

- [ ] **Step 5: WorkflowSnapshot leftovers**

In `WorkflowSnapshot.tsx`: `empty` (:49) `text-slate-300` → `text-hint`; label/timing spans (:16-17) `text-slate-400` → `text-caption`; `no workflow snapshot` (:61) → `text-hint`; branch `then`/`else` captions (:33, :38) → `text-caption`.

- [ ] **Step 6: Gates and commit**

Run: `cd webapp/frontend && npm run lint && npm run typecheck && npm test -- --run && npm run build`
Expected: PASS.

```bash
git add webapp/frontend/src
git commit -m "fix(studio): record table targets/titles, fatal error rendered red like the live view (audit F2, F4, F24)"
```

---

### Task 10: Dialogs — native `<dialog>` + sticky header (F19-F21, a11y e-i)

**Files:**
- Modify: `src/builder/LoadDialog.tsx`
- Modify: `src/run/InputDialog.tsx`

**Interfaces:**
- Consumes: `IconButton` (Task 1); `Download`, `Keyboard`, `Minus`, `X` from `lucide-react`.
- Platform notes: `dialog.showModal()` gives the focus trap, `aria-modal`, and Esc (a `cancel` event). Backdrop clicks arrive as a click whose `e.target === dialogElement`. `::backdrop` is styled via Tailwind's `backdrop:` variant. `<dialog>` has UA padding/border — reset with `p-0`.

- [ ] **Step 1: LoadDialog — dialog element + sticky structure (F21)**

Replace the outer two divs (:69-77 and the matching closers) with:

```tsx
export function LoadDialog(props: { onClose: () => void }) {
  const ref = useRef<HTMLDialogElement>(null)
  useEffect(() => {
    ref.current?.showModal()
  }, [])
  // …existing state/handlers unchanged…
  return (
    <dialog
      ref={ref}
      onClose={props.onClose}
      onClick={(e) => {
        if (e.target === e.currentTarget) props.onClose()
      }}
      className="m-auto w-[28rem] rounded-lg p-0 shadow-xl backdrop:bg-black/30"
    >
      <div className="flex max-h-[70vh] flex-col">
        <div className="shrink-0 p-4 pb-2">
          <div className="mb-2 flex items-center justify-between">
            <h2 className="text-sm font-semibold">Load experiment</h2>
            <IconButton icon={X} label="Close" onClick={props.onClose} />
          </div>
          <input
            autoFocus
            value={search}
            placeholder="search…"
            onChange={(e) => setSearch(e.target.value)}
            className="w-full rounded border border-slate-300 px-2 py-1 text-sm"
          />
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto px-4 pb-4">
          {/* error / loading / empty paragraphs and the ul, unchanged content */}
        </div>
      </div>
    </dialog>
  )
}
```

(`useRef` import; the header+search are a non-scrolling flex child, only the list region scrolls — F21. `dialog` is display:block when open; no flex-centering wrapper needed, `m-auto` centres it.)

- [ ] **Step 2: LoadDialog — row affordances (F19, F20) and icon actions**

- Open button (:97): `className="min-w-0 flex-1 rounded px-1 text-left hover:bg-slate-100"`.
- Name/description (:98-101): add `title={item.name}` and `title={item.description ?? 'no description'}`; description `text-slate-400` → `text-caption`.
- Export `⭳` (:103-109) → `<IconButton icon={Download} label="Export experiment as JSON" onClick={() => void exportItem(item)} />`.
- Delete `✕` (:110-116) → `<IconButton icon={X} label="Delete experiment" destructive onClick={() => void remove(item)} />`.
- `loading…`/`no experiments` paragraphs (:90-93): `text-slate-400` → `text-hint`.

- [ ] **Step 3: InputDialog — dialog element that resists Esc**

The run is parked on this input — it must NOT close on Esc/backdrop (the file's own header comment). Replace the overlay (:100-101 and closer):

```tsx
export function InputDialog() {
  const ref = useRef<HTMLDialogElement>(null)
  // …existing state…
  useEffect(() => {
    if (pending !== null && !hidden) ref.current?.showModal()
  }, [pending, hidden])
  // …
  return (
    <dialog
      ref={ref}
      onCancel={(e) => e.preventDefault()}
      className="m-auto w-96 rounded-lg p-4 shadow-xl backdrop:bg-black/30"
    >
      {/* existing inner content, minus the old wrapper divs */}
    </dialog>
  )
}
```

(`useEffect`/`useRef` imports. **Rules of hooks:** the new `useEffect` goes with the other hooks at the top, BEFORE the `pending === null`/banner-hidden early returns. Those early returns stay — when hidden, the dialog unmounts; unhiding remounts it and the effect calls `showModal()` again. `onCancel` + preventDefault blocks Esc.)

- Hide `—` button (:105-106) → `<IconButton icon={Minus} label="Hide (the run stays paused on this input)" onClick={() => setHidden(true)} />`.
- Banner `⌨` (:83) → `<Keyboard size={14} aria-hidden className="mr-1 inline" />`.
- min/max hint (:54) `text-slate-400` → `text-hint`.

- [ ] **Step 4: Browser sanity check**

Dev-server check (no component tests possible): open Load dialog — focus lands inside, Tab cycles within the dialog, Esc closes it, backdrop click closes it, long list scrolls under a fixed search box. Trigger an operator input (run `ui-audit-run.json` on FakeLab) — Esc does NOT close it, Hide collapses to the banner, the banner reopens it. Note results in the ledger.

- [ ] **Step 5: Gates and commit**

Run: `cd webapp/frontend && npm run lint && npm run typecheck && npm test -- --run && npm run build`
Expected: PASS.

```bash
git add webapp/frontend/src
git commit -m "feat(studio): native dialog semantics — focus trap, Esc, sticky search; load-row affordances (audit F19-F21, a11y)"
```

---

### Task 11: Glyph sweep + full gates

**Files:** repo-wide check, no planned edits (fix stragglers found).

- [ ] **Step 1: Sweep for banned glyph controls**

Run: `cd webapp/frontend && grep -rn --include='*.tsx' -E '>[[:space:]]*[⧉✕✎▾▸⭳↶↷⬇↻⑂⏱⌨≡∥◉⛔⚠−]|[⧉✕✎▾▸⭳↶↷⬇]' src | grep -v 'ui/icons\|summary\|CLAUDE'`
Expected: no interactive-control hits. Allowed survivors: `∀` (ui/icons.tsx), `R×N`/`⤳`/`×`/`→`/`←`-in-prose inside summary.ts strings and tests, `●` (Toolbar), `…` everywhere. Fix anything else by the Task-1 primitives (e.g. missed `✕` in a file this plan didn't list).

- [ ] **Step 2: Full gates, both stacks**

Run: `cd webapp/frontend && npm run lint && npm run typecheck && npm test -- --run && npm run build`
Run: `cd webapp/backend && .venv/bin/python -m pytest -q && .venv/bin/python -m mypy && .venv/bin/python -m ruff check .`
Expected: all green (backend untouched — this catches accidental cross-tree edits).

- [ ] **Step 3: Commit (only if stragglers were fixed)**

```bash
git add -A && git commit -m "fix(studio): glyph-control sweep stragglers"
```

---

### Task 12: Full probe re-run — 42 states × 3 viewports

**Files:**
- Harness: rebuild in the scratchpad from `docs/superpowers/plans/2026-07-17-experiment-studio-ui-audit.md` Task 2 code blocks (probe rules + state driver + capture loop). Do NOT commit the harness.
- Baseline: `docs/ui-audit/2026-07-17/probe.json.gz`.
- Output: write the fresh probe JSON + a comparison summary to the scratchpad; paste the verdict table into the PR description (Task 13).

**Interfaces / gate (spec §8):**
1. Every root-cause selector cited in findings 1-4, 12 measures clean: ≥4.5:1 normal text, ≥3:1 graphics, ≥24px both axes on the cited controls, truncating spans carry `title`.
2. The F11 scripted click (Task 4 Step 3's script) duplicates the subtree — re-run it against the final tree.
3. No NEW S2-class rows vs the baseline: any contrast<4.5 text row, <24px interactive row, or clip-confirmed overlap that has no counterpart in the baseline is a regression — fix it and re-run.
4. Harness updates required by this increment: dialogs are now `dialog[open]` (NOT `.fixed.inset-0`); icons are SVGs inside buttons (the target-size rule measures the `<button>`, not the `<svg>`); block cards still key off `.cursor-grab`.

- [ ] **Step 1: Rebuild the harness in the scratchpad; apply the two audit-proven rules (oklch pixel-readback contrast; clip-aware overlap with `elementFromPoint` confirmation) and the `dialog[open]` selector update.**
- [ ] **Step 2: Drive all 42 states × {1024×720, 1280×800, 1920×1080}; emit rows.**
- [ ] **Step 3: Evaluate the four gate lines above; write `probe-comparison.md` in the scratchpad (per-finding verdict: FIXED / STILL-FAILING / NEW-REGRESSION).**
- [ ] **Step 4: Fix wave for anything STILL-FAILING or NEW (e.g. `bg-red-600` badge still <4.5 → `bg-red-700`); re-run the affected states; commit fixes as `fix(studio): probe fix wave — <what>`.**
- [ ] **Step 5: When the gate holds, note the final row counts + verdicts in the ledger.**

---

### Task 13: PR

- [ ] **Step 1: Push and open the PR**

```bash
git push -u origin feat/experiment-studio-ui-fixes
gh pr create --title "feat(studio): UI-audit fixes — icons, contrast, targets, dialogs (W10)" --body "$(cat <<'EOF'
Write the body from: (a) a per-finding F1-F24 outcome list, (b) the Task 12 probe
verdict table (FIXED / STILL-FAILING / NEW-REGRESSION per finding, with row counts),
(c) the icon-system rule now recorded in webapp/frontend/CLAUDE.md, (d) a pointer to
the spec docs/superpowers/specs/2026-07-17-experiment-studio-ui-fixes-design.md.

🤖 Generated with [Claude Code](https://claude.com/claude-code)

https://claude.ai/code/session_01Dd1qymRAvMToVz6iQduH9j
EOF
)"
```

- [ ] **Step 2: CI green, merge (squash), confirm release-please picks it up as 0.8.0.**
