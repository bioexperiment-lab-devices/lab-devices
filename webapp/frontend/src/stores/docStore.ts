/** Single document store for the builder. The temporal (zundo) wrapper snapshots ONLY
 * the document fields, so undo/redo never touches selection, diagnostics, or save
 * bookkeeping. Dirty state is derived by comparing against the last saved snapshot. */
import { create } from 'zustand'
import { useStore, type StoreApi } from 'zustand'
import { temporal, type TemporalState } from 'zundo'
import type { ExperimentDocJson, WorkflowJson } from '../types/doc'
import type { MappedDiagnostic } from '../builder/paths'
import { treeToDoc, type DocContent } from '../builder/convert'
import {
  containsUid,
  duplicateNode,
  insertNode,
  moveNode,
  removeNode,
  updateNode,
  type BlockNode,
  type SlotRef,
} from '../builder/tree'
import {
  countGroupRefs,
  countRoleRefs,
  countStreamRefs,
  renameGroupRefs,
  renameRoleRefs,
  renameStreamRefs,
} from '../builder/refs'

export const ROLE_NAME_RE = /^[a-z][a-z0-9_]*$/
export const STREAM_NAME_RE = /^[A-Za-z_][A-Za-z0-9_]*$/
// A group name is interpolated into `{holes}` (engine expand.py's `_HOLE_RE`/validate.py's
// `_IDENT_RE`), so it must be a plain identifier — the same character class as STREAM_NAME_RE,
// kept as its own constant since roles/streams/groups are three separate namespaces.
export const GROUP_NAME_RE = /^[A-Za-z_][A-Za-z0-9_]*$/

export interface DocSnapshot {
  name: string
  description: string | null
  roles: Record<string, { type: string }>
  // persistence is a per-stream override (2026-07-14 review, I2) — no UI sets it, but it
  // must survive store round trips the same way workflow-level persistence/defaults do.
  streams: Record<string, { units: string | null; persistence?: string | null }>
  tree: BlockNode[]
  // Reusable, parametrized group bodies invoked via group_ref (design §5.2). Unlike
  // persistence/defaults/metadata below, groups is NOT opaque carry-through: the store has a
  // full authoring API for it (addGroup/renameGroup/removeGroup/setGroupParams), so it is a
  // required field, like tree, defaulting to {} rather than being carried as `undefined`.
  groups: Record<string, { params: string[]; body: BlockNode[] }>
  // Carried opaquely through load -> save (2026-07-14 review, Fix 1): the builder has no
  // UI for either, but a hand-authored workflow.defaults.retry or custom persistence
  // setting must survive a round trip through the store, not just through convert.ts's
  // pure functions in isolation.
  persistence?: WorkflowJson['persistence']
  defaults?: WorkflowJson['defaults']
  // Carried opaquely through load -> save, same reason as persistence/defaults above: a
  // hand-authored workflow.metadata.author/description must survive a round trip through
  // the store, not just through convert.ts's pure functions in isolation.
  metadata?: WorkflowJson['metadata']
}

