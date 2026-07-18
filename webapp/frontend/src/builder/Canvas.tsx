import { Fragment, createContext, useContext, useEffect, useMemo, useRef, useState } from 'react'
import { useDraggable } from '@dnd-kit/core'
import { ChevronDown, ChevronRight, Copy, Plus, X } from 'lucide-react'
import { useActiveTree, useDocStore } from '../stores/docStore'
import { useRoleColorStore } from '../stores/roleColorStore'
import { diagnosticsByUid, type MappedDiagnostic } from './paths'
import { blockDraggableId, type DragPayload } from './dnd'
import { DropSlot } from './DropSlot'
import { assignRoleColors } from './roleColors'
import { blockSummary, blockSummaryParts, faultMarker } from './summary'
import { newPaletteNode, type BlockNode, type BranchNode, type ParallelNode } from './tree'
import { controlClass, inlineButtonClass } from '../ui/controls'
import { IconButton } from '../ui/IconButton'
import { KindIcon } from '../ui/icons'
import { ScrollFades, useScrollEdges } from '../ui/ScrollX'
import { useDismissable } from '../ui/useDismissable'
import {
  cardBorderClass,
  headerFillClass,
  interiorFillClass,
  isFlowKind,
} from './constructTint'

const DiagContext = createContext<Map<string, MappedDiagnostic[]>>(new Map())

/** Nesting depth of the list currently being rendered. 0 is the canvas backdrop; the
 * outermost container's interior is 1. Only ContainerBody provides it —
 * BlockList is depth-transparent, so a container's own card sits at its PARENT's depth
 * and only its interior descends. */
const DepthContext = createContext(0)

