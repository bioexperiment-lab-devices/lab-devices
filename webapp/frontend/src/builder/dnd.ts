/** Drag-and-drop wire types. Draggables carry DragPayload in dnd-kit's data; droppables
 * are insertion slots encoded in the droppable id so onDragEnd needs no lookups. */
import type { PaletteKind, SlotRef } from './tree'

export type DragPayload =
  | { source: 'palette-block'; kind: PaletteKind }
  | { source: 'palette-group'; name: string }
  | { source: 'palette-verb'; role: string; verb: string; verbKind: 'command' | 'measure'; deviceType: string }
  | { source: 'canvas'; uid: string }

const ROOT = '~root'

export const slotDroppableId = (at: SlotRef): string =>
  `slot|${at.parentUid ?? ROOT}|${at.slot}|${at.index}`

export function parseSlotDroppableId(id: string): SlotRef | null {
  const parts = id.split('|')
  if (parts.length !== 4 || parts[0] !== 'slot') return null
  const index = Number(parts[3])
  if (!Number.isInteger(index) || index < 0) return null
  return { parentUid: parts[1] === ROOT ? null : parts[1], slot: parts[2], index }
}

export const blockDraggableId = (uid: string): string => `block|${uid}`
