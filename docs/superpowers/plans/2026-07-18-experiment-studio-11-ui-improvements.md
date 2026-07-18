# Experiment Studio W11 — UI Improvements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the six hand-found UI defects in the Experiment Studio Builder by fixing the three shared causes underneath them — no control-height token, a scroll fade painted as a background, and rigid 50/50 branch arms with nested scrollers.

**Architecture:** Four new shared primitives land in `src/ui/`, each split into a pure function (unit-tested in the node-env vitest setup) and a thin React component (verified by the capture harness). Consumers then adopt them file by file. The riskiest change — removing nested horizontal scrollers so the Canvas becomes the single scroller — is isolated in one task with a mechanical regression check.

**Tech Stack:** React 19, TypeScript, Tailwind CSS 4, Zustand, lucide-react, vitest (node env), Playwright (new devDependency, harness only).

## Global Constraints

Copied verbatim from `webapp/frontend/CLAUDE.md` and the design spec. **Every task's requirements implicitly include this section.**

- **Icons:** interactive icons come from **lucide-react** only. `src/ui/IconButton.tsx` is the only way to render an icon-only action — it enforces the ≥24×24px hit area, contrast, and `title`/`aria-label`.
- **No raw glyph characters for interactive controls** (no ✕ ⧉ ✎ ▾ ↻ ⭳ buttons). Semantic notation stays typographic: `∀`, `R×N`, `⤳`, `×N`, the `●` unsaved dot, ellipses, prose dashes.
- **Text colors:** meaning-carrying secondary text uses `text-caption` (slate-600); incidental placeholder/empty-state text uses `text-hint` (slate-500). Never raw `text-slate-400` or lighter on text that carries meaning. On the tinted canvas (`bg-slate-100`) use `text-caption` even for incidental text.
- **Testing:** vitest runs in **node env — pure functions only, no component rendering, no jsdom, no @testing-library.** DOM wiring is verified by the capture/probe harness (Task 13).
- **Control height token:** every text input, select, and inline button renders at **24px (`h-6`)**, matching the existing `IconButton` contract. Introduced in Task 1; all later tasks consume it.
- **Gates (run in `webapp/frontend`):** `npm run lint && npm test && npm run build`.
- **Do not modify `src/run/InputDialog.tsx`'s dismissal behavior.** Its `onCancel` preventDefault is deliberate — the run is parked on that prompt.
- **Commit after every task.** Conventional commits, scope `studio`.

**Working directory for all paths below:** `/Users/khamit/lab-devices/.claude/worktrees/ui-improvements`. Frontend paths are relative to `webapp/frontend`.

---

## File Structure

**Created:**

| File | Responsibility |
|---|---|
| `src/ui/controls.ts` | The control-height token. `controlClass()` / `inlineButtonClass()`. |
| `src/ui/controls.test.ts` | Locks the invariant that every control family shares one height. |
| `src/ui/autoGrow.ts` | Pure `autoGrowHeight()` and `collapseNewlines()`. |
| `src/ui/autoGrow.test.ts` | Grow, cap, boundary, newline collapsing. |
| `src/ui/AutoGrowTextArea.tsx` | Textarea that applies `autoGrowHeight` in a layout effect. |
| `src/ui/useDismissable.ts` | Pure `shouldDismiss()` + the hook that registers listeners while open. |
| `src/ui/useDismissable.test.ts` | Inside / outside / Escape / other keys. |
| `src/ui/scrollEdges.ts` | Pure `scrollEdges()` — scroll metrics → which edges continue. |
| `src/ui/scrollEdges.test.ts` | Both edges, at start, at end, not overflowing. |
| `src/ui/ScrollX.tsx` | `useScrollEdges(ref)` hook + `<ScrollFades>` overlay component. |
| `tools/probe.mjs` | Boundary rules incl. the new sibling-control-height rule. |
| `tools/probe-selftest.html` | One planted violation per rule. |
| `tools/probe-selftest.mjs` | Asserts the probe finds exactly the planted set. |
| `tools/capture.mjs` | Drives the app across states × viewports; writes screenshots + `probe.json`. |
| `tools/README.md` | How to run the harness. |

**Modified:** `src/index.css`, `src/builder/{Canvas,Inspector,Toolbar,fields,Palette,RolesPanel,StreamsPanel,StreamIntoPicker}.tsx`, `src/builder/params.ts`, `src/records/RecordsTable.tsx`, `webapp/frontend/CLAUDE.md`, `package.json`.

## Task → Finding Map

| Task | Closes |
|---|---|
| 1 | cause C-A (token) |
| 2, 3, 4 | primitives for #4, #6, #1 |
| 5 | #6 (popover), #3 (`ƒ` button), #4 (expressions) |
| 6 | #4 (prose fields), A4 |
| 7 | #5a |
| 8 | #2, C11 |
| 9 | #3 (add-buttons), C9, C10 |
| 10 | #1, #5b |
| 11 | C1–C8 |
| 12 | #6 (remaining) |
| 13, 14 | verification, evidence, preprod |

---

## Task 1: The control-height token

**Files:**
- Create: `src/ui/controls.ts`, `src/ui/controls.test.ts`
- Modify: `src/builder/fields.tsx:8-9` (`inputClass`), `src/builder/fields.tsx:71-74` (textarea class)

**Interfaces:**
- Consumes: `iconButtonClass()` from `src/ui/IconButton.tsx` (existing).
- Produces: `CONTROL_H: string`, `controlClass(opts?: {mono?: boolean; invalid?: boolean}): string`, `inlineButtonClass(opts?: {subtle?: boolean}): string`. Every later task uses these.

- [ ] **Step 1: Write the failing test**

Create `src/ui/controls.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import { iconButtonClass } from './IconButton'
import { CONTROL_H, controlClass, inlineButtonClass } from './controls'

/** The height classes present in a class string. */
const heights = (cls: string) => cls.split(/\s+/).filter((c) => /^h-\d/.test(c))

describe('control height token', () => {
  it('pins every control family to the same single height', () => {
    // This is the whole point of the token: an input, an inline button and an
    // icon button sitting in one flex row must agree, or they disagree by 2-4px
    // like the twelve sites the 2026-07-18 sweep found.
    expect(heights(controlClass())).toEqual([CONTROL_H])
    expect(heights(inlineButtonClass())).toEqual([CONTROL_H])
    expect(heights(iconButtonClass())).toEqual([CONTROL_H])
  })

  it('always carries a border so bordered and borderless controls cannot differ by 2px', () => {
    expect(controlClass()).toContain('border')
    expect(inlineButtonClass()).toContain('border')
  })

  it('adds font-mono only when asked', () => {
    expect(controlClass({ mono: true })).toContain('font-mono')
    expect(controlClass()).not.toContain('font-mono')
  })

  it('signals invalid with a border colour, not a height change', () => {
    expect(controlClass({ invalid: true })).toContain('border-red-400')
    expect(heights(controlClass({ invalid: true }))).toEqual([CONTROL_H])
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd webapp/frontend && npx vitest run src/ui/controls.test.ts`
Expected: FAIL — `Failed to resolve import "./controls"`.

- [ ] **Step 3: Write minimal implementation**

Create `src/ui/controls.ts`:

```ts
/** The one control-height token (spec §4.1, cause C-A).
 *
 * Before this existed the app had four height scales: IconButton pinned 24px,
 * `inputClass` yielded ~22px, Toolbar's `buttonClass` ~26px, and ad-hoc add-buttons
 * omitted the border and lost 2px more. Any row mixing two of them sat visibly
 * crooked — twelve such sites shipped in 0.8.0.
 *
 * 24px is not arbitrary: it is the hit-area floor IconButton already enforces
 * (see IconButton.tsx), so an icon button beside a text field is now flush by
 * construction rather than by coincidence. Height lives HERE and nowhere else —
 * a consumer that needs a different height is a bug in the consumer.
 */
export const CONTROL_H = 'h-6'

/** Text inputs, textareas' single-line siblings, and selects. */
export function controlClass(opts: { mono?: boolean; invalid?: boolean } = {}): string {
  return (
    `${CONTROL_H} w-full rounded border bg-white px-1.5 text-xs ` +
    'focus:border-blue-400 focus:outline-none ' +
    (opts.invalid ? 'border-red-400 ' : 'border-slate-300 ') +
    (opts.mono ? 'font-mono' : '')
  ).trim()
}

/** Inline buttons that sit in a row with inputs or other buttons.
 * `subtle` is the dashed "add another" affordance; it keeps the same height. */
export function inlineButtonClass(opts: { subtle?: boolean } = {}): string {
  return (
    `${CONTROL_H} inline-flex shrink-0 items-center justify-center rounded border px-2 text-xs ` +
    'disabled:opacity-40 ' +
    (opts.subtle
      ? 'border-dashed border-slate-300 text-caption hover:border-slate-400 hover:text-slate-700'
      : 'border-slate-300 bg-white hover:bg-slate-100 disabled:hover:bg-white')
  ).trim()
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd webapp/frontend && npx vitest run src/ui/controls.test.ts`
Expected: PASS, 4 tests.

