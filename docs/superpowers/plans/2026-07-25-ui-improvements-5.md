# UI Improvements 5 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land the three follow-up fixes raised in `docs/ui-improvements-4/comments.md` — even parallel-lane gutters with a centred, label-clearing separator (#5); an expression input whose painted box equals its typed-in box (#12); and `{binding}` autocomplete in expressions (#13) — plus a probe rule that makes the #12 defect class impossible to ship again.

**Architecture:** Three independent surfaces. (1) Canvas layout: the horizontal `DropSlot` stops being an invisible 12px spacer and *becomes* the lane gutter, carrying the separator hairline centred inside it; a new `src/builder/laneLayout.ts` owns the spacing tokens the way `ui/controls.ts` owns control metrics. (2) `ui/controls.ts` gains `block` on `textAreaClass()`, collapsing the line-box strut that made the highlight overlay paint ~4px taller than the textarea. (3) `builder/expr/complete.ts` masks `{holes}` before lexing and grows a hole-completion context, reusing `expr/holes.ts` from PR #80 — `tokenize.ts`/`parse.ts` stay untouched because the golden parity corpus pins them to the engine.

**Tech Stack:** React 19 + TypeScript + Tailwind 4 (Vite), vitest (node env, pure functions only), Playwright-driven capture/probe harness in `webapp/frontend/tools/`.

**Spec:** `docs/superpowers/specs/2026-07-25-ui-improvements-5-design.md`

## Global Constraints

- Worktree: `/Users/khamit/lab-devices-ui5`, branch `fix/ui-improvements-5`, based on `main` @ `825317d`. All paths below are relative to `webapp/frontend/` unless stated otherwise.
- `webapp/frontend/CLAUDE.md` rules are binding: control metrics live only in `ui/controls.ts`; helper classes **select** exactly one class per property and are never overridden by concatenation; Tailwind class names must be complete literals in source (no `` `mt-${n}` ``); no `dark:` variants (dark theme is a palette remap); colour stays in the state / construct-tint / role-swatch languages.
- vitest runs in **node env**: pure functions only. No component rendering, no jsdom, no @testing-library. DOM behaviour is verified by the capture probe.
- Never edit `src/builder/expr/tokenize.ts` or `src/builder/expr/parse.ts` — they are pinned to the engine by `expr/__goldens__` + `parity.test.ts`.
- Tailwind spacing unit = 4px (`mt-7` = 28px, `mb-1` = 4px, `w-2` = 8px, `w-4` = 16px, `mr-2` = 8px).
- Commit after every task. Conventional-commit prefixes (`fix(studio):`, `test(studio):`, `chore(studio):`); the repo uses release-please, so the PR title decides the release note.
- Every commit message ends with:
  ```
  Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_019FbbJvjeyTCoy4WY9E6X66
  ```

## Environment setup (do this once, before Task 1)

```bash
cd /Users/khamit/lab-devices-ui5/webapp/frontend && npm ci
```

The capture harness needs the **built SPA served by the backend on one origin** (a separate Vite dev server answering on a stale port is the classic trap — `capture.mjs:539` documents it). From the repo root:

```bash
cd /Users/khamit/lab-devices-ui5
python3 -m venv .venv && .venv/bin/pip install -q -e . -e "webapp/backend[dev]"
cd webapp/frontend && npm run build
cd /Users/khamit/lab-devices-ui5
STUDIO_STATIC_DIR=/Users/khamit/lab-devices-ui5/webapp/frontend/dist \
STUDIO_DATA_DIR=/private/tmp/claude-501/-Users-khamit-lab-devices/cadd74eb-eb42-4d0e-b70e-6f88438ca4a1/scratchpad/studio-data \
.venv/bin/uvicorn experiment_studio.app:create_app --factory --port 8000 &
```

Then `curl -s localhost:8000 | head -5` must return the built `index.html`. Capture runs as:

```bash
cd /Users/khamit/lab-devices-ui5/webapp/frontend
node tools/capture.mjs --url http://localhost:8000 --out /private/tmp/claude-501/-Users-khamit-lab-devices/cadd74eb-eb42-4d0e-b70e-6f88438ca4a1/scratchpad/shots
```

**Every capture must be preceded by `npm run build`** — the backend serves `dist/`, so an unbuilt change is invisible and the run reports clean states about code that is not there.

---

### Task 1: Probe rule R6 — `control-wrapper-gap`

The guard goes in first so the #12 fix has something that fails before and passes after.

**Files:**
- Modify: `tools/probe.mjs` (append a rule after R5, before `return out`)
- Modify: `tools/probe-selftest.html` (append plants/traps at the end of `<body>`)
- Modify: `tools/probe-selftest.mjs:25-31` (`expectedCounts`)

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: a violation record `{ rule: 'control-wrapper-gap', selector, detail }` emitted by `probeRules()`; Task 2 asserts it fires on the app pre-fix and is gone post-fix.

- [ ] **Step 1: Write the failing test — plant + traps in the selftest fixture**

Append to the end of `tools/probe-selftest.html`'s `<body>`:

```html
<!-- PLANT R6: a textarea left at its browser-default display:inline-block, alone in a BLOCK
     wrapper. An inline-level child sits on a line box, so the wrapper gains the parent font's
     descender space below the control and measures ~5px taller than the box you type in. That
     is PR #80's expression editor exactly: its highlight overlay is `absolute inset-0`, so the
     size it paints is the WRAPPER's, and the visible box stopped matching the active one. -->
<div style="font-size: 14px; line-height: 20px">
  <textarea style="display: inline-block; height: 24px; margin: 0; padding: 0; border: 0"></textarea>
</div>

<!-- TRAP R6a: the same wrapper with a BLOCK textarea — no line box, no strut, wrapper == control.
     This is the fixed shape; if it ever fires, the rule is measuring something other than the gap. -->
<div style="font-size: 14px; line-height: 20px">
  <textarea style="display: block; height: 24px; margin: 0; padding: 0; border: 0"></textarea>
</div>

<!-- TRAP R6b: a wrapper holding a label AND the control. The extra height is ordinary layout,
     not a strut, and the app's FieldRow (src/builder/fields.tsx) is built exactly this way — so
     without the sole-in-flow-child condition every field in the Inspector becomes a standing hit. -->
<div style="font-size: 14px; line-height: 20px">
  <span>label</span>
  <textarea style="display: inline-block; height: 24px; margin: 0; padding: 0; border: 0"></textarea>
</div>

<!-- TRAP R6c: a flex column that STRETCHES a short textarea (the Inspector's `fillParent`
     description field). The wrapper is legitimately far taller than the control and there is no
     line box in a flex formatting context, so a rule that ignored the parent's display would
     report a 76px "gap" that is not a defect. -->
<div style="display: flex; flex-direction: column; height: 100px">
  <textarea style="height: 24px; margin: 0; padding: 0; border: 0"></textarea>
</div>
```