export interface EditorState extends DocSnapshot {
  serverId: string | null
  savedSnapshot: string
  selectedUid: string | null
  // The active editing scope: null is the main workflow, else a key into `groups` (design
  // §5.2). This is VIEW state, not a document field — it must stay out of the zundo snapshot
  // exactly like selectedUid (file header comment), so undo/redo never rewrites it directly.
  scope: string | null
  // Which role RolesPanel should scroll to and highlight, set by a Problems row click on a
  // role diagnostic (paths.ts's `MappedDiagnostic.role`, previously read by nothing). VIEW
  // state like `scope`/`selectedUid` above — not part of the zundo snapshot.
  focusedRole: string | null
  // Which block uid Canvas should scroll to, set by a Problems row click on a block
  // diagnostic. A dedicated field rather than reusing `selectedUid` for this: `select()` is
  // also called by ordinary canvas clicks, and Canvas's own re-render (after a cross-scope
  // `setScope`) has to land before the scroll query runs, exactly like `focusedRole` above —
  // a same-tick `document.getElementById` in the click handler races React's batched commit
  // for the new scope's DOM and silently no-ops (2026-07-16 review, Finding 2). VIEW state,
  // not part of the zundo snapshot.
  scrollToUid: string | null
  collapsed: Record<string, boolean>
  diagnostics: MappedDiagnostic[]
  validating: boolean
  validationError: string | null
  setName: (name: string) => void
  setDescription: (description: string | null) => void
  insertBlock: (node: BlockNode, at: SlotRef) => void
  moveBlock: (uid: string, to: SlotRef) => void
  removeBlock: (uid: string) => void
  duplicateBlock: (uid: string) => void
  patchBlock: (uid: string, patch: object) => void
  addRole: (name: string, type: string) => string | null
  renameRole: (from: string, to: string) => string | null
  removeRole: (name: string) => string | null
  addStream: (name: string, units: string | null) => string | null
  renameStream: (from: string, to: string) => string | null
  removeStream: (name: string) => string | null
  setStreamUnits: (name: string, units: string | null) => void
  setScope: (scope: string | null) => void
  focusRole: (name: string | null) => void
  scrollToBlock: (uid: string | null) => void
  addGroup: (name: string) => string | null
  renameGroup: (from: string, to: string) => string | null
  removeGroup: (name: string) => string | null
  setGroupParams: (name: string, params: string[]) => void
  select: (uid: string | null) => void
  toggleCollapsed: (uid: string) => void
  setDiagnostics: (diags: MappedDiagnostic[]) => void
  setValidating: (v: boolean) => void
  setValidationError: (e: string | null) => void
  markSaved: (serverId: string, savedSnapshot?: string) => void
}

export const selectContent = (s: DocSnapshot): DocContent => ({
  name: s.name,
  description: s.description,
  roles: s.roles,
  streams: s.streams,
  tree: s.tree,
  groups: s.groups,
  ...(s.persistence !== undefined ? { persistence: s.persistence } : {}),
  ...(s.defaults !== undefined ? { defaults: s.defaults } : {}),
  ...(s.metadata !== undefined ? { metadata: s.metadata } : {}),
})

/** The dirty-check, and the value `markSaved`/`loadDoc` compare against. It must cover EVERY
 * field the store round-trips into the saved document — `persistence` and `defaults` included.
 * No UI mutates those two today, so omitting them was inert; the moment one does, a change to
 * either would leave the doc reading clean and be silently dropped on navigate-away. (An absent
 * key and an `undefined` one stringify identically, so adding them does not perturb any existing
 * snapshot: a doc with no `defaults` produces the same string as before.) */
export const snapshotOf = (content: DocContent): string =>
  JSON.stringify({
    name: content.name,
    description: content.description,
    roles: content.roles,
    streams: content.streams,
    tree: content.tree,
    groups: content.groups,
    persistence: content.persistence,
    defaults: content.defaults,
    metadata: content.metadata,
  })

export const selectDoc = (s: DocSnapshot): ExperimentDocJson => treeToDoc(selectContent(s))

export const selectDirty = (s: EditorState): boolean =>
  snapshotOf(selectContent(s)) !== s.savedSnapshot

const emptyContent = (): DocContent => ({
  name: 'Untitled experiment',
  description: null,
  roles: {},
  streams: {},
  tree: [],
  groups: {},
})

const renameKey = <V>(rec: Record<string, V>, from: string, to: string): Record<string, V> =>
  Object.fromEntries(Object.entries(rec).map(([k, v]) => [k === from ? to : k, v]))

const removeKey = <V>(rec: Record<string, V>, key: string): Record<string, V> =>
  Object.fromEntries(Object.entries(rec).filter(([k]) => k !== key))

