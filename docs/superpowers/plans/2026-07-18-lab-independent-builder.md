# Lab-independent Builder Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Builder the first and default tab, and stop the shell from implying that
authoring an experiment requires a selected lab.

**Architecture:** Tab identity, order and lab-scoping move out of the `TabShell` component into a
new pure module `src/shell/tabs.ts`, because vitest here runs in the node environment and cannot
render components — logic left in the component is untestable. `TabShell` then renders the header's
lab pill only for tabs the module marks lab-scoped, which is Run alone. The Builder's Roles section
gains one sentence saying roles are symbolic. No backend, API, schema, or document-format change.

**Tech Stack:** React 19.2, Vite 8, Tailwind 4, Zustand 5, vitest 4 (node environment), oxlint,
Playwright (capture harness only, not wired into vitest).

**Spec:** `docs/superpowers/specs/2026-07-18-lab-independent-builder-design.md`

## Global Constraints

- All work happens in `webapp/frontend/`. Do not modify `webapp/backend/` or `src/` (the engine).
- vitest runs in the **node environment**, `include: ['src/**/*.test.{ts,tsx}']`, `TZ=UTC`. Tests
  cover **pure functions and stores only** — no component rendering, no jsdom, no
  `@testing-library`. Never add one. (`webapp/frontend/CLAUDE.md`, "Testing")
- Secondary text that carries meaning uses `text-caption`; incidental placeholder/empty-state text
  uses `text-hint`. Never `text-slate-400` or lighter on meaningful text.
  (`webapp/frontend/CLAUDE.md`, "Text colors")
- Interactive icons come from **lucide-react** only, rendered through `IconButton`. This plan adds
  no icons.
- Never append a Tailwind utility onto a class string a helper already baked in — `w-full`,
  `text-slate-500` and friends win by declaration order in the compiled stylesheet regardless of
  class-string order. Helpers take options that *select* a class instead.
  (`webapp/frontend/CLAUDE.md`, "Control height")
- TypeScript is strict everywhere, with `erasableSyntaxOnly` and `verbatimModuleSyntax`: type-only
  imports must be written `import type { X } from '...'` or `import { type X } from '...'`.
- The full gate is `cd webapp/frontend && npm run lint && npm run typecheck && npm test &&
  npm run build`. Two oxlint fast-refresh warnings are known and expected; oxlint still exits 0.
- Commit messages follow Conventional Commits with a `studio` scope, e.g. `feat(studio): …`.

---

### Task 1: Pure tab module, new tab order, Builder as landing tab

Extracts tab identity into a testable module, flips the order to Builder-first, makes Builder the
landing tab, and fixes the capture harness selector in the same commit so the tree is never left
with a broken harness.

**Files:**
- Create: `webapp/frontend/src/shell/tabs.ts`
- Create: `webapp/frontend/src/shell/tabs.test.ts`
- Create: `webapp/frontend/src/stores/navStore.test.ts`
- Modify: `webapp/frontend/src/shell/TabShell.tsx:1-4` (drop the local `TABS`/`Tab`, import them)
- Modify: `webapp/frontend/src/stores/navStore.ts:3,11` (import path, initial tab)
- Modify: `webapp/frontend/tools/capture.mjs:41` (tab-number regex)

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `TABS: readonly ['Builder','Devices','Run','Records']`, `type Tab = (typeof TABS)[number]`,
  and `labScopedTab(tab: Tab): boolean` — all exported from `src/shell/tabs.ts`. Task 2 imports
  `labScopedTab` and `Tab` from this module. `TabShell.tsx` no longer exports `TABS` or `Tab`;
  every importer must use `src/shell/tabs.ts`.

- [ ] **Step 1: Write the failing tests**