Then add the rule's expected count to `tools/probe-selftest.mjs`'s `expectedCounts` object (keep the keys alphabetical as they are today):

```js
const expectedCounts = {
  'clipped-overflow': 1,
  'control-wrapper-gap': 1,
  'sibling-height-mismatch': 3,
  'text-contrast': 2,
  'tiny-target': 1,
  'truncate-without-title': 1,
}
```

- [ ] **Step 2: Run the selftest to verify it fails**

```bash
cd /Users/khamit/lab-devices-ui5/webapp/frontend && npm run probe:selftest
```

Expected: `FAIL — probe missed planted violations: control-wrapper-gap`.

If instead it reports a different rule over-firing, one of the new plants tripped an existing rule (most likely `tiny-target`, which only counts `BUTTON`, so this should not happen) — fix the fixture, not the counts.

- [ ] **Step 3: Implement the rule**

In `tools/probe.mjs`, immediately before the closing `return out` of `probeRules()`:

```js
  // R6 — a control's wrapper is taller than the control it wraps. PR #80's #12 shape: Tailwind's
  // preflight does not blockify form controls (it sets only `resize: vertical` on textarea), so a
  // textarea stays display:inline-block, and a BLOCK wrapper therefore puts it on a line box and
  // adds the parent font's descender space below it. Anything painted at the wrapper's size — the
  // expression editor's highlight overlay is `absolute inset-0` — then draws a box the control does
  // not have, and the box you see stops being the box you type in. R4 could not catch this: its
  // walker collects BUTTON/INPUT/SELECT only, and adding TEXTAREA there would flag every
  // legitimately multi-line editor sitting beside its 24px ƒ button.
  //
  // Two conditions keep it free of false positives:
  //   • the textarea must be its parent's ONLY in-flow child — an absolutely positioned sibling
  //     (that overlay) does not count, but a label or a second control means the extra height is
  //     ordinary layout (the app's FieldRow is span + control);
  //   • the parent must be a BLOCK container — the strut is a line-box artifact, and a flex/grid
  //     parent blockifies its children, so a stretched short textarea in a flex column (the
  //     Inspector's fillParent description) is not a defect and must not be reported as one.
  // An auto-grown textarea cannot trip it either: the wrapper grows with the control.
  for (const el of document.querySelectorAll('textarea')) {
    const parent = el.parentElement
    if (!parent) continue
    const ps = getComputedStyle(parent)
    if (ps.display !== 'block') continue
    const siblings = Array.from(parent.children).filter((c) => {
      if (c === el) return false
      const p = getComputedStyle(c).position
      return p !== 'absolute' && p !== 'fixed'
    })
    if (siblings.length > 0) continue
    const num = (v) => parseFloat(v) || 0
    const inner =
      parent.getBoundingClientRect().height -
      num(ps.paddingTop) - num(ps.paddingBottom) -
      num(ps.borderTopWidth) - num(ps.borderBottomWidth)
    const es = getComputedStyle(el)
    const outer = el.getBoundingClientRect().height + num(es.marginTop) + num(es.marginBottom)
    if (outer > 0 && inner - outer > 1) {
      out.push({
        rule: 'control-wrapper-gap',
        selector: cssPath(el),
        detail: `wrapper ${inner.toFixed(1)}px vs control ${outer.toFixed(1)}px`,
      })
    }
  }
```

- [ ] **Step 4: Run the selftest to verify it passes**

```bash
cd /Users/khamit/lab-devices-ui5/webapp/frontend && npm run probe:selftest
```

Expected: `PASS — probe found exactly the planted set: {"clipped-overflow":1,"control-wrapper-gap":1,...}`.
A count of 2+ for `control-wrapper-gap` means a trap is firing — do not adjust the count, fix the rule.

- [ ] **Step 5: Commit**

```bash
cd /Users/khamit/lab-devices-ui5
git add webapp/frontend/tools/probe.mjs webapp/frontend/tools/probe-selftest.html webapp/frontend/tools/probe-selftest.mjs
git commit -m "test(studio): probe rule for a wrapper taller than its control

R6 control-wrapper-gap flags a textarea whose sole-in-flow-child block wrapper
measures taller than the control — the inline-block line-box strut that made the
expression editor's absolute-inset-0 overlay paint a box 4px larger than the
input. One plant, three traps in the selftest fixture.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_019FbbJvjeyTCoy4WY9E6X66"
```

---

### Task 2: #12 — block-level textareas so the painted box equals the input

**Files:**
- Modify: `src/ui/controls.ts:68-74` (`textAreaClass`)
- Test: `src/ui/controls.test.ts` (add cases near the existing `textAreaClass` block, ~line 100-132)

**Interfaces:**
- Consumes: R6 from Task 1 (used as the app-level red/green gate).
- Produces: `textAreaClass()` output contains `block`; no signature change.

- [ ] **Step 1: Write the failing unit test**

Add to `src/ui/controls.test.ts` inside the same `describe` that holds the existing `textAreaClass` assertions:

```ts
  it('renders textareas block-level so their wrapper cannot outgrow them', () => {
    // A default (inline-block) textarea sits on a line box, so a block wrapper gains the parent
    // font's descender space below it — the expression editor's overlay is `absolute inset-0`
    // and painted that wrapper, showing a box 4px taller than the one you type in (#12 follow-up).
    expect(textAreaClass()).toContain('block')
    expect(textAreaClass({ mono: true, ghost: true })).toContain('block')
    // Inputs and selects are deliberately NOT blockified: they carry no overlay, and blockifying
    // them would change every row where one sits inline beside text.
    expect(controlClass().split(/\s+/)).not.toContain('block')
  })
```

- [ ] **Step 2: Run it to verify it fails**

```bash
cd /Users/khamit/lab-devices-ui5/webapp/frontend && npx vitest run src/ui/controls.test.ts
```

Expected: FAIL — `expected 'w-full py-0.5 rounded border …' to contain 'block'`.

- [ ] **Step 3: Implement**

In `src/ui/controls.ts`, change `textAreaClass`'s returned string and extend its docstring:

```ts
/** Textareas. Shares `controlSurfaceClass` with `controlClass` but deliberately carries no
 * `h-*` class: a textarea's height is driven by its content (see `autoGrow.ts`), never by
 * the fixed single-line token. `py-0.5` replaces the vertical space `CONTROL_H` would have
 * fixed. `fillParent` adds `max-h-full` so a flex parent can bound the growth instead.
 *
 * `block` is load-bearing, not cosmetic. Tailwind's preflight does not blockify form controls
 * (it sets only `resize: vertical` on textarea), so a textarea is inline-block by default and a
 * block wrapper puts it on a LINE BOX — adding the parent font's descender space, ~4px, below
 * it. The expression editor's highlight overlay is `absolute inset-0`, i.e. it paints the
 * WRAPPER, so that strut is what made the visible box taller than the box you type in once #12
 * raised the input to 24px. Block-level means the wrapper is exactly the control's height and
 * the two boxes agree by construction. Probe R6 (`control-wrapper-gap`) is the enforcement. */
export function textAreaClass(
  opts: { mono?: boolean; fillParent?: boolean; ghost?: boolean } = {},
): string {
  return (
    `block w-full py-0.5 ${controlSurfaceClass(opts)} ` + (opts.fillParent ? 'max-h-full' : '')
  ).trim()
}
```

