import { useDroppable } from '@dnd-kit/core'
import { useDocStore } from '../stores/docStore'
import { canDrop, type SlotRef } from './tree'
import { slotDroppableId, type DragPayload } from './dnd'
import { LANE_DIVIDER_INSET, LANE_EDGE_W, LANE_GUTTER_W } from './laneLayout'

/** Insertion bar between blocks (or a dashed hint box for empty lists). Highlights only
 * when the active drag may legally drop here — a container can never enter its own
 * subtree.
 *
 * A horizontal slot is also the parallel row's GUTTER (comment #5): it stopped being an invisible
 * 12px spacer standing beside a separator and became the spacing itself — `LANE_EDGE_W` at the
 * row's ends, `LANE_GUTTER_W` between two lanes with the hairline centred inside it. That is what
 * makes the separator evenly spaced: there is no longer 12px of slot on one side of it and
 * nothing on the other. */
export function DropSlot(props: {
  at: SlotRef
  horizontal: boolean
  hint: boolean
  /** Draw the lane separator centred in this gutter, and widen it to hold two lanes' air. */
  divider?: boolean
}) {
  const { at, horizontal, hint, divider = false } = props
  const { setNodeRef, isOver, active } = useDroppable({ id: slotDroppableId(at) })
  const tree = useDocStore((s) => s.tree)
  const scope = useDocStore((s) => s.scope)
  const payload = (active?.data.current ?? null) as DragPayload | null
  const legal =
    payload !== null && (payload.source !== 'canvas' || canDrop(tree, payload.uid, at))
  const highlight = isOver && legal
  if (hint) {
    return (
      <div
        ref={setNodeRef}
        className={
          'flex-1 rounded border border-dashed px-2 py-3 text-center text-xs ' +
          // A horizontal hint is the empty state of a parallel's lane row, and that row's body no
          // longer has horizontal padding of its own (the gutters supply it), so the hint carries
          // its own 8px. A vertical hint's padding still comes from the parent body.
          (horizontal ? 'mx-2 ' : '') +
          (highlight
            ? // Already opaque (bg-blue-50 fully paints the box), so this branch never
              // needs the hatch backing below regardless of scope.
              'border-blue-400 bg-blue-50 text-blue-500'
            : // Same reasoning as ScopeSwitcher's strip (Canvas.tsx): "drop here" must not
              // sit directly on the canvas hatch, so it goes solid white whenever a group
              // scope is active.
              'border-slate-300 text-caption' + (scope === null ? '' : ' bg-white shadow-sm'))
        }
      >
        drop here
      </div>
    )
  }
  return (
    <div
      ref={setNodeRef}
      className={
        (horizontal
          ? `self-stretch ${divider ? `flex justify-center ${LANE_GUTTER_W}` : LANE_EDGE_W} `
          : 'my-0.5 h-2 ') +
        'shrink-0 rounded transition-colors ' +
        (highlight ? 'bg-blue-400' : isOver ? 'bg-red-200' : 'bg-transparent')
      }
    >
      {divider && !highlight && (
        // The plain slate hairline of #10 (PR #80), same token as the Toolbar's divider. Its
        // MARGINS — not `self-stretch` — decide how far it runs, so it covers the lanes' cards
        // and stops clear of the label row above them.
        <span aria-hidden className={`w-px bg-slate-200 ${LANE_DIVIDER_INSET}`} />
      )}
    </div>
  )
}
