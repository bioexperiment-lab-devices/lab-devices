# Inspector Form Structure (W15) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Re-cut the Inspector's per-block settings form so grouping and order follow author intent instead of the order the code was written.

**Architecture:** Every block form becomes three regions — an always-first `Label` row, the kind's own fields unheaded, then up to two collapsible tail sections (`Timing`, `On failure`) that render only when they have eligible fields and auto-open when they hold a non-default value. All membership and summary logic moves into pure functions in `builder/inspectorRules.ts`, because vitest here runs node-env with no component rendering and anything left in `Inspector.tsx` is untestable by construction.

**Tech Stack:** React 19.2, TypeScript (strict, `erasableSyntaxOnly` + `verbatimModuleSyntax`), Tailwind 4, vitest 4 (node env), lucide-react, Playwright probe harness.

Spec: `docs/superpowers/specs/2026-07-18-inspector-form-structure-design.md`

## Global Constraints

- **vitest runs in node env: pure functions only.** No component rendering, no jsdom, no `@testing-library`. DOM wiring is verified by the probe harness, never by vitest.
- **Never concatenate a layout class onto a control helper.** `controlClass()`, `inlineButtonClass()` and friends bake classes that are equal-specificity Tailwind utilities in the same `@layer utilities` block; an appended class loses to compiled declaration order, silently. Add an **option** that *selects* the class instead. This applies to every property, not just width (W12 reintroduced it in `text-color`).
- **Control height lives only in `src/ui/controls.ts`,** via the `CONTROL_H = 'h-6'` token. A component needing a different height is a bug in the component.
- **Meaning-carrying secondary text uses `text-caption`; incidental text uses `text-hint`.** Never raw `text-slate-400` or lighter on meaningful text.
- **Interactive icons come from lucide-react only,** rendered through `IconButton` when icon-only. Decorative icons inside a labeled button carry `aria-hidden`.
- **No document-shape change.** `convert.ts` and `tree.ts` are untouched; open-then-save stays a byte no-op.
- Frontend gate (run from `webapp/frontend`): `npm run lint && npm run typecheck && npm test -- --run && npm run build`. Known oxlint fast-refresh warnings (4 as of this branch: StreamChart, IconButton, icons, ScrollX) are expected; exit 0 is the pass condition.

---

### Task 1: Section membership as exhaustive pure functions

**Files:**
- Modify: `webapp/frontend/src/builder/inspectorRules.ts`
- Test: `webapp/frontend/src/builder/inspectorRules.test.ts`

**Interfaces:**
- Consumes: `BlockNode` from `./tree` (already imported by this module).
- Produces:
  - `export type TimingField = 'gapAfter' | 'startOffset'`
  - `export type FailureField = 'onError' | 'retry'`
  - `export function timingFields(kind: BlockNode['kind'], parentKind: BlockNode['kind'] | null): TimingField[]`
  - `export function failureFields(kind: BlockNode['kind']): FailureField[]`
  - An empty array means "do not render this section at all."

- [ ] **Step 1: Write the failing tests**

Append to `webapp/frontend/src/builder/inspectorRules.test.ts` (keep the existing `gapAfterEligible` describe block and add `timingFields`, `failureFields` to the import on line 2):

```ts
describe('timingFields', () => {
  it('offers gap after wherever the shared runner honors it', () => {
    expect(timingFields('wait', null)).toEqual(['gapAfter'])
    expect(timingFields('wait', 'serial')).toEqual(['gapAfter'])
    expect(timingFields('command', 'loop')).toEqual(['gapAfter'])
  })
  it('offers start offset only to a child of a parallel, which has no next-in-list', () => {
    expect(timingFields('wait', 'parallel')).toEqual(['startOffset'])
    expect(timingFields('serial', 'parallel')).toEqual(['startOffset'])
  })
  it('offers nothing for for_each, a splice with no runtime block to carry the keys', () => {
    // expand.py:26 _FOR_EACH_FORBIDDEN — an empty list means the section does not render.
    expect(timingFields('for_each', null)).toEqual([])
    expect(timingFields('for_each', 'parallel')).toEqual([])
  })
})

describe('failureFields', () => {
  it('offers on error plus retry to the two device-touching kinds', () => {
    expect(failureFields('command')).toEqual(['onError', 'retry'])
    expect(failureFields('measure')).toEqual(['onError', 'retry'])
  })
  it('offers on error alone to every other kind that can tolerate a failure', () => {
    expect(failureFields('wait')).toEqual(['onError'])
    expect(failureFields('alarm')).toEqual(['onError'])
    expect(failureFields('parallel')).toEqual(['onError'])
    // group_ref is NOT restricted — only for_each appears in _FOR_EACH_FORBIDDEN.
    expect(failureFields('group_ref')).toEqual(['onError'])
  })
  it('offers nothing to abort or for_each, so neither renders the section', () => {
    // abort: tolerating a safety stop is a contradiction (engine design 2026-07-16 §5.1).
    expect(failureFields('abort')).toEqual([])
    // for_each: expand.py:26 forbids retry and on_error along with the timing keys.
    expect(failureFields('for_each')).toEqual([])
  })
})
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd webapp/frontend && npx vitest run src/builder/inspectorRules.test.ts
```

