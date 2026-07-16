import { Fragment, createContext, useContext, useMemo, useState } from 'react'
import { useDraggable } from '@dnd-kit/core'
import { useDocStore } from '../stores/docStore'
import { diagnosticsByUid, type MappedDiagnostic } from './paths'
import { blockDraggableId, type DragPayload } from './dnd'
import { DropSlot } from './DropSlot'
import { blockSummary } from './summary'
import { newPaletteNode, type BlockNode, type BranchNode, type ParallelNode } from './tree'

const DiagContext = createContext<Map<string, MappedDiagnostic[]>>(new Map())

export function Canvas() {
  const scope = useDocStore((s) => s.scope)
  const tree = useDocStore((s) => s.tree)
  const groups = useDocStore((s) => s.groups)
  // The canvas renders whichever list `scope` names (design §5.2): the main workflow tree
  // when null, else the active group's body. docStore's own `activeList`/`setActiveList`
  // (docStore.ts) resolve the same scope for every block op, so reads here always agree
  // with what insertBlock/moveBlock/etc. would write to.
  const activeTree = scope === null ? tree : (groups[scope]?.body ?? [])
  const select = useDocStore((s) => s.select)
  const diagnostics = useDocStore((s) => s.diagnostics)
  const byUid = useMemo(() => diagnosticsByUid(diagnostics), [diagnostics])
  return (
    <DiagContext.Provider value={byUid}>
      <div
        className="min-w-0 flex-1 overflow-auto bg-slate-100 p-4"
        onClick={() => select(null)}
      >
        <ScopeSwitcher />
        {activeTree.length === 0 && (
          <p className="mb-2 rounded border border-dashed border-slate-300 p-8 text-center text-sm text-slate-400">
            Drag blocks from the palette to start building.
          </p>
        )}
        <BlockList parentUid={null} slot="blocks" items={activeTree} />
      </div>
    </DiagContext.Provider>
  )
}

/** "Editing: [ Main workflow ▾ ]" (design §5.2) — the Palette/Inspector/drag-drop are
 * unchanged by which scope is active; only this selector and the two reads above (Canvas's
 * `activeTree`, Inspector's mirror of it) know that "the current tree" is now a choice
 * rather than a fixed field. "+ New group…" follows the AddRoleForm precedent
 * (Palette.tsx's inline-error-under-the-control pattern) rather than a native prompt(). */
function ScopeSwitcher() {
  const scope = useDocStore((s) => s.scope)
  const groups = useDocStore((s) => s.groups)
  const setScope = useDocStore((s) => s.setScope)
  const addGroup = useDocStore((s) => s.addGroup)
  const [adding, setAdding] = useState(false)
  const [name, setName] = useState('')
  const [error, setError] = useState<string | null>(null)
  const groupNames = Object.keys(groups)

  const create = () => {
    const err = addGroup(name)
    setError(err)
    if (!err) {
      setScope(name)
      setAdding(false)
      setName('')
    }
  }

  return (
    <div
      onClick={(e) => e.stopPropagation()}
      className="mb-2 flex flex-wrap items-center gap-2 text-xs"
    >
      <span className="font-semibold text-slate-500">Editing:</span>
      <select
        value={scope ?? ''}
        onChange={(e) => setScope(e.target.value === '' ? null : e.target.value)}
        className="rounded border border-slate-300 bg-white px-1.5 py-0.5"
      >
        <option value="">Main workflow</option>
        {groupNames.map((g) => (
          <option key={g} value={g}>
            {g}
            {groups[g].params.length > 0 ? `(${groups[g].params.join(', ')})` : ''}
          </option>
        ))}
      </select>
      {adding ? (
        <div className="flex items-center gap-1">
          <input
            autoFocus
            value={name}
            placeholder="group name"
            onChange={(e) => setName(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') create()
              if (e.key === 'Escape') {
                setAdding(false)
                setName('')
                setError(null)
              }
            }}
            className="w-28 rounded border border-slate-300 px-1 py-0.5 font-mono text-xs"
          />
          <button onClick={create} className="rounded bg-slate-200 px-2 py-0.5 hover:bg-slate-300">
            Add
          </button>
          <button
            onClick={() => {
              setAdding(false)
              setName('')
              setError(null)
            }}
            className="text-slate-400 hover:text-slate-600"
          >
            cancel
          </button>
        </div>
      ) : (
        <button
          onClick={() => setAdding(true)}
          className="rounded border border-dashed border-slate-300 px-2 py-0.5 text-slate-500 hover:text-slate-700"
        >
          + New group…
        </button>
      )}
      {error && <span className="text-red-600">{error}</span>}
    </div>
  )
}

