import { Fragment, createContext, useContext, useEffect, useMemo, useRef, useState } from 'react'
import { useDraggable } from '@dnd-kit/core'
import { ChevronDown, ChevronRight, Copy, Plus, X } from 'lucide-react'
import { useActiveTree, useDocStore } from '../stores/docStore'
import { diagnosticsByUid, type MappedDiagnostic } from './paths'
import { blockDraggableId, type DragPayload } from './dnd'
import { DropSlot } from './DropSlot'
import { blockSummary } from './summary'
import { newPaletteNode, type BlockNode, type BranchNode, type ParallelNode } from './tree'
import { controlClass, inlineButtonClass } from '../ui/controls'
import { IconButton } from '../ui/IconButton'
import { KindIcon } from '../ui/icons'
import { ScrollFades, useScrollEdges } from '../ui/ScrollX'

const DiagContext = createContext<Map<string, MappedDiagnostic[]>>(new Map())

export function Canvas() {
  // The canvas renders whichever list `scope` names (design §5.2): the main workflow tree
  // when null, else the active group's body. docStore's own `activeList`/`setActiveList`
  // (docStore.ts) resolve the same scope for every block op, so reads here always agree
  // with what insertBlock/moveBlock/etc. would write to.
  const activeTree = useActiveTree()
  const select = useDocStore((s) => s.select)
  const diagnostics = useDocStore((s) => s.diagnostics)
  const byUid = useMemo(() => diagnosticsByUid(diagnostics), [diagnostics])

  // `scrollToUid` (docStore.ts) is set by a Problems row click on a block diagnostic
  // (ProblemsPanel.tsx). Reading it here and scrolling in a reactive effect — the same shape
  // as RolesPanel's `focusedRole` effect — rather than querying the DOM synchronously inside
  // that click handler is what makes this immune to the cross-scope race (2026-07-16 review,
  // Finding 2): when the click also calls `setScope`, `activeTree` above is what re-renders
  // this component for the new scope, and this effect only runs after that render commits, so
  // `block-${scrollToUid}` is guaranteed to already be in the DOM by the time it queries.
  const scrollToUid = useDocStore((s) => s.scrollToUid)
  useEffect(() => {
    if (!scrollToUid) return
    document
      .getElementById(`block-${scrollToUid}`)
      ?.scrollIntoView({ behavior: 'smooth', block: 'center' })
  }, [scrollToUid])

  // The canvas is the app's SINGLE horizontal scroller (finding #1, finding #5b). The fades
  // are absolute overlays rendered as a sibling of the scroller inside this `relative` wrapper
  // — not children of it: `useScrollEdges` re-observes the scroller's children, so a fade
  // living among them would risk a resize feedback loop, and it would scroll away with the
  // content instead of staying pinned to the viewport edge.
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
      <span className="font-semibold text-caption">Editing:</span>
      <select
        value={scope ?? ''}
        onChange={(e) => setScope(e.target.value === '' ? null : e.target.value)}
        className={controlClass() + ' w-auto'}
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
            className={controlClass({ mono: true }) + ' w-28'}
          />
          <button onClick={create} className={inlineButtonClass()}>
            Add
          </button>
          <button
            onClick={() => {
              setAdding(false)
              setName('')
              setError(null)
            }}
            className={inlineButtonClass({ subtle: true })}
          >
            cancel
          </button>
        </div>
      ) : (
        <button
          onClick={() => setAdding(true)}
          className={inlineButtonClass({ subtle: true })}
        >
          <Plus size={12} aria-hidden className="mr-0.5 inline" />New group…
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
        // min-w-0: a card that sits in a flex lane/branch-arm must be able to shrink to its
        // container instead of forcing it wide (flex min-width:auto is the classic culprit
        // behind a card painting past its box — audit F11). The lane/arm containers no longer
        // clip (the Canvas is the single scroller), so this is what keeps a card honest.
        'min-w-0 rounded border bg-white text-sm shadow-sm ' +
        (selected ? 'border-blue-500 ring-1 ring-blue-300 ' : 'border-slate-300 ') +
        (isDragging ? 'opacity-40' : '')
      }
    >
      <div
        {...listeners}
        {...attributes}
        className="flex min-w-0 cursor-grab items-center gap-1 px-2 py-1"
      >
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
        <KindIcon kind={node.kind} />
        {/* max-w-80 (20rem): under width:max-content a nowrap truncate span's intrinsic
            contribution is its full untruncated text (min-w-0 on this row only lets items
            shrink — it can't cap that contribution), so an explicit max-width is what makes
            `truncate` actually ellipsize instead of widening every card up the tree to the
            canvas's single scroller. 20rem covers a `device · verb (k=v, k=v)` summary
            (routinely 35-50 chars) in full at this text-sm size while still capping a
            pathologically long device/verb/param-value string. */}
        <span title={blockSummary(node)} className="max-w-80 truncate">{blockSummary(node)}</span>
        {node.label && (
          // max-w-40 (10rem): the label is a short user-typed nickname rendered at text-xs —
          // 10rem comfortably fits an ordinary one or two-word label while still capping an
          // arbitrarily long pasted one, so it can't be the thing that drives canvas width.
          <span title={node.label} className="max-w-40 truncate text-xs italic text-caption">“{node.label}”</span>
        )}
        <span className="ml-auto flex items-center gap-1">
          {diags.length > 0 && (
            <span
              title={diags.map((d) => d.message).join('\n')}
              className="rounded-full bg-red-600 px-1.5 text-[10px] font-bold text-white"
            >
              {diags.length}
            </span>
          )}
          <IconButton
            icon={Copy}
            label="Duplicate"
            onClick={(e) => {
              e.stopPropagation()
              duplicateBlock(node.uid)
            }}
          />
          <IconButton
            icon={X}
            label="Delete"
            destructive
            onClick={(e) => {
              e.stopPropagation()
              removeBlock(node.uid)
            }}
          />
        </span>
      </div>
      {!collapsed && isContainer && <ContainerBody node={node} />}
      {collapsed && isContainer && (
        <p className="px-2 pb-1 text-xs text-hint">…collapsed…</p>
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
    // No nested overflow here: the Canvas is the only horizontal scroller, so a wide lane
    // widens the canvas's content and scrolls THERE instead of being clipped inside this box.
    <div className="flex items-stretch">
      <DropSlot
        at={{ parentUid: node.uid, slot: 'children', index: 0 }}
        horizontal
        hint={node.children.length === 0}
      />
      {node.children.map((lane, i) => (
        <Fragment key={lane.uid}>
          <div className="min-w-48 flex-auto rounded border border-dashed border-slate-200 p-1">
            <div className="flex h-6 items-center justify-between px-1 text-[10px] uppercase text-caption">
              <span>lane {i + 1}</span>
              {isEmptyLane(lane) && (
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
        className="m-1 flex shrink-0 items-center self-stretch rounded border border-dashed border-slate-300 bg-white px-2 text-xs text-caption hover:border-slate-400 hover:text-slate-600"
      >
        <Plus size={12} aria-hidden className="mr-0.5" />lane
      </button>
    </div>
  )
}

function BranchLanes({ node }: { node: BranchNode }) {
  const patchBlock = useDocStore((s) => s.patchBlock)
  return (
    // W10 put `overflow-x-auto` here for audit F11 (a too-wide arm painting past the card edge
    // over a sibling's action icons). That clipping is gone: the Canvas is now the single
    // horizontal scroller, so a wide arm widens the canvas content and scrolls there — reachable
    // rather than hidden. BlockView's `min-w-0` (F11's other half) stays and still does its job.
    //
    // flex-auto, not flex-1: `flex: 1 1 0%` is a hard equal split that ignores content, which is
    // why an empty ELSE arm claimed half the card while THEN's content was cramped (finding #5b).
    // `flex: 1 1 auto` bases each arm on its own content and shares only the leftover space, so a
    // light arm settles toward its min-w-48 floor and a heavy arm takes the slack.
    <div className="flex gap-2 px-2 pb-2">
      <div className="min-w-48 flex-auto">
        <p className="flex h-6 items-center text-[10px] uppercase text-caption">then</p>
        <BlockList parentUid={node.uid} slot="then" items={node.then} />
      </div>
      <div className="min-w-48 flex-auto">
        {node.else === null ? (
          <>
            <p className="flex h-6 items-center text-[10px] uppercase text-caption">else</p>
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
        ) : (
          <>
            <p className="flex h-6 items-center justify-between text-[10px] uppercase text-caption">
              <span>else</span>
              {node.else.length === 0 && (
                <IconButton
                  icon={X}
                  label="Remove else"
                  destructive
                  onClick={(e) => {
                    e.stopPropagation()
                    patchBlock(node.uid, { else: null })
                  }}
                />
              )}
            </p>
            <BlockList parentUid={node.uid} slot="else" items={node.else} />
          </>
        )}
      </div>
    </div>
  )
}