Expected: FAIL — `timingFields is not a function` / no exported member `timingFields`.

- [ ] **Step 3: Implement**

Append to `webapp/frontend/src/builder/inspectorRules.ts`:

```ts
/** The tail sections' membership (design 2026-07-18 §3.3). An EMPTY array means the section
 * is not rendered at all — that is how `for_each` ends up with no tail and `abort` with no
 * "On failure", which states each engine rule better than a disabled control would. */
export type TimingField = 'gapAfter' | 'startOffset'
export type FailureField = 'onError' | 'retry'

export function timingFields(
  kind: BlockNode['kind'],
  parentKind: BlockNode['kind'] | null,
): TimingField[] {
  const fields: TimingField[] = []
  if (gapAfterEligible(kind, parentKind)) fields.push('gapAfter')
  // start_offset positions a lane against the parallel's own start, so it is meaningful
  // only for a direct child of a parallel — and never for a for_each, which is spliced
  // away before there is a runtime block to offset (expand.py:26).
  if (kind !== 'for_each' && parentKind === 'parallel') fields.push('startOffset')
  return fields
}

/** A Record, not a set membership check: a fifteenth kind is then a COMPILE error until it
 * declares its failure policy. W12 proved the difference — a hand-maintained array of kinds
 * silently defaults a new kind to the wrong bucket and the test still passes. */
const FAILURE_POLICY: Record<BlockNode['kind'], FailureField[]> = {
  command: ['onError', 'retry'],
  measure: ['onError', 'retry'],
  operator_input: ['onError'],
  wait: ['onError'],
  serial: ['onError'],
  parallel: ['onError'],
  loop: ['onError'],
  branch: ['onError'],
  compute: ['onError'],
  record: ['onError'],
  alarm: ['onError'],
  group_ref: ['onError'],
  abort: [],
  for_each: [],
}

export function failureFields(kind: BlockNode['kind']): FailureField[] {
  return FAILURE_POLICY[kind]
}
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
cd webapp/frontend && npx vitest run src/builder/inspectorRules.test.ts && npm run typecheck
```

Expected: PASS, all describe blocks green; typecheck exits 0.

- [ ] **Step 5: Commit**

```bash
git add webapp/frontend/src/builder/inspectorRules.ts webapp/frontend/src/builder/inspectorRules.test.ts
git commit -m "feat(studio): section membership rules for the Inspector tail"
```

---

### Task 2: Collapsed-header summaries

**Files:**
- Modify: `webapp/frontend/src/builder/inspectorRules.ts`
- Test: `webapp/frontend/src/builder/inspectorRules.test.ts`

**Interfaces:**
- Consumes: `timingFields` / `failureFields` from Task 1; `BlockNode` from `./tree`.
- Produces:
  - `export function timingSummary(node: BlockNode, parentKind: BlockNode['kind'] | null): string | null`
  - `export function failureSummary(node: BlockNode): string | null`
  - Both return `null` when every field is at its default. **`summary !== null` IS the auto-open predicate** — there is no separate predicate function, so the two can never disagree.

Both summaries only report fields the section actually renders: a node carrying a `gapAfter` while sitting in a parallel lane (ineligible there) must not advertise a control the section does not show.

- [ ] **Step 1: Write the failing tests**

Append to `webapp/frontend/src/builder/inspectorRules.test.ts` (extend the line 2 import with `timingSummary`, `failureSummary`, and add `import type { BlockNode } from './tree'` plus `import type { RetryJson } from '../types/doc'`):

