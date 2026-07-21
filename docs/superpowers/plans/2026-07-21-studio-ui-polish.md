# Studio UI Polish (PR 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Nine pure-frontend visual fixes in the Studio Builder: honest palette defaults, consistent drop zones, a help-message empty state, separator-based inner sections, a quieter streams panel, and a roles panel that shows colors, adds roles in place, and never clips its color picker.

**Architecture:** All changes live in `webapp/frontend/src` — no API, schema, or backend change. Class-string changes follow the repo's select-don't-append rule (constructTint.ts's doc comment). Component behavior that vitest (node-env, pure functions only) can't reach is verified by the committed probe/capture harness plus targeted Playwright screenshots.

**Tech Stack:** React 19.2, Tailwind 4, vitest 4 (node env, pure fns), dnd-kit, lucide-react, the committed `tools/probe.mjs`/`tools/capture.mjs` harness.

**Spec:** `docs/superpowers/specs/2026-07-21-studio-ui-polish-design.md`

## Global Constraints

- Worktree: `/Users/khamit/lab-devices-wt/studio-ui-polish`, branch `feat/studio-ui-polish`. All paths below are relative to `webapp/frontend/` unless they start with `docs/`.
- Frontend gate: `cd webapp/frontend && npm run lint && npm run typecheck && npm test -- --run && npm run build` (2 known oxlint fast-refresh warnings are OK, exit 0).
- vitest is node-env and imports PURE modules only — never import a `.tsx` component into a test. Class-string logic that needs testing must live in (or move to) a pure `.ts` helper.
- Tailwind: never append a competing utility onto a class a helper already bakes in (same property = cascade lottery). SELECT the final class instead. Applies to every property, not just width.
- Tailwind 4 scans source text: never interpolate class fragments (`border-${x}-200` compiles to nothing).
- Keep the canvas conventions: text never sits directly on the group-scope hatch (goes `bg-white` when `scope !== null`); amber is reserved for warnings; blue is selection/legal-drop.
- Commit after every task with a conventional-commit message; end every commit body with the two Claude trailers used on this branch (see `git log -1`).

---

### Task 1: Honest palette defaults (`newPaletteNode`) + loop count empty-commit

**Files:**
- Modify: `src/builder/tree.ts:381-400`
- Modify: `src/builder/Inspector.tsx:1066`
- Test: `src/builder/tree.test.ts`

**Interfaces:**
- Produces: `newPaletteNode('loop')` → `count: ''`; `('wait')` → `duration: ''`; `('operator_input')` → `name: ''`; `('for_each')` → `vars: [], rows: []`. Types already allow all of these (`count: number | string`, `vars: ParamDeclJson[]`).

- [ ] **Step 1: Write the failing tests** — in `src/builder/tree.test.ts`, add (adjust `describe` nesting to match the file's existing style; if existing assertions pin the OLD defaults, update them to these):

```ts
describe('newPaletteNode seeds', () => {
  it('seeds for_each empty — no fabricated variable or rows', () => {
    const n = newPaletteNode('for_each')
    expect(n.kind === 'for_each' && n.vars).toEqual([])
    expect(n.kind === 'for_each' && n.rows).toEqual([])
  })
  it('seeds wait, loop, and operator_input empty', () => {
    const w = newPaletteNode('wait')
    expect(w.kind === 'wait' && w.duration).toBe('')
    const l = newPaletteNode('loop')
    expect(l.kind === 'loop' && l.count).toBe('')
    const o = newPaletteNode('operator_input')
    expect(o.kind === 'operator_input' && o.name).toBe('')
  })
  it('keeps parallel structural seed: two empty serial lanes', () => {
    const p = newPaletteNode('parallel')
    expect(p.kind === 'parallel' && p.children.map((c) => c.kind)).toEqual(['serial', 'serial'])
  })
})
```

- [ ] **Step 2: Run to verify failure** — `npm test -- --run tree` → the new assertions FAIL against `count: 2` / `'1s'` / `'value'` / tube-rows.

- [ ] **Step 3: Implement** in `src/builder/tree.ts`:

```ts
    case 'loop':
      return { ...base, kind, mode: 'count', count: '', until: '', check: 'after', pace: null, body: [] }
    case 'branch':
      return { ...base, kind, condition: '', then: [], else: [] }
    case 'wait':
      return { ...base, kind, duration: '' }
    case 'operator_input':
      return { ...base, kind, name: '', inputType: 'float', prompt: null, min: null, max: null, choices: null }
```

and for `for_each`, replace the seeded case AND its comment (the comment's rationale is superseded — invalid-until-filled is already the norm for branch/compute/record, and Save never gates on validation):

```ts
    case 'for_each':
      // Seeded empty like branch/compute: a fabricated example (tube / 1,2,3) read as real
      // data. An empty `in` is still a load error (expand.py:99), so the block is
      // invalid-until-filled — which Save permits and ProblemsPanel reports, same as an
      // empty branch condition.
      return { ...base, kind, vars: [], rows: [], body: [] }
```

In `src/builder/Inspector.tsx:1066`, stop silently rewriting a cleared count to 1 (matches WaitForm's `v ?? ''` precedent one screen up):

```ts
                count: trimmed === '' ? '' : /^\d+$/.test(trimmed) ? Number(trimmed) : trimmed,
```

- [ ] **Step 4: Run the full suite** — `npm test -- --run`. Other tests may pin the old seeds (`torture.test.ts`, `docStore.test.ts`, `summary.test.ts`, `paletteSections.test.ts` all import `newPaletteNode`). Update any failing expectation to the new seeds — but read each failure first: if a test *constructs* a for_each with vars to exercise something else, give it explicit vars instead of relying on the seed.

- [ ] **Step 5: Typecheck + lint** — `npm run typecheck && npm run lint`.

- [ ] **Step 6: Commit** — `git add -A && git commit -m "feat(studio): seed palette blocks empty — placeholders, not fabricated defaults"`.

---

### Task 2: Drop-zone margin + empty-canvas help message

**Files:**
- Modify: `src/builder/DropSlot.tsx:23`
- Modify: `src/builder/Canvas.tsx:85-97`

**Interfaces:**
- Produces: hint DropSlot class no longer contains `m-1`; empty-canvas `<p>` no longer contains `border-dashed`/`border`/`p-8`.

- [ ] **Step 1: Edit `DropSlot.tsx`** — the hint branch's class loses its outer margin (blocks carry no outer margin; vertical rhythm comes from the interleaved `my-0.5` bars):

```ts
          'flex-1 rounded border border-dashed px-2 py-3 text-center text-xs ' +
```

- [ ] **Step 2: Edit `Canvas.tsx`** — the empty-canvas hint stops dressing as a drop zone. It keeps ScopeSwitcher's exact hatch-backing treatment (`rounded bg-white shadow-sm` only under a group scope — the repo's "text never sits on the hatch" rule) but loses the dashed action-box costume:

```tsx
              <p
                className={
                  // Help text, not a drop target — the actual droppable is the hint DropSlot
                  // below (BlockList's leading slot). Same hatch-backing rule as
                  // ScopeSwitcher's strip: solid white whenever a group scope is active.
                  'mb-2 px-2 py-4 text-center text-sm text-caption ' +
                  (scope === null ? '' : 'rounded bg-white shadow-sm')
                }
              >
                Drag blocks from the palette to start building.
              </p>
```

- [ ] **Step 3: Gate** — `npm run typecheck && npm run lint && npm test -- --run` (no test pins these strings; visual verification is Task 7).

- [ ] **Step 4: Commit** — `git commit -am "fix(studio): drop-zone spacing matches blocks; empty-canvas hint reads as help, not a drop target"`.

---

### Task 3: Lane and branch-arm boxes become labeled separators

**Files:**
- Modify: `src/builder/Canvas.tsx:461-470` (legacy lane), `:480-489` (serial lane), `:562-570` (branch arms)

**Interfaces:**
- Consumes: `constructBorderClass(kind)` from `constructTint.ts` (returns e.g. `border-teal-200`) — construct identity stays encoded in ONE place.
- Produces: lanes/arms have no full border; lane `index > 0` and the ELSE arm carry `border-l` + the construct's border color; serial-lane selection = `ring-2 ring-blue-400` only.

- [ ] **Step 1: Serial lane (`Lane`, the `lane.kind === 'serial'` return)** — replace the wrapper's className:

```tsx
      className={
        // No idle box: lanes separate with a single hairline (index > 0), in parallel's
        // construct tint so retinting the map retints the separator too. Selection is the
        // ring alone — same `ring-2 ring-blue-400` as BlockView, with no border for it to
        // compete with.
        'min-w-48 flex-initial rounded p-1 ' +
        (index > 0 ? 'border-l ' + constructBorderClass('parallel') + ' ' : '') +
        (selected ? 'ring-2 ring-blue-400 ' : '') +
        (isDragging ? 'opacity-40' : '')
      }
```

- [ ] **Step 2: Legacy (non-serial) lane** — same treatment, keeping its label row:

```tsx
      <div
        className={
          'min-w-48 flex-initial rounded p-1' +
          (index > 0 ? ' border-l ' + constructBorderClass('parallel') : '')
        }
      >
```

- [ ] **Step 3: Branch arms (`BranchLanes`)** — THEN arm loses its box; ELSE arm keeps only a left hairline in branch's tint. Replace the two wrapper divs (both `else === null` and else-present branches share the outer div at `:570`):

```tsx
      <div className="min-w-48 flex-initial px-1 pb-1">
        <p className="flex h-6 items-center text-[10px] uppercase text-caption">then</p>
        <BlockList parentUid={node.uid} slot="then" items={node.then} />
      </div>
      <div className={'min-w-48 flex-initial border-l px-1 pb-1 ' + constructBorderClass('branch')}>
```

Update the comment above the arms (`:563-565`): it currently explains why the arm *borders* read the tint; reword to say the arm *separator* reads it — identity still encoded once.

- [ ] **Step 4: Gate** — `npm run typecheck && npm run lint && npm test -- --run && npm run build`.

- [ ] **Step 5: Commit** — `git commit -am "feat(studio): lanes and branch arms use labeled separators instead of nested boxes"`.

---

### Task 4: Streams panel — quiet right-aligned source badge, filter removed

**Files:**
- Modify: `src/builder/StreamsPanel.tsx`
- Delete: `src/builder/streamFilter.ts`, `src/builder/streamFilter.test.ts`

**Interfaces:**
- Produces: row order = name · units · (right-aligned) source badge · delete. Unused = plain `text-hint` text, no amber, no background.

- [ ] **Step 1: Remove the filter** — delete the `filterStreamNames` import, the `query` state, the filter `<input>` (lines 60-65), the "no streams match" `<li>`; `const matches = Object.keys(streams)`. In the group-refs section: `const shownGroupRefs = groupRefs` (drop `visibleGroupRefs`). Then `git rm src/builder/streamFilter.ts src/builder/streamFilter.test.ts` and `grep -rn filterStreamNames src/` to confirm zero remaining references.

- [ ] **Step 2: Reorder + restyle the main-row badge** — move the source `<span>` to AFTER the units input and give it `ml-auto`; the delete IconButton loses its `ml-auto`. New row body (name button/rename input unchanged):

```tsx
            <input
              value={s.units ?? ''}
              placeholder="units"
              onChange={(e) => setStreamUnits(name, e.target.value || null)}
              className={controlClass({ width: 'w-14' })}
            />
            <span
              title={
                sources[name] === undefined
                  ? 'No block writes this stream'
                  : `Written by a ${sources[name]} block`
              }
              className={
                'ml-auto flex h-6 shrink-0 items-center text-xs ' +
                (sources[name] === undefined
                  ? 'text-hint'
                  : 'rounded bg-slate-100 px-1 text-caption')
              }
            >
              {sources[name] ?? 'unused'}
            </span>
            <IconButton
              icon={X}
              label="Delete stream"
              destructive
              onClick={() => setError(removeStream(name))}
            />
```

- [ ] **Step 3: Same treatment in the group-refs list** — move that source `<span>` to the end of its row (it already is last) and apply the identical quiet classes (`ml-auto flex h-6 shrink-0 items-center text-xs` + the same ternary). Keep the origin tag and units spans as they are.

- [ ] **Step 4: Gate** — `npm run typecheck && npm run lint && npm test -- --run` (the deleted test file must not appear in the run).

- [ ] **Step 5: Commit** — `git commit -am "feat(studio): streams panel — quiet right-aligned source tag, filter removed"`.

---

### Task 5: Roles panel — inline add-role chip + color dots on badges

**Files:**
- Modify: `src/builder/RolesSection.tsx`

**Interfaces:**
- Consumes: `assignRoleColors(roles, overrides)` from `./roleColors` (Record<roleName, swatchClass | null>), `useRoleColorStore((s) => s.overrides)`, `useDocStore((s) => s.roles)` — the exact pattern of `useRoleColor` in `Canvas.tsx:220-226`.
- Produces: `AddRoleForm` renders inside the badge row; badges carry an `aria-hidden` color dot.

- [ ] **Step 1: Color dots.** In `RoleTypeBlock`, resolve colors once (group params have no doc-role entry, so they get no dot for free):

```tsx
  const docRoles = useDocStore((s) => s.roles)
  const overrides = useRoleColorStore((s) => s.overrides)
  const assigned = useMemo(() => assignRoleColors(docRoles, overrides), [docRoles, overrides])
```

(add `useMemo` to the react import, `useRoleColorStore` + `assignRoleColors` to the existing imports — `roleColors` is already imported for the picker constants). In `badge(name)`'s button branch, insert the dot before the truncate span — the same swatch square the canvas header uses, so the color a user picks is visible before any block is dropped:

```tsx
        {assigned[name] && (
          <span aria-hidden className={`mr-1 h-2.5 w-2.5 shrink-0 rounded-sm ${assigned[name]}`} />
        )}
```

- [ ] **Step 2: Move AddRoleForm into the badge row.** Restructure `RoleTypeBlock`'s body: the badge-row div always renders (not only when roles exist) with `AddRoleForm` as its last flow chip, before the `ml-auto` action cluster; remove the old `<AddRoleForm …/>` at the bottom (line 224); keep the "no roles yet" hint `<p>` only while `group.roles.length === 0`:

```tsx
      {group.roles.length === 0 && (
        <p className="mb-1 px-1 text-xs text-hint">no roles yet — add one to use this device</p>
      )}
      <div className="mb-1 flex flex-wrap items-center gap-1">
        {topRoles.map((name) => badge(name))}
        <AddRoleForm type={group.type} onAdded={setPicked} />
        {group.roles.length > 0 && !selectedIsParam && (
          <span className="ml-auto flex items-center">
            {/* …existing RoleColorPicker / Pencil / X cluster, unchanged… */}
          </span>
        )}
      </div>
```

- [ ] **Step 3: Make AddRoleForm row-native.** The collapsed button drops its `' mt-1'` suffix (the row's `gap-1` spaces it). The expanded form becomes an inline row whose error wraps to a full-width line inside the flex-wrap parent:

```tsx
  return (
    <div ref={addingRef} className="flex min-w-0 flex-wrap items-center gap-1">
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
      {error && <p className="basis-full text-xs text-red-600">{error}</p>}
    </div>
  )
```

Update `AddRoleForm`'s doc comment: the form now lives inline after the last role badge (the old "below the block" placement was the complaint), dismiss boundary reasoning unchanged.

- [ ] **Step 4: Gate** — `npm run typecheck && npm run lint && npm test -- --run`.

- [ ] **Step 5: Commit** — `git commit -am "feat(studio): role badges show their colour; add-role sits after the last role"`.

---

### Task 6: Color picker escapes the palette clip (portal + flip)

**Files:**
- Modify: `src/ui/useDismissable.ts`
- Modify: `src/builder/RolesSection.tsx` (`RoleColorPicker`)
- Test: `src/ui/useDismissable.test.ts` (create if absent)

**Interfaces:**
- Produces: `useDismissable(open, onClose, extra?: RefObject<HTMLElement | null>)` — a node inside EITHER container counts as inside. `shouldDismiss` signature unchanged (composite built in the hook).

- [ ] **Step 1: Failing test** for the composite-container rule (pure, node-env):

```ts
import { describe, expect, it } from 'vitest'
import { shouldDismiss, type DismissContainer } from './useDismissable'

const containerOf = (members: Set<unknown>): DismissContainer => ({
  contains: (n) => members.has(n),
})

describe('shouldDismiss with a composite container (portal popovers)', () => {
  const inTrigger = {} as Node
  const inPortal = {} as Node
  const outside = {} as Node
  const composite: DismissContainer = {
    contains: (n) =>
      containerOf(new Set([inTrigger])).contains(n) || containerOf(new Set([inPortal])).contains(n),
  }
  it('keeps open for pointerdown inside either part', () => {
    expect(shouldDismiss({ type: 'pointerdown', target: inTrigger }, composite)).toBe(false)
    expect(shouldDismiss({ type: 'pointerdown', target: inPortal }, composite)).toBe(false)
  })
  it('dismisses for pointerdown outside both', () => {
    expect(shouldDismiss({ type: 'pointerdown', target: outside }, composite)).toBe(true)
  })
})
```

Run: `npm test -- --run useDismissable` — passes already if `shouldDismiss` is exported (it is); this pins the composite semantics the hook change relies on. Then extend the hook (this part has no node-env test — it's DOM wiring):

```ts
export function useDismissable(
  open: boolean,
  onClose: () => void,
  extra?: RefObject<HTMLElement | null>,
): RefObject<HTMLDivElement | null> {
```

and inside `handle`, build the composite:

```ts
      const container: DismissContainer | null = ref.current && {
        contains: (n: DismissTarget) =>
          Boolean(ref.current?.contains(n) || extra?.current?.contains(n)),
      }
      if (shouldDismiss({ type: e.type, key, target: e.target as Node | null }, container)) {
```

(`extra` is read inside the listener, so it needs no dependency-array entry — note that in a comment.)

- [ ] **Step 2: Portal the popover.** In `RoleColorPicker`, render the panel through `createPortal` (import from `react-dom`), positioned `fixed` from the trigger rect, right-aligned to the trigger, flipping above when the viewport bottom would clip it. Measure the panel AFTER first paint (`useLayoutEffect`), keeping it invisible until placed:

```tsx
function RoleColorPicker({ name, type }: { name: string; type: string }) {
  const [open, setOpen] = useState(false)
  const panelRef = useRef<HTMLDivElement>(null)
  const ref = useDismissable(open, () => setOpen(false), panelRef)
  const [pos, setPos] = useState<{ top: number; right: number } | null>(null)
  const setColor = useRoleColorStore((s) => s.setColor)
  const clearColor = useRoleColorStore((s) => s.clearColor)
  const resetColor = useRoleColorStore((s) => s.resetColor)
  const key = roleColorKey(name, type)

  // The palette aside is overflow-y-auto, which clips any absolute child on BOTH axes —
  // the popover must escape to document.body. Position: fixed, measured after first
  // paint (visibility:hidden until placed), right-aligned to the trigger, flipped above
  // it when the viewport bottom would crop it.
  useLayoutEffect(() => {
    if (!open) {
      setPos(null)
      return
    }
    const trigger = ref.current?.getBoundingClientRect()
    const panel = panelRef.current?.getBoundingClientRect()
    if (!trigger || !panel) return
    const below = trigger.bottom + 4 + panel.height <= window.innerHeight
    setPos({
      top: below ? trigger.bottom + 4 : Math.max(8, trigger.top - 4 - panel.height),
      right: Math.max(8, window.innerWidth - trigger.right),
    })
  }, [open, ref])

  return (
    <div ref={ref} className="relative inline-flex">
      <IconButton
        icon={PaletteIcon}
        label={`Colour for ${name}`}
        onClick={(e) => {
          e.stopPropagation()
          setOpen((v) => !v)
        }}
      />
      {open &&
        createPortal(
          <div
            ref={panelRef}
            style={{
              position: 'fixed',
              top: pos?.top ?? 0,
              right: pos?.right ?? 0,
              visibility: pos ? 'visible' : 'hidden',
              maxWidth: 'calc(100vw - 16px)',
            }}
            className="z-10 flex w-max flex-wrap gap-1 rounded border border-slate-300 bg-white p-1 shadow-lg"
          >
            {/* …swatch buttons + auto + no colour, byte-identical to before… */}
          </div>,
          document.body,
        )}
    </div>
  )
}
```

(imports: `useLayoutEffect`, `useRef` from react — `useRef` is already imported; `createPortal` from `react-dom`.) Keep the swatch/auto/no-colour buttons byte-identical. Update the component doc comment to note the portal + why (the aside's overflow clip).

- [ ] **Step 3: Gate** — `npm run typecheck && npm run lint && npm test -- --run && npm run build`.

- [ ] **Step 4: Commit** — `git commit -am "fix(studio): role colour picker escapes the palette scroll clip via portal"`.

---

### Task 7: Visual verification — probe + capture + targeted screenshots

**Files:**
- Read-only verification; evidence to `docs/ui-polish/` (absolute `--out` path — a relative one writes a stray copy under `webapp/frontend/docs/`).

- [ ] **Step 1: Stand up an isolated stack.** The worktree needs its own backend venv:

```bash
cd /Users/khamit/lab-devices-wt/studio-ui-polish/webapp/backend
python3 -m venv .venv && .venv/bin/pip install -e ../.. -e ".[dev]"
```

Start `tests/devserver.py` and `npm run dev` on NON-default ports (a sibling checkout may own :5173/:8000 — W13/W14 both nearly captured the wrong app; `capture.mjs`'s `assertServerServesThisCheckout` preflight exists because of it).

- [ ] **Step 2: Run the committed harness** — `npm run probe:selftest`, then `npm run capture` against the dev URL with `--out /Users/khamit/lab-devices-wt/studio-ui-polish/docs/ui-polish/`. Expect R1-R5 at their established baselines (R4 sibling-height: 0; R5 within the documented residuals). Any NEW violation in touched areas (palette, canvas, streams) is a defect in Tasks 1-6 — fix before proceeding.

- [ ] **Step 3: Targeted Playwright screenshots** (scratchpad script, evidence into `docs/ui-polish/`): (a) roles panel with ≥2 roles, one custom color — dots visible, add-role chip after the last badge; (b) color picker open on the LAST role block of a long palette — popover fully visible (the old clip repro); (c) empty canvas — help text + single "drop here" box; (d) a parallel with 3 lanes + a branch with both arms — separators, no boxes; lane selected — ring visible; (e) streams panel with one used + one unused stream — badge right-aligned, no amber. Review each screenshot yourself before calling the task done.

- [ ] **Step 4: Full gate** — `npm run lint && npm run typecheck && npm test -- --run && npm run build`.

- [ ] **Step 5: Commit evidence** — `git add docs/ui-polish && git commit -m "docs(studio): visual evidence for UI polish round"`.