- [ ] **Step 4: Run the unit tests to verify they pass**

```bash
cd /Users/khamit/lab-devices-ui5/webapp/frontend && npx vitest run src/ui/controls.test.ts
```

Expected: PASS, all cases in the file.

- [ ] **Step 5: Prove it on the real app (R6 red → green)**

The point of Task 1 is that this is measurable, not eyeballed. With the environment from the setup section running:

```bash
cd /Users/khamit/lab-devices-ui5/webapp/frontend
git stash                                  # back to the pre-fix build
npm run build
node tools/capture.mjs --url http://localhost:8000 --out /private/tmp/claude-501/-Users-khamit-lab-devices/cadd74eb-eb42-4d0e-b70e-6f88438ca4a1/scratchpad/shots-before
grep -c control-wrapper-gap /private/tmp/claude-501/-Users-khamit-lab-devices/cadd74eb-eb42-4d0e-b70e-6f88438ca4a1/scratchpad/shots-before/probe.json
git stash pop
npm run build
node tools/capture.mjs --url http://localhost:8000 --out /private/tmp/claude-501/-Users-khamit-lab-devices/cadd74eb-eb42-4d0e-b70e-6f88438ca4a1/scratchpad/shots-after
grep -c control-wrapper-gap /private/tmp/claude-501/-Users-khamit-lab-devices/cadd74eb-eb42-4d0e-b70e-6f88438ca4a1/scratchpad/shots-after/probe.json
```

Expected: the *before* count is > 0 (every state showing an expression editor — `expression-popover`, `group-scope-expression`, `inspector-*`) and the *after* count is 0. If *before* is 0, the rule is not reaching the real editors — go back to Task 1 rather than declaring #12 fixed. Record both numbers in the commit message.

Note the `after` run will still report other violations if Task 3 is not done yet; only the `control-wrapper-gap` count matters here.

- [ ] **Step 6: Commit**

```bash
cd /Users/khamit/lab-devices-ui5
git add webapp/frontend/src/ui/controls.ts webapp/frontend/src/ui/controls.test.ts
git commit -m "fix(studio): expression input's visible box matches its active box (#12)

Tailwind's preflight leaves textareas inline-block, so the editor's wrapper
carried a line-box strut and the absolute-inset-0 highlight overlay painted ~4px
taller than the 24px input. textAreaClass() is now block-level, which collapses
the wrapper onto the control everywhere. Probe R6: N hits before, 0 after.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_019FbbJvjeyTCoy4WY9E6X66"
```

(Replace `N` with the measured before-count.)

---

### Task 3: #5 — lane gutters, indentation and separators

**Files:**
- Create: `src/builder/laneLayout.ts`
- Create: `src/builder/laneLayout.test.ts`
- Modify: `src/builder/DropSlot.tsx` (whole component)
- Modify: `src/builder/Canvas.tsx` — `ContainerBody` (~line 391-395), `ParallelLanes` (398-444), `Lane` (474-480), `BranchLanes` (557-566)

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  - `laneLayout.ts` exports `LANE_PAD = 'py-1'`, `LANE_PAD_PX = 4`, `LANE_EDGE_W = 'w-2'`, `LANE_GUTTER_W = 'w-4'`, `LANE_DIVIDER_INSET = 'mt-7 mb-1'`, `LANE_DIVIDER_TOP_PX = 28`.
  - `DropSlot` gains an optional prop: `divider?: boolean`.

- [ ] **Step 1: Write the failing test for the spacing tokens**

Create `src/builder/laneLayout.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import { CONTROL_H_PX } from '../ui/controls'
import {
  LANE_DIVIDER_INSET,
  LANE_DIVIDER_TOP_PX,
  LANE_EDGE_W,
  LANE_GUTTER_W,
  LANE_PAD_PX,
} from './laneLayout'

/** Tailwind's spacing unit is 4px, so `mt-7` is 28px. Class names must be literals in source
 * (the scanner cannot see a template string), which is why the tokens are literals and this
 * test checks the arithmetic behind them instead of the other way round. */
const px = (cls: string): number => Number(cls.match(/-(\d+)$/)![1]) * 4

describe('lane layout tokens', () => {
  it('makes an inter-lane gutter exactly two edge insets wide', () => {
    // 8px of air on each side of every lane: where two lanes meet, their margins add up to the
    // gutter, and the hairline sits in the middle of it.
    expect(px(LANE_GUTTER_W)).toBe(2 * px(LANE_EDGE_W))
    expect(px(LANE_EDGE_W)).toBe(8)
  })

  it('starts the divider below the lane label row', () => {
    // The label row is one CONTROL_H tall and sits inside the lane's vertical padding, so the
    // hairline clears it by exactly that sum. If the control token ever moves, this fails and
    // the inset must move with it (comment #5: the line must not run into the tinted header).
    expect(LANE_DIVIDER_TOP_PX).toBe(LANE_PAD_PX + CONTROL_H_PX)
    const [top, bottom] = LANE_DIVIDER_INSET.split(' ')
    expect(px(top)).toBe(LANE_DIVIDER_TOP_PX)
    expect(px(bottom)).toBe(LANE_PAD_PX)
  })
})
```

- [ ] **Step 2: Run it to verify it fails**

```bash
cd /Users/khamit/lab-devices-ui5/webapp/frontend && npx vitest run src/builder/laneLayout.test.ts
```

Expected: FAIL — `Failed to resolve import "./laneLayout"`.

- [ ] **Step 3: Create the token module**

Create `src/builder/laneLayout.ts`:

```ts
/** The canvas's lane-spacing tokens (comment #5 on PR #80), the way `ui/controls.ts` owns
 * control metrics: one home, so the parallel lanes and the branch arms cannot drift apart.
 *
 * The rule: EVERY lane and arm is surrounded by 8px of air, and a container's inner content
 * therefore starts exactly 8px inside its card border whatever the construct. Before this,
 * three contributors stacked up — the body's `px-2`, a 12px horizontal DropSlot that was pure
 * invisible spacer, and the lane's own `p-1` — putting a parallel's first card 24px in, a
 * branch arm's 12px in and a loop's 8px in. The drop slots now ARE the gutters: 8px at the row's
 * edges, 16px between two lanes (two lanes' 8px of air), with the separator centred inside.
 *
 * Class names are literals because Tailwind 4 scans source text — a computed `w-${n}` compiles
 * to no CSS at all (CLAUDE.md). `laneLayout.test.ts` checks the arithmetic these literals stand
 * for, including their lockstep with CONTROL_H_PX. */

/** A lane's / arm's vertical padding. Horizontal padding is deliberately absent: the gutters
 * supply the horizontal air, and a second source of it is what broke the indentation. */
export const LANE_PAD = 'py-1'
export const LANE_PAD_PX = 4

/** The air on the outer edge of the lane row — one lane's worth. */
export const LANE_EDGE_W = 'w-2'

/** The gutter where two lanes meet: two edges' worth, hairline centred. */
export const LANE_GUTTER_W = 'w-4'

/** How far the separator clears the lane's label row (`LANE 1`, `then`, `else`), which is one
 * CONTROL_H tall inside LANE_PAD: the line covers the CARDS, not the labels, and so never runs
 * into the tinted construct header above it. Bottom inset matches the lane's own padding. */
export const LANE_DIVIDER_TOP_PX = 28
export const LANE_DIVIDER_INSET = 'mt-7 mb-1'
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
cd /Users/khamit/lab-devices-ui5/webapp/frontend && npx vitest run src/builder/laneLayout.test.ts
```

Expected: PASS (2 tests).

- [ ] **Step 5: Teach `DropSlot` to be a gutter**

Replace the non-hint return and extend the hint branch in `src/builder/DropSlot.tsx`:

```tsx
import { useDroppable } from '@dnd-kit/core'
import { useDocStore } from '../stores/docStore'
import { canDrop, type SlotRef } from './tree'
import { slotDroppableId, type DragPayload } from './dnd'
import { LANE_DIVIDER_INSET, LANE_EDGE_W, LANE_GUTTER_W } from './laneLayout'

/** Insertion bar between blocks (or a dashed hint box for empty lists). Highlights only
 * when the active drag may legally drop here — a container can never enter its own
 * subtree.
 *
 * A horizontal slot is also the parallel row's GUTTER (comment #5): it stopped being an
 * invisible 12px spacer sitting beside a separator and became the spacing itself —
 * `LANE_EDGE_W` at the row's edges, `LANE_GUTTER_W` between two lanes with the hairline
 * centred in it. That is what makes the separator evenly spaced: there is no longer a 12px
 * spacer on one side of it and nothing on the other. */
export function DropSlot(props: {
  at: SlotRef
  horizontal: boolean
  hint: boolean
  /** Draw the lane separator centred in this gutter, and widen it to hold two lanes' air. */
  divider?: boolean
}) {
  const { at, horizontal, hint, divider = false } = props
  const { setNodeRef, isOver, active } = useDroppable({ id: slotDroppableId(at) })
  const tree = useDocStore((s) => s.tree)
  const scope = useDocStore((s) => s.scope)
  const payload = (active?.data.current ?? null) as DragPayload | null
  const legal =
    payload !== null && (payload.source !== 'canvas' || canDrop(tree, payload.uid, at))
  const highlight = isOver && legal
  if (hint) {
    return (
      <div
        ref={setNodeRef}
        className={
          'flex-1 rounded border border-dashed px-2 py-3 text-center text-xs ' +
          // A horizontal hint is the empty state of a parallel's lane row, and that row's body
          // has no horizontal padding of its own any more (the gutters supply it) — so the hint
          // carries its own 8px of air. The vertical hint's padding still comes from the parent.
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
  return (
    <div
      ref={setNodeRef}
      className={
        (horizontal
          ? `self-stretch ${divider ? `flex justify-center ${LANE_GUTTER_W}` : LANE_EDGE_W} `
          : 'my-0.5 h-2 ') +
        'shrink-0 rounded transition-colors ' +
        (highlight ? 'bg-blue-400' : isOver ? 'bg-red-200' : 'bg-transparent')
      }
    >
      {divider && !highlight && (
        // Plain slate hairline, same token as the Toolbar's divider (#10, PR #80). Its margins —
        // not `self-stretch` — decide its extent, so it covers the lane's cards and clears the
        // label row above them.
        <span aria-hidden className={`w-px bg-slate-200 ${LANE_DIVIDER_INSET}`} />
      )}
    </div>
  )
}
```

- [ ] **Step 6: Rebuild the parallel row**

In `src/builder/Canvas.tsx`:

(a) import the tokens — add to the existing `./` imports near the top:

```tsx
import { LANE_DIVIDER_INSET, LANE_PAD } from './laneLayout'
```

(b) `ContainerBody`'s wrapper (currently `<div className={`rounded-b px-2 pb-2 ${fill}`}>`):

```tsx
  return (
    <DepthContext.Provider value={depth}>
      {/* A parallel supplies its own horizontal air through the lane gutters (laneLayout.ts):
          its edge drop slot IS the 8px inset, so a `px-2` here would stack a second one on top
          and push lane content deeper than every other construct's (comment #5). */}
      <div className={`rounded-b pb-2 ${node.kind === 'parallel' ? '' : 'px-2'} ${fill}`}>
        {body}
      </div>
    </DepthContext.Provider>
  )
```

(c) `ParallelLanes`'s returned JSX — replace everything from `<div className="flex items-stretch">` to the closing `</div>` (keeping the existing block comment above it):

```tsx
    <div className="flex items-stretch">
      {node.children.map((lane, i) => (
        <Fragment key={lane.uid}>
          {/* The gutter BEFORE lane i, and the row's only horizontal spacing: the leading one is
              the row's 8px edge inset, every later one is a 16px gutter carrying the centred
              hairline. Slot indices are unchanged — slot i still inserts before lane i. */}
          <DropSlot
            at={{ parentUid: node.uid, slot: 'children', index: i }}
            horizontal
            hint={false}
            divider={i > 0}
          />
          <Lane lane={lane} index={i} />
        </Fragment>
      ))}
      {node.children.length === 0 ? (
        <DropSlot at={{ parentUid: node.uid, slot: 'children', index: 0 }} horizontal hint />
      ) : (
        // The append slot doubles as the divider that gives "+ lane" its own compartment.
        <DropSlot
          at={{ parentUid: node.uid, slot: 'children', index: node.children.length }}
          horizontal
          hint={false}
          divider
        />
      )}
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
        // Its LEFT air comes from the divider gutter before it; `mr-2` gives the row the same
        // 8px right edge as the leading slot gives it on the left.
        className={inlineButtonClass({ subtle: true, stretch: true }) + ' my-1 mr-2'}
      >
        <Plus size={12} aria-hidden className="mr-0.5" />lane
      </button>
    </div>
```

- [ ] **Step 7: Drop the horizontal padding from lanes and arms**

Still in `Canvas.tsx`:

(a) `Lane`'s wrapper className — replace `'min-w-48 flex-initial rounded p-1 '` with:

```tsx
        // Horizontal padding would stack on top of the gutters and put this lane's cards deeper
        // than a loop's body (comment #5) — the gutters own the horizontal air now.
        `min-w-48 flex-initial rounded ${LANE_PAD} ` +
```