```ts
/** Minimal NodeBase-shaped fixture. The parameter is spelled out field by field rather than
 * as `Partial<BlockNode>`: BlockNode is a union, and both `Partial` and `Pick` distribute
 * over unions, so the derived type would admit a `kind: 'wait'` carrying a Command's payload.
 * These tests exercise only the block-level keys every kind shares, so the explicit shape is
 * both safer and clearer. The cast is confined to this one boundary. */
const node = (over: {
  kind: BlockNode['kind']
  gapAfter?: string | null
  startOffset?: string | null
  onError?: 'fail' | 'continue'
  retry?: RetryJson
}): BlockNode =>
  ({ uid: 'u1', label: null, gapAfter: null, startOffset: null, ...over }) as BlockNode

describe('timingSummary', () => {
  it('is null when nothing is set, which is what keeps the section collapsed', () => {
    expect(timingSummary(node({ kind: 'wait' }), null)).toBeNull()
  })
  it('names each set value so a collapsed section still shows what it holds', () => {
    expect(timingSummary(node({ kind: 'wait', gapAfter: '30s' }), null)).toBe('gap after 30s')
    expect(timingSummary(node({ kind: 'wait', startOffset: '5min' }), 'parallel')).toBe('start +5min')
    expect(
      timingSummary(node({ kind: 'wait', gapAfter: '30s', startOffset: '5min' }), 'parallel'),
    ).toBe('start +5min')
  })
  it('ignores a value whose field this section does not render', () => {
    // gapAfter survives in the doc when a block is moved into a parallel lane, but the
    // section has no control for it there — advertising it would point at nothing.
    expect(timingSummary(node({ kind: 'wait', gapAfter: '30s' }), 'parallel')).toBeNull()
  })
})

describe('failureSummary', () => {
  it('is null at the engine default (on_error: fail, no retry)', () => {
    expect(failureSummary(node({ kind: 'command' }))).toBeNull()
    expect(failureSummary(node({ kind: 'command', onError: 'fail' }))).toBeNull()
  })
  it('reports a tolerated failure and the retry count', () => {
    expect(failureSummary(node({ kind: 'command', onError: 'continue' }))).toBe('continue')
    expect(failureSummary(node({ kind: 'command', retry: { attempts: 3 } }))).toBe('retry ×3')
    expect(
      failureSummary(node({ kind: 'command', onError: 'continue', retry: { attempts: 3 } })),
    ).toBe('continue, retry ×3')
  })
  it('ignores a retry left on a kind that does not render the control', () => {
    expect(failureSummary(node({ kind: 'wait', retry: { attempts: 3 } }))).toBeNull()
  })
})
```

Note on the third `timingSummary` case: with `parentKind: 'parallel'` only `startOffset` is eligible, so a set `gapAfter` is deliberately not reported.

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd webapp/frontend && npx vitest run src/builder/inspectorRules.test.ts
```

Expected: FAIL — no exported member `timingSummary`.

- [ ] **Step 3: Implement**

Append to `webapp/frontend/src/builder/inspectorRules.ts`:

```ts
/** Collapsed-header summary (design §4). Returning `null` for "all defaults" means the
 * caller's open-by-default test is exactly `summary !== null`, so the disclosure state and
 * the text describing it are derived from one expression and cannot drift apart.
 *
 * Each summary filters through its own membership function, so it can only ever mention a
 * control the section actually renders. */
export function timingSummary(
  node: BlockNode,
  parentKind: BlockNode['kind'] | null,
): string | null {
  const fields = timingFields(node.kind, parentKind)
  const parts: string[] = []
  if (fields.includes('gapAfter') && node.gapAfter !== null) parts.push(`gap after ${node.gapAfter}`)
  if (fields.includes('startOffset') && node.startOffset !== null) {
    parts.push(`start +${node.startOffset}`)
  }
  return parts.length > 0 ? parts.join(', ') : null
}

