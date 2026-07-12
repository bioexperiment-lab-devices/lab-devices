/** Single document store for the builder. The temporal (zundo) wrapper snapshots ONLY
 * the document fields, so undo/redo never touches selection, diagnostics, or save
 * bookkeeping. Dirty state is derived by comparing against the last saved snapshot. */
import { create } from 'zustand'
import { useStore, type StoreApi } from 'zustand'
import { temporal, type TemporalState } from 'zundo'
import type { ExperimentDocJson } from '../types/doc'
import type { MappedDiagnostic } from '../builder/paths'
import { treeToDoc, type DocContent } from '../builder/convert'
import {
  containsUid,
  duplicateNode,
  findNode,
  insertNode,
  moveNode,
  removeNode,
  updateNode,
  type BlockNode,
  type SlotRef,
} from '../builder/tree'
import {
  countRoleRefs,
  countStreamRefs,
  renameRoleRefs,
  renameStreamRefs,
} from '../builder/refs'

export const ROLE_NAME_RE = /^[a-z][a-z0-9_]*$/
export const STREAM_NAME_RE = /^[A-Za-z_][A-Za-z0-9_]*$/

export interface DocSnapshot {
  name: string
  description: string | null
  roles: Record<string, { type: string }>
  streams: Record<string, { units: string | null }>
  tree: BlockNode[]
}

export interface EditorState extends DocSnapshot {
  serverId: string | null
  savedSnapshot: string
  selectedUid: string | null
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
  select: (uid: string | null) => void
  toggleCollapsed: (uid: string) => void
  setDiagnostics: (diags: MappedDiagnostic[]) => void
  setValidating: (v: boolean) => void
  setValidationError: (e: string | null) => void
  markSaved: (serverId: string) => void
}

export const selectContent = (s: DocSnapshot): DocContent => ({
  name: s.name,
  description: s.description,
  roles: s.roles,
  streams: s.streams,
  tree: s.tree,
})

export const snapshotOf = (content: DocContent): string =>
  JSON.stringify({
    name: content.name,
    description: content.description,
    roles: content.roles,
    streams: content.streams,
    tree: content.tree,
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
})

const renameKey = <V>(rec: Record<string, V>, from: string, to: string): Record<string, V> =>
  Object.fromEntries(Object.entries(rec).map(([k, v]) => [k === from ? to : k, v]))

const removeKey = <V>(rec: Record<string, V>, key: string): Record<string, V> =>
  Object.fromEntries(Object.entries(rec).filter(([k]) => k !== key))

export const useDocStore = create<EditorState>()(
  temporal(
    (set, get) => ({
      ...emptyContent(),
      serverId: null,
      savedSnapshot: snapshotOf(emptyContent()),
      selectedUid: null,
      collapsed: {},
      diagnostics: [],
      validating: false,
      validationError: null,

      setName: (name) => set({ name }),
      setDescription: (description) => set({ description }),

      insertBlock: (node, at) =>
        set((s) => ({ tree: insertNode(s.tree, node, at), selectedUid: node.uid })),

      moveBlock: (uid, to) => set((s) => ({ tree: moveNode(s.tree, uid, to) })),

      removeBlock: (uid) =>
        set((s) => {
          const [tree] = removeNode(s.tree, uid)
          const removed = findNode(s.tree, uid)
          const selectionGone =
            s.selectedUid !== null && removed !== null && containsUid(removed, s.selectedUid)
          return { tree, selectedUid: selectionGone ? null : s.selectedUid }
        }),

      duplicateBlock: (uid) =>
        set((s) => {
          const [tree, cloneUid] = duplicateNode(s.tree, uid)
          return { tree, selectedUid: cloneUid ?? s.selectedUid }
        }),

      patchBlock: (uid, patch) => set((s) => ({ tree: updateNode(s.tree, uid, patch) })),

      addRole: (name, type) => {
        if (!ROLE_NAME_RE.test(name)) return `role name must match [a-z][a-z0-9_]*`
        if (name in get().roles) return `role '${name}' already exists`
        set((s) => ({ roles: { ...s.roles, [name]: { type } } }))
        return null
      },

      renameRole: (from, to) => {
        if (from === to) return null
        if (!ROLE_NAME_RE.test(to)) return `role name must match [a-z][a-z0-9_]*`
        if (to in get().roles) return `role '${to}' already exists`
        set((s) => ({
          roles: renameKey(s.roles, from, to),
          tree: renameRoleRefs(s.tree, from, to),
        }))
        return null
      },

      removeRole: (name) => {
        const refs = countRoleRefs(get().tree, name)
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

      renameStream: (from, to) => {
        if (from === to) return null
        if (!STREAM_NAME_RE.test(to)) return `stream name must be an identifier`
        if (to in get().streams) return `stream '${to}' already exists`
        set((s) => ({
          streams: renameKey(s.streams, from, to),
          tree: renameStreamRefs(s.tree, from, to),
        }))
        return null
      },

      removeStream: (name) => {
        const refs = countStreamRefs(get().tree, name)
        if (refs > 0) return `stream '${name}' is used by ${refs} block${refs === 1 ? '' : 's'}`
        set((s) => ({ streams: removeKey(s.streams, name) }))
        return null
      },

      setStreamUnits: (name, units) =>
        set((s) => ({
          streams: name in s.streams ? { ...s.streams, [name]: { units } } : s.streams,
        })),

      select: (uid) => set({ selectedUid: uid }),
      toggleCollapsed: (uid) =>
        set((s) => ({ collapsed: { ...s.collapsed, [uid]: !s.collapsed[uid] } })),
      setDiagnostics: (diagnostics) => set({ diagnostics }),
      setValidating: (validating) => set({ validating }),
      setValidationError: (validationError) => set({ validationError }),
      markSaved: (serverId) =>
        set((s) => ({ serverId, savedSnapshot: snapshotOf(selectContent(s)) })),
    }),
    {
      partialize: (state): DocSnapshot => ({
        name: state.name,
        description: state.description,
        roles: state.roles,
        streams: state.streams,
        tree: state.tree,
      }),
      equality: (a, b) => JSON.stringify(a) === JSON.stringify(b),
      limit: 100,
    },
  ),
)

const temporalStore = (
  useDocStore as unknown as { temporal: StoreApi<TemporalState<DocSnapshot>> }
).temporal

export const undo = (): void => temporalStore.getState().undo()
export const redo = (): void => temporalStore.getState().redo()

export function useTemporal<T>(selector: (s: TemporalState<DocSnapshot>) => T): T {
  return useStore(temporalStore, selector)
}

export function loadDoc(content: DocContent, serverId: string | null): void {
  useDocStore.setState({
    ...content,
    serverId,
    savedSnapshot: snapshotOf(content),
    selectedUid: null,
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