- [ ] **Step 5: Adopt the token in the two `fields.tsx` primitives**

In `src/builder/fields.tsx`, replace the module-level `inputClass` (lines 8-9) — delete it entirely — and import the token:

```tsx
import { controlClass } from '../ui/controls'
```

In `TextField` (line 44), replace `className={inputClass + (props.mono ? ' font-mono' : '')}` with:

```tsx
      className={controlClass({ mono: props.mono })}
```

In `TextAreaField` (lines 71-74), replace the inline class string with a textarea-appropriate one that shares the border/padding but **not** the fixed height (a textarea is multi-line by definition):

```tsx
      className={
        'w-full rounded border border-slate-300 bg-white px-1.5 py-0.5 text-xs ' +
        'focus:border-blue-400 focus:outline-none ' +
        (props.mono ? 'font-mono' : '')
      }
```

- [ ] **Step 6: Run the full gate**

Run: `cd webapp/frontend && npm run lint && npm test && npm run build`
Expected: all pass. `TextField` now renders at 24px; the Toolbar name field and every Inspector field grow ~2px.

- [ ] **Step 7: Commit**

```bash
git add webapp/frontend/src/ui/controls.ts webapp/frontend/src/ui/controls.test.ts webapp/frontend/src/builder/fields.tsx
git commit -m "feat(studio): add the control-height token and adopt it in fields"
```

---

## Task 2: Auto-growing textarea primitive

**Files:**
- Create: `src/ui/autoGrow.ts`, `src/ui/autoGrow.test.ts`, `src/ui/AutoGrowTextArea.tsx`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `autoGrowHeight(m: {scrollHeight: number; lineHeight: number; maxLines: number}): {height: number; overflow: 'hidden' | 'auto'}`, `collapseNewlines(s: string): string`, and the component `AutoGrowTextArea` with props `{value, onCommit, placeholder?, mono?, maxLines?, singleLine?, fillParent?}`. Tasks 5, 6, 7 consume the component.

- [ ] **Step 1: Write the failing test**

Create `src/ui/autoGrow.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import { autoGrowHeight } from './autoGrow'

describe('autoGrowHeight', () => {
  it('grows to fit content below the cap and hides the scrollbar', () => {
    expect(autoGrowHeight({ scrollHeight: 48, lineHeight: 16, maxLines: 8 })).toEqual({
      height: 48,
      overflow: 'hidden',
    })
  })

  it('stops at the cap and hands scrolling back to the browser', () => {
    expect(autoGrowHeight({ scrollHeight: 400, lineHeight: 16, maxLines: 8 })).toEqual({
      height: 128,
      overflow: 'auto',
    })
  })

  it('treats exactly-at-cap as fitting, not overflowing', () => {
    // Off-by-one here shows up as a scrollbar flickering on and off as the user types.
    expect(autoGrowHeight({ scrollHeight: 128, lineHeight: 16, maxLines: 8 })).toEqual({
      height: 128,
      overflow: 'hidden',
    })
  })

  it('never returns a height below one line', () => {
    expect(autoGrowHeight({ scrollHeight: 0, lineHeight: 16, maxLines: 8 }).height).toBe(16)
  })
})

describe('collapseNewlines', () => {
  it('collapses pasted newlines into spaces', () => {
    // The expression grammar has no newlines. A user pasting a formatted expression from
    // a doc must get a valid single-line value, not a parse error.
    expect(collapseNewlines('last(od_1) > od_thr\nand blanks_ready')).toBe(
      'last(od_1) > od_thr and blanks_ready',
    )
  })

  it('collapses CRLF and runs of newlines to a single space', () => {
    expect(collapseNewlines('a\r\n\r\nb')).toBe('a b')
  })

  it('leaves an already single-line value untouched', () => {
    expect(collapseNewlines('mean(od_1, last=5) > 0.6')).toBe('mean(od_1, last=5) > 0.6')
  })
})
```

Update the import line at the top of the file to `import { autoGrowHeight, collapseNewlines } from './autoGrow'`.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd webapp/frontend && npx vitest run src/ui/autoGrow.test.ts`
Expected: FAIL — `Failed to resolve import "./autoGrow"`.

- [ ] **Step 3: Write minimal implementation**

Create `src/ui/autoGrow.ts`:

```ts
/** Decide the rendered height of an auto-growing textarea (spec §4.2, finding #4).
 *
 * Split out as a pure function because vitest here runs in node with no jsdom, so this
 * is the only part of the auto-grow behaviour that can be tested at all. The component
 * does nothing but measure `scrollHeight` and apply what this returns.
 */
export function autoGrowHeight(m: {
  scrollHeight: number
  lineHeight: number
  maxLines: number
}): { height: number; overflow: 'hidden' | 'auto' } {
  const cap = m.lineHeight * m.maxLines
  const wanted = Math.max(m.scrollHeight, m.lineHeight)
  if (wanted > cap) return { height: cap, overflow: 'auto' }
  return { height: wanted, overflow: 'hidden' }
}

/** Collapse newlines so a pasted multi-line value stays single-line (spec §4.2, finding #4).
 *
 * Lives here rather than in `builder/` so that `ui/` never imports from a feature module —
 * `AutoGrowTextArea` is the only consumer, via its `singleLine` prop. The expression fields
 * render as textareas purely to get soft wrapping; the VALUE must stay single-line because
 * the expression grammar has no newline token.
 */