Create `webapp/frontend/src/shell/tabs.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import { labScopedTab, TABS } from './tabs'

describe('TABS', () => {
  // Builder first is the whole point: a workflow is authored and validated with no lab in
  // mind, so authoring — not lab selection — is the first thing a user sees.
  it('orders the tabs Builder, Devices, Run, Records', () => {
    expect([...TABS]).toEqual(['Builder', 'Devices', 'Run', 'Records'])
  })
})

describe('labScopedTab', () => {
  it('marks Run, and only Run, as lab-scoped', () => {
    expect(TABS.filter((t) => labScopedTab(t))).toEqual(['Run'])
  })

  it('does not mark Builder — the builder never reads lab state', () => {
    expect(labScopedTab('Builder')).toBe(false)
  })

  // Records lists every record regardless of lab and already shows a per-row lab column
  // (RecordsTable.tsx), so a global lab pill there would assert a filter that does not exist.
  it('does not mark Records — the records table is not filtered by lab', () => {
    expect(labScopedTab('Records')).toBe(false)
  })
})
```

Create `webapp/frontend/src/stores/navStore.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import { TABS } from '../shell/tabs'
import { useNavStore } from './navStore'

describe('navStore', () => {
  it('lands on Builder, which needs no lab', () => {
    expect(useNavStore.getState().tab).toBe('Builder')
  })

  it('lands on whichever tab is first in the bar', () => {
    expect(useNavStore.getState().tab).toBe(TABS[0])
  })
})
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd webapp/frontend && npm test -- src/shell/tabs.test.ts src/stores/navStore.test.ts`

Expected: FAIL. `tabs.test.ts` fails to resolve the import `./tabs` (the module does not exist
yet). `navStore.test.ts` fails to resolve `../shell/tabs`, and its first assertion would fail
anyway because the store still starts on `'Devices'`.

- [ ] **Step 3: Create the tab module**

Create `webapp/frontend/src/shell/tabs.ts`:

```ts
/** Tab identity, order, and lab-scoping.
 *
 * This is a pure module rather than part of TabShell.tsx because vitest runs in the node
 * environment here (webapp/frontend/CLAUDE.md) — no component rendering — so anything left
 * inside the component cannot be asserted by any test in this repo. Same reason
 * builder/paletteSections.ts exists. */

export const TABS = ['Builder', 'Devices', 'Run', 'Records'] as const
export type Tab = (typeof TABS)[number]

/** Which tabs the selected lab actually governs.
 *
 * Typed as an exhaustive Record<Tab, boolean> rather than a set of lab-scoped names: a fifth
 * tab added later is then a compile error until it states whether it depends on a lab, which a
 * membership check would silently default to "no". Only Run binds roles to physical devices
 * (run/PreflightPanel.tsx); the Builder authors symbolic roles against the static engine
 * catalog, and Records lists every record with its own per-row lab column. */
const LAB_SCOPED: Record<Tab, boolean> = {
  Builder: false,
  Devices: false,
  Run: true,
  Records: false,
}

export const labScopedTab = (tab: Tab): boolean => LAB_SCOPED[tab]
```

- [ ] **Step 4: Point `TabShell` at the module**

In `webapp/frontend/src/shell/TabShell.tsx`, replace lines 1-4:

```tsx
import type { ReactNode } from 'react'

export const TABS = ['Devices', 'Builder', 'Run', 'Records'] as const
export type Tab = (typeof TABS)[number]
```

with:

```tsx
import type { ReactNode } from 'react'
import { TABS, type Tab } from './tabs'
```

Leave the rest of the file alone in this task; the pill is Task 2.

- [ ] **Step 5: Point `navStore` at the module and land on Builder**

In `webapp/frontend/src/stores/navStore.ts`, change line 3 from:

```ts
import type { Tab } from '../shell/TabShell'
```

to:

```ts
import type { Tab } from '../shell/tabs'
```

and change line 11 from `tab: 'Devices',` to:

```ts
  tab: 'Builder',
```

- [ ] **Step 6: Fix the capture harness's tab selector**

The harness clicks the Builder tab by its accessible name, which embeds the tab's index digit.
Builder is now tab 1, so in `webapp/frontend/tools/capture.mjs` change line 41 from:

```js
  await page.getByRole('button', { name: /^2\s*Builder$/ }).click()
```

to:

```js
  await page.getByRole('button', { name: /^1\s*Builder$/ }).click()
```

Every capture state routes through `gotoBuilder`, so leaving this stale breaks all of them.

