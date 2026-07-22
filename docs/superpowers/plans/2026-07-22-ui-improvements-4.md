# UI Improvements 4 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix eleven catalogued UI issues in Experiment Studio's frontend (parallel lane controls, scrollbar, group-card overflow, block indentation, expression-help clipping, constants form, PR #70 separators, expression input height, `{binding}` validation).

**Architecture:** Pure-function-first where a testable helper exists (`maskHoles` for #13, an auto-grow floor for #12) — TDD in vitest (node env). The remaining fixes are DOM/CSS edits verified by `tsc`/`oxlint`/`vite build` and the capture probe (`npm run capture`, both themes). No component/jsdom tests (repo rule). Reuse existing patterns: `RolesSection`'s `createPortal` anchored-popup for #7; the Toolbar's `h-4 w-px bg-slate-200` divider for #10; `controls.ts` for all heights.

**Tech Stack:** React 19, TypeScript, Tailwind 4, Zustand, vitest, oxlint, Playwright (capture harness).

## Global Constraints

- Control height lives ONLY in `src/ui/controls.ts` (`CONTROL_H = 'h-6'` = 24px). A component needing a different height is a bug in the component.
- Helper classes (`controlClass`, `textAreaClass`, `constructBorderClass`, `inlineButtonClass`) SELECT one class per property; never override by concatenation (`helper() + ' border-blue-500'` loses the cascade).
- Colours stay in three separate languages: state hue (blue/red/amber/emerald), construct tint (`constructTint.ts`), role swatch (`roleColors.ts`). Separators in this plan are neutral `slate-200` (a divider surface, not a construct).
- Dark theme is a palette remap in `index.css` `:root[data-theme='dark']`; use plain palette classes only — NO `dark:` variants, hex, or arbitrary values. Any new palette step used must exist in the remap.
- Tailwind 4 scans source text: class names must be complete literals (no `` `bg-${x}-200` ``).
- vitest is node-env, pure functions only. DOM wiring is verified by the capture probe.
- Every task ends green: `npm run typecheck && npm run lint && npm run test` before commit. Commit per task.
- Working directory for all commands: `/Users/khamit/lab-devices-ui-improvements-4/webapp/frontend`. Branch: `feat/ui-improvements-4`.

---

### Task 1: `{binding}` hole masking helper (#13, pure fn)

**Files:**
- Create: `src/builder/expr/holes.ts`
- Test: `src/builder/expr/holes.test.ts`

**Interfaces:**
- Produces: `maskHoles(text: string): { masked: string; holes: Hole[] }` where `interface Hole { start: number; end: number; name: string }`. `masked` has every `{ident}` replaced by `_ident_` (equal length, positions preserved); `holes` lists each in source order.
- Produces: `HOLE_RE` is internal; not exported.

- [ ] **Step 1: Write the failing test**

```ts
// src/builder/expr/holes.test.ts
import { describe, expect, it } from 'vitest'
import { maskHoles } from './holes'

describe('maskHoles', () => {
  it('replaces a hole with an equal-length identifier and records its span', () => {
    const { masked, holes } = maskHoles('{od}')
    expect(masked).toBe('_od_')
    expect(masked.length).toBe('{od}'.length)
    expect(holes).toEqual([{ start: 0, end: 4, name: 'od' }])
  })

  it('preserves positions of surrounding tokens', () => {
    const { masked, holes } = maskHoles('mean({od}, last=5)')
    expect(masked).toBe('mean(_od_, last=5)')
    expect(holes).toEqual([{ start: 5, end: 9, name: 'od' }])
  })

  it('masks multiple holes', () => {
    const { masked, holes } = maskHoles('{a} + {bee}')
    expect(masked).toBe('_a_ + _bee_')
    expect(holes.map((h) => h.name)).toEqual(['a', 'bee'])
  })

  it('never turns a hole into a keyword', () => {
    expect(maskHoles('{not}').masked).toBe('_not_')
    expect(maskHoles('{and}').masked).toBe('_and_')
  })

  it('leaves an unclosed or empty brace untouched', () => {
    expect(maskHoles('{od').masked).toBe('{od')
    expect(maskHoles('{}').masked).toBe('{}')
    expect(maskHoles('no braces here').holes).toEqual([])
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm run test -- holes`
Expected: FAIL — cannot resolve `./holes`.

- [ ] **Step 3: Write minimal implementation**

```ts
// src/builder/expr/holes.ts
/** Group-body {name} holes (engine expand.py `_HOLE_RE`) are not lexable by the parity-pinned
 * expr tokenizer. This masks each `{ident}` to an equal-length bare identifier `_ident_` so the
 * client-side validator/highlighter can tokenize the rest, while recording each hole's span so
 * callers map results back to the original `{name}` form. Equal length keeps every downstream
 * position (underlines, highlight spans) exact. Does NOT touch tokenize.ts/parse.ts — the golden
 * parity corpus and engine port stay in lockstep. */
export interface Hole {
  start: number
  end: number
  name: string
}

const HOLE_RE = /\{([A-Za-z_][A-Za-z0-9_]*)\}/g

export function maskHoles(text: string): { masked: string; holes: Hole[] } {
  const holes: Hole[] = []
  const masked = text.replace(HOLE_RE, (m, name: string, offset: number) => {
    holes.push({ start: offset, end: offset + m.length, name })
    return `_${name}_`
  })
  return { masked, holes }
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npm run test -- holes`
Expected: PASS (5 tests).

- [ ] **Step 5: Typecheck, lint, commit**

```bash
npm run typecheck && npm run lint
git add src/builder/expr/holes.ts src/builder/expr/holes.test.ts
git commit -m "feat(studio): hole-masking helper for client-side expr validation (#13)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Br9UuW8ZjsoHzkXmGFEEUk"
```

---

### Task 2: Wire hole-masking into validation + highlighting (#13)

**Files:**
- Modify: `src/builder/expr/analyze.ts`
- Modify: `src/builder/expr/highlight.ts`
- Test: `src/builder/expr/analyze.test.ts` (create if absent; otherwise append)

**Interfaces:**
- Consumes: `maskHoles`, `Hole` from `./holes` (Task 1).
- `analyzeExpression(text, expected, scope)` signature UNCHANGED. Behaviour: `{name}` holes no longer emit `unexpected character '{'`; a hole present in scope (either `{name}` or bare `name`) is accepted; an absent hole reports `unknown binding '{name}'` / `unknown stream '{name}'`.
- `highlightSpans(text, underlines)` signature UNCHANGED. Behaviour: holes colour as name references; no error span after `{`.

- [ ] **Step 1: Write the failing test**

```ts
// src/builder/expr/analyze.test.ts
import { describe, expect, it } from 'vitest'
import { analyzeExpression } from './analyze'

const scope = { streams: ['{od}'], bindings: ['{tube}', 'warm'] }

describe('analyzeExpression with {holes}', () => {
  it('accepts a known stream hole inside a stat call', () => {
    expect(analyzeExpression('mean({od}, last=5)', 'any', scope)).toEqual([])
  })

  it('accepts a known binding hole', () => {
    expect(analyzeExpression('{tube}', 'any', scope)).toEqual([])
  })

  it('does not report "unexpected character" for a brace', () => {
    const out = analyzeExpression('{tube} + warm', 'any', scope)
    expect(out.some((p) => /unexpected character/.test(p.message))).toBe(false)
  })

  it('reports an unknown hole using its {name} form', () => {
    const out = analyzeExpression('{bogus}', 'any', scope)
    expect(out).toHaveLength(1)
    expect(out[0].message).toBe("unknown binding '{bogus}'")
    expect(out[0].pos).toBe(0)
    expect(out[0].len).toBe('{bogus}'.length)
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm run test -- analyze`
Expected: FAIL — first three tests get `unexpected character '{'`, fourth gets wrong message/pos.

- [ ] **Step 3: Implement in `analyze.ts`**

Replace the body of `analyzeExpression` (lines 48–74) so it masks first, walks a masked scope, then restores hole names in messages. Add the import at top.

```ts
import { parseExpression, type Expr } from './parse'
import { maskHoles, type Hole } from './holes'
```

```ts
/** Add masked `_name_` forms for every {hole} in scope so `walk` accepts a hole reference by its
 * masked identifier. Bare names pass through unchanged. */
function maskScope(scope: ExprScope): ExprScope {
  const mask = (n: string): string =>
    n.startsWith('{') && n.endsWith('}') ? `_${n.slice(1, -1)}_` : n
  return { streams: scope.streams.map(mask), bindings: scope.bindings.map(mask) }
}

/** Restore a problem's message + span to the original {name} form when it lands on a hole. */
function restoreHole(p: ExprProblem, holes: Hole[]): ExprProblem {
  const h = holes.find((x) => x.start === p.pos && x.end === p.pos + p.len)
  if (!h) return p
  return { ...p, message: p.message.replace(`'_${h.name}_'`, `'{${h.name}}'`) }
}

export function analyzeExpression(
  text: string,
  expected: ExpectedType,
  scope: ExprScope,
): ExprProblem[] {
  if (text.trim() === '') return []
  const { masked, holes } = maskHoles(text)
  const result = parseExpression(masked)
  if (!result.ok) {
    const { message, pos, atEnd } = result.error
    return [{ message, pos, len: atEnd ? 0 : 1 }]
  }
  const problems: ExprProblem[] = []
  walk(result.ast, maskScope(scope), problems)
  const ast = result.ast
  if (expected === 'duration' && ast.t === 'const' && typeof ast.value === 'number') {
    problems.push({ message: 'durations need a unit — 30s, not 30', pos: 0, len: text.length })
  }
  if (
    expected === 'int' &&
    ast.t === 'const' &&
    typeof ast.value === 'number' &&
    !Number.isInteger(ast.value)
  ) {
    problems.push({ message: 'expected a whole number', pos: 0, len: text.length })
  }
  return holes.length === 0 ? problems : problems.map((p) => restoreHole(p, holes))
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npm run test -- analyze`
Expected: PASS (4 tests).

- [ ] **Step 5: Implement in `highlight.ts` and verify no regressions**

In `classify` (line 62), tokenize the MASKED text so holes lex; positions are identical because masking is equal-length. Change the import and the first line of `classify`:

```ts
import { KEYWORDS, STAT_FNS, tokenize, type Token } from './tokenize'
import { maskHoles } from './holes'
```

```ts
function classify(text: string): Array<{ start: number; end: number; cls: SpanClass }> {
  const { tokens, error } = tokenize(maskHoles(text).masked)
  // ...rest unchanged (positions and text.length match the original 1:1)...
```

Run the full expr suite to confirm the parity/highlight goldens still pass:

Run: `npm run test`
Expected: PASS (all suites, including `expr/` goldens — `classify` output for hole-free text is byte-identical).

- [ ] **Step 6: Typecheck, lint, commit**

```bash
npm run typecheck && npm run lint
git add src/builder/expr/analyze.ts src/builder/expr/highlight.ts src/builder/expr/analyze.test.ts
git commit -m "fix(studio): validate and highlight {binding} holes in expression editor (#13)

Client-side validator/highlighter mask {name} holes to equal-length bare
identifiers before the parity-pinned tokenizer runs, matching each hole
against the active scope. No more false 'unexpected character' on {od}/{tube};
tokenize.ts/parse.ts (golden-pinned) untouched.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Br9UuW8ZjsoHzkXmGFEEUk"
```

---

### Task 3: 24px floor for the expression editor height (#12)

**Files:**
- Modify: `src/ui/autoGrow.ts`
- Modify: `src/ui/autoGrow.test.ts`
- Modify: `src/ui/controls.ts` (export the pixel height)
- Modify: `src/builder/ExpressionEditor.tsx:89-102`

**Interfaces:**
- Produces: `CONTROL_H_PX = 24` exported from `controls.ts`.
- `autoGrowHeight(m)` gains optional `m.minHeight?: number` (default `m.lineHeight`, preserving existing callers). Floors the returned height at `minHeight`.

- [ ] **Step 1: Write the failing test** (append to `src/ui/autoGrow.test.ts`)

```ts
import { autoGrowHeight } from './autoGrow'
// (existing imports/tests above)

describe('autoGrowHeight minHeight floor', () => {
  it('floors a single short line at minHeight', () => {
    expect(autoGrowHeight({ scrollHeight: 20, lineHeight: 16, maxLines: 6, minHeight: 24 }))
      .toEqual({ height: 24, overflow: 'hidden' })
  })
  it('lets content taller than minHeight grow', () => {
    expect(autoGrowHeight({ scrollHeight: 48, lineHeight: 16, maxLines: 6, minHeight: 24 }))
      .toEqual({ height: 48, overflow: 'hidden' })
  })
  it('defaults minHeight to lineHeight when omitted', () => {
    expect(autoGrowHeight({ scrollHeight: 10, lineHeight: 16, maxLines: 6 }))
      .toEqual({ height: 16, overflow: 'hidden' })
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm run test -- autoGrow`
Expected: FAIL — first test returns `height: 20`.

- [ ] **Step 3: Implement the floor in `autoGrow.ts`**

```ts
export function autoGrowHeight(m: {
  scrollHeight: number
  lineHeight: number
  maxLines: number
  minHeight?: number
}): { height: number; overflow: 'hidden' | 'auto' } {
  const cap = m.lineHeight * m.maxLines
  const floor = m.minHeight ?? m.lineHeight
  const wanted = Math.max(m.scrollHeight, floor)
  if (wanted > cap) return { height: cap, overflow: 'auto' }
  return { height: wanted, overflow: 'hidden' }
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npm run test -- autoGrow`
Expected: PASS.

- [ ] **Step 5: Export the pixel constant and pass it from the editor**

In `src/ui/controls.ts`, beside `export const CONTROL_H = 'h-6'` (line 13) add:

```ts
/** The 24px pixel value behind CONTROL_H, for consumers that size imperatively
 * (auto-growing textareas) rather than via the class. Keep in lockstep with CONTROL_H. */
export const CONTROL_H_PX = 24
```

In `src/builder/ExpressionEditor.tsx`, update the import (line 11) and the auto-grow effect (lines 93-98):

```ts
import { textAreaClass, CONTROL_H_PX } from '../ui/controls'
```

```ts
    const lineHeight = Number.parseFloat(getComputedStyle(el).lineHeight) || 16
    const { height, overflow } = autoGrowHeight({
      scrollHeight: el.scrollHeight,
      lineHeight,
      maxLines: MAX_LINES,
      minHeight: CONTROL_H_PX,
    })
```

- [ ] **Step 6: Typecheck, lint, test, commit**

```bash
npm run typecheck && npm run lint && npm run test
git add src/ui/autoGrow.ts src/ui/autoGrow.test.ts src/ui/controls.ts src/builder/ExpressionEditor.tsx
git commit -m "fix(studio): expression inputs render at the 24px control height (#12)

autoGrowHeight gains a minHeight floor (default lineHeight); the editor
passes CONTROL_H_PX so a single-line expression matches sibling controls
and clears the probe's sibling-height rule.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Br9UuW8ZjsoHzkXmGFEEUk"
```

---

### Task 4: Portal-anchor the expression popups (#7)

**Files:**
- Create: `src/ui/AnchoredPopup.tsx`
- Modify: `src/builder/ExpressionEditor.tsx` (`CompletionPopup` at 285-314, `HelpPopover` at 318-376, and their render sites 277-280)

**Interfaces:**
- Produces: `AnchoredPopup({ anchorRef, align, children }: { anchorRef: RefObject<HTMLElement | null>; align: 'left' | 'right'; children: ReactNode })` — renders `children` via `createPortal` to `document.body`, `position: fixed`, measured from `anchorRef`'s rect, flipping above when there's no room below and clamping horizontally to keep both edges ≥ 8px inside the viewport (the `RolesSection.tsx:264-311` logic, generalised).

**Note:** No vitest (DOM/portal). Verified by typecheck/lint/build and the `expression-popover` + `group-scope-expression` capture states.

- [ ] **Step 1: Create `AnchoredPopup.tsx`** (mirrors `RolesSection`'s picker)

```tsx
import { useLayoutEffect, useRef, useState, type ReactNode, type RefObject } from 'react'
import { createPortal } from 'react-dom'

/** A popup that escapes ancestor `overflow` clipping (spec §7): portalled to document.body,
 * position:fixed, measured from `anchorRef`. Flips above when it would overflow the viewport
 * bottom; clamps horizontally so both edges stay ≥ 8px inside. Generalised from RolesSection's
 * colour picker. The caller supplies the panel chrome (border/bg/shadow/width). */
export function AnchoredPopup(props: {
  anchorRef: RefObject<HTMLElement | null>
  align: 'left' | 'right'
  children: ReactNode
}) {
  const panelRef = useRef<HTMLDivElement>(null)
  const [pos, setPos] = useState<{ top: number; left: number } | null>(null)

  useLayoutEffect(() => {
    const trigger = props.anchorRef.current?.getBoundingClientRect()
    const panel = panelRef.current?.getBoundingClientRect()
    if (!trigger || !panel) return
    const below = trigger.bottom + 4 + panel.height <= window.innerHeight
    const top = below ? trigger.bottom + 4 : Math.max(8, trigger.top - 4 - panel.height)
    const rawLeft = props.align === 'right' ? trigger.right - panel.width : trigger.left
    const left = Math.max(8, Math.min(rawLeft, window.innerWidth - 8 - panel.width))
    setPos({ top, left })
  }, [props.anchorRef, props.align])

  return createPortal(
    <div
      ref={panelRef}
      style={{
        position: 'fixed',
        top: pos?.top ?? 0,
        left: pos?.left ?? 0,
        visibility: pos ? 'visible' : 'hidden',
        maxWidth: 'calc(100vw - 16px)',
      }}
      className="z-30"
    >
      {props.children}
    </div>,
    document.body,
  )
}
```

- [ ] **Step 2: Use it for both popups in `ExpressionEditor.tsx`**

Add the import:

```ts
import { AnchoredPopup } from '../ui/AnchoredPopup'
```

The wrapper already has `wrapRef` (line 162). Both popups anchor to it. Change the render sites (277-280) to pass the anchor, and drop the popups' own `absolute … mt-1` positioning (the portal owns position now; keep the panel chrome classes). `CompletionPopup`:

```tsx
{popup && (
  <AnchoredPopup anchorRef={wrapRef} align="left">
    <CompletionPopup popup={popup} onPick={accept} />
  </AnchoredPopup>
)}
{helpOpen && help && (
  <AnchoredPopup anchorRef={wrapRef} align="right">
    <HelpPopover help={help} onName={onName} onFn={onFn} onWindow={onWindow} />
  </AnchoredPopup>
)}
```

In `CompletionPopup` (line 290) change the `<ul>` class from
`"absolute left-0 z-20 mt-1 max-h-48 w-56 overflow-auto rounded border border-slate-300 bg-white py-0.5 text-xs shadow-lg"`
to
`"max-h-48 w-56 overflow-auto rounded border border-slate-300 bg-white py-0.5 text-xs shadow-lg"`.

In `HelpPopover` (line 332) change the `<div>` class from
`"absolute right-0 z-20 mt-1 w-72 rounded border border-slate-300 bg-white p-2 text-xs shadow-lg"`
to
`"w-72 rounded border border-slate-300 bg-white p-2 text-xs shadow-lg"`.

**Dismissal note:** `useDismissable` (line 159) wraps `wrapRef`; it must treat the portalled panel as "inside" so clicking a help chip doesn't close it. `useDismissable.test.ts` already references an `inPortal` node — confirm `useDismissable` ignores clicks whose target is inside a `[data-portal]`/body-portal panel. If it closes on portal clicks, add `data-portal` to the `AnchoredPopup` div and update `useDismissable` to treat `closest('[data-portal]')` as inside. Verify by reading `src/ui/useDismissable.ts` before wiring.

- [ ] **Step 3: Verify**

Run: `npm run typecheck && npm run lint && npm run test && npm run build`
Expected: all PASS (build proves the portal + JSX compile).

- [ ] **Step 4: Commit**

```bash
git add src/ui/AnchoredPopup.tsx src/builder/ExpressionEditor.tsx
git commit -m "fix(studio): float expression help/completion popups above panel clipping (#7)

Both popups now portal to document.body with fixed, viewport-clamped
positioning (RolesSection's picker pattern generalised into AnchoredPopup),
so they no longer clip behind the w-64 palette or the viewport edge.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Br9UuW8ZjsoHzkXmGFEEUk"
```

---

### Task 5: Unify parallel lane controls + clean lane separators/indent (#1, #5-parallel, #10-parallel)

**Files:**
- Modify: `src/builder/Canvas.tsx` — `ParallelLanes` (399-442) and `Lane` (451-543)

**Interfaces:**
- `Lane({ lane, index })` renders one `LaneShell` (header with `LANE N`, label, fault marker, diagnostics badge, duplicate, empty-only delete; selection ring; drag) regardless of `lane.kind`. Body: `serial` → `<BlockList slot="children" items={lane.children}>`; any other kind → `<BlockView node={lane}>`.
- Separators between lanes are standalone `<span aria-hidden className="w-px self-stretch bg-slate-200" />` — no `border-l`, no construct tint, no rounded corners.

**Note:** No vitest (DOM). Verified by typecheck/lint/build and the `morbidostat` (three bare-block lanes) + `group-scope-deep` capture states.

- [ ] **Step 1: Rewrite `Lane` as a single shell**

Replace the whole `Lane` function (451-543) with:

```tsx
/** One lane of a Parallel — feature-equivalent regardless of the child's kind (#1). A `serial`
 * child IS the lane: its children render directly in the body and this header is the serial's
 * handle. Any other kind is an imported bare-block lane whose single block renders as a card in
 * the body; the lane header still carries lane-level select/drag/duplicate. Delete stays
 * empty-only (a bare-block lane is never empty → removed via its card's ✕ or select+Delete). */
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
  const isSerial = lane.kind === 'serial'
  const marker = faultMarker(lane).trim()
  const canDelete = isSerial && lane.children.length === 0
  return (
    <div
      id={`block-${lane.uid}`}
      ref={setNodeRef}
      onClick={(e) => {
        e.stopPropagation()
        select(lane.uid)
      }}
      className={
        'min-w-48 flex-initial rounded p-1 ' +
        (selected ? 'ring-2 ring-blue-400 ' : '') +
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
          {canDelete && (
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
      {isSerial ? (
        <BlockList parentUid={lane.uid} slot="children" items={lane.children} />
      ) : (
        <BlockView node={lane} />
      )}
    </div>
  )
}
```

- [ ] **Step 2: Add the standalone hairline between lanes in `ParallelLanes`**

In `ParallelLanes` (416-421) interleave a neutral hairline before each lane after the first:

```tsx
      {node.children.map((lane, i) => (
        <Fragment key={lane.uid}>
          {i > 0 && <span aria-hidden className="w-px self-stretch bg-slate-200" />}
          <Lane lane={lane} index={i} />
          <DropSlot at={{ parentUid: node.uid, slot: 'children', index: i + 1 }} horizontal hint={false} />
        </Fragment>
      ))}
```

Confirm `constructBorderClass` is still imported/used elsewhere in the file (branch arm in Task 6); if `Lane` was its only user, remove the now-unused import to satisfy oxlint.

- [ ] **Step 3: Verify**

Run: `npm run typecheck && npm run lint && npm run test && npm run build`
Expected: all PASS.

- [ ] **Step 4: Commit**

```bash
git add src/builder/Canvas.tsx
git commit -m "fix(studio): parallel lanes are feature-equivalent regardless of kind (#1, #10)

One LaneShell renders select/drag/duplicate/empty-delete/diagnostics for
every lane; imported bare-block lanes are no longer stripped of controls.
Lane separators become plain slate hairlines (no border-on-rounded-box,
no construct tint).

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Br9UuW8ZjsoHzkXmGFEEUk"
```

---

### Task 6: Branch-arm separators + consistent container indentation (#5, #10-branch)

**Files:**
- Modify: `src/builder/Canvas.tsx` — `BranchLanes` (545-600ish) and confirm `ContainerBody` (392-396)

**Interfaces:**
- Branch arm separator is a standalone `<span aria-hidden className="w-px self-stretch bg-slate-200" />` between the THEN and ELSE arms — no `border-l`, no construct tint.
- Every container interior keeps the single `px-2` unit from `ContainerBody`; horizontal-container children (lanes, arms) use identical inner padding (`p-1`) so a Parallel and a Branch at the same depth inset their content equally and nesting steps evenly.

**Note:** No vitest. Verified by typecheck/lint/build and the `branch-selected` + `group-scope-deep` capture states.

- [ ] **Step 1: Rewrite the `BranchLanes` arm row**

Replace the arm row (from `<div className="flex gap-2">` through the ELSE arm's opening `<div>`) so both arms use the same `p-1` padding and the divider is a standalone hairline:

```tsx
    <div className="flex gap-2">
      <div className="min-w-48 flex-initial p-1">
        <p className="flex h-6 items-center px-1 text-[10px] uppercase text-caption">then</p>
        <BlockList parentUid={node.uid} slot="then" items={node.then} />
      </div>
      <span aria-hidden className="w-px self-stretch bg-slate-200" />
      <div className="min-w-48 flex-initial p-1">
        {node.else === null ? (
```

Keep the rest of the ELSE arm body (the `else` label, the `my-0.5 h-2` spacer, the "+ add else" button) unchanged. The `then` label gains `px-1` to match the lane header's inner padding; the ELSE arm loses its `border-l` + `constructBorderClass('branch')`.

Update the stale comment block above the row (568-570, about reading `branch`'s tint) — replace it with a one-line note that the arm separator is a neutral slate hairline shared with parallel lanes.

- [ ] **Step 2: Remove now-unused construct-border import if applicable**

If `constructBorderClass` is no longer referenced anywhere in `Canvas.tsx` after Tasks 5-6, remove its import. Run lint to confirm:

Run: `npm run lint`
Expected: PASS (no unused-import error). If it flags `constructBorderClass`, delete the import line.

- [ ] **Step 3: Verify**

Run: `npm run typecheck && npm run lint && npm run test && npm run build`
Expected: all PASS.

- [ ] **Step 4: Commit**

```bash
git add src/builder/Canvas.tsx
git commit -m "fix(studio): even container indentation + plain branch-arm separator (#5, #10)

Branch arms use the same p-1 inner padding as parallel lanes and are
divided by the same neutral slate hairline, so Parallel and Branch inset
their content equally and nested blocks step in evenly.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Br9UuW8ZjsoHzkXmGFEEUk"
```

---

### Task 7: Group card signature truncation (#3)

**Files:**
- Modify: `src/builder/Palette.tsx` — `GroupsPanel` row (87-99)
- Modify: `src/builder/Chip.tsx:24` (add `overflow-hidden`)

**Interfaces:** none new. The signature ellipsizes inside the chip; full text in `title`.

**Note:** No vitest. Verified by the `scope-switcher-long-group` capture state.

- [ ] **Step 1: Make the signature truncate and the chip clip**

In `Palette.tsx` replace the chip's inner spans (92-98) so name + params share one truncating region:

```tsx
              <KindIcon kind="group_ref" className="mr-1 shrink-0" />
              <span
                className="min-w-0 truncate font-mono"
                title={`${name}(${group.params.map((p) => p.name).join(', ')})`}
              >
                {name}
                <span className="ml-1 text-caption">
                  ({group.params.map((p) => p.name).join(', ')})
                </span>
              </span>
```

In `Chip.tsx` (line 24) add `overflow-hidden` to the container class string so nothing paints past the rounded box:

```tsx
  'flex cursor-grab select-none items-center overflow-hidden rounded border border-slate-300 bg-white px-2 py-1 text-xs shadow-sm '
```

Confirm the block-palette chips (which are short, `flex-wrap` pills) still look right with `overflow-hidden` — they have no overflowing content, so clipping is a no-op there. If any chip relied on visible overflow (none do), revisit; otherwise this is safe.

- [ ] **Step 2: Verify**

Run: `npm run typecheck && npm run lint && npm run test && npm run build`
Expected: all PASS.

- [ ] **Step 3: Commit**

```bash
git add src/builder/Palette.tsx src/builder/Chip.tsx
git commit -m "fix(studio): group-card signature truncates instead of overflowing (#3)

Name + params share one min-w-0 truncate region (full signature in title)
and the Chip clips to its rounded box, so a multi-param group no longer
spills under the edit/delete icons or forces a horizontal scrollbar.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Br9UuW8ZjsoHzkXmGFEEUk"
```

---

### Task 8: Stacked constants form (#8, #9)

**Files:**
- Modify: `src/builder/ConstantsPanel.tsx` — the edit row (68-97) and create form (98-116)

**Interfaces:** none new. Both the existing-constant row and the create form use one stacked layout: name row (with delete on the far right for edit / Add for create), then a full-width `ExpressionEditor`, then a `unit` input + `TypeBadge` row.

**Note:** No vitest. Verified by the Constants panel capture (add a `constants-panel` state — see Task 10 note if none exists; otherwise the panel is reachable via the Constants section).

- [ ] **Step 1: Replace the edit-row `<li>` with a stacked block**

```tsx
        {Object.entries(constants).map(([name, decl]) => (
          <li key={name} className="space-y-1 border-b border-slate-200 pb-1 text-sm">
            <div className="flex items-center gap-1">
              <span className="min-w-0 flex-1 truncate font-mono text-caption" title={name}>
                {name}
              </span>
              <IconButton
                icon={X}
                label="Delete constant"
                destructive
                onClick={() => setError(removeConstant(name))}
              />
            </div>
            <ExpressionEditor
              value={valueText(decl.value)}
              expected="any"
              placeholder="value or expression"
              onCommit={(t) => setConstantValue(name, coerceConstantValue(t))}
            />
            <div className="flex items-center gap-1">
              <input
                value={decl.as ?? ''}
                placeholder="unit"
                onChange={(e) => setConstantUnit(name, e.target.value || null)}
                className={controlClass({ width: 'w-20' })}
              />
              <TypeBadge name={name} />
            </div>
          </li>
        ))}
```

- [ ] **Step 2: Replace the create form with the same stacked shape**

The create form needs its own `unit` state and a value that commits through the same coercion. Add a `newUnit` state at the top of the component (beside `newValue`):

```tsx
  const [newUnit, setNewUnit] = useState('')
```

Update `add` so a unit set at creation time is applied (after the value is added):

```tsx
  const add = (): void => {
    if (!newName.trim()) return
    const nm = newName.trim()
    const err = addConstant(nm, coerceConstantValue(newValue))
    setError(err)
    if (!err) {
      if (newUnit.trim()) setConstantUnit(nm, newUnit.trim())
      setNewName('')
      setNewValue('')
      setNewUnit('')
    }
  }
```

Replace the create `<div className="flex items-center gap-1">` block (98-116) with:

```tsx
      <div className="space-y-1">
        <div className="flex items-center gap-1">
          <input
            value={newName}
            placeholder="name"
            onChange={(e) => setNewName(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && add()}
            className={controlClass({ mono: true, width: 'w-full' })}
          />
          <button onClick={add} className={inlineButtonClass()}>
            Add
          </button>
        </div>
        <ExpressionEditor
          value={newValue}
          expected="any"
          placeholder="value or expression"
          onCommit={(t) => setNewValue(t)}
        />
        <input
          value={newUnit}
          placeholder="unit"
          onChange={(e) => setNewUnit(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && add()}
          className={controlClass({ width: 'w-20' })}
        />
      </div>
```

**Note on the create value editor:** `ExpressionEditor` commits on blur/Enter via `onCommit`, so `newValue` updates when the user leaves the field; `add()` reads the latest `newValue`. Enter inside the expression editor commits the field (not the form) — the user presses Add or Enter in the name/unit input to create. This matches the edit row's commit semantics and resolves #8 (create now uses the expression editor + unit, like edit).

- [ ] **Step 3: Verify**

Run: `npm run typecheck && npm run lint && npm run test && npm run build`
Expected: all PASS.

- [ ] **Step 4: Commit**

```bash
git add src/builder/ConstantsPanel.tsx
git commit -m "fix(studio): stacked, consistent constants create/edit forms (#8, #9)

Both forms use one stacked layout — name row, full-width expression editor,
unit + type badge — so the value editor no longer collapses to one character
in the narrow palette and the create form gains the expression editor + unit
field the edit row already had.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Br9UuW8ZjsoHzkXmGFEEUk"
```

---

### Task 9: Global thin scrollbars (#2)

**Files:**
- Modify: `src/index.css` (add scrollbar styling after the utilities block, before the dark-theme block)

**Interfaces:** none. Every scroll surface renders a thin styled scrollbar in both themes; the horizontal-overflow trigger is already removed by Task 7.

**Note:** No vitest. Verified by the Palette capture in both themes.

- [ ] **Step 1: Add scrollbar styling to `index.css`**

Insert after the `edge-hatch` utility (line 41), before the dark-theme comment block:

```css
/* ---------------------------------------------------------------------------
 * Thin scrollbars (UI improvements 4, #2). The app defined none, so every
 * overflow container fell back to the thick classic native bar. These use the
 * slate divider tokens, so they remap with the dark theme automatically. OS
 * overlay auto-hide stays OS-controlled; this only removes the "very bold" weight.
 * ------------------------------------------------------------------------- */
* {
  scrollbar-width: thin;
  scrollbar-color: var(--color-slate-300) transparent;
}
*::-webkit-scrollbar {
  width: 8px;
  height: 8px;
}
*::-webkit-scrollbar-track {
  background: transparent;
}
*::-webkit-scrollbar-thumb {
  background-color: var(--color-slate-300);
  border-radius: 9999px;
}
*::-webkit-scrollbar-thumb:hover {
  background-color: var(--color-slate-400);
}
```

- [ ] **Step 2: Verify build**

Run: `npm run build`
Expected: PASS (CSS compiles; no token errors — `--color-slate-300/400` exist and are remapped in dark mode).

- [ ] **Step 3: Commit**

```bash
git add src/index.css
git commit -m "fix(studio): thin styled scrollbars app-wide (#2)

The app defined no scrollbar CSS, so every overflow container drew the
thick native bar. Adds a thin slate scrollbar (thumb on transparent track)
using the divider tokens, so it remaps in dark mode too.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Br9UuW8ZjsoHzkXmGFEEUk"
```

---

### Task 10: Full verification + capture probe

**Files:** none (verification only; may add capture states if a fixed surface is uncovered).

- [ ] **Step 1: Full suite**

Run: `npm run typecheck && npm run lint && npm run test && npm run build`
Expected: all PASS.

- [ ] **Step 2: Capture probe (both themes)**

Prereq: dev server running (`npm run dev`, proxies `/api` to backend on :8000) — start the backend + frontend per `webapp/frontend/tools/README.md`, then in a second shell:

Run: `npm run capture -- --out /private/tmp/claude-501/-Users-khamit-lab-devices/a2960e45-bc61-474c-9772-b37a38a48760/scratchpad/capture`
Expected: writes PNGs + `probe.json`. Open `probe.json`: zero R4 (`sibling-height-mismatch`) and zero R5 (`text-contrast`) violations. Eyeball the `morbidostat` (lane controls #1), `branch-selected` (#5/#10), `expression-popover` + `group-scope-expression` (#7/#12/#13), `scope-switcher-long-group` (#3), and the Constants panel shots.

If the backend/servers are unavailable in this environment, record that the capture step could not run and rely on the unit suite + typecheck/lint/build as the gate, noting it explicitly in the PR description.

- [ ] **Step 3: Commit any capture-state additions**

If a state was added to `tools/capture.mjs` to cover the Constants panel or the mixed-lane parallel, commit it:

```bash
git add webapp/frontend/tools/capture.mjs
git commit -m "test(studio): capture states for constants panel + mixed parallel lanes

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Br9UuW8ZjsoHzkXmGFEEUk"
```

---

## Self-Review

**Spec coverage:**
- #1 → Task 5 ✓ · #2 → Task 9 ✓ · #3 → Task 7 ✓ · #5 → Tasks 5+6 ✓ · #7 → Task 4 ✓ · #8 → Task 8 ✓ · #9 → Task 8 ✓ · #10 → Tasks 5+6 ✓ · #12 → Task 3 ✓ · #13 → Tasks 1+2 ✓. Testing strategy → Task 10 ✓. (Issues #4, #6, #11 do not exist in the source list — the improvements doc numbers 1,2,3,5,7,8,9,10,12,13.)

**Placeholder scan:** none — every code step shows concrete code; every run step shows the command + expected result.

**Type consistency:** `maskHoles`/`Hole` (Task 1) consumed in Task 2; `CONTROL_H_PX` (Task 3) matches its `controls.ts` export; `AnchoredPopup` prop shape (Task 4) matches its use; `LaneShell` behaviour (Task 5) and the `w-px self-stretch bg-slate-200` divider literal are identical in Tasks 5 and 6.

## Execution Handoff

Plan complete. Executing inline in this session (user authorised full autonomous flow), verifying each task green before commit, then opening the PR, waiting for CI, and merging.
