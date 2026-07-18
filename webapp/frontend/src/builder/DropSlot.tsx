import { useDroppable } from '@dnd-kit/core'
import { useDocStore } from '../stores/docStore'
import { canDrop, type SlotRef } from './tree'
import { slotDroppableId, type DragPayload } from './dnd'

/** Insertion bar between blocks (or a dashed hint box for empty lists). Highlights only
 * when the active drag may legally drop here — a container can never enter its own
 * subtree. */
export function DropSlot(props: { at: SlotRef; horizontal: boolean; hint: boolean }) {
  const { at, horizontal, hint } = props
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
          'm-1 flex-1 rounded border border-dashed px-2 py-3 text-center text-xs ' +
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
        (horizontal ? 'mx-0.5 w-2 self-stretch ' : 'my-0.5 h-2 ') +
        'shrink-0 rounded transition-colors ' +
        (highlight ? 'bg-blue-400' : isOver ? 'bg-red-200' : 'bg-transparent')
      }
    />
  )
}