- [ ] **Step 7: Run the tests to verify they pass**

Run: `cd webapp/frontend && npm test -- src/shell/tabs.test.ts src/stores/navStore.test.ts`

Expected: PASS, 5 tests across 2 files.

- [ ] **Step 8: Verify nothing else imported the old exports**

Run: `cd webapp/frontend && grep -rn "from '.*shell/TabShell'" src/`

Expected: exactly one line — `src/App.tsx:4:import { TabShell } from './shell/TabShell'` — which
imports the component, not the moved types. If anything else appears, repoint it at
`src/shell/tabs`.

- [ ] **Step 9: Run the full gate**

Run: `cd webapp/frontend && npm run lint && npm run typecheck && npm test && npm run build`

Expected: oxlint exits 0 with the two known fast-refresh warnings; `tsc -b` prints nothing;
vitest reports all tests passing (267 before this task, 272 after); `vite build` succeeds.

- [ ] **Step 10: Commit**

```bash
git add webapp/frontend/src/shell/tabs.ts webapp/frontend/src/shell/tabs.test.ts \
  webapp/frontend/src/shell/TabShell.tsx webapp/frontend/src/stores/navStore.ts \
  webapp/frontend/src/stores/navStore.test.ts webapp/frontend/tools/capture.mjs
git commit -m "feat(studio): put Builder first and make it the landing tab"
```

---

### Task 2: Scope the header lab pill to the Run tab

**Files:**
- Modify: `webapp/frontend/src/shell/TabShell.tsx:40-54` (wrap the pill in a condition)

**Interfaces:**
- Consumes: `labScopedTab(tab: Tab): boolean` and `TABS`/`Tab` from `src/shell/tabs.ts` (Task 1).
- Produces: nothing new. `TabShell`'s props are unchanged — it still takes `lab: string | null`,
  and callers (`App.tsx:26`) need no edit.

There is no unit test for this step: the change is JSX, and vitest cannot render components in
this repo (see Global Constraints). The rule it enforces is already pinned by
`labScopedTab`'s tests in Task 1; the rendering is verified by the capture harness in Task 4.

- [ ] **Step 1: Import the predicate**

In `webapp/frontend/src/shell/TabShell.tsx`, change the import added in Task 1 from:

```tsx
import { TABS, type Tab } from './tabs'
```

to:

```tsx
import { labScopedTab, TABS, type Tab } from './tabs'
```

- [ ] **Step 2: Render the pill only on lab-scoped tabs**

Replace the header's trailing span (currently lines 40-54, the `ml-auto` span containing the pill
and the status line) with:

```tsx
        <span className="ml-auto flex min-w-0 items-center gap-3 self-center py-3">
          {/* The pill claims the current view is bound to a lab, so it may only appear where
              that is true. On the Builder it read as an unmet precondition for work that has
              no lab dependency at all; on Records it read as a filter over a table that is
              never filtered by lab (RecordsTable renders its own per-row lab column). */}
          {labScopedTab(props.active) && (
            <span
              className={
                'shrink-0 rounded-full px-2 py-0.5 text-xs ' +
                (props.lab ? 'bg-blue-100 text-blue-700' : 'bg-slate-100 text-caption')
              }
            >
              {props.lab ? `lab: ${props.lab}` : 'no lab selected'}
            </span>
          )}
          {/* truncate + title: a long health string must shorten, not wrap the single row
              at 1024px (spec §3.2). min-w-0 on the parent is what lets it shrink. This is the
              server's health, not the lab's, so it stays on every tab. */}
          <span title={props.statusLine} className="truncate text-xs text-hint">
            {props.statusLine}
          </span>
        </span>
```

- [ ] **Step 3: Run the full gate**

Run: `cd webapp/frontend && npm run lint && npm run typecheck && npm test && npm run build`

Expected: all green, same counts as Task 1 Step 9 (this task adds no tests).

- [ ] **Step 4: Commit**

```bash
git add webapp/frontend/src/shell/TabShell.tsx
git commit -m "feat(studio): show the lab pill only on the Run tab"
```

---

### Task 3: Say in the Builder that roles are symbolic