/** Applies one of the renameXRefs helpers (refs.ts) to every group's body — groups are real,
 * editable containers of command/measure/record blocks (design §5.2), so a role/stream/group
 * rename must reach references inside them, exactly as it already reaches the main tree.
 * `rename` preserves array identity when a body has no matching ref (refs.ts's mapNodes), so
 * this keeps that property one level up: a group untouched by the rename gets back the SAME
 * object, not a structurally-equal new one — followUndoScope (below) depends on that identity
 * staying meaningful. */
const renameRefsInGroups = (
  groups: Record<string, { params: string[]; body: BlockNode[] }>,
  rename: (body: BlockNode[]) => BlockNode[],
): Record<string, { params: string[]; body: BlockNode[] }> =>
  Object.fromEntries(
    Object.entries(groups).map(([name, g]) => {
      const body = rename(g.body)
      return [name, body === g.body ? g : { ...g, body }]
    }),
  )

/** The Palette/Inspector/drag-drop/expression-help operate on "the current tree" (design
 * §5.2) — a selector over whichever list `scope` names, not a fixed field. These two helpers
 * are the single place that resolves it, so the five block ops below need not each re-derive
 * the scope check; `activeList` reads, `setActiveList` returns the partial `set()` patch that
 * writes back to the same list, keeping the same in-place-update/patch shape the ops already
 * use. `activeList` is exported as a plain function (not a hook) for the one non-component
 * caller (BuilderTab.tsx's `dragLabel`, which reads via `useDocStore.getState()` rather than
 * the hook); `useActiveTree` below wraps it for the React call sites (Canvas.tsx, Inspector.tsx,
 * fields.tsx) so every one of the four resolves scope through this single helper instead of
 * re-deriving `scope === null ? tree : groups[scope]?.body ?? []` independently (2026-07-16
 * review, Findings 1+2 — the fourth copy, in fields.tsx, left group-body expressions unable
 * to see their own group's bindings in the ƒ popover). */
export const activeList = (s: Pick<EditorState, 'scope' | 'tree' | 'groups'>): BlockNode[] =>
  s.scope === null ? s.tree : (s.groups[s.scope]?.body ?? [])

const setActiveList = (
  s: Pick<EditorState, 'scope' | 'tree' | 'groups'>,
  list: BlockNode[],
): Partial<Pick<EditorState, 'tree' | 'groups'>> =>
  s.scope === null
    ? { tree: list }
    : {
        groups: {
          ...s.groups,
          [s.scope]: { params: s.groups[s.scope]?.params ?? [], body: list },
        },
      }