export function failureSummary(node: BlockNode): string | null {
  const fields = failureFields(node.kind)
  const parts: string[] = []
  // 'fail' is the engine default, so only 'continue' is worth surfacing.
  if (fields.includes('onError') && node.onError === 'continue') parts.push('continue')
  if (fields.includes('retry') && node.retry !== undefined) {
    parts.push(`retry ×${node.retry.attempts}`)
  }
  return parts.length > 0 ? parts.join(', ') : null
}
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
cd webapp/frontend && npx vitest run src/builder/inspectorRules.test.ts && npm run typecheck
```

Expected: PASS; typecheck exits 0.

- [ ] **Step 5: Commit**

```bash
git add webapp/frontend/src/builder/inspectorRules.ts webapp/frontend/src/builder/inspectorRules.test.ts
git commit -m "feat(studio): collapsed-header summaries for the Inspector tail"
```

---

### Task 3: The collapsible section control

**Files:**
- Modify: `webapp/frontend/src/ui/controls.ts`
- Test: `webapp/frontend/src/ui/controls.test.ts`
- Create: `webapp/frontend/src/builder/InspectorSection.tsx`

**Interfaces:**
- Consumes: `CONTROL_H` from `../ui/controls`.
- Produces:
  - `export function sectionHeaderClass(): string` in `src/ui/controls.ts`
  - `export function InspectorSection(props: { title: string; summary: string | null; children: ReactNode })` in `src/builder/InspectorSection.tsx`

**Why a new helper rather than `inlineButtonClass({ subtle: true, width: 'w-full' })`:** the header must be left-aligned and borderless. `inlineButtonClass` bakes `justify-center` and a border, and `justify-start` / `justify-center` are equal-specificity utilities in the same `@layer utilities` block — appending `justify-start` loses to compiled declaration order and the header renders centred while looking correct in source. This is the exact cascade trap in the Global Constraints. A dedicated helper emits one alignment class and has no cascade fight to lose. It carries `CONTROL_H` so the header measures 24px like every control it sits above, keeping probe rule R4 satisfied.

- [ ] **Step 1: Write the failing test**

Append to `webapp/frontend/src/ui/controls.test.ts`:

```ts
describe('sectionHeaderClass', () => {
  it('carries the shared control height so it lines up with the fields below it', () => {
    expect(sectionHeaderClass()).toContain('h-6')
  })
  it('is left-aligned and emits no competing justify utility', () => {
    const cls = sectionHeaderClass()
    expect(cls).toContain('justify-start')
    // The cascade trap: two justify-* utilities in one class string means the compiled
    // stylesheet order decides, not this string's order.
    expect(cls).not.toContain('justify-center')
  })
  it('uses text-caption, since the header names a real setting group', () => {
    expect(sectionHeaderClass()).toContain('text-caption')
  })
})
```

Add `sectionHeaderClass` to the existing import at the top of the file.

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd webapp/frontend && npx vitest run src/ui/controls.test.ts
```

Expected: FAIL — no exported member `sectionHeaderClass`.

- [ ] **Step 3: Implement the helper**

Append to `webapp/frontend/src/ui/controls.ts`:

```ts
/** The Inspector's collapsible tail-section header (design 2026-07-18 §3.3).
 *
 * Borderless and left-aligned, so it reads as a section heading rather than a push button —
 * which is what distinguishes it from the body's plain `PARAMS`/`ARGS` sub-labels, whose
 * ambiguity with the old `h3` headers is part of what this increment removes.
 *
 * It exists as its own helper rather than as options bolted onto `inlineButtonClass` because
 * that one bakes `justify-center` and a border: appending `justify-start` would lose the
 * cascade silently (equal specificity, same `@layer utilities`, compiled order decides). One
 * helper, one alignment class, no fight to lose.
 *
 * Carries CONTROL_H: the header shares a column with 24px inputs and selects, and the probe's
 * sibling-height-mismatch rule holds that column to ≤1px. */
export function sectionHeaderClass(): string {
  return (
    `${CONTROL_H} flex w-full items-center justify-start gap-1 rounded px-1 ` +
    'text-xs font-semibold uppercase text-caption hover:bg-slate-100'
  ).trim()
}
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
cd webapp/frontend && npx vitest run src/ui/controls.test.ts
```

Expected: PASS.

- [ ] **Step 5: Create the component**

Create `webapp/frontend/src/builder/InspectorSection.tsx`:

```tsx
import { ChevronDown, ChevronRight } from 'lucide-react'
import { useState, type ReactNode } from 'react'
import { sectionHeaderClass } from '../ui/controls'

/** A collapsible tail section of the block form (design 2026-07-18 §4).
 *
 * Collapsed by default, EXCEPT when `summary` is non-null — a section holding a non-default
 * value opens itself. The caller passes `timingSummary(...)`/`failureSummary(...)`, whose
 * null-means-all-defaults contract makes `summary !== null` the whole auto-open rule.
 *
 * Collapsing a section that holds a value is allowed, because the collapsed header renders
 * that value. The promise is that a configured value is never HIDDEN, not that a section is
 * never closed — locking a non-default section open would trade an honest affordance for a
 * control that mysteriously refuses to work.
 *
 * Open state is deliberately NOT lifted or persisted: `Inspector` mounts `BlockForm` with
 * `key={node.uid}`, so selecting another block remounts this and the auto-open computation
 * re-runs against the new node. No disclosure state carries between blocks, and two people
 * looking at one document see the same panel. */
export function InspectorSection(props: {
  title: string
  summary: string | null
  children: ReactNode
}) {
  const [open, setOpen] = useState(props.summary !== null)
  const Chevron = open ? ChevronDown : ChevronRight
  return (
    <div className="mt-2 border-t border-slate-200 pt-2">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen(!open)}
        className={sectionHeaderClass()}
      >
        <Chevron size={12} aria-hidden className="shrink-0" />
        <span className="shrink-0">{props.title}</span>
        {!open && props.summary !== null && (
          <span
            title={props.summary}
            className="min-w-0 truncate font-normal normal-case text-caption"
          >
            · {props.summary}
          </span>
        )}
      </button>
      {open && <div className="pt-1">{props.children}</div>}
    </div>
  )
}
```

The `title` sits ON the truncating span, not on the parent button: probe rule R2 checks that an ellipsised element is reachable via hover text, and a `title` on the parent reads fine to a human reviewer but fires R2 (W13 trap).

- [ ] **Step 6: Verify it compiles and lints**

```bash
cd webapp/frontend && npm run typecheck && npm run lint
```

Expected: typecheck exits 0; lint exits 0 with at most the two known fast-refresh warnings.

- [ ] **Step 7: Commit**

```bash
git add webapp/frontend/src/ui/controls.ts webapp/frontend/src/ui/controls.test.ts webapp/frontend/src/builder/InspectorSection.tsx
git commit -m "feat(studio): collapsible Inspector section control"
```

---

### Task 4: Restructure BlockForm

**Files:**
- Modify: `webapp/frontend/src/builder/Inspector.tsx:149-214` (the `BlockForm` function)

**Interfaces:**
- Consumes: `timingFields`, `failureFields`, `timingSummary`, `failureSummary` (Tasks 1-2); `InspectorSection` (Task 3).
- Produces: nothing consumed by later tasks.

This is the increment's headline change: `Label` moves from the tail to the first row, and the mislabelled `Timing & label` header is replaced by two honestly-named collapsible sections.

- [ ] **Step 1: Update the imports**

In `webapp/frontend/src/builder/Inspector.tsx`, replace the line-10 import:

```ts
import { gapAfterEligible } from './inspectorRules'
```

with:

```ts
import { failureFields, failureSummary, timingFields, timingSummary } from './inspectorRules'
import { InspectorSection } from './InspectorSection'
```

`gapAfterEligible` is no longer called from this file — `timingFields` wraps it. Leave it exported from `inspectorRules.ts`; its own tests still cover it.

- [ ] **Step 2: Replace `BlockForm` entirely**

Replace lines 149-214 (the whole `BlockForm` function, from `function BlockForm(` through its closing `}`) with:

```tsx
function BlockForm({ node }: { node: BlockNode }) {
  const activeTree = useActiveTree()
  const patchBlock = useDocStore((s) => s.patchBlock)
  const loc = findLocation(activeTree, node.uid)
  const parentKind = loc?.parent?.kind ?? null
  // An empty list means the section does not render at all (design §3.3): `for_each` gets
  // no tail whatsoever (expand.py:26 forbids all four keys on a splice) and `abort` gets no
  // "On failure" (tolerating a safety stop is a contradiction, engine design 2026-07-16
  // §5.1). Both absences state the engine's rule better than a disabled control would.
  const timing = timingFields(node.kind, parentKind)
  const failure = failureFields(node.kind)
  return (
    <div>
      <h2 className="mb-2 text-sm font-semibold text-slate-700">{KIND_TITLES[node.kind]}</h2>
      {/* Label is the one field that means the same thing for all fourteen kinds, so it
          leads every form. The h2 keeps naming the kind, so nothing about kind legibility
          regresses (design §3.1). */}
      <FieldRow label="Label">
        <TextField
          value={node.label ?? ''}
          onCommit={(v) => patchBlock(node.uid, { label: v || null })}
          placeholder="optional display name"
        />
      </FieldRow>
      <KindBody node={node} />
      {timing.length > 0 && (
        <InspectorSection title="Timing" summary={timingSummary(node, parentKind)}>
          {timing.includes('gapAfter') && (
            <FieldRow label="Gap after">
              <DurationField
                value={node.gapAfter}
                allowEmpty
                onCommit={(v) => patchBlock(node.uid, { gapAfter: v })}
              />
            </FieldRow>
          )}
          {timing.includes('startOffset') && (
            <FieldRow label="Start offset">
              <DurationField
                value={node.startOffset}
                allowEmpty
                onCommit={(v) => patchBlock(node.uid, { startOffset: v })}
              />
            </FieldRow>
          )}
        </InspectorSection>
      )}
      {failure.length > 0 && (
        <InspectorSection title="On failure" summary={failureSummary(node)}>
          {failure.includes('onError') && (
            <FieldRow label="On error">
              <select
                value={node.onError ?? 'fail'}
                onChange={(e) =>
                  patchBlock(node.uid, { onError: e.target.value as 'fail' | 'continue' })
                }
                className={controlClass()}
              >
                <option value="fail">fail (stop the run)</option>
                <option value="continue">continue (tolerate the failure)</option>
              </select>
            </FieldRow>
          )}
          {/* Narrowed by kind rather than by `failure.includes('retry')` so TypeScript can
              prove the node is a Command/Measure. FAILURE_POLICY still decides whether the
              SECTION renders; this decides whether the sub-form does. */}
          {(node.kind === 'command' || node.kind === 'measure') && <RetrySection node={node} />}
        </InspectorSection>
      )}
    </div>
  )
}
```