**Files:**
- Modify: `webapp/frontend/src/builder/RolesSection.tsx:18-32` (`RolesSection` body)
- Modify: `webapp/frontend/src/builder/roleGroups.ts:1-6` (stale doc comment)

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: nothing. `RolesSection` keeps its zero-argument signature and `roleGroups`/
  `effectiveSelection` keep their existing signatures — the comment change is prose only, so
  `roleGroups.test.ts` needs no edit and must keep passing untouched.

- [ ] **Step 1: Add the hint above the type blocks**

In `webapp/frontend/src/builder/RolesSection.tsx`, replace the whole `RolesSection` function
(lines 18-32) with:

```tsx
export function RolesSection() {
  const catalog = useCatalogStore((s) => s.catalog)
  const roles = useDocStore((s) => s.roles)
  const groups = roleGroups(roles, catalog)
  return (
    <div className="space-y-2">
      {/* The Roles section is the only place in the Builder where hardware is conceptually
          adjacent — device types name real equipment and verb chips name real operations — so
          it is the only place a reader can reasonably wonder which lab they are looking at.
          The answer is none: these come from the engine's static catalog (GET /api/catalog),
          and the binding to physical devices happens in the Run tab's preflight. */}
      <p className="px-1 text-xs text-hint">
        Roles are symbolic — you bind them to real devices when you start a run.
      </p>
      {groups.length === 0 ? (
        <p className="px-1 text-xs text-hint">no device types in the catalog yet</p>
      ) : (
        groups.map((g) => <RoleTypeBlock key={g.type} group={g} catalog={catalog} />)
      )}
    </div>
  )
}
```

Note the structural change: the empty-state paragraph used to be an early `return` before the
wrapper `div`, so the hint would not have shown when the catalog was empty or still loading —
which is exactly when a confused reader most needs it. It is now a branch inside the wrapper.

- [ ] **Step 2: Correct the stale comment that claims a lab dependency**

In `webapp/frontend/src/builder/roleGroups.ts`, replace lines 1-6:

```ts
/** Pure grouping for the palette's Roles section (spec §3.3): one entry per catalog
 * device type in catalog order — a type with no roles still gets a block, so the user
 * sees what the lab offers and can create the first role in place — then one entry per
 * unknown type cited by the doc's roles (first-appearance order, rendered amber by the
 * consumer). A null catalog (still loading, or errored) yields only the cited types, all
 * flagged unknown, rather than pretending to know their verbs. */
```

with:

```ts
/** Pure grouping for the palette's Roles section (spec §3.3): one entry per catalog
 * device type in catalog order — a type with no roles still gets a block, so the user sees
 * every device type the engine supports and can create the first role in place — then one
 * entry per unknown type cited by the doc's roles (first-appearance order, rendered amber by
 * the consumer). A null catalog (still loading, or errored) yields only the cited types, all
 * flagged unknown, rather than pretending to know their verbs.
 *
 * The catalog is the engine's static verb registry (GET /api/catalog -> verb_catalog()), NOT
 * the selected lab's roster. Nothing under builder/ reads lab state; roles are symbolic and
 * are bound to devices at run time. This comment used to say "what the lab offers", which is
 * how a reader concludes a lab dependency exists here. */
```

- [ ] **Step 3: Run the full gate**

Run: `cd webapp/frontend && npm run lint && npm run typecheck && npm test && npm run build`

Expected: all green. `src/builder/roleGroups.test.ts` must still pass unmodified — if it fails,
the comment edit accidentally changed code.

- [ ] **Step 4: Commit**

```bash
git add webapp/frontend/src/builder/RolesSection.tsx webapp/frontend/src/builder/roleGroups.ts
git commit -m "feat(studio): state that builder roles are symbolic, not lab devices"
```

---

### Task 4: Verify in a real browser and record the landing-tab change

**Files:**
- Modify: none of the application source. This task only runs the app and the harness.
- Capture output is written by `tools/capture.mjs` itself (W11 wrote its evidence under
  `docs/ui-improvements/after/`); do not hand-edit whatever it produces.

**Interfaces:**
- Consumes: the running app from Tasks 1-3.
- Produces: nothing consumed by later tasks. This is the final gate.