export const useDocStore = create<EditorState>()(
  temporal(
    (set, get) => ({
      ...emptyContent(),
      // Restated explicitly (not just via the `...emptyContent()` spread above): DocContent
      // declares `groups` optional (Record<...> | undefined) for callers that predate it, so
      // TS widens the spread's `groups` to include `undefined` — but EditorState's `groups`
      // is required, like `tree`. The runtime value is the same {} either way.
      groups: {},
      serverId: null,
      savedSnapshot: snapshotOf(emptyContent()),
      selectedUid: null,
      scope: null,
      focusedRole: null,
      scrollToUid: null,
      collapsed: {},
      diagnostics: [],
      validating: false,
      validationError: null,

      setName: (name) => set({ name }),
      setDescription: (description) => set({ description }),

      insertBlock: (node, at) =>
        set((s) => ({
          ...setActiveList(s, insertNode(activeList(s), node, at)),
          selectedUid: node.uid,
        })),

      moveBlock: (uid, to) => set((s) => setActiveList(s, moveNode(activeList(s), uid, to))),

      removeBlock: (uid) =>
        set((s) => {
          const [list, removed] = removeNode(activeList(s), uid)
          const selectionGone =
            s.selectedUid !== null && removed !== null && containsUid(removed, s.selectedUid)
          return { ...setActiveList(s, list), selectedUid: selectionGone ? null : s.selectedUid }
        }),

      duplicateBlock: (uid) =>
        set((s) => {
          const [list, cloneUid] = duplicateNode(activeList(s), uid)
          return { ...setActiveList(s, list), selectedUid: cloneUid ?? s.selectedUid }
        }),

      patchBlock: (uid, patch) =>
        set((s) => setActiveList(s, updateNode(activeList(s), uid, patch))),

      addRole: (name, type) => {
        if (!ROLE_NAME_RE.test(name)) return `role name must match [a-z][a-z0-9_]*`
        if (name in get().roles) return `role '${name}' already exists`
        set((s) => ({ roles: { ...s.roles, [name]: { type } } }))
        return null
      },

      // A role can be referenced from inside a group body, not just the main tree (a group
      // is a real, editable container of command/measure/record blocks, exactly like the
      // main tree) — so rename must cascade into every group body, the same way renameGroup
      // already cascades group_refs there. Leaving groups un-cascaded would let a rename
      // orphan a role reference that lives only inside a group (Task 9 review, Finding 1).
      renameRole: (from, to) => {
        if (from === to) return null
        if (!ROLE_NAME_RE.test(to)) return `role name must match [a-z][a-z0-9_]*`
        if (to in get().roles) return `role '${to}' already exists`
        set((s) => ({
          roles: renameKey(s.roles, from, to),
          tree: renameRoleRefs(s.tree, from, to),
          groups: renameRefsInGroups(s.groups, (body) => renameRoleRefs(body, from, to)),
        }))
        return null
      },

      // Counting only the main tree let a role used exclusively inside a group body (e.g. a
      // `command.device` in `groups.service.body`) be deleted with zero warning — Save never
      // gates on validation (Toolbar.tsx), so that silently persisted a doc whose group body
      // cited a role that no longer existed in `roles` (Task 9 review, Finding 1).
      removeRole: (name) => {
        const { tree, groups } = get()
        let refs = countRoleRefs(tree, name)
        for (const g of Object.values(groups)) refs += countRoleRefs(g.body, name)
        if (refs > 0) return `role '${name}' is used by ${refs} block${refs === 1 ? '' : 's'}`
        set((s) => ({ roles: removeKey(s.roles, name) }))
        return null
      },

      addStream: (name, units) => {
        if (!STREAM_NAME_RE.test(name)) return `stream name must be an identifier`
        if (name in get().streams) return `stream '${name}' already exists`
        set((s) => ({ streams: { ...s.streams, [name]: { units } } }))
        return null
      },

      // Same reasoning as renameRole above: a measure/record block writing into this stream
      // can live inside a group body, not just the main tree, so the rename must cascade there
      // too (Task 9 review, Finding 1 — code-identical to the role half).
      renameStream: (from, to) => {
        if (from === to) return null
        if (!STREAM_NAME_RE.test(to)) return `stream name must be an identifier`
        if (to in get().streams) return `stream '${to}' already exists`
        set((s) => ({
          streams: renameKey(s.streams, from, to),
          tree: renameStreamRefs(s.tree, from, to),
          groups: renameRefsInGroups(s.groups, (body) => renameStreamRefs(body, from, to)),
        }))
        return null
      },

      // Same reasoning as removeRole above: counting only the main tree let a stream used
      // exclusively inside a group body be deleted with zero warning (Task 9 review, Finding 1).
      removeStream: (name) => {
        const { tree, groups } = get()
        let refs = countStreamRefs(tree, name)
        for (const g of Object.values(groups)) refs += countStreamRefs(g.body, name)
        if (refs > 0) return `stream '${name}' is used by ${refs} block${refs === 1 ? '' : 's'}`
        set((s) => ({ streams: removeKey(s.streams, name) }))
        return null
      },

      setStreamUnits: (name, units) =>
        set((s) => ({
          // Spread the existing entry first (2026-07-14 review, I2): replacing it outright
          // silently destroyed a per-stream `persistence` override the moment its units
          // were edited, even before the doc was ever saved.
          streams: name in s.streams ? { ...s.streams, [name]: { ...s.streams[name], units } } : s.streams,
        })),

      setScope: (scope) => set({ scope, selectedUid: null }),
      focusRole: (name) => set({ focusedRole: name }),
      scrollToBlock: (uid) => set({ scrollToUid: uid }),

      addGroup: (name) => {
        if (!GROUP_NAME_RE.test(name)) return `group name must be an identifier`
        if (name in get().groups) return `group '${name}' already exists`
        set((s) => ({ groups: { ...s.groups, [name]: { params: [], body: [] } } }))
        return null
      },

      renameGroup: (from, to) => {
        if (from === to) return null
        if (!GROUP_NAME_RE.test(to)) return `group name must be an identifier`
        if (to in get().groups) return `group '${to}' already exists`
        set((s) => {
          // A group can group_ref another group (design §5.2), so the rename must cascade
          // through every group body as well as the main tree — otherwise a rename produces
          // the exact "unknown group" dangling reference this task's START HERE bug produced
          // on save, just triggered here instead.
          const renamed = renameKey(s.groups, from, to)
          return {
            groups: renameRefsInGroups(renamed, (body) => renameGroupRefs(body, from, to)),
            tree: renameGroupRefs(s.tree, from, to),
            // Follow the rename if it targets the group currently being viewed — otherwise
            // scope would keep naming a key that no longer exists in `groups`, and the next
            // edit through activeList/setActiveList would silently resurrect an empty group
            // under the old name (design §5.2's scope-follow rule, applied to a rename).
            scope: s.scope === from ? to : s.scope,
          }
        })
        return null
      },

      removeGroup: (name) => {
        const { tree, groups } = get()
        let refs = countGroupRefs(tree, name)
        for (const g of Object.values(groups)) refs += countGroupRefs(g.body, name)
        if (refs > 0) return `group '${name}' is used by ${refs} block${refs === 1 ? '' : 's'}`
        set((s) => {
          const selectedUid = s.selectedUid
          const removedBody = s.groups[name]?.body ?? []
          const selectionGone =
            selectedUid !== null && removedBody.some((n) => containsUid(n, selectedUid))
          return {
            groups: removeKey(s.groups, name),
            scope: s.scope === name ? null : s.scope,
            selectedUid: selectionGone ? null : s.selectedUid,
          }
        })
        return null
      },

      setGroupParams: (name, params) =>
        set((s) =>
          name in s.groups
            ? { groups: { ...s.groups, [name]: { ...s.groups[name], params: [...params] } } }
            : {},
        ),

      select: (uid) => set({ selectedUid: uid }),
      toggleCollapsed: (uid) =>
        set((s) => ({ collapsed: { ...s.collapsed, [uid]: !s.collapsed[uid] } })),
      setDiagnostics: (diagnostics) => set({ diagnostics }),
      setValidating: (validating) => set({ validating }),
      setValidationError: (validationError) => set({ validationError }),
      markSaved: (serverId, savedSnapshot) =>
        set((s) => ({ serverId, savedSnapshot: savedSnapshot ?? snapshotOf(selectContent(s)) })),
    }),
    {
      partialize: (state): DocSnapshot => ({
        name: state.name,
        description: state.description,
        roles: state.roles,
        streams: state.streams,
        tree: state.tree,
        // groups is a document field, exactly like tree — it belongs in the undo snapshot
        // (design §5.2). `scope` does NOT: it stays out entirely, same as selectedUid, so it
        // is not read here at all.
        groups: state.groups,
      }),
      equality: (a, b) => JSON.stringify(a) === JSON.stringify(b),
      limit: 100,
    },
  ),
)