(b) both `BranchLanes` arms — replace `className="min-w-48 flex-initial p-1"` (two occurrences) with:

```tsx
      <div className={`min-w-48 flex-initial ${LANE_PAD}`}>
```

(c) the branch-arm hairline — replace `<span aria-hidden className="w-px self-stretch bg-slate-200" />` with:

```tsx
      {/* Same hairline and the same inset as a parallel's lane divider (laneLayout.ts), so a
          branch and a parallel at the same depth are spaced and divided identically. The row's
          `gap-2` already puts 8px on each side of it — the arms' own air. */}
      <span aria-hidden className={`w-px self-stretch bg-slate-200 ${LANE_DIVIDER_INSET}`} />
```

Also update the comment block above the first arm (currently mentioning `p-1`) to say the arms carry `LANE_PAD` and get their horizontal air from the row's `gap-2`.

- [ ] **Step 8: Typecheck, lint and unit tests**

```bash
cd /Users/khamit/lab-devices-ui5/webapp/frontend && npm run typecheck && npm run lint && npm run test
```

Expected: clean. (`Fragment` is already imported in Canvas.tsx; if the `i > 0` hairline removal left an unused import, oxlint will say so.)

- [ ] **Step 9: Measure the indentation on the real app**

Write `/private/tmp/claude-501/-Users-khamit-lab-devices/cadd74eb-eb42-4d0e-b70e-6f88438ca4a1/scratchpad/measure-insets.mjs` — it must live inside `webapp/frontend` for `import 'playwright'` to resolve, so copy it to `webapp/frontend/measure-insets.mjs`, run it, then delete it:

```js
import { chromium } from 'playwright'

const browser = await chromium.launch()
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
await page.goto('http://localhost:8000')
await page.getByRole('button', { name: 'Load', exact: true }).click()
await page.getByRole('button', { name: /morbidostat/ }).first().click()
await page.waitForTimeout(500)

const rows = await page.evaluate(() => {
  const out = []
  for (const card of document.querySelectorAll('[id^="block-"]')) {
    const body = card.querySelector(':scope > div.rounded-b')
    if (!body) continue
    const first = body.querySelector('[id^="block-"]')
    if (!first) continue
    out.push({
      card: card.id.slice(6, 14),
      dx: Math.round(first.getBoundingClientRect().left - card.getBoundingClientRect().left),
    })
  }
  return out
})
console.log(rows)
const bad = rows.filter((r) => r.dx !== 8)
console.log(bad.length === 0 ? 'PASS — every container indents its content by 8px' : `FAIL — ${JSON.stringify(bad)}`)
await browser.close()
```

```bash
cd /Users/khamit/lab-devices-ui5/webapp/frontend && npm run build && cp /private/tmp/.../measure-insets.mjs . && node measure-insets.mjs && rm measure-insets.mjs
```

Expected: `PASS — every container indents its content by 8px`. A parallel's row reports the *lane* as its first block (a lane is a `serial` block with its own `block-` id), which is exactly the measurement wanted: the lane starts 8px in, and its own cards start at its left edge because lanes no longer have horizontal padding.

If a container reports 12 or 24, the corresponding padding removal in Step 6/7 did not take effect — do not adjust the expected number.

- [ ] **Step 10: Capture and eyeball the separators**

```bash
cd /Users/khamit/lab-devices-ui5/webapp/frontend
node tools/capture.mjs --url http://localhost:8000 --out /private/tmp/claude-501/-Users-khamit-lab-devices/cadd74eb-eb42-4d0e-b70e-6f88438ca4a1/scratchpad/shots-lanes
```

Expected: 0 violations across all state/viewport combinations, both themes. Then open `shots-lanes/light-builder-morbidostat-1440x900.png` and `…-builder-torture-…png` and confirm: the hairline is centred between lanes, starts below the `LANE N` labels, and there is one hairline before `+ lane`.

- [ ] **Step 11: Commit**

```bash
cd /Users/khamit/lab-devices-ui5
git add webapp/frontend/src/builder/laneLayout.ts webapp/frontend/src/builder/laneLayout.test.ts webapp/frontend/src/builder/DropSlot.tsx webapp/frontend/src/builder/Canvas.tsx
git commit -m "fix(studio): even lane gutters and label-clearing separators (#5)

The horizontal DropSlot was 12px of invisible spacer sitting on ONE side of the
lane hairline, which both pushed a parallel's content 24px in (a loop's is 8px)
and left the separator 17px from one lane and 4px from the next. The slots are
now the gutters themselves — 8px at the row edges, 16px between lanes with the
hairline centred — and lanes and branch arms drop their horizontal padding, so
every construct indents its content by exactly 8px. The hairline starts below
the LANE/then/else label row instead of running into the tinted header, and
'+ lane' gets a divider of its own.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_019FbbJvjeyTCoy4WY9E6X66"
```

---

### Task 4: #13 — `{binding}` autocomplete

**Files:**
- Modify: `src/builder/expr/complete.ts` (whole file)
- Modify: `src/builder/expr/complete.test.ts` (add a `describe` block)
- Modify: `src/builder/expr/analyze.ts:74-78` (error message)
- Modify: `src/builder/expr/analyze.test.ts` (one case)

