# Scope-aware References Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** While a group's body is the active editing scope, surface that group's own typed params & locals across the Builder's reference surfaces — stream params/locals in the Streams section, role params (draggable) in the Roles section, plus the Inspector's Role/Into pickers and expression help — additive to the top-level roles/streams and scoped to that group only.

**Architecture:** One pure module (`builder/scopeRefs.ts`) derives "references available in the current scope" (top-level ∪ the active group's typed params/locals, the group's shown as `{name}` holes). Every consumer reads it through one hook (`useScopeRefs`) instead of re-reading `s.roles`/`s.streams`. At the workflow scope (`scope === null`) every derivation collapses to today's behavior, so nothing outside a group scope changes.

**Tech Stack:** React + Zustand (`docStore`), TypeScript, Vite, Vitest (pure-function tests only), oxlint, dnd-kit, Tailwind 4. Spec: `docs/superpowers/specs/2026-07-21-group-scope-references-design.md`.

## Global Constraints

- All work is under `webapp/frontend/`. Run commands from that directory.
- **Vitest tests cover pure functions only** — no component rendering, no jsdom (`webapp/frontend/CLAUDE.md` "Testing"). DOM wiring is verified by `npm run capture` (the probe harness) and by `npm run build` (tsc).
- **CI gate (what must be green to merge):** `npm run lint`, `npm test`, `npm run build`. `npm run capture` is a local discipline (run it after touching control classes / adding rows) but is NOT in CI.
- **Control height:** every input/select/inline-button renders at 24px via `controlClass()`/`inlineButtonClass()` from `src/ui/controls.ts`. Pass `width` as an option (`controlClass({ width: 'w-24' })`), never concatenate a width class.
- **Icons:** interactive icons via lucide-react through `IconButton`; no raw glyph characters for controls.
- **Tailwind class names must be complete literals** — no `` `bg-${x}-500` `` interpolation.
- **Text colour:** meaning-carrying secondary text uses `text-caption` (slate-600); incidental/empty-state uses `text-hint` (slate-500). On `bg-slate-100`/tinted surfaces use `text-caption` (text-hint fails AA there). Hatching (`bg-hatch`) is reserved for group scope + `group_ref` — do NOT use it for the new subsection dividers.
- **Commit** after each task's tests pass. Branch is `feat/studio-scope-references` (already checked out).

---

### Task 1: `builder/scopeRefs.ts` — pure scope-reference derivations

**Files:**
- Create: `webapp/frontend/src/builder/scopeRefs.ts`
- Test: `webapp/frontend/src/builder/scopeRefs.test.ts`

**Interfaces:**
- Consumes: `GroupDef` (`{ params: ParamDeclJson[]; locals: Record<string, LocalDeclJson>; body: BlockNode[] }`) from `./convert`; `RoleDeclJson` (`{ type: string; device?: string }`) from `../types/doc`; `useDocStore` from `../stores/docStore`.
- Produces (later tasks rely on these exact names/types):
  - `hole(name: string): string`
  - `activeGroup(scope: string | null, groups: Record<string, GroupDef>): GroupDef | null`
  - `rolesInScope(roles: Record<string, RoleDeclJson>, group: GroupDef | null): Record<string, RoleDeclJson>`
  - `groupRoleParamNames(group: GroupDef | null): Set<string>`
  - `interface ScopeStreamRef { ref: string; origin: 'param' | 'local'; units: string | null }`
  - `groupStreamRefs(group: GroupDef | null): ScopeStreamRef[]`
  - `scopeStreamNames(streams: Record<string, unknown>, group: GroupDef | null): string[]`
  - `scopeBindingNames(group: GroupDef | null): string[]`
  - `useScopeRefs(): { scope: string | null; group: GroupDef | null; roles: Record<string, RoleDeclJson>; streamHoles: string[]; roleParamNames: Set<string> }`

- [ ] **Step 1: Write the failing test**

Create `webapp/frontend/src/builder/scopeRefs.test.ts`:

```ts
import { describe, it, expect } from 'vitest'
import {
  hole,
  activeGroup,
  rolesInScope,
  groupRoleParamNames,
  groupStreamRefs,
  scopeStreamNames,
  scopeBindingNames,
} from './scopeRefs'
import type { GroupDef } from './convert'

const G = (over: Partial<GroupDef> = {}): GroupDef => ({ params: [], locals: {}, body: [], ...over })

// A group like morbidostat's `service` plus a role param and value params, exercising every kind.
const svc = G({
  params: [
    { name: 'param_pump', kind: 'role', device_type: 'pump' },
    { name: 'param_stream', kind: 'stream' },
    { name: 'tube', kind: 'int' },
    { name: 'note', kind: 'string' },
  ],
  locals: {
    local_stream: { kind: 'stream', units: 'AU' },
    c: { kind: 'binding', init: '0' },
  },
})

describe('hole', () => {
  it('wraps a name in braces', () => {
    expect(hole('param_pump')).toBe('{param_pump}')
  })
})

describe('activeGroup', () => {
  it('is null at the workflow scope', () => {
    expect(activeGroup(null, { svc })).toBeNull()
  })
  it('is null when scope names a group that does not exist', () => {
    expect(activeGroup('gone', {})).toBeNull()
  })
  it('returns the named group', () => {
    expect(activeGroup('svc', { svc })).toBe(svc)
  })
})

describe('rolesInScope', () => {
  const roles = { top_pump: { type: 'pump' }, valve1: { type: 'valve' } }
  it('returns the given roles unchanged at the workflow scope', () => {
    expect(rolesInScope(roles, null)).toBe(roles)
  })
  it('adds role-kind params as {hole} -> { type }, keeping top-level roles', () => {
    const r = rolesInScope(roles, svc)
    expect(r['{param_pump}']).toEqual({ type: 'pump' })
    expect(r.top_pump).toEqual({ type: 'pump' })
    expect(Object.keys(r)).toHaveLength(3)
  })
  it('ignores non-role params', () => {
    const r = rolesInScope(roles, svc)
    expect(r['{param_stream}']).toBeUndefined()
    expect(r['{tube}']).toBeUndefined()
  })
  it('does not mutate the input roles', () => {
    rolesInScope(roles, svc)
    expect(roles).not.toHaveProperty('{param_pump}')
  })
  it('skips a role param missing its device_type', () => {
    const g = G({ params: [{ name: 'p', kind: 'role' }] })
    expect(rolesInScope({}, g)).toEqual({})
  })
})

describe('groupRoleParamNames', () => {
  it('is empty at the workflow scope', () => {
    expect(groupRoleParamNames(null).size).toBe(0)
  })
  it('is the set of role-param holes', () => {
    const s = groupRoleParamNames(svc)
    expect(s.has('{param_pump}')).toBe(true)
    expect(s.size).toBe(1)
  })
})

describe('groupStreamRefs', () => {
  it('is empty at the workflow scope', () => {
    expect(groupStreamRefs(null)).toEqual([])
  })
  it('lists stream params then stream locals as holes, carrying units', () => {
    expect(groupStreamRefs(svc)).toEqual([
      { ref: '{param_stream}', origin: 'param', units: null },
      { ref: '{local_stream}', origin: 'local', units: 'AU' },
    ])
  })
})

describe('scopeStreamNames', () => {
  it('is the bare top-level stream names at the workflow scope', () => {
    expect(scopeStreamNames({ od: {}, blank: {} }, null)).toEqual(['od', 'blank'])
  })
  it('appends the group stream params & locals as holes', () => {
    expect(scopeStreamNames({ od: {} }, svc)).toEqual(['od', '{param_stream}', '{local_stream}'])
  })
})

describe('scopeBindingNames', () => {
  it('is empty at the workflow scope', () => {
    expect(scopeBindingNames(null)).toEqual([])
  })
  it('lists value/binding params then binding locals as holes, excluding role & stream', () => {
    expect(scopeBindingNames(svc)).toEqual(['{tube}', '{note}', '{c}'])
  })
})
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd webapp/frontend && npx vitest run src/builder/scopeRefs.test.ts`
Expected: FAIL — `Failed to resolve import "./scopeRefs"` / functions not defined.

- [ ] **Step 3: Write the implementation**

Create `webapp/frontend/src/builder/scopeRefs.ts`:

```ts
/** Scope-aware reference derivations (design 2026-07-21). While a group's body is the active
 * editing scope, the Builder's reference surfaces must offer that group's own typed params &
 * locals IN ADDITION to the top-level roles/streams — the group's shown as {name} holes, since
 * that is how a group body references them (engine expand.py `_HOLE_RE`). Kept pure (no React)
 * so the derivations are unit-testable; the one hook at the bottom is the single React entry
 * point. At the workflow scope (group === null) every function collapses to exactly the
 * top-level behavior, so nothing outside a group scope changes. */
import { useDocStore } from '../stores/docStore'
import type { GroupDef } from './convert'
import type { RoleDeclJson } from '../types/doc'

/** The {name} hole form a group body uses to reference its own param/local. */
export const hole = (name: string): string => `{${name}}`

/** The group currently being edited, or null at the workflow scope (or if scope names a group
 * that no longer exists). */
export function activeGroup(
  scope: string | null,
  groups: Record<string, GroupDef>,
): GroupDef | null {
  return scope === null ? null : (groups[scope] ?? null)
}

/** Role references usable in the active scope: every top-level role, PLUS the active group's
 * role-kind params keyed by their {hole} form -> { type: device_type }. Shaped exactly like
 * `s.roles` so ActionForm/RetrySection/roleGroups/rolesOfType consume it unchanged. Returns the
 * given `roles` (same reference) at the workflow scope. A role param missing its device_type is
 * skipped defensively — the engine requires it, but a half-typed row must not crash the UI. */
export function rolesInScope(
  roles: Record<string, RoleDeclJson>,
  group: GroupDef | null,
): Record<string, RoleDeclJson> {
  if (group === null) return roles
  const out: Record<string, RoleDeclJson> = { ...roles }
  for (const p of group.params) {
    if (p.kind === 'role' && p.device_type) out[hole(p.name)] = { type: p.device_type }
  }
  return out
}

/** The set of {hole} names contributed by the active group's role params — lets a consumer
 * partition a `rolesInScope` map's names into top-level vs. this-group entries for the additive
 * Roles display. Empty at the workflow scope. */
export function groupRoleParamNames(group: GroupDef | null): Set<string> {
  const names = new Set<string>()
  if (group !== null) {
    for (const p of group.params) if (p.kind === 'role') names.add(hole(p.name))
  }
  return names
}

export interface ScopeStreamRef {
  /** The name a body block uses to reference it — always the {hole} form here. */
  ref: string
  origin: 'param' | 'local'
  units: string | null
}

/** The active group's OWN stream references (its stream-kind params, then its stream-kind
 * locals), each as a {hole}. Empty at the workflow scope. Feeds the StreamsPanel "In this group"
 * subsection and (mapped to `.ref`) the Measure/Record Into picker's extra options. */
export function groupStreamRefs(group: GroupDef | null): ScopeStreamRef[] {
  if (group === null) return []
  const out: ScopeStreamRef[] = []
  for (const p of group.params) {
    if (p.kind === 'stream') out.push({ ref: hole(p.name), origin: 'param', units: null })
  }
  for (const [name, l] of Object.entries(group.locals)) {
    if (l.kind === 'stream') out.push({ ref: hole(name), origin: 'local', units: l.units ?? null })
  }
  return out
}

/** Stream names for expression help: bare top-level names + the active group's stream params &
 * locals as {holes}. */
export function scopeStreamNames(
  streams: Record<string, unknown>,
  group: GroupDef | null,
): string[] {
  return [...Object.keys(streams), ...groupStreamRefs(group).map((r) => r.ref)]
}

/** Scalar names usable in expressions, all as {holes}: the active group's VALUE params
 * (int/number/bool/string) and its binding params, then its binding locals. role/stream refs are
 * excluded — a role is a device name and a stream is offered under Streams, not as a scalar
 * binding. Callers union this with `collectBindings(activeTree)`. Empty at the workflow scope. */
export function scopeBindingNames(group: GroupDef | null): string[] {
  if (group === null) return []
  const out: string[] = []
  for (const p of group.params) {
    if (p.kind !== 'role' && p.kind !== 'stream') out.push(hole(p.name))
  }
  for (const [name, l] of Object.entries(group.locals)) {
    if (l.kind === 'binding') out.push(hole(name))
  }
  return out
}

/** The single React entry point: the active group plus the derivations every consumer needs,
 * subscribing to `roles`/`scope`/`groups` as separate slices (the same shape `useActiveTree`
 * uses) so a render fires only when one of those actually changes. */
export function useScopeRefs(): {
  scope: string | null
  group: GroupDef | null
  roles: Record<string, RoleDeclJson>
  streamHoles: string[]
  roleParamNames: Set<string>
} {
  const scope = useDocStore((s) => s.scope)
  const groups = useDocStore((s) => s.groups)
  const roles = useDocStore((s) => s.roles)
  const group = activeGroup(scope, groups)
  return {
    scope,
    group,
    roles: rolesInScope(roles, group),
    streamHoles: groupStreamRefs(group).map((r) => r.ref),
    roleParamNames: groupRoleParamNames(group),
  }
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd webapp/frontend && npx vitest run src/builder/scopeRefs.test.ts`
Expected: PASS (all cases).

- [ ] **Step 5: Lint the new files**

Run: `cd webapp/frontend && npm run lint`
Expected: 0 errors.

- [ ] **Step 6: Commit**

```bash
git add webapp/frontend/src/builder/scopeRefs.ts webapp/frontend/src/builder/scopeRefs.test.ts
git commit -m "feat(studio): pure scope-reference derivations (scopeRefs)"
```

---

### Task 2: Roles section shows the group's role params, draggable

**Files:**
- Modify: `webapp/frontend/src/builder/dnd.ts` (extend `palette-verb` payload)
- Modify: `webapp/frontend/src/builder/BuilderTab.tsx` (drop handler resolves via `deviceType`)
- Modify: `webapp/frontend/src/builder/RolesSection.tsx` (additive param badges + chips)

**Interfaces:**
- Consumes: `useScopeRefs` (Task 1); `roleGroups`, `effectiveSelection` (`./roleGroups`); `newVerbNode` (`./tree`) with signature `newVerbNode(role: string, verb: string, spec: VerbSpec)` → sets the node's `device` to `role`.
- Produces: verb-chip `DragPayload` now carries `deviceType: string`.

- [ ] **Step 1: Extend the drag payload type**

In `webapp/frontend/src/builder/dnd.ts`, change the `palette-verb` variant to add `deviceType`:

```ts
export type DragPayload =
  | { source: 'palette-block'; kind: PaletteKind }
  | { source: 'palette-group'; name: string }
  | { source: 'palette-verb'; role: string; verb: string; verbKind: 'command' | 'measure'; deviceType: string }
  | { source: 'canvas'; uid: string }
```

- [ ] **Step 2: Resolve the dropped verb via `deviceType`**