/** The hook form of `activeList` for React render bodies. Selects `scope`/`tree`/`groups` as
 * three separate `useDocStore` slices — exactly the subscription shape Canvas.tsx/Inspector.tsx
 * already used before this helper existed — rather than one selector computing the ternary
 * inside `useDocStore`, so a render is triggered only when one of those three slices actually
 * changes, same as before; the derivation itself now happens in one place instead of three (soon
 * four). Returns `s.tree`/a group's `body` array by reference, never a freshly-allocated array,
 * so it does not perturb memoization downstream (e.g. Canvas's `useMemo` over diagnostics). */
export function useActiveTree(): BlockNode[] {
  const scope = useDocStore((s) => s.scope)
  const tree = useDocStore((s) => s.tree)
  const groups = useDocStore((s) => s.groups)
  return activeList({ scope, tree, groups })
}

const temporalStore = (
  useDocStore as unknown as { temporal: StoreApi<TemporalState<DocSnapshot>> }
).temporal

/** `scope` is view state and is not in the zundo snapshot (partialize above), so undo/redo can
 * revert an edit made in a scope OTHER than the one currently displayed. Rather than applying
 * that change invisibly, follow it (design §5.2): find which list actually changed — the main
 * tree, or one specific group's body — and switch scope there. A no-op undo/redo (empty
 * history) changes nothing, so nextScope stays undefined and scope is left alone. */