function BlockList(props: { parentUid: string | null; slot: string; items: BlockNode[] }) {
  const { parentUid, slot, items } = props
  return (
    <div className="flex flex-col">
      <DropSlot at={{ parentUid, slot, index: 0 }} horizontal={false} hint={items.length === 0} />
      {items.map((node, i) => (
        <Fragment key={node.uid}>
          <BlockView node={node} />
          <DropSlot at={{ parentUid, slot, index: i + 1 }} horizontal={false} hint={false} />
        </Fragment>
      ))}
    </div>
  )
}

function BlockView({ node }: { node: BlockNode }) {
  const select = useDocStore((s) => s.select)
  const selected = useDocStore((s) => s.selectedUid === node.uid)
  const collapsed = useDocStore((s) => Boolean(s.collapsed[node.uid]))
  const toggleCollapsed = useDocStore((s) => s.toggleCollapsed)
  const duplicateBlock = useDocStore((s) => s.duplicateBlock)
  const removeBlock = useDocStore((s) => s.removeBlock)
  const diags = useContext(DiagContext).get(node.uid) ?? []
  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({
    id: blockDraggableId(node.uid),
    data: { source: 'canvas', uid: node.uid } satisfies DragPayload,
  })
  const isContainer =
    node.kind === 'serial' || node.kind === 'parallel' || node.kind === 'loop' || node.kind === 'branch' || node.kind === 'for_each'
  return (
    <div
      id={`block-${node.uid}`}
      ref={setNodeRef}
      onClick={(e) => {
        e.stopPropagation()
        select(node.uid)
      }}
      className={
        'rounded border bg-white text-sm shadow-sm ' +
        (selected ? 'border-blue-500 ring-1 ring-blue-300 ' : 'border-slate-300 ') +
        (isDragging ? 'opacity-40' : '')
      }
    >
      <div {...listeners} {...attributes} className="flex cursor-grab items-center gap-1 px-2 py-1">
        {isContainer && (
          <button
            onClick={(e) => {
              e.stopPropagation()
              toggleCollapsed(node.uid)
            }}
            className="text-xs text-slate-400 hover:text-slate-700"
          >
            {collapsed ? '▸' : '▾'}
          </button>
        )}
        <span className="truncate">{blockSummary(node)}</span>
        {node.label && <span className="truncate text-xs italic text-slate-400">“{node.label}”</span>}
        <span className="ml-auto flex items-center gap-1">
          {diags.length > 0 && (
            <span
              title={diags.map((d) => d.message).join('\n')}
              className="rounded-full bg-red-500 px-1.5 text-[10px] font-bold text-white"
            >
              {diags.length}
            </span>
          )}
          <button
            title="Duplicate"
            onClick={(e) => {
              e.stopPropagation()
              duplicateBlock(node.uid)
            }}
            className="text-xs text-slate-300 hover:text-slate-600"
          >
            ⧉
          </button>
          <button
            title="Delete"
            onClick={(e) => {
              e.stopPropagation()
              removeBlock(node.uid)
            }}
            className="text-xs text-slate-300 hover:text-red-600"
          >
            ✕
          </button>
        </span>
      </div>
      {!collapsed && isContainer && <ContainerBody node={node} />}
      {collapsed && isContainer && (
        <p className="px-2 pb-1 text-xs text-slate-400">…collapsed…</p>
      )}
    </div>
  )
}

