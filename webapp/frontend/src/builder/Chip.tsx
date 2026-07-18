import type { ReactNode } from 'react'
import { useDraggable } from '@dnd-kit/core'
import type { DragPayload } from './dnd'

/** Draggable palette chip (structure kinds and role verbs). Unchanged from its former
 * Palette-local self; it lives alone so Palette and RolesSection can both import it
 * without a component-level cycle. */
export function Chip(props: { id: string; payload: DragPayload; children: ReactNode }) {
  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({
    id: props.id,
    data: props.payload,
  })
  return (
    <div
      ref={setNodeRef}
      {...listeners}
      {...attributes}
      className={
        'flex cursor-grab select-none items-center rounded border border-slate-300 bg-white px-2 py-1 text-xs shadow-sm ' +
        (isDragging ? 'opacity-40' : 'hover:border-slate-400')
      }
    >
      {props.children}
    </div>
  )
}