`RetrySection` itself is unchanged — this task moves it under a correct header, it does not reopen its `pending` hazard logic.

- [ ] **Step 3: Verify the gate**

```bash
cd webapp/frontend && npm run typecheck && npm run lint && npm test -- --run
```

Expected: typecheck exits 0 (an unused-import error here means Step 1 was applied incompletely); lint exits 0 with at most the two known warnings; all existing tests pass — no vitest test renders this component, so the suite should be unchanged in count.

- [ ] **Step 4: Verify in a real browser**

Start the devserver and frontend per the W5 recipe, then open the Builder with `webapp/fixtures/ui-audit-torture.json` loaded and check:

1. Selecting a **Wait** block shows `Label` first, `Duration` next, and two collapsed section headers.
2. Selecting a **for_each** block shows `Label` and the body only — **no** section headers at all.
3. Selecting an **abort** block shows a `Timing` header but **no** `On failure` header.
4. A block with `gap_after` set opens `Timing` automatically; collapsing it shows `TIMING · gap after 30s` in the header.
5. Clicking a collapsed header expands it; clicking again collapses it.
6. Selecting a different block and coming back resets the disclosure to its auto-open state.

- [ ] **Step 5: Commit**

```bash
git add webapp/frontend/src/builder/Inspector.tsx
git commit -m "feat(studio): label-first block form with Timing and On failure sections"
```

---

### Task 5: Body field reordering

**Files:**
- Modify: `webapp/frontend/src/builder/Inspector.tsx` — `ActionForm` and `OperatorInputForm`

**Interfaces:**
- Consumes: nothing new.
- Produces: nothing consumed by later tasks.

Two orderings inside the body are development-order artifacts (design §5). Both are pure JSX reorderings: no handler, no state and no document shape changes.

- [ ] **Step 1: Reorder `ActionForm` so a measure's result destination comes last**

In `ActionForm`, the `Into stream` picker currently renders between the `Verb` row and `ParamFields`, wedging the result destination between a verb and the verb's own params. Move it after the params block. Replace the tail of `ActionForm`'s returned JSX — the lines from `{node.kind === 'measure' && <IntoPicker node={node} />}` through the closing `)}` of the spec conditional — with:

```tsx
      {spec ? (
        <ParamFields node={node} specs={spec.params} />
      ) : (
        <p className="text-xs text-amber-600">verb not in catalog — params not editable</p>
      )}
      {/* Result destination last: configure the action, then say where its value goes.
          It used to sit above the params, splitting a verb from its own arguments. */}
      {node.kind === 'measure' && <IntoPicker node={node} />}
```

`IntoPicker` itself is unchanged. Command is unaffected — it has no `into`.

- [ ] **Step 2: Reorder `OperatorInputForm` so the type's constraints follow the type**

`Prompt` currently sits between `Type` and the `Min`/`Max`/`Choices` constraints that the type governs. Move the `Prompt` row below both conditional constraint blocks, so the order becomes `Binding name → Type → Min/Max → Choices → Prompt`. In `OperatorInputForm`, delete this row from its current position directly after the `Type` row:

```tsx
      <FieldRow label="Prompt">
        <AutoGrowTextArea
          value={node.prompt ?? ''}
          onCommit={(v) => patchBlock(node.uid, { prompt: v || null })}
          placeholder="shown to the operator"
        />
      </FieldRow>
```

and re-insert it verbatim as the **last** child of the enclosing `<div>`, after the `{node.inputType === 'enum' && (...)}` block. Add this comment above the re-inserted row:

```tsx
      {/* Last: the type and its constraints define what the operator may enter, so they
          belong together; the prompt is the operator-facing prose describing the result. */}
```

`setType`'s clearing behaviour (`choices` cleared when leaving enum; `min`/`max` cleared for enum and bool) is untouched.

- [ ] **Step 3: Verify the gate**

```bash
cd webapp/frontend && npm run typecheck && npm run lint && npm test -- --run
```

Expected: all three exit 0 (lint with at most the two known warnings).

- [ ] **Step 4: Verify in a real browser**

With the devserver running, select a `measure` block and confirm the order reads Role, Verb, PARAMS, Into stream. Select an `operator_input` block, set its Type to `enum`, and confirm the order reads Binding name, Type, Choices, Prompt; switch Type to `int` and confirm it reads Binding name, Type, Min, Max, Prompt.

- [ ] **Step 5: Commit**

```bash
git add webapp/frontend/src/builder/Inspector.tsx
git commit -m "feat(studio): reorder measure and operator-input body fields"
```

---

### Task 6: Probe states and the UI-consistency sweep

**Files:**
- Modify: `webapp/frontend/tools/capture.mjs`
- Create: `docs/ui-improvements-3/` (probe output for the record)

**Interfaces:**
- Consumes: the finished UI from Tasks 3-5.
- Produces: probe evidence that rule R4 (`sibling-height-mismatch`) is at zero with the tail sections **open**.

**This task is why the increment is not done at Task 5.** A probe rule reports clean on rows that never mounted. W12 shipped a plan that read as verified because `capture.mjs` never opened the Groups panel, so R4 measured nothing. Collapsed-by-default sections are the identical trap: with both closed, every new row is invisible to the probe and it passes vacuously.

- [ ] **Step 1: Add capture states that open the tail**

In `webapp/frontend/tools/capture.mjs`, add a helper above the `states` array. The section header's accessible name changes once it carries a summary (`Timing` → `Timing · gap after 30s`), so match it by prefix:

```js
/** Expand a collapsed Inspector tail section by title. The accessible name gains the
 * collapsed-state summary once a value is set (`Timing · gap after 30s`), so anchor the
 * match at the start rather than using an exact name. */
async function expandSection(page, title) {
  const header = page.getByRole('button', { name: new RegExp(`^${title}`) })
  if ((await header.getAttribute('aria-expanded')) === 'false') await header.click()
  await page.waitForTimeout(150)
}
```

Then append these four states to the `states` array. Values are set through the UI rather than by editing a fixture — `ui-audit-torture.json` and `ui-audit-run.json` have other consumers (`torture.test.ts`, the run harness):