export function Canvas() {
  // The canvas renders whichever list `scope` names (design §5.2): the main workflow tree
  // when null, else the active group's body. docStore's own `activeList`/`setActiveList`
  // (docStore.ts) resolve the same scope for every block op, so reads here always agree
  // with what insertBlock/moveBlock/etc. would write to.
  const activeTree = useActiveTree()
  const scope = useDocStore((s) => s.scope)
  const select = useDocStore((s) => s.select)
  const diagnostics = useDocStore((s) => s.diagnostics)
  const byUid = useMemo(() => diagnosticsByUid(diagnostics), [diagnostics])

  // `scrollToUid` (docStore.ts) is set by a Problems row click on a block diagnostic
  // (ProblemsPanel.tsx). Reading it here and scrolling in a reactive effect — the same shape
  // as RolesSection's `focusedRole` effect — rather than querying the DOM synchronously inside
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
      <div className="relative min-w-0 flex-1 overflow-hidden rounded-lg border border-slate-200">
        <div
          ref={scrollRef}
          className={
            // Editing a group body was pixel-identical to editing the main workflow — the
            // only cue was the value in a dropdown. The hatch says "this is a subroutine"
            // without stealing any content space.
            'h-full overflow-auto p-4 ' +
            (scope === null ? 'bg-slate-100' : 'bg-slate-100 bg-hatch')
          }
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
  const cancelAdding = () => {
    setAdding(false)
    setName('')
    setError(null)
  }
  // The "+ New group…" trigger unmounts entirely once `adding` is true (the ternary below
  // swaps it out for this input row), so it can never be clicked while the ref is live —
  // unlike StreamIntoPicker's <select>, there is no coexisting trigger that also needs to
  // count as "inside". Wrapping just the input/Add/cancel row is the correct boundary here.
  const addingRef = useDismissable(adding, cancelAdding)

  return (
    <div
      onClick={(e) => e.stopPropagation()}
      className={
        // Text must not sit directly on the canvas hatch (Canvas's backdrop, above): this
        // strip goes solid white whenever a group scope is active so "Editing: [ ... ]"
        // stays readable over it.
        'mb-2 flex flex-wrap items-center gap-2 rounded px-2 py-1 text-xs ' +
        (scope === null ? '' : 'bg-white shadow-sm')
      }
    >
      <span className="font-semibold text-caption">Editing:</span>
      <select
        value={scope ?? ''}
        onChange={(e) => setScope(e.target.value === '' ? null : e.target.value)}
        className={controlClass({ width: 'w-auto' })}
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
        <div ref={addingRef} className="flex items-center gap-1">
          <input
            autoFocus
            value={name}
            placeholder="group name"
            onChange={(e) => setName(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') create()
              if (e.key === 'Escape') cancelAdding()
            }}
            className={controlClass({ mono: true, width: 'w-28' })}
          />
          <button onClick={create} className={inlineButtonClass()}>
            Add
          </button>
          <button onClick={cancelAdding} className={inlineButtonClass({ subtle: true })}>
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

/** The swatch class for a block's device role, or null when the block has no role or the
 * user cleared that role's colour. Resolved from the doc's roles rather than stored on the
 * block, so every command and measure of a role shares one colour by construction. */
function useRoleColor(node: BlockNode): string | null {
  const roles = useDocStore((s) => s.roles)
  const overrides = useRoleColorStore((s) => s.overrides)
  const assigned = useMemo(() => assignRoleColors(roles, overrides), [roles, overrides])
  if (node.kind !== 'command' && node.kind !== 'measure') return null
  return assigned[node.device] ?? null
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
  const isContainer = isFlowKind(node.kind)
  const swatch = useRoleColor(node)
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
        //
        // The border comes from cardBorderClass, which SELECTS exactly one class: containers
        // wear their construct tint, leaves stay slate-300, and selection replaces both. The
        // selection ring is `ring-2` rather than W13's `ring-1` because a canvas of tinted
        // borders makes a 1px ring too easy to lose — the ring, not the border, is now the
        // load-bearing selection cue.
        'min-w-0 rounded border bg-white text-sm shadow-sm ' +
        cardBorderClass({ kind: node.kind, selected }) + ' ' +
        // A group_ref is a leaf that expands to an entire subtree rendered nowhere on
        // screen (design §3.5) — the edge hatch is the one sanctioned cue for that, paired
        // with pl-1.5 so the header content clears the hatched strip instead of sitting on it.
        (node.kind === 'group_ref' ? 'edge-hatch pl-1.5 ' : '') +
        (selected ? 'ring-2 ring-blue-400 ' : '') +
        (isDragging ? 'opacity-40' : '')
      }
    >
      <div
        {...listeners}
        {...attributes}
        className={
          'flex min-w-0 cursor-grab items-center gap-1 rounded-t px-2 py-1 ' +
          headerFillClass(node.kind)
        }
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
        {swatch && (
          <span
            aria-hidden
            className={`h-2.5 w-2.5 shrink-0 rounded-sm ${swatch}`}
          />
        )}
        <KindIcon kind={node.kind} />
        {/* max-w-80 (20rem): under width:max-content a nowrap truncate span's intrinsic
            contribution is its full untruncated text (min-w-0 on this row only lets items
            shrink — it can't cap that contribution), so an explicit max-width is what makes
            `truncate` actually ellipsize instead of widening every card up the tree to the
            canvas's single scroller. 20rem covers a `device · verb (k=v, k=v)` summary
            (routinely 35-50 chars) in full at this text-sm size while still capping a
            pathologically long device/verb/param-value string. */}
        <span title={blockSummary(node)} className="max-w-80 truncate">
          {blockSummaryParts(node).map((s, i) => (
            <span
              key={i}
              className={
                s.role === 'subject'
                  ? 'font-medium text-slate-900'
                  : s.role === 'verb'
                    ? 'text-slate-700'
                    : 'text-caption'
              }
            >
              {s.text}
            </span>
          ))}
        </span>
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

/** A container's interior. Every construct now gets the same treatment — a depth-keyed
 * neutral fill on the region that used to be pure padding — so containment reads as filled
 * AREAS rather than as strokes you have to count.
 *
 * The `ml-2 border-l-2 border-slate-200` rule that loop and for_each carried before this
 * increment is gone. It was a second vertical line drawn 8px inside the card border that was
 * already there: a stroke without a fact. Both constructs are now told apart by their border
 * and header hue instead (constructTint.ts), which is why they no longer need to be — and no
 * longer are — byte-identical. */
function ContainerBody({ node }: { node: BlockNode }) {
  const depth = useContext(DepthContext) + 1
  const fill = interiorFillClass(depth)
  const body = (() => {
    switch (node.kind) {
      case 'serial':
        return <BlockList parentUid={node.uid} slot="children" items={node.children} />
      case 'parallel':
        return <ParallelLanes node={node} />
      case 'loop':
        return <BlockList parentUid={node.uid} slot="body" items={node.body} />
      case 'for_each':
        return <BlockList parentUid={node.uid} slot="body" items={node.body} />
      case 'branch':
        return <BranchLanes node={node} />
      default:
        return null
    }
  })()
  if (body === null) return null
  return (
    <DepthContext.Provider value={depth}>
      <div className={`rounded-b px-2 pb-2 ${fill}`}>{body}</div>
    </DepthContext.Provider>
  )
}

function ParallelLanes({ node }: { node: ParallelNode }) {
  const insertBlock = useDocStore((s) => s.insertBlock)
  return (
    // No nested overflow here: the Canvas is the only horizontal scroller, so a wide lane
    // widens the canvas's content and scrolls THERE instead of being clipped inside this box.
    //
    // Lanes are `flex-initial` for the same reason the branch arms are (see BranchLanes): a
    // grow factor makes an EMPTY lane claim an equal share of whatever space is left, which is
    // finding #5b's "free space on one side, hidden content on the other" in a different
    // container. Sizing to content also keeps the "+ lane" button next to the last lane rather
    // than shoved to the far edge by the lanes' growth.
    <div className="flex items-stretch">
      <DropSlot
        at={{ parentUid: node.uid, slot: 'children', index: 0 }}
        horizontal
        hint={node.children.length === 0}
      />
      {node.children.map((lane, i) => (
        <Fragment key={lane.uid}>
          <Lane lane={lane} index={i} />
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
        // `stretch` instead of the 24px token: this button runs the full height of the lanes
        // beside it, which is why it is the one sanctioned height exception (controls.ts).
        // `m-1` is the button's existing inset from the lane row, and it is a margin — not a
        // width or a colour — so nothing in the helper competes with it in the cascade.
        className={inlineButtonClass({ subtle: true, stretch: true }) + ' m-1'}
      >
        <Plus size={12} aria-hidden className="mr-0.5" />lane
      </button>
    </div>
  )
}

/** One lane of a Parallel. A `serial` child IS the lane (spec §3.4): its children render
 * directly in the lane box and this header row is the serial's handle — click selects it
 * (the Inspector edits its label/on_error there), drag moves/reorders it, and its label,
 * fault markers and diagnostics show here, since there is no card to carry them. Emptying
 * a lane therefore never destroys it; the ✕ (empty lanes only) and select+Delete stay the
 * explicit removal paths. Any other kind is a legacy/imported bare-block lane and keeps
 * the card rendering — both committed fixtures contain such lanes (spec §5). */
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
  if (lane.kind !== 'serial') {
    return (
      <div className="min-w-48 flex-initial rounded border border-dashed border-slate-200 p-1">
        <div className="flex h-6 items-center px-1 text-[10px] uppercase text-caption">
          lane {index + 1}
        </div>
        <BlockView node={lane} />
      </div>
    )
  }
  const marker = faultMarker(lane).trim()
  return (
    <div
      id={`block-${lane.uid}`}
      ref={setNodeRef}
      onClick={(e) => {
        e.stopPropagation()
        select(lane.uid)
      }}
      className={
        'min-w-48 flex-initial rounded border border-dashed p-1 ' +
        (selected ? 'border-blue-500 ring-1 ring-blue-300 ' : 'border-slate-200 ') +
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
          // max-w-40 for the same intrinsic-width reason as BlockView's label span: under the
          // canvas's width:max-content a nowrap span contributes its FULL untruncated width.
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
          {lane.children.length === 0 && (
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
      <BlockList parentUid={lane.uid} slot="children" items={lane.children} />
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
    // flex-initial (`flex: 0 1 auto`), per design §4.2 #5b — NOT flex-1 and NOT flex-auto:
    //   • flex-1 (`1 1 0%`) is a hard equal split that ignores content — the original defect,
    //     an empty ELSE arm claiming half the card while THEN's content was cramped.
    //   • flex-auto (`1 1 auto`) still carries flex-grow:1 on BOTH arms, so leftover space is
    //     *still* split 50/50 — only the starting point differs. Measured on a doc with one
    //     card in THEN and `else: null`, canvas 1294px (1920px viewport): flex-auto gave
    //     THEN 808.7px / ELSE 427.3px. The ELSE arm holds nothing but the "+ add else" button
    //     (~80px of content) and took an equal 347.5px share of the slack — finding #5b,
    //     reproduced. The committed fixtures cannot catch it: morbidostat and torture both
    //     overflow, so slack is zero and grow never runs.
    //   • flex-initial has no grow at all: each arm sits at its content width (floored by
    //     min-w-48), shrinking only when the row is over-full. Leftover space stays leftover —
    //     it belongs to the card, not to whichever arm happens to be empty. Same doc, same
    //     canvas: THEN 461.2px (its content) / ELSE 192px (the min-w-48 floor).
    <div className="flex gap-2">
      <div className="min-w-48 flex-initial rounded border border-violet-200 px-1 pb-1">
        <p className="flex h-6 items-center text-[10px] uppercase text-caption">then</p>
        <BlockList parentUid={node.uid} slot="then" items={node.then} />
      </div>
      <div className="min-w-48 flex-initial rounded border border-violet-200 px-1 pb-1">
        {node.else === null ? (
          <>
            <p className="flex h-6 items-center text-[10px] uppercase text-caption">else</p>
            <div className="flex flex-col">
              {/* Mirrors the leading `DropSlot` of the THEN arm's BlockList — a vertical
                  DropSlot renders `my-0.5 h-2` (DropSlot.tsx), and this arm has no BlockList
                  to render one. Without it the two arms' first rows sit 12px out of line.
                  If DropSlot's vertical size changes, change this to match. */}
              <div className="my-0.5 h-2" />
              <button
                onClick={(e) => {
                  e.stopPropagation()
                  patchBlock(node.uid, { else: [] })
                }}
                // Same control as the Inspector's "+ add else lane" (Inspector.tsx), and
                // routed through the same helper so a change to the subtle variant reaches
                // both. h-6 matches the old py-1.5 + text-xs box to the pixel.
                className={inlineButtonClass({ subtle: true, width: 'w-full' })}
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