**Interfaces:**
- Consumes: `maskHoles` from `./holes` (PR #80).
- Produces: `Completion` gains `match: string`; `completionsAt` unchanged in signature; new exported `holeContextAt(text, caret)`.

- [ ] **Step 1: Write the failing tests**

Append to `src/builder/expr/complete.test.ts`:

```ts
// A group body references its own params and locals as {holes} (engine expand.py _HOLE_RE), and
// scopeRefs.ts already puts them in scope in that form. Only the completion path could not see
// them: it lexes with the parity-pinned tokenizer, which has no '{'.
const groupScope = { streams: ['od', '{feed}'], bindings: ['feed_ml', '{target_od}', '{tube}'] }

describe('completionsAt with {holes}', () => {
  it('offers every hole the moment { is typed', () => {
    const s = completionsAt('{', 1, groupScope)
    expect(labels(s)).toEqual(['{feed}', '{target_od}', '{tube}'])
    expect(s?.replace).toEqual({ start: 0, end: 1 })
    expect(s?.items[0]).toMatchObject({ insert: '{feed}', caretBack: 0 })
  })

  it('filters holes on the inner name and keeps the braces in the replacement', () => {
    const s = completionsAt('{t', 2, groupScope)
    expect(labels(s)).toEqual(['{target_od}', '{tube}'])
    expect(s?.replace).toEqual({ start: 0, end: 2 })
  })

  it('replaces a whole complete hole when the caret sits inside one', () => {
    // `{tu|be}` — accepting must not nest a second brace pair inside the first.
    const s = completionsAt('{tube} > 1', 3, groupScope)
    expect(labels(s)).toEqual(['{tube}'])
    expect(s?.replace).toEqual({ start: 0, end: 6 })
  })

  it('says nothing right after a finished hole', () => {
    expect(completionsAt('{tube}', 6, groupScope)).toBeNull()
  })

  it('still completes AFTER a hole earlier in the line', () => {
    // The regression that made the whole surface feel dead: an unmasked '{' lexes as an error,
    // and context() bails for every caret position after it.
    const s = completionsAt('{target_od} - me', 16, groupScope)
    expect(labels(s)).toEqual(['mean'])
    expect(s?.replace).toEqual({ start: 14, end: 16 })
  })

  it('reaches a hole from a bare prefix, braces and all', () => {
    const s = completionsAt('tu', 2, groupScope)
    expect(labels(s)).toEqual(['{tube}'])
    expect(s?.items[0]).toMatchObject({ insert: '{tube}' })
    expect(s?.replace).toEqual({ start: 0, end: 2 })
  })

  it('offers hole streams as a stat-call argument', () => {
    expect(labels(completionsAt('mean(f', 6, groupScope))).toEqual(['{feed}'])
  })

  it('offers nothing for { at the workflow scope, where holes are not syntax', () => {
    expect(completionsAt('{', 1, scope)).toBeNull()
  })
})
```

And append to `src/builder/expr/analyze.test.ts` (inside the existing top-level `describe`):

```ts
  it('names an unfinished hole instead of quoting the raw character', () => {
    // What the user stares at for the 300ms between typing `{od` and typing `}`.
    const [p] = analyzeExpression('{budge', 'any', { streams: [], bindings: ['{budget}'] })
    expect(p.message).toBe("unfinished {binding} — add the closing '}'")
    expect(p.pos).toBe(0)
  })
```

- [ ] **Step 2: Run them to verify they fail**

```bash
cd /Users/khamit/lab-devices-ui5/webapp/frontend && npx vitest run src/builder/expr/complete.test.ts src/builder/expr/analyze.test.ts
```

Expected: the eight new completion cases fail (`expected null to be …` for most), and the analyze case fails with `expected "unexpected character '{'" to be "unfinished {binding} …"`.

- [ ] **Step 3: Implement the completion changes**

Rewrite `src/builder/expr/complete.ts` as follows (unchanged parts kept verbatim):

```ts
/** Caret-context autocomplete (spec §3.6): four contexts — a {hole} reference, atom position,
 * stat-call first argument, and the window slot after the comma. Pure so vitest can cover it;
 * the popup DOM is probe territory. */
import type { ExprScope } from './analyze'
import { maskHoles } from './holes'
import { STAT_FNS, tokenize, type Token } from './tokenize'

export interface Completion {
  label: string
  kind: 'fn' | 'stream' | 'binding' | 'keyword' | 'window'
  insert: string
  caretBack: number
  /** What a typed prefix is matched against — the label, except for a {hole}, where it is the
   * inner name so typing `tu` reaches `{tube}` without the user knowing the brace syntax. */
  match: string
}

export interface CompletionSet {
  items: Completion[]
  replace: { start: number; end: number }
}

const STAT_FN_SET = new Set<string>(STAT_FNS)
const ATOM_LEAD_OPS = new Set(['(', '+', '-', '*', '/', '<', '<=', '>', '>=', '==', '!=', '='])
const ATOM_LEAD_NAMES = new Set(['and', 'or', 'not'])
const IDENT_CHAR = /[A-Za-z0-9_]/

const isHole = (name: string): boolean => name.startsWith('{') && name.endsWith('}')
const inner = (name: string): string => (isHole(name) ? name.slice(1, -1) : name)

/** Tokens strictly before the caret, and the NAME token the caret touches (pos < caret
 * <= end), if any. Returns null when a lex error precedes the caret or the caret sits
 * inside a non-NAME token.
 *
 * {holes} are masked before lexing (holes.ts, PR #80): they are group-body syntax the
 * parity-pinned tokenizer cannot lex, and an unmasked one is a lex error that kills completions
 * for every caret position after it. The mask is equal-length by construction, so every token
 * `pos` below still indexes the ORIGINAL text and the replace spans stay valid. */
function context(text: string, caret: number): { prev: Token[]; partial: Token | null } | null {
  const { tokens, error } = tokenize(maskHoles(text).masked)
  if (error && error.pos < caret) return null
  const before = tokens.filter((t) => t.kind !== 'END' && t.pos < caret)
  const last = before[before.length - 1]
  if (last && last.kind === 'NAME' && caret <= last.pos + last.text.length) {
    return { prev: before.slice(0, -1), partial: last }
  }
  if (last && caret < last.pos + last.text.length) return null
  return { prev: before, partial: null }
}

/** The caret sits in a `{name` reference: scanning back over identifier characters reaches a `{`.
 * `end` swallows the closing brace when the hole is already complete, so accepting a completion
 * replaces `{tube}` rather than nesting a second pair of braces inside it. */
export function holeContextAt(
  text: string,
  caret: number,
): { start: number; end: number; prefix: string } | null {
  let i = caret
  while (i > 0 && IDENT_CHAR.test(text[i - 1])) i -= 1
  if (i === 0 || text[i - 1] !== '{') return null
  const tail = /^[A-Za-z0-9_]*\}/.exec(text.slice(caret))
  return { start: i - 1, end: caret + (tail ? tail[0].length : 0), prefix: text.slice(i, caret) }
}

function holePool(scope: ExprScope): Completion[] {
  const mk = (name: string, kind: 'stream' | 'binding'): Completion => ({
    label: name,
    kind,
    insert: name,
    caretBack: 0,
    match: inner(name),
  })
  return [
    ...scope.streams.filter(isHole).map((s) => mk(s, 'stream')),
    ...scope.bindings.filter(isHole).map((b) => mk(b, 'binding')),
  ]
}

/** Is the caret inside the argument parens of a stat call? Scans for an unmatched '('
 * whose preceding token is a stat-function name. */
export function insideStatCallArgs(text: string, caret: number): boolean {
  const ctx = context(text, caret)
  if (!ctx) return false
  const prev = ctx.prev
  let depth = 0
  for (let i = prev.length - 1; i >= 0; i--) {
    const t = prev[i]
    if (t.kind !== 'OP') continue
    if (t.text === ')') depth += 1
    else if (t.text === '(') {
      if (depth === 0) {
        const before = prev[i - 1]
        return before?.kind === 'NAME' && STAT_FN_SET.has(before.text)
      }
      depth -= 1
    }
  }
  return false
}

export function completionsAt(
  text: string,
  caret: number,
  scope: ExprScope,
  force = false,
): CompletionSet | null {
  // A `{` is an explicit trigger — the hole list opens on the brace alone, with no prefix and no
  // Ctrl+Space, because there is nothing else `{` can start. At the workflow scope no hole-form
  // names exist, so this yields nothing and `{` stays inert, which is correct: holes are
  // group-body syntax.
  const hc = holeContextAt(text, caret)
  if (hc) {
    const items = holePool(scope).filter((i) => i.match.startsWith(hc.prefix))
    return items.length === 0 ? null : { items, replace: { start: hc.start, end: hc.end } }
  }
  // Just past a finished `{tube}` there is nothing left to complete, and the masked NAME token
  // would otherwise offer the very hole the user just closed.
  if (caret > 0 && text[caret - 1] === '}') return null

  const ctx = context(text, caret)
  if (!ctx) return null
  const { prev, partial } = ctx
  const prefix = partial ? text.slice(partial.pos, caret) : ''
  if (!force && prefix === '') return null
  const last = prev[prev.length - 1]
  const beforeLast = prev[prev.length - 2]
  const streamItem = (s: string): Completion => ({
    label: s,
    kind: 'stream',
    insert: s,
    caretBack: 0,
    match: inner(s),
  })

  let pool: Completion[]
  if (
    last?.kind === 'OP' &&
    last.text === '(' &&
    beforeLast?.kind === 'NAME' &&
    STAT_FN_SET.has(beforeLast.text)
  ) {
    pool = scope.streams.map(streamItem)
  } else if (last?.kind === 'OP' && last.text === ',' && insideStatCallArgs(text, last.pos)) {
    pool = [{ label: 'last=', kind: 'window', insert: 'last=', caretBack: 0, match: 'last=' }]
  } else if (
    last === undefined ||
    (last.kind === 'OP' && ATOM_LEAD_OPS.has(last.text)) ||
    (last.kind === 'NAME' && ATOM_LEAD_NAMES.has(last.text))
  ) {
    pool = [
      ...STAT_FNS.map((f) => ({
        label: f,
        kind: 'fn' as const,
        insert: `${f}()`,
        caretBack: 1,
        match: f,
      })),
      ...scope.streams.map(streamItem),
      ...scope.bindings.map((b) => ({
        label: b,
        kind: 'binding' as const,
        insert: b,
        caretBack: 0,
        match: inner(b),
      })),
      { label: 'not', kind: 'keyword' as const, insert: 'not', caretBack: 0, match: 'not' },
    ]
  } else {
    return null
  }

  // Matched on `match`, not `label`: a bare `tu` must reach `{tube}` (comment #13).
  const items = pool.filter((i) => i.match.startsWith(prefix))
  if (items.length === 0) return null
  const replace = partial
    ? { start: partial.pos, end: partial.pos + partial.text.length }
    : { start: caret, end: caret }
  return { items, replace }
}
```

- [ ] **Step 4: Implement the analyze message**

In `src/builder/expr/analyze.ts`, replace the `if (!result.ok)` block:

```ts
  if (!result.ok) {
    const { message, pos, atEnd } = result.error
    // `{` has no role in the grammar except as a group-body hole, so a lex error landing on one
    // is always an unfinished reference. Say that instead of quoting the character: this is what
    // the user reads for the 300ms between typing `{od` and typing `}` (comment #13).
    const friendly = text[pos] === '{' ? "unfinished {binding} — add the closing '}'" : message
    return [{ message: friendly, pos, len: atEnd ? 0 : 1 }]
  }
```

- [ ] **Step 5: Run the expression suites to verify they pass**

```bash
cd /Users/khamit/lab-devices-ui5/webapp/frontend && npx vitest run src/builder/expr/
```

Expected: PASS, including `parity.test.ts` and the golden corpus (untouched tokenizer/parser).

- [ ] **Step 6: Verify in the running Builder**

Rebuild and drive it (the popup is DOM wiring, so vitest cannot see it):

```bash
cd /Users/khamit/lab-devices-ui5/webapp/frontend && npm run build
```

Then with the backend serving the new `dist`, in a browser at `http://localhost:8000`: load `examples/morbidostat.json`, enter a group scope with params (`Groups` → the group with params → its body), select a block with a value/guard slot, and in the expression field check all four:
1. typing `{` opens the popup listing the group's holes;
2. typing `{t` filters it, and Enter inserts `{target_od}` with no leftover brace;
3. typing a bare `tu` offers `{tube}`;
4. after `{target_od} - me` the popup still offers `mean` — and no amber problem is shown once the hole is closed.

- [ ] **Step 7: Commit**

```bash
cd /Users/khamit/lab-devices-ui5
git add webapp/frontend/src/builder/expr/complete.ts webapp/frontend/src/builder/expr/complete.test.ts webapp/frontend/src/builder/expr/analyze.ts webapp/frontend/src/builder/expr/analyze.test.ts
git commit -m "fix(studio): autocomplete {bindings} in expressions (#13)

complete.ts lexed the raw draft with the parity-pinned tokenizer, so a '{' was a
lex error: the popup never opened on a hole, and a completed {od} earlier in the
line killed completions for everything after it. It now masks holes before
lexing (holes.ts, PR #80), opens the full hole list on '{' alone, replaces a
complete hole rather than nesting braces, and matches hole entries on their
inner name so a bare 'tu' reaches {tube}. An unfinished hole now reads
'unfinished {binding}' instead of quoting the character. tokenize/parse
untouched — engine parity stays pinned.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_019FbbJvjeyTCoy4WY9E6X66"
```

---

### Task 5: Full verification, PR, CI, merge

**Files:**
- Modify: `docs/ui-improvements-4/comments.md` (append the resolution of each item)

**Interfaces:**
- Consumes: everything above.
- Produces: a merged PR.

- [ ] **Step 1: Run the whole frontend gate**

```bash
cd /Users/khamit/lab-devices-ui5/webapp/frontend
npm run typecheck && npm run lint && npm run test && npm run probe:selftest && npm run build
```

Expected: all clean.

- [ ] **Step 2: Full capture, both themes**

```bash
cd /Users/khamit/lab-devices-ui5/webapp/frontend
node tools/capture.mjs --url http://localhost:8000 --out /private/tmp/claude-501/-Users-khamit-lab-devices/cadd74eb-eb42-4d0e-b70e-6f88438ca4a1/scratchpad/shots-final
```

Expected: `0 violation(s) across N state/viewport combinations`. Any `control-wrapper-gap` hit here is a #12 regression; any `sibling-height-mismatch` is a lane-padding mistake from Task 3.

- [ ] **Step 3: Record the outcome in the feedback doc**

Append to `docs/ui-improvements-4/comments.md`:

```markdown
---

## Resolution (PR #NN, UI improvements 5)

- **#5** — the horizontal `DropSlot` was 12px of invisible spacer on one side of the
  hairline. Drop slots are now the gutters themselves (8px at the row edges, 16px
  between lanes, hairline centred), and lanes and branch arms dropped their
  horizontal padding: every construct now indents its content by exactly 8px,
  measured. The separator starts below the `LANE N` / `then` / `else` label row and
  `+ lane` has a divider of its own.
- **#12** — the painted box was the *wrapper*, which carried an inline-block line-box
  strut ~4px taller than the 24px input. `textAreaClass()` is block-level now, so
  wrapper and control are the same box; probe rule R6 `control-wrapper-gap` keeps it
  that way.
- **#13** — the completion path lexed raw text, so `{` was a lex error. It masks holes
  now, opens the hole list on `{`, and matches holes on their inner name, so a bare
  `tu` also reaches `{tube}`.
```

Replace `#NN` with the real PR number once it exists.

- [ ] **Step 4: Open the PR**

```bash
cd /Users/khamit/lab-devices-ui5
git add docs/ui-improvements-4/comments.md && git commit -m "docs(studio): record UI improvements 5 resolutions

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_019FbbJvjeyTCoy4WY9E6X66"
git push -u origin fix/ui-improvements-5
gh pr create --title "fix(studio): UI improvements 5 — lane gutters, expression box, binding autocomplete" --body "$(cat <<'EOF'
Follow-ups on the three PR #80 fixes the user re-opened in `docs/ui-improvements-4/comments.md`.

**#5 — parallel lane spacers.** The horizontal `DropSlot` was 12px of invisible layout width sitting on *one* side of the lane hairline, and there was one on each outer edge too: a parallel's first card sat 24px inside its card border where a loop's sits at 8px, and the separator was 17px from the lane on its left and 4px from the one on its right. The drop slots are now the gutters themselves — `w-2` at the row's edges, `w-4` between two lanes with the hairline centred inside — and lanes and branch arms drop their horizontal padding. Every construct now indents its content by exactly 8px (measured with Playwright, not eyeballed). The separator starts below the `LANE N` / `then` / `else` label row instead of running into the tinted header, and `+ lane` gets a divider of its own. New `src/builder/laneLayout.ts` owns these tokens the way `ui/controls.ts` owns control metrics.

**#12 — visible box vs. active box.** Tailwind's preflight does not blockify form controls, so a textarea is `inline-block` and a block wrapper puts it on a line box, adding ~4px of descender space below it. The expression editor's highlight overlay is `absolute inset-0`, so what it painted was the *wrapper*. Raising the input to 24px in #80 turned that hidden 4px into a visible oversized box. `textAreaClass()` is block-level now: wrapper == control == 24px.

**#13 — binding autocomplete.** `complete.ts` lexed the raw draft with the parity-pinned tokenizer, so `{` was a lex error and the popup never opened — and a completed `{od}` earlier in the line killed completions for everything after it. It now masks holes first (`expr/holes.ts` from #80), opens the full hole list on `{` alone, replaces a complete hole instead of nesting braces, and matches hole entries on their inner name so a bare `tu` reaches `{tube}`. `tokenize.ts`/`parse.ts` untouched — engine parity stays pinned by the golden corpus.

**Guard.** New probe rule R6 `control-wrapper-gap` flags a textarea whose sole-in-flow-child block wrapper measures taller than the control. Written before the #12 fix and observed failing on the pre-fix build; one plant and three traps in the probe selftest.

Spec: `docs/superpowers/specs/2026-07-25-ui-improvements-5-design.md`
Plan: `docs/superpowers/plans/2026-07-25-ui-improvements-5.md`

Verification: `npm run typecheck && lint && test && probe:selftest && build` clean; capture harness reports 0 violations across every state/viewport in both themes.

🤖 Generated with [Claude Code](https://claude.com/claude-code)

https://claude.ai/code/session_019FbbJvjeyTCoy4WY9E6X66
EOF
)"
```

- [ ] **Step 5: Poll CI to green, then merge**

```bash
gh pr checks --watch
gh pr merge --squash --delete-branch
```

If a check fails, fix it on the branch and push — do not merge red.

- [ ] **Step 6: Clean up the worktree**

```bash
cd /Users/khamit/lab-devices && git pull && git worktree remove ../lab-devices-ui5
```

---

## Self-review

**Spec coverage.** #5's three contributors (body padding, drop-slot width, lane padding) → Task 3 Steps 5-7; the divider extent + `+ lane` divider → Task 3 Steps 5-7; the empty-parallel hint edge case → Task 3 Step 5. #12 root cause and one-line fix → Task 2. #13's four changes (mask, hole context, bare-prefix match, message) → Task 4 Steps 3-4. Guard R6 written before the fix and observed failing on the app → Task 1 + Task 2 Step 5. Out-of-scope items are absent from every task.

**Types.** `divider?: boolean` is declared in Task 3 Step 5 and used only there and in Step 6. `Completion.match` is added in Task 4 Step 3 and set on every construction site in the same block. `LANE_PAD`/`LANE_DIVIDER_INSET` are created in Task 3 Step 3 and imported in Steps 5-7; `LANE_EDGE_W`/`LANE_GUTTER_W` are used only by `DropSlot`, `LANE_PAD_PX`/`LANE_DIVIDER_TOP_PX` only by the test.

**Known sequencing note.** Task 2 Step 5 stashes and rebuilds to get a pre-fix measurement. Run it before Task 3 touches the same tree, or the stash will carry lane changes too.

---

## Deviations from this plan (recorded after execution)

1. **The R6 plant did not fire as written.** `tools/probe-selftest.html` had no doctype, so it
   rendered in **quirks mode**, where a line box holding only a replaced element skips the strut
   — the fixture was structurally unable to express the defect. Fixed by adding `<!doctype html>`
   plus a `* { box-sizing: border-box }` rule standing in for Tailwind's preflight; without the
   second, standards mode made the R4 "matching row" trap fire (3 → 4 hits). The plant also
   gained the absolutely positioned overlay sibling, so it doubles as the test for the
   abspos-exclusion the real editor depends on.

2. **Root cause of #12 was confirmed by measurement before the fix, not assumed.** Real app:
   wrapper 28px / textarea 24px / overlay 28px, `parentDisplay: block`, `taDisplay: inline-block`.
   Two isolated repros of the strut failed first (both quirks mode), which is what exposed
   deviation 1.

3. **The indentation assertion is 9px, not 8px.** The script measures from the card's *outer*
   edge, which includes its 1px border: 1 + 8. All 10 containers in morbidostat and all 14 in the
   torture fixture report 9, uniformly — that is the passing state, not a failure.

4. **Backend CI was already red on `main`.** ruff 0.16 widened its default rule set and the
   backend installs ruff unpinned, so `webapp-backend` failed with 71 findings in untouched files
   (37 × B008 on FastAPI's `Depends`). Fixed here by pinning the rule set explicitly — see the
   `ci(studio):` commit. Not foreseen by this plan and unrelated to the three fixes.

5. **Not done:** the plan's Task 2 Step 5 `git stash` dance was unnecessary — the pre-fix capture
   ran against the already-built `dist` before the source edit, so the before/after numbers (66 →
   0) came from two ordinary builds.