function followUndoScope(before: DocSnapshot, after: DocSnapshot): void {
  let nextScope: string | null | undefined
  if (before.tree !== after.tree) {
    nextScope = null
  } else {
    const names = new Set([...Object.keys(before.groups), ...Object.keys(after.groups)])
    for (const name of names) {
      if (before.groups[name] !== after.groups[name]) {
        nextScope = name in after.groups ? name : null
        break
      }
    }
  }
  if (nextScope !== undefined && nextScope !== useDocStore.getState().scope) {
    useDocStore.setState({ scope: nextScope })
  }
}

export function undo(): void {
  const before = useDocStore.getState()
  temporalStore.getState().undo()
  followUndoScope(before, useDocStore.getState())
}

export function redo(): void {
  const before = useDocStore.getState()
  temporalStore.getState().redo()
  followUndoScope(before, useDocStore.getState())
}

export const pauseHistory = (): void => temporalStore.getState().pause()
export const resumeHistory = (): void => temporalStore.getState().resume()

export function useTemporal<T>(selector: (s: TemporalState<DocSnapshot>) => T): T {
  return useStore(temporalStore, selector)
}

export function loadDoc(content: DocContent, serverId: string | null): void {
  // Unlike persistence/defaults/metadata (opaque carry-through, legitimately `undefined`),
  // `groups` is a required field on the live state (like tree) — normalize it up front so
  // `savedSnapshot` below is computed from the SAME value that lands in state, not from
  // whatever `content.groups` happened to be before defaulting.
  const normalized: DocContent = { ...content, groups: content.groups ?? {} }
  useDocStore.setState({
    ...normalized,
    // Explicit, not just `...normalized`: zustand's setState (without `replace`) shallow-merges
    // into the CURRENT state, and `content` simply omits these keys when the incoming doc
    // has none — Object.assign then leaves whatever the previously-open document left behind
    // untouched. Writing `undefined` here is an own-property assignment, so it actually
    // clears them (2026-07-14 review, I1 — cross-document contamination via Task 8's carry-
    // through: doc B must never inherit doc A's workflow.defaults/persistence).
    persistence: content.persistence,
    defaults: content.defaults,
    metadata: content.metadata,
    serverId,
    savedSnapshot: snapshotOf(normalized),
    selectedUid: null,
    scope: null,
    focusedRole: null,
    scrollToUid: null,
    collapsed: {},
    diagnostics: [],
    validating: false,
    validationError: null,
  })
  temporalStore.getState().clear()
}

export function newDoc(): void {
  loadDoc(emptyContent(), null)
}