function ContainerBody({ node }: { node: BlockNode }) {
  switch (node.kind) {
    case 'serial':
      return (
        <div className="px-2 pb-2">
          <BlockList parentUid={node.uid} slot="children" items={node.children} />
        </div>
      )
    case 'parallel':
      return (
        <div className="px-2 pb-2">
          <ParallelLanes node={node} />
        </div>
      )
    case 'loop':
      return (
        <div className="ml-2 border-l-2 border-slate-200 px-2 pb-2">
          <BlockList parentUid={node.uid} slot="body" items={node.body} />
        </div>
      )
    case 'for_each':
      return (
        <div className="ml-2 border-l-2 border-slate-200 px-2 pb-2">
          <BlockList parentUid={node.uid} slot="body" items={node.body} />
        </div>
      )
    case 'branch':
      return <BranchLanes node={node} />
    default:
      return null
  }
}

function ParallelLanes({ node }: { node: ParallelNode }) {
  const removeBlock = useDocStore((s) => s.removeBlock)
  const insertBlock = useDocStore((s) => s.insertBlock)
  const isEmptyLane = (lane: BlockNode) => lane.kind === 'serial' && lane.children.length === 0
  return (
    <div className="flex items-stretch overflow-x-auto">
      <DropSlot
        at={{ parentUid: node.uid, slot: 'children', index: 0 }}
        horizontal
        hint={node.children.length === 0}
      />
      {node.children.map((lane, i) => (
        <Fragment key={lane.uid}>
          <div className="min-w-48 flex-1 rounded border border-dashed border-slate-200 p-1">
            <div className="flex items-center justify-between px-1 text-[10px] uppercase text-slate-400">
              <span>lane {i + 1}</span>
              {isEmptyLane(lane) && (
                <button
                  title="Remove lane"
                  onClick={(e) => {
                    e.stopPropagation()
                    removeBlock(lane.uid)
                  }}
                  className="hover:text-red-600"
                >
                  ✕
                </button>
              )}
            </div>
            <BlockView node={lane} />
          </div>
          <DropSlot at={{ parentUid: node.uid, slot: 'children', index: i + 1 }} horizontal hint={false} />
        </Fragment>
      ))}
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
        className="m-1 shrink-0 self-center rounded border border-dashed border-slate-300 px-2 py-1 text-xs text-slate-400 hover:text-slate-600"
      >
        + lane
      </button>
    </div>
  )
}

function BranchLanes({ node }: { node: BranchNode }) {
  const patchBlock = useDocStore((s) => s.patchBlock)
  return (
    <div className="flex gap-2 px-2 pb-2">
      <div className="min-w-48 flex-1">
        <p className="text-[10px] uppercase text-slate-400">then</p>
        <BlockList parentUid={node.uid} slot="then" items={node.then} />
      </div>
      <div className="min-w-48 flex-1">
        {node.else === null ? (
          <button
            onClick={(e) => {
              e.stopPropagation()
              patchBlock(node.uid, { else: [] })
            }}
            className="mt-4 rounded border border-dashed border-slate-300 px-2 py-1 text-xs text-slate-400 hover:text-slate-600"
          >
            + add else
          </button>
        ) : (
          <>
            <p className="flex items-center justify-between text-[10px] uppercase text-slate-400">
              <span>else</span>
              {node.else.length === 0 && (
                <button
                  title="Remove else"
                  onClick={(e) => {
                    e.stopPropagation()
                    patchBlock(node.uid, { else: null })
                  }}
                  className="hover:text-red-600"
                >
                  ✕
                </button>
              )}
            </p>
            <BlockList parentUid={node.uid} slot="else" items={node.else} />
          </>
        )}
      </div>
    </div>
  )
}