In `webapp/frontend/src/builder/BuilderTab.tsx`, `onDragEnd`, replace the final `palette-verb` arm (currently reading `s.roles[payload.role]?.type`) with a lookup keyed on the payload's `deviceType`, so a role-param chip (whose `role` is `{param_pump}`, absent from `s.roles`) still resolves:

```ts
    // palette-verb: `deviceType` comes from the palette chip (the role's device type), so a
    // role-param chip ({param_pump}, not in s.roles) resolves the same as a top-level role.
    const spec = catalog?.device_types[payload.deviceType]?.[payload.verb]
    if (spec) s.insertBlock(newVerbNode(payload.role, payload.verb, spec), at)
```

(The `newVerbNode(payload.role, …)` call is unchanged; `payload.role` is the bare name for a top-level role and the `{param_pump}` hole for a role param — both land in the node's `device` field, which is exactly right.)

- [ ] **Step 3: Make the Roles section scope-aware and partition badges**

In `webapp/frontend/src/builder/RolesSection.tsx`:

Replace the import of the doc-store roles selector with the scope hook, and thread `paramNames` down. Change `RolesSection` to:

```ts
export function RolesSection() {
  const catalog = useCatalogStore((s) => s.catalog)
  const { roles, roleParamNames } = useScopeRefs()
  const groups = roleGroups(roles, catalog)
  return (
    <div className="space-y-2">
      <p className="px-1 text-xs text-hint">
        Roles are symbolic — you bind them to real devices when you start a run.
      </p>
      {groups.length === 0 ? (
        <p className="px-1 text-xs text-hint">no device types in the catalog yet</p>
      ) : (
        groups.map((g) => (
          <RoleTypeBlock key={g.type} group={g} catalog={catalog} paramNames={roleParamNames} />
        ))
      )}
    </div>
  )
}
```

Add the import at the top: `import { useScopeRefs } from './scopeRefs'` and remove the now-unused `useDocStore` roles read in `RolesSection` (keep `useDocStore` imported — `RoleTypeBlock` still uses it for rename/remove/focusedRole).

In `RoleTypeBlock`, accept `paramNames`, partition `group.roles`, disable rename/delete for params, and render an additive "In this group" divider with the param badges. Replace the `RoleTypeBlock` signature and its badges/controls region:

```ts
function RoleTypeBlock({
  group,
  catalog,
  paramNames,
}: {
  group: RoleTypeGroup
  catalog: Catalog | null
  paramNames: Set<string>
}) {
  const renameRole = useDocStore((s) => s.renameRole)
  const removeRole = useDocStore((s) => s.removeRole)
  const focusedRole = useDocStore((s) => s.focusedRole)
  const [picked, setPicked] = useState<string | null>(null)
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState('')
  const [error, setError] = useState<string | null>(null)
  const cancelled = useRef(false)
  const selected = effectiveSelection(group.roles, picked)
  const selectedIsParam = selected !== null && paramNames.has(selected)
  const topRoles = group.roles.filter((r) => !paramNames.has(r))
  const groupParams = group.roles.filter((r) => paramNames.has(r))
  const isFocusedHere = focusedRole !== null && group.roles.includes(focusedRole)

  useEffect(() => {
    if (focusedRole === null || !isFocusedHere) return
    setPicked(focusedRole)
    document
      .getElementById(`role-${focusedRole}`)
      ?.scrollIntoView({ behavior: 'smooth', block: 'center' })
  }, [focusedRole, isFocusedHere])

  const startRename = () => {
    if (!selected) return
    setEditing(true)
    setDraft(selected)
    setError(null)
    cancelled.current = false
  }
  const commitRename = () => {
    if (!selected) return
    const err = draft && draft !== selected ? renameRole(selected, draft) : null
    setError(err)
    if (err === null) {
      setEditing(false)
      if (draft) setPicked(draft)
    }
  }

  // One badge renderer shared by the top-level and group-param rows. A group param is a
  // read-only {hole} reference here (edited in the group's Params panel), so it never enters
  // the rename input and is rendered font-mono to read as code.
  const badge = (name: string) => {
    const isParam = paramNames.has(name)
    return editing && name === selected && !isParam ? (
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
    ) : (
      <button
        key={name}
        id={`role-${name}`}
        onClick={() => {
          setPicked(name)
          setEditing(false)
          setError(null)
        }}
        className={
          badgeClass({ active: name === selected }) +
          (focusedRole === name ? ' ring-2 ring-amber-400' : '')
        }
      >
        <span className={'min-w-0 truncate' + (isParam ? ' font-mono' : '')} title={name}>
          {name}
        </span>
      </button>
    )
  }

  const verbs = group.known ? (catalog?.device_types[group.type] ?? {}) : null
  return (
    <div className="rounded border border-slate-200 bg-white p-1.5">
      <p className="mb-1 flex items-center text-xs font-semibold text-caption">
        <span className="min-w-0 truncate" title={group.type}>
          {group.type}
        </span>
        {!group.known && (
          <span className="ml-1 shrink-0 font-normal text-amber-700">— unknown device type</span>
        )}
      </p>
      {group.roles.length === 0 ? (
        <p className="mb-1 px-1 text-xs text-hint">no roles yet — add one to use this device</p>
      ) : (
        <div className="mb-1 flex flex-wrap items-center gap-1">
          {topRoles.map((name) => badge(name))}
          {/* rename/delete/colour act on `selected` and only make sense for a real top-level
              role — a group param is edited in the group's Params panel, so hide the cluster
              (and never render the rename input) when the selection is a param. */}
          {!selectedIsParam && (
            <span className="ml-auto flex items-center">
              {selected && <RoleColorPicker name={selected} type={group.type} />}
              <IconButton icon={Pencil} label="Rename selected role" onClick={startRename} />
              <IconButton
                icon={X}
                label="Delete selected role"
                destructive
                onClick={() => {
                  if (!selected) return
                  const err = removeRole(selected)
                  setError(err)
                  if (err === null) setPicked(null)
                }}
              />
            </span>
          )}
        </div>
      )}
      {groupParams.length > 0 && (
        <div className="mb-1">
          <p className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-caption">
            In this group
          </p>
          <div className="flex flex-wrap items-center gap-1">{groupParams.map((name) => badge(name))}</div>
        </div>
      )}
      {error && <p className="mb-1 text-xs text-red-600">{error}</p>}
      {selected !== null && verbs !== null && (
        <div className="flex flex-wrap gap-1">
          {Object.entries(verbs).map(([verb, spec]) => (
            <Chip
              key={verb}
              id={`palette-verb-${selected}-${verb}`}
              payload={{
                source: 'palette-verb',
                role: selected,
                verb,
                verbKind: spec.kind,
                deviceType: group.type,
              }}
            >
              <KindIcon kind={spec.kind === 'measure' ? 'measure' : 'command'} className="mr-1" />
              {verb}
            </Chip>
          ))}
        </div>
      )}
      <AddRoleForm type={group.type} onAdded={setPicked} />
    </div>
  )
}
```

- [ ] **Step 4: Typecheck & build**

Run: `cd webapp/frontend && npm run build`
Expected: `tsc -b` clean, `vite build` succeeds. (No new vitest — this is DOM wiring; `dnd.test.ts` still passes because the added payload field is optional-at-callsite only where constructed, and all constructors set it.)

- [ ] **Step 5: Run the existing suite + lint**

Run: `cd webapp/frontend && npm test && npm run lint`
Expected: all tests PASS (including `dnd.test.ts`, `roleGroups.test.ts`), lint 0 errors.

- [ ] **Step 6: Commit**

```bash
git add webapp/frontend/src/builder/dnd.ts webapp/frontend/src/builder/BuilderTab.tsx webapp/frontend/src/builder/RolesSection.tsx
git commit -m "feat(studio): show a group's role params in the Roles palette, draggable"
```

---

### Task 3: Streams section shows the group's stream params & locals

**Files:**
- Modify: `webapp/frontend/src/builder/StreamsPanel.tsx`

**Interfaces:**
- Consumes: `useScopeRefs`, `groupStreamRefs` (Task 1); `useActiveTree` (`../stores/docStore`); `streamSources` (`./refs`); `filterStreamNames` (`./streamFilter`).

- [ ] **Step 1: Add the read-only "In this group" subsection**

In `webapp/frontend/src/builder/StreamsPanel.tsx`, add imports:

```ts
import { useActiveTree, useDocStore } from '../stores/docStore'
import { streamSources } from './refs'
import { groupStreamRefs, useScopeRefs } from './scopeRefs'
```

Inside `StreamsPanel`, after `const sources = streamSources(tree)`, derive the group refs and their in-body source tags:

```ts
  const { scope, group } = useScopeRefs()
  const activeTree = useActiveTree()
  const groupSources = streamSources(activeTree)
  const groupRefs = groupStreamRefs(group)
  const visibleGroupRefs = new Set(filterStreamNames(groupRefs.map((r) => r.ref), query))
  const shownGroupRefs = groupRefs.filter((r) => visibleGroupRefs.has(r.ref))
```

Then, immediately before the closing `{error && …}` line at the bottom of the returned JSX (after the add-stream `<div>`), insert the subsection:

```tsx
      {scope !== null && shownGroupRefs.length > 0 && (
        <div className="mt-1 border-t border-slate-200 pt-1">
          <p className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-caption">
            In group “{scope}”
          </p>
          <ul className="space-y-1">
            {shownGroupRefs.map((r) => (
              <li key={r.ref} className="flex items-center gap-1 text-sm">
                <span className="min-w-0 flex-1 truncate font-mono text-caption" title={r.ref}>
                  {r.ref}
                </span>
                <span className="shrink-0 rounded bg-slate-100 px-1 text-xs text-caption">
                  {r.origin}
                </span>
                {r.units && <span className="shrink-0 text-xs text-hint">{r.units}</span>}
                <span
                  title={
                    groupSources[r.ref] === undefined
                      ? 'No block in this group writes this stream'
                      : `Written by a ${groupSources[r.ref]} block`
                  }
                  className={
                    'flex h-6 shrink-0 items-center rounded px-1 text-xs ' +
                    (groupSources[r.ref] === undefined
                      ? 'bg-amber-100 text-amber-700'
                      : 'bg-slate-200 text-slate-600')
                  }
                >
                  {groupSources[r.ref] ?? 'unused'}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
```

(The subsection is read-only by design — stream params/locals are authored in the group's Inspector Params/Locals panels, per the spec.)

- [ ] **Step 2: Typecheck & build**

Run: `cd webapp/frontend && npm run build`
Expected: clean.

- [ ] **Step 3: Run tests + lint**

Run: `cd webapp/frontend && npm test && npm run lint`
Expected: PASS, 0 lint errors.

- [ ] **Step 4: Commit**

```bash
git add webapp/frontend/src/builder/StreamsPanel.tsx
git commit -m "feat(studio): show a group's stream params & locals in the Streams palette"
```

---

### Task 4: Inspector pickers recognize the group's role/stream refs

**Files:**
- Modify: `webapp/frontend/src/builder/StreamIntoPicker.tsx` (add `extraOptions`)
- Modify: `webapp/frontend/src/builder/Inspector.tsx` (`ActionForm`, `RetrySection`, `ArgField`, `IntoPicker`, `ValueForm`)

**Interfaces:**
- Consumes: `useScopeRefs` (Task 1). `StreamIntoPicker` gains an optional `extraOptions?: string[]` prop (hole names rendered as extra `<option>`s).

- [ ] **Step 1: Add `extraOptions` to `StreamIntoPicker`**

In `webapp/frontend/src/builder/StreamIntoPicker.tsx`, change the props and render extra options after the real streams:

```ts
export function StreamIntoPicker(props: {
  value: string
  onPick: (name: string) => void
  extraOptions?: string[]
}) {
  const { value, onPick, extraOptions } = props
```

and inside the `<select>`, after the `{names.map(…)}` block and before the `+ new stream…` option, add:

```tsx
        {(extraOptions ?? [])
          .filter((h) => !names.includes(h))
          .map((h) => (
            <option key={h} value={h}>
              {h}
            </option>
          ))}
```

- [ ] **Step 2: Make `ActionForm`, `RetrySection`, `ArgField` roles scope-aware**

In `webapp/frontend/src/builder/Inspector.tsx`, add the import:

```ts
import { useScopeRefs } from './scopeRefs'
```

In `ActionForm`, replace `const roles = useDocStore((s) => s.roles)` with:

```ts
  const { roles } = useScopeRefs()
```

In `RetrySection`, replace `const roles = useDocStore((s) => s.roles)` with:

```ts
  const { roles } = useScopeRefs()
```

In `ArgField`, replace `const roles = useDocStore((s) => s.roles)` with:

```ts
  const { roles } = useScopeRefs()
```

(These three now resolve `{param_pump}` to its type, so the Role dropdown offers it, verbs populate, and the `unknown role` banner clears when a valid role param is referenced.)

- [ ] **Step 3: Pass the group's stream holes to the Measure/Record Into pickers**

In `IntoPicker` (the Measure destination), read the holes and pass them:

```ts
function IntoPicker({ node }: { node: MeasureNode }) {
  const patchBlock = useDocStore((s) => s.patchBlock)
  const { streamHoles } = useScopeRefs()
  return (
    <FieldRow label="Into stream" required>
      <StreamIntoPicker
        value={node.into}
        onPick={(name) => patchBlock(node.uid, { into: name })}
        extraOptions={streamHoles}
      />
    </FieldRow>
  )
}
```

In `ValueForm`, read the holes once and pass them to the record branch's `StreamIntoPicker`:

```ts
function ValueForm({ node }: { node: ComputeNode | RecordNode }) {
  const patchBlock = useDocStore((s) => s.patchBlock)
  const { streamHoles } = useScopeRefs()
  return (
    <div>
      {node.kind === 'compute' ? (
        <FieldRow label="Into (binding)" required>
          <TextField
            mono
            value={node.into}
            onCommit={(v) => patchBlock(node.uid, { into: v })}
            placeholder="c_1"
          />
        </FieldRow>
      ) : (
        <FieldRow label="Into stream" required>
          <StreamIntoPicker
            value={node.into}
            onPick={(v) => patchBlock(node.uid, { into: v })}
            extraOptions={streamHoles}
          />
        </FieldRow>
      )}
      <FieldRow label="Value" required>
        <ExpressionInput
          value={String(node.value)}
          onCommit={(v) => patchBlock(node.uid, { value: coerceValueInput(v) })}
        />
      </FieldRow>
    </div>
  )
}
```

- [ ] **Step 4: Typecheck & build**

Run: `cd webapp/frontend && npm run build`
Expected: clean. (`StreamIntoPicker`'s existing callers in `ArgField` still typecheck — `extraOptions` is optional.)

- [ ] **Step 5: Run tests + lint**

Run: `cd webapp/frontend && npm test && npm run lint`
Expected: PASS, 0 lint errors.

- [ ] **Step 6: Commit**

```bash
git add webapp/frontend/src/builder/StreamIntoPicker.tsx webapp/frontend/src/builder/Inspector.tsx
git commit -m "feat(studio): Inspector Role & Into pickers recognize a group's typed refs"
```

---

### Task 5: Expression help lists the group's holes

**Files:**
- Modify: `webapp/frontend/src/builder/fields.tsx` (`ExpressionInput`)

**Interfaces:**
- Consumes: `useScopeRefs`, `scopeStreamNames`, `scopeBindingNames` (Task 1); existing `collectBindings`, `useActiveTree`.

- [ ] **Step 1: Feed scope-aware stream & binding lists to the help builder**

In `webapp/frontend/src/builder/fields.tsx`, add the import:

```ts
import { scopeBindingNames, scopeStreamNames, useScopeRefs } from './scopeRefs'
```

In `ExpressionInput`, replace the `help` derivation. The current code is:

```ts
  const activeTree = useActiveTree()
  const expression = useCatalogStore((s) => s.catalog?.expression ?? null)
  const help = expression
    ? buildExpressionHelp(expression, Object.keys(streams), collectBindings(activeTree))
    : null
```

Change it to union the group's stream/binding holes:

```ts
  const activeTree = useActiveTree()
  const { group } = useScopeRefs()
  const expression = useCatalogStore((s) => s.catalog?.expression ?? null)
  const help = expression
    ? buildExpressionHelp(
        expression,
        scopeStreamNames(streams, group),
        Array.from(new Set([...collectBindings(activeTree), ...scopeBindingNames(group)])),
      )
    : null
```

- [ ] **Step 2: Typecheck & build**

Run: `cd webapp/frontend && npm run build`
Expected: clean.

- [ ] **Step 3: Run tests + lint**

Run: `cd webapp/frontend && npm test && npm run lint`
Expected: PASS, 0 lint errors.

- [ ] **Step 4: Commit**

```bash
git add webapp/frontend/src/builder/fields.tsx
git commit -m "feat(studio): expression help lists a group's stream/binding/value holes"
```

---

### Task 6: Capture fixture + probe states, then full verification

**Files:**
- Create: `webapp/fixtures/group-scope-refs.json`
- Modify: `webapp/frontend/tools/capture.mjs` (FIXTURES entry + states)

**Interfaces:**
- Consumes: the capture harness helpers `gotoBuilder`, `importDoc`, `selectScope`, `selectBlock` (all in `capture.mjs`).

- [ ] **Step 1: Add a fixture exercising every new ref kind**

Create `webapp/fixtures/group-scope-refs.json`:

```json
{
  "doc_version": 1,
  "name": "Group scope refs probe",
  "description": null,
  "workflow": {
    "schema_version": 2,
    "roles": { "top_pump": { "type": "pump" } },
    "streams": { "od_top": { "units": "AU" } },
    "groups": {
      "probe_group": {
        "params": [
          { "name": "param_pump", "kind": "role", "device_type": "pump" },
          { "name": "param_stream", "kind": "stream" },
          { "name": "tube", "kind": "int" }
        ],
        "locals": {
          "local_stream": { "kind": "stream", "units": "AU" },
          "c": { "kind": "binding", "init": "0" }
        },
        "body": [
          {
            "command": {
              "device": "{param_pump}",
              "verb": "dispense",
              "params": { "volume_ml": 1, "speed_ml_min": 5, "direction": "forward" }
            },
            "label": "pump via role param"
          },
          { "record": { "into": "{local_stream}", "value": "{c}" }, "label": "record into local stream" },
          {
            "branch": { "if": "count({param_stream}, last=5min) > 0", "then": [] },
            "label": "branch on stream param"
          }
        ]
      }
    },
    "blocks": [
      {
        "group_ref": {
          "name": "probe_group",
          "as": "p1",
          "args": { "param_pump": "top_pump", "param_stream": "od_top", "tube": 1 }
        },
        "label": "call probe_group"
      }
    ]
  }
}
```

(A top-level `group_ref` gives `importDoc` a block card to wait on; `top_pump`/`od_top` exercise the additive divider — the pump block shows a top role AND `{param_pump}`, and the Streams list shows `od_top` above the "In this group" subsection.)

- [ ] **Step 2: Register the fixture and add probe states**

In `webapp/frontend/tools/capture.mjs`, add to the `FIXTURES` object:

```js
  groupScopeRefs: path.join(repoRoot, 'webapp/fixtures/group-scope-refs.json'),
```

Then add these entries to the `states` array (anywhere after `group-scope-deep`):

```js
  {
    name: 'group-scope-roles-streams',
    description:
      'editing probe_group: the Roles pump block shows top_pump AND the {param_pump} role ' +
      'param under an "In this group" divider (its verb chips draggable), and the opened ' +
      'Streams section shows od_top above the {param_stream}/{local_stream} subsection. The ' +
      'state that makes the new palette subsections non-vacuous for R4/R5 and the ' +
      'truncate-with-title rule.',
    setup: async (page) => {
      await gotoBuilder(page)
      await importDoc(page, FIXTURES.groupScopeRefs)
      await selectScope(page, 'probe_group')
      // Select the role-param badge so its draggable verb chips actually mount.
      await page.locator('[id="role-{param_pump}"]').click()
      await page.getByRole('button', { name: 'Streams', exact: true }).click()
      await page.waitForTimeout(200)
      // Assert the new DOM mounted, or the capture would be a vacuous clean pass.
      if ((await page.locator('[id="role-{param_pump}"]').count()) !== 1) {
        throw new Error('the {param_pump} role-param badge did not mount')
      }
    },
  },
  {
    name: 'group-scope-expression',
    description:
      'the expression-help popover while editing probe_group: its Streams list includes ' +
      '{param_stream}/{local_stream} and its Bindings list includes {tube}/{c}. Guards the ' +
      'scope-aware help wiring.',
    setup: async (page) => {
      await gotoBuilder(page)
      await importDoc(page, FIXTURES.groupScopeRefs)
      await selectScope(page, 'probe_group')
      await selectBlock(page, /branch on stream param|^\s*If /)
      await page.getByRole('button', { name: 'Expression help' }).first().click()
      await page.waitForTimeout(200)
    },
  },
```

- [ ] **Step 3: Run the capture harness (local; requires dev + backend servers)**

Bring up the app, then capture. From the repo root, in three shells (or backgrounded):

```bash
# backend (serves /api/catalog, needed for verb chips)
python -m pip install -e . -e "webapp/backend[dev]"   # once
python -m uvicorn app.main:app --app-dir webapp/backend --port 8000 &
# frontend dev server
cd webapp/frontend && npm run dev &   # serves http://localhost:5173, proxies /api to :8000
```

Then:

```bash
cd webapp/frontend && npm run capture
```

Expected: every state×viewport combination reports clean (0 accessibility/layout violations), including the two new `group-scope-*` states. If a truncation/contrast/sibling-height violation is reported on a new row, fix the class per `webapp/frontend/CLAUDE.md` and re-run.

> If the local servers cannot be started in this environment, record that capture was not run and rely on `npm run build` + the CI gates; the new rows follow the exact class patterns of the existing role badges / stream rows (truncate + `title`, `text-caption` on tinted chips), which the probe already validates on the top-level equivalents.

- [ ] **Step 4: Commit**

```bash
git add webapp/fixtures/group-scope-refs.json webapp/frontend/tools/capture.mjs
git commit -m "test(studio): capture fixture + probe states for group-scope references"
```

---

### Task 7: Final gate — full suite as CI runs it

**Files:** none (verification only).

- [ ] **Step 1: Run the exact CI frontend gate**

```bash
cd webapp/frontend && npm run lint && npm test && npm run build
```

Expected: lint 0 errors; all vitest suites PASS (incl. `scopeRefs.test.ts`); `tsc -b` + `vite build` clean. This mirrors the `webapp-frontend` CI job exactly.

- [ ] **Step 2: Push the branch and open the PR**

```bash
git push -u origin feat/studio-scope-references
gh pr create --fill --base main --head feat/studio-scope-references
```

- [ ] **Step 3: Wait for CI, then merge**

Poll `gh pr checks` until all required checks are green, then `gh pr merge --squash`. If a check fails, read the log, fix on the branch, push, and re-poll.

---

## Self-Review

**Spec coverage:**
- "Streams section shows param_stream + local_stream (this group only)" → Task 3 (`groupStreamRefs` + subsection, gated on `scope !== null`).
- "Roles section shows param_pump (grouped by type), draggable to canvas (this group only)" → Task 2 (partitioned badges under the device-type block, chip payload `deviceType`, drop handler).
- Additive display model → Tasks 2 & 3 keep top-level entries and add an "In this group" divider; `rolesInScope`/`groupStreamRefs` are additive.
- Full coherence (Complete): Inspector Role dropdown / Into picker (Task 4), expression help incl. value + binding holes (Task 5).
- Single "references-in-scope" derivation feeding all consumers → Task 1 (`scopeRefs.ts` + `useScopeRefs`).
- Testing: pure unit tests (Task 1) + probe capture states (Task 6) + CI gate (Task 7). All spec requirements map to a task.

**Placeholder scan:** No TBD/TODO/"handle edge cases"; every code step shows complete code. The one conditional note (Task 6 Step 3) is an environment fallback for the non-CI capture, not a code placeholder.

**Type consistency:** `useScopeRefs()` returns `{ scope, group, roles, streamHoles, roleParamNames }` (Task 1) and every consumer destructures exactly those names (Tasks 2–5). `palette-verb` payload gains `deviceType: string` (Task 2 Step 1) and every constructor (RolesSection chip, Task 2 Step 3) sets it; the sole reader (BuilderTab, Task 2 Step 2) uses it. `StreamIntoPicker` gains `extraOptions?: string[]` (Task 4 Step 1); new callers pass `streamHoles: string[]` (Task 4 Step 3), existing `ArgField` caller unaffected (optional). `ScopeStreamRef.origin` is `'param' | 'local'` in both the type and `groupStreamRefs`.