- [ ] **Step 1: Confirm the probe's self-test still passes**

Run: `cd webapp/frontend && npm run probe:selftest`

Expected: PASS. This checks the probe's own rules against planted defects and reverts, so a
failure here means the harness is broken, not the app.

- [ ] **Step 2: Start the dev backend and frontend**

In two shells:

```bash
cd webapp/backend && .venv/bin/python tests/devserver.py
```

```bash
cd webapp/frontend && npm run dev
```

Expected: the backend serves `http://localhost:8000`, and Vite serves the app with `/api`
proxied to it (`vite.config.ts`).

- [ ] **Step 3: Run the capture harness**

Run: `cd webapp/frontend && npm run capture`

Expected: it completes without a Playwright timeout — a timeout on the tab click means Task 1
Step 6's regex is wrong. Expected result: **0 probe violations** across all state/viewport
combinations, matching the baseline W11 established. In particular the
`sibling-height-mismatch` rule (R4) must stay clean on the header row, whose composition
changed when the pill became conditional.

- [ ] **Step 4: Confirm the three user-visible outcomes by hand**

With the dev app open in a browser:

1. On first load with a cleared `studio.selectedLab` (run `localStorage.clear()` in the console,
   then reload), the app lands on the Builder tab and the tab bar reads
   "1 Builder, 2 Devices, 3 Run, 4 Records".
2. No lab pill appears in the header on Builder, Devices, or Records. It appears on Run, reading
   `no lab selected`.
3. The Run tab shows "Select a lab first" with a "Go to Devices" button, and that button lands on
   Devices. Select a lab there, return to Run, and the pill reads `lab: <name>`.

Expected: all three hold. If any does not, fix it before Step 5 rather than recording an
exception.

- [ ] **Step 5: Commit any capture evidence**

```bash
git add -A docs/ui-improvements webapp/frontend/tools
git commit -m "test(studio): capture evidence for the lab-independent builder"
```

If `git status` shows nothing to add here, skip the commit — the harness writes evidence only
when configured to, and an empty commit is not wanted.

- [ ] **Step 6: Record the landing-tab change for future sessions**

The W5 UI-testing recipe in project memory states that "after `page.reload()` the app lands on
the Devices tab". That is now false. Update
`~/.claude/projects/-Users-khamit-lab-devices/memory/experiment-studio-increments.md` to say the
app lands on **Builder**, and note that `capture.mjs` matches the Builder tab as `/^1\s*Builder$/`.

---

## Self-review notes

**Spec coverage.** §1 problem statement → Tasks 1-3 collectively. §2 settled decisions → honoured
throughout; no Run gating and no `device`→`role` rename appear anywhere in this plan. §3 tab order,
landing tab, pure module → Task 1. §4 tab-scoped pill, Run only → Task 2 (and pinned by Task 1's
`labScopedTab` tests). §5 legibility: hint line and stale comment → Task 3. §6 Run stays the only
gate → no code change, verified in Task 4 Step 4.3. §7 capture harness → Task 1 Step 6 (the edit,
committed with the change that breaks it) and Task 4 Steps 1-3 (the re-run). §8 compatibility → the
memory correction is Task 4 Step 6. §9 testing → Task 1 Steps 1-2-7 and the full gate in every task.
§10 out of scope → nothing in this plan touches those areas.

**Type consistency.** `labScopedTab` and `TABS` are named identically in `tabs.ts` (Task 1 Step 3),
`tabs.test.ts` (Task 1 Step 1), `navStore.test.ts` (Task 1 Step 1), `TabShell.tsx` (Task 1 Step 4,
Task 2 Steps 1-2). `Tab` is imported type-only everywhere, as `verbatimModuleSyntax` requires.
`RolesSection` keeps its zero-argument signature and `RoleTypeBlock`'s existing
`{ group, catalog }` props are unchanged by Task 3.

**Known risk.** The test count quoted in Task 1 Step 9 (267 → 272) is the figure from the W12
increment plus the five tests this plan adds. If the baseline has moved, the delta of +5 is what
matters, not the absolute number.
