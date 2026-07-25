import {
  Fragment,
  createContext,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react'
import { useDraggable } from '@dnd-kit/core'
import { ChevronDown, ChevronRight, Copy, Plus, X } from 'lucide-react'
import { useActiveTree, useDocStore } from '../stores/docStore'
import { useRoleColorStore } from '../stores/roleColorStore'
import { diagnosticsByUid, type MappedDiagnostic } from './paths'
import { blockDraggableId, type DragPayload } from './dnd'
import { DropSlot } from './DropSlot'
import { CHIP_GAP, LANE_DIVIDER_INSET, LANE_LABEL_H, LANE_PAD } from './laneLayout'
import { assignRoleColors } from './roleColors'
import {
  blockSummary,
  blockSummaryParts,
  faultMarker,
  splitSummary,
  type SummarySegment,
} from './summary'
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
          {/* `w-fit`, NOT `w-max` — the single change that lets a card wrap at all (design
              2026-07-25-adaptive-canvas-chips §3). `width: max-content` defines "available
              width" as whatever the content wants, so a flex row never runs out of room and
              `flex-wrap` can never fire: every card was single-line because it had no choice,
              and N cards in a parallel's lanes multiplied into N card-widths of canvas.

              `width: fit-content` is min(max-content, max(min-content, available)):
                • max-content ≤ available — the wrapper takes `min-w-full` and nothing wraps,
                  exactly as before.
                • min-content ≤ available < max-content — the wrapper takes the available width,
                  lanes shrink to it and cards wrap. This regime did not exist before.
                • available < min-content — the wrapper takes min-content, which is by
                  construction wide enough for every descendant, so a wide subtree still scrolls
                  the canvas instead of painting outside its box. That is the property `w-max`
                  was chosen for, and it survives. */}
          <div className="w-fit min-w-full">
            <ScopeSwitcher />
            {activeTree.length === 0 && (
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
            {groups[g].params.length > 0
              ? `(${groups[g].params.map((p) => p.name).join(', ')})`
              : ''}
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
    // `min-h-0 flex-1` is what lets an empty list's hint span a taller sibling lane (#3). It is
    // inert in this component's other parents (a loop's body, the canvas root): flex-basis does
    // not apply to a block-level child of a block-level box.
    <div className="flex min-h-0 flex-1 flex-col">
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

/** The three weights a summary is read at (design §3.4): who acts, what happens, everything
 * else. Shared by the card's head and tail spans so the split into two flex items cannot make
 * the same segment render differently on either side of it. */
function segmentSpans(segs: SummarySegment[]) {
  return segs.map((s, i) => (
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
  ))
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
  // The identity run the card keeps on one line, and the detail run it may reflow below it.
  const { head, tail } = splitSummary(blockSummaryParts(node))
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
        // `relative group/card`: the positioning context for the role rail and the action
        // overlay below. The group is NAMED — a bare `group-hover:` matches ANY `.group`
        // ancestor, so an unnamed group here would make a lane's hover light up every card
        // inside it.
        'relative group/card min-w-0 rounded border bg-white text-sm shadow-sm ' +
        cardBorderClass({ kind: node.kind, selected }) + ' ' +
        // A group_ref is a leaf that expands to an entire subtree rendered nowhere on
        // screen (design §3.5) — the edge hatch is the one sanctioned cue for that, paired
        // with pl-1.5 so the header content clears the hatched strip instead of sitting on it.
        (node.kind === 'group_ref' ? 'edge-hatch pl-1.5 ' : '') +
        (selected ? 'ring-2 ring-blue-400 ' : '') +
        (isDragging ? 'opacity-40' : '')
      }
    >
      {/* The device role's colour as a 4px left rail instead of a 10px inline square with a 4px
          gap beside it — 14px of every card's width back, and a colour column you can scan down
          a stack rather than a dot you have to find. Deliberately NOT `border-l-4 border-l-…`:
          `cardBorderClass` SELECTS the card's single border class and replaces it outright on
          selection, so a border-colour override would be the appended-utility cascade fight
          CLAUDE.md forbids. An absolutely-positioned child cannot lose that fight.
          Only `command`/`measure` have a role (useRoleColor), so this never lands on a container,
          and `group_ref`'s `edge-hatch` left edge can never collide with it — a group_ref has no
          role. */}
      {swatch && (
        <span aria-hidden className={`absolute inset-y-0 left-0 w-1 rounded-l ${swatch}`} />
      )}
      <div
        {...listeners}
        {...attributes}
        className={
          // `items-start`, not `items-center`: the row is now allowed to be more than one line
          // tall, and the chevron/icon/badge must sit against the FIRST line rather than float
          // in the middle of a three-line block.
          'flex min-w-0 cursor-grab items-start gap-1 rounded-t py-1 ' +
          // Left padding SELECTED, never appended: 12px when the rail is there so text clears
          // it, the usual 8px otherwise.
          (swatch ? 'pl-3 pr-2 ' : 'px-2 ') +
          headerFillClass(node.kind)
        }
      >
        {/* No placeholder for a leaf. Reserving the chevron's 24px on every leaf card put its
            icon in the same column as a container's chevron, which bought a rhythm nobody asked
            for at the price of 24px of horizontal space on every leaf — and leaves are the
            majority of cards. Leaf content now starts at the card's padding edge. */}
        {isContainer && (
          <IconButton
            icon={collapsed ? ChevronRight : ChevronDown}
            label={collapsed ? 'Expand' : 'Collapse'}
            onClick={(e) => {
              e.stopPropagation()
              toggleCollapsed(node.uid)
            }}
          />
        )}
        {/* h-6 wrappers under `items-start`: a 14px icon and a 16px badge both centre against the
            text cluster's 24px first line instead of hanging off its top edge. IconButton is
            already 24px and needs none. */}
        <span className="flex h-6 shrink-0 items-center">
          <KindIcon kind={node.kind} />
        </span>
        {diags.length > 0 && (
          // The badge used to share the right-hand cluster with Duplicate/Delete. That cluster is
          // now a hover overlay, and an error count that vanishes — or hides behind the overlay —
          // when you reach for the card is the wrong trade, so it moves in-flow to the leading
          // cluster. Side effect worth having: error counts line up down the left of a stack.
          <span className="flex h-6 shrink-0 items-center">
            <span
              title={diags.map((d) => d.message).join('\n')}
              className="rounded-full bg-red-600 px-1.5 text-[10px] font-bold text-white"
            >
              {diags.length}
            </span>
          </span>
        )}
        {/* The wrapping text cluster (design §5.2). `py-0.5` centres its 20px first line against
            the 24px control row beside it, which is what keeps an UNWRAPPED leaf card at exactly
            CHIP_H_PX (8px py-1 + 24px + 2px border = 34px) and PR #83's chip band intact.
            `items-center` and never `items-baseline`: an overflow:hidden box's baseline is its
            bottom margin edge, so `truncate` + baseline alignment misaligns.

            `contain-inline` (index.css) is what makes the whole thing work under a `w-fit`
            canvas: it stops this cluster's text from voting on the canvas's width, so a card can
            never widen the tree — only lane and arm floors can. Its width comes from `flex-1`,
            so it has no need to size itself; its height still tracks the wrapped lines. */}
        <span
          title={blockSummary(node)}
          className="contain-inline flex min-w-0 flex-1 flex-wrap items-center gap-x-1 py-0.5"
        >
          {/* `min-w-0` is what lets this ellipsize instead of overflowing; the CLUSTER's
              `contain-inline` is what stops it widening the canvas. Both are needed and they do
              different jobs — min-width:0 is a layout-time permission to shrink, not a reduction
              of the intrinsic contribution (index.css spells out the 3619px-vs-766px measurement
              that proves it). With containment above, `bioreactor_left_densitometer ·
              read_optical_density` ellipsizes inside whatever width its lane has and contributes
              nothing to the tree's width, which is why the old `max-w-80` cap is gone rather than
              tightened.
              The `title` is repeated HERE and not merely inherited from the cluster because
              probe R2 (truncate-without-title) reads `el.title` on the ellipsising element
              itself, not on an ancestor. */}
          <span title={blockSummary(node)} className="min-w-0 shrink truncate">
            {segmentSpans(head)}
          </span>
          {/* Rendered only when non-empty: an empty flex item still takes its share of `gap-x-1`,
              which would put 4px of dead air after the head of every `wash`-style group_ref.
              `wrap-anywhere` (overflow-wrap: anywhere) is what stops a single unbreakable token —
              a long expression with no spaces — from setting a large min-content size. Unlike
              `break-word` it DOES reduce the intrinsic minimum. */}
          {tail.length > 0 && (
            <span className="min-w-0 wrap-anywhere">{segmentSpans(tail)}</span>
          )}
          {node.label && (
            <span
              title={node.label}
              className="min-w-0 shrink truncate text-xs italic text-caption"
            >
              “{node.label}”
            </span>
          )}
        </span>
      </div>
      {/* Duplicate/Delete float instead of holding 56px of every card's width open. `right-2
          top-1` is exactly where they sat in flow (the header's px-2 / py-1), so nothing moves —
          the space they used to occupy is simply returned to the text.
          Backing is SELECTED, not appended: headerFillClass returns '' for leaves, which are
          bg-white, so the overlay covers whatever it sits on.
          Nothing becomes unreachable: they keep title/aria-label via IconButton, appear on
          keyboard focus, stay lit on the selected card, and Delete/Backspace on a selection
          already removes a block (BuilderTab.tsx). */}
      <span
        className={
          'absolute right-2 top-1 items-center gap-1 rounded pl-1 shadow-sm ' +
          'group-hover/card:flex group-focus-within/card:flex ' +
          (headerFillClass(node.kind) || 'bg-white') + ' ' +
          (selected ? 'flex' : 'hidden')
        }
      >
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
      {/* A parallel supplies its own horizontal air through the lane gutters (laneLayout.ts) —
          its edge drop slot IS the 8px inset — so a `px-2` here would stack a second one on top
          of it and push lane content deeper than every other construct's (comment #5). */}
      <div className={`rounded-b pb-2 ${node.kind === 'parallel' ? '' : 'px-2'} ${fill}`}>
        {body}
      </div>
    </DepthContext.Provider>
  )
}

/** A column OUTSIDE any lane that reproduces a lane's vertical geometry, so its child fills
 * exactly the band a lane's CARDS occupy (#4): the lane's own padding, then the invisible
 * counterpart of the `LANE N` label row, then the band, bracketed by the air a vertical DropSlot
 * puts above and below a card.
 *
 * Two things need it, and neither lives inside a `Lane` so neither inherits any of it: the
 * "+ lane" button, and the lane row's own empty state (a parallel whose lanes have all been
 * deleted), which has no lanes to align with but still has "+ lane" beside it. Expressed as
 * geometry rather than as a hand-tuned `mt-10 mb-4`, so it tracks the tokens in laneLayout.ts. */
function ChipBand({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <div className={`flex flex-col ${LANE_PAD} ` + (className ?? '')}>
      <span aria-hidden className={`shrink-0 ${LANE_LABEL_H}`} />
      <div className={`flex min-h-0 flex-1 items-stretch ${CHIP_GAP}`}>{children}</div>
    </div>
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
      {node.children.map((lane, i) => (
        <Fragment key={lane.uid}>
          {/* The gutter BEFORE lane i, and the row's only horizontal spacing (comment #5): the
              leading one is the row's 8px edge inset, every later one is a 16px gutter carrying
              the centred hairline. Slot indices are unchanged — slot i still inserts before
              lane i — so nothing about the drag targets moves, only their geometry. */}
          <DropSlot
            at={{ parentUid: node.uid, slot: 'children', index: i }}
            horizontal
            hint={false}
            divider={i > 0}
          />
          <Lane lane={lane} index={i} />
        </Fragment>
      ))}
      {node.children.length === 0 ? (
        // No lanes to align with, so the hint borrows the same band "+ lane" beside it uses.
        <ChipBand>
          <DropSlot at={{ parentUid: node.uid, slot: 'children', index: 0 }} horizontal hint />
        </ChipBand>
      ) : (
        // The append slot doubles as the divider that gives "+ lane" a compartment of its own.
        <DropSlot
          at={{ parentUid: node.uid, slot: 'children', index: node.children.length }}
          horizontal
          hint={false}
          divider
        />
      )}
      {/* The band puts this button on the same lines as the lanes' cards (#4) instead of running
          the whole interior height including the `LANE N` label row. Its LEFT air comes from the
          divider gutter before it; `mr-2` gives the row the same 8px right edge the leading slot
          gives it on the left. `stretch` in a flex ROW is full height at content width — this
          button must NOT take a `width`, or it stops fitting its label. */}
      <ChipBand className="mr-2">
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
          className={inlineButtonClass({ subtle: true, stretch: true })}
        >
          <Plus size={12} aria-hidden className="mr-0.5" />lane
        </button>
      </ChipBand>
    </div>
  )
}

/** One lane of a Parallel — feature-equivalent regardless of the child's kind (#1). A `serial`
 * child IS the lane (spec §3.4): its children render directly in the body and this header row is
 * the serial's handle — click selects it, drag moves/reorders it, and its label, fault markers and
 * diagnostics show here. Any other kind is a legacy/imported bare-block lane whose single block
 * renders as a card in the body; the lane header still carries the SAME lane-level select, drag and
 * duplicate, so every lane looks and behaves the same. Delete stays empty-only — a bare-block lane
 * is never empty, so it is removed via its card's ✕ or select+Delete, exactly like a populated
 * serial lane. Lanes separate with a plain slate hairline drawn by ParallelLanes (#10). */
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
  const marker = faultMarker(lane).trim()
  const canDelete = lane.kind === 'serial' && lane.children.length === 0
  // A lane paints no background of its own — it sits on its parallel's interior fill, and the
  // action overlay below has to reproduce that to cover the header it floats over.
  const laneFill = interiorFillClass(useContext(DepthContext))
  return (
    <div
      id={`block-${lane.uid}`}
      ref={setNodeRef}
      onClick={(e) => {
        e.stopPropagation()
        select(lane.uid)
      }}
      className={
        // Selection is the ring alone — same `ring-2 ring-blue-400` as BlockView, with no border
        // for it to compete with. Lane separators live in the gutters (DropSlot), and the lane
        // takes vertical padding only: horizontal padding here would stack on top of the gutter
        // and put this lane's cards deeper than a loop's body (comment #5).
        // `flex flex-col` (#3): the lane must be a column so its BlockList can take the height
        // left over after the label row. Without it the lane stretches to the tallest sibling
        // but its contents do not, and an empty lane's hint has nothing to fill.
        // `relative group/lane`: same overlay treatment as a card (see below), and the same
        // reason for naming the group.
        `relative group/lane flex min-w-48 flex-initial flex-col rounded ${LANE_PAD} ` +
        (selected ? 'ring-2 ring-blue-400 ' : '') +
        (isDragging ? 'opacity-40' : '')
      }
    >
      <div
        {...listeners}
        {...attributes}
        // `contain-inline` for the same reason as a card's text cluster (index.css): the label
        // below is nowrap, and without containment its full text would set this lane's
        // min-content and widen the whole canvas. The row's width comes from the lane's column
        // stretch, so it has no need to size itself.
        className="contain-inline flex h-6 min-w-0 shrink-0 cursor-grab items-center gap-1 px-1 text-[10px] uppercase text-caption"
      >
        <span className="shrink-0">lane {index + 1}</span>
        {diags.length > 0 && (
          // In flow, and ahead of the label, for the same reason as a card's badge: the
          // right-hand cluster is now a hover overlay and an error count must not hide under it.
          <span
            title={diags.map((d) => d.message).join('\n')}
            className="shrink-0 rounded-full bg-red-600 px-1.5 text-[10px] font-bold normal-case text-white"
          >
            {diags.length}
          </span>
        )}
        {lane.label && (
          // `min-w-0` rather than the old `max-w-40`: a flex item with min-width:0 contributes
          // nothing to its container's min-content, so the label cannot widen the lane at all —
          // strictly stronger than the cap it replaces, which existed only because the canvas
          // used to be sized by max-content.
          <span title={lane.label} className="min-w-0 truncate normal-case italic">
            “{lane.label}”
          </span>
        )}
        {marker && <span className="shrink-0 normal-case">{marker}</span>}
      </div>
      {/* The lane's actions float exactly as a card's do. This is not a width fix — a lane header's
          min-content (~100px) is well under the 192px lane floor — it is a consistency and noise
          one: a card that hides its actions inside a lane that does not would read as a bug, and
          three lanes' worth of permanently-lit buttons is real clutter on a dense canvas.
          `right-1 top-1` matches the header's px-1 and the lane's LANE_PAD. A lane has no
          background of its own, so the backing is its parallel's interior fill, read from the
          depth this lane is being rendered at.
          Hovering a card inside a lane also hovers the lane, so both overlays appear — that is
          CSS hover propagation and it is the right behaviour: you are in that lane. */}
      <span
        className={
          'absolute right-1 top-1 items-center gap-1 rounded pl-1 ' +
          'group-hover/lane:flex group-focus-within/lane:flex ' +
          laneFill + ' ' +
          (selected ? 'flex' : 'hidden')
        }
      >
        <IconButton
          icon={Copy}
          label="Duplicate lane"
          onClick={(e) => {
            e.stopPropagation()
            duplicateBlock(lane.uid)
          }}
        />
        {canDelete && (
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
      {lane.kind === 'serial' ? (
        <BlockList parentUid={lane.uid} slot="children" items={lane.children} />
      ) : (
        // A legacy bare-block lane has no BlockList and therefore no drop slots, but it must
        // still present the SAME band as its serial siblings: without this its card sits 12px
        // above theirs in the same row, and "+ lane" — which has no way to know which kind of
        // lane it stands beside — sizes itself against a band that is 24px shorter than the one
        // it was built for (measured: an 18px button, under the 24px hit-area floor).
        <div className={`flex min-h-0 flex-1 flex-col ${CHIP_GAP}`}>
          <BlockView node={lane} />
        </div>
      )}
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
      {/* Arms carry the same LANE_PAD as parallel lanes and are divided by the same hairline at
          the same inset (#5, #10, laneLayout.ts): a Branch and a Parallel at the same depth inset
          their content equally — 8px, like every other construct — and their dividers cover the
          arms' cards without running into the tinted header. The row's `gap-2` already puts 8px
          on each side of the hairline, which is a parallel's 16px gutter by another route. */}
      {/* `flex flex-col` for the same reason a Lane is one (#3): the arm stretches to its
          sibling, and its BlockList has to stretch with it or an empty arm's hint fills nothing. */}
      <div className={`flex min-w-48 flex-initial flex-col ${LANE_PAD}`}>
        <p className="flex h-6 shrink-0 items-center px-1 text-[10px] uppercase text-caption">
          then
        </p>
        <BlockList parentUid={node.uid} slot="then" items={node.then} />
      </div>
      <span aria-hidden className={`w-px self-stretch bg-slate-200 ${LANE_DIVIDER_INSET}`} />
      <div className={`flex min-w-48 flex-initial flex-col ${LANE_PAD}`}>
        {node.else === null ? (
          <>
            <p className="flex h-6 shrink-0 items-center px-1 text-[10px] uppercase text-caption">
              else
            </p>
            {/* The same band the THEN arm's cards occupy (#4). This replaces a hand-copied
                `my-0.5 h-2` spacer whose comment asked the next reader to keep it in sync with
                DropSlot by hand; CHIP_GAP is that sync. */}
            <div className={`flex min-h-0 flex-1 items-stretch ${CHIP_GAP}`}>
              <button
                onClick={(e) => {
                  e.stopPropagation()
                  patchBlock(node.uid, { else: [] })
                }}
                // Same control as the Inspector's "+ add else lane" (Inspector.tsx), and routed
                // through the same helper so a change to the subtle variant reaches both. No
                // `width`: the button fits its label and the band gives it its height.
                className={inlineButtonClass({ subtle: true, stretch: true })}
              >
                <Plus size={12} aria-hidden className="mr-0.5" />add else
              </button>
            </div>
          </>
        ) : (
          <>
            <p className="flex h-6 shrink-0 items-center justify-between px-1 text-[10px] uppercase text-caption">
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