```js
  {
    name: 'inspector-tail-autoopen',
    description:
      'both tail sections auto-opened by non-default values. Sets the values, then selects ' +
      'AWAY and back so BlockForm remounts and the auto-open path (summary !== null) is what ' +
      'opens them — not the clicks that set them.',
    setup: async (page) => {
      await gotoBuilder(page)
      await importDoc(page, FIXTURES.torture)
      await selectBlock(page, /^\s*wait /)
      await expandSection(page, 'Timing')
      await page.getByLabel('Gap after').fill('30s')
      await page.getByLabel('Gap after').press('Enter')
      await expandSection(page, 'On failure')
      await page.getByLabel('On error').selectOption('continue')
      await page.waitForTimeout(200)
      await selectBlock(page, /^\s*Abort if /) // away…
      await selectBlock(page, /^\s*wait /) // …and back: remount, auto-open
    },
  },
  {
    name: 'inspector-tail-expanded',
    description:
      'a block at all defaults with both tail sections manually expanded — the collapsed ' +
      'default would leave R4 (sibling-height-mismatch) nothing to measure on these rows, ' +
      'which is exactly how W12 shipped a vacuously clean probe run.',
    setup: async (page) => {
      await gotoBuilder(page)
      await importDoc(page, FIXTURES.torture)
      await selectBlock(page, /^\s*Alarm if /)
      await expandSection(page, 'Timing')
      await expandSection(page, 'On failure')
    },
  },
  {
    name: 'inspector-retry-hazard',
    description:
      'the densest mixed-control rows in the panel: the amber allow_repeat hazard box open ' +
      'under On failure, for a verb the catalog does not report as retry_safe.',
    setup: async (page) => {
      await gotoBuilder(page)
      await importDoc(page, FIXTURES.morbidostat)
      // pump.dispense takes a RELATIVE volume_ml, so the engine registry leaves it
      // retry_safe = False — retrying after a partial dispense double-doses the culture.
      // It lives in groups.service, which the main tree cannot reach.
      await selectScope(page, 'service')
      await selectBlock(page, / · dispense/)
      await expandSection(page, 'On failure')
      await page.getByLabel('retry on failure').check()
      await page.waitForTimeout(200)
    },
  },
  {
    name: 'inspector-tail-start-offset',
    description:
      'a block sitting in a parallel lane, whose Timing section offers Start offset INSTEAD of ' +
      'Gap after (a lane has no next-in-list). The only state that renders that control, and ' +
      'the one field the Task 4 browser check never exercised.',
    setup: async (page) => {
      await gotoBuilder(page)
      await importDoc(page, FIXTURES.torture)
      await selectBlock(page, PARALLEL_CHILD) // see note below
      await expandSection(page, 'Timing')
    },
  },
  {
    name: 'inspector-tail-absent',
    description:
      'a for_each block, which renders NO tail at all (expand.py:26 forbids all four ' +
      'block-level keys on a splice). Guards the empty-section path against a regression ' +
      'that renders an empty bordered box.',
    setup: async (page) => {
      await gotoBuilder(page)
      await importDoc(page, FIXTURES.torture)
      await selectBlock(page, /^\s*For each /)
    },
  },
```

The existing `inspector-operator-input` state needs no edit — it re-runs automatically and now captures the Task 5 field order.

**`PARALLEL_CHILD` is the one selector you must determine against the running app**, because it depends on the torture fixture's lane contents rather than on a block kind. The requirement is exact: select a block whose **direct parent is a `parallel`**, since that is the only position where `timingFields` offers `Start offset` instead of `Gap after`. Confirm you picked the right block by asserting the Timing section contains a `Start offset` field and **no** `Gap after` field — if you see `Gap after`, the block you selected is not a lane child. Note that W13 made a `serial` under a `parallel` render *as* the lane, so the direct child of a `parallel` is typically that `serial`; its lane header is a valid selection target. Define `PARALLEL_CHILD` as a module-level `const` beside the other selectors, with a comment naming the block you settled on.

If a `selectBlock` regex finds no match, check it against `blockSummary` in `src/builder/summary.ts`, which is the exact text those card headers render.

- [ ] **Step 2: Run the probe self-test**

```bash
cd webapp/frontend && npm run probe:selftest
```

Expected: PASS. This confirms the rules still detect their planted defects before you trust a clean run.

- [ ] **Step 3: Run the capture**

```bash
cd webapp/frontend && npm run capture
```

Expected: R4 `sibling-height-mismatch` at **0 violations** across all states and viewports, R2 `truncate-without-title` at 0, R3 `tiny-target` at 0. R1 residuals matching the documented by-design set are acceptable.

Confirm in the output that the new states actually mounted the rows — a state reporting zero *measured elements* for the Inspector is the vacuous-pass failure this task exists to prevent, not a success.

- [ ] **Step 4: Fix any violation at its source**

A height mismatch means a control in the new markup is not on the `CONTROL_H` token. Fix it in `src/ui/controls.ts` or by having the component ask for the right helper — **never** by appending a class at the call site, which the Global Constraints forbid and which loses the cascade silently. Re-run Step 3 until clean.

- [ ] **Step 5: Commit the evidence**

```bash
git add webapp/frontend/tools/capture.mjs docs/ui-improvements-3/
git commit -m "test(studio): probe states covering the expanded Inspector tail"
```

---

## Final Verification

- [ ] Full frontend gate from `webapp/frontend`:

```bash
npm run lint && npm run typecheck && npm test -- --run && npm run build
```

- [ ] Backend gate from `webapp/backend` (should be untouched, run it to prove it):

```bash
.venv/bin/python -m pytest -q && .venv/bin/python -m mypy && .venv/bin/python -m ruff check .
```

- [ ] Confirm the byte no-op contract still holds: open `examples/morbidostat.json` in the Builder, save it, and confirm the stored document is unchanged. This increment touches no document shape, so any diff here is a real regression.

- [ ] Open the PR against `main`.