export function collapseNewlines(s: string): string {
  return s.replace(/[\r\n]+/g, ' ')
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd webapp/frontend && npx vitest run src/ui/autoGrow.test.ts`
Expected: PASS, 4 tests.

- [ ] **Step 5: Write the component**

Create `src/ui/AutoGrowTextArea.tsx`:

```tsx
import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { autoGrowHeight, collapseNewlines } from './autoGrow'

/** A textarea that grows with its content up to `maxLines`, then scrolls internally
 * (spec §4.2, finding #4).
 *
 * `singleLine` serves the expression fields: the expression grammar has no newlines, so
 * newlines are stripped on input and Enter commits instead of inserting one. The value is
 * therefore always single-line — what the textarea buys is SOFT WRAPPING, so a long
 * expression is fully visible instead of scrolling sideways inside a one-line box.
 *
 * `fillParent` is for the Inspector's description (finding #5a): `max-h-full` lets the
 * flex parent bound the growth, so the field fills the free space and no more.
 *
 * Commit semantics deliberately match TextField (fields.tsx): commit on blur, revert on
 * Escape, so no caller has to learn a second interaction model.
 */
export function AutoGrowTextArea(props: {
  value: string
  onCommit: (v: string) => void
  placeholder?: string
  mono?: boolean
  maxLines?: number
  singleLine?: boolean
  fillParent?: boolean
}) {
  const { maxLines = 12, singleLine = false, fillParent = false } = props
  const ref = useRef<HTMLTextAreaElement>(null)
  const [draft, setDraft] = useState(props.value)
  useEffect(() => setDraft(props.value), [props.value])

  useLayoutEffect(() => {
    const el = ref.current
    if (!el) return
    // Collapse first: scrollHeight only shrinks if the element is not already tall.
    el.style.height = 'auto'
    const lineHeight = Number.parseFloat(getComputedStyle(el).lineHeight) || 16
    const { height, overflow } = autoGrowHeight({
      scrollHeight: el.scrollHeight,
      lineHeight,
      maxLines,
    })
    el.style.height = `${height}px`
    el.style.overflowY = fillParent ? 'auto' : overflow
  }, [draft, maxLines, fillParent])

  const commit = () => {
    if (draft !== props.value) props.onCommit(draft)
  }

  return (
    <textarea
      ref={ref}
      value={draft}
      rows={1}
      placeholder={props.placeholder}
      onChange={(e) => setDraft(singleLine ? collapseNewlines(e.target.value) : e.target.value)}
      onBlur={commit}
      onKeyDown={(e) => {
        if (e.key === 'Escape') {
          setDraft(props.value)
          return
        }
        if (singleLine && e.key === 'Enter') {
          e.preventDefault()
          commit()
        }
      }}
      className={
        'w-full resize-none rounded border border-slate-300 bg-white px-1.5 py-0.5 text-xs ' +
        'focus:border-blue-400 focus:outline-none ' +
        (fillParent ? 'max-h-full ' : '') +
        (props.mono ? 'font-mono' : '')
      }
    />
  )
}
```

- [ ] **Step 6: Run the full gate**

Run: `cd webapp/frontend && npm run lint && npm test && npm run build`
Expected: all pass. Nothing consumes the component yet.

- [ ] **Step 7: Commit**

```bash
git add webapp/frontend/src/ui/autoGrow.ts webapp/frontend/src/ui/autoGrow.test.ts webapp/frontend/src/ui/AutoGrowTextArea.tsx
git commit -m "feat(studio): add the auto-growing textarea primitive"
```

---

## Task 3: Dismissal hook

**Files:**
- Create: `src/ui/useDismissable.ts`, `src/ui/useDismissable.test.ts`

**Interfaces:**
- Produces: `shouldDismiss(e: {type: string; key?: string; target: DismissTarget | null}, container: DismissContainer | null): boolean` and `useDismissable(open: boolean, onClose: () => void): RefObject<HTMLDivElement | null>`. Tasks 5 and 12 consume the hook.

- [ ] **Step 1: Write the failing test**

Create `src/ui/useDismissable.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import { shouldDismiss } from './useDismissable'

/** Minimal stand-in for a DOM node — vitest runs in node here, so there is no real one. */
const container = (contains: boolean) => ({ contains: () => contains })
const target = {} as never

describe('shouldDismiss', () => {
  it('dismisses on a pointerdown outside the container', () => {
    expect(shouldDismiss({ type: 'pointerdown', target }, container(false))).toBe(true)
  })

  it('ignores a pointerdown inside the container', () => {
    // Clicking the popover's own content must never close it.
    expect(shouldDismiss({ type: 'pointerdown', target }, container(true))).toBe(false)
  })

  it('dismisses on Escape regardless of where focus is', () => {
    expect(shouldDismiss({ type: 'keydown', key: 'Escape', target }, container(true))).toBe(true)
  })

  it('ignores other keys', () => {
    expect(shouldDismiss({ type: 'keydown', key: 'a', target }, container(false))).toBe(false)
  })

  it('does not dismiss when the container is not mounted yet', () => {
    expect(shouldDismiss({ type: 'pointerdown', target }, null)).toBe(false)
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd webapp/frontend && npx vitest run src/ui/useDismissable.test.ts`
Expected: FAIL — `Failed to resolve import "./useDismissable"`.

- [ ] **Step 3: Write minimal implementation**

Create `src/ui/useDismissable.ts`:

```ts
import { useEffect, useRef, type RefObject } from 'react'

export type DismissTarget = Node
export type DismissContainer = { contains: (n: DismissTarget) => boolean }

/** Should this event close the open transient layer? (spec §4.2, finding #6.)
 *
 * Pure so the node-env vitest setup can test it; the hook below is only wiring.
 * Escape wins regardless of focus position — a user pressing Escape means "close it"
 * even while the caret sits inside the layer.
 */
export function shouldDismiss(
  e: { type: string; key?: string; target: DismissTarget | null },
  container: DismissContainer | null,
): boolean {
  if (e.type === 'keydown') return e.key === 'Escape'
  if (!container || !e.target) return false
  return !container.contains(e.target)
}

/** Close `open` layers on outside pointerdown or Escape. Attach the returned ref to the
 * element that counts as "inside" — for a popover, the wrapper holding BOTH the trigger
 * and the panel, or clicking the trigger to close would immediately reopen it.
 *
 * `pointerdown` rather than `click`: a click that starts inside and ends outside (a drag
 * or a text selection) must not dismiss.
 */
export function useDismissable(open: boolean, onClose: () => void): RefObject<HTMLDivElement | null> {
  const ref = useRef<HTMLDivElement>(null)
  // Held in a ref so a caller passing an inline arrow does not re-register listeners
  // on every render.
  const onCloseRef = useRef(onClose)
  useEffect(() => {
    onCloseRef.current = onClose
  }, [onClose])

  useEffect(() => {
    if (!open) return
    const handle = (e: Event) => {
      const key = e instanceof KeyboardEvent ? e.key : undefined
      if (shouldDismiss({ type: e.type, key, target: e.target as Node | null }, ref.current)) {
        onCloseRef.current()
      }
    }
    document.addEventListener('pointerdown', handle)
    document.addEventListener('keydown', handle)
    return () => {
      document.removeEventListener('pointerdown', handle)
      document.removeEventListener('keydown', handle)
    }
  }, [open])

  return ref
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd webapp/frontend && npx vitest run src/ui/useDismissable.test.ts`
Expected: PASS, 5 tests.

- [ ] **Step 5: Run the full gate and commit**

Run: `cd webapp/frontend && npm run lint && npm test && npm run build`

```bash
git add webapp/frontend/src/ui/useDismissable.ts webapp/frontend/src/ui/useDismissable.test.ts
git commit -m "feat(studio): add the outside-click and Escape dismissal hook"
```

---

## Task 4: Scroll-edge detection and fade overlays

**Files:**
- Create: `src/ui/scrollEdges.ts`, `src/ui/scrollEdges.test.ts`, `src/ui/ScrollX.tsx`

**Interfaces:**
- Produces: `scrollEdges(m: {scrollLeft: number; scrollWidth: number; clientWidth: number}, tolerance?: number): ScrollEdges` where `ScrollEdges = {overflowing: boolean; atStart: boolean; atEnd: boolean}`; `useScrollEdges(ref: RefObject<HTMLElement | null>): ScrollEdges`; `<ScrollFades edges={ScrollEdges} from={string} />`. Task 10 consumes all three.

- [ ] **Step 1: Write the failing test**

Create `src/ui/scrollEdges.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import { scrollEdges } from './scrollEdges'

describe('scrollEdges', () => {
  it('reports no overflow when content fits', () => {
    expect(scrollEdges({ scrollLeft: 0, scrollWidth: 500, clientWidth: 500 })).toEqual({
      overflowing: false,
      atStart: true,
      atEnd: true,
    })
  })

  it('at the left end, only the right edge continues', () => {
    expect(scrollEdges({ scrollLeft: 0, scrollWidth: 1000, clientWidth: 500 })).toEqual({
      overflowing: true,
      atStart: true,
      atEnd: false,
    })
  })

  it('scrolled to the middle, both edges continue', () => {
    expect(scrollEdges({ scrollLeft: 250, scrollWidth: 1000, clientWidth: 500 })).toEqual({
      overflowing: true,
      atStart: false,
      atEnd: false,
    })
  })

  it('at the right end, only the left edge continues', () => {
    expect(scrollEdges({ scrollLeft: 500, scrollWidth: 1000, clientWidth: 500 })).toEqual({
      overflowing: true,
      atStart: false,
      atEnd: true,
    })
  })

  it('tolerates sub-pixel rounding at both ends', () => {
    // Browsers hand back fractional scrollLeft on zoom / HiDPI. Without tolerance a fade
    // stays painted at a fully-scrolled edge, which is exactly the artifact we are removing.
    expect(scrollEdges({ scrollLeft: 0.4, scrollWidth: 1000, clientWidth: 500 }).atStart).toBe(true)
    expect(scrollEdges({ scrollLeft: 499.6, scrollWidth: 1000, clientWidth: 500 }).atEnd).toBe(true)
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd webapp/frontend && npx vitest run src/ui/scrollEdges.test.ts`
Expected: FAIL — `Failed to resolve import "./scrollEdges"`.

- [ ] **Step 3: Write minimal implementation**

Create `src/ui/scrollEdges.ts`:

```ts
export type ScrollEdges = { overflowing: boolean; atStart: boolean; atEnd: boolean }

/** Which horizontal edges have more content beyond them (spec §3, finding #1).
 *
 * The settled behaviour is that a fade appears at an edge ONLY while content continues
 * that way. The old CSS got this from `background-attachment: local`, but an overlay does
 * not scroll with its content, so the condition has to be computed from scroll position —
 * this function is that computation, and the only reason ScrollX holds state.
 */
export function scrollEdges(
  m: { scrollLeft: number; scrollWidth: number; clientWidth: number },
  tolerance = 1,
): ScrollEdges {
  const overflowing = m.scrollWidth - m.clientWidth > tolerance
  if (!overflowing) return { overflowing: false, atStart: true, atEnd: true }
  return {
    overflowing: true,
    atStart: m.scrollLeft <= tolerance,
    atEnd: m.scrollLeft >= m.scrollWidth - m.clientWidth - tolerance,
  }
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd webapp/frontend && npx vitest run src/ui/scrollEdges.test.ts`
Expected: PASS, 5 tests.

- [ ] **Step 5: Write the hook and the overlay component**

Create `src/ui/ScrollX.tsx`:

```tsx
import { useEffect, useState, type RefObject } from 'react'
import { scrollEdges, type ScrollEdges } from './scrollEdges'

/** Track which edges of a horizontal scroller still have content beyond them. */
export function useScrollEdges(ref: RefObject<HTMLElement | null>): ScrollEdges {
  const [edges, setEdges] = useState<ScrollEdges>({
    overflowing: false,
    atStart: true,
    atEnd: true,
  })

  useEffect(() => {
    const el = ref.current
    if (!el) return
    const measure = () => setEdges(scrollEdges(el))
    measure()
    el.addEventListener('scroll', measure, { passive: true })
    // The scroller's own size AND its content's size both change the answer: collapsing a
    // block or adding a lane changes scrollWidth without any scroll event firing.
    const ro = new ResizeObserver(measure)
    ro.observe(el)
    for (const child of Array.from(el.children)) ro.observe(child)
    return () => {
      el.removeEventListener('scroll', measure)
      ro.disconnect()
    }
  }, [ref])

  return edges
}

/** The fade overlays themselves (spec §4.1).
 *
 * These are ABSOLUTE OVERLAYS, not a background — that is the entire fix for finding #1.
 * The old `scroll-x-shadow` utility painted the fade via `background:` on the scroll
 * container, so it rendered behind the white block cards and survived only in the gutters
 * between them, reading as a rendering artifact rather than a feature.
 *
 * Render inside a `relative` parent that also holds the scroller. `from` must match the
 * scroller's own background (e.g. `from-slate-100` on the canvas) or the fade shows a seam.
 */
export function ScrollFades(props: { edges: ScrollEdges; from: string }) {
  const { edges, from } = props
  if (!edges.overflowing) return null
  return (
    <>
      {!edges.atStart && (
        <div
          aria-hidden
          className={`pointer-events-none absolute inset-y-0 left-0 z-10 w-10 bg-gradient-to-r ${from} to-transparent`}
        />
      )}
      {!edges.atEnd && (
        <div
          aria-hidden
          className={`pointer-events-none absolute inset-y-0 right-0 z-10 w-10 bg-gradient-to-l ${from} to-transparent`}
        />
      )}
    </>
  )
}
```

- [ ] **Step 6: Run the full gate and commit**

Run: `cd webapp/frontend && npm run lint && npm test && npm run build`

```bash
git add webapp/frontend/src/ui/scrollEdges.ts webapp/frontend/src/ui/scrollEdges.test.ts webapp/frontend/src/ui/ScrollX.tsx
git commit -m "feat(studio): add scroll-edge detection and overlay fades"
```

---

## Task 5: Rework `ExpressionInput` — icon, auto-grow, dismissal

Closes finding #6 (the popover), finding #3's `ƒ` button, and finding #4 for all six expression sites at once.

**Files:**
- Modify: `src/builder/fields.tsx:133-200` (`ExpressionInput`)

**Interfaces:**
- Consumes: `AutoGrowTextArea` (Task 2 — including its `singleLine` newline handling), `useDismissable` (Task 3), `IconButton` (existing), `SquareFunction` from `lucide-react`.
- Produces: no signature change — `ExpressionInput` keeps `{value, onCommit, placeholder?}`, so its six call sites in `Inspector.tsx` are untouched.

This task has no new pure logic of its own: the newline rule is `collapseNewlines`, already implemented and tested in Task 2. Verification here is the gate plus Task 13's harness.

- [ ] **Step 1: Rewrite `ExpressionInput`**

In `src/builder/fields.tsx`, add imports:

```tsx
import { SquareFunction } from 'lucide-react'
import { AutoGrowTextArea } from '../ui/AutoGrowTextArea'
import { IconButton } from '../ui/IconButton'
import { useDismissable } from '../ui/useDismissable'
```

Replace the `return (...)` body of `ExpressionInput` (currently lines 150-199) with:

```tsx
  // The ref wraps BOTH the trigger and the panel: if the trigger sat outside it, clicking
  // it while open would dismiss and immediately re-open (spec §4.2, finding #6).
  const wrapRef = useDismissable(open, () => setOpen(false))
  return (
    <div ref={wrapRef} className="relative">
      <div className="flex items-start gap-1">
        <AutoGrowTextArea
          mono
          singleLine
          maxLines={6}
          value={props.value}
          onCommit={props.onCommit}
          placeholder={props.placeholder ?? 'expression'}
        />
        <IconButton
          icon={SquareFunction}
          label="Expression help"
          onClick={() => setOpen(!open)}
          className="border border-slate-300"
        />
      </div>
      {open && help && (
        <div className="absolute right-0 z-20 mt-1 w-72 rounded border border-slate-300 bg-white p-2 text-xs shadow-lg">
          <p className="font-semibold text-slate-600">Streams</p>
          <p className="mb-1 font-mono text-caption">
            {help.streams.length > 0 ? help.streams.join(', ') : '— none declared —'}
          </p>
          <p className="font-semibold text-slate-600">Bindings</p>
          <p className="mb-1 font-mono text-caption">
            {help.bindings.length > 0 ? help.bindings.join(', ') : '— none —'}
          </p>
          <p className="font-semibold text-slate-600">Functions</p>
          <ul className="mb-1">
            {help.functions.map((f) => (
              <li key={f.name} className="flex justify-between gap-2">
                <span className="font-mono">{f.name}</span>
                <span className="font-mono text-hint">{f.example}</span>
              </li>
            ))}
          </ul>
          <p className="font-semibold text-slate-600">Windows</p>
          <ul>
            {help.windowForms.map((w) => (
              <li key={w.label} className="flex justify-between gap-2">
                <span>{w.label}</span>
                <span className="font-mono text-hint">{w.example}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
```

Four changes beyond the layout: the raw `ƒ` glyph becomes `IconButton icon={SquareFunction}` (matching `Inspector.tsx:477`, which already renders this same semantic correctly — the app had two renderings of "expression" side by side); `items-center` becomes `items-start` so the button sits at the field's first line as it grows; `z-10` becomes `z-20` so the panel clears the new fade overlays (`z-10`, Task 4); and the two `text-slate-500` runs become `text-caption` per the global constraints.

- [ ] **Step 2: Run the full gate**

Run: `cd webapp/frontend && npm run lint && npm test && npm run build`
Expected: all pass.

- [ ] **Step 3: Commit**

```bash
git add webapp/frontend/src/builder/fields.tsx
git commit -m "fix(studio): expression fields wrap, dismiss on outside click, and use a real icon"
```

---

## Task 6: Long-text fields in the Inspector

**Files:**
- Modify: `src/builder/Inspector.tsx` — `prompt` (line ~538), abort/alarm `message` (line ~718), catalog `string` params (line ~452), `+ add else lane` (line ~656)

**Interfaces:**
- Consumes: `AutoGrowTextArea` (Task 2), `inlineButtonClass` (Task 1).

- [ ] **Step 1: Replace the `prompt` field**

In `OperatorInputForm`, replace the `Prompt` `FieldRow`'s `TextField` with:

```tsx
      <FieldRow label="Prompt">
        <AutoGrowTextArea
          value={node.prompt ?? ''}
          onCommit={(v) => patchBlock(node.uid, { prompt: v || null })}
          placeholder="shown to the operator"
        />
      </FieldRow>
```

- [ ] **Step 2: Replace the abort/alarm `message` field**

In `ConditionForm`:

```tsx
      <FieldRow label="Message" required>
        <AutoGrowTextArea
          value={node.message}
          onCommit={(v) => patchBlock(node.uid, { message: v })}
          placeholder={node.kind === 'abort' ? 'why the run must stop' : 'what to flag'}
        />
      </FieldRow>
```

- [ ] **Step 3: Replace the catalog `string` param field**

In `ParamInput`, the `spec.type === 'string'` branch:

```tsx
  if (spec.type === 'string') {
    return (
      <AutoGrowTextArea
        value={typeof value === 'string' ? value : paramInputText(value)}
        onCommit={(t) => onCommit(coerceParamInput(t, 'string'))}
        placeholder={spec.required ? 'required' : 'optional'}
      />
    )
  }
```

Keep the rest of the branch (the expression-mode toggle) exactly as it was.

- [ ] **Step 4: Fix the `+ add else lane` button (finding A4)**

Three defects in one element: content-width in a full-width stack, a literal `"+"` string where Canvas uses the Lucide icon, and `text-slate-500` where the global constraints mandate `text-caption`. Replace it with:

```tsx
        <button
          onClick={() => patchBlock(node.uid, { else: [] })}
          className={inlineButtonClass({ subtle: true }) + ' w-full'}
        >
          <Plus size={12} aria-hidden className="mr-0.5" />add else lane
        </button>
```

Add `Plus` to the `lucide-react` import at the top of `Inspector.tsx`, and `inlineButtonClass` from `../ui/controls`. Apply the same `inlineButtonClass() + ' w-full'` to its sibling `remove else lane` button (without `subtle`, keeping it solid-bordered).

- [ ] **Step 5: Add the import and run the gate**

Add `import { AutoGrowTextArea } from '../ui/AutoGrowTextArea'` to `Inspector.tsx`.

Run: `cd webapp/frontend && npm run lint && npm test && npm run build`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add webapp/frontend/src/builder/Inspector.tsx
git commit -m "fix(studio): long-text Inspector fields grow instead of scrolling sideways"
```

---

## Task 7: Inspector panel layout — pin the summary to the bottom

**Files:**
- Modify: `src/builder/Inspector.tsx:61` (the `<aside>`), `DocProperties` (~line 107), `GroupProperties` (~line 80), `src/builder/fields.tsx` (`FieldRow` gains a `grow` prop)

- [ ] **Step 1: Give `FieldRow` a `grow` variant**

In `src/builder/fields.tsx`:

```tsx
export function FieldRow(props: {
  label: string
  required?: boolean
  grow?: boolean
  children: ReactNode
}) {
  return (
    <label className={'text-xs ' + (props.grow ? 'flex min-h-0 flex-1 flex-col py-1' : 'block py-1')}>
      <span className="mb-0.5 block text-slate-500">
        {props.label}
        {props.required && <span className="text-red-500"> *</span>}
      </span>
      {props.children}
    </label>
  )
}
```

`min-h-0` is load-bearing: without it a flex child refuses to shrink below its content and the textarea pushes the pinned lines off the panel instead of scrolling.

- [ ] **Step 2: Make the aside a flex column**

```tsx
    <aside className="flex w-80 shrink-0 flex-col overflow-y-auto border-l border-slate-200 bg-slate-50 p-3">
```

- [ ] **Step 3: Restructure `DocProperties`**

```tsx
function DocProperties() {
  const description = useDocStore((s) => s.description)
  const setDescription = useDocStore((s) => s.setDescription)
  const roles = useDocStore((s) => s.roles)
  const streams = useDocStore((s) => s.streams)
  const tree = useDocStore((s) => s.tree)
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <h2 className="mb-2 text-sm font-semibold text-slate-700">Experiment</h2>
      <FieldRow label="Description" grow>
        <AutoGrowTextArea
          fillParent
          value={description ?? ''}
          onCommit={(v) => setDescription(v || null)}
          placeholder="what this experiment does"
        />
      </FieldRow>
      {/* mt-auto pins these to the bottom of the panel (finding #5a): the description
          above grows into the free space instead of leaving 800px of dead panel. */}
      <p className="mt-auto pt-2 text-xs text-caption">
        {Object.keys(roles).length} roles · {Object.keys(streams).length} streams ·{' '}
        {tree.length} top-level blocks
      </p>
      <p className="mt-1 text-xs text-caption">Select a block to edit its parameters.</p>
    </div>
  )
}
```

- [ ] **Step 4: Apply the same shape to `GroupProperties`**

Wrap its body in `<div className="flex min-h-0 flex-1 flex-col">`, give its `Params (one per line)` `FieldRow` the `grow` prop with `fillParent` on the textarea, and change its trailing two `<p>` lines to `mt-auto pt-2` / `mt-1` exactly as above.

- [ ] **Step 5: Run the gate and commit**

Run: `cd webapp/frontend && npm run lint && npm test && npm run build`

```bash
git add webapp/frontend/src/builder/Inspector.tsx webapp/frontend/src/builder/fields.tsx
git commit -m "fix(studio): pin Inspector summary lines to the bottom, grow the description"
```

---

## Task 8: Toolbar grouping

**Files:**
- Modify: `src/builder/Toolbar.tsx:49-50` (`buttonClass`), `:161-233` (the row)

- [ ] **Step 1: Replace `buttonClass` with the shared token**

Delete the module-level `buttonClass` (lines 49-50) and import instead:

```tsx
import { inlineButtonClass } from '../ui/controls'

const buttonClass = inlineButtonClass()
```

This fixes C11 in passing: the name field and every button now share one height, where the field previously sat ~4px shorter.

- [ ] **Step 2: Group the actions**

Replace the `<span className="ml-auto flex items-center gap-1">…</span>` wrapper and its nine children with three groups separated by dividers:

```tsx
      <span className="ml-auto flex items-center gap-3">
        <span className="flex items-center gap-1">
          <button
            className={buttonClass}
            disabled={!canUndo}
            onClick={undo}
            title="Undo (⌘Z)"
            aria-label="Undo"
          >
            <Undo2 size={16} aria-hidden />
          </button>
          <button
            className={buttonClass}
            disabled={!canRedo}
            onClick={redo}
            title="Redo (⇧⌘Z)"
            aria-label="Redo"
          >
            <Redo2 size={16} aria-hidden />
          </button>
        </span>
        <span aria-hidden className="h-4 w-px bg-slate-200" />
        <span className="flex items-center gap-1">
          <button className={buttonClass} disabled={busy} onClick={fresh}>
            New
          </button>
          <button className={buttonClass} disabled={busy} onClick={() => setLoadOpen(true)}>
            Load
          </button>
          <button className={buttonClass} disabled={busy} onClick={() => void save()}>
            Save
          </button>
          <button className={buttonClass} disabled={busy} onClick={saveAs}>
            Save as
          </button>
          <button
            className={buttonClass}
            disabled={busy || serverId === null}
            title={serverId === null ? 'Save first' : 'Duplicate on the server and open the copy'}
            onClick={() => void duplicate()}
          >
            Duplicate
          </button>
        </span>
        <span aria-hidden className="h-4 w-px bg-slate-200" />
        <span className="flex items-center gap-1">
          <button
            className={buttonClass}
            disabled={busy}
            title="Download this experiment as a JSON file"
            onClick={exportDoc}
          >
            Export
          </button>
          <button
            className={buttonClass}
            disabled={busy}
            title="Import an experiment from a JSON file"
            onClick={() => fileRef.current?.click()}
          >
            Import
          </button>
        </span>
      </span>
```

Groups are history · document · transfer (spec §3). `gap-1` within a group, `gap-3` between, with a 1px divider — this costs no extra horizontal width versus the old uniform `gap-1`.

- [ ] **Step 3: Run the gate and commit**

Run: `cd webapp/frontend && npm run lint && npm test && npm run build`

```bash
git add webapp/frontend/src/builder/Toolbar.tsx
git commit -m "fix(studio): group toolbar actions into history, document and transfer"
```

---

## Task 9: Canvas add-button alignment and stable header heights

**Files:**
- Modify: `src/builder/Canvas.tsx` — `BlockView` header (~line 192), `ParallelLanes` lane header (~line 291) and `+ lane` (~line 310), `BranchLanes` else arm (~line 340)

- [ ] **Step 1: Make the `+ add else` placeholder a full-width block**

In `BranchLanes`, replace the `node.else === null` branch with a structure that mirrors the THEN arm exactly — same `<p>` header, same leading spacer as `BlockList`'s first `DropSlot` (`my-0.5 h-2`), and a full-width dashed button:

```tsx
          <>
            <p className="text-[10px] uppercase text-caption">else</p>
            <div className="flex flex-col">
              <div className="my-0.5 h-2" />
              <button
                onClick={(e) => {
                  e.stopPropagation()
                  patchBlock(node.uid, { else: [] })
                }}
                className="flex w-full items-center justify-center rounded border border-dashed border-slate-300 py-1.5 text-xs text-caption hover:border-slate-400 hover:text-slate-700"
              >
                <Plus size={12} aria-hidden className="mr-0.5" />add else
              </button>
            </div>
          </>
```

Three defects go at once: the button was inline-block (content width) beside full-width block cards; `mt-4` was a hand-tuned magic number standing in for the missing `else` header, so it never matched the real `text-[10px]` line box; and it omitted the leading `DropSlot` spacer that pushes the THEN arm's first card down. Full width is what makes it read as "this adds a block here", per the user's own suggestion.

- [ ] **Step 2: Stop the `+ lane` button drifting**

In `ParallelLanes`, the button's `self-center` explicitly opts out of the container's `items-stretch`, so it floats further off-centre the taller the lanes grow. Replace `self-center` with `self-stretch`:

```tsx
        className="m-1 flex shrink-0 items-center self-stretch rounded border border-dashed border-slate-300 bg-white px-2 text-xs text-caption hover:border-slate-400 hover:text-slate-600"
```

- [ ] **Step 3: Fix the header heights that change as lanes fill (C9)**

Both the lane header and the else header render an `IconButton` only conditionally, so the header band is 24px tall with the button and ~13px without — every block below shifts when a lane fills or empties. Pin the band. In `ParallelLanes`:

```tsx
            <div className="flex h-6 items-center justify-between px-1 text-[10px] uppercase text-caption">
```

and in `BranchLanes`' `else` header:

```tsx
            <p className="flex h-6 items-center justify-between text-[10px] uppercase text-caption">
```

For symmetry the THEN header and the `else` placeholder header from Step 1 must match, so give both the same band:

```tsx
        <p className="flex h-6 items-center text-[10px] uppercase text-caption">then</p>
```

(and the same `flex h-6 items-center` on the Step 1 `else` header).

- [ ] **Step 4: Reserve the chevron gutter on non-container cards (C10)**

In `BlockView`'s header row, container blocks get a leading 24px chevron and non-containers get nothing, so a `wait` card's label starts ~28px left of a `serial` card's in the same list. Reserve the space:

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

- [ ] **Step 5: Run the gate and commit**

Run: `cd webapp/frontend && npm run lint && npm test && npm run build`

```bash
git add webapp/frontend/src/builder/Canvas.tsx
git commit -m "fix(studio): align add-buttons with blocks and stabilise header heights"
```

---

## Task 10: One scroller, content-sized arms

**This is the increment's riskiest task** — it reverses part of W10's fix for audit finding F11. Do not batch it with anything else.

**Files:**
- Modify: `src/builder/Canvas.tsx` (`Canvas`, `ParallelLanes`, `BranchLanes`), `src/index.css` (delete the utility)

**Interfaces:**
- Consumes: `useScrollEdges`, `ScrollFades` (Task 4).

- [ ] **Step 1: Delete the background-based utility**

Remove the entire `@utility scroll-x-shadow { … }` block from `src/index.css` (lines 16-26), including its comment. Leaving a broken background-based fade in the stylesheet is how it comes back.

- [ ] **Step 2: Make the Canvas the single horizontal scroller**

Replace the `Canvas` component's returned markup:

```tsx
  const scrollRef = useRef<HTMLDivElement>(null)
  const edges = useScrollEdges(scrollRef)

  return (
    <DiagContext.Provider value={byUid}>
      <div className="relative min-w-0 flex-1">
        <div
          ref={scrollRef}
          className="h-full overflow-auto bg-slate-100 p-4"
          onClick={() => select(null)}
        >
          {/* w-max lets a wide subtree make the canvas scroll instead of clipping inside a
              nested box; min-w-full keeps a narrow doc filling the viewport. */}
          <div className="w-max min-w-full">
            <ScopeSwitcher />
            {activeTree.length === 0 && (
              <p className="mb-2 rounded border border-dashed border-slate-300 p-8 text-center text-sm text-caption">
                Drag blocks from the palette to start building.
              </p>
            )}
            <BlockList parentUid={null} slot="blocks" items={activeTree} />
          </div>
        </div>
        <ScrollFades edges={edges} from="from-slate-100" />
      </div>
    </DiagContext.Provider>
  )
```

Add to the imports: `useRef` from `react`, and `import { ScrollFades, useScrollEdges } from '../ui/ScrollX'`.

- [ ] **Step 3: Remove the nested scrollers and size arms to content**

`BranchLanes`' container — drop `overflow-x-auto scroll-x-shadow`:

```tsx
    <div className="flex gap-2 px-2 pb-2">
```

Both arms change from `min-w-48 flex-1` to `min-w-48 flex-auto`:

```tsx
      <div className="min-w-48 flex-auto">
```

`flex-1` is `flex: 1 1 0%` — a hard equal split that ignores content, which is why an empty ELSE arm claimed half the card. `flex-auto` is `flex: 1 1 auto`: the basis is the content's own width, and leftover space is still shared. So a light arm shrinks toward its `min-w-48` floor and a heavy arm gets the slack.

`ParallelLanes`' container — same removal:

```tsx
    <div className="flex items-stretch">
```

and its lanes from `min-w-48 flex-1` to `min-w-48 flex-auto`.

- [ ] **Step 4: Verify F11 has not regressed**

`BlockView`'s `min-w-0` (line ~187) **stays** — it was added for F11 to stop a card forcing its lane wide, and it is still correct. What changed is that the container is no longer a clipping scroller.

Load the committed torture fixture and check mechanically that nothing is clipped:

```bash
cd webapp/frontend && npm run dev
```

In a second shell, with the app open at the torture fixture, run in the browser console:

```js
// F11's condition, stated mechanically: content wider than its box under a non-scrolling
// overflow is content the user cannot reach.
Array.from(document.querySelectorAll('*'))
  .filter((el) => {
    const o = getComputedStyle(el).overflowX
    return (o === 'hidden' || o === 'clip') && el.scrollWidth > el.clientWidth + 1
  })
  .map((el) => `${el.tagName}.${el.className}`)
```

Expected: `[]`. Any entry is an F11 regression — fix it before committing rather than proceeding.

- [ ] **Step 5: Run the gate and commit**

Run: `cd webapp/frontend && npm run lint && npm test && npm run build`

```bash
git add webapp/frontend/src/builder/Canvas.tsx webapp/frontend/src/index.css
git commit -m "fix(studio): one canvas scroller with overlay fades, content-sized branch arms"
```

---

## Task 11: Adopt the control token everywhere else (C1–C8)

**Files:**
- Modify: `src/builder/StreamsPanel.tsx`, `src/builder/RolesPanel.tsx`, `src/builder/Palette.tsx`, `src/builder/StreamIntoPicker.tsx`, `src/builder/Canvas.tsx` (`ScopeSwitcher`), `src/builder/Inspector.tsx` (selects, unknown-param row), `src/records/RecordsTable.tsx`

Each site below is a separate assertion — a shared token that silently misses four sites leaves the app *more* inconsistent than before, not less.

- [ ] **Step 1: `Inspector.tsx` selects and the unknown-param row (C1, C2)**

Replace every `className="w-full rounded border border-slate-300 px-1 py-0.5 text-xs"` on a `<select>` in `Inspector.tsx` with `className={controlClass()}` (import from `../ui/controls`). There are several — the operator-input type select, the bool param select, and any others; grep for `<select` in the file and convert all of them.

For the unknown-param row (~line 428), the bare `<span className="flex-1 truncate font-mono text-xs">` sits ~16px tall beside a 24px `IconButton`. Give it the band:

```tsx
        <span className="flex h-6 flex-1 items-center truncate font-mono text-xs">
```

- [ ] **Step 2: `StreamsPanel.tsx` (C3, C4, C5)**

- The add-row button (~line 141) `rounded bg-slate-200 px-2 py-0.5` has no border and sits 2px short: replace its class with `inlineButtonClass()`.
- The units input (~line 109) is the app's only `border-slate-200` input: replace its class with `controlClass()` plus a width utility (`w-14`) — pass the width as a sibling class, e.g. `className={controlClass() + ' w-14'}`.
- The stream-name display button (~line 80) and its rename input (~line 91) must render at the same height or the row jumps on entering edit mode: give the display button `inlineButtonClass()` and the input `controlClass({ mono: true })`.
- The source `<span className="px-1">` gets `flex h-6 items-center px-1`.

- [ ] **Step 3: `RolesPanel.tsx` (C6)**

Same latent bug as C5. The display-mode button (~line 68) takes `inlineButtonClass()`; the edit-mode input (~line 79) takes `controlClass({ mono: true }) + ' w-28'`.

- [ ] **Step 4: `Palette.tsx` (C7)**

`AddRoleForm`'s button (~line 89) takes `inlineButtonClass()`; its input (~line 95) and select (~line 100) take `controlClass()`.

- [ ] **Step 5: `StreamIntoPicker.tsx` (C8)**

Its two inputs (~lines 49, 55) take `controlClass()`; its button (~line 60) takes `inlineButtonClass()`.

- [ ] **Step 6: `Canvas.tsx`'s `ScopeSwitcher` (A3)**

The `select` (~line 92) takes `controlClass() + ' w-auto'`; the group-name input (~line 117) takes `controlClass({ mono: true }) + ' w-28'`; the `Add` button (borderless, 2px short) takes `inlineButtonClass()`; the bare-text `cancel` button takes `inlineButtonClass({ subtle: true })`; and `New group…` takes `inlineButtonClass({ subtle: true })`.

- [ ] **Step 7: `RecordsTable.tsx`**

`NameCell`'s rename input (~line 38) takes `controlClass()`.

- [ ] **Step 8: Verify no height scale survived**

Run:

```bash
cd webapp/frontend && grep -rn "px-2 py-1\|px-1 py-0.5\|px-1.5 py-0.5\|bg-slate-200 px-2" src/ --include='*.tsx' | grep -v "AutoGrowTextArea\|TextAreaField"
```

Expected: no hits on `<input>`, `<select>`, or `<button>` elements. Textareas legitimately keep `py-0.5` (they are multi-line by definition). Any remaining hit is a missed C-site — convert it.

- [ ] **Step 9: Run the gate and commit**

Run: `cd webapp/frontend && npm run lint && npm test && npm run build`

```bash
git add webapp/frontend/src
git commit -m "fix(studio): adopt the control-height token across every panel"
```

---

## Task 12: Remaining dismissal sites

**Files:**
- Modify: `src/builder/StreamIntoPicker.tsx`, `src/builder/Canvas.tsx` (`ScopeSwitcher`)

- [ ] **Step 1: Give `StreamIntoPicker`'s adding mode an exit**

This is the worst dismissal case in the app: once the `__new__` option opens the inline form, there is **no** exit at all — not Escape, not outside click, not a cancel button. Only a successful `create()` closes it.

Wrap the adding form in the hook's ref and reset the picker on dismiss:

```tsx
import { useDismissable } from '../ui/useDismissable'

// inside the component, alongside the existing `adding` state:
  const wrapRef = useDismissable(adding, () => setAdding(false))
```

Wrap the adding-mode markup in `<div ref={wrapRef} className="flex items-center gap-1">…</div>`, and add an explicit cancel button beside `create` so the exit is visible and not only discoverable:

```tsx
          <button type="button" onClick={() => setAdding(false)} className={inlineButtonClass({ subtle: true })}>
            cancel
          </button>
```

- [ ] **Step 2: Give the group creator outside-click dismissal**

`ScopeSwitcher` already handles Escape and has a visible `cancel`; it lacks only the outside-click half. Extract its reset into a named callback and attach the hook:

```tsx
  const cancelAdding = () => {
    setAdding(false)
    setName('')
    setError(null)
  }
  const addingRef = useDismissable(adding, cancelAdding)
```

Attach `ref={addingRef}` to the `<div className="flex items-center gap-1">` that wraps the input and its two buttons, and replace the bodies of the existing Escape handler and `cancel` button with `cancelAdding()`.

- [ ] **Step 3: Run the gate and commit**

Run: `cd webapp/frontend && npm run lint && npm test && npm run build`

```bash
git add webapp/frontend/src/builder/StreamIntoPicker.tsx webapp/frontend/src/builder/Canvas.tsx
git commit -m "fix(studio): inline adding modes dismiss on outside click and Escape"
```

---

## Task 13: Commit the capture harness with a sibling-height rule

The audit's probe and capture scripts lived in scratchpad and were lost. The user audits this UI by hand and will again; a throwaway harness makes that manual every time.

**Files:**
- Create: `tools/probe.mjs`, `tools/probe-selftest.html`, `tools/probe-selftest.mjs`, `tools/capture.mjs`, `tools/README.md`
- Modify: `package.json` (add `playwright` devDependency and two scripts)

- [ ] **Step 1: Add Playwright**

```bash
cd webapp/frontend && npm install -D playwright && npx playwright install chromium
```

Add to `package.json` scripts:

```json
    "probe:selftest": "node tools/probe-selftest.mjs",
    "capture": "node tools/capture.mjs"
```

- [ ] **Step 2: Write the probe with the new rule**

Create `tools/probe.mjs` exporting an in-page function returning `Violation[]`, where `Violation = {rule, selector, detail}`. Implement four rules:

```js
/** Rules run inside the page via page.evaluate(). Keep this a single pure function with no
 * imports — it is serialised into the browser. */
export function probeRules() {
  const out = []
  const cssPath = (el) => {
    const parts = []
    for (let n = el; n && n.nodeType === 1 && parts.length < 4; n = n.parentElement) {
      parts.unshift(n.tagName.toLowerCase() + (n.className ? '.' + String(n.className).trim().split(/\s+/).join('.') : ''))
    }
    return parts.join(' > ')
  }

  // R1 — clipped overflow: content wider than its box under a non-scrolling overflow.
  for (const el of document.querySelectorAll('*')) {
    const o = getComputedStyle(el).overflowX
    if ((o === 'hidden' || o === 'clip') && el.scrollWidth > el.clientWidth + 1) {
      out.push({ rule: 'clipped-overflow', selector: cssPath(el), detail: `${el.scrollWidth} > ${el.clientWidth}` })
    }
  }

  // R2 — truncate without title: an ellipsised label with no hover text is unreadable.
  for (const el of document.querySelectorAll('*')) {
    if (getComputedStyle(el).textOverflow === 'ellipsis' && el.scrollWidth > el.clientWidth + 1 && !el.title) {
      out.push({ rule: 'truncate-without-title', selector: cssPath(el), detail: el.textContent?.slice(0, 40) ?? '' })
    }
  }

  // R3 — tiny target: interactive controls below the 24px hit-area floor.
  for (const el of document.querySelectorAll('button, a[href], input, select, textarea')) {
    const r = el.getBoundingClientRect()
    if (r.width > 0 && (r.height < 23.5 || r.width < 23.5) && el.tagName === 'BUTTON') {
      out.push({ rule: 'tiny-target', selector: cssPath(el), detail: `${Math.round(r.width)}x${Math.round(r.height)}` })
    }
  }

  // R4 — sibling controls disagree about height. THIS IS THE NEW RULE (spec §5): the audit
  // had no rule for it, which is why all twelve C-sites shipped in 0.8.0.
  for (const row of document.querySelectorAll('*')) {
    const s = getComputedStyle(row)
    if (s.display !== 'flex' || s.flexDirection.startsWith('column')) continue
    if (s.alignItems === 'stretch') continue // stretch makes heights agree by definition
    const controls = Array.from(row.children).filter((c) =>
      ['BUTTON', 'INPUT', 'SELECT'].includes(c.tagName),
    )
    if (controls.length < 2) continue
    const hs = controls.map((c) => c.getBoundingClientRect().height).filter((h) => h > 0)
    if (hs.length < 2) continue
    const spread = Math.max(...hs) - Math.min(...hs)
    if (spread > 1) {
      out.push({ rule: 'sibling-height-mismatch', selector: cssPath(row), detail: `spread ${spread.toFixed(1)}px` })
    }
  }

  return out
}
```

- [ ] **Step 3: Write the self-test page with one planted violation per rule**

Create `tools/probe-selftest.html` with exactly four planted violations and at least two traps that must **not** fire:

```html
<meta charset="utf-8" />
<title>probe self-test</title>
<style>
  .clip { overflow-x: hidden; width: 50px; }
  .clip > span { display: inline-block; width: 200px; }
  .trunc { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; width: 40px; }
  .row { display: flex; align-items: center; }
  .row input { height: 22px; }
  .row button { height: 26px; }
  .okrow { display: flex; align-items: center; }
  .okrow input, .okrow button { height: 24px; }
</style>

<!-- PLANT R1 -->
<div class="clip"><span>wide content that cannot be reached</span></div>
<!-- PLANT R2 -->
<div class="trunc">a label long enough to be ellipsised</div>
<!-- PLANT R3 -->
<button style="height:16px;width:16px">x</button>
<!-- PLANT R4 -->
<div class="row"><input /><button>go</button></div>

<!-- TRAP: scrollable overflow is reachable, must NOT fire R1 -->
<div style="overflow-x:auto;width:50px"><span style="display:inline-block;width:200px">ok</span></div>
<!-- TRAP: truncation WITH a title is fine, must NOT fire R2 -->
<div class="trunc" title="full text here">a label long enough to be ellipsised</div>
<!-- TRAP: matching heights must NOT fire R4 -->
<div class="okrow"><input /><button>go</button></div>
```

- [ ] **Step 4: Write the self-test runner**

Create `tools/probe-selftest.mjs`:

```js
import { chromium } from 'playwright'
import { fileURLToPath } from 'node:url'
import { probeRules } from './probe.mjs'

const url = fileURLToPath(new URL('./probe-selftest.html', import.meta.url))
const browser = await chromium.launch()
const page = await browser.newPage()
await page.goto(`file://${url}`)
const found = await page.evaluate(probeRules)
await browser.close()

const rules = [...new Set(found.map((v) => v.rule))].sort()
const expected = ['clipped-overflow', 'sibling-height-mismatch', 'tiny-target', 'truncate-without-title']

// An untested probe reporting zero violations is indistinguishable from a working app, and
// is MORE dangerous than no probe. It must be proven to find planted bugs before its
// silence means anything.
const missing = expected.filter((r) => !rules.includes(r))
if (missing.length) {
  console.error(`FAIL — probe missed planted violations: ${missing.join(', ')}`)
  process.exit(1)
}
const counts = Object.fromEntries(expected.map((r) => [r, found.filter((v) => v.rule === r).length]))
const overfired = expected.filter((r) => counts[r] !== 1)
if (overfired.length) {
  console.error(`FAIL — expected exactly one hit per rule, got ${JSON.stringify(counts)} (traps firing?)`)
  process.exit(1)
}
console.log('PASS — probe found exactly the planted set:', JSON.stringify(counts))
```

- [ ] **Step 5: Run the self-test — it must PASS**

Run: `cd webapp/frontend && npm run probe:selftest`
Expected: `PASS — probe found exactly the planted set: {"clipped-overflow":1,...}`

- [ ] **Step 6: Mutation-verify the new rule**

Temporarily change `.row button { height: 26px }` to `height: 22px` in the self-test page and re-run.
Expected: **FAIL**, reporting `sibling-height-mismatch` missing. Revert the change and confirm PASS again. A rule that has never gone red proves nothing.

- [ ] **Step 7: Write `capture.mjs` and the README**

Create `tools/capture.mjs` driving the dev server across the states behind the user's screenshots (morbidostat doc loaded; a branch selected; the Inspector on an operator-input block; the expression popover open; the torture fixture) at viewports 1024×720, 1440×900, 1920×1080 — writing PNGs plus `probe.json` to a directory given as `--out`. Document both scripts in `tools/README.md`, including the prerequisite that the dev server is already running.

- [ ] **Step 8: Commit**

```bash
git add webapp/frontend/tools webapp/frontend/package.json webapp/frontend/package-lock.json
git commit -m "test(studio): commit the capture harness with a sibling-height probe rule"
```

---

## Task 14: Evidence, project rule, and preprod

**Files:**
- Create: `docs/ui-improvements/after/`
- Modify: `webapp/frontend/CLAUDE.md`

- [ ] **Step 1: Capture after-shots**

Run the dev server, then `npm run capture -- --out ../../docs/ui-improvements/after`. Check each of the six findings against its original screenshot in `docs/ui-improvements/screenshots/`. A finding is closed when its after-shot shows the fix **at all three widths** — not when the diff looks right.

- [ ] **Step 2: Confirm the probe is clean on the real app**

Inspect the emitted `probe.json`. Expected: zero `sibling-height-mismatch` and zero `clipped-overflow` rows. Any row is a missed C-site or an F11 regression — fix it before proceeding.

- [ ] **Step 3: Document the token as a project rule**

Add to `webapp/frontend/CLAUDE.md`, after the Icons section:

```markdown
## Control height

- Every text input, select, and inline button renders at **24px** via `controlClass()` /
  `inlineButtonClass()` from `src/ui/controls.ts`, matching `IconButton`'s hit-area floor.
  Height belongs in that module and nowhere else — a component needing a different height
  is a bug in the component. Four competing height scales shipped in 0.8.0 and left twelve
  visibly crooked rows (docs/superpowers/specs/2026-07-18-experiment-studio-ui-improvements-design.md, cause C-A).
- Textareas are exempt from the fixed height (they are multi-line by definition) but share
  the same border and padding.
```

- [ ] **Step 4: Commit**

```bash
git add docs/ui-improvements/after webapp/frontend/CLAUDE.md
git commit -m "docs(studio): W11 after-shots and the control-height project rule"
```

- [ ] **Step 5: Build and push the image, then deploy to preprod**

```bash
docker build -f webapp/Dockerfile -t ghcr.io/bioexperiment-lab-devices/experiment-studio:0.9.0-rc1 .
docker push ghcr.io/bioexperiment-lab-devices/experiment-studio:0.9.0-rc1
```

In `/Users/khamit/lab_devices_server`, set `studio_image` in `compose/pins.yaml` to the new tag (it currently pins `0.8.0`), then `task deploy`.

- [ ] **Step 6: Confirm on preprod against a real document**

Open the Studio on preprod with `windows_arm64_test_client` and the real morbidostat doc.

Preprod is where findings #5b and #4 must be confirmed, because both depend on real content: a real morbidostat doc has the deep nesting that made inner content unreachable and the long prompts that made a one-line field unusable. **A synthetic fixture can be made to pass either fix by accident.** Specifically confirm:

1. The nested branch inside `tube 1: service` shows its inner blocks without a nested scroller, and the canvas scrolls horizontally if the tree is wider than the viewport.
2. The `drug_stock_x_mic` prompt wraps to several lines and is fully readable.
3. The expression popover closes on an outside click and on Escape.
4. No fade appears at an edge that is already fully scrolled.

- [ ] **Step 7: Open the PR**

```bash
git push -u origin worktree-ui-improvements
gh pr create --title "fix(studio): W11 UI improvements" --body "$(cat <<'EOF'
Fixes the six hand-found UI defects in `docs/ui-improvements/improvements.md` by fixing the three shared causes underneath them.

## Causes
- **No control-height token** — four competing height scales left twelve visibly crooked rows. Now one 24px token in `src/ui/controls.ts`.
- **The scroll fade was a `background`** — so it rendered *behind* the block cards and survived only in the gutters, reading as an artifact. Now an overlay, shown per-edge only while content continues that way.
- **Rigid 50/50 branch arms + nested scrollers** — an empty ELSE arm claimed half the card while THEN's content scrolled in a cramped box. Arms now size to content; the canvas is the single scroller.

## Findings
| # | Fix |
|---|---|
| 1 | Overlay fade, per-edge conditional; `scroll-x-shadow` deleted |
| 2 | Toolbar grouped history / document / transfer with dividers |
| 3 | `+ add` buttons full-width and block-aligned; `ƒ` glyph → Lucide `SquareFunction` |
| 4 | Auto-growing textareas at all 10 long-text sites; expressions soft-wrap, newlines stripped |
| 5 | Inspector summary pinned to the bottom; branch arms content-sized |
| 6 | `useDismissable` on the popover and both inline adding modes |

Plus twelve bonus alignment sites the sweeps found (C1–C11, A4).

## Verification
- Pure logic unit-tested in the node-env vitest setup: `autoGrowHeight`, `collapseNewlines`, `scrollEdges`, `shouldDismiss`.
- The capture harness is now **committed** under `webapp/frontend/tools/` rather than left in scratchpad, with a new `sibling-height-mismatch` probe rule that is mutation-verified.
- Before/after evidence at 1024/1440/1920 in `docs/ui-improvements/after/`.
- Confirmed on lab-bridge preprod against the real morbidostat doc.

Design: `docs/superpowers/specs/2026-07-18-experiment-studio-ui-improvements-design.md`
Plan: `docs/superpowers/plans/2026-07-18-experiment-studio-11-ui-improvements.md`

🤖 Generated with [Claude Code](https://claude.com/claude-code)

https://claude.ai/code/session_01DB6hMCu2MhkdTuzL252t2u
EOF
)"
```

- [ ] **Step 8: Merge when CI is green**

```bash
gh pr checks --watch && gh pr merge --squash
```

---

## Self-Review

**Spec coverage.** Every spec section maps to a task: §4.1's four primitives → Tasks 1-4; §4.2's six findings → Tasks 5-10; §4.3's twelve bonus sites → Tasks 6 (A4), 9 (C9, C10), 11 (C1-C8), 8 (C11); §5's testing → the pure tests in Tasks 1-5 plus Task 13's mutation-verified rule; §6's verification → Tasks 13-14; §7's F11 risk → Task 10 Step 4 and Task 14 Step 6; §8's deliverables → all fourteen tasks.

**Known gap, accepted:** Task 13 Step 7 (`capture.mjs`) describes the states and viewports rather than showing full code, because the exact selectors depend on the DOM as it stands *after* Tasks 1-12 land. The implementer writes it against the finished app. Every other code step is complete.

**Type consistency.** `controlClass`/`inlineButtonClass` (Task 1) are consumed with the same signatures in Tasks 5, 6, 8, 11, 12. `AutoGrowTextArea`'s props (Task 2) match every call site in Tasks 5-7 (`fillParent` used only in Task 7, `singleLine`/`maxLines` only in Task 5). `useDismissable(open, onClose)` (Task 3) is called identically in Tasks 5 and 12. `scrollEdges`/`useScrollEdges`/`ScrollFades` (Task 4) are consumed only in Task 10, with `ScrollEdges` as the shared type. `collapseNewlines` lives in `src/ui/autoGrow.ts` and is imported only by its neighbour `AutoGrowTextArea` — deliberately **not** in `builder/params.ts`, so that `src/ui/` never imports from a feature module.
